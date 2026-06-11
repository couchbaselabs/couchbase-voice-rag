import asyncio
import logging

import magic
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
)

from middleware.auth import get_current_user
from models.common import OkResponse
from models.documents import (
    DocumentSummary,
    JobStatusResponse,
    UploadResponse,
)
from services import couchbase_service, document_service
from utils.filenames import safe_filename

logger = logging.getLogger(__name__)

router = APIRouter()

EXT_TO_MIME = {
    ".pdf": {"application/pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
    ".txt": {"text/plain"},
}
ALLOWED_EXTENSIONS = frozenset(EXT_TO_MIME)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
_READ_CHUNK = 1 * 1024 * 1024  # 1 MB


async def _read_upload_within_limit(file: UploadFile, limit: int) -> bytes:
    """Read the upload in chunks, rejecting with HTTP 413 when over ``limit``."""
    buffer = bytearray()
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {limit // (1024 * 1024)}MB.",
            )
    return bytes(buffer)


def _sanitized_filename(raw: str) -> str:
    try:
        return safe_filename(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "",
    response_model=list[DocumentSummary],
    summary="List uploaded documents",
)
def list_documents(username: str = Depends(get_current_user)):
    """Aggregate stored chunks by source filename and return per-document summaries."""
    return couchbase_service.list_uploaded_files()


@router.post(
    "/upload",
    response_model=UploadResponse,
    summary="Upload a PDF/DOCX/TXT document",
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    username: str = Depends(get_current_user),
):
    """Validate, store, and schedule embedding generation for an uploaded document."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    filename = _sanitized_filename(file.filename)

    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Supported file types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    file_bytes = await _read_upload_within_limit(file, MAX_FILE_SIZE)

    detected_mime = magic.from_buffer(file_bytes[:4096], mime=True)
    if detected_mime not in EXT_TO_MIME[ext]:
        logger.warning(
            "Rejected upload %r: declared ext=%s but detected mime=%s",
            filename, ext, detected_mime,
        )
        raise HTTPException(
            status_code=400,
            detail="File content does not match the declared extension.",
        )

    chunk_count = await asyncio.to_thread(
        document_service.extract_and_store, filename, file_bytes
    )

    background_tasks.add_task(
        document_service.generate_embeddings, filename, file_bytes
    )

    return UploadResponse(filename=filename, chunk_count=chunk_count)


@router.get(
    "/status/{filename:path}",
    response_model=JobStatusResponse,
    summary="Check embedding-generation status",
)
def get_upload_status(
    filename: str,
    username: str = Depends(get_current_user),
):
    """Return the lifecycle state of the background embedding job for ``filename``."""
    return document_service.get_job_status(_sanitized_filename(filename))


@router.delete(
    "/{filename:path}",
    response_model=OkResponse,
    summary="Delete a document and its chunks",
)
def delete_document(
    filename: str,
    username: str = Depends(get_current_user),
):
    """Remove every stored chunk whose ``source_filename`` matches ``filename``."""
    couchbase_service.delete_documents_by_filename(_sanitized_filename(filename))
    return OkResponse()
