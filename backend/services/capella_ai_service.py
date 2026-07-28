import asyncio
import logging

import httpx

import config
from services import (
    capella_management_service as cms,
)
from services import (
    couchbase_service,
    settings_store,
)
from services.capella_management_service import CAPELLA_BASE

logger = logging.getLogger(__name__)

COMPLETED_STATUSES = {"completed", "partiallyCompleted", "failed"}
POLL_INTERVAL = 5
_HTTP_TIMEOUT = httpx.Timeout(30.0)


def is_configured() -> bool:
    """Capella mode is active only when the user selected it AND API keys are set."""
    saved = settings_store.load_settings() or {}
    method = saved.get("embedding_method", config.EMBEDDING_METHOD_DEFAULT)
    if method != "capella":
        return False
    return cms.is_configured()


async def _get_provider_id(client: httpx.AsyncClient) -> str:
    """Return the Capella AI provider id whose ``type`` matches the workflow body.

    Our ``create_workflow`` posts an
    ``embeddingModel.external.openAiIntegration.providerId`` field, so the
    provider must be ``type == "openAI"``. Cluster orgs that host other
    demos / sandboxes commonly have multiple providers registered
    (``awsS3`` for AI HOL, ``awsBedrock`` for Bedrock demos, ``openAI``
    for us); picking ``providers[0]`` silently sent an ``awsS3`` id into
    an ``openAiIntegration`` field and Capella rejected the workflow
    create with a 4xx — which, combined with a delete-then-create
    recreate flow, destroyed the user's workflow without leaving a
    replacement behind.
    """
    if config.CAPELLA_AI_PROVIDER_ID:
        return config.CAPELLA_AI_PROVIDER_ID
    if "provider_id" in cms._discovered:
        return cms._discovered["provider_id"]

    org_id = await cms.get_org_id(client)
    resp = await client.get(
        f"{CAPELLA_BASE}/v4/organizations/{org_id}/aiServices/providers",
        headers=cms._headers(),
    )
    resp.raise_for_status()
    providers = resp.json().get("data", [])
    openai_providers = [p for p in providers if p.get("type") == "openAI"]
    if not openai_providers:
        found = ", ".join(
            f"{p.get('name')!r}:{p.get('type')}" for p in providers
        ) or "none"
        raise RuntimeError(
            "No Capella AI provider with type='openAI' registered for this org. "
            "Register an OpenAI provider in the Capella console under "
            "AI Services -> Providers before running Capella mode. "
            f"Currently visible providers: {found}."
        )
    provider = openai_providers[0]
    provider_id = provider["id"]
    cms._discovered["provider_id"] = provider_id
    logger.info(
        "Auto-discovered Capella AI provider: %s (%s)",
        provider_id, provider.get("name"),
    )
    return provider_id


async def _base_url(client: httpx.AsyncClient) -> str:
    org_id = await cms.get_org_id(client)
    project_id = await cms.get_project_id(client)
    cluster_id = await cms.get_cluster_id(client)
    return (
        f"{CAPELLA_BASE}/v4/organizations/{org_id}"
        f"/projects/{project_id}"
        f"/clusters/{cluster_id}"
        f"/aiServices/workflows"
    )


