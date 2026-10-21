"""The guardrail judge resolves the agent's model by its registry id."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from docsgpt.background.guard import _EngineOwner
from docsgpt.guardrails import runtime
from docsgpt.guardrails.config import GuardrailsConfig


def _agent(**overrides):
    values = dict(
        llm_name="openai_compatible",
        api_key=None,
        user_api_key=None,
        decoded_token={"sub": "owner"},
        model_id="0b7e0f4c-1234-5678-9abc-deadbeef0102",
        upstream_model_id="my-upstream-name",
        agent_id="agent-1",
        model_user_id="owner",
        request_id="req-1",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.unit
class TestJudgeModel:
    def _capture(self, monkeypatch):
        captured = {}

        def create_llm(*args, **kwargs):
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr("docsgpt.llm.llm_creator.LLMCreator.create_llm", create_llm)
        monkeypatch.setattr(runtime.settings, "GUARDRAILS_JUDGE_MODEL", None)
        return captured

    def test_judge_uses_the_registry_id_not_the_upstream_name(self, monkeypatch):
        # A custom model's upstream name is not registered: resolving it
        # would find no model, so no endpoint or key of its own.
        captured = self._capture(monkeypatch)
        runtime._judge_factory(_agent())()
        assert captured["model_id"] == "0b7e0f4c-1234-5678-9abc-deadbeef0102"
        assert captured["model_user_id"] == "owner"

    def test_judge_falls_back_to_the_upstream_name_without_a_model_id(self, monkeypatch):
        captured = self._capture(monkeypatch)
        runtime._judge_factory(_agent(model_id=None))()
        assert captured["model_id"] == "my-upstream-name"

    def test_an_explicit_judge_model_wins(self, monkeypatch):
        captured = self._capture(monkeypatch)
        runtime._judge_factory(_agent())("judge-model")
        assert captured["model_id"] == "judge-model"

    def test_the_instance_judge_model_beats_the_agent_model(self, monkeypatch):
        captured = self._capture(monkeypatch)
        monkeypatch.setattr(runtime.settings, "GUARDRAILS_JUDGE_MODEL", "instance-judge")
        runtime._judge_factory(_agent())()
        assert captured["model_id"] == "instance-judge"

    def _owner(self, monkeypatch, *, default_model_id):
        monkeypatch.setattr("docsgpt.core.model_utils.validate_model_id", lambda mid, user_id=None: True)
        monkeypatch.setattr("docsgpt.core.model_utils.get_default_model_id", lambda: None)
        monkeypatch.setattr("docsgpt.core.model_utils.get_provider_from_model_id", lambda mid, user_id=None: "openai")
        monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda name: "k")
        return _EngineOwner(
            user_id="u1",
            agent_id="a1",
            agent_row={"default_model_id": default_model_id},
            config=GuardrailsConfig(),
        )

    def test_a_background_run_judges_with_the_agent_default_model(self, monkeypatch):
        captured = self._capture(monkeypatch)
        runtime._judge_factory(self._owner(monkeypatch, default_model_id="gpt-5.4-mini-high"))()
        assert captured["model_id"] == "gpt-5.4-mini-high"

    def test_a_background_run_without_any_model_does_not_raise(self, monkeypatch):
        # The owner carries ``model_id`` only; with no agent or registry
        # default the judge gets ``None`` rather than an AttributeError.
        captured = self._capture(monkeypatch)
        runtime._judge_factory(self._owner(monkeypatch, default_model_id=None))()
        assert captured["model_id"] is None
