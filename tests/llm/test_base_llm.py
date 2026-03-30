"""Unit tests for application/llm/base.py — BaseLLM.

Covers initialisation, static helpers, supports_* introspection,
structured-output defaults, and attachment-type defaults.
Fallback behaviour is covered separately in test_fallback.py.
"""

from unittest.mock import MagicMock, Mock

import pytest

from application.llm.base import BaseLLM


# ---------------------------------------------------------------------------
# Concrete stub so we can instantiate the abstract base
# ---------------------------------------------------------------------------


class StubLLM(BaseLLM):
    """Minimal concrete BaseLLM for unit-testing non-abstract members."""

    def _raw_gen(self, baseself, model, messages, stream, tools=None, **kw):
        return "raw_gen_result"

    def _raw_gen_stream(self, baseself, model, messages, stream, tools=None, **kw):
        yield "chunk"


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBaseLLMInit:

    def test_defaults(self):
        llm = StubLLM()
        assert llm.decoded_token is None
        assert llm.agent_id is None
        assert llm.model_id is None
        assert llm.base_url is None
        assert llm.token_usage == {"prompt_tokens": 0, "generated_tokens": 0}
        assert llm._backup_models == []
        assert llm._fallback_llm is None

    def test_agent_id_cast_to_str(self):
        llm = StubLLM(agent_id=42)
        assert llm.agent_id == "42"

    def test_agent_id_none_stays_none(self):
        llm = StubLLM(agent_id=None)
        assert llm.agent_id is None

    def test_custom_params(self):
        token = {"sub": "u1"}
        llm = StubLLM(
            decoded_token=token,
            agent_id="abc",
            model_id="gpt-4",
            base_url="http://x",
            backup_models=["m1", "m2"],
        )
        assert llm.decoded_token is token
        assert llm.agent_id == "abc"
        assert llm.model_id == "gpt-4"
        assert llm.base_url == "http://x"
        assert llm._backup_models == ["m1", "m2"]


# ---------------------------------------------------------------------------
# _remove_null_values
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveNullValues:

    def test_removes_none_values(self):
        result = BaseLLM._remove_null_values({"a": 1, "b": None, "c": "x"})
        assert result == {"a": 1, "c": "x"}

    def test_keeps_falsy_non_none(self):
        result = BaseLLM._remove_null_values({"a": 0, "b": "", "c": False, "d": []})
        assert result == {"a": 0, "b": "", "c": False, "d": []}

    def test_non_dict_passthrough(self):
        assert BaseLLM._remove_null_values("hello") == "hello"
        assert BaseLLM._remove_null_values(42) == 42
        assert BaseLLM._remove_null_values([1, 2]) == [1, 2]

    def test_empty_dict(self):
        assert BaseLLM._remove_null_values({}) == {}

    def test_all_none(self):
        assert BaseLLM._remove_null_values({"a": None, "b": None}) == {}


# ---------------------------------------------------------------------------
# supports_tools / _supports_tools
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSupportsTools:

    def test_supports_tools_true_when_callable(self):
        llm = StubLLM()
        assert llm.supports_tools() is True

    def test_supports_tools_false_when_not_callable(self):
        llm = StubLLM()
        llm._supports_tools = "not_callable"
        assert llm.supports_tools() is False

    def test_default_supports_tools_raises(self):
        llm = StubLLM()
        with pytest.raises(NotImplementedError):
            llm._supports_tools()


# ---------------------------------------------------------------------------
# supports_structured_output / _supports_structured_output
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSupportsStructuredOutput:

    def test_supports_structured_output_true(self):
        llm = StubLLM()
        assert llm.supports_structured_output() is True

    def test_default_supports_structured_output_returns_false(self):
        llm = StubLLM()
        assert llm._supports_structured_output() is False


# ---------------------------------------------------------------------------
# prepare_structured_output_format
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareStructuredOutputFormat:

    def test_returns_none_by_default(self):
        llm = StubLLM()
        assert llm.prepare_structured_output_format({"type": "object"}) is None


# ---------------------------------------------------------------------------
# get_supported_attachment_types
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSupportedAttachmentTypes:

    def test_returns_empty_list(self):
        llm = StubLLM()
        assert llm.get_supported_attachment_types() == []


# ---------------------------------------------------------------------------
# fallback_llm — caching
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFallbackLLMCaching:

    def test_returns_cached_instance(self, monkeypatch):
        """Once resolved, the same fallback instance is returned."""
        sentinel = StubLLM()
        llm = StubLLM()
        llm._fallback_llm = sentinel
        assert llm.fallback_llm is sentinel

    def test_none_when_no_backup_and_no_global(self, monkeypatch):
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(FALLBACK_LLM_PROVIDER=None),
        )
        llm = StubLLM(backup_models=[])
        assert llm.fallback_llm is None

    def test_global_fallback_init_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(
                FALLBACK_LLM_PROVIDER="openai",
                FALLBACK_LLM_NAME="gpt-4",
                FALLBACK_LLM_API_KEY="k",
                API_KEY="k",
            ),
        )
        monkeypatch.setattr(
            "application.llm.llm_creator.LLMCreator.create_llm",
            Mock(side_effect=RuntimeError("boom")),
        )
        llm = StubLLM(backup_models=[])
        assert llm.fallback_llm is None
