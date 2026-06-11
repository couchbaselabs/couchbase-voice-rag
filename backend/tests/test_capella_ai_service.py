"""Unit tests for capella_ai_service.

Flows that matter for customer-grade demos:

- ``get_or_create_workflow`` must NOT reuse a workflow whose
  ``targetCouchbaseKeyspace`` no longer matches current Settings —
  that's exactly the case where the workflow runs at 0/0 forever
  because chunks land in the new collection while the workflow keeps
  watching the old one. The fix is to delete the stale workflow and
  create a fresh one with the same name.

- ``_get_provider_id`` must select the openAI-typed provider; the
  workflow body uses ``openAiIntegration.providerId`` so any other
  provider type makes Capella reject the create.

- ``wait_for_run`` must poll until terminal and raise on ``failed``.
  Note that per-chunk progress is not derived from this poll — the
  Capella API does not expose ``processedFiles`` / ``totalFiles`` for
  vectorization workflows; the UI bar is driven from Couchbase
  counts inside ``document_service`` instead.
"""

import httpx
import pytest
import respx

from services import capella_ai_service as cas
from services import capella_management_service as cms

CAPELLA_BASE = cms.CAPELLA_BASE


@pytest.fixture(autouse=True)
def reset_discovery_cache():
    cms._discovered.clear()
    yield
    cms._discovered.clear()


@pytest.fixture
def configured(monkeypatch):
    """Pin org/project/cluster ids + bucket/scope/collection for a stable workflow URL."""
    monkeypatch.setattr(cms.config.settings, "capella_api_key_id", "key-id")
    monkeypatch.setattr(cms.config.settings, "capella_api_key_token", "key-token")
    monkeypatch.setattr(cms.config.settings, "capella_org_id", "org1")
    monkeypatch.setattr(cms.config.settings, "capella_project_id", "proj1")
    monkeypatch.setattr(cms.config.settings, "capella_cluster_id", "cluster1")
    monkeypatch.setattr(cms.config.settings, "capella_workflow_id", "")
    monkeypatch.setattr(cms.config.settings, "capella_workflow_name", "demo_wf")
    monkeypatch.setattr(cms.config.settings, "capella_ai_provider_id", "prov1")
    monkeypatch.setattr(cms.config.settings, "cb_bucket", "rag")
    monkeypatch.setattr(cms.config.settings, "cb_scope", "_default")
    monkeypatch.setattr(cms.config.settings, "cb_collection", "documents_capella")
    monkeypatch.setattr(cms.config.settings, "openai_embedding_model", "text-embedding-3-small")


WORKFLOWS_URL = (
    f"{CAPELLA_BASE}/v4/organizations/org1/projects/proj1"
    f"/clusters/cluster1/aiServices/workflows"
)


def _workflow(name: str, wf_id: str, collection: str) -> dict:
    return {
        "id": wf_id,
        "name": name,
        "type": "vectorization",
        "configuration": {
            "targetCouchbaseKeyspace": {
                "bucket": "rag",
                "scope": "_default",
                "collection": collection,
            }
        },
    }


async def test_get_or_create_workflow_reuses_matching(configured):
    """Same name + same keyspace -> reuse, no delete / no create."""
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        mock.get(WORKFLOWS_URL).mock(
            return_value=httpx.Response(
                200, json={"data": [_workflow("demo_wf", "wf-1", "documents_capella")]}
            )
        )
        # No DELETE / POST should be called — assert_all_called=True will
        # complain if extra mocks are registered, so we register none.

        wf_id = await cas.get_or_create_workflow()

        assert wf_id == "wf-1"
        assert cms.config.settings.capella_workflow_id == "wf-1"


async def test_get_or_create_workflow_recreates_when_keyspace_is_stale(configured):
    """Same name but workflow points at a different collection -> delete + create."""
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        mock.get(WORKFLOWS_URL).mock(
            return_value=httpx.Response(
                200,
                # Workflow exists but targets the OLD collection (the python-mode one)
                json={"data": [_workflow("demo_wf", "wf-stale", "documents_local")]},
            )
        )
        delete_route = mock.delete(f"{WORKFLOWS_URL}/wf-stale").mock(
            return_value=httpx.Response(204)
        )
        create_route = mock.post(WORKFLOWS_URL).mock(
            return_value=httpx.Response(201, json={"id": "wf-fresh"})
        )

        wf_id = await cas.get_or_create_workflow()

        assert wf_id == "wf-fresh"
        assert delete_route.called
        assert create_route.called
        # Body of the POST must target the CURRENT collection
        import json

        body = json.loads(create_route.calls[0].request.read())
        assert body["configuration"]["targetCouchbaseKeyspace"]["collection"] == (
            "documents_capella"
        )
        assert cms.config.settings.capella_workflow_id == "wf-fresh"


