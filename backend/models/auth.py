from pydantic import BaseModel, Field, SecretStr


class LoginRequest(BaseModel):
    """Credentials submitted to ``POST /api/auth/login``."""

    username: str = Field(..., min_length=1, max_length=64)
    password: SecretStr


class LoginResponse(BaseModel):
    """Issued JWT plus the flag that drives the password-change flow."""

    token: str
    username: str
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    """Payload for ``POST /api/auth/change-password``."""

    current_password: SecretStr
    new_password: SecretStr = Field(..., min_length=4)


class MeResponse(BaseModel):
    """Profile summary for the caller's JWT."""

    username: str
    must_change_password: bool


class ForceLogoutResponse(BaseModel):
    """Returned after bumping the global JWT version (invalidates all tokens)."""

    ok: bool = True
    message: str
