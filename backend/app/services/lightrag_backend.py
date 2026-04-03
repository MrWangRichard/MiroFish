"""
Shared helpers for working with the LightRAG backend.
"""

import asyncio
import atexit
import os
import shutil
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from ..config import Config
from ..utils.logger import get_logger

try:
    import numpy as np
    from lightrag import LightRAG
    from lightrag.llm.openai import openai_complete_if_cache, openai_embed
    from lightrag.utils import wrap_embedding_func_with_attrs

    LIGHTRAG_AVAILABLE = True
except ImportError:
    np = None
    LightRAG = None
    openai_complete_if_cache = None
    openai_embed = None
    wrap_embedding_func_with_attrs = None
    LIGHTRAG_AVAILABLE = False


logger = get_logger("mirofish.lightrag_backend")

_LIGHTRAG_LOOP = None
_LIGHTRAG_LOOP_THREAD = None
_LIGHTRAG_LOOP_READY = threading.Event()
_LIGHTRAG_LOOP_GUARD = threading.Lock()
_LIGHTRAG_SHARED_STORAGE_GUARD = threading.Lock()

DEFAULT_ENTITY_TYPES = [
    "Person",
    "Organization",
    "Location",
    "Event",
    "Concept",
    "Artifact",
    "Time",
]


def is_lightrag_available() -> bool:
    return LIGHTRAG_AVAILABLE


def ensure_lightrag_available():
    if not LIGHTRAG_AVAILABLE:
        raise ImportError(
            "LightRAG 未安装，请安装 lightrag-hku 以及所需存储依赖。"
        )


def get_graph_working_dir(graph_id: str) -> str:
    return os.path.join(Config.LIGHTTRAG_WORKING_DIR, graph_id)


def get_graph_workspace(graph_id: str) -> str:
    return f"{Config.LIGHTTRAG_WORKSPACE}_{graph_id}"


def extract_entity_types(ontology: Optional[Dict[str, Any]]) -> List[str]:
    if not ontology:
        return DEFAULT_ENTITY_TYPES

    entity_types = []
    for entity_def in ontology.get("entity_types", []):
        name = str(entity_def.get("name", "")).strip()
        if name:
            entity_types.append(name)

    return entity_types or DEFAULT_ENTITY_TYPES


def _sync_lightrag_storage_env():
    """
    Sync selected backend Config values into process env for LightRAG storages.

    LightRAG's Neo4JStorage does not read our Flask Config object. It loads
    connection settings directly from `os.environ` during `initialize()`.
    This bridge keeps the effective runtime values consistent, including our
    normalization from local `neo4j://` to `bolt://`.
    """
    if Config.LIGHTTRAG_GRAPH_STORAGE == "Neo4JStorage":
        os.environ["NEO4J_URI"] = _normalize_neo4j_uri(Config.NEO4J_URI)
        os.environ["NEO4J_USERNAME"] = Config.NEO4J_USERNAME
        os.environ["NEO4J_PASSWORD"] = Config.NEO4J_PASSWORD


def _normalize_neo4j_uri(uri: str) -> str:
    """
    Prefer direct Bolt connections for local standalone Neo4j instances.

    The `neo4j://` scheme enables routing discovery, which commonly fails for
    single-node local deployments and raises "Unable to retrieve routing
    information". For loopback hosts we transparently downgrade to `bolt://`.
    """
    value = (uri or "").strip()
    if not value:
        return value

    parts = urlsplit(value)
    if parts.scheme != "neo4j":
        return value

    host = (parts.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return value

    normalized = urlunsplit(("bolt", parts.netloc, parts.path, parts.query, parts.fragment))
    if normalized != value:
        logger.info(
            "Normalizing local Neo4j URI from '%s' to '%s' to avoid routing discovery failures",
            value,
            normalized,
        )
    return normalized


def _run_loop_forever():
    global _LIGHTRAG_LOOP

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _LIGHTRAG_LOOP = loop
    _LIGHTRAG_LOOP_READY.set()

    try:
        loop.run_forever()
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


def _get_lightrag_loop():
    global _LIGHTRAG_LOOP_THREAD

    with _LIGHTRAG_LOOP_GUARD:
        if (
            _LIGHTRAG_LOOP is not None
            and _LIGHTRAG_LOOP_THREAD is not None
            and _LIGHTRAG_LOOP_THREAD.is_alive()
            and _LIGHTRAG_LOOP.is_running()
        ):
            return _LIGHTRAG_LOOP

        _LIGHTRAG_LOOP_READY.clear()
        _LIGHTRAG_LOOP_THREAD = threading.Thread(
            target=_run_loop_forever,
            name="LightRAGAsyncLoop",
            daemon=True,
        )
        _LIGHTRAG_LOOP_THREAD.start()

    _LIGHTRAG_LOOP_READY.wait()
    return _LIGHTRAG_LOOP


def _shutdown_lightrag_loop():
    global _LIGHTRAG_LOOP, _LIGHTRAG_LOOP_THREAD

    with _LIGHTRAG_LOOP_GUARD:
        loop = _LIGHTRAG_LOOP
        thread = _LIGHTRAG_LOOP_THREAD
        _LIGHTRAG_LOOP = None
        _LIGHTRAG_LOOP_THREAD = None

    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)


