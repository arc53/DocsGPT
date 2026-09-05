"""Bounded cross-turn chaining, chained system-head dedupe and prompt-cache
hints on the OpenAI Responses path.

Background (prod, 2026-09-01/03): ``previous_response_id`` chained every user
turn onto the previous one, so Azure's stored transcript grew without bound
(889k prompt tokens for a 37k-token local history) while every local guard
measured the local history. Each chained round also re-sent the system
message, which the server appends rather than dedupes, and after a
compression the rebuilt local messages were still chained onto the
uncompressed transcript.
"""

import types
from unittest.mock import MagicMock

import pytest

from application.core.model_settings import ModelCapabilities


def _make_llm(monkeypatch, store_responses=True, **extra_settings):
    monkeypatch.setattr("application.llm.openai.OpenAI", MagicMock())
    monkeypatch.setattr(
        "application.llm.openai.StorageCreator",
        types.SimpleNamespace(get_storage=lambda: None),
    )
    monkeypatch.setattr(
        "application.llm.openai.settings",
        types.SimpleNamespace(
            OPENAI_API_KEY="k",
            API_KEY="k",
            OPENAI_BASE_URL="",
            AZURE_DEPLOYMENT_NAME="dep",
            OPENAI_RESPONSES_STORE=store_responses,
            OPENAI_REASONING_SUMMARY="auto",
            **extra_settings,
        ),
    )
    from application.llm.openai import OpenAILLM

    llm = OpenAILLM(api_key="k")
    llm.capabilities = ModelCapabilities(
        supports_tools=True, supports_structured_output=True, api_flavor="responses"
    )
    return llm


def _messages(system="sys"):
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
    ]


def _roles(items):
    return [i.get("role") for i in items if isinstance(i, dict) and i.get("role")]


def _accepted(llm, rid="resp_1"):
    """The provider accepted the request just built: record its response."""
    llm._record_responses_metadata(types.SimpleNamespace(id=rid, output=[], usage=None))


# ── chained system head ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_chained_input_omits_unchanged_system_head(monkeypatch):
    llm = _make_llm(monkeypatch)
    # The unchained send is what puts the system message into the stored
    # transcript; the chained follow-up must not append a second copy.
    first, prev = llm._build_responses_input(_messages(), None)
    assert prev is None
    assert "system" in _roles(first)
    _accepted(llm)

    chained, prev = llm._build_responses_input(_messages(), "resp_1")
    assert prev == "resp_1"
    assert _roles(chained) == ["user"]


@pytest.mark.unit
def test_chained_input_resends_changed_system_head(monkeypatch):
    llm = _make_llm(monkeypatch)
    llm._build_responses_input(_messages("sys v1"), None)
    _accepted(llm)

    chained, _ = llm._build_responses_input(_messages("sys v2"), "resp_1")
    assert _roles(chained) == ["system", "user"]
    _accepted(llm, "resp_2")

    # ...and the new head becomes the one the chain holds.
    again, _ = llm._build_responses_input(_messages("sys v2"), "resp_2")
    assert _roles(again) == ["user"]


@pytest.mark.unit
def test_chained_system_head_hash_roundtrips_through_state(monkeypatch):
    llm = _make_llm(monkeypatch)
    llm._build_responses_input(_messages(), None)
    _accepted(llm)
    state = llm.export_responses_state()
    assert state.get("system_hash")

    resumed = _make_llm(monkeypatch)
    assert resumed.import_responses_state(state) is True
    chained, _ = resumed._build_responses_input(_messages(), "resp_1")
    assert _roles(chained) == ["user"]


@pytest.mark.unit
def test_start_responses_turn_forgets_system_head(monkeypatch):
    llm = _make_llm(monkeypatch)
    llm._build_responses_input(_messages(), None)
    _accepted(llm)
    llm.start_responses_turn()
    chained, _ = llm._build_responses_input(_messages(), "resp_1")
    # A fresh chain has no head on the server yet, so the head is sent.
    assert _roles(chained) == ["system", "user"]


