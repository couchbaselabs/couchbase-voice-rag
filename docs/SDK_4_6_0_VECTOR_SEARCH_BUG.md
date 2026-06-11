# Couchbase Python SDK 4.6.0 — `Scope.search()` with `SearchRequest` (vector search) routes to cluster-level FTS path

> Scope-level vector search via `scope.search(index_name, SearchRequest, ...)` raises
> `QueryIndexNotFoundException(ec=17)` because the SDK does not propagate scope context for
> the `SearchRequest` branch. The legacy `SearchQuery` branch and direct REST call work.
> Already fixed on the SDK's master branch; this document captures the bug for upstream
> reporting and to anchor the in-tree workaround.

## Environment

- Couchbase Python SDK: **4.6.0** (PyPI's latest stable as of 2026-04;
  release tag commit `fbceef9ed86af073f7f4144b5154a80a52130208`)
- Couchbase Server: **8.0.0** (official `couchbase:8.0.0` Docker image)
- Python: 3.12

## Summary

On SDK 4.6.0, `scope.search(index_name, search_request, ...)` — where
`search_request` is built from `VectorSearch.from_vector_query(...)` (i.e. any
modern vector or hybrid search) — raises `QueryIndexNotFoundException(ec=17)`
even when the scope-level FTS index exists and reports `indexStatus="Ready"`.
The same query body sent directly to the scope-level FTS REST endpoint
(`POST /api/bucket/<B>/scope/<S>/index/<bare>/query`) returns
`{"status":{"successful":1, ...}, "hits":[...]}`.

The legacy `SearchQuery` path (`scope.search(bare, SearchQuery(...))`) works
correctly. Only the `SearchRequest` path is broken.

## Root cause

File: `couchbase/logic/scope_req_builder.py` —
`ScopeRequestBuilder.build_search_request`

GitHub (4.6.0 tag):
<https://github.com/couchbase/couchbase-python-client/blob/4.6.0/couchbase/logic/scope_req_builder.py>

```python
def build_search_request(self, index, query, obs_handler, *options, **kwargs):
    num_workers = kwargs.pop('num_workers', None)
    if isinstance(query, SearchQuery):
        opt = SearchOptions()
        opts = list(options)
        for o in opts:
            if isinstance(o, SearchOptions):
                opt = o
                opts.remove(o)
        # set the scope_name as this scope if not provided
        if not ('scope_name' in opt or 'scope_name' in kwargs):
            kwargs['scope_name'] = f'{self._scope_name}'           # <-- only here
        req = SearchQueryRequest(
            SearchQueryBuilder.create_search_query_object(index, query, *options, **kwargs), obs_handler)
    else:
        # SearchRequest branch (used by VectorSearch / hybrid) -- no scope_name injection
        req = SearchQueryRequest(
            SearchQueryBuilder.create_search_query_from_request(index, query, *options, **kwargs), obs_handler)
    ...
```

The legacy `SearchQuery` branch injects `kwargs['scope_name']` so the underlying
C++ core knows the scope context. The `SearchRequest` branch — which is what
`VectorSearch.from_vector_query(...)` and modern hybrid queries take — does
not. The resulting `SearchQueryRequest` carries no scope context, so the C++
core dispatches via the cluster-level FTS endpoint
(`/api/index/<name>/query`).

The cluster-level catalog stores the index under its fully-qualified
`<bucket>.<scope>.<name>` form (the server adds that entry automatically on
scope-level upsert), so a bare-name lookup misses and the response is
`index_not_found`.

## Already fixed on master

GitHub (master HEAD):
<https://github.com/couchbase/couchbase-python-client/blob/master/couchbase/logic/scope_req_builder.py>

```python
def build_search_request(self, index, query, obs_handler, *options, **kwargs):
    num_workers = kwargs.pop('num_workers', None)

    if isinstance(query, SearchQuery):
        query_builder = SearchQueryBuilder.create_search_query_object(index, query, *options, **kwargs)
    else:
        query_builder = SearchQueryBuilder.create_search_query_from_request(index, query, *options, **kwargs)

    scope_name = query_builder.scope_name if query_builder.scope_name else self._scope_name
    req = SearchQueryRequest(query_builder, obs_handler, self._bucket_name, scope_name)
    ...
```

