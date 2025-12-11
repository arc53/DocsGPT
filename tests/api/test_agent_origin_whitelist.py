# tests/application/test_agent_origin_whitelist.py

import types
from application.routes import agent_api


def _fake_agent(enabled, allowed_origins):
    agent = types.SimpleNamespace()
    agent.origin_whitelist_enabled = enabled
    agent.allowed_origins = allowed_origins
    return agent


def test_origin_allowed_when_feature_disabled():
    agent = _fake_agent(enabled=False, allowed_origins="")
    assert agent_api._is_origin_allowed(agent, None) is True
    assert agent_api._is_origin_allowed(agent, "https://example.com") is True


def test_origin_rejected_when_missing_and_enabled():
    agent = _fake_agent(enabled=True, allowed_origins="https://example.com")
    assert agent_api._is_origin_allowed(agent, None) is False


def test_default_docsgpt_origins_always_allowed():
    agent = _fake_agent(enabled=True, allowed_origins="")
    assert agent_api._is_origin_allowed(agent, "https://app.docsgpt.cloud") is True
    assert agent_api._is_origin_allowed(agent, "https://ent.docsgpt.cloud") is True


def test_custom_origin_must_be_in_whitelist():
    agent = _fake_agent(enabled=True, allowed_origins="https://a.com, https://b.com")
    assert agent_api._is_origin_allowed(agent, "https://a.com") is True
    assert agent_api._is_origin_allowed(agent, "https://b.com") is True
    assert agent_api._is_origin_allowed(agent, "https://c.com") is False