@pytest.mark.unit
def test_unchained_input_always_carries_system(monkeypatch):
    llm = _make_llm(monkeypatch)
    llm._build_responses_input(_messages(), None)
    again, prev = llm._build_responses_input(_messages(), None)
    assert prev is None
    assert "system" in _roles(again)


# ── request params: truncation + cache hints ────────────────────────────────


def _params(llm, **kwargs):
    return llm._build_responses_params(
        "gpt-5.6", [{"role": "user", "content": []}], tools=None,
        response_format=None, previous_response_id=None, stream=True,
        kwargs=kwargs,
    )


@pytest.mark.unit
def test_build_responses_params_defaults_omit_truncation_and_cache_hints(monkeypatch):
    llm = _make_llm(monkeypatch)
    llm._prompt_cache_key = "conv-123"
    params = _params(llm)
    assert "truncation" not in params
    assert "prompt_cache_key" not in params
    assert "prompt_cache_retention" not in params


@pytest.mark.unit
def test_build_responses_params_truncation_and_cache_hints(monkeypatch):
    llm = _make_llm(
        monkeypatch,
        OPENAI_RESPONSES_TRUNCATION_AUTO=True,
        OPENAI_PROMPT_CACHE_KEY=True,
        OPENAI_PROMPT_CACHE_RETENTION="24h",
    )
    llm._prompt_cache_key = "conv-123"
    params = _params(llm)
    assert params["truncation"] == "auto"
    assert params["prompt_cache_key"] == "conv-123"
    assert params["prompt_cache_retention"] == "24h"


@pytest.mark.unit
def test_build_responses_params_cache_key_needs_a_conversation(monkeypatch):
    llm = _make_llm(monkeypatch, OPENAI_PROMPT_CACHE_KEY=True)
    llm._prompt_cache_key = None
    assert "prompt_cache_key" not in _params(llm)


# ── agent: when does the next turn chain? ───────────────────────────────────


