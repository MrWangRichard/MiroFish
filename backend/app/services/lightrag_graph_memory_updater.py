"""
Runtime graph memory updater backed by LightRAG.
"""

import threading
import time
from datetime import datetime
from queue import Empty, Queue
from typing import Any, Dict, List, Optional

from .lightrag_backend import create_lightrag, finalize_lightrag, lightrag_insert
from .zep_graph_memory_updater import AgentActivity
from ..utils.logger import get_logger


logger = get_logger("mirofish.graph_memory_updater")


class LightRAGGraphMemoryUpdater:
    BATCH_SIZE = 5
    SEND_INTERVAL = 0.5
    MAX_RETRIES = 3
    RETRY_DELAY = 2

    PLATFORM_DISPLAY_NAMES = {
        "twitter": "世界1",
        "reddit": "世界2",
    }

    def __init__(self, graph_id: str, api_key: Optional[str] = None):
        self.graph_id = graph_id
        self.api_key = api_key
        self._rag = create_lightrag(graph_id)
        self._activity_queue: Queue = Queue()
        self._platform_buffers: Dict[str, List[AgentActivity]] = {
            "twitter": [],
            "reddit": [],
        }
        self._buffer_lock = threading.Lock()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._total_activities = 0
        self._total_sent = 0
        self._total_items_sent = 0
        self._failed_count = 0
        self._skipped_count = 0
        logger.info(
            f"LightRAGGraphMemoryUpdater 初始化完成: graph_id={graph_id}, batch_size={self.BATCH_SIZE}"
        )

    def _get_platform_display_name(self, platform: str) -> str:
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)

    def start(self):
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name=f"LightRAGMemoryUpdater-{self.graph_id[:8]}",
        )
        self._worker_thread.start()
        logger.info(f"LightRAGGraphMemoryUpdater 已启动: graph_id={self.graph_id}")

    def stop(self):
        self._running = False
        self._flush_remaining()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)

        finalize_lightrag(self._rag)
        logger.info(
            f"LightRAGGraphMemoryUpdater 已停止: graph_id={self.graph_id}, "
            f"total_activities={self._total_activities}, "
            f"batches_sent={self._total_sent}, "
            f"items_sent={self._total_items_sent}, "
            f"failed={self._failed_count}, "
            f"skipped={self._skipped_count}"
        )

    def add_activity(self, activity: AgentActivity):
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return

        self._activity_queue.put(activity)
        self._total_activities += 1
        logger.debug(f"添加活动到 LightRAG 队列: {activity.agent_name} - {activity.action_type}")

    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        if "event_type" in data:
            return

        activity = AgentActivity(
            platform=platform,
            agent_id=data.get("agent_id", 0),
            agent_name=data.get("agent_name", ""),
            action_type=data.get("action_type", ""),
            action_args=data.get("action_args", {}),
            round_num=data.get("round", 0),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )
        self.add_activity(activity)

    def _worker_loop(self):
        while self._running or not self._activity_queue.empty():
            try:
                try:
                    activity = self._activity_queue.get(timeout=1)
                    platform = activity.platform.lower()
                    with self._buffer_lock:
                        if platform not in self._platform_buffers:
                            self._platform_buffers[platform] = []
                        self._platform_buffers[platform].append(activity)

                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][: self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE :]
                            self._send_batch_activities(batch, platform)
                            time.sleep(self.SEND_INTERVAL)
                except Empty:
                    pass
            except Exception as exc:
                logger.error(f"LightRAG 图谱记忆更新循环异常: {exc}")
                time.sleep(1)

    def _send_batch_activities(self, activities: List[AgentActivity], platform: str):
        if not activities:
            return

        episode_texts = [activity.to_episode_text() for activity in activities]

        for attempt in range(self.MAX_RETRIES):
            try:
                lightrag_insert(self._rag, episode_texts)
                self._total_sent += 1
                self._total_items_sent += len(activities)
                display_name = self._get_platform_display_name(platform)
                logger.info(
                    f"成功批量写入 {len(activities)} 条{display_name}活动到 LightRAG 图谱 {self.graph_id}"
                )
                return
            except Exception as exc:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(
                        f"批量写入 LightRAG 失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {exc}"
                    )
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"批量写入 LightRAG 失败，已重试{self.MAX_RETRIES}次: {exc}")
                    self._failed_count += 1

    def _flush_remaining(self):
        while not self._activity_queue.empty():
            try:
                activity = self._activity_queue.get_nowait()
                platform = activity.platform.lower()
                with self._buffer_lock:
                    if platform not in self._platform_buffers:
                        self._platform_buffers[platform] = []
                    self._platform_buffers[platform].append(activity)
            except Empty:
                break

        with self._buffer_lock:
            for platform, buffer in self._platform_buffers.items():
                if buffer:
                    logger.info(
                        f"发送{self._get_platform_display_name(platform)}平台剩余的 {len(buffer)} 条活动"
                    )
                    self._send_batch_activities(buffer, platform)
            for platform in self._platform_buffers:
                self._platform_buffers[platform] = []

    def get_stats(self) -> Dict[str, Any]:
        with self._buffer_lock:
            buffer_sizes = {p: len(b) for p, b in self._platform_buffers.items()}

        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,
            "batches_sent": self._total_sent,
            "items_sent": self._total_items_sent,
            "failed_count": self._failed_count,
            "skipped_count": self._skipped_count,
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,
            "running": self._running,
        }


class LightRAGGraphMemoryManager:
    _updaters: Dict[str, LightRAGGraphMemoryUpdater] = {}
    _lock = threading.Lock()
    _stop_all_done = False

    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> LightRAGGraphMemoryUpdater:
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()

            updater = LightRAGGraphMemoryUpdater(graph_id)
            updater.start()
            cls._updaters[simulation_id] = updater
            logger.info(f"创建 LightRAG 图谱记忆更新器: simulation_id={simulation_id}, graph_id={graph_id}")
            return updater

    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[LightRAGGraphMemoryUpdater]:
        return cls._updaters.get(simulation_id)

    @classmethod
    def stop_updater(cls, simulation_id: str):
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
                del cls._updaters[simulation_id]
                logger.info(f"已停止 LightRAG 图谱记忆更新器: simulation_id={simulation_id}")

    @classmethod
    def stop_all(cls):
        if cls._stop_all_done:
            return
        cls._stop_all_done = True

        with cls._lock:
            for simulation_id, updater in list(cls._updaters.items()):
                try:
                    updater.stop()
                except Exception as exc:
                    logger.error(f"停止 LightRAG 更新器失败: simulation_id={simulation_id}, error={exc}")
            cls._updaters.clear()

    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        return {
            sim_id: updater.get_stats()
            for sim_id, updater in cls._updaters.items()
        }
