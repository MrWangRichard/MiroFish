"""
Graph view service for limited graph rendering and focused entity subgraphs.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence

from ..config import Config
from ..utils.logger import get_logger
from .graph_builder_factory import create_graph_builder
from .zep_reader_factory import create_entity_reader


logger = get_logger("mirofish.graph_view_service")

DEFAULT_HOP_LIMIT = 20
DEFAULT_TOTAL_NODE_LIMIT = 150


def _close_resource(resource) -> None:
    close_fn = getattr(resource, "close", None)
    if callable(close_fn):
        close_fn()


class GraphViewService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY

    def _get_full_graph_data(self, graph_id: str) -> Dict[str, Any]:
        builder = create_graph_builder(api_key=self.api_key)
        return builder.get_graph_data(graph_id)

    def _create_reader(self):
        return create_entity_reader(api_key=self.api_key)

    @staticmethod
    def _entity_type_from_labels(labels: List[str]) -> str:
        for label in labels or []:
            if label not in ["Entity", "Node"]:
                return label
        return "Entity"

    @staticmethod
    def _dedupe_entities(entities: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        result = []

        for entity in entities:
            uuid = entity.get("uuid")
            if not uuid or uuid in seen:
                continue
            seen.add(uuid)
            result.append(entity)

        return result

    @staticmethod
    def _ordered_unique_ids(values: Sequence[str]) -> List[str]:
        seen = set()
        result = []

        for value in values:
            item = (value or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            result.append(item)

        return result

    @staticmethod
    def _build_response(
        graph_id: str,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        total_node_count: int,
        total_edge_count: int,
        view_mode: str,
        focus_node_uuid: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "graph_id": graph_id,
            "nodes": nodes,
            "edges": edges,
            "node_count": total_node_count,
            "edge_count": total_edge_count,
            "display_node_count": len(nodes),
            "display_edge_count": len(edges),
            "view_mode": view_mode,
            "focus_node_uuid": focus_node_uuid,
        }

    @staticmethod
    def _reader_supports(reader, method_name: str) -> bool:
        return callable(getattr(reader, method_name, None))

    def _reader_supports_search(self, reader, graph_id: str) -> bool:
        supports = getattr(reader, "supports_graph_search", None)
        if callable(supports):
            try:
                return bool(supports(graph_id))
            except Exception as exc:
                logger.warning(f"Failed to check optimized graph search support: {exc}")
        return False

    def _reader_supports_neighborhood(self, reader, graph_id: str) -> bool:
        supports = getattr(reader, "supports_graph_neighborhood_queries", None)
        if callable(supports):
            try:
                return bool(supports(graph_id))
            except Exception as exc:
                logger.warning(f"Failed to check optimized graph neighborhood support: {exc}")
        return False

    def _get_graph_stats(
        self,
        graph_id: str,
        reader=None,
        full_graph_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, int]:
        if reader is not None and self._reader_supports(reader, "get_graph_stats"):
            try:
                stats = reader.get_graph_stats(graph_id)
                if stats:
                    return {
                        "node_count": int(stats.get("node_count", 0)),
                        "edge_count": int(stats.get("edge_count", 0)),
                    }
            except Exception as exc:
                logger.warning(f"Failed to load graph stats through reader: {exc}")

        if full_graph_data is None:
            full_graph_data = self._get_full_graph_data(graph_id)

        return {
            "node_count": int(full_graph_data.get("node_count", len(full_graph_data.get("nodes", []) or []))),
            "edge_count": int(full_graph_data.get("edge_count", len(full_graph_data.get("edges", []) or []))),
        }

    @staticmethod
    def _decorate_nodes(
        ordered_node_ids: Sequence[str],
        node_map: Dict[str, Dict[str, Any]],
        edges: Sequence[Dict[str, Any]],
        degree_map: Dict[str, int],
        distance_map: Optional[Dict[str, int]] = None,
        focus_node_uuid: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        visible_degree_map = defaultdict(int)
        for edge in edges:
            source_uuid = edge.get("source_node_uuid")
            target_uuid = edge.get("target_node_uuid")
            if source_uuid:
                visible_degree_map[source_uuid] += 1
            if target_uuid and target_uuid != source_uuid:
                visible_degree_map[target_uuid] += 1

        result = []
        for node_id in ordered_node_ids:
            node = node_map.get(node_id)
            if not node:
                continue

            node_data = dict(node)
            attributes = dict(node_data.get("attributes", {}) or {})
            degree = int(degree_map.get(node_id, visible_degree_map.get(node_id, 0)))
            visible_degree = int(visible_degree_map.get(node_id, 0))
            distance = int((distance_map or {}).get(node_id, 0))
            is_focus = bool(focus_node_uuid and node_id == focus_node_uuid)
            has_more_neighbors = degree > visible_degree

            node_data["degree"] = degree
            node_data["visible_degree"] = visible_degree
            node_data["has_more_neighbors"] = has_more_neighbors
            node_data["distance"] = distance
            node_data["is_focus"] = is_focus

            attributes["degree"] = degree
            attributes["visible_degree"] = visible_degree
            attributes["has_more_neighbors"] = has_more_neighbors
            attributes["distance"] = distance
            attributes["is_focus"] = is_focus
            node_data["attributes"] = attributes

            result.append(node_data)

        return result

    @staticmethod
    def _filter_edges_by_node_ids(
        edges: Sequence[Dict[str, Any]],
        node_ids: set[str],
    ) -> List[Dict[str, Any]]:
        return [
            edge
            for edge in edges
            if edge.get("source_node_uuid") in node_ids
            and edge.get("target_node_uuid") in node_ids
        ]

    @staticmethod
    def _resolve_node_from_full_graph(
        graph_data: Dict[str, Any],
        entity_uuid: str,
    ) -> Optional[Dict[str, Any]]:
        node_map = {
            node.get("uuid"): node
            for node in graph_data.get("nodes", []) or []
            if node.get("uuid")
        }
        node = node_map.get(entity_uuid)
        if node:
            return node

        for item in graph_data.get("nodes", []) or []:
            if item.get("name") == entity_uuid:
                return item
        return None

    def _collect_reader_edges(
        self,
        reader,
        graph_id: str,
        response_node_ids: Sequence[str],
        context_node_ids: Sequence[str],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        ordered_context_ids = self._ordered_unique_ids(context_node_ids)
        response_id_set = set(response_node_ids)
        context_id_set = set(ordered_context_ids)

        if not ordered_context_ids:
            return [], {}

        context_node_map = reader.get_nodes_by_uuids(graph_id, ordered_context_ids)
        adjacency_map = reader.get_nodes_edges_batch(graph_id, ordered_context_ids)

        pair_order = []
        seen_pairs = set()
        for node_id in ordered_context_ids:
            for source_uuid, target_uuid in adjacency_map.get(node_id, []) or []:
                if source_uuid not in context_id_set or target_uuid not in context_id_set:
                    continue
                if source_uuid not in response_id_set and target_uuid not in response_id_set:
                    continue

                pair = (source_uuid, target_uuid)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                pair_order.append(pair)

        edge_map = reader.get_edge_details_batch(graph_id, pair_order)
        edges = []

        for pair in pair_order:
            edge_list = edge_map.get(pair, [])
            if not edge_list:
                continue

            source_uuid, target_uuid = pair
            source_node = context_node_map.get(source_uuid, {})
            target_node = context_node_map.get(target_uuid, {})

            for edge in edge_list:
                edge_data = dict(edge)
                edge_data["uuid"] = edge_data.get("uuid") or f"{source_uuid}->{target_uuid}"
                edge_data["source_node_uuid"] = source_uuid
                edge_data["target_node_uuid"] = target_uuid
                edge_data["source_node_name"] = source_node.get("name", source_uuid)
                edge_data["target_node_name"] = target_node.get("name", target_uuid)
                edge_data["fact_type"] = edge_data.get("fact_type") or edge_data.get("name") or "RELATED"
                edge_data["episodes"] = edge_data.get("episodes", []) or []
                edges.append(edge_data)

        return edges, context_node_map

    def _build_neighborhood_from_reader(
        self,
        reader,
        graph_id: str,
        entity_uuid: str,
        hops: int,
        per_hop_limit: int,
        total_node_limit: int,
        exclude_node_uuids: Optional[Sequence[str]] = None,
        view_mode_prefix: str = "focus",
    ) -> Optional[Dict[str, Any]]:
        center_node = reader.get_node_by_uuid(graph_id, entity_uuid)
        if center_node is None and self._reader_supports(reader, "search_entities"):
            matches = reader.search_entities(graph_id, entity_uuid, limit=1)
            if matches:
                center_node = reader.get_node_by_uuid(graph_id, matches[0]["uuid"])

        if center_node is None:
            return None

        stats = self._get_graph_stats(graph_id, reader=reader)

        center_uuid = center_node["uuid"]
        existing_node_ids = set(self._ordered_unique_ids(exclude_node_uuids or []))
        existing_node_ids.discard(center_uuid)
        response_node_limit = max(1, total_node_limit - len(existing_node_ids))

        returned_node_ids = [center_uuid]
        returned_node_id_set = {center_uuid}
        distance_map = {center_uuid: 0}
        frontier = [center_uuid]

        for hop in range(1, max(1, hops) + 1):
            if not frontier or len(returned_node_id_set) >= response_node_limit:
                break

            adjacency_map = reader.get_nodes_edges_batch(graph_id, frontier)
            candidate_ids = []
            candidates_by_source = {}

            for source_uuid in frontier:
                seen_candidates = set()
                candidates = []

                for pair in adjacency_map.get(source_uuid, []) or []:
                    pair_source, pair_target = pair
                    if pair_source == source_uuid:
                        neighbor_uuid = pair_target
                    elif pair_target == source_uuid:
                        neighbor_uuid = pair_source
                    else:
                        continue

                    if (
                        not neighbor_uuid
                        or neighbor_uuid in returned_node_id_set
                        or neighbor_uuid in existing_node_ids
                        or neighbor_uuid in seen_candidates
                    ):
                        continue

                    seen_candidates.add(neighbor_uuid)
                    candidates.append(neighbor_uuid)
                    candidate_ids.append(neighbor_uuid)

                candidates_by_source[source_uuid] = candidates

            degree_map = reader.get_node_degrees(graph_id, candidate_ids)
            next_frontier = []

            for source_uuid in frontier:
                candidates = sorted(
                    candidates_by_source.get(source_uuid, []),
                    key=lambda node_id: (-degree_map.get(node_id, 0), node_id),
                )

                added_count = 0
                for candidate_uuid in candidates:
                    if candidate_uuid in returned_node_id_set or candidate_uuid in existing_node_ids:
                        continue
                    if added_count >= per_hop_limit or len(returned_node_id_set) >= response_node_limit:
                        break

                    returned_node_id_set.add(candidate_uuid)
                    returned_node_ids.append(candidate_uuid)
                    distance_map[candidate_uuid] = hop
                    next_frontier.append(candidate_uuid)
                    added_count += 1

            frontier = self._ordered_unique_ids(next_frontier)

        context_node_ids = self._ordered_unique_ids(returned_node_ids + list(existing_node_ids))
        edges, context_node_map = self._collect_reader_edges(
            reader=reader,
            graph_id=graph_id,
            response_node_ids=returned_node_ids,
            context_node_ids=context_node_ids,
        )

        node_map = dict(context_node_map)
        node_map.setdefault(center_uuid, center_node)
        degree_map = reader.get_node_degrees(graph_id, returned_node_ids)
        nodes = self._decorate_nodes(
            ordered_node_ids=returned_node_ids,
            node_map=node_map,
            edges=edges,
            degree_map=degree_map,
            distance_map=distance_map,
            focus_node_uuid=center_uuid,
        )

        return self._build_response(
            graph_id=graph_id,
            nodes=nodes,
            edges=edges,
            total_node_count=stats["node_count"],
            total_edge_count=stats["edge_count"],
            view_mode=f"{view_mode_prefix}_{max(1, hops)}",
            focus_node_uuid=center_uuid,
        )

    def _build_default_graph_view_from_full_graph(
        self,
        graph_id: str,
        graph_data: Dict[str, Any],
        limit: int,
    ) -> Dict[str, Any]:
        all_nodes = graph_data.get("nodes", []) or []
        all_edges = graph_data.get("edges", []) or []
        total_node_count = graph_data.get("node_count", len(all_nodes))
        total_edge_count = graph_data.get("edge_count", len(all_edges))

        degree_map = defaultdict(int)
        for edge in all_edges:
            source_uuid = edge.get("source_node_uuid")
            target_uuid = edge.get("target_node_uuid")
            if source_uuid:
                degree_map[source_uuid] += 1
            if target_uuid and target_uuid != source_uuid:
                degree_map[target_uuid] += 1

        ordered_nodes = sorted(
            all_nodes,
            key=lambda node: (
                -degree_map.get(node.get("uuid"), 0),
                node.get("name") or node.get("uuid") or "",
            ),
        )
        selected_nodes = ordered_nodes[:limit]
        selected_node_ids = [node.get("uuid") for node in selected_nodes if node.get("uuid")]
        selected_edges = self._filter_edges_by_node_ids(all_edges, set(selected_node_ids))
        node_map = {
            node.get("uuid"): node
            for node in selected_nodes
            if node.get("uuid")
        }
        nodes = self._decorate_nodes(
            ordered_node_ids=selected_node_ids,
            node_map=node_map,
            edges=selected_edges,
            degree_map=degree_map,
            distance_map={node_id: 0 for node_id in selected_node_ids},
        )

        return self._build_response(
            graph_id=graph_id,
            nodes=nodes,
            edges=selected_edges,
            total_node_count=total_node_count,
            total_edge_count=total_edge_count,
            view_mode="default",
        )

    def _build_neighborhood_from_full_graph(
        self,
        graph_id: str,
        graph_data: Dict[str, Any],
        entity_uuid: str,
        hops: int,
        per_hop_limit: int,
        total_node_limit: int,
        exclude_node_uuids: Optional[Sequence[str]] = None,
        view_mode_prefix: str = "focus",
    ) -> Optional[Dict[str, Any]]:
        center_node = self._resolve_node_from_full_graph(graph_data, entity_uuid)
        if center_node is None:
            return None

        all_nodes = graph_data.get("nodes", []) or []
        all_edges = graph_data.get("edges", []) or []
        total_node_count = graph_data.get("node_count", len(all_nodes))
        total_edge_count = graph_data.get("edge_count", len(all_edges))

        node_map = {
            node.get("uuid"): node
            for node in all_nodes
            if node.get("uuid")
        }
        adjacency_map = defaultdict(list)
        degree_map = defaultdict(int)

        for edge in all_edges:
            source_uuid = edge.get("source_node_uuid")
            target_uuid = edge.get("target_node_uuid")
            if not source_uuid or not target_uuid:
                continue
            adjacency_map[source_uuid].append((source_uuid, target_uuid))
            if target_uuid != source_uuid:
                adjacency_map[target_uuid].append((source_uuid, target_uuid))
            degree_map[source_uuid] += 1
            if target_uuid != source_uuid:
                degree_map[target_uuid] += 1

        center_uuid = center_node["uuid"]
        existing_node_ids = set(self._ordered_unique_ids(exclude_node_uuids or []))
        existing_node_ids.discard(center_uuid)
        response_node_limit = max(1, total_node_limit - len(existing_node_ids))

        returned_node_ids = [center_uuid]
        returned_node_id_set = {center_uuid}
        distance_map = {center_uuid: 0}
        frontier = [center_uuid]

        for hop in range(1, max(1, hops) + 1):
            if not frontier or len(returned_node_id_set) >= response_node_limit:
                break

            next_frontier = []
            for source_uuid in frontier:
                seen_candidates = set()
                candidates = []
                for pair in adjacency_map.get(source_uuid, []):
                    pair_source, pair_target = pair
                    if pair_source == source_uuid:
                        neighbor_uuid = pair_target
                    elif pair_target == source_uuid:
                        neighbor_uuid = pair_source
                    else:
                        continue

                    if (
                        not neighbor_uuid
                        or neighbor_uuid in returned_node_id_set
                        or neighbor_uuid in existing_node_ids
                        or neighbor_uuid in seen_candidates
                    ):
                        continue

                    seen_candidates.add(neighbor_uuid)
                    candidates.append(neighbor_uuid)

                candidates.sort(
                    key=lambda node_id: (
                        -degree_map.get(node_id, 0),
                        (node_map.get(node_id, {}) or {}).get("name") or node_id,
                    )
                )

                added_count = 0
                for candidate_uuid in candidates:
                    if candidate_uuid in returned_node_id_set or candidate_uuid in existing_node_ids:
                        continue
                    if added_count >= per_hop_limit or len(returned_node_id_set) >= response_node_limit:
                        break

                    returned_node_id_set.add(candidate_uuid)
                    returned_node_ids.append(candidate_uuid)
                    distance_map[candidate_uuid] = hop
                    next_frontier.append(candidate_uuid)
                    added_count += 1

            frontier = self._ordered_unique_ids(next_frontier)

        context_node_ids = set(returned_node_ids) | existing_node_ids
        edges = []
        for edge in all_edges:
            source_uuid = edge.get("source_node_uuid")
            target_uuid = edge.get("target_node_uuid")
            if source_uuid not in context_node_ids or target_uuid not in context_node_ids:
                continue
            if source_uuid not in returned_node_id_set and target_uuid not in returned_node_id_set:
                continue
            edges.append(edge)

        nodes = self._decorate_nodes(
            ordered_node_ids=returned_node_ids,
            node_map=node_map,
            edges=edges,
            degree_map=degree_map,
            distance_map=distance_map,
            focus_node_uuid=center_uuid,
        )

        return self._build_response(
            graph_id=graph_id,
            nodes=nodes,
            edges=edges,
            total_node_count=total_node_count,
            total_edge_count=total_edge_count,
            view_mode=f"{view_mode_prefix}_{max(1, hops)}",
            focus_node_uuid=center_uuid,
        )

    def get_graph_view(self, graph_id: str, limit: Optional[int] = None) -> Dict[str, Any]:
        if limit is None or limit <= 0:
            graph_data = self._get_full_graph_data(graph_id)
            graph_data["display_node_count"] = len(graph_data.get("nodes", []) or [])
            graph_data["display_edge_count"] = len(graph_data.get("edges", []) or [])
            graph_data["view_mode"] = "full"
            graph_data["focus_node_uuid"] = None
            return graph_data

        reader = self._create_reader()
        try:
            if self._reader_supports_neighborhood(reader, graph_id) and self._reader_supports_search(reader, graph_id):
                stats = self._get_graph_stats(graph_id, reader=reader)
                entities = reader.get_popular_entities(graph_id, limit=limit)
                selected_node_ids = [entity.get("uuid") for entity in entities if entity.get("uuid")]
                node_map = reader.get_nodes_by_uuids(graph_id, selected_node_ids)
                degree_map = reader.get_node_degrees(graph_id, selected_node_ids)
                edges, context_node_map = self._collect_reader_edges(
                    reader=reader,
                    graph_id=graph_id,
                    response_node_ids=selected_node_ids,
                    context_node_ids=selected_node_ids,
                )
                node_map.update(context_node_map)
                nodes = self._decorate_nodes(
                    ordered_node_ids=selected_node_ids,
                    node_map=node_map,
                    edges=edges,
                    degree_map=degree_map,
                    distance_map={node_id: 0 for node_id in selected_node_ids},
                )
                return self._build_response(
                    graph_id=graph_id,
                    nodes=nodes,
                    edges=edges,
                    total_node_count=stats["node_count"],
                    total_edge_count=stats["edge_count"],
                    view_mode="default",
                )
        finally:
            _close_resource(reader)

        graph_data = self._get_full_graph_data(graph_id)
        return self._build_default_graph_view_from_full_graph(graph_id, graph_data, limit)

    def get_entity_options(
        self,
        graph_id: str,
        query: str = "",
        limit: int = 100,
    ) -> Dict[str, Any]:
        reader = self._create_reader()
        try:
            if self._reader_supports_search(reader, graph_id) and self._reader_supports(reader, "search_entities"):
                entities = reader.search_entities(graph_id, query=query, limit=limit)
                return {
                    "entities": entities,
                    "count": len(entities),
                    "query": query,
                }
        finally:
            _close_resource(reader)

        graph_data = self._get_full_graph_data(graph_id)
        all_nodes = graph_data.get("nodes", []) or []
        normalized_query = (query or "").strip().lower()

        candidates = [
            {
                "uuid": node.get("uuid", ""),
                "name": node.get("name", "") or "",
                "labels": node.get("labels", []) or [],
                "entity_type": self._entity_type_from_labels(node.get("labels", []) or []),
            }
            for node in all_nodes
            if node.get("uuid")
        ]

        if not normalized_query:
            entities = candidates[:limit]
            return {
                "entities": entities,
                "count": len(entities),
                "query": query,
            }

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

        ordered = self._dedupe_entities(exact_uuid + exact_name + prefix_matches + contains_matches)[:limit]

        return {
            "entities": ordered,
            "count": len(ordered),
            "query": query,
        }

    def get_focus_graph_view(
        self,
        graph_id: str,
        entity_uuid: str,
        hops: int = 1,
        per_hop_limit: int = DEFAULT_HOP_LIMIT,
        total_node_limit: int = DEFAULT_TOTAL_NODE_LIMIT,
    ) -> Optional[Dict[str, Any]]:
        if not entity_uuid:
            return None

        hops = max(1, hops)
        per_hop_limit = max(1, per_hop_limit)
        total_node_limit = max(1, total_node_limit)

        reader = self._create_reader()
        try:
            if self._reader_supports_neighborhood(reader, graph_id):
                result = self._build_neighborhood_from_reader(
                    reader=reader,
                    graph_id=graph_id,
                    entity_uuid=entity_uuid,
                    hops=hops,
                    per_hop_limit=per_hop_limit,
                    total_node_limit=total_node_limit,
                    view_mode_prefix="focus",
                )
                if result:
                    return result
        finally:
            _close_resource(reader)

        graph_data = self._get_full_graph_data(graph_id)
        return self._build_neighborhood_from_full_graph(
            graph_id=graph_id,
            graph_data=graph_data,
            entity_uuid=entity_uuid,
            hops=hops,
            per_hop_limit=per_hop_limit,
            total_node_limit=total_node_limit,
            view_mode_prefix="focus",
        )

    def get_expand_graph_view(
        self,
        graph_id: str,
        entity_uuid: str,
        hops: int = 1,
        per_hop_limit: int = DEFAULT_HOP_LIMIT,
        total_node_limit: int = DEFAULT_TOTAL_NODE_LIMIT,
        exclude_node_uuids: Optional[Sequence[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not entity_uuid:
            return None

        hops = max(1, hops)
        per_hop_limit = max(1, per_hop_limit)
        total_node_limit = max(1, total_node_limit)

        reader = self._create_reader()
        try:
            if self._reader_supports_neighborhood(reader, graph_id):
                result = self._build_neighborhood_from_reader(
                    reader=reader,
                    graph_id=graph_id,
                    entity_uuid=entity_uuid,
                    hops=hops,
                    per_hop_limit=per_hop_limit,
                    total_node_limit=total_node_limit,
                    exclude_node_uuids=exclude_node_uuids,
                    view_mode_prefix="expand",
                )
                if result:
                    return result
        finally:
            _close_resource(reader)

        graph_data = self._get_full_graph_data(graph_id)
        return self._build_neighborhood_from_full_graph(
            graph_id=graph_id,
            graph_data=graph_data,
            entity_uuid=entity_uuid,
            hops=hops,
            per_hop_limit=per_hop_limit,
            total_node_limit=total_node_limit,
            exclude_node_uuids=exclude_node_uuids,
            view_mode_prefix="expand",
        )
