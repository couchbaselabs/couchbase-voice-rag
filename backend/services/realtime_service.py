import asyncio
import json
import logging
import os

import websockets
from fastapi import WebSocket
from websockets.exceptions import ConnectionClosed

import config
from services import couchbase_service, embedding_service, web_search_service

logger = logging.getLogger(__name__)

# When set to "1", every outgoing/incoming Realtime event is logged at INFO
# with a (truncated) payload. Off by default because instructions / user
# input / assistant transcripts are sensitive. Toggled per-investigation.
_DEBUG_PAYLOAD = os.environ.get("REALTIME_DEBUG_PAYLOAD") == "1"


_SYSTEM_INSTRUCTIONS_BASE = """You are a helpful English-speaking assistant with access to a knowledge base.

ABSOLUTE RULE: You MUST ALWAYS respond in English.

When the transcribed input contains letter-by-letter spelling (e.g., "X T C R"), interpret it as an acronym or technical term (e.g., "XDCR"). Use the knowledge base vocabulary hints to match likely intended terms.
Be concise and conversational since you are responding with voice."""

SYSTEM_INSTRUCTIONS_KB_ONLY = (
    _SYSTEM_INSTRUCTIONS_BASE
    + """

KNOWLEDGE BASE USAGE:

ALWAYS call search_knowledge_base FIRST for any factual question.

The tool returns one of three responses; respond accordingly:

(a) Relevant text passages from the uploaded documents.
    -> Answer based on those passages. You MAY begin with
       "Based on the knowledge base..." but ONLY when you are
       actually citing the returned text. If your answer goes
       beyond the passages, say so explicitly.

(b) The exact phrase "No relevant information found in the knowledge base."
    -> If you are confident you know the answer from your general
       training (e.g., well-known technical concepts like Couchbase,
       Python, REST APIs, common products), JUST ANSWER THE QUESTION
       DIRECTLY and naturally. Do NOT preface the answer with "I
       don't have information in the knowledge base" or any similar
       disclaimer. Do NOT say "From general knowledge,...". Just
       answer as if you knew it all along.
       Only when the topic is genuinely outside your knowledge
       (e.g., a private internal project, very recent events) should
       you admit you don't know. When you do, phrase it as
       "I'm not familiar with X" or "I don't know about X" —
       NEVER mention the knowledge base in your answer. Then
       optionally suggest the user upload related documents
       (e.g., "If you upload related documents I can help with
       specifics.").

(c) The exact phrase "Knowledge base search temporarily unavailable."
    -> Answer the question directly from your general knowledge if
       you know it. Do not mention the KB outage unless the user
       asks. If the topic is outside your knowledge, say
       "I'm not familiar with X" or "I don't know about X" — again
       without mentioning the knowledge base.

CRITICAL RULE: Never start a response with "Based on the knowledge
base..." for cases (b) or (c). Doing so falsely implies you cited
stored documents. Also NEVER mention the knowledge base when you
don't have an answer — just say "I'm not familiar with that" or
"I don't know about that" plainly. The knowledge base is an
internal detail; the user should not see it surface in your
disclaimers.
"""
)

SYSTEM_INSTRUCTIONS_WITH_WEB = (
    _SYSTEM_INSTRUCTIONS_BASE
    + """

KNOWLEDGE BASE + WEB SEARCH USAGE:

ALWAYS call search_knowledge_base FIRST for any factual question.

The tool returns one of three responses:

(a) Relevant text passages from the uploaded documents.
    -> Answer based on those passages. You MAY begin with
       "Based on the knowledge base..." ONLY when actually citing
       the returned text.

(b) The exact phrase "No relevant information found in the knowledge base."
    -> If you are confident you know the answer from your general
       training (e.g., well-known technical concepts like Couchbase,
       Python, REST APIs, common products), JUST ANSWER THE QUESTION
       DIRECTLY and naturally. Do NOT preface the answer with "I
       don't have information in the knowledge base" or any similar
       disclaimer.
       Only when the topic is something you genuinely don't know
       well (e.g., very recent events, niche specifics, a private
       project) should you call search_web. When you do call
       search_web, begin with "I found this from a web search..."
       and answer from those results. If even the web has no useful
       result, say "I'm not familiar with X" — NEVER mention the
       knowledge base in your reply.

(c) The exact phrase "Knowledge base search temporarily unavailable."
    -> Answer directly from your general knowledge if you know it.
       Otherwise call search_web. Either way, do not mention the
       knowledge base outage. If still unknown, say "I'm not
       familiar with X" without referencing the KB.

CRITICAL RULE: Never start a response with "Based on the knowledge
base..." for cases (b) or (c). Also NEVER mention the knowledge
base when you cannot answer — phrase any uncertainty as
"I'm not familiar with that" or "I don't know about that". The
knowledge base is an internal detail; the user should not see it
surface in your disclaimers.
"""
)

