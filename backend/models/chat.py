from typing import Literal

from pydantic import BaseModel


class ChatMessage(BaseModel):
    """One transcript entry exchanged between the user and the assistant."""

    role: Literal["user", "assistant"]
    text: str


class SaveSessionRequest(BaseModel):
    """Payload for persisting a chat session's title and message history."""

    title: str
    messages: list[ChatMessage]


class ChatSessionSummary(BaseModel):
    """One entry in the chat session list (metadata only, no messages)."""

    session_id: str
    title: str
    created_at: str
    updated_at: str


class ChatSessionDetail(BaseModel):
    """Full chat session document including the message transcript."""

    session_id: str
    title: str
    messages: list[ChatMessage]
    created_at: str
    updated_at: str
