"""Capella Management API client for project / cluster / bucket operations.

Hosts the auto-discovery helpers (``get_org_id`` / ``get_project_id`` /
``get_cluster_id``) that were previously embedded in
``capella_ai_service`` so that bucket provisioning and AI Workflows
share the same lookup logic and caches.

The Settings UI never asks the user for org/project/cluster IDs — the
API key alone suffices when the key has read access to the parent
project. ``CB_CONNECTION_STRING`` is matched against each cluster's
own ``connectionString`` so the right cluster is picked even in
multi-cluster projects.
"""

import logging
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

CAPELLA_BASE = "https://cloudapi.cloud.couchbase.com"
_HTTP_TIMEOUT = httpx.Timeout(30.0)

_discovered: dict[str, str] = {}


def is_configured() -> bool:
    """Whether a Capella Management API key is available for this process."""
    return bool(
        config.settings.capella_api_key_id and config.settings.capella_api_key_token
    )


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.settings.capella_api_key_token}",
        "Content-Type": "application/json",
    }


def _extract_host(connection_string: str) -> str:
    """Reduce a Couchbase connection string to its bare hostname (no scheme/port/path)."""
    s = connection_string.split("//", 1)[-1]
    s = s.split("/", 1)[0]
    s = s.split("?", 1)[0]
    s = s.split(":", 1)[0]
    return s.lower()


async def get_org_id(client: httpx.AsyncClient) -> str:
    """Return the Capella organization ID, preferring env override then cache then API."""
    if config.settings.capella_org_id:
        return config.settings.capella_org_id
    if "org_id" in _discovered:
        return _discovered["org_id"]

    resp = await client.get(f"{CAPELLA_BASE}/v4/organizations", headers=_headers())
    resp.raise_for_status()
    orgs = resp.json().get("data") or []
    if not orgs:
        raise RuntimeError("No Capella organizations visible to this API key")
    org_id = orgs[0]["id"]
    _discovered["org_id"] = org_id
    logger.info("Auto-discovered Capella org: %s", org_id)
    return org_id


async def get_project_id(client: httpx.AsyncClient) -> str:
    """Return the Capella project ID, preferring env override then cache then API."""
    if config.settings.capella_project_id:
        return config.settings.capella_project_id
    if "project_id" in _discovered:
        return _discovered["project_id"]

    org_id = await get_org_id(client)
    resp = await client.get(
        f"{CAPELLA_BASE}/v4/organizations/{org_id}/projects",
        headers=_headers(),
    )
    resp.raise_for_status()
    projects = resp.json().get("data") or []
    if not projects:
        raise RuntimeError("No Capella projects visible to this API key")
    project_id = projects[0]["id"]
    _discovered["project_id"] = project_id
    logger.info("Auto-discovered Capella project: %s", project_id)
    return project_id


async def get_cluster_id(client: httpx.AsyncClient) -> str:
    """Return the cluster ID whose ``connectionString`` host matches CB_CONNECTION_STRING."""
    if config.settings.capella_cluster_id:
        return config.settings.capella_cluster_id
    if "cluster_id" in _discovered:
        return _discovered["cluster_id"]

    org_id = await get_org_id(client)
    project_id = await get_project_id(client)
    resp = await client.get(
        f"{CAPELLA_BASE}/v4/organizations/{org_id}/projects/{project_id}/clusters",
        headers=_headers(),
    )
    resp.raise_for_status()
    clusters = resp.json().get("data") or []
    if not clusters:
        raise RuntimeError("No Capella clusters visible to this API key")

    target_host = _extract_host(config.settings.cb_connection_string)
    for c in clusters:
        cs = c.get("connectionString", "")
        if cs and _extract_host(cs) == target_host:
            cluster_id = c["id"]
            _discovered["cluster_id"] = cluster_id
            logger.info(
                "Matched Capella cluster %s by hostname %s", cluster_id, target_host
            )
            return cluster_id

    raise RuntimeError(
        f"No Capella cluster matched host {target_host!r} — "
        "set CB_CONNECTION_STRING to a cluster owned by this API key"
    )


