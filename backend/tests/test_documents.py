import io

import pytest


@pytest.fixture
def fake_pdf_bytes() -> bytes:
    # Minimal PDF signature so python-magic identifies it as application/pdf
    # even though the rest of the file is a stub.
    return b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n" + b"stub content " * 64 + b"\n%%EOF\n"


def test_list_documents_requires_auth(client):
    resp = client.get("/api/documents")
    assert resp.status_code == 401


def test_list_documents_returns_array(client, auth_headers):
    resp = client.get("/api/documents", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_upload_rejects_unsupported_extension(client, auth_headers):
    resp = client.post(
        "/api/documents/upload",
        headers=auth_headers,
        files={"file": ("bad.exe", io.BytesIO(b"MZ\x90"), "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_upload_rejects_content_type_mismatch(client, auth_headers):
    # .pdf extension but plain-text content — MIME detection should reject.
    resp = client.post(
        "/api/documents/upload",
        headers=auth_headers,
        files={"file": ("hello.pdf", io.BytesIO(b"this is plain text"), "application/pdf")},
    )
    assert resp.status_code == 400


def test_upload_accepts_real_pdf_signature(client, auth_headers, mocker, fake_pdf_bytes):
    from services import document_service

    mocker.patch.object(document_service, "extract_and_store", return_value=7)

    async def _noop_embed(*args, **kwargs):
        return None

    mocker.patch.object(document_service, "generate_embeddings", _noop_embed)

    resp = client.post(
        "/api/documents/upload",
        headers=auth_headers,
        files={"file": ("report.pdf", io.BytesIO(fake_pdf_bytes), "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "report.pdf"
    assert body["chunk_count"] == 7
    assert body["status"] == "vectorizing"


def test_upload_sanitizes_path_traversal(client, auth_headers, mocker, fake_pdf_bytes):
    from services import document_service

    mocker.patch.object(document_service, "extract_and_store", return_value=1)

    async def _noop_embed(*args, **kwargs):
        return None

    mocker.patch.object(document_service, "generate_embeddings", _noop_embed)

    resp = client.post(
        "/api/documents/upload",
        headers=auth_headers,
        files={
            "file": (
                "../../etc/passwd.pdf",
                io.BytesIO(fake_pdf_bytes),
                "application/pdf",
            ),
        },
    )
    assert resp.status_code == 200
    # The stored filename must have no path fragments left.
    assert "/" not in resp.json()["filename"]
    assert ".." not in resp.json()["filename"]


def test_status_reports_unknown_for_new_file(client, auth_headers):
    resp = client.get("/api/documents/status/nothing.pdf", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "unknown"


def test_delete_calls_service(client, auth_headers, mocker):
    from services import couchbase_service

    spy = mocker.patch.object(couchbase_service, "delete_documents_by_filename")
    resp = client.delete("/api/documents/report.pdf", headers=auth_headers)
    assert resp.status_code == 200
    spy.assert_called_once_with("report.pdf")
