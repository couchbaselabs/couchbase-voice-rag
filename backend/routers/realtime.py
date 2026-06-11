import asyncio
import json
import logging

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import config
from middleware.auth import verify_token
from services.realtime_service import RealtimeSession

logger = logging.getLogger(__name__)

router = APIRouter()


def _check_ws_origin(websocket: WebSocket) -> bool:
    """Mirror the HTTP CORS allowlist on the WebSocket handshake.

    Starlette's ``CORSMiddleware`` short-circuits when ``scope["type"] !=
    "http"``, so it does not protect WebSocket endpoints. With the auth
    cookie set as ``SameSite=None; Secure`` (Phase F3), browsers attach
    it to cross-origin WS handshakes — we must reject any handshake whose
    ``Origin`` header is not on the allowlist or is missing entirely
    (browsers always send one for ``new WebSocket(...)``).
    """
    return websocket.headers.get("origin") in config.ALLOWED_ORIGINS


def _authenticate_ws(websocket: WebSocket) -> str | None:
    """Return the authenticated username from the ``token`` cookie, or ``None``."""
    token = websocket.cookies.get("token", "")
    return verify_token(token) if token else None


@router.websocket("/ws/realtime")
async def realtime_endpoint(websocket: WebSocket):
    if not _check_ws_origin(websocket):
        await websocket.close(code=4003, reason="Forbidden origin")
        return
    username = _authenticate_ws(websocket)
    if not username:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info(f"WebSocket connected: {username}")

    session = RealtimeSession(client_ws=websocket)
    try:
        await session.connect()
        await session.run()
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {username}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await session.close()


@router.websocket("/ws/deepgram")
async def deepgram_endpoint(websocket: WebSocket):
    if not _check_ws_origin(websocket):
        await websocket.close(code=4003, reason="Forbidden origin")
        return
    username = _authenticate_ws(websocket)
    if not username:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    if not config.DEEPGRAM_API_KEY:
        await websocket.close(code=4002, reason="Deepgram not configured")
        return

    await websocket.accept()

    # Build Deepgram URL with vocabulary keywords from knowledge base
    from services import couchbase_service
    keywords_param = ""
    try:
        vocab = await asyncio.to_thread(couchbase_service.load_vocabulary_hints)
        if vocab:
            keywords_param = "&" + "&".join(
                f"keywords={w}:2" for w in vocab[:20]
            )
    except Exception as e:
        logger.warning("Failed to load vocabulary hints for Deepgram: %s", e)

    dg_url = (
        "wss://api.deepgram.com/v1/listen"
        "?encoding=linear16&sample_rate=24000&channels=1"
        "&language=en&model=nova-2&punctuate=true"
        "&interim_results=true&utterance_end_ms=1500"
        f"{keywords_param}"
    )

    try:
        async with websockets.connect(
            dg_url,
            additional_headers={"Authorization": f"Token {config.DEEPGRAM_API_KEY}"},
        ) as dg_ws:

            async def client_to_deepgram():
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await dg_ws.send(data)
                except WebSocketDisconnect:
                    logger.debug("Client disconnected from Deepgram relay")

            async def deepgram_to_client():
                try:
                    async for msg in dg_ws:
                        try:
                            result = json.loads(msg)
                        except json.JSONDecodeError as e:
                            logger.warning("Discarding malformed Deepgram message: %s", e)
                            continue
                        if result.get("type") == "Results":
                            channel = result.get("channel", {})
                            alt = channel.get("alternatives", [{}])[0]
                            transcript = alt.get("transcript", "")
                            is_final = result.get("is_final", False)
                            if transcript:
                                await websocket.send_json({
                                    "transcript": transcript,
                                    "is_final": is_final,
                                })
                        elif result.get("type") == "UtteranceEnd":
                            await websocket.send_json({
                                "type": "utterance_end",
                            })
                except websockets.exceptions.ConnectionClosed:
                    logger.debug("Deepgram WebSocket closed")

            async def keepalive():
                try:
                    while True:
                        await asyncio.sleep(8)
                        await dg_ws.send(json.dumps({"type": "KeepAlive"}))
                except Exception as e:
                    logger.debug("Deepgram keepalive ended: %s", e)

            await asyncio.gather(client_to_deepgram(), deepgram_to_client(), keepalive())

    except Exception as e:
        logger.error(f"Deepgram relay error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception as e:
            logger.debug("websocket.close() error (ignored): %s", e)
