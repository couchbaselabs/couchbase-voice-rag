from pydantic import BaseModel, Field, SecretStr


class SettingsRequest(BaseModel):
    """Cluster + OpenAI settings submitted by the Settings UI."""

    cb_connection_string: str = Field(..., description="``couchbases://...`` endpoint.")
    cb_username: str
    cb_password: SecretStr
    cb_bucket: str
    cb_scope: str = "_default"
    cb_collection: str = Field(
        ...,
        description=(
            "Collection name. UI auto-fills from ``embedding_method`` "
            "(documents_local / documents_capella) but the user can override."
        ),
    )
    cb_search_index: str = Field(
        ...,
        description="Vector search index name. Auto-filled by UI based on mode.",
    )
    embedding_method: str = Field(
        default="capella",
        description="One of ``capella`` (AI Services workflow) or ``python`` (local).",
    )
    azure_openai_endpoint: str = Field(
        ..., description="Azure OpenAI resource URL (https://...)."
    )
    openai_api_key: SecretStr = Field(..., description="Azure OpenAI API key.")
    openai_realtime_model: str = Field(
        ..., description="Azure OpenAI Realtime deployment name."
    )
    openai_embedding_model: str = Field(
        ..., description="Azure OpenAI embedding deployment name."
    )
    capella_api_key_id: SecretStr = Field(
        default=SecretStr(""),
        description="Capella Management API key ID (only when EMBEDDING_METHOD=capella).",
    )
    capella_api_key_token: SecretStr = Field(
        default=SecretStr(""),
        description="Capella Management API key token.",
    )
    capella_workflow_name: str = Field(
        default="realtime_rag_vectorization",
        description=(
            "Capella AI Workflow name. Backend looks for an existing "
            "workflow with this name on the cluster and reuses it; "
            "creates one with this exact name if none exists."
        ),
    )
    deepgram_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="Deepgram primary STT API key (Whisper is the fallback when blank).",
    )
    tavily_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="Tavily key for the web-search fallback.",
    )
    web_search_enabled: bool = Field(
        default=False,
        description="Enable Tavily web-search fallback when KB has no relevant results.",
    )


class SettingsValues(BaseModel):
    """Settings payload returned to the UI. Secret fields come back blank."""

    cb_connection_string: str
    cb_username: str
    cb_password: str
    cb_bucket: str
    cb_scope: str
    cb_collection: str
    cb_search_index: str
    embedding_method: str
    azure_openai_endpoint: str
    openai_api_key: str
    openai_realtime_model: str
    openai_embedding_model: str
    capella_api_key_id: str
    capella_api_key_token: str
    capella_workflow_name: str
    deepgram_api_key: str
    tavily_api_key: str
    web_search_enabled: bool


class SettingsResponse(BaseModel):
    """Envelope for :class:`SettingsValues`."""

    settings: SettingsValues


class SettingsStatusResponse(BaseModel):
    """Whether the backend currently has a live Couchbase connection."""

    initialized: bool


class SettingsProgressResponse(BaseModel):
    """Current stage of the most recent (or in-flight) Save & Connect."""

    stage: str = Field(
        ...,
        description=(
            "One of: idle, applying, capella_user, capella_bucket, "
            "connecting, creating_bucket, creating_collections, "
            "creating_indexes, building_search_index, saving, done, error."
        ),
    )


class SaveSettingsResponse(BaseModel):
    """Acknowledgement returned after a successful settings save + reconnect."""

    ok: bool = True
    message: str
