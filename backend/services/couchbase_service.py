import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import requests as http_requests
from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.exceptions import (
    BucketAlreadyExistsException,
    CollectionAlreadyExistsException,
    CouchbaseException,
    ServiceUnavailableException,
)
from couchbase.management.buckets import BucketSettings, BucketType
from couchbase.management.collections import CreateCollectionSettings
from couchbase.management.search import SearchIndex
from couchbase.options import ClusterOptions, QueryOptions
from couchbase.search import SearchOptions, SearchRequest
from couchbase.vector_search import VectorQuery, VectorSearch

import config

logger = logging.getLogger(__name__)

CHAT_HISTORY_COLLECTION = "chat_history"

_cluster = None
_connected_string = None


def _is_local_connection() -> bool:
    conn = config.CB_CONNECTION_STRING.lower()
    if "localhost" in conn or "127.0.0.1" in conn:
        return True
    if conn.startswith("couchbase://couchbase"):
        return True
    return False


def _get_couchbase_host() -> str:
    conn = config.CB_CONNECTION_STRING
    host = conn.replace("couchbase://", "").replace("couchbases://", "").split("?")[0]
    return host or "localhost"


def _init_docker_cluster():
    """Bootstrap a fresh Couchbase docker container via the REST API.

    Idempotent: probes ``/pools/default`` with the configured admin
    credentials first; if that returns 200, the cluster is already up
    and we skip every bootstrap step. Otherwise we attempt
    ``setupServices`` / memory quotas / admin-creds in order, each
    treating a 401 response as "already configured" rather than fatal —
    this covers the docker-volume-restart race where ``/pools`` briefly
    returns ``pools=[]`` but the cluster has admin set.
    """
    host = _get_couchbase_host()
    base_url = f"http://{host}:8091"

    last_err: Exception | None = None
    for _ in range(10):
        try:
            r = http_requests.get(f"{base_url}/pools", timeout=3)
            if r.status_code in (200, 401):
                break
        except Exception as e:
            last_err = e
        time.sleep(2)
    else:
        logger.error("Couchbase REST API not reachable after retries: %s", last_err)
        raise RuntimeError(
            f"Couchbase REST API at {base_url} not reachable: {last_err}"
        ) from last_err

    if config.CB_USERNAME and config.CB_PASSWORD:
        try:
            probe = http_requests.get(
                f"{base_url}/pools/default",
                auth=(config.CB_USERNAME, config.CB_PASSWORD),
                timeout=3,
            )
            if probe.status_code == 200:
                logger.debug("Couchbase already initialized — skipping bootstrap")
                return
        except Exception as e:
            logger.debug("Auth probe failed (will attempt bootstrap): %s", e)

    def _post(path: str, data: dict, label: str) -> bool:
        resp = http_requests.post(f"{base_url}{path}", data=data, timeout=10)
        if resp.status_code == 401:
            logger.info(
                "Skipping %s — cluster reports it is already configured", label
            )
            return False
        resp.raise_for_status()
        return True

    if _post(
        "/node/controller/setupServices",
        {"services": "kv,index,fts,n1ql"},
        "setupServices",
    ):
        _post(
            "/pools/default",
            {"memoryQuota": 512, "indexMemoryQuota": 256, "ftsMemoryQuota": 256},
            "memory quotas",
        )
        _post(
            "/settings/web",
            {
                "username": config.CB_USERNAME,
                "password": config.CB_PASSWORD,
                "port": "SAME",
            },
            "admin credentials",
        )
        # GSI storage mode must be set before any CREATE INDEX runs, otherwise
        # the indexer rejects every request with "Please Set Indexer Storage
        # Mode Before Create Index". Plasma is the default on Couchbase 7+ EE.
        try:
            r = http_requests.post(
                f"{base_url}/settings/indexes",
                data={"storageMode": "plasma"},
                auth=(config.CB_USERNAME, config.CB_PASSWORD),
                timeout=10,
            )
            if r.status_code >= 400:
                logger.warning(
                    "Could not set GSI storageMode=plasma (HTTP %s): %s",
                    r.status_code, r.text,
                )
            else:
                logger.info("Set GSI indexer storageMode=plasma")
        except Exception as e:
            logger.warning("Could not set GSI storageMode: %s", e)

        logger.info(
            "Initialized Docker Couchbase cluster at %s (services + memory + admin + indexer)",
            base_url,
        )
        time.sleep(2)
    else:
        logger.info(
            "Docker Couchbase cluster at %s already configured — bootstrap skipped",
            base_url,
        )


