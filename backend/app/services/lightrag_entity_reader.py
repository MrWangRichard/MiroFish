"""
LightRAG entity reader compatible with the ZepEntityReader interface.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..utils.logger import get_logger
from .lightrag_backend import (
    create_lightrag,
    finalize_lightrag,
    lightrag_count_edges,
    lightrag_count_nodes,
    lightrag_edge_to_dict,
    lightrag_get_all_edges,
    lightrag_get_all_nodes,
    lightrag_get_edges_batch,
    lightrag_get_edges_for_pairs,
    lightrag_get_node,
    lightrag_get_node_degrees_batch,
    lightrag_get_node_edges,
    lightrag_get_nodes_batch,
    lightrag_get_nodes_edges_batch,
    lightrag_get_popular_labels,
    lightrag_node_to_dict,
    lightrag_search_labels,
)
from .zep_entity_reader import EntityNode, ZepEntityReader


logger = get_logger("mirofish.lightrag_entity_reader")


class LightRAGEntityReader(ZepEntityReader):
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self._rag_cache = {}
        self._current_graph_id: Optional[str] = None

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

    def _get_storage(self, graph_id: str):
        return self._get_rag(graph_id).chunk_entity_relation_graph

    def _storage_supports(self, graph_id: str, *method_names: str) -> bool:
        storage = self._get_storage(graph_id)
        return all(callable(getattr(storage, name, None)) for name in method_names)

    @staticmethod
    def _entity_type_from_labels(labels: Sequence[str]) -> str:
        for label in labels or []:
            if label not in ["Entity", "Node"]:
                return label
        return "Entity"

    @classmethod
    def _entity_option_from_node(cls, node: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "uuid": node.get("uuid", ""),
            "name": node.get("name", "") or "",
            "labels": node.get("labels", []) or [],
            "entity_type": cls._entity_type_from_labels(node.get("labels", []) or []),
        }

    @staticmethod
    def _ordered_unique_ids(node_ids: Iterable[str]) -> List[str]:
        ordered = []
        seen = set()
        for node_id in node_ids:
            value = (node_id or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    def supports_graph_neighborhood_queries(self, graph_id: str) -> bool:
        return self._storage_supports(
            graph_id,
            "get_node",
            "get_nodes_batch",
            "get_nodes_edges_batch",
            "get_edges_batch",
            "node_degrees_batch",
        )

    def supports_graph_search(self, graph_id: str) -> bool:
        return self._storage_supports(graph_id, "get_popular_labels", "search_labels")

    def get_graph_stats(self, graph_id: str) -> Dict[str, int]:
        rag = self._get_rag(graph_id)

        try:
            return {
                "node_count": lightrag_count_nodes(rag),
                "edge_count": lightrag_count_edges(rag),
            }
        except Exception as exc:
            logger.warning(f"Falling back to full graph scan for LightRAG stats: {exc}")
            nodes = self.get_all_nodes(graph_id)
            edges = self.get_all_edges(graph_id)
            return {
                "node_count": len(nodes),
                "edge_count": len(edges),
            }

    def get_node_by_uuid(
        self,
        graph_id: str,
        entity_uuid: str,
    ) -> Optional[Dict[str, Any]]:
        rag = self._get_rag(graph_id)
        raw_node = lightrag_get_node(rag, entity_uuid)
        if raw_node:
            return lightrag_node_to_dict(raw_node)

        query = (entity_uuid or "").strip()
        if not query:
            return None

        if self.supports_graph_search(graph_id):
            labels = lightrag_search_labels(rag, query, limit=5)
            for label in labels:
                if label == query:
                    exact_node = lightrag_get_node(rag, label)
                    if exact_node:
                        return lightrag_node_to_dict(exact_node)

        return None

    def get_nodes_by_uuids(
        self,
        graph_id: str,
        node_uuids: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        ordered_ids = self._ordered_unique_ids(node_uuids)
        if not ordered_ids:
            return {}

        rag = self._get_rag(graph_id)
        raw_nodes = lightrag_get_nodes_batch(rag, ordered_ids)
        return {
            node_id: lightrag_node_to_dict(raw_node)
            for node_id, raw_node in (raw_nodes or {}).items()
            if raw_node
        }

    def get_node_degrees(
        self,
        graph_id: str,
        node_uuids: Sequence[str],
    ) -> Dict[str, int]:
        ordered_ids = self._ordered_unique_ids(node_uuids)
        if not ordered_ids:
            return {}

        rag = self._get_rag(graph_id)
        return lightrag_get_node_degrees_batch(rag, ordered_ids)

    def get_nodes_edges_batch(
        self,
        graph_id: str,
        node_uuids: Sequence[str],
    ) -> Dict[str, List[tuple[str, str]]]:
        ordered_ids = self._ordered_unique_ids(node_uuids)
        if not ordered_ids:
            return {}

        rag = self._get_rag(graph_id)
        return lightrag_get_nodes_edges_batch(rag, ordered_ids)

    def get_edge_details_batch(
        self,
        graph_id: str,
        pairs: Sequence[tuple[str, str]],
    ) -> Dict[tuple[str, str], List[Dict[str, Any]]]:
        normalized_pairs = []
        seen = set()

        for source_uuid, target_uuid in pairs:
            source = (source_uuid or "").strip()
            target = (target_uuid or "").strip()
            if not source or not target:
                continue
            key = (source, target)
            if key in seen:
                continue
            seen.add(key)
            normalized_pairs.append({"src": source, "tgt": target})

        if not normalized_pairs:
            return {}

        rag = self._get_rag(graph_id)
        result: Dict[tuple[str, str], List[Dict[str, Any]]] = {}

        try:
            raw_edges = lightrag_get_edges_for_pairs(rag, normalized_pairs)
            for raw_edge in raw_edges or []:
                pair_key = (raw_edge.get("pair_src", ""), raw_edge.get("pair_tgt", ""))
                if not pair_key[0] or not pair_key[1]:
                    continue

                edge_input = dict(raw_edge.get("properties", {}) or {})
                edge_input["source"] = raw_edge.get("source") or pair_key[0]
                edge_input["target"] = raw_edge.get("target") or pair_key[1]

                edge = lightrag_edge_to_dict(edge_input)
                edge["fact_type"] = edge["name"]
                edge["episodes"] = []

                bucket = result.setdefault(pair_key, [])
                edge_index = len(bucket)
                edge["uuid"] = f"{edge['source_node_uuid']}->{edge['target_node_uuid']}:{edge['name']}:{edge_index}"
                bucket.append(edge)

            if result:
                return result
        except Exception as exc:
            logger.warning(f"Falling back to single-edge pair lookup for LightRAG: {exc}")

        raw_edges = lightrag_get_edges_batch(rag, normalized_pairs)

        for (source_uuid, target_uuid), raw_edge in (raw_edges or {}).items():
            edge_input = dict(raw_edge or {})
            edge_input["source"] = source_uuid
            edge_input["target"] = target_uuid
            edge = lightrag_edge_to_dict(edge_input)
            edge["fact_type"] = edge["name"]
            edge["episodes"] = []
            edge["uuid"] = f"{edge['source_node_uuid']}->{edge['target_node_uuid']}:{edge['name']}:0"
            result[(source_uuid, target_uuid)] = [edge]

        return result

    def get_popular_entities(
        self,
        graph_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        rag = self._get_rag(graph_id)

        if not self.supports_graph_search(graph_id):
            return [
                self._entity_option_from_node(node)
                for node in self.get_all_nodes(graph_id)[:limit]
            ]

        labels = lightrag_get_popular_labels(rag, limit=limit)
        node_map = self.get_nodes_by_uuids(graph_id, labels)

        entities = []
        for label in labels:
            node = node_map.get(label)
            if node:
                entities.append(self._entity_option_from_node(node))
        return entities

    def search_entities(
        self,
        graph_id: str,
        query: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        trimmed_query = (query or "").strip()
        if not trimmed_query:
            return self.get_popular_entities(graph_id, limit=limit)

        if not self.supports_graph_search(graph_id):
            normalized_query = trimmed_query.lower()
            candidates = [
                self._entity_option_from_node(node)
                for node in self.get_all_nodes(graph_id)
            ]
            exact_uuid = []
            exact_name = []
            prefix_matches = []
            contains_matches = []

            for candidate in candidates:
                uuid_value = candidate["uuid"].lower()
                name_value = candidate["name"].lower()
                if uuid_value == normalized_query:
                    exact_uuid.append(candidate)
                elif name_value == normalized_query:
                    exact_name.append(candidate)
                elif uuid_value.startswith(normalized_query) or name_value.startswith(normalized_query):
                    prefix_matches.append(candidate)
                elif normalized_query in uuid_value or normalized_query in name_value:
                    contains_matches.append(candidate)

            ordered = []
            seen = set()
            for candidate in exact_uuid + exact_name + prefix_matches + contains_matches:
                uuid_value = candidate.get("uuid")
                if not uuid_value or uuid_value in seen:
                    continue
                seen.add(uuid_value)
                ordered.append(candidate)
            return ordered[:limit]

        rag = self._get_rag(graph_id)
        labels = lightrag_search_labels(rag, trimmed_query, limit=limit)
        if trimmed_query not in labels:
            raw_node = lightrag_get_node(rag, trimmed_query)
            if raw_node:
                labels.insert(0, trimmed_query)

        ordered_ids = self._ordered_unique_ids(labels)
        node_map = self.get_nodes_by_uuids(graph_id, ordered_ids)

        entities = []
        for label in ordered_ids:
            node = node_map.get(label)
            if node:
                entities.append(self._entity_option_from_node(node))
        return entities[:limit]

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        rag = self._get_rag(graph_id)
        raw_nodes = lightrag_get_all_nodes(rag)
        return [lightrag_node_to_dict(node) for node in raw_nodes]

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        rag = self._get_rag(graph_id)
        raw_edges = lightrag_get_all_edges(rag)
        return [lightrag_edge_to_dict(edge) for edge in raw_edges]

    def get_node_edges(self, node_uuid: str) -> List[Dict[str, Any]]:
        if not self._current_graph_id:
            return []

        rag = self._get_rag(self._current_graph_id)
        raw_pairs = lightrag_get_node_edges(rag, node_uuid) or []
        edge_map = self.get_edge_details_batch(self._current_graph_id, raw_pairs)
        edges = []
        for pair in raw_pairs:
            edges.extend(edge_map.get(pair, []))
        return edges

    def get_entity_with_context(
        self,
        graph_id: str,
        entity_uuid: str,
    ) -> Optional[EntityNode]:
        node = self.get_node_by_uuid(graph_id, entity_uuid)
        if node is None:
            return None

        adjacency_map = self.get_nodes_edges_batch(graph_id, [node["uuid"]])
        edge_pairs = adjacency_map.get(node["uuid"], []) or []
        edge_map = self.get_edge_details_batch(graph_id, edge_pairs)

        related_edges = []
        related_node_ids = []

        for source_uuid, target_uuid in edge_pairs:
            edges = edge_map.get((source_uuid, target_uuid), [])
            if not edges:
                continue

            for edge in edges:
                if source_uuid == node["uuid"]:
                    related_edges.append(
                        {
                            "uuid": edge.get("uuid"),
                            "direction": "outgoing",
                            "edge_name": edge["name"],
                            "fact": edge.get("fact", "") or "",
                            "fact_type": edge.get("fact_type") or edge["name"],
                            "target_node_uuid": target_uuid,
                            "attributes": edge.get("attributes", {}) or {},
                            "created_at": edge.get("created_at"),
                            "valid_at": edge.get("valid_at"),
                            "invalid_at": edge.get("invalid_at"),
                            "expired_at": edge.get("expired_at"),
                            "episodes": edge.get("episodes", []) or [],
                        }
                    )
                    related_node_ids.append(target_uuid)
                else:
                    related_edges.append(
                        {
                            "uuid": edge.get("uuid"),
                            "direction": "incoming",
                            "edge_name": edge["name"],
                            "fact": edge.get("fact", "") or "",
                            "fact_type": edge.get("fact_type") or edge["name"],
                            "source_node_uuid": source_uuid,
                            "attributes": edge.get("attributes", {}) or {},
                            "created_at": edge.get("created_at"),
                            "valid_at": edge.get("valid_at"),
                            "invalid_at": edge.get("invalid_at"),
                            "expired_at": edge.get("expired_at"),
                            "episodes": edge.get("episodes", []) or [],
                        }
                    )
                    related_node_ids.append(source_uuid)

        related_node_map = self.get_nodes_by_uuids(graph_id, related_node_ids)
        related_nodes = []
        for related_uuid in self._ordered_unique_ids(related_node_ids):
            related_node = related_node_map.get(related_uuid)
            if not related_node:
                continue
            related_nodes.append(
                {
                    "uuid": related_node["uuid"],
                    "name": related_node["name"],
                    "labels": related_node["labels"],
                    "summary": related_node.get("summary", ""),
                    "attributes": related_node.get("attributes", {}) or {},
                    "created_at": related_node.get("created_at"),
                }
            )

        return EntityNode(
            uuid=node["uuid"],
            name=node["name"],
            labels=node["labels"],
            summary=node["summary"],
            attributes=node["attributes"],
            related_edges=related_edges,
            related_nodes=related_nodes,
        )

    def __del__(self):
        self.close()
