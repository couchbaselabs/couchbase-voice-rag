"""Unit tests for capella_management_service.

The Management API itself is mocked via respx so the tests stay
hermetic; we exercise the auto-discovery path (org → project →
cluster), the host-matching cluster lookup, and the idempotent
bucket creation behaviour on 409/422.
"""

import httpx
import pytest
import respx

from services import capella_management_service as cms

CAPELLA_BASE = cms.CAPELLA_BASE


@pytest.fixture(autouse=True)
def reset_discovery_cache():
    cms._discovered.clear()
    yield
    cms._discovered.clear()


@pytest.fixture
def configured_capella(monkeypatch):
    """Capella API key + connection string pointing at one specific host."""
    monkeypatch.setattr(cms.config.settings, "capella_api_key_id", "key-id")
    monkeypatch.setattr(cms.config.settings, "capella_api_key_token", "key-token")
    monkeypatch.setattr(cms.config.settings, "capella_org_id", "")
    monkeypatch.setattr(cms.config.settings, "capella_project_id", "")
    monkeypatch.setattr(cms.config.settings, "capella_cluster_id", "")
    monkeypatch.setattr(
        cms.config.settings,
        "cb_connection_string",
        "couchbases://cb.abc.cloud.couchbase.com",
    )
    monkeypatch.setattr(cms.config.settings, "cb_bucket", "realtime-rag")


def _stub_discovery(mock: respx.MockRouter, *, cluster_host: str) -> None:
    """Wire up the org → project → cluster lookup chain."""
    mock.get(f"{CAPELLA_BASE}/v4/organizations").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "org1"}]})
    )
    mock.get(f"{CAPELLA_BASE}/v4/organizations/org1/projects").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "proj1"}]})
    )
    mock.get(
        f"{CAPELLA_BASE}/v4/organizations/org1/projects/proj1/clusters"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "cluster1",
                        "connectionString": f"couchbases://{cluster_host}",
                    }
                ]
            },
        )
    )


async def test_ensure_bucket_creates_when_missing(configured_capella):
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        _stub_discovery(mock, cluster_host="cb.abc.cloud.couchbase.com")
        bucket_route = mock.post(
            f"{CAPELLA_BASE}/v4/organizations/org1/projects/proj1"
            f"/clusters/cluster1/buckets"
        ).mock(return_value=httpx.Response(201, json={"id": "bucket-1"}))

        await cms.ensure_bucket("realtime-rag")

        assert bucket_route.called
        body = bucket_route.calls[0].request.read()
        assert b'"name":"realtime-rag"' in body
        assert b'"memoryAllocationInMb":256' in body


async def test_ensure_bucket_idempotent_on_409(configured_capella):
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        _stub_discovery(mock, cluster_host="cb.abc.cloud.couchbase.com")
        mock.post(
            f"{CAPELLA_BASE}/v4/organizations/org1/projects/proj1"
            f"/clusters/cluster1/buckets"
        ).mock(return_value=httpx.Response(409, json={"error": "bucket exists"}))

        # Should not raise
        await cms.ensure_bucket("realtime-rag")


async def test_ensure_bucket_raises_when_no_matching_cluster(configured_capella):
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        _stub_discovery(mock, cluster_host="cb.different.cloud.couchbase.com")
        # bucket POST should never be called

        with pytest.raises(RuntimeError, match="No Capella cluster matched host"):
            await cms.ensure_bucket("realtime-rag")


def test_extract_host_strips_scheme_path_query_port():
    assert (
        cms._extract_host("couchbases://cb.abc.cloud.couchbase.com")
        == "cb.abc.cloud.couchbase.com"
    )
    assert (
        cms._extract_host("couchbases://cb.abc.cloud.couchbase.com:11207")
        == "cb.abc.cloud.couchbase.com"
    )
    assert (
        cms._extract_host(
            "couchbases://cb.abc.cloud.couchbase.com/path?ssl=true"
        )
        == "cb.abc.cloud.couchbase.com"
    )
    assert cms._extract_host("CB.ABC.cloud.couchbase.com") == "cb.abc.cloud.couchbase.com"


def test_normalize_if_match_strips_version_prefix():
    """Capella's ``Version: N`` ETag must be reduced to bare ``N`` for PUT.

    Empirically: ``If-Match: Version: 1`` → 500; ``If-Match: 1`` → 204.
    """
    assert cms._normalize_if_match("Version: 1") == "1"
    assert cms._normalize_if_match("Version: 42") == "42"
    assert cms._normalize_if_match("version: 3") == "3"  # case-insensitive
    assert cms._normalize_if_match("  Version: 7  ") == "7"  # whitespace trimmed
    # Non-decorated values pass through unchanged
    assert cms._normalize_if_match('"abc123"') == '"abc123"'
    assert cms._normalize_if_match("") == ""
    assert cms._normalize_if_match(None) == ""