def _ensure_bucket():
    cluster = connect()
    bucket_mgr = cluster.buckets()
    try:
        bucket_mgr.create_bucket(
            BucketSettings(
                name=config.CB_BUCKET,
                bucket_type=BucketType.COUCHBASE,
                ram_quota_mb=256,
                flush_enabled=False,
            )
        )
        logger.info("Created bucket: %s", config.CB_BUCKET)
        time.sleep(3)
    except BucketAlreadyExistsException:
        # Expected on reruns — bucket already present
        pass


def connect():
    """Return a cached Cluster handle, reconnecting if the connection string changed."""
    global _cluster, _connected_string

    conn_str = config.CB_CONNECTION_STRING

    if _cluster is not None and _connected_string == conn_str:
        return _cluster

    if _cluster is not None:
        disconnect()

    if _is_local_connection():
        _init_docker_cluster()

    auth = PasswordAuthenticator(config.CB_USERNAME, config.CB_PASSWORD)
    options = ClusterOptions(auth)

    if not _is_local_connection():
        options.apply_profile("wan_development")

    _cluster = Cluster(conn_str, options)
    # Wait for the cluster to come up. With no service_types argument the
    # SDK pings all seven services (KV, View, Query, Search, Analytics,
    # Management, Eventing) by default — the canonical "wait for everything
    # the cluster has" behaviour, see couchbase-cxx-client core/cluster.cxx
    # cluster::ping. 30s instead of 15s because a fresh docker-compose
    # bootstrap was occasionally returning "ready" before Query / Management
    # were truly responsive, surfacing as ServiceUnavailableException
    # (http_status: 0, retry_attempts: 0) on the first index/search call.
    _cluster.wait_until_ready(timedelta(seconds=30))
    _connected_string = conn_str
    return _cluster


def disconnect():
    """Drop the cached Cluster handle so the next ``connect()`` reopens the link."""
    global _cluster, _connected_string
    _cluster = None
    _connected_string = None


def _get_collection(collection_name=None):
    cluster = connect()
    bucket = cluster.bucket(config.CB_BUCKET)
    scope = bucket.scope(config.CB_SCOPE)
    return scope.collection(collection_name or config.CB_COLLECTION)


def _ensure_collections():
    """Create the user-supplied document collection + the chat_history one.

    The document collection name is the SSOT in config.CB_COLLECTION (whatever
    the Settings UI saved). chat_history is a backend-internal collection not
    exposed in the UI, so it stays hardcoded.
    """
    cluster = connect()
    bucket = cluster.bucket(config.CB_BUCKET)
    coll_manager = bucket.collections()

    for name in (config.CB_COLLECTION, CHAT_HISTORY_COLLECTION):
        if not name:
            continue
        try:
            coll_manager.create_collection(
                config.CB_SCOPE, name, settings=CreateCollectionSettings()
            )
            logger.info("Created collection: %s", name)
        except CollectionAlreadyExistsException:
            pass
        except Exception as e:
            logger.warning("Could not create collection %r: %s", name, e)


def _build_search_index_def(index_name: str, collection_name: str) -> dict:
    """Build a scope-level FTS vector index definition.

    The ``name`` field is the bare index name (e.g. "vector-search-index").
    Per the Couchbase Python SDK 4.6 / Server 8.0 docs, scope-level
    indexes are registered and queried by bare name through
    ``scope.search_indexes()`` and ``scope.search()`` -- the bucket and
    scope context comes from the manager / scope handle, not from the
    name string.
    """
    cb_scope = config.CB_SCOPE
    cb_bucket = config.CB_BUCKET
    return {
        "type": "fulltext-index",
        "name": index_name,
        "sourceType": "gocbcore",
        "sourceName": cb_bucket,
        "planParams": {
            "maxPartitionsPerPIndex": 1024,
            "indexPartitions": 1,
        },
        "params": {
            "doc_config": {
                "docid_prefix_delim": "",
                "docid_regexp": "",
                "mode": "scope.collection.type_field",
                "type_field": "type",
            },
            "mapping": {
                "default_mapping": {"dynamic": False, "enabled": False},
                "types": {
                    f"{cb_scope}.{collection_name}": {
                        "dynamic": False,
                        "enabled": True,
                        "properties": {
                            "embedding": {
                                "enabled": True,
                                "dynamic": False,
                                "fields": [
                                    {
                                        "dims": config.EMBEDDING_DIMENSION,
                                        "index": True,
                                        "name": "embedding",
                                        "similarity": "dot_product",
                                        "type": "vector",
                                        "vector_index_optimized_for": "recall",
                                    }
                                ],
                            },
                            "text": {
                                "enabled": True,
                                "dynamic": False,
                                "fields": [
                                    {
                                        "index": True,
                                        "store": True,
                                        "name": "text",
                                        "type": "text",
                                    }
                                ],
                            },
                        },
                    }
                },
            },
            "store": {"indexType": "scorch"},
        },
    }


