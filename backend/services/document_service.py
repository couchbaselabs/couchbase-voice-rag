import asyncio
import io
import logging
import re
import threading
import time
from collections import Counter

from docx import Document
from pypdf import PdfReader

from services import capella_ai_service, couchbase_service, embedding_service
from utils.text_splitter import split_text

logger = logging.getLogger(__name__)


def extract_text(filename: str, file_bytes: bytes) -> str:
    """Return the text content of a PDF/DOCX/TXT upload; raise on other extensions."""
    name = filename.lower()

    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if name.endswith(".docx"):
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs)

    if name.endswith(".txt"):
        return file_bytes.decode("utf-8")

    raise ValueError(f"Unsupported file type: {name}")


def extract_vocabulary(chunks: list[str], max_terms: int = 50) -> list[str]:
    """Pick likely technical terms (acronyms + CamelCase + capitalized) for STT hinting."""
    text = " ".join(chunks)
    # Uppercase acronyms (2+ chars): XDCR, CAS, N1QL, SQL++, etc.
    acronyms = re.findall(r'\b[A-Z][A-Z0-9+]{1,}(?:\+\+)?\b', text)
    # CamelCase words: MapReduce, BucketManager, etc.
    camel = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b', text)
    # Capitalized technical terms
    capitalized = re.findall(r'\b[A-Z][a-z]{2,}\b', text)

    counts = Counter(acronyms + camel)
    common = {"The", "This", "That", "These", "Those", "Here", "There", "What",
              "When", "Where", "Which", "How", "Each", "Every", "Some", "Most",
              "Many", "Much", "Very", "Also", "However", "For", "With", "From",
              "Into", "About", "After", "Before", "Between", "Through", "During",
              "Without", "Within", "Along", "Among", "Beyond", "Since", "Until",
              "Upon", "Across", "Against", "Below", "Beneath", "Beside", "Besides",
              "But", "Not", "All", "Any", "Both", "Few", "More", "Other", "Such"}
    for word in capitalized:
        if word not in common and len(word) > 2:
            counts[word] += 1

    return [term for term, _ in counts.most_common(max_terms)]


# In-memory job status. Protected by a threading.Lock so sync endpoints
# (running in FastAPI's threadpool) and async background tasks (running on
# the event loop) can both mutate it safely. Entries in terminal states
# are garbage-collected lazily after JOB_STATUS_TTL_SECONDS.
_JOB_STATUS_TTL_SECONDS = 3600
_TERMINAL_STATUSES = {"completed", "failed"}
_job_status: dict[str, dict] = {}
_job_status_lock = threading.Lock()


def _set_job_status(filename: str, value: dict) -> None:
    value = dict(value)
    if value.get("status") in _TERMINAL_STATUSES:
        value["_finished_at"] = time.monotonic()
    with _job_status_lock:
        _job_status[filename] = value


def _gc_job_status_locked() -> None:
    now = time.monotonic()
    stale = [
        name
        for name, entry in _job_status.items()
        if entry.get("status") in _TERMINAL_STATUSES
        and now - entry.get("_finished_at", now) > _JOB_STATUS_TTL_SECONDS
    ]
    for name in stale:
        del _job_status[name]


def get_job_status(filename: str) -> dict:
    """Return the embedding-pipeline status for ``filename`` (or ``{"status": "unknown"}``)."""
    with _job_status_lock:
        _gc_job_status_locked()
        entry = _job_status.get(filename)
    if not entry:
        return {"status": "unknown"}
    # Hide internal bookkeeping from API consumers.
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def extract_and_store(filename: str, file_bytes: bytes) -> int:
    """Synchronous: extract text, chunk, store WITHOUT embeddings. Returns chunk count."""
    text = extract_text(filename, file_bytes)
    chunks = split_text(text)
    if not chunks:
        return 0

    for i, chunk in enumerate(chunks):
        doc_id = f"{filename}_chunk_{i}"
        metadata = {
            "source_filename": filename,
            "chunk_index": i,
            "embedding_method": "pending",
        }
        couchbase_service.upsert_document_text(doc_id, chunk, filename, metadata)

    # Extract vocabulary
    new_vocab = extract_vocabulary(chunks)
    if new_vocab:
        existing = couchbase_service.load_vocabulary_hints()
        merged = list(dict.fromkeys(existing + new_vocab))[:100]
        couchbase_service.save_vocabulary_hints(merged)

    _set_job_status(filename, {"status": "vectorizing", "chunk_count": len(chunks)})
    return len(chunks)