def test_is_configured_requires_both_id_and_token(monkeypatch):
    monkeypatch.setattr(cms.config.settings, "capella_api_key_id", "")
    monkeypatch.setattr(cms.config.settings, "capella_api_key_token", "")
    assert cms.is_configured() is False

    monkeypatch.setattr(cms.config.settings, "capella_api_key_id", "x")
    assert cms.is_configured() is False

    monkeypatch.setattr(cms.config.settings, "capella_api_key_token", "y")
    assert cms.is_configured() is True


async def test_ensure_bucket_skips_when_not_configured(monkeypatch):
    monkeypatch.setattr(cms.config.settings, "capella_api_key_id", "")
    monkeypatch.setattr(cms.config.settings, "capella_api_key_token", "")
    with pytest.raises(RuntimeError, match="API key not configured"):
        await cms.ensure_bucket("anything")


async def test_ensure_user_creates_when_missing(configured_capella):
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        _stub_discovery(mock, cluster_host="cb.abc.cloud.couchbase.com")
        user_route = mock.post(
            f"{CAPELLA_BASE}/v4/organizations/org1/projects/proj1"
            f"/clusters/cluster1/users"
        ).mock(return_value=httpx.Response(201, json={"id": "user-1"}))

        await cms.ensure_user("rag_app", "rag_app_secret", "realtime-rag")

        assert user_route.called
        body = user_route.calls[0].request.read()
        assert b'"name":"rag_app"' in body
        assert b'"password":"rag_app_secret"' in body
        assert b'"data_reader"' in body and b'"data_writer"' in body
        assert b'"name":"realtime-rag"' in body


async def test_ensure_user_idempotent_when_access_already_grants_bucket(
    configured_capella,
):
    """POST 409 -> GET /users -> bucket already in access -> no PUT."""
    cluster_path = (
        f"{CAPELLA_BASE}/v4/organizations/org1/projects/proj1"
        f"/clusters/cluster1"
    )
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        _stub_discovery(mock, cluster_host="cb.abc.cloud.couchbase.com")
        mock.post(f"{cluster_path}/users").mock(
            return_value=httpx.Response(409, json={"error": "user exists"})
        )
        mock.get(f"{cluster_path}/users").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "user-1",
                            "name": "rag_app",
                            "access": [
                                {
                                    "privileges": ["data_reader", "data_writer"],
                                    "resources": {
                                        "buckets": [{"name": "realtime-rag"}]
                                    },
                                }
                            ],
                        }
                    ]
                },
            )
        )
        # GET /users/{id} and PUT must NOT be called when access already grants
        # the bucket -- assert_all_called=True ensures we didn't stub anything
        # extra that goes unused.

        await cms.ensure_user("rag_app", "rag_app_secret", "realtime-rag")


async def test_ensure_user_patches_access_on_existing_user(configured_capella):
    """POST 422 -> GET /users -> bucket missing -> GET /users/{id} -> PUT.

    The new bucket must be folded into the existing read+write access
    entry rather than appended as a separate entry — Capella's PUT
    rejects (500) bodies that have two access entries sharing the
    same privilege set.
    """
    cluster_path = (
        f"{CAPELLA_BASE}/v4/organizations/org1/projects/proj1"
        f"/clusters/cluster1"
    )
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        _stub_discovery(mock, cluster_host="cb.abc.cloud.couchbase.com")
        mock.post(f"{cluster_path}/users").mock(
            return_value=httpx.Response(422, json={"error": "user exists"})
        )
        mock.get(f"{cluster_path}/users").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "user-1",
                            "name": "rag_app",
                            "access": [
                                {
                                    "privileges": ["data_reader", "data_writer"],
                                    "resources": {
                                        "buckets": [{"name": "other-bucket"}]
                                    },
                                }
                            ],
                        }
                    ]
                },
            )
        )
        mock.get(f"{cluster_path}/users/user-1").mock(
            return_value=httpx.Response(
                200,
                headers={"etag": "Version: 1"},
                json={
                    "id": "user-1",
                    "name": "rag_app",
                    "access": [
                        {
                            "privileges": ["data_reader", "data_writer"],
                            "resources": {"buckets": [{"name": "other-bucket"}]},
                        }
                    ],
                },
            )
        )
        put_route = mock.put(f"{cluster_path}/users/user-1").mock(
            return_value=httpx.Response(204)
        )

        await cms.ensure_user("rag_app", "rag_app_secret", "realtime-rag")

        assert put_route.called
        put_call = put_route.calls[0]
        # Capella's GET returns ETag as "Version: N" but its own PUT
        # parser 500s on that shape — only the bare numeric form works,
        # which matches the OpenAPI spec's If-Match example ("12").
        assert put_call.request.headers.get("If-Match") == "1"
        import json

        sent = json.loads(put_call.request.read())
        # Canonical shape: one access entry per privilege set, both
        # buckets grouped under its resources.buckets list.
        assert len(sent["access"]) == 1
        entry = sent["access"][0]
        assert sorted(entry["privileges"]) == ["data_reader", "data_writer"]
        bucket_names = {b["name"] for b in entry["resources"]["buckets"]}
        assert bucket_names == {"other-bucket", "realtime-rag"}