def _search_index_ready_local(index_name: str) -> tuple[bool, str]:
    """Probe the local Couchbase FTS REST API for index readiness.

    Returns ``(ready, detail)``. ``ready`` is True only when the
    dedicated ``/status`` endpoint reports ``indexStatus == "Ready"`` --
    the documented signal that FTS has assigned plan partitions and the
    index can serve ``scope.search()`` calls. ``detail`` is a short
    human-readable string used for diagnostic logging only.

    The SDK's ``get_indexed_documents_count()`` returns once the manager
    metadata is in place and so passes well before plan partitions
    exist; that gap is what surfaces as "no planPIndexes for
    indexName ..." on the first vector search.

    ``index_name`` is the bare index name -- the scope-level catalog
    stores scope-level indexes by bare name regardless of how the
    upserted ``SearchIndex.name`` was spelled.
    """
    raw_host = _get_couchbase_host()
    host = raw_host.split(":", 1)[0]
    url = (
        f"http://{host}:8094/api/bucket/{config.CB_BUCKET}"
        f"/scope/{config.CB_SCOPE}/index/{index_name}/status"
    )
    try:
        r = http_requests.get(
            url,
            auth=(config.CB_USERNAME, config.CB_PASSWORD),
            timeout=2,
        )
    except Exception as e:
        return False, f"http error: {type(e).__name__}: {e}"
    if r.status_code != 200:
        return False, f"http {r.status_code}: {r.text[:200]}"
    try:
        body = r.json()
    except Exception:
        return False, f"non-json body: {r.text[:200]}"
    status = body.get("indexStatus")
    return status == "Ready", f"indexStatus={status!r}"


# Distance metric for SQL++ APPROX_VECTOR_DISTANCE in capella mode. Must match
# the similarity of the Capella AI Workflow's Hyperscale vector index (created
# with similarity "L2"), otherwise the planner cannot use the index and falls
# back to a full primary scan.
_VECTOR_METRIC = "L2_SQUARED"


def _active_embedding_method() -> str:
    """Return the embedding method in effect: saved settings, else env default.

    Mirrors ``capella_ai_service.is_configured()``'s resolution so indexing and
    retrieval agree with how the documents were actually embedded. Imported
    lazily to avoid an import cycle (settings_store -> ... -> couchbase_service).
    """
    from services import settings_store

    saved = settings_store.load_settings() or {}
    return saved.get("embedding_method", config.EMBEDDING_METHOD_DEFAULT)


