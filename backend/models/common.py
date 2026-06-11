from pydantic import BaseModel, ConfigDict


class OkResponse(BaseModel):
    """Generic acknowledgement payload used by idempotent mutating endpoints."""

    model_config = ConfigDict(json_schema_extra={"example": {"ok": True}})

    ok: bool = True


class OkMessageResponse(OkResponse):
    """Acknowledgement with an optional human-readable message."""

    message: str
