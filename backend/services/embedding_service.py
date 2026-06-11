from openai import AzureOpenAI

import config

_client = None


def _get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.OPENAI_API_KEY,
            api_version="2023-05-15",
        )
    return _client


def get_embedding(text: str) -> list[float]:
    """Return a single embedding vector for ``text``."""
    client = _get_client()
    response = client.embeddings.create(
        model=config.OPENAI_EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Return one embedding vector per input text (single Azure OpenAI call)."""
    client = _get_client()
    response = client.embeddings.create(
        model=config.OPENAI_EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]
