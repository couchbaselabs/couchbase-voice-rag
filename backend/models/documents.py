from pydantic import BaseModel, Field


class DocumentSummary(BaseModel):
    """One entry in the uploaded-document listing."""

    filename: str
    chunk_count: int
    embedding_method: str | None = None
    workflow_name: str | None = None


class UploadResponse(BaseModel):
    """Returned immediately after a PDF upload is accepted for processing."""

    filename: str
    chunk_count: int
    status: str = Field(
        default="vectorizing",
        description="Lifecycle state: vectorizing, completed, failed, unknown.",
    )


class JobStatusResponse(BaseModel):
    """Current embedding-generation state for a previously uploaded filename."""

    status: str
    chunk_count: int | None = None
    method: str | None = None
    error: str | None = None
    processed_files: int | None = None
    total_files: int | None = None
