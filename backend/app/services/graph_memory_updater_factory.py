"""
Factory helpers for runtime graph memory updaters.
"""

from ..config import Config


def create_graph_memory_updater(simulation_id: str, graph_id: str):
    backend = Config.GRAPH_BACKEND.lower()

    if backend == "zep":
        from .zep_graph_memory_updater import ZepGraphMemoryManager

        return ZepGraphMemoryManager.create_updater(simulation_id, graph_id)

    if backend == "lightrag":
        from .lightrag_graph_memory_updater import LightRAGGraphMemoryManager

        return LightRAGGraphMemoryManager.create_updater(simulation_id, graph_id)

    raise ValueError(
        f"无效的 GRAPH_BACKEND 配置: '{backend}'，有效值: 'zep' | 'lightrag'"
    )


def get_graph_memory_updater(simulation_id: str):
    backend = Config.GRAPH_BACKEND.lower()

    if backend == "zep":
        from .zep_graph_memory_updater import ZepGraphMemoryManager

        return ZepGraphMemoryManager.get_updater(simulation_id)

    if backend == "lightrag":
        from .lightrag_graph_memory_updater import LightRAGGraphMemoryManager

        return LightRAGGraphMemoryManager.get_updater(simulation_id)

    return None


def stop_graph_memory_updater(simulation_id: str):
    backend = Config.GRAPH_BACKEND.lower()

    if backend == "zep":
        from .zep_graph_memory_updater import ZepGraphMemoryManager

        return ZepGraphMemoryManager.stop_updater(simulation_id)

    if backend == "lightrag":
        from .lightrag_graph_memory_updater import LightRAGGraphMemoryManager

        return LightRAGGraphMemoryManager.stop_updater(simulation_id)


def stop_all_graph_memory_updaters():
    backend = Config.GRAPH_BACKEND.lower()

    if backend == "zep":
        from .zep_graph_memory_updater import ZepGraphMemoryManager

        return ZepGraphMemoryManager.stop_all()

    if backend == "lightrag":
        from .lightrag_graph_memory_updater import LightRAGGraphMemoryManager

        return LightRAGGraphMemoryManager.stop_all()