def _update_capella_metadata_sync(filename: str, chunk_count: int, workflow_id: str) -> None:
    """Stamp every chunk with embedding_method=capella in a single N1QL round-trip.

    The ``chunk_count`` parameter is kept for backward compatibility with
    callers — the underlying query updates by ``source_filename`` so the
    explicit count is no longer needed.
    """
    couchbase_service.stamp_capella_metadata(filename, workflow_id)


def _run_local_embedding_sync(filename: str, chunks: list[str]) -> None:
    embeddings = embedding_service.get_embeddings_batch(chunks)
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        doc_id = f"{filename}_chunk_{i}"
        metadata = {
            "source_filename": filename,
            "chunk_index": i,
            "embedding_method": "local",
        }
        couchbase_service.upsert_document(doc_id, chunk, emb, metadata)


async def _poll_capella_progress(
    filename: str, total: int, stop: asyncio.Event,
) -> None:
    """Push per-second, file-specific progress into _job_status while a Capella run is in flight.

    Capella's workflow-run API does not expose per-chunk progress for
    vectorization workflows (the runs subresource is permission-denied
    for that type), so we derive progress from Couchbase directly: count
    how many of this filename's chunks already have an ``embedding``
    field. The frontend's polling endpoint then sees real
    ``processed_files`` / ``total_files`` increments per poll and
    switches the progress bar from indeterminate shimmer to a
    determinate filling bar.
    """
    while not stop.is_set():
        try:
            processed = await asyncio.to_thread(
                couchbase_service.count_embedded_chunks_by_filename, filename,
            )
        except Exception:
            logger.exception("progress poll for %r failed (continuing)", filename)
            processed = 0
        _set_job_status(filename, {
            "status": "vectorizing",
            "chunk_count": total,
            "method": "capella",
            "processed_files": processed,
            "total_files": total,
        })
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


async def generate_embeddings(filename: str, file_bytes: bytes) -> None:
    """Background task: generate embeddings via Capella or local Python.

    Runs on the event loop; blocking SDK calls are dispatched to a worker
    thread so a long embedding job does not stall other requests.
    """
    try:
        text = await asyncio.to_thread(extract_text, filename, file_bytes)
        chunks = split_text(text)
        if not chunks:
            _set_job_status(filename, {"status": "completed", "chunk_count": 0})
            return

        if capella_ai_service.is_configured():
            logger.info("Using Capella AI Services for '%s'", filename)
            try:
                workflow_id = await capella_ai_service.get_or_create_workflow()
                run_id = await capella_ai_service.run_workflow(workflow_id)

                stop_progress = asyncio.Event()
                progress_task = asyncio.create_task(
                    _poll_capella_progress(filename, len(chunks), stop_progress)
                )
                try:
                    await capella_ai_service.wait_for_run(workflow_id, run_id)
                finally:
                    stop_progress.set()
                    await progress_task

                await asyncio.to_thread(
                    _update_capella_metadata_sync,
                    filename, len(chunks), workflow_id,
                )
                _set_job_status(
                    filename,
                    {
                        "status": "completed",
                        "chunk_count": len(chunks),
                        "method": "capella",
                    },
                )
                logger.info("Capella embedding completed for '%s'", filename)
                return
            except Exception as e:
                logger.warning(
                    "Capella failed for '%s': %s. Falling back to local.",
                    filename, e,
                )

        logger.info("Using local embedding for '%s'", filename)
        await asyncio.to_thread(_run_local_embedding_sync, filename, chunks)
        _set_job_status(
            filename,
            {"status": "completed", "chunk_count": len(chunks), "method": "local"},
        )
        logger.info("Local embedding completed for '%s'", filename)

    except Exception as e:
        logger.error("Embedding failed for '%s': %s", filename, e)
        _set_job_status(filename, {"status": "failed", "error": str(e)})
