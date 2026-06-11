import threading
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import config

_security = HTTPBearer(auto_error=False)

TOKEN_EXPIRY_HOURS = 24

_token_version: int = 0
_token_version_lock = threading.Lock()


def get_token_version() -> int:
    with _token_version_lock:
        return _token_version


def increment_token_version() -> int:
    global _token_version
    with _token_version_lock:
        _token_version += 1
        return _token_version


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
        "ver": get_token_version(),
    }
    return jwt.encode(payload, config.get_jwt_secret(), algorithm="HS256")


def verify_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, config.get_jwt_secret(), algorithms=["HS256"])
        if payload.get("ver") != get_token_version():
            return None
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> str:
    token = None

    # 1. Bearer token from Authorization header
    if credentials:
        token = credentials.credentials

    # 2. Cookie fallback
    if not token:
        token = request.cookies.get("token")

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    username = verify_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return username


def get_token_from_query(query_token: str | None) -> str:
    if not query_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = verify_token(query_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return username