async def ensure_bucket(name: str, ram_quota_mb: int = 256) -> None:
    """Create the Capella bucket if missing; idempotent on already-exists responses.

    Caller must have a valid Capella Management API key
    (``is_configured()`` true). The bucket is created with sensible
    demo defaults: type ``couchbase``, durability
    ``majorityAndPersistActive``, 1 replica.
    """
    if not is_configured():
        raise RuntimeError("Capella API key not configured")

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        org_id = await get_org_id(client)
        project_id = await get_project_id(client)
        cluster_id = await get_cluster_id(client)
        url = (
            f"{CAPELLA_BASE}/v4/organizations/{org_id}/projects/{project_id}"
            f"/clusters/{cluster_id}/buckets"
        )
        body: dict[str, Any] = {
            "name": name,
            "type": "couchbase",
            "memoryAllocationInMb": ram_quota_mb,
            "bucketConflictResolution": "seqno",
            "durabilityLevel": "majorityAndPersistActive",
            "replicas": 1,
            "flush": False,
            "storageBackend": "couchstore",
        }
        resp = await client.post(url, headers=_headers(), json=body)
        if resp.status_code in (200, 201):
            logger.info("Created Capella bucket %r in cluster %s", name, cluster_id)
            return
        if resp.status_code in (409, 422):
            logger.debug(
                "Capella bucket %r already exists (status %s) — continuing",
                name,
                resp.status_code,
            )
            return
        resp.raise_for_status()


def _normalize_if_match(etag: str | None) -> str:
    """Convert Capella's ``Version: N`` ETag into the bare ``N`` form for If-Match.

    Empirically confirmed against the live Capella v4 API:
    ``GET /users/{id}`` returns ``ETag: Version: 1`` (literal string with
    space-after-colon), but ``PUT /users/{id}`` with
    ``If-Match: Version: 1`` returns HTTP 500. Omitting If-Match or
    sending just ``If-Match: 1`` both succeed with 204. The Capella
    OpenAPI spec's ``If-Match`` parameter example is also a bare numeric
    string (``"12"``), so the GET-decorated ``Version: N`` form is not
    round-trippable — the server-side parser appears to choke on the
    space before the number.

    We strip the prefix so the value we send matches the documented
    If-Match shape and preserves optimistic concurrency. If the ETag
    doesn't match the ``Version: N`` pattern we return it unchanged.
    """
    if not etag:
        return ""
    stripped = etag.strip()
    lowered = stripped.lower()
    if lowered.startswith("version:"):
        return stripped.split(":", 1)[1].strip()
    return stripped


def _strip_wildcard_scopes(access: list[dict]) -> list[dict]:
    """Drop the ``scopes:[{"name":"*"}]`` decoration from echoed entries.

    Capella's ``GET /users`` decorates each ``ResourceBucket`` with
    ``scopes:[{"name":"*"}]`` to mean "all scopes" when the credential
    was created without an explicit scope selection. The official
    OpenAPI spec (operation ``getDatabaseCredential``) does not list
    ``*`` as a valid ``ResourceScope.name`` value — it is a GET-only
    decoration. Per the same spec, ``ResourceBucket.scopes`` is
    optional and absence is the canonical encoding for "all scopes"
    (``Access.resources`` description: "Leaving this empty will grant
    access to all buckets"). Submitting the wildcard back in a PUT
    body is therefore a round-tripping bug; we drop the field so the
    PUT uses the documented "absence == all scopes" encoding.
    """
    cleaned: list[dict] = []
    for entry in access:
        new_entry = dict(entry)
        resources = dict(entry.get("resources") or {})
        buckets = resources.get("buckets") or []
        new_buckets: list[dict] = []
        for b in buckets:
            nb = dict(b)
            scopes = nb.get("scopes") or []
            if scopes and all(
                (s or {}).get("name") == "*" and not (s or {}).get("collections")
                for s in scopes
            ):
                nb.pop("scopes", None)
            new_buckets.append(nb)
        if "resources" in entry:
            resources["buckets"] = new_buckets
            new_entry["resources"] = resources
        cleaned.append(new_entry)
    return cleaned


