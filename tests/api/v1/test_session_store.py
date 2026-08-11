"""Tests for privacy-preserving v1 client session correlation."""

from unittest.mock import MagicMock

import pytest

from application.api.v1.session_store import (
    delete_conversation,
    identify_session,
    load_conversation,
    save_conversation,
)


@pytest.mark.unit
def test_session_key_is_prompt_and_agent_scoped():
    headers = {"X-Session-ID": "raw-secret-session"}
    main = {"messages": [{"role": "system", "content": "coding"}]}
    title = {"messages": [{"role": "system", "content": "title"}]}
    one = identify_session(headers, main, "agent-1")
    assert one != identify_session(headers, title, "agent-1")
    assert one != identify_session(headers, main, "agent-2")
    assert "raw-secret-session" not in one.key


@pytest.mark.unit
def test_explicit_docsgpt_session_precedes_generic_header():
    data = {
        "docsgpt": {"session_id": "explicit"},
        "messages": [{"role": "user", "content": "hi"}],
    }
    explicit = identify_session({"X-Session-ID": "generic"}, data, "agent")
    expected = identify_session(
        {"X-DocsGPT-Session-ID": "explicit"},
        {"messages": data["messages"]},
        "agent",
    )
    assert explicit == expected


@pytest.mark.unit
def test_openai_user_field_is_not_a_chat_session():
    data = {
        "user": "stable-end-user-id",
        "messages": [{"role": "user", "content": "hi"}],
    }
    assert identify_session({}, data, "agent") is None


@pytest.mark.unit
def test_save_and_load_use_bounded_redis_ttl(monkeypatch):
    redis = MagicMock()
    redis.get.return_value = b"conv-1"
    monkeypatch.setattr(
        "application.api.v1.session_store.get_redis_instance", lambda: redis
    )
    monkeypatch.setattr(
        "application.api.v1.session_store.settings.V1_SESSION_TTL_SECONDS", 123
    )
    session = identify_session({"X-Session-ID": "s"}, {"messages": []}, "a")
    save_conversation(session, "conv-1")
    redis.set.assert_called_once_with(session.key, "conv-1", ex=123)
    assert load_conversation(session) == "conv-1"


@pytest.mark.unit
def test_delete_conversation_invalidates_stale_mapping(monkeypatch):
    redis = MagicMock()
    monkeypatch.setattr(
        "application.api.v1.session_store.get_redis_instance", lambda: redis
    )
    session = identify_session({"X-Session-ID": "s"}, {"messages": []}, "a")
    delete_conversation(session)
    redis.delete.assert_called_once_with(session.key)
