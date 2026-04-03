"""
LightRAG-backed graph tools service with the same public interface as ZepToolsService.
"""

from typing import List, Optional

from lightrag import QueryParam

from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from .lightrag_backend import (
    create_lightrag,
    finalize_lightrag,
    lightrag_edge_to_dict,
    lightrag_get_all_edges,
    lightrag_get_all_nodes,
    lightrag_node_to_dict,
    lightrag_query_data,
)
from .zep_tools import EdgeInfo, NodeInfo, SearchResult, ZepToolsService


logger = get_logger("mirofish.zep_tools")


class LightRAGToolsService(ZepToolsService):
    """Drop-in replacement for ZepToolsService when GRAPH_BACKEND=lightrag."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        llm_client: Optional[LLMClient] = None,
    ):
        self.api_key = api_key
        self._llm_client = llm_client
        self._rag_cache = {}
        self._current_graph_id: Optional[str] = None
        logger.info("LightRAGToolsService 初始化完成")

    def close(self):
        for rag in self._rag_cache.values():
            finalize_lightrag(rag)
        self._rag_cache.clear()

    def _get_rag(self, graph_id: str):
        self._current_graph_id = graph_id
        rag = self._rag_cache.get(graph_id)
        if rag is None:
            rag = create_lightrag(graph_id)
            self._rag_cache[graph_id] = rag
        return rag

    def _get_current_graph_id(self) -> str:
        if not self._current_graph_id:
            raise ValueError("当前没有可用的 graph_id 上下文")
        return self._current_graph_id

    def search_graph(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
    ) -> SearchResult:
        logger.info(f"图谱搜索: graph_id={graph_id}, query={query[:50]}...")

        rag = self._get_rag(graph_id)
        query_mode = "hybrid"
        if scope == "nodes":
            query_mode = "local"
        elif scope == "edges":
            query_mode = "global"

        try:
            raw_result = lightrag_query_data(
                rag,
                query,
                param=QueryParam(mode=query_mode, top_k=max(limit, 5)),
            )
            data = raw_result.get("data", {}) if isinstance(raw_result, dict) else {}

            entities = data.get("entities", []) or []
            relations = data.get("relationships", []) or []

            nodes_result = [
                {
                    "uuid": str(entity.get("entity_name", "")),
                    "name": entity.get("entity_name", ""),
                    "labels": ["Entity", entity.get("entity_type", "")]
                    if entity.get("entity_type")
                    else ["Entity"],
                    "summary": entity.get("description", "") or "",
                    "attributes": {
                        "entity_type": entity.get("entity_type", "") or "",
                        "source_id": entity.get("source_id", "") or "",
                        "file_path": entity.get("file_path", "") or "",
                        "reference_id": entity.get("reference_id", "") or "",
                    },
                }
                for entity in entities[:limit]
            ]

            edges_result = [
                {
                    "uuid": f"{rel.get('src_id', '')}->{rel.get('tgt_id', '')}",
                    "name": rel.get("keywords", "") or "related",
                    "fact": rel.get("description", "") or "",
                    "source_node_uuid": rel.get("src_id", "") or "",
                    "target_node_uuid": rel.get("tgt_id", "") or "",
                    "source_node_name": rel.get("src_id", "") or "",
                    "target_node_name": rel.get("tgt_id", "") or "",
                    "attributes": {
                        "weight": rel.get("weight", 1.0),
                        "source_id": rel.get("source_id", "") or "",
                        "file_path": rel.get("file_path", "") or "",
                        "reference_id": rel.get("reference_id", "") or "",
                    },
                    "created_at": rel.get("created_at"),
                    "valid_at": rel.get("valid_at"),
                    "invalid_at": rel.get("invalid_at"),
                    "expired_at": rel.get("expired_at"),
                }
                for rel in relations[:limit]
            ]

            if scope == "nodes":
                facts = [node["summary"] for node in nodes_result if node.get("summary")]
            else:
                facts = [edge["fact"] for edge in edges_result if edge.get("fact")]
                if not facts:
                    facts = [node["summary"] for node in nodes_result if node.get("summary")]

            return SearchResult(
                facts=facts[:limit],
                edges=edges_result if scope != "nodes" else [],
                nodes=nodes_result,
                query=query,
                total_count=len(facts[:limit]),
            )
        except Exception as exc:
            logger.warning(f"LightRAG 检索失败，降级为本地搜索: {exc}")
            return self._local_search(graph_id, query, limit, scope)

    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        rag = self._get_rag(graph_id)
        raw_nodes = lightrag_get_all_nodes(rag)
        result = []
        for node in raw_nodes:
            node_data = lightrag_node_to_dict(node)
            result.append(
                NodeInfo(
                    uuid=node_data["uuid"],
                    name=node_data["name"],
                    labels=node_data["labels"],
                    summary=node_data["summary"],
                    attributes=node_data["attributes"],
                )
            )
        return result

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        rag = self._get_rag(graph_id)
        raw_edges = lightrag_get_all_edges(rag)
        result = []
        for edge in raw_edges:
            edge_data = lightrag_edge_to_dict(edge)
            edge_info = EdgeInfo(
                uuid=edge_data["uuid"],
                name=edge_data["name"],
                fact=edge_data["fact"],
                source_node_uuid=edge_data["source_node_uuid"],
                target_node_uuid=edge_data["target_node_uuid"],
                source_node_name=edge_data["source_node_name"],
                target_node_name=edge_data["target_node_name"],
            )
            if include_temporal:
                edge_info.created_at = edge_data.get("created_at")
                edge_info.valid_at = edge_data.get("valid_at")
                edge_info.invalid_at = edge_data.get("invalid_at")
                edge_info.expired_at = edge_data.get("expired_at")
            result.append(edge_info)
        return result

    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        graph_id = self._get_current_graph_id()
        for node in self.get_all_nodes(graph_id):
            if node.uuid == node_uuid or node.name == node_uuid:
                return node
        return None

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        related_edges = []
        for edge in self.get_all_edges(graph_id):
            if edge.source_node_uuid == node_uuid or edge.target_node_uuid == node_uuid:
                related_edges.append(edge)
        return related_edges

    def __del__(self):
        self.close()