def _ensure_search_index():
    if not config.CB_SEARCH_INDEX or not config.CB_COLLECTION:
        logger.info(
            "Skipping search-index setup -- search_index=%r collection=%r",
            config.CB_SEARCH_INDEX, config.CB_COLLECTION,
        )
        return

    # In capella mode the Capella AI Workflow builds its own Hyperscale (GSI)
    # vector index over the `embedding` field, which vector_search queries via
    # SQL++. Building a second app-owned FTS index over the same vectors is
    # redundant, so skip it here.
    if _active_embedding_method() == "capella":
        logger.info(
            "Skipping app FTS search-index setup -- capella mode uses the "
            "workflow's Hyperscale vector index."
        )
        return

    cluster = connect()
    bucket = cluster.bucket(config.CB_BUCKET)
    scope = bucket.scope(config.CB_SCOPE)
    index_mgr = scope.search_indexes()

    index_name = config.CB_SEARCH_INDEX
    index_def = _build_search_index_def(index_name, config.CB_COLLECTION)
    search_index = SearchIndex.from_json(json.dumps(index_def))
    qualified = f"{config.CB_BUCKET}.{config.CB_SCOPE}.{index_name}"

    # Couchbase's FTS REST contract treats `PUT /api/index/{name}` as
    # CREATE unless the body carries the existing index's `uuid`. If an
    # index with this name already exists from an earlier session (e.g.
    # the user switched cb_collection from documents_local to
    # documents_capella, or vice versa, so the old index's `types`
    # mapping no longer covers the current chunks) the upsert below is
    # rejected with QueryIndexAlreadyExistsException and the stale
    # definition keeps quietly pointing at the wrong collection -- the
    # FTS catalog reports no docs, and vector_search returns nothing.
    # Fetch the existing uuid first and copy it onto the new index so
    # the upsert is interpreted as an UPDATE, force-syncing the types
    # mapping to the current cb_collection.
    try:
        existing = index_mgr.get_index(index_name)
        if existing.uuid:
            search_index.uuid = existing.uuid
            logger.info(
                "Existing search index %r found (uuid=%s); upsert will update its types mapping",
                qualified, existing.uuid,
            )
    except CouchbaseException as e:
        # First-time create (index does not exist yet) is the normal
        # path; SDK raises a not-found error class we don't import to
        # avoid churn on SDK version upgrades. Anything else here is
        # a transient FTS-up-but-not-ready error, which the upsert
        # retry below already handles.
        logger.debug("get_index(%r) returned %s; assuming first-time create", index_name, type(e).__name__)

    # wait_until_ready (in connect()) is a connectivity ping per
    # Couchbase docs and does not guarantee that the FTS management
    # layer is ready to accept upsert_index right away. Retry the
    # narrow transient error class only -- ServiceUnavailableException
    # is what surfaces during the post-bootstrap gap; broader catches
    # would silently retry persistent errors. upsert_index is
    # idempotent (same definition repeated yields the same result), so
    # retry is safe.
    upserted = False
    for attempt in range(5):
        try:
            index_mgr.upsert_index(search_index)
            logger.info("Upserted scope-level search index %r", qualified)
            upserted = True
            break
        except ServiceUnavailableException as e:
            if attempt < 4:
                logger.warning(
                    "upsert_index transient failure (attempt %d/5): %s "
                    "-- retrying in 5s",
                    attempt + 1, e,
                )
                time.sleep(5)
                continue
            logger.warning(
                "upsert_index failed after 5 attempts: %s -- giving up", e,
            )
        except Exception as e:
            logger.warning("Could not upsert search index %r: %s", qualified, e)
            break
    if not upserted:
        return

    # FTS index ingestion is async. The dedicated /status endpoint
    # reports indexStatus="Ready" only once FTS has assigned plan
    # partitions and the index can serve scope.search() calls; without
    # this gate the first vector search hits "no planPIndexes for
    # indexName ..." during the build window.
    deadline = time.monotonic() + 60

    if _is_local_connection():
        while time.monotonic() < deadline:
            ready, detail = _search_index_ready_local(index_name)
            if ready:
                logger.info(
                    "Search index %r ready (%s)", qualified, detail,
                )
                return
            logger.debug(
                "Search index %r not yet ready: %s", qualified, detail,
            )
            time.sleep(2)
        logger.warning(
            "Search index %r not Ready within 60s -- continuing anyway",
            qualified,
        )
        return

    # Capella branch: routing /api/... over 18094/TLS through a
    # SRV-based connection string is non-trivial, so fall back to the
    # SDK manager. It uses the canonical bare-name scope-level path
    # internally; Capella's shorter build SLA tends to hide the
    # planPIndexes gap, but the gate is still correct.
    while time.monotonic() < deadline:
        try:
            count = index_mgr.get_indexed_documents_count(index_name)
            logger.info(
                "Search index %r ready (indexed docs: %d)", qualified, count,
            )
            return
        except Exception as e:
            logger.debug(
                "Search index %r not yet queryable: %s", qualified, e,
            )
        time.sleep(2)
    logger.warning(
        "Search index %r not confirmed queryable within 60s -- continuing anyway",
        qualified,
    )


def _ensure_primary_indexes():
    cluster = connect()
    mgr = cluster.query_indexes()
    for name in (config.CB_COLLECTION, CHAT_HISTORY_COLLECTION):
        if not name:
            continue
        try:
            mgr.create_primary_index(
                config.CB_BUCKET,
                scope_name=config.CB_SCOPE,
                collection_name=name,
                ignore_if_exists=True,
            )
            logger.info("Primary index ensured on: %s", name)
        except Exception as e:
            logger.warning("Could not create primary index on %r: %s", name, e)


