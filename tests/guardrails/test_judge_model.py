"""The judge LLM is built from the registry id, never the upstream wire name."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from docsgpt.background.guard import _EngineOwner
from docsgpt.guardrails.config import GuardrailsConfig
from docsgpt.guardrails.runtime import _judge_factory


@pytest.fixture
def created(monkeypatch):
    """Capture the ``model_id`` each judge LLM is created with."""
    calls = []

    def fake_create_llm(llm_name, **kwargs):
        calls.append(kwargs["model_id"])
        return SimpleNamespace(model_id=kwargs["model_id"])

    monkeypatch.setattr("docsgpt.llm.llm_creator.LLMCreator.create_llm", fake_create_llm)
    monkeypatch.setattr("docsgpt.guardrails.runtime.settings.GUARDRAILS_JUDGE_MODEL", None)
    return calls


def _agent(**over):
    attrs = dict(
        llm_name="openai",
        api_key="k",
        user_api_key=None,
        decoded_token={"sub": "u1"},
        agent_id="a1",
        model_user_id=None,
        # One upstream model at two reasoning efforts: the registry id and the wire name differ.
        model_id="gpt-5.4-mini-high",
        upstream_model_id="gpt-5.4-mini",
    )
    attrs.update(over)
    return SimpleNamespace(**attrs)


class TestJudgeModelId:
    def test_the_agent_registry_id_is_used_not_the_upstream_name(self, created):
        _judge_factory(_agent())()
        assert created == ["gpt-5.4-mini-high"]

    def test_a_control_model_still_wins(self, created):
        _judge_factory(_agent())("judge-model")
        assert created == ["judge-model"]

    def test_the_instance_judge_model_beats_the_agent_model(self, created, monkeypatch):
        monkeypatch.setattr("docsgpt.guardrails.runtime.settings.GUARDRAILS_JUDGE_MODEL", "instance-judge")
        _judge_factory(_agent())()
        assert created == ["instance-judge"]

    def test_a_background_run_judges_with_the_agent_default_model(self, created, monkeypatch):
        monkeypatch.setattr("docsgpt.core.model_utils.validate_model_id", lambda mid, user_id=None: True)
        monkeypatch.setattr("docsgpt.core.model_utils.get_provider_from_model_id", lambda mid, user_id=None: "openai")
        monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda name: "k")
        owner = _EngineOwner(
            user_id="u1",
            agent_id="a1",
            agent_row={"default_model_id": "gpt-5.4-mini-high"},
            config=GuardrailsConfig(),
        )
        _judge_factory(owner)()
        assert created == ["gpt-5.4-mini-high"]