_TOOL_SEARCH_KB = {
    "type": "function",
    "name": "search_knowledge_base",
    "description": (
        "Search the uploaded document knowledge base for relevant information. "
        "ALWAYS call this FIRST before answering any factual question."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query based on what the user is asking about",
            }
        },
        "required": ["query"],
    },
}

_TOOL_SEARCH_WEB = {
    "type": "function",
    "name": "search_web",
    "description": (
        "Search the web for information when the knowledge base has no relevant results. "
        "Only use this AFTER search_knowledge_base returns no useful information."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The web search query",
            }
        },
        "required": ["query"],
    },
}


def _build_tools() -> list[dict]:
    """Return the LLM tool list for a new RealtimeSession.

    `search_knowledge_base` is always offered. `search_web` is only
    appended when ``web_search_service.is_enabled()`` is true (toggle
    AND key) so a stale Tavily key in .env can't re-enable web search
    by itself.
    """
    tools = [_TOOL_SEARCH_KB]
    if web_search_service.is_enabled():
        tools.append(_TOOL_SEARCH_WEB)
    return tools


def _build_instructions() -> str:
    """Return system instructions matched to the active tool set."""
    return (
        SYSTEM_INSTRUCTIONS_WITH_WEB
        if web_search_service.is_enabled()
        else SYSTEM_INSTRUCTIONS_KB_ONLY
    )