def _ensure_secondary_indexes():
    """Create GSI secondary indexes aligned with actual N1QL query patterns."""
    cluster = connect()
    bucket = config.CB_BUCKET
    scope = config.CB_SCOPE

    statements: list[tuple[str, str, str]] = []
    if config.CB_COLLECTION:
        statements.append(
            (
                "idx_source_filename",
                config.CB_COLLECTION,
                f"CREATE INDEX IF NOT EXISTS idx_source_filename "
                f"ON `{bucket}`.`{scope}`.`{config.CB_COLLECTION}`"
                f"(metadata.source_filename)",
            )
        )
    statements.append(
        (
            "idx_updated_at",
            CHAT_HISTORY_COLLECTION,
            f"CREATE INDEX IF NOT EXISTS idx_updated_at "
            f"ON `{bucket}`.`{scope}`.`{CHAT_HISTORY_COLLECTION}`"
            f"(updated_at DESC)",
        )
    )

    for index_name, collection, stmt in statements:
        try:
            cluster.query(stmt).execute()
            logger.info(
                "Secondary index ensured: %s on %s", index_name, collection
            )
        except Exception as e:
            logger.warning(
                "Could not create secondary index %r on %r: %s",
                index_name, collection, e,
            )


def setup(stage_cb: Callable[[str], None] | None = None):
    """Bring up bucket/collections/indexes on the connected cluster (idempotent).

    Optional ``stage_cb`` is invoked with stage names ("creating_bucket",
    "creating_collections", "creating_indexes", "building_search_index")
    so callers can surface progress to a UI. Default is a no-op so existing
    callers (lifespan startup) keep working unchanged.
    """
    cb = stage_cb or (lambda _: None)
    connect()
    if _is_local_connection():
        cb("creating_bucket")
        _ensure_bucket()
    cb("creating_collections")
    _ensure_collections()
    cb("creating_indexes")
    _ensure_primary_indexes()
    _ensure_secondary_indexes()
    cb("building_search_index")
    _ensure_search_index()


# --- Knowledge base operations ---

def list_uploaded_files() -> list[dict]:
    """Group document chunks by ``source_filename`` and return per-file summaries."""
    cluster = connect()
    query = (
        f"SELECT metadata.source_filename AS filename, COUNT(*) AS chunk_count, "
        f"MAX(metadata.embedding_method) AS embedding_method, "
        f"MAX(metadata.workflow_name) AS workflow_name "
        f"FROM `{config.CB_BUCKET}`.`{config.CB_SCOPE}`.`{config.CB_COLLECTION}` "
        f"GROUP BY metadata.source_filename "
        f"ORDER BY metadata.source_filename"
    )
    try:
        result = cluster.query(query)
        return [row for row in result]
    except Exception as e:
        logger.warning("list_uploaded_files query failed: %s", e)
        return []


def delete_documents_by_filename(filename: str):
    """Remove every chunk whose metadata.source_filename matches ``filename``."""
    cluster = connect()
    query = (
        f"SELECT META().id AS doc_id "
        f"FROM `{config.CB_BUCKET}`.`{config.CB_SCOPE}`.`{config.CB_COLLECTION}` "
        f"WHERE metadata.source_filename = $filename"
    )
    result = cluster.query(query, filename=filename)
    collection = _get_collection(config.CB_COLLECTION)
    for row in result:
        try:
            collection.remove(row["doc_id"])
        except Exception as e:
            logger.warning(
                "Failed to remove document %r: %s", row.get("doc_id"), e
            )


# --- Document / Vector operations ---

def upsert_document(doc_id: str, text: str, embedding: list[float], metadata: dict):
    """Store a chunk with a precomputed embedding (local Python path)."""
    collection = _get_collection(config.CB_COLLECTION)
    doc = {
        "text": text,
        "embedding": embedding,
        "metadata": metadata,
    }
    collection.upsert(doc_id, doc)


def upsert_document_text(doc_id: str, text: str, filename: str, metadata: dict | None = None):
    """Store text without embedding — Capella AI Services will add embedding."""
    collection = _get_collection(config.CB_COLLECTION)
    doc = {
        "text": text,
        "metadata": metadata or {"source_filename": filename},
    }
    collection.upsert(doc_id, doc)


def has_embedding(doc_id: str) -> bool:
    """Return True if the document exists and has a non-empty embedding field."""
    try:
        collection = _get_collection(config.CB_COLLECTION)
        result = collection.get(doc_id)
        doc = result.content_as[dict]
        embedding = doc.get("embedding")
        return embedding is not None and len(embedding) > 0
    except Exception as e:
        logger.debug("has_embedding(%s) miss: %s", doc_id, e)
        return False


