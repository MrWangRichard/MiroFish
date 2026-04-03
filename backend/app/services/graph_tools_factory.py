"""
Factory for graph retrieval and analysis tools.
"""

from ..config import Config


def create_graph_tools_service(api_key: str = None, llm_client=None):
    backend = Config.GRAPH_BACKEND.lower()

    if backend == "zep":
        from .zep_tools import ZepToolsService

        return ZepToolsService(api_key=api_key, llm_client=llm_client)

    if backend == "lightrag":
        from .lightrag_tools import LightRAGToolsService

        return LightRAGToolsService(api_key=api_key, llm_client=llm_client)

    raise ValueError(
        f"无效的 GRAPH_BACKEND 配置: '{backend}'，有效值: 'zep' | 'lightrag'"
    )


def get_backend_name() -> str:
    return Config.GRAPH_BACKEND
