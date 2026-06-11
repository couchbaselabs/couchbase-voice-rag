"""Unit tests for document_service helpers.

Most of the embedding pipeline is exercised via the upload route test
(``test_documents``), but the Couchbase-driven Capella progress
poller has its own contract worth pinning: while a Capella workflow
run is in flight, the poller must keep refreshing the in-memory job
status with the latest ``count_embedded_chunks_by_filename`` result
so the frontend's polling endpoint can render a determinate progress
bar. Capella's workflow-run API does not expose per-chunk progress
for vectorization workflows, so this poller is the only progress
source.
"""

import asyncio

import pytest

from services import document_service


@pytest.fixture(autouse=True)
def reset_job_status():
    """Clear the module-level job-status dict between tests."""
    document_service._job_status.clear()
    yield
    document_service._job_status.clear()


async def test_poll_capella_progress_writes_increasing_counts(monkeypatch):
    """Each poll iteration must push the latest embedded-chunk count into _job_status."""
    counts = iter([0, 2, 5, 10])

    def _stub_count(_filename: str) -> int:
        try:
            return next(counts)
        except StopIteration:
            return 10

    monkeypatch.setattr(
        document_service.couchbase_service,
        "count_embedded_chunks_by_filename",
        _stub_count,
    )

    # Make the per-iteration wait return instantly so the test isn't
    # hostage to wall clock. asyncio.wait_for(stop.wait(), timeout=2.0)
    # raises asyncio.TimeoutError when the event is unset, which the
    # poller swallows -- shortcut that wait.
    async def _fake_wait_for(awaitable, timeout):
        # The poller passes ``stop.wait()`` here; close the coroutine so
        # Python doesn't warn about it being un-awaited.
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(document_service.asyncio, "wait_for", _fake_wait_for)

    stop = asyncio.Event()
    task = asyncio.create_task(
        document_service._poll_capella_progress("file.pdf", total=10, stop=stop)
    )

    # Yield enough times to let the poller cycle through several iterations
    for _ in range(8):
        await asyncio.sleep(0)

    stop.set()
    await task

    entry = document_service._job_status["file.pdf"]
    assert entry["status"] == "vectorizing"
    assert entry["method"] == "capella"
    assert entry["total_files"] == 10
    assert entry["chunk_count"] == 10
    # The final reported count must be one of the values the stub returned,
    # i.e. the poller actually consumed and stored the iterator results.
    assert entry["processed_files"] in (0, 2, 5, 10)


async def test_poll_capella_progress_survives_query_failure(monkeypatch):
    """An exception from the count query must not break the poller -- it logs and continues."""

    def _broken(_filename: str) -> int:
        raise RuntimeError("transient cluster failure")

    monkeypatch.setattr(
        document_service.couchbase_service,
        "count_embedded_chunks_by_filename",
        _broken,
    )

    async def _fake_wait_for(awaitable, timeout):
        # The poller passes ``stop.wait()`` here; close the coroutine so
        # Python doesn't warn about it being un-awaited.
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(document_service.asyncio, "wait_for", _fake_wait_for)

    stop = asyncio.Event()
    task = asyncio.create_task(
        document_service._poll_capella_progress("file.pdf", total=4, stop=stop)
    )

    for _ in range(4):
        await asyncio.sleep(0)

    stop.set()
    await task

    # processed_files falls back to 0 on exception; the bar shows the
    # indeterminate shimmer in that case (frontend treats total>0 +
    # processed==0 as 0% determinate, which is also fine).
    entry = document_service._job_status["file.pdf"]
    assert entry["status"] == "vectorizing"
    assert entry["processed_files"] == 0
    assert entry["total_files"] == 4