class RealtimeSession:
    """Bi-directional relay between a browser WebSocket and Azure OpenAI Realtime.

    Owns the upstream ``openai_ws`` connection, forwards client audio/text,
    dispatches the ``search_knowledge_base`` / ``search_web`` function calls,
    and streams responses back to the browser.
    """

    def __init__(self, client_ws: WebSocket):
        self.client_ws = client_ws
        self.openai_ws = None
        self._tasks: list[asyncio.Task] = []

    async def _send_to_openai(self, event: dict) -> None:
        """Send an event upstream to OpenAI with per-event DEBUG logging."""
        event_type = event.get("type", "<unknown>")
        if _DEBUG_PAYLOAD:
            logger.debug("OpenAI send %s payload=%s", event_type, json.dumps(event)[:2000])
        else:
            logger.debug("OpenAI send: %s", event_type)
        await self.openai_ws.send(json.dumps(event))

    async def connect(self):
        model = config.OPENAI_REALTIME_MODEL
        base = config.AZURE_OPENAI_ENDPOINT.replace("https://", "wss://").rstrip("/")
        url = f"{base}/openai/v1/realtime?model={model}"
        logger.info("Connecting to Azure OpenAI Realtime: %s", url)
        headers = {"api-key": config.OPENAI_API_KEY}
        self.openai_ws = await websockets.connect(url, additional_headers=headers)
        await self._configure_session()

    async def _configure_session(self):
        # Load vocabulary hints and include in instructions
        try:
            vocab = await asyncio.to_thread(couchbase_service.load_vocabulary_hints)
        except Exception:
            vocab = []

        instructions = _build_instructions()
        if vocab:
            vocab_str = ", ".join(vocab[:50])
            instructions += (
                f"\n\nThe knowledge base contains these technical terms "
                f"that the user may ask about: {vocab_str}. "
                f"Listen carefully for these terms in the user's speech."
            )

        session_config = {
            "type": "session.update",
            "session": {
                # GA Realtime API requires `type` and `model`, and uses a
                # restructured audio block. modalities -> output_modalities;
                # voice / formats / turn_detection moved under audio.input /
                # audio.output. See:
                #   https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio-preview-api-migration-guide
                #   https://learn.microsoft.com/en-us/azure/ai-services/openai/realtime-audio-quickstart
                "type": "realtime",
                "model": config.OPENAI_REALTIME_MODEL,
                "instructions": instructions,
                # GA accepts one output modality per session. "audio" so
                # the greeting and answers are spoken; the assistant's
                # transcript still streams via
                # response.output_audio_transcript.* and surfaces on
                # screen via _openai_to_client_loop.
                "output_modalities": ["audio"],
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        # Manual mic mode -- user clicks to talk, no server VAD.
                        "turn_detection": None,
                        # input_audio_transcription deliberately omitted:
                        # the browser already runs Deepgram STT and
                        # forwards text.send events, so OpenAI-side
                        # transcription would double-bill.
                    },
                    "output": {
                        "voice": "shimmer",
                        "format": {"type": "audio/pcm", "rate": 24000},
                    },
                },
                "tools": _build_tools(),
                "tool_choice": "auto",
            },
        }
        await self._send_to_openai(session_config)

        # Send initial greeting so the AI speaks first.
        # output_modalities is inherited from session.update (["audio"]);
        # specifying it here would have to use the GA name and is
        # redundant.
        await self._send_to_openai({
            "type": "response.create",
            "response": {
                "instructions": "You MUST respond in English only. Greet the user briefly. Say exactly: Hello! I am Couchbase Voice RAG Agent. How can I help you today?",
            },
        })

    async def run(self):
        try:
            task_client = asyncio.create_task(self._client_to_openai_loop())
            task_openai = asyncio.create_task(self._openai_to_client_loop())
            self._tasks = [task_client, task_openai]
            await asyncio.gather(*self._tasks)
        except Exception as e:
            logger.info(f"Session ended: {e}")
        finally:
            await self.close()

    async def _client_to_openai_loop(self):
        try:
            while True:
                data = await self.client_ws.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError as e:
                    logger.warning("Discarding malformed client message: %s", e)
                    continue
                msg_type = msg.get("type", "")

                # All per-message lines stay at DEBUG -- audio.append fires
                # every ~50ms in voice mode and even non-audio messages add
                # up over a session. LOG_LEVEL=DEBUG surfaces them when
                # actually needed.
                if msg_type != "audio.append":
                    logger.debug("Client msg: %s", msg_type)
                elif _DEBUG_PAYLOAD:
                    logger.debug("Client audio.append (%d bytes)", len(msg.get("audio", "")))

                if msg_type == "audio.append":
                    await self._send_to_openai({
                        "type": "input_audio_buffer.append",
                        "audio": msg["audio"],
                    })

                elif msg_type == "audio.commit":
                    await self._send_to_openai({
                        "type": "input_audio_buffer.commit",
                    })

                elif msg_type == "text.send":
                    await self._send_to_openai({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": msg["text"],
                                }
                            ],
                        },
                    })
                    await self._send_to_openai({
                        "type": "response.create",
                    })

                elif msg_type == "response.cancel":
                    await self._send_to_openai({
                        "type": "response.cancel",
                    })

                elif msg_type == "session.config":
                    update = {"type": "session.update", "session": {}}
                    if "instructions" in msg:
                        update["session"]["instructions"] = msg["instructions"]
                    if "voice" in msg:
                        update["session"]["voice"] = msg["voice"]
                    if update["session"]:
                        await self._send_to_openai(update)

        except ConnectionClosed as e:
            logger.info(
                "Client WS closed: code=%s reason=%r",
                getattr(e, "code", "?"),
                getattr(e, "reason", "?"),
            )
        except Exception as e:
            logger.info(f"Client loop ended: {e}")

    async def _openai_to_client_loop(self):
        try:
            async for raw_msg in self.openai_ws:
                try:
                    event = json.loads(raw_msg)
                except json.JSONDecodeError as e:
                    logger.warning("Discarding malformed OpenAI message: %s", e)
                    continue
                event_type = event.get("type", "")

                # All per-event lines stay at DEBUG. response.audio.delta
                # would flood the logs at any level above DEBUG, and the
                # remaining events (response.create / .done / function_call_*
                # / etc.) are not operator-actionable on their own --
                # LOG_LEVEL=DEBUG with optional REALTIME_DEBUG_PAYLOAD=1 is
                # the supported path when actually debugging.
                if _DEBUG_PAYLOAD and event_type not in (
                    "response.audio.delta",
                    "response.output_audio.delta",
                ):
                    logger.debug("OpenAI event %s payload=%s", event_type, json.dumps(event)[:2000])
                else:
                    logger.debug("OpenAI event: %s", event_type)

                # Audio delta -> forward to client
                # Match both legacy (`response.audio.delta`) and GA-renamed
                # (`response.output_audio.delta`) event names — Azure's
                # reference still lists the legacy names while the GA
                # migration guide documents the renames; handling both is
                # defensive against either source being out of date.
                if event_type in ("response.audio.delta", "response.output_audio.delta"):
                    await self.client_ws.send_json({
                        "type": "audio.delta",
                        "audio": event.get("delta", ""),
                    })

                # Audio done
                elif event_type in ("response.audio.done", "response.output_audio.done"):
                    await self.client_ws.send_json({
                        "type": "audio.done",
                    })

                # User transcript
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    await self.client_ws.send_json({
                        "type": "transcript.done",
                        "text": event.get("transcript", ""),
                        "role": "user",
                    })

                # Assistant transcript partial
                elif event_type in (
                    "response.audio_transcript.delta",
                    "response.output_audio_transcript.delta",
                ):
                    await self.client_ws.send_json({
                        "type": "transcript.partial",
                        "text": event.get("delta", ""),
                    })

                # Assistant transcript done
                elif event_type in (
                    "response.audio_transcript.done",
                    "response.output_audio_transcript.done",
                ):
                    await self.client_ws.send_json({
                        "type": "transcript.done",
                        "text": event.get("transcript", ""),
                        "role": "assistant",
                    })

                # Text response (for text-only mode)
                elif event_type in ("response.text.delta", "response.output_text.delta"):
                    await self.client_ws.send_json({
                        "type": "text.delta",
                        "text": event.get("delta", ""),
                    })

                elif event_type in ("response.text.done", "response.output_text.done"):
                    await self.client_ws.send_json({
                        "type": "text.done",
                        "text": event.get("text", ""),
                    })

                # Function call
                elif event_type == "response.function_call_arguments.done":
                    await self._handle_function_call(
                        name=event.get("name", ""),
                        call_id=event.get("call_id", ""),
                        arguments=event.get("arguments", "{}"),
                    )

                # Error
                elif event_type == "error":
                    error_info = event.get("error", {})
                    error_code = error_info.get("code", "")

                    # Non-fatal errors: log only, don't break client session
                    non_fatal = {
                        "input_audio_buffer_commit_empty",
                        "response_cancel_not_active",
                    }
                    if error_code in non_fatal:
                        logger.warning(f"OpenAI non-fatal error (ignored): {error_code}")
                    elif error_code == "session_expired":
                        logger.warning("OpenAI session expired (30min limit)")
                        await self.client_ws.send_json({
                            "type": "session_expired",
                            "message": "Session expired. Please start a new conversation.",
                        })
                    else:
                        logger.error(f"OpenAI Realtime error: {error_info}")
                        await self.client_ws.send_json({
                            "type": "error",
                            "message": error_info.get("message", "Unknown error"),
                        })

                else:
                    # Unhandled events (e.g. GA-only ones like
                    # conversation.item.added / .done) stay at DEBUG --
                    # LOG_LEVEL=DEBUG surfaces them when investigating
                    # protocol changes.
                    logger.debug("Unhandled OpenAI event: %s", event_type)

        except ConnectionClosed as e:
            logger.info(
                "OpenAI WS closed: code=%s reason=%r rcvd=%s sent=%s",
                getattr(e, "code", "?"),
                getattr(e, "reason", "?"),
                getattr(e, "rcvd", None),
                getattr(e, "sent", None),
            )
        except Exception as e:
            logger.info(f"OpenAI loop ended: {e}")

    async def _handle_function_call(self, name: str, call_id: str, arguments: str):
        if name == "search_knowledge_base":
            try:
                args = json.loads(arguments)
                query = args.get("query", "")

                await self.client_ws.send_json({
                    "type": "function_call.searching",
                    "query": query,
                    "source": "kb",
                })

                embedding = await asyncio.to_thread(
                    embedding_service.get_embedding, query
                )
                results = await asyncio.to_thread(
                    couchbase_service.vector_search, embedding, 3
                )
                context = "\n\n---\n\n".join(
                    [r["text"] for r in results if r.get("text")]
                )

                output = context or "No relevant information found in the knowledge base."

                await self._send_to_openai({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": output,
                    },
                })

                await self._send_to_openai({
                    "type": "response.create",
                })

                await self.client_ws.send_json({
                    "type": "function_call.results",
                    "source": "kb",
                    "count": len(results),
                })

            except Exception as e:
                logger.error(f"KB search error: {e}")
                await self.client_ws.send_json({
                    "type": "function_call.results",
                    "source": "kb",
                    "count": 0,
                    "error": str(e),
                })
                await self._send_to_openai({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        # Exact phrase matched by SYSTEM_INSTRUCTIONS case (c).
                        "output": "Knowledge base search temporarily unavailable.",
                    },
                })
                await self._send_to_openai({
                    "type": "response.create",
                })

        elif name == "search_web":
            try:
                args = json.loads(arguments)
                query = args.get("query", "")

                await self.client_ws.send_json({
                    "type": "function_call.searching",
                    "query": query,
                    "source": "web",
                })

                output = await asyncio.to_thread(web_search_service.search, query)

                await self._send_to_openai({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": output,
                    },
                })

                await self._send_to_openai({
                    "type": "response.create",
                })

                await self.client_ws.send_json({
                    "type": "function_call.results",
                    "source": "web",
                    "count": 1,
                })

            except Exception as e:
                logger.error(f"Web search error: {e}")
                await self.client_ws.send_json({
                    "type": "function_call.results",
                    "source": "web",
                    "count": 0,
                    "error": str(e),
                })
                await self._send_to_openai({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": f"Web search failed: {str(e)}. Answer based on general knowledge.",
                    },
                })
                await self._send_to_openai({
                    "type": "response.create",
                })

    async def close(self):
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        if self.openai_ws:
            try:
                await self.openai_ws.close()
            except Exception as e:
                logger.debug("openai_ws.close() error (ignored): %s", e)
