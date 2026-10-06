"""The guardrail judge resolves the agent's model by its registry id."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from docsgpt.guardrails import runtime


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