def _vector_search_hyperscale(query_embedding: list[float], top_k: int = 3) -> list[dict]:
    """Vector search via the Capella AI Workflow's Hyperscale (GSI) vector index.

    Used in capella embedding mode. Runs a SQL++ ``APPROX_VECTOR_DISTANCE``
    query; the query planner selects the workflow-created ``embedding VECTOR``
    index automatically when the metric matches the index similarity (L2) --
    no index name needed. ``top_k`` is inlined as an int literal (we control
    it; not user input) to avoid a parameter in the LIMIT clause. Returns the
    same dict shape as the FTS path so callers stay unchanged.
    """
    cluster = connect()
    coll = f"`{config.CB_BUCKET}`.`{config.CB_SCOPE}`.`{config.CB_COLLECTION}`"
    stmt = (
        f"SELECT META().id AS id, text, metadata, "
        f'APPROX_VECTOR_DISTANCE(embedding, $qv, "{_VECTOR_METRIC}") AS _dist '
        f"FROM {coll} "
        f'ORDER BY APPROX_VECTOR_DISTANCE(embedding, $qv, "{_VECTOR_METRIC}") '
        f"LIMIT {int(top_k)}"
    )
    result = cluster.query(
        stmt, QueryOptions(named_parameters={"qv": query_embedding})
    )
    docs = []
    for row in result:
        text = row.get("text", "")
        if not text:
            continue  # Skip results without text content
        dist = row.get("_dist") or 0.0
        docs.append({
            "id": row.get("id"),
            "text": text,
            "metadata": row.get("metadata", {}),
            # Convert distance (lower is better) to a higher-is-better score so
            # the shape matches the FTS path's `score`.
            "score": 1.0 / (1.0 + dist),
        })
    return docs


def vector_search(query_embedding: list[float], top_k: int = 3) -> list[dict]:
    """Run a vector search and return the top-k matching chunks.

    In capella mode this queries the Capella AI Workflow's Hyperscale vector
    index via SQL++ (``_vector_search_hyperscale``). In local/python mode it
    runs a dot-product FTS query over the app-owned scope-level search index
    (below).

    The index itself remains scope-level (registered via
    ``scope.search_indexes().upsert_index`` with a bare name; RBAC,
    lifecycle, and scope binding all preserved). The query, however,
    has to go through ``cluster.search(qualified, ...)`` because of a
    routing gap in Couchbase Python SDK 4.6.0:

    ``couchbase/logic/scope_req_builder.py::ScopeRequestBuilder.build_search_request``
    only injects ``kwargs['scope_name']`` into the C++ core request
    when the query is a legacy ``SearchQuery``; the ``SearchRequest``
    branch (the modern interface that VectorSearch uses) skips that
    injection, so the core dispatches to the cluster-level FTS path
    without scope context. Calling ``scope.search(bare, SearchRequest)``
    on this SDK version surfaces as ``QueryIndexNotFoundException`` --
    the cluster-level FTS catalog only knows the index under its
    fully-qualified ``bucket.scope.name`` form (the server auto-adds
    that entry on scope-level upsert), so a bare-name lookup misses.

    Couchbase Server itself accepts ``scope.search(bare)`` over plain
    REST -- a direct ``POST /api/bucket/B/scope/S/index/<bare>/query``
    returns hits as expected -- so the gap is strictly in the SDK
    routing, not the index.

    The fix is already on the SDK's master branch
    (``couchbase-python-client@master::scope_req_builder.py``
    refactors ``build_search_request`` to extract ``scope_name`` from
    the query builder for both branches and pass it explicitly into
    ``SearchQueryRequest``). PyPI's latest stable is still 4.6.0 at
    the time of writing, so this workaround is needed until the next
    release (4.7 / next minor) reaches PyPI; at that point switch
    back to ``scope.search(index_name, ...)`` and drop this comment.

    See ``docs/SDK_4_6_0_VECTOR_SEARCH_BUG.md`` for the full
    write-up, reproduction steps, and the GitHub source pointers
    on which this workaround relies.
    """
    if _active_embedding_method() == "capella":
        return _vector_search_hyperscale(query_embedding, top_k)

    cluster = connect()
    index_name = config.CB_SEARCH_INDEX
    qualified = f"{config.CB_BUCKET}.{config.CB_SCOPE}.{index_name}"

    vector_query = VectorQuery("embedding", query_embedding, num_candidates=top_k)
    search_request = SearchRequest.create(VectorSearch.from_vector_query(vector_query))

    last_exc: Exception | None = None
    for attempt in range(2):  # initial + one retry on transient build race
        try:
            result = cluster.search(
                qualified,
                search_request,
                SearchOptions(limit=top_k, fields=["text", "metadata"]),
            )
            rows = list(result.rows())
            docs = []
            for row in rows:
                fields = row.fields
                text = fields.get("text", "")
                if not text:
                    continue  # Skip results without text content
                docs.append({
                    "id": row.id,
                    "text": text,
                    "metadata": fields.get("metadata", {}),
                    "score": row.score,
                })
            return docs
        except CouchbaseException as e:
            # Catches transient FTS build-window errors -- e.g. "no
            # planPIndexes for indexName ..." that surfaces during the
            # gap between upsert_index and plan partition assignment.
            # _ensure_search_index polls /status to close that gap; the
            # retry stays as defence-in-depth.
            #
            # str(e) on a search error includes SearchErrorContext with
            # the full request body -- including the 1536-dim embedding
            # vector. Truncate so a transient retry doesn't produce a
            # 30k-char log line.
            last_exc = e
            if attempt == 0:
                logger.warning(
                    "Search index %r failed (%s: %s) -- retrying once after 5s",
                    qualified, type(e).__name__, str(e)[:300],
                )
                time.sleep(5)
            continue
    if last_exc is not None:
        raise last_exc
    return []