def _merge_bucket_into_access(
    current_access: list[dict],
    bucket: str,
    privileges: list[str],
) -> list[dict]:
    """Add ``bucket`` to the access entry that already grants ``privileges``.

    The Capella OpenAPI spec models ``Access.resources.buckets`` as an
    array of ``ResourceBucket`` and the documented examples for
    ``postDatabaseCredential`` use one ``Access`` entry per privilege
    set (e.g. the ``SeparateAccessForDifferentScopes`` example has
    distinct ``data_reader`` and ``data_writer`` entries). The spec
    contains no example where two entries share the same privilege set
    — granting the same privileges across multiple buckets is meant to
    be expressed as a single entry with multiple items in
    ``resources.buckets``. ``GET /users`` returns the same canonical
    shape: one entry per unique privilege set.

    To honour that canonical shape, we look for an existing entry with
    the same privilege set and append the bucket to its bucket list;
    only when no such entry exists do we add a fresh ``Access``
    object. Entries with other privilege sets are preserved verbatim.
    """
    priv_key = frozenset(privileges)
    cleaned = _strip_wildcard_scopes(current_access)
    merged: list[dict] = []
    appended = False
    for entry in cleaned:
        entry_privs = frozenset(entry.get("privileges") or [])
        if not appended and entry_privs == priv_key:
            new_entry = dict(entry)
            resources = dict(entry.get("resources") or {})
            buckets = list(resources.get("buckets") or [])
            buckets.append({"name": bucket})
            resources["buckets"] = buckets
            new_entry["resources"] = resources
            merged.append(new_entry)
            appended = True
        else:
            merged.append(entry)
    if not appended:
        merged.append({
            "privileges": list(privileges),
            "resources": {"buckets": [{"name": bucket}]},
        })
    return merged


async def _sync_user_access(
    client: httpx.AsyncClient,
    cluster_path: str,
    username: str,
    bucket: str,
) -> None:
    """Ensure ``username`` has data_reader+data_writer on ``bucket``.

    Called from ensure_user when POST /users returns 409/422
    (already exists). Fetches the existing user definition, checks
    whether the target bucket is already in any access entry, and
    PUTs an updated user with the bucket merged into the existing
    read+write access entry (or a fresh entry if none yet has that
    privilege set). Existing access entries with other privilege
    sets are preserved so sharing the same credential across
    multiple demos / sandboxes on one cluster doesn't strip other
    grants.
    """
    list_resp = await client.get(f"{cluster_path}/users", headers=_headers())
    list_resp.raise_for_status()
    users = list_resp.json().get("data", [])
    target = next((u for u in users if u.get("name") == username), None)
    if target is None:
        logger.warning(
            "User %r reported already-exists but not found in /users; "
            "skipping access sync",
            username,
        )
        return

    user_id = target["id"]
    current_access = target.get("access") or []
    already_granted = any(
        b.get("name") == bucket
        for entry in current_access
        for b in (entry.get("resources") or {}).get("buckets") or []
    )
    if already_granted:
        logger.debug(
            "Capella user %r already has access to bucket %r — skipping update",
            username, bucket,
        )
        return

    detail_resp = await client.get(
        f"{cluster_path}/users/{user_id}", headers=_headers()
    )
    detail_resp.raise_for_status()
    etag = detail_resp.headers.get("etag") or detail_resp.headers.get("ETag")

    new_access = _merge_bucket_into_access(
        list(current_access), bucket, ["data_reader", "data_writer"]
    )
    put_headers = dict(_headers())
    if_match = _normalize_if_match(etag)
    if if_match:
        put_headers["If-Match"] = if_match

    put_resp = await client.put(
        f"{cluster_path}/users/{user_id}",
        headers=put_headers,
        json={"access": new_access},
    )
    put_resp.raise_for_status()
    logger.info(
        "Granted Capella user %r access to bucket %r",
        username, bucket,
    )


async def ensure_user(username: str, password: str, bucket: str) -> None:
    """Create a Capella database user with read+write access to ``bucket``.

    Idempotent on already-exists responses (409 / 422). Caller must have
    a valid Capella Management API key (``is_configured()`` true).
    """
    if not is_configured():
        raise RuntimeError("Capella API key not configured")

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        org_id = await get_org_id(client)
        project_id = await get_project_id(client)
        cluster_id = await get_cluster_id(client)
        url = (
            f"{CAPELLA_BASE}/v4/organizations/{org_id}/projects/{project_id}"
            f"/clusters/{cluster_id}/users"
        )
        body: dict[str, Any] = {
            "name": username,
            "password": password,
            "access": [
                {
                    "privileges": ["data_reader", "data_writer"],
                    "resources": {
                        "buckets": [{"name": bucket}],
                    },
                }
            ],
        }
        resp = await client.post(url, headers=_headers(), json=body)
        if resp.status_code in (200, 201):
            logger.info(
                "Created Capella DB user %r in cluster %s", username, cluster_id
            )
            return
        if resp.status_code in (409, 422):
            logger.debug(
                "Capella DB user %r already exists (status %s) — syncing access policy",
                username,
                resp.status_code,
            )
            cluster_path = (
                f"{CAPELLA_BASE}/v4/organizations/{org_id}"
                f"/projects/{project_id}/clusters/{cluster_id}"
            )
            await _sync_user_access(client, cluster_path, username, bucket)
            return
        resp.raise_for_status()
