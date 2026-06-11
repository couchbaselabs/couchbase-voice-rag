from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import get_current_user
from models.chat import (
    ChatSessionDetail,
    ChatSessionSummary,
    SaveSessionRequest,
)
from models.common import OkResponse
from services import couchbase_service

router = APIRouter()


@router.get(
    "/sessions",
    response_model=list[ChatSessionSummary],
    summary="List saved chat sessions",
)
def list_sessions(username: str = Depends(get_current_user)):
    """Return every persisted chat session ordered by ``updated_at`` descending."""
    return couchbase_service.list_chat_sessions()


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetail,
    summary="Load a chat session",
)
def load_session(
    session_id: str,
    username: str = Depends(get_current_user),
):
    """Return the stored title, timestamps, and full message transcript for ``session_id``."""
    session = couchbase_service.load_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post(
    "/sessions/{session_id}",
    response_model=OkResponse,
    summary="Upsert a chat session",
)
def save_session(
    session_id: str,
    req: SaveSessionRequest,
    username: str = Depends(get_current_user),
):
    """Create or overwrite the persisted transcript for ``session_id``."""
    messages = [m.model_dump() for m in req.messages]
    couchbase_service.save_chat_session(session_id, req.title, messages)
    return OkResponse()


@router.delete(
    "/sessions/{session_id}",
    response_model=OkResponse,
    summary="Delete a chat session",
)
def delete_session(
    session_id: str,
    username: str = Depends(get_current_user),
):
    """Remove the persisted chat session document identified by ``session_id``."""
    couchbase_service.delete_chat_session(session_id)
    return OkResponse()
