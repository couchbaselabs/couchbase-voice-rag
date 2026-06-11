"""Unit tests for the dynamic tool list / system prompt builders.

The Settings UI's Tavily switch + key state both gate whether the LLM
sees the ``search_web`` tool and which system prompt it receives. Both
builders consult the same ``web_search_service.is_enabled()`` so they
can never disagree.
"""

import config
from services import realtime_service


def _set_state(monkeypatch, *, enabled: bool, key: str) -> None:
    monkeypatch.setattr(config.settings, "web_search_enabled", enabled)
    monkeypatch.setattr(config.settings, "tavily_api_key", key)


def test_build_tools_omits_search_web_when_toggle_off(monkeypatch):
    _set_state(monkeypatch, enabled=False, key="any-key")
    tools = realtime_service._build_tools()
    names = [t["name"] for t in tools]
    assert "search_knowledge_base" in names
    assert "search_web" not in names


def test_build_tools_includes_search_web_when_toggle_and_key(monkeypatch):
    _set_state(monkeypatch, enabled=True, key="tv-key")
    tools = realtime_service._build_tools()
    names = [t["name"] for t in tools]
    assert "search_knowledge_base" in names
    assert "search_web" in names


def test_build_tools_omits_search_web_when_toggle_on_but_no_key(monkeypatch):
    _set_state(monkeypatch, enabled=True, key="")
    tools = realtime_service._build_tools()
    assert "search_web" not in [t["name"] for t in tools]


def test_build_instructions_kb_only_when_toggle_off(monkeypatch):
    _set_state(monkeypatch, enabled=False, key="tv-key")
    text = realtime_service._build_instructions()
    assert "search_knowledge_base" in text
    assert "search_web" not in text


def test_build_instructions_with_web_when_enabled(monkeypatch):
    _set_state(monkeypatch, enabled=True, key="tv-key")
    text = realtime_service._build_instructions()
    assert "search_knowledge_base" in text
    assert "search_web" in text