Both branches now feed through a unified flow that extracts `scope_name` from
the query builder (or falls back to `self._scope_name`) and explicitly passes
it together with `self._bucket_name` to `SearchQueryRequest`. This is the
correct fix.

## Reproduction

1. Start Couchbase Server 8.0.0 in Docker. Create bucket `realtime-rag`,
   scope `_default`, collection `documents`.
2. Register a scope-level FTS vector index via the Python SDK:

   ```python
   from couchbase.management.search import SearchIndex
   index_def = {
       "type": "fulltext-index",
       "name": "vector-search-index",
       "sourceType": "gocbcore",
       "sourceName": "realtime-rag",
       "params": {
           "doc_config": {"mode": "scope.collection.type_field", "type_field": "type"},
           "mapping": {
               "default_mapping": {"dynamic": False, "enabled": False},
               "types": {
                   "_default.documents": {
                       "dynamic": False, "enabled": True,
                       "properties": {
                           "embedding": {"enabled": True, "fields": [
                               {"dims": 1536, "index": True, "name": "embedding",
                                "similarity": "dot_product", "type": "vector",
                                "vector_index_optimized_for": "recall"}
                           ]}
                       }
                   }
               }
           },
           "store": {"indexType": "scorch"}
       }
   }
   scope.search_indexes().upsert_index(SearchIndex.from_json(json.dumps(index_def)))
   ```

3. Wait for `indexStatus="Ready"`:

   ```bash
   curl -u "$USER:$PW" \
     http://localhost:8094/api/bucket/realtime-rag/scope/_default/index/vector-search-index/status
   # -> {"status":"ok","indexStatus":"Ready"}
   ```

4. Insert at least one document with an `embedding` field of 1536 floats.

5. Execute via SDK:

   ```python
   from couchbase.search import SearchRequest
   from couchbase.vector_search import VectorQuery, VectorSearch
   from couchbase.options import SearchOptions

   request = SearchRequest.create(
       VectorSearch.from_vector_query(VectorQuery("embedding", query_vector, num_candidates=3))
   )
   result = scope.search(
       "vector-search-index",
       request,
       SearchOptions(limit=3, fields=["text", "metadata"]),
   )
   list(result.rows())   # raises QueryIndexNotFoundException
   ```

6. Verify the same query body succeeds via direct REST:

   ```bash
   curl -u "$USER:$PW" -X POST \
     http://localhost:8094/api/bucket/realtime-rag/scope/_default/index/vector-search-index/query \
     -H "Content-Type: application/json" \
     -d '{"size":3,"knn":[{"field":"embedding","k":3,"vector":[/* 1536 floats */]}]}'
   # -> 200, {"status":{"total":1,"failed":0,"successful":1},"hits":[...]}
   ```

7. Confirm the cluster-level catalog stores the index under FQN:

   ```bash
   curl -u "$USER:$PW" http://localhost:8094/api/cfg \
     | jq '.indexDefs.indexDefs | keys'
   # -> ["realtime-rag._default.vector-search-index"]
   ```

## Observed error

```
QueryIndexNotFoundException(<ec=17, category=couchbase.common,
  message=Streaming operation failed,
  context=SearchErrorContext({
    'context_type': 'SearchErrorContext',
    'index_name': 'vector-search-index',
    'parameters': '{"ctl":{"timeout":75000},"explain":false,"fields":["text","metadata"],"knn":[...]}',
    'last_dispatched_to': '<host>:8094',
    ...
  })>)
```

## Workaround (in this repository)

Until a release containing the master fix lands on PyPI, query through
`cluster.search(qualified_fqn, search_request, ...)` where
`qualified_fqn = f"{bucket}.{scope}.{index_name}"`. The cluster-level catalog
carries the index under the FQN (server-side auto-entry on scope-level
upsert), so this path resolves. The index itself remains scope-level —
RBAC, lifecycle, and scope binding are unaffected. See
`backend/services/couchbase_service.py::vector_search` for the in-tree
implementation; the docstring there cross-references this document.

## Suggested fix

Backport the master `build_search_request` refactor to a 4.6.x patch
release, or release 4.7 with the fix included. The change is self-contained
and the master form is already correct.
