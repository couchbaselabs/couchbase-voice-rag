"""Unit tests for couchbase_service helpers that don't need a live cluster.

Most of couchbase_service is exercised through the integration smoke
test (`docker-compose up` + Save & Connect), but the FTS index
upsert path has a subtle correctness contract worth pinning with a
unit test: when an index with the configured name already exists,
its ``uuid`` must be carried forward into the new SearchIndex object
before calling ``upsert_index``. Without that, Couchbase rejects the
PUT with ``QueryIndexAlreadyExistsException`` (cannot create index
because an index with the same name already exists) and the stale
``types`` mapping keeps pointing at the previous cb_collection -- so
vector_search returns nothing once the user changes cb_collection.
"""

from unittest.mock import MagicMock

from couchbase.exceptions import CouchbaseException

from services import couchbase_service


class _FakeIndexManager:
    def __init__(self, existing_uuid: str | None):
        self._existing_uuid = existing_uuid
        self.upsert_calls: list = []

    def get_index(self, name: str):
        if self._existing_uuid is None:
            raise CouchbaseException("index not found")
        existing = MagicMock()
        existing.uuid = self._existing_uuid
        existing.name = name
        return existing

    def upsert_index(self, index):
        self.upsert_calls.append(index)


def _stub_cluster(monkeypatch, mgr: _FakeIndexManager) -> None:
    """Wire up connect() -> bucket() -> scope() -> search_indexes() -> mgr."""
    scope = MagicMock()
    scope.search_indexes.return_value = mgr
    bucket = MagicMock()
    bucket.scope.return_value = scope
    cluster = MagicMock()
    cluster.bucket.return_value = bucket

    monkeypatch.setattr(couchbase_service, "connect", lambda: cluster)
    # _ensure_search_index post-upsert polls for index status; short-circuit
    # those branches so the test doesn't sleep / hit network.
    monkeypatch.setattr(couchbase_service, "_is_local_connection", lambda: True)
    monkeypatch.setattr(
        couchbase_service,
        "_search_index_ready_local",
        lambda _name: (True, "ready"),
    )


def test_ensure_search_index_carries_existing_uuid_for_update(monkeypatch):
    """Stale index with different keyspace must be UPDATED, not failed-as-create.

    Without the uuid carry-forward the SDK's upsert_index sends a PUT
    with no uuid, Couchbase treats it as a create, and rejects on the
    name collision -- leaving the stale ``_default.documents`` types
    mapping in place while the user's chunks live in
    ``_default.documents_capella``.
    """
    monkeypatch.setattr(couchbase_service.config, "CB_BUCKET", "rag")
    monkeypatch.setattr(couchbase_service.config, "CB_SCOPE", "_default")
    monkeypatch.setattr(couchbase_service.config, "CB_COLLECTION", "documents_capella")
    monkeypatch.setattr(couchbase_service.config, "CB_SEARCH_INDEX", "vector-search-index")

    mgr = _FakeIndexManager(existing_uuid="abc-123")
    _stub_cluster(monkeypatch, mgr)

    couchbase_service._ensure_search_index()

    assert len(mgr.upsert_calls) == 1
    upserted = mgr.upsert_calls[0]
    assert upserted.uuid == "abc-123"
    # The mapping must target the CURRENT cb_collection, not the stale
    # one that may have been in the existing index.
    types = upserted.params["mapping"]["types"]
    assert "_default.documents_capella" in types


def test_ensure_search_index_first_time_create_has_no_uuid(monkeypatch):
    """No existing index -> upsert with no uuid (create path)."""
    monkeypatch.setattr(couchbase_service.config, "CB_BUCKET", "rag")
    monkeypatch.setattr(couchbase_service.config, "CB_SCOPE", "_default")
    monkeypatch.setattr(couchbase_service.config, "CB_COLLECTION", "documents_capella")
    monkeypatch.setattr(couchbase_service.config, "CB_SEARCH_INDEX", "vector-search-index")

    mgr = _FakeIndexManager(existing_uuid=None)
    _stub_cluster(monkeypatch, mgr)

    couchbase_service._ensure_search_index()

    assert len(mgr.upsert_calls) == 1
    upserted = mgr.upsert_calls[0]
    # SearchIndex.from_json with no uuid yields empty/None uuid.
    assert not upserted.uuid


def test_count_embedded_chunks_by_filename_filters_on_embedding_field(monkeypatch):
    """The N1QL query must include ``embedding IS VALUED``.

    Without that filter, the count equals total chunks immediately
    (since chunks are stored without embedding by the upload path) and
    the progress bar would jump to 100% before Capella does any actual
    work. The clause must also target the current cb_collection so the
    count reflects the same docs the workflow is processing.
    """
    monkeypatch.setattr(couchbase_service.config, "CB_BUCKET", "rag")
    monkeypatch.setattr(couchbase_service.config, "CB_SCOPE", "_default")
    monkeypatch.setattr(couchbase_service.config, "CB_COLLECTION", "documents_capella")

    seen_queries: list[str] = []

    class _StubResult:
        def __iter__(self):
            return iter([{"cnt": 7}])

    class _StubCluster:
        def query(self, q: str, **_kwargs):
            seen_queries.append(q)
            return _StubResult()

    monkeypatch.setattr(couchbase_service, "connect", lambda: _StubCluster())

    n = couchbase_service.count_embedded_chunks_by_filename("file.pdf")

    assert n == 7
    assert len(seen_queries) == 1
    q = seen_queries[0]
    assert "metadata.source_filename = $filename" in q
    assert "embedding IS VALUED" in q
    assert "`rag`.`_default`.`documents_capella`" in q


def test_count_embedded_chunks_by_filename_returns_zero_on_query_failure(monkeypatch):
    """Transient N1QL failures must not raise -- the caller polls every 2s."""
    monkeypatch.setattr(couchbase_service.config, "CB_BUCKET", "rag")
    monkeypatch.setattr(couchbase_service.config, "CB_SCOPE", "_default")
    monkeypatch.setattr(couchbase_service.config, "CB_COLLECTION", "documents_capella")

    class _StubCluster:
        def query(self, _q: str, **_kwargs):
            raise RuntimeError("transient cluster failure")

    monkeypatch.setattr(couchbase_service, "connect", lambda: _StubCluster())

    assert couchbase_service.count_embedded_chunks_by_filename("file.pdf") == 0