def _reset_lightrag_shared_storage():
    from lightrag.kg.shared_storage import finalize_share_data, initialize_share_data

    with _LIGHTRAG_SHARED_STORAGE_GUARD:
        finalize_share_data()
        initialize_share_data()


def _run_async(coro):
    loop = _get_lightrag_loop()

    if threading.current_thread() is _LIGHTRAG_LOOP_THREAD:
        raise RuntimeError("Cannot call _run_async from the LightRAG event loop thread")

    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


def lightrag_insert(
    rag: "LightRAG",
    input_data,
    split_by_character: Optional[str] = None,
    split_by_character_only: bool = False,
    ids=None,
    file_paths=None,
    track_id: Optional[str] = None,
):
    """
    Safely insert documents through the dedicated LightRAG event loop.

    Do not call `rag.insert(...)` directly in application code.
    """
    return _run_async(
        rag.ainsert(
            input_data,
            split_by_character=split_by_character,
            split_by_character_only=split_by_character_only,
            ids=ids,
            file_paths=file_paths,
            track_id=track_id,
        )
    )


def lightrag_query(
    rag: "LightRAG",
    query: str,
    param=None,
    system_prompt: Optional[str] = None,
):
    """
    Safely execute a query through the dedicated LightRAG event loop.

    Do not call `rag.query(...)` directly in application code.
    """
    return _run_async(rag.aquery(query, param=param, system_prompt=system_prompt))


def lightrag_query_data(
    rag: "LightRAG",
    query: str,
    param=None,
):
    """
    Safely execute a structured retrieval query through the dedicated LightRAG event loop.

    Do not call `rag.query_data(...)` directly in application code.
    """
    return _run_async(rag.aquery_data(query, param=param))


def lightrag_get_all_nodes(rag: "LightRAG") -> List[Dict[str, Any]]:
    """Read all graph nodes through the dedicated LightRAG event loop."""
    return _run_async(rag.chunk_entity_relation_graph.get_all_nodes())


def lightrag_get_all_edges(rag: "LightRAG") -> List[Dict[str, Any]]:
    """Read all graph edges through the dedicated LightRAG event loop."""
    return _run_async(rag.chunk_entity_relation_graph.get_all_edges())


def lightrag_get_node(
    rag: "LightRAG",
    node_id: str,
):
    """Read a single graph node through the dedicated LightRAG event loop."""
    return _run_async(rag.chunk_entity_relation_graph.get_node(node_id))