async def list_workflows() -> list[dict]:
    """Return all workflows registered under the current org/project/cluster."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        url = await _base_url(client)
        resp = await client.get(url, headers=cms._headers())
        resp.raise_for_status()
        return resp.json().get("data", [])


def _current_target_keyspace() -> dict[str, str]:
    """Return the keyspace a freshly created workflow would target right now.

    Cached / pre-existing workflows must point at exactly this keyspace
    or they are stale — the user has changed cb_collection (typically by
    switching embedding_method, which auto-derives documents_local vs
    documents_capella in the Settings UI) and the old workflow is still
    watching the previous collection.
    """
    return {
        "bucket": config.CB_BUCKET,
        "scope": config.CB_SCOPE,
        "collection": config.CB_COLLECTION,
    }


def _keyspace_matches(workflow: dict) -> bool:
    actual = (
        (workflow.get("configuration") or {}).get("targetCouchbaseKeyspace") or {}
    )
    want = _current_target_keyspace()
    return all(actual.get(k) == want.get(k) for k in ("bucket", "scope", "collection"))


async def delete_workflow(workflow_id: str) -> None:
    """Delete a Capella AI workflow. Idempotent on 404.

    Raises a user-actionable ``RuntimeError`` on 405/409 (Capella's way
    of saying "the workflow has an active run; you can't delete it
    right now") so the caller can surface the right instruction
    instead of treating it as a generic transient failure.
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        base = await _base_url(client)
        resp = await client.delete(f"{base}/{workflow_id}", headers=cms._headers())
        if resp.status_code == 404:
            logger.debug("Workflow %s already gone", workflow_id)
            return
        if resp.status_code in (405, 409):
            raise RuntimeError(
                f"Capella workflow {workflow_id} cannot be deleted right now "
                f"(status {resp.status_code}). It likely has an active run -- "
                "cancel the run in the Capella console, or rename the workflow "
                "via the CAPELLA_WORKFLOW_NAME env var to skip the stale one."
            )
        resp.raise_for_status()
        logger.info("Deleted Capella AI workflow: %s", workflow_id)


async def create_workflow(name: str | None = None) -> str:
    """Create a vectorization workflow targeting the configured Capella
    collection. The workflow is named ``name`` (or
    ``config.settings.capella_workflow_name`` if omitted).
    """
    if name is None:
        name = config.settings.capella_workflow_name
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        provider_id = await _get_provider_id(client)
        body = {
            "name": name,
            "type": "vectorization",
            "configuration": {
                "targetCouchbaseKeyspace": {
                    "bucket": config.CB_BUCKET,
                    "scope": config.CB_SCOPE,
                    "collection": config.CB_COLLECTION,
                },
                "vectorizationConfig": {
                    # Build the Hyperscale vector index over `embedding`; in
                    # capella mode couchbase_service.vector_search queries it
                    # via SQL++ APPROX_VECTOR_DISTANCE. Its default similarity
                    # (L2) must match couchbase_service._VECTOR_METRIC.
                    "createIndexes": True,
                    "embeddingFieldMappings": {
                        "embedding": {
                            "sourceFields": ["text"],
                        },
                    },
                    "embeddingModel": {
                        "external": {
                            "openAiIntegration": {
                                "providerId": provider_id,
                            },
                            "modelName": config.OPENAI_EMBEDDING_MODEL,
                        },
                    },
                },
            },
        }
        url = await _base_url(client)
        resp = await client.post(url, headers=cms._headers(), json=body)
        resp.raise_for_status()
        workflow_id = resp.json()["id"]
        logger.info("Created Capella AI workflow: %s", workflow_id)
        return workflow_id


async def get_or_create_workflow() -> str:
    """Return the workflow id whose name AND keyspace match current Settings.

    Looking up by name (instead of "first match where type ==
    vectorization") avoids hijacking an unrelated workflow on a
    cluster that hosts other demos / sandboxes. Re-validating the
    keyspace on top of the name avoids the inverse mistake: reusing a
    workflow whose name still matches but whose
    ``targetCouchbaseKeyspace`` points at a collection the user has
    since changed (e.g. switching embedding_method from python to
    capella swaps cb_collection from documents_local to
    documents_capella). Without the re-check, the workflow keeps
    watching the old collection while new chunks land in the new one
    and every run sits at processedFiles=0/totalFiles=0.

    On mismatch the stale workflow is deleted and a fresh one is
    created under the same name. Provider lookup runs BEFORE the delete
    so that a missing / mis-typed provider raises and leaves the stale
    workflow in place — Capella's API has no PUT for workflow keyspace,
    so delete-then-create is the only path, and a failed create after a
    successful delete would destroy the user's workflow with no
    replacement. Failing fast on the precondition is the safer half of
    that trade-off. If Capella refuses the delete (active run), the
    underlying ``RuntimeError`` from ``delete_workflow`` bubbles up
    with an actionable hint.
    """
    target_name = config.settings.capella_workflow_name
    want_keyspace = _current_target_keyspace()

    if config.settings.capella_workflow_id:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            base = await _base_url(client)
            try:
                resp = await client.get(
                    f"{base}/{config.settings.capella_workflow_id}",
                    headers=cms._headers(),
                )
                resp.raise_for_status()
                cached = resp.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    logger.info(
                        "Cached workflow %s no longer exists; will rediscover",
                        config.settings.capella_workflow_id,
                    )
                    config.settings.capella_workflow_id = ""
                    cached = None
                else:
                    raise
        if cached is not None:
            if _keyspace_matches(cached):
                logger.info(
                    "Using cached workflow id: %s (keyspace verified)",
                    config.settings.capella_workflow_id,
                )
                return config.settings.capella_workflow_id
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                await _get_provider_id(client)
            logger.warning(
                "Cached workflow %s targets stale keyspace %r; recreating to %r",
                config.settings.capella_workflow_id,
                (cached.get("configuration") or {}).get("targetCouchbaseKeyspace"),
                want_keyspace,
            )
            await delete_workflow(config.settings.capella_workflow_id)
            config.settings.capella_workflow_id = ""

    workflows = await list_workflows()
    for wf in workflows:
        if wf.get("name") == target_name and wf.get("type") == "vectorization":
            if _keyspace_matches(wf):
                wf_id = wf["id"]
                logger.info("Found existing workflow %r: %s", target_name, wf_id)
                config.settings.capella_workflow_id = wf_id
                return wf_id
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                await _get_provider_id(client)
            logger.warning(
                "Workflow %r has stale keyspace %r; recreating to match %r",
                target_name,
                (wf.get("configuration") or {}).get("targetCouchbaseKeyspace"),
                want_keyspace,
            )
            await delete_workflow(wf["id"])
            break

    wf_id = await create_workflow(name=target_name)
    config.settings.capella_workflow_id = wf_id
    return wf_id


async def run_workflow(workflow_id: str) -> str:
    """Trigger a fresh run of ``workflow_id`` and return the new run id."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        base = await _base_url(client)
        resp = await client.post(f"{base}/{workflow_id}/runs", headers=cms._headers())
        resp.raise_for_status()
        run_id = resp.json()["id"]
        logger.info("Started workflow run: %s", run_id)
        return run_id


async def get_run_status(workflow_id: str, run_id: str) -> dict:
    """Return the current status document for a workflow run."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        base = await _base_url(client)
        resp = await client.get(f"{base}/{workflow_id}/runs/{run_id}", headers=cms._headers())
        resp.raise_for_status()
        return resp.json()


async def wait_for_run(
    workflow_id: str,
    run_id: str,
    timeout: int = 300,
) -> dict:
    """Poll the workflow run every ``POLL_INTERVAL`` seconds until it finishes or times out.

    Returns the final status dict on terminal state, raises
    ``RuntimeError`` on ``failed`` and ``TimeoutError`` past ``timeout``.

    Note: per-chunk progress is NOT derived from this poll. Capella's
    workflow run status response for vectorization workflows is just
    ``{createdAt, createdByUserID, id, status}`` -- no
    ``processedFiles`` / ``totalFiles`` fields, and the
    ``/runs/{runId}/processedFiles`` sub-resource returns 422
    "Operation not permitted for workflow type: vectorization". The
    UI progress bar is driven from Couchbase directly by
    ``document_service._poll_capella_progress``.
    """
    loop = asyncio.get_running_loop()
    start = loop.time()

    while loop.time() - start < timeout:
        status = await get_run_status(workflow_id, run_id)
        current = status.get("status", "")
        logger.debug("Workflow run %s status: %s", run_id, current)

        if current in COMPLETED_STATUSES:
            if current == "failed":
                raise RuntimeError(
                    f"Workflow run {run_id} failed. "
                    "Check Capella console for details."
                )
            if current == "partiallyCompleted":
                logger.warning(
                    "Workflow run %s partially completed: %d errors",
                    run_id, status.get("erroredFiles", 0),
                )
            return status

        await asyncio.sleep(POLL_INTERVAL)

    raise TimeoutError(
        f"Workflow run {run_id} did not complete within {timeout}s."
    )


async def trigger_and_wait(timeout: int = 300) -> dict:
    """Convenience: ensure a workflow exists, start a run, and wait for its terminal status."""
    workflow_id = await get_or_create_workflow()
    run_id = await run_workflow(workflow_id)
    return await wait_for_run(workflow_id, run_id, timeout=timeout)


async def wait_for_embedding(
    doc_id: str,
    timeout: int = 180,
    poll_interval: int = 3,
) -> bool:
    """Legacy helper: poll Couchbase until a doc gains an ``embedding`` field."""
    loop = asyncio.get_running_loop()
    start = loop.time()
    while loop.time() - start < timeout:
        if await asyncio.to_thread(couchbase_service.has_embedding, doc_id):
            logger.info("Embedding complete for '%s'", doc_id)
            return True
        await asyncio.sleep(poll_interval)
    raise TimeoutError(
        f"Embedding not added to '{doc_id}' within {timeout}s."
    )