async def test_get_or_create_workflow_creates_when_none_exist(configured):
    """No workflows on the cluster -> just create with the configured name."""
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        mock.get(WORKFLOWS_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        create_route = mock.post(WORKFLOWS_URL).mock(
            return_value=httpx.Response(201, json={"id": "wf-new"})
        )

        wf_id = await cas.get_or_create_workflow()

        assert wf_id == "wf-new"
        assert create_route.called


async def test_get_or_create_workflow_revalidates_cached_id(configured, monkeypatch):
    """Cached workflow id is GETted and keyspace-checked before reuse."""
    monkeypatch.setattr(cms.config.settings, "capella_workflow_id", "wf-cached")
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        # Cached workflow now points at the stale collection
        mock.get(f"{WORKFLOWS_URL}/wf-cached").mock(
            return_value=httpx.Response(
                200, json=_workflow("demo_wf", "wf-cached", "documents_local")
            )
        )
        mock.delete(f"{WORKFLOWS_URL}/wf-cached").mock(
            return_value=httpx.Response(204)
        )
        mock.get(WORKFLOWS_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        mock.post(WORKFLOWS_URL).mock(
            return_value=httpx.Response(201, json={"id": "wf-replacement"})
        )

        wf_id = await cas.get_or_create_workflow()

        assert wf_id == "wf-replacement"
        assert cms.config.settings.capella_workflow_id == "wf-replacement"


async def test_delete_workflow_active_run_raises_actionable_error(configured):
    """405/409 -> ``RuntimeError`` with hint instead of opaque httpx error."""
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        mock.delete(f"{WORKFLOWS_URL}/wf-x").mock(
            return_value=httpx.Response(409, json={"error": "active run"})
        )

        with pytest.raises(RuntimeError, match="active run|cancel the run"):
            await cas.delete_workflow("wf-x")


async def test_wait_for_run_returns_final_status(configured, monkeypatch):
    """``wait_for_run`` polls until a terminal status and returns it."""
    async def _fake_sleep(_seconds):
        return

    monkeypatch.setattr(cas.asyncio, "sleep", _fake_sleep)

    statuses = [
        {"status": "running"},
        {"status": "running"},
        {"status": "completed"},
    ]
    run_url = f"{WORKFLOWS_URL}/wf-1/runs/run-1"
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        mock.get(run_url).mock(
            side_effect=[httpx.Response(200, json=s) for s in statuses]
        )

        final = await cas.wait_for_run("wf-1", "run-1")
        assert final["status"] == "completed"


PROVIDERS_URL = f"{CAPELLA_BASE}/v4/organizations/org1/aiServices/providers"


async def test_get_provider_id_filters_to_openai_type(configured, monkeypatch):
    """A cluster org with mixed provider types: only the openAI one is picked.

    Picking ``providers[0]`` (the pre-fix behaviour) hands an awsS3 id
    to a workflow body that names it as ``openAiIntegration.providerId``
    — Capella rejects the create, which compounds destructively with
    Phase N-A's delete-then-create flow.
    """
    monkeypatch.setattr(cas.config.settings, "capella_ai_provider_id", "")
    cms._discovered.pop("provider_id", None)
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        mock.get(PROVIDERS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "s3-1", "name": "S3-A", "type": "awsS3"},
                        {"id": "bed-1", "name": "Bedrock-A", "type": "awsBedrock"},
                        {"id": "oai-1", "name": "OpenAI-A", "type": "openAI"},
                        {"id": "s3-2", "name": "S3-B", "type": "awsS3"},
                    ]
                },
            )
        )
        async with httpx.AsyncClient() as client:
            pid = await cas._get_provider_id(client)
        assert pid == "oai-1"


async def test_get_provider_id_raises_when_no_openai_provider(
    configured, monkeypatch,
):
    """No openAI-typed provider -> RuntimeError listing what WAS found.

    The message must name the visible providers so the operator can
    register the missing one without guessing.
    """
    monkeypatch.setattr(cas.config.settings, "capella_ai_provider_id", "")
    cms._discovered.pop("provider_id", None)
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        mock.get(PROVIDERS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "s3-1", "name": "S3-A", "type": "awsS3"},
                        {"id": "bed-1", "name": "Bedrock-A", "type": "awsBedrock"},
                    ]
                },
            )
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(RuntimeError) as exc_info:
                await cas._get_provider_id(client)
        msg = str(exc_info.value)
        assert "openAI" in msg
        assert "S3-A" in msg  # surfaces what's actually registered
        assert "awsBedrock" in msg


async def test_get_or_create_workflow_does_not_delete_when_provider_missing(
    configured, monkeypatch,
):
    """Stale workflow + no openAI provider -> DO NOT delete the old workflow.

    The pre-fix behaviour (Phase N-A) deleted the workflow first, then
    failed to recreate it because of the bad provider, leaving the
    cluster with nothing. The fix validates the provider FIRST and
    bubbles the RuntimeError up, leaving the stale workflow in place.
    """
    monkeypatch.setattr(cas.config.settings, "capella_ai_provider_id", "")
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        mock.get(WORKFLOWS_URL).mock(
            return_value=httpx.Response(
                200,
                json={"data": [_workflow("demo_wf", "wf-stale", "documents_local")]},
            )
        )
        mock.get(PROVIDERS_URL).mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"id": "s3-1", "name": "S3", "type": "awsS3"}]},
            )
        )
        # Deliberately NO DELETE/POST stubs: respx.mock(assert_all_called=True)
        # would complain if we accidentally registered one and didn't fire it,
        # AND the destructive call would 404 against an unmocked route, so
        # this catches both regression modes.

        with pytest.raises(RuntimeError, match="openAI"):
            await cas.get_or_create_workflow()

        # Stale workflow stays — the next attempt (after the operator
        # registers an openAI provider) can recreate cleanly.
        assert cas.config.settings.capella_workflow_id == ""


async def test_wait_for_run_raises_on_failed_status(configured, monkeypatch):
    """``failed`` terminal status must surface as a RuntimeError with the run id."""
    async def _fake_sleep(_seconds):
        return

    monkeypatch.setattr(cas.asyncio, "sleep", _fake_sleep)

    run_url = f"{WORKFLOWS_URL}/wf-1/runs/run-1"
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        mock.get(run_url).mock(
            return_value=httpx.Response(200, json={"status": "failed"})
        )
        with pytest.raises(RuntimeError, match="run-1"):
            await cas.wait_for_run("wf-1", "run-1")