async def test_ensure_user_strips_wildcard_scopes_from_echoed_access(
    configured_capella,
):
    """Server-side ``scopes:[{"name":"*"}]`` wildcard must be stripped before PUT.

    Capella's GET /users response decorates bucket entries with a
    ``*``-scope marker for "all scopes". Re-submitting that wildcard
    in PUT triggers a server 500, so the merged body sent to PUT
    must drop ``scopes`` whenever the only entry is the wildcard.
    """
    cluster_path = (
        f"{CAPELLA_BASE}/v4/organizations/org1/projects/proj1"
        f"/clusters/cluster1"
    )
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        _stub_discovery(mock, cluster_host="cb.abc.cloud.couchbase.com")
        mock.post(f"{cluster_path}/users").mock(
            return_value=httpx.Response(422, json={"error": "user exists"})
        )
        mock.get(f"{cluster_path}/users").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "user-1",
                            "name": "rag_app",
                            "access": [
                                {
                                    "privileges": ["data_reader", "data_writer"],
                                    "resources": {
                                        "buckets": [
                                            {
                                                "name": "other-bucket",
                                                "scopes": [{"name": "*"}],
                                            }
                                        ]
                                    },
                                }
                            ],
                        }
                    ]
                },
            )
        )
        mock.get(f"{cluster_path}/users/user-1").mock(
            return_value=httpx.Response(
                200,
                headers={"etag": "Version: 1"},
                json={
                    "id": "user-1",
                    "name": "rag_app",
                    "access": [
                        {
                            "privileges": ["data_reader", "data_writer"],
                            "resources": {
                                "buckets": [
                                    {
                                        "name": "other-bucket",
                                        "scopes": [{"name": "*"}],
                                    }
                                ]
                            },
                        }
                    ],
                },
            )
        )
        put_route = mock.put(f"{cluster_path}/users/user-1").mock(
            return_value=httpx.Response(204)
        )

        await cms.ensure_user("rag_app", "rag_app_secret", "realtime-rag")

        assert put_route.called
        body = put_route.calls[0].request.read()
        # Wildcard-only scopes entry stripped from echoed bucket
        assert b'"name":"*"' not in body
        assert b'"scopes"' not in body
        # Both buckets present in the merged access body
        assert b'"name":"other-bucket"' in body
        assert b'"name":"realtime-rag"' in body


async def test_ensure_user_preserves_explicit_scopes_in_echoed_access(
    configured_capella,
):
    """Real scope names (not ``*`` wildcards) must be preserved in the PUT body."""
    cluster_path = (
        f"{CAPELLA_BASE}/v4/organizations/org1/projects/proj1"
        f"/clusters/cluster1"
    )
    with respx.mock(base_url=CAPELLA_BASE, assert_all_called=True) as mock:
        _stub_discovery(mock, cluster_host="cb.abc.cloud.couchbase.com")
        mock.post(f"{cluster_path}/users").mock(
            return_value=httpx.Response(422, json={"error": "user exists"})
        )
        explicit_access = [
            {
                "privileges": ["data_reader", "data_writer"],
                "resources": {
                    "buckets": [
                        {
                            "name": "other-bucket",
                            "scopes": [
                                {"name": "inventory", "collections": ["airline"]}
                            ],
                        }
                    ]
                },
            }
        ]
        mock.get(f"{cluster_path}/users").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "user-1", "name": "rag_app", "access": explicit_access}
                    ]
                },
            )
        )
        mock.get(f"{cluster_path}/users/user-1").mock(
            return_value=httpx.Response(
                200,
                headers={"etag": "Version: 1"},
                json={
                    "id": "user-1",
                    "name": "rag_app",
                    "access": explicit_access,
                },
            )
        )
        put_route = mock.put(f"{cluster_path}/users/user-1").mock(
            return_value=httpx.Response(204)
        )

        await cms.ensure_user("rag_app", "rag_app_secret", "realtime-rag")

        body = put_route.calls[0].request.read()
        assert b'"name":"inventory"' in body
        assert b'"airline"' in body


async def test_ensure_user_raises_when_not_configured(monkeypatch):
    monkeypatch.setattr(cms.config.settings, "capella_api_key_id", "")
    monkeypatch.setattr(cms.config.settings, "capella_api_key_token", "")
    with pytest.raises(RuntimeError, match="API key not configured"):
        await cms.ensure_user("rag_app", "rag_app_secret", "realtime-rag")