def get_chunks_by_filename(filename: str) -> list[str]:
    cluster = connect()
    query = (
        f"SELECT text "
        f"FROM `{config.CB_BUCKET}`.`{config.CB_SCOPE}`.`{config.CB_COLLECTION}` "
        f"WHERE metadata.source_filename = $filename "
        f"ORDER BY metadata.chunk_index"
    )
    try:
        result = cluster.query(query, filename=filename)
        return [row.get("text", "") for row in result]
    except Exception as e:
        logger.warning("get_chunks_by_filename query failed: %s", e)
        return []


def count_chunks_by_filename(filename: str) -> int:
    cluster = connect()
    query = (
        f"SELECT COUNT(*) AS cnt "
        f"FROM `{config.CB_BUCKET}`.`{config.CB_SCOPE}`.`{config.CB_COLLECTION}` "
        f"WHERE metadata.source_filename = $filename"
    )
    try:
        result = cluster.query(query, filename=filename)
        for row in result:
            return row.get("cnt", 0)
    except Exception as e:
        logger.warning("count_chunks_by_filename query failed: %s", e)
    return 0


def count_embedded_chunks_by_filename(filename: str) -> int:
    """How many of ``filename``'s chunks already have an ``embedding`` field.

    Capella AI Workflows process chunks in place: they read each doc's
    ``text``, compute its embedding, and write it back under the
    ``embedding`` field on the same doc. So the count of docs where
    ``embedding IS VALUED`` for this filename is the canonical
    "chunks processed so far" number -- and unlike the workflow run's
    aggregate ``processedFiles`` field (which Capella does not expose
    for vectorization workflows anyway), it is per-file accurate
    even when multiple uploads share a single workflow run.

    Returns 0 on transient query failures so the caller can keep
    polling without raising; this is a UX progress signal, not a
    hard count callers rely on.
    """
    cluster = connect()
    query = (
        f"SELECT COUNT(*) AS cnt "
        f"FROM `{config.CB_BUCKET}`.`{config.CB_SCOPE}`.`{config.CB_COLLECTION}` "
        f"WHERE metadata.source_filename = $filename "
        f"AND embedding IS VALUED"
    )
    try:
        result = cluster.query(query, filename=filename)
        for row in result:
            return row.get("cnt", 0)
    except Exception as e:
        logger.warning("count_embedded_chunks_by_filename query failed: %s", e)
    return 0


def stamp_capella_metadata(filename: str, workflow_id: str) -> None:
    """Mark every chunk of ``filename`` as Capella-vectorized in one round-trip.

    Replaces a per-chunk ``get`` + ``upsert`` loop with a single N1QL
    UPDATE so the tail-end metadata flip after ``wait_for_run`` is
    constant-time instead of O(chunk_count) round-trips. Idempotent —
    re-running on already-stamped docs is a no-op at the value level.
    """
    cluster = connect()
    query = (
        f"UPDATE `{config.CB_BUCKET}`.`{config.CB_SCOPE}`.`{config.CB_COLLECTION}` "
        f"SET metadata.embedding_method = 'capella', "
        f"    metadata.workflow_name = $workflow_id "
        f"WHERE metadata.source_filename = $filename"
    )
    try:
        # query() returns a result iterator; consuming it forces the
        # mutation to actually run. UPDATE produces no rows but raises
        # on syntax / permission failures.
        result = cluster.query(query, filename=filename, workflow_id=workflow_id)
        for _ in result:
            pass
    except Exception as e:
        logger.warning(
            "stamp_capella_metadata failed for %r: %s", filename, e,
        )


