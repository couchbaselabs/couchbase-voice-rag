from fastapi import APIRouter, Depends, HTTPException, Request, Response

from middleware.auth import create_token, get_current_user, increment_token_version
from middleware.rate_limit import limiter
from models.auth import (
    ChangePasswordRequest,
    ForceLogoutResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
)
from models.common import OkMessageResponse
from services import user_store

router = APIRouter()


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Authenticate and issue a JWT",
)
@limiter.limit("10/minute")
async def login(request: Request, req: LoginRequest, response: Response):
    """Verify credentials and return a 24-hour JWT in both the body and an HTTP-only cookie."""
    password = req.password.get_secret_value()
    if not user_store.verify_password(req.username, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(req.username)
    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=86400,
    )
    return LoginResponse(
        token=token,
        username=req.username,
        must_change_password=user_store.must_change_password(req.username),
    )


@router.post("/logout", response_model=OkMessageResponse, summary="Clear the auth cookie")
async def logout(response: Response):
    """Drop the ``token`` cookie. JWTs are stateless, so this only affects the browser."""
    response.delete_cookie(key="token")
    return OkMessageResponse(message="Logged out")


@router.post(
    "/force-logout",
    response_model=ForceLogoutResponse,
    summary="Invalidate every issued JWT",
)
async def force_logout(username: str = Depends(get_current_user)):
    """Bump the global token version so every previously issued JWT is rejected."""
    new_version = increment_token_version()
    return ForceLogoutResponse(
        message=f"All tokens invalidated (version={new_version})"
    )


@router.post(
    "/change-password",
    response_model=OkMessageResponse,
    summary="Change the current user's password",
)
async def change_password(
    req: ChangePasswordRequest,
    username: str = Depends(get_current_user),
):
    """Rotate the password for the authenticated user and invalidate outstanding JWTs."""
    current = req.current_password.get_secret_value()
    new = req.new_password.get_secret_value()
    if not user_store.verify_password(username, current):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    user_store.set_password(username, new)
    increment_token_version()
    return OkMessageResponse(message="Password changed. Please log in again.")


@router.get("/me", response_model=MeResponse, summary="Return the caller's profile")
async def me(username: str = Depends(get_current_user)):
    """Return the username embedded in the caller's JWT plus any forced-rotation flag."""
    return MeResponse(
        username=username,
        must_change_password=user_store.must_change_password(username),
    )
