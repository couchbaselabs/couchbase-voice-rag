import logging

from tavily import TavilyClient

import config

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        if not config.TAVILY_API_KEY:
            raise RuntimeError("TAVILY_API_KEY is not configured")
        _client = TavilyClient(api_key=config.TAVILY_API_KEY)
    return _client


def is_configured() -> bool:
    """Return ``True`` when a Tavily API key is available."""
    return bool(config.TAVILY_API_KEY)


def is_enabled() -> bool:
    """Return ``True`` only when both the toggle is on AND a key is set.

    Callers wanting the operator-controlled "fall back to the web when KB
    misses" feature should gate on this rather than ``is_configured()`` so
    a stale Tavily key in .env doesn't accidentally re-enable the path.
    """
    return bool(config.settings.web_search_enabled) and is_configured()


def search(query: str, max_results: int = 3) -> str:
    """Run a Tavily web search and flatten the answer plus sources into a prompt string."""
    client = _get_client()
    result = client.search(
        query=query,
        search_depth="basic",
        max_results=max_results,
        include_answer=True,
    )

    answer = result.get("answer", "")
    sources = result.get("results", [])

    parts = []
    if answer:
        parts.append(f"Web search summary: {answer}")

    for src in sources[:max_results]:
        title = src.get("title", "")
        content = src.get("content", "")
        url = src.get("url", "")
        parts.append(f"Source: {title}\n{content}\nURL: {url}")

    return "\n\n---\n\n".join(parts) if parts else "No web results found."