def set_embedding_method_by_filename(filename: str, method: str) -> None:
    """Set ``metadata.embedding_method = method`` on every chunk of ``filename``.

    A single N1QL UPDATE (constant-time, like ``stamp_capella_metadata``)
    used to durably record embedding state — notably ``"failed"`` on an
    embedding error and ``"pending"`` when a retry starts — so the state
    survives process restarts (unlike the in-memory job-status dict).
    """
    cluster = connect()
    query = (
        f"UPDATE `{config.CB_BUCKET}`.`{config.CB_SCOPE}`.`{config.CB_COLLECTION}` "
        f"SET metadata.embedding_method = $method "
        f"WHERE metadata.source_filename = $filename"
    )
    try:
        result = cluster.query(query, filename=filename, method=method)
        for _ in result:
            pass
    except Exception as e:
        logger.warning(
            "set_embedding_method_by_filename(%r, %r) failed: %s",
            filename, method, e,
        )


# --- Chat history operations ---

def save_chat_session(session_id: str, title: str, messages: list[dict]):
    """Upsert a chat session doc, preserving the original ``created_at`` on updates."""
    collection = _get_collection(CHAT_HISTORY_COLLECTION)
    doc = {
        "session_id": session_id,
        "title": title,
        "messages": messages,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        existing = collection.get(session_id)
        doc["created_at"] = existing.content_as[dict].get(
            "created_at", doc["updated_at"]
        )
    except Exception:
        doc["created_at"] = doc["updated_at"]

    collection.upsert(session_id, doc)


def list_chat_sessions() -> list[dict]:
    """List chat session summaries ordered by ``updated_at`` descending."""
    cluster = connect()
    # ``title IS NOT MISSING`` filters out the singleton ``vocabulary_hints``
    # doc that shares the chat_history collection — it has no title and would
    # break the SessionSummary response model.
    query = (
        f"SELECT META().id AS session_id, title, created_at, updated_at "
        f"FROM `{config.CB_BUCKET}`.`{config.CB_SCOPE}`.`{CHAT_HISTORY_COLLECTION}` "
        f"WHERE title IS NOT MISSING "
        f"ORDER BY updated_at DESC"
    )
    try:
        result = cluster.query(query)
        return [row for row in result]
    except Exception as e:
        logger.warning("list_chat_sessions query failed: %s", e)
        return []


def load_chat_session(session_id: str) -> dict | None:
    """Return the full chat session document or ``None`` if it does not exist."""
    try:
        collection = _get_collection(CHAT_HISTORY_COLLECTION)
        result = collection.get(session_id)
        return result.content_as[dict]
    except Exception as e:
        logger.debug("load_chat_session(%s) miss: %s", session_id, e)
        return None


def delete_chat_session(session_id: str):
    """Remove a chat session document, swallowing NotFound errors."""
    try:
        collection = _get_collection(CHAT_HISTORY_COLLECTION)
        collection.remove(session_id)
    except Exception as e:
        logger.warning("Failed to delete chat session %r: %s", session_id, e)


def generate_session_id() -> str:
    return str(uuid.uuid4())


# --- Vocabulary hints for STT ---

VOCABULARY_HINTS_DOC_ID = "vocabulary_hints"


def save_vocabulary_hints(terms: list[str]):
    """Persist STT vocabulary hints extracted from uploaded documents."""
    collection = _get_collection(CHAT_HISTORY_COLLECTION)
    collection.upsert(VOCABULARY_HINTS_DOC_ID, {"terms": terms})


def load_vocabulary_hints() -> list[str]:
    """Return the stored STT vocabulary hints, or an empty list if none persisted."""
    try:
        collection = _get_collection(CHAT_HISTORY_COLLECTION)
        result = collection.get(VOCABULARY_HINTS_DOC_ID)
        return result.content_as[dict].get("terms", [])
    except Exception as e:
        logger.debug("load_vocabulary_hints miss: %s", e)
        return []