def _agent(monkeypatch, history, last_compression_at=None, **overrides):
    from application.agents import base as base_mod
    from application.agents.base import BaseAgent

    class _Agent(BaseAgent):
        def _gen_inner(self, query, log_context):
            yield from ()

    agent = _Agent.__new__(_Agent)
    agent.chat_history = history
    agent.llm = types.SimpleNamespace(
        responses_chain_key=lambda: "key",
        _uses_responses_api=lambda: True,
    )
    agent.model_id = "m"
    agent.model_user_id = None
    agent.user = "u"
    agent.last_compression_at = last_compression_at
    defaults = {
        "OPENAI_RESPONSES_STORE": True,
        "OPENAI_RESPONSES_CHAIN_ACROSS_TURNS": True,
        "OPENAI_RESPONSES_CHAIN_BUDGET_TOKENS": None,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        monkeypatch.setattr(base_mod.settings, key, value, raising=False)
    monkeypatch.setattr(
        "application.core.model_utils.get_token_limit", lambda *a, **k: 1000
    )
    return agent


def _turn(prompt_tokens, epoch=None, rid="resp_1"):
    meta = {
        "response_id": rid,
        "response_chain_key": "key",
        "usage": {"prompt_tokens": prompt_tokens},
    }
    if epoch:
        meta["compression_epoch"] = epoch
    return {"prompt": "q", "response": "a", "metadata": meta}


@pytest.mark.unit
def test_previous_response_id_chains_within_budget(monkeypatch):
    agent = _agent(monkeypatch, [_turn(500)])
    assert agent._previous_response_id() == "resp_1"


@pytest.mark.unit
def test_previous_response_id_stops_at_model_window(monkeypatch):
    # Last turn already cost the whole window: start this one from the
    # bounded local history instead of growing Azure's transcript further.
    agent = _agent(monkeypatch, [_turn(1000)])
    assert agent._previous_response_id() is None


@pytest.mark.unit
def test_previous_response_id_honours_explicit_budget(monkeypatch):
    agent = _agent(
        monkeypatch, [_turn(500)], OPENAI_RESPONSES_CHAIN_BUDGET_TOKENS=400
    )
    assert agent._previous_response_id() is None


@pytest.mark.unit
def test_previous_response_id_chains_when_usage_unknown(monkeypatch):
    turn = _turn(0)
    turn["metadata"].pop("usage")
    agent = _agent(monkeypatch, [turn])
    assert agent._previous_response_id() == "resp_1"


@pytest.mark.unit
def test_previous_response_id_kill_switch(monkeypatch):
    agent = _agent(
        monkeypatch, [_turn(10)], OPENAI_RESPONSES_CHAIN_ACROSS_TURNS=False
    )
    assert agent._previous_response_id() is None


@pytest.mark.unit
def test_previous_response_id_breaks_after_newer_compression(monkeypatch):
    agent = _agent(
        monkeypatch,
        [_turn(10, epoch="2026-09-03T09:00:00+00:00")],
        last_compression_at="2026-09-03T10:00:00+00:00",
    )
    assert agent._previous_response_id() is None


@pytest.mark.unit
def test_previous_response_id_chains_when_turn_saw_the_compression(monkeypatch):
    epoch = "2026-09-03T10:00:00+00:00"
    agent = _agent(monkeypatch, [_turn(10, epoch=epoch)], last_compression_at=epoch)
    assert agent._previous_response_id() == "resp_1"


@pytest.mark.unit
def test_previous_response_id_compression_epoch_format_tolerant(monkeypatch):
    # JSONB round-trips give "2026-09-03 10:00:00.123+00:00"; the point
    # itself is written as an ISO datetime. Both must compare equal.
    agent = _agent(
        monkeypatch,
        [_turn(10, epoch="2026-09-03T10:00:00.123000+00:00")],
        last_compression_at="2026-09-03 10:00:00.123+00:00",
    )
    assert agent._previous_response_id() == "resp_1"


@pytest.mark.unit
def test_previous_response_id_breaks_when_turn_predates_any_compression(monkeypatch):
    agent = _agent(
        monkeypatch, [_turn(10)], last_compression_at="2026-09-03T10:00:00+00:00"
    )
    assert agent._previous_response_id() is None


@pytest.mark.unit
def test_emit_responses_metadata_records_compression_epoch(monkeypatch):
    agent = _agent(monkeypatch, [], last_compression_at="2026-09-03T10:00:00+00:00")
    agent.llm = types.SimpleNamespace(
        responses_chain_key=lambda: "key",
        _uses_responses_api=lambda: True,
        _last_response_id="resp_9",
        _last_usage={"prompt_tokens": 1},
        export_responses_state=lambda: {"chain_key": "key"},
    )
    events = list(agent._emit_responses_metadata())
    assert events and events[0]["metadata"]["compression_epoch"] == "2026-09-03T10:00:00+00:00"
    assert events[0]["metadata"]["response_id"] == "resp_9"


# ── cache key is opaque ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_cache_key_for_user_is_opaque_and_stable():
    from application.agents.base import _cache_key_for_user

    key = _cache_key_for_user("user_2Vhzgd63RSgixvvbF8Z2nhtqnE9")
    assert key and "user_2Vhzgd" not in key
    assert len(key) == 32 and all(c in "0123456789abcdef" for c in key)
    assert key == _cache_key_for_user("user_2Vhzgd63RSgixvvbF8Z2nhtqnE9")
    assert key != _cache_key_for_user("someone-else")
    assert _cache_key_for_user(None) is None


# ── the head hash commits only once the provider accepted the request ───────


@pytest.mark.unit
def test_system_hash_commits_only_when_the_response_is_recorded(monkeypatch):
    llm = _make_llm(monkeypatch)
    llm._build_responses_input(_messages(), None)
    # Not recorded (the request failed before the provider stored it): a
    # chained follow-up must still carry the head.
    chained, _ = llm._build_responses_input(_messages(), "resp_1")
    assert _roles(chained) == ["system", "user"]
    _accepted(llm)
    chained, _ = llm._build_responses_input(_messages(), "resp_1")
    assert _roles(chained) == ["user"]


@pytest.mark.unit
def test_failed_chained_request_resends_changed_head_on_retry(monkeypatch):
    llm = _make_llm(monkeypatch)
    llm._build_responses_input(_messages("sys v1"), None)
    _accepted(llm)
    first, _ = llm._build_responses_input(_messages("sys v2"), "resp_1")
    assert _roles(first) == ["system", "user"]
    # Transport error before any chunk: nothing recorded. The same-primary
    # retry chains onto resp_1 again, whose stored head is still "sys v1".
    retry, _ = llm._build_responses_input(_messages("sys v2"), "resp_1")
    assert _roles(retry) == ["system", "user"]
    _accepted(llm, "resp_2")
    after, _ = llm._build_responses_input(_messages("sys v2"), "resp_2")
    assert _roles(after) == ["user"]


# ── a failed non-streaming response must not become chain state ─────────────


@pytest.mark.unit
def test_failed_response_records_no_chain_state(monkeypatch):
    llm = _make_llm(monkeypatch)
    # An accepted turn with head "sys v1".
    llm._build_responses_input(_messages("sys v1"), None)
    _accepted(llm, "resp_ok")
    committed = llm._chain_system_hash

    failed = types.SimpleNamespace(
        id="resp_bad", status="failed", error=types.SimpleNamespace(message="boom"),
        incomplete_details=None, output=[], usage=None,
    )
    llm.client.responses.create = MagicMock(return_value=failed)
    with pytest.raises(RuntimeError):
        llm._responses_gen(
            "gpt-5.6", _messages("sys v2"), tools=None, previous_response_id="resp_ok"
        )

    # Neither the failed id nor the head it carried became chain state
    # (the in-turn id is cleared before every request; the retry chains via
    # the caller's previous_response_id)...
    assert llm._last_response_id != "resp_bad"
    assert llm._chain_system_hash == committed
    # ...so the retry chains onto resp_ok and re-sends the changed head.
    retry, prev = llm._build_responses_input(_messages("sys v2"), "resp_ok")
    assert prev == "resp_ok"
    assert _roles(retry) == ["system", "user"]


@pytest.mark.unit
def test_output_capped_response_still_records_chain_state(monkeypatch):
    llm = _make_llm(monkeypatch)
    capped = types.SimpleNamespace(
        id="resp_len", status="incomplete",
        incomplete_details=types.SimpleNamespace(reason="max_output_tokens"),
        output=[types.SimpleNamespace(type="message", content=[
            types.SimpleNamespace(type="output_text", text="partial")])],
        usage=None, error=None,
    )
    llm.client.responses.create = MagicMock(return_value=capped)
    assert llm._responses_gen("gpt-5.6", _messages(), tools=None) == "partial"
    assert llm._last_response_id == "resp_len"
    assert llm._chain_system_hash is not None


@pytest.mark.unit
def test_recorded_request_without_a_head_clears_the_committed_hash(monkeypatch):
    llm = _make_llm(monkeypatch)
    llm._build_responses_input(_messages("sys v1"), None)
    _accepted(llm, "resp_1")
    # An unchained fallback with no system message at all is recorded: the
    # new transcript holds no head, so the old hash must not survive it.
    llm._build_responses_input([{"role": "user", "content": "q"}], None)
    _accepted(llm, "resp_2")
    assert llm._chain_system_hash is None
    chained, _ = llm._build_responses_input(_messages("sys v1"), "resp_2")
    assert _roles(chained) == ["system", "user"]