def lightrag_get_nodes_batch(
    rag: "LightRAG",
    node_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Read multiple graph nodes through the dedicated LightRAG event loop."""
    return _run_async(rag.chunk_entity_relation_graph.get_nodes_batch(node_ids))


def lightrag_get_node_edges(
    rag: "LightRAG",
    node_id: str,
):
    """Read a single node's edges through the dedicated LightRAG event loop."""
    return _run_async(rag.chunk_entity_relation_graph.get_node_edges(node_id))


def lightrag_get_nodes_edges_batch(
    rag: "LightRAG",
    node_ids: List[str],
) -> Dict[str, List[tuple[str, str]]]:
    """Read multiple nodes' edges through the dedicated LightRAG event loop."""
    return _run_async(rag.chunk_entity_relation_graph.get_nodes_edges_batch(node_ids))


def lightrag_get_edges_batch(
    rag: "LightRAG",
    pairs: List[Dict[str, str]],
) -> Dict[tuple[str, str], Dict[str, Any]]:
    """Read multiple graph edges through the dedicated LightRAG event loop."""
    return _run_async(rag.chunk_entity_relation_graph.get_edges_batch(pairs))


def lightrag_get_edges_for_pairs(
    rag: "LightRAG",
    pairs: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """Read all graph edges for the requested node pairs."""
    storage = rag.chunk_entity_relation_graph
    driver = getattr(storage, "_driver", None)
    workspace_label_getter = getattr(storage, "_get_workspace_label", None)
    database = getattr(storage, "_DATABASE", None)

    if driver is None or not callable(workspace_label_getter):
        raise AttributeError("Current LightRAG graph storage does not expose pair edge queries")

    async def _query():
        workspace_label = workspace_label_getter()
        async with driver.session(database=database, default_access_mode="READ") as session:
            result = await session.run(
                f"""
                UNWIND $pairs AS pair
                MATCH (src:`{workspace_label}` {{entity_id: pair.src}})-[r]-(tgt:`{workspace_label}` {{entity_id: pair.tgt}})
                RETURN pair.src AS pair_src,
                       pair.tgt AS pair_tgt,
                       startNode(r).entity_id AS source,
                       endNode(r).entity_id AS target,
                       properties(r) AS properties
                """,
                pairs=pairs,
            )
            try:
                records = []
                async for record in result:
                    records.append(
                        {
                            "pair_src": record["pair_src"],
                            "pair_tgt": record["pair_tgt"],
                            "source": record["source"],
                            "target": record["target"],
                            "properties": record["properties"] or {},
                        }
                    )
                return records
            finally:
                await result.consume()

    return _run_async(_query())


def lightrag_get_node_degrees_batch(
    rag: "LightRAG",
    node_ids: List[str],
) -> Dict[str, int]:
    """Read multiple node degrees through the dedicated LightRAG event loop."""
    return _run_async(rag.chunk_entity_relation_graph.node_degrees_batch(node_ids))


def lightrag_get_popular_labels(
    rag: "LightRAG",
    limit: int = 300,
) -> List[str]:
    """Read popular graph labels through the dedicated LightRAG event loop."""
    return _run_async(rag.chunk_entity_relation_graph.get_popular_labels(limit=limit))


def lightrag_search_labels(
    rag: "LightRAG",
    query: str,
    limit: int = 50,
) -> List[str]:
    """Search graph labels through the dedicated LightRAG event loop."""
    return _run_async(rag.chunk_entity_relation_graph.search_labels(query, limit=limit))


def lightrag_count_nodes(rag: "LightRAG") -> int:
    """Count graph nodes for Neo4j-backed LightRAG storages."""
    storage = rag.chunk_entity_relation_graph
    driver = getattr(storage, "_driver", None)
    workspace_label_getter = getattr(storage, "_get_workspace_label", None)
    database = getattr(storage, "_DATABASE", None)

    if driver is None or not callable(workspace_label_getter):
        raise AttributeError("Current LightRAG graph storage does not expose count support")

    async def _count():
        workspace_label = workspace_label_getter()
        async with driver.session(database=database, default_access_mode="READ") as session:
            result = await session.run(f"MATCH (n:`{workspace_label}`) RETURN count(n) AS total")
            try:
                record = await result.single()
                return int(record["total"] if record else 0)
            finally:
                await result.consume()

    return _run_async(_count())


def lightrag_count_edges(rag: "LightRAG") -> int:
    """Count graph edges for Neo4j-backed LightRAG storages."""
    storage = rag.chunk_entity_relation_graph
    driver = getattr(storage, "_driver", None)
    workspace_label_getter = getattr(storage, "_get_workspace_label", None)
    database = getattr(storage, "_DATABASE", None)

    if driver is None or not callable(workspace_label_getter):
        raise AttributeError("Current LightRAG graph storage does not expose count support")

    async def _count():
        workspace_label = workspace_label_getter()
        async with driver.session(database=database, default_access_mode="READ") as session:
            result = await session.run(
                f"MATCH (a:`{workspace_label}`)-[r]-(b:`{workspace_label}`) RETURN count(r) AS total"
            )
            try:
                record = await result.single()
                return int(record["total"] if record else 0)
            finally:
                await result.consume()

    return _run_async(_count())


def lightrag_get_entity_info(
    rag: "LightRAG",
    entity_name: str,
    include_vector_data: bool = False,
):
    """Read entity details through the dedicated LightRAG event loop."""
    return _run_async(
        rag.get_entity_info(entity_name, include_vector_data=include_vector_data)
    )


def lightrag_get_relation_info(
    rag: "LightRAG",
    source: str,
    target: str,
    include_vector_data: bool = False,
):
    """Read relation details through the dedicated LightRAG event loop."""
    return _run_async(
        rag.get_relation_info(
            source,
            target,
            include_vector_data=include_vector_data,
        )
    )


def create_llm_func():
    ensure_lightrag_available()

    async def llm_model_func(
        prompt,
        system_prompt=None,
        history_messages=None,
        keyword_extraction=False,
        **kwargs,
    ) -> str:
        return await openai_complete_if_cache(
            Config.LLM_MODEL_NAME,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages or [],
            api_key=Config.LLM_API_KEY,
            base_url=Config.LLM_BASE_URL,
            **kwargs,
        )

    return llm_model_func


def create_embedding_func():
    ensure_lightrag_available()

    @wrap_embedding_func_with_attrs(
        embedding_dim=Config.LIGHTRAG_EMBEDDING_DIM,
        max_token_size=Config.LIGHTTRAG_MAX_TOKEN_SIZE,
    )
    async def embedding_func(texts: List[str]) -> "np.ndarray":
        return await openai_embed.func(
            texts,
            model=Config.LIGHTTRAG_EMBEDDING_MODEL,
            api_key=Config.LLM_API_KEY,
            base_url=Config.LLM_BASE_URL,
        )

    return embedding_func


def create_lightrag(
    graph_id: str,
    ontology: Optional[Dict[str, Any]] = None,
) -> "LightRAG":
    ensure_lightrag_available()
    _sync_lightrag_storage_env()

    working_dir = get_graph_working_dir(graph_id)
    os.makedirs(working_dir, exist_ok=True)

    rag = LightRAG(
        working_dir=working_dir,
        llm_model_func=create_llm_func(),
        embedding_func=create_embedding_func(),
        graph_storage=Config.LIGHTTRAG_GRAPH_STORAGE,
        vector_storage=Config.LIGHTTRAG_VECTOR_STORAGE,
        kv_storage=Config.LIGHTTRAG_KV_STORAGE,
        doc_status_storage=Config.LIGHTTRAG_DOC_STATUS_STORAGE,
        workspace=get_graph_workspace(graph_id),
        addon_params={
            "language": Config.LIGHTTRAG_LANGUAGE,
            "entity_types": extract_entity_types(ontology),
        },
    )

    try:
        _run_async(rag.initialize_storages())
    except RuntimeError as exc:
        if "bound to a different event loop" not in str(exc):
            raise

        logger.warning(
            "Detected stale LightRAG shared storage bound to a different event loop; "
            "resetting shared storage and retrying initialization"
        )
        _reset_lightrag_shared_storage()
        _run_async(rag.initialize_storages())
    return rag


def finalize_lightrag(rag: Optional["LightRAG"]):
    if rag is None:
        return

    try:
        _run_async(rag.finalize_storages())
    except Exception as exc:
        logger.warning(f"关闭 LightRAG 存储失败: {exc}")


def drop_lightrag_graph(graph_id: str, rag: Optional["LightRAG"] = None):
    rag = rag or create_lightrag(graph_id)
    working_dir = get_graph_working_dir(graph_id)

    storage_names = [
        "chunk_entity_relation_graph",
        "entities_vdb",
        "relationships_vdb",
        "chunks_vdb",
        "full_docs",
        "text_chunks",
        "full_entities",
        "full_relations",
        "entity_chunks",
        "relation_chunks",
        "llm_response_cache",
        "doc_status",
    ]

    try:
        for storage_name in storage_names:
            storage = getattr(rag, storage_name, None)
            drop_method = getattr(storage, "drop", None)
            if callable(drop_method):
                try:
                    _run_async(drop_method())
                except Exception as exc:
                    logger.warning(
                        f"清理 LightRAG 存储失败: graph_id={graph_id}, storage={storage_name}, error={exc}"
                    )
    finally:
        finalize_lightrag(rag)

    if os.path.isdir(working_dir):
        shutil.rmtree(working_dir, ignore_errors=True)


def lightrag_node_to_dict(node: Dict[str, Any]) -> Dict[str, Any]:
    entity_name = node.get("entity_id") or node.get("id") or ""
    entity_type = node.get("entity_type") or ""
    labels = ["Entity"]
    if entity_type:
        labels.append(str(entity_type))

    return {
        "uuid": str(entity_name),
        "name": str(entity_name),
        "labels": labels,
        "summary": node.get("description", "") or "",
        "attributes": {
            "entity_id": entity_name,
            "entity_type": entity_type,
            "source_id": node.get("source_id", "") or "",
            "file_path": node.get("file_path", "") or "",
        },
        "created_at": node.get("created_at"),
    }


def lightrag_edge_to_dict(edge: Dict[str, Any]) -> Dict[str, Any]:
    source = edge.get("source", "") or ""
    target = edge.get("target", "") or ""
    edge_name = edge.get("keywords") or edge.get("relation_type") or "related"
    description = edge.get("description", "") or ""

    return {
        "uuid": f"{source}->{target}",
        "name": str(edge_name),
        "fact": description,
        "source_node_uuid": str(source),
        "target_node_uuid": str(target),
        "source_node_name": str(source),
        "target_node_name": str(target),
        "attributes": {
            "weight": edge.get("weight", 1.0),
            "keywords": edge.get("keywords", ""),
            "source_id": edge.get("source_id", ""),
            "file_path": edge.get("file_path", ""),
        },
        "created_at": edge.get("created_at"),
        "valid_at": edge.get("valid_at"),
        "invalid_at": edge.get("invalid_at"),
        "expired_at": edge.get("expired_at"),
    }


atexit.register(_shutdown_lightrag_loop)
