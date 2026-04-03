"""
LightRAG-backed graph builder.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from lightrag import QueryParam

from ..models.task import TaskManager
from ..utils.logger import get_logger
from .lightrag_backend import (
    create_lightrag,
    drop_lightrag_graph,
    finalize_lightrag,
    lightrag_edge_to_dict,
    lightrag_get_all_edges,
    lightrag_get_all_nodes,
    lightrag_get_entity_info,
    lightrag_get_relation_info,
    lightrag_insert,
    lightrag_node_to_dict,
    lightrag_query,
)


logger = get_logger("mirofish.graph_builder")


@dataclass
class GraphInfo:
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
        }


class GraphBuilderService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.task_manager = TaskManager()
        self._rag = None
        self._graph_id: Optional[str] = None
        self._graph_name: Optional[str] = None
        self._ontology: Optional[Dict[str, Any]] = None
        logger.info("GraphBuilderService (LightRAG 版本) 初始化完成")

    def _ensure_initialized(self):
        if self._graph_id is None:
            raise ValueError("LightRAG graph_id 尚未初始化")
        if self._rag is None:
            self._rag = create_lightrag(self._graph_id, ontology=self._ontology)

    def create_graph(self, name: str) -> str:
        self._graph_id = f"lightrag_{uuid.uuid4().hex[:8]}"
        self._graph_name = name or "MiroFish Graph"
        logger.info(f"创建图谱: {self._graph_name}, graph_id={self._graph_id}")
        return self._graph_id

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        self._graph_id = graph_id
        self._ontology = ontology
        logger.info(f"保存图谱本体: graph_id={graph_id}")

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None,
    ) -> List[str]:
        self._graph_id = graph_id
        self._ensure_initialized()

        total_chunks = len(chunks)
        chunk_ids = [f"chunk_{index}" for index in range(total_chunks)]

        for batch_start in range(0, total_chunks, batch_size):
            batch = chunks[batch_start : batch_start + batch_size]
            batch_end = min(batch_start + batch_size, total_chunks)
            lightrag_insert(self._rag, batch)

            if progress_callback:
                progress_callback(
                    f"已插入 {batch_end}/{total_chunks} 个文本块",
                    batch_end / max(total_chunks, 1),
                )

        logger.info(f"LightRAG 文本插入完成: graph_id={graph_id}, chunks={total_chunks}")
        return chunk_ids

    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600,
    ):
        if progress_callback:
            progress_callback("LightRAG 处理完成", 1.0)
        logger.info("LightRAG 数据处理完成")

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        self._graph_id = graph_id
        self._ensure_initialized()

        raw_nodes = lightrag_get_all_nodes(self._rag)
        raw_edges = lightrag_get_all_edges(self._rag)

        nodes = []
        for node in raw_nodes:
            node_data = lightrag_node_to_dict(node)
            nodes.append(
                {
                    "uuid": node_data["uuid"],
                    "name": node_data["name"],
                    "labels": node_data["labels"],
                    "summary": node_data["summary"],
                    "attributes": node_data["attributes"],
                    "created_at": node_data.get("created_at"),
                }
            )

        edges = []
        for edge in raw_edges:
            edge_data = lightrag_edge_to_dict(edge)
            edges.append(
                {
                    "uuid": edge_data["uuid"],
                    "name": edge_data["name"],
                    "fact": edge_data["fact"],
                    "fact_type": edge_data["name"],
                    "source_node_uuid": edge_data["source_node_uuid"],
                    "target_node_uuid": edge_data["target_node_uuid"],
                    "source_node_name": edge_data["source_node_name"],
                    "target_node_name": edge_data["target_node_name"],
                    "attributes": edge_data["attributes"],
                    "created_at": edge_data.get("created_at"),
                    "valid_at": edge_data.get("valid_at"),
                    "invalid_at": edge_data.get("invalid_at"),
                    "expired_at": edge_data.get("expired_at"),
                    "episodes": [],
                }
            )

        return {
            "graph_id": graph_id,
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    def delete_graph(self, graph_id: str):
        logger.info(f"删除 LightRAG 图谱: graph_id={graph_id}")
        drop_lightrag_graph(graph_id, rag=self._rag if self._graph_id == graph_id else None)
        self._rag = None
        if self._graph_id == graph_id:
            self._graph_id = None
            self._ontology = None
            self._graph_name = None

    def query(
        self,
        question: str,
        mode: str = "hybrid",
        top_k: int = 60,
        enable_rerank: bool = True,
    ) -> str:
        self._ensure_initialized()
        return lightrag_query(
            self._rag,
            question,
            param=QueryParam(mode=mode, top_k=top_k, enable_rerank=enable_rerank),
        )

    def get_entity(self, entity_name: str) -> Optional[Dict[str, Any]]:
        self._ensure_initialized()
        try:
            return lightrag_get_entity_info(self._rag, entity_name)
        except Exception as exc:
            logger.error(f"获取 LightRAG 实体失败: {exc}")
            return None

    def get_relation(self, source: str, target: str) -> Optional[Dict[str, Any]]:
        self._ensure_initialized()
        try:
            return lightrag_get_relation_info(self._rag, source, target)
        except Exception as exc:
            logger.error(f"获取 LightRAG 关系失败: {exc}")
            return None

    def __del__(self):
        finalize_lightrag(self._rag)
