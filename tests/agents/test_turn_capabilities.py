"""What a turn can do with attachments, computed once from the final tool list."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from docsgpt.agents.base import BaseAgent
from docsgpt.agents.turn_capabilities import (
    ATTACHMENTS_TOOL_NAME,
    TurnCapabilities,
    build_turn_capabilities,
)


class _Agent(BaseAgent):
    def _gen_inner(self, query, log_context=None):
        yield {"answer": "ok"}


def _llm(types=("image/png", "image/jpeg"), supports_tools=True):
    llm = Mock()
    llm.get_supported_attachment_types = Mock(return_value=list(types))
    llm._supports_tools = Mock(return_value=supports_tools)
    llm.model_id = "gpt-test"
    return llm


def _agent(llm, **kwargs):
    agent = _Agent(
        endpoint="stream",
        llm_name="openai",
        model_id="gpt-test",
        api_key="k",
        llm=llm,
        llm_handler=Mock(),
        decoded_token={"sub": "u"},
        **kwargs,
    )
    return agent


CODE_TOOLS = {
    "t-code": {
        "name": "code_executor",
        "actions": [{"name": "run_code", "description": "run", "parameters": {"properties": {}}}],
    }
}


@pytest.mark.unit
class TestBuildTurnCapabilities:
    def test_vision_and_native_pdf_follow_the_supported_types(self):
        caps = build_turn_capabilities(
            supported_attachment_types=["image/png", "application/pdf"],
            tool_calling=True,
            server_tools={},
            window=128000,
            is_v1=False,
            sandbox_available=False,
        )
        assert caps.vision is True
        assert caps.native_pdf is True
        assert caps.window == 128000

    def test_text_only_model(self):
        caps = build_turn_capabilities(
            supported_attachment_types=[],
            tool_calling=True,
            server_tools={},
            window=32000,
            is_v1=False,
            sandbox_available=True,
        )
        assert (caps.vision, caps.native_pdf) == (False, False)

    def test_sandbox_needs_the_code_tool_tool_calling_and_a_backend(self):
        def caps(tools, tool_calling=True, sandbox_available=True):
            return build_turn_capabilities(
                supported_attachment_types=[],
                tool_calling=tool_calling,
                server_tools=tools,
                window=1000,
                is_v1=False,
                sandbox_available=sandbox_available,
            )

        assert caps({"code_executor": "run_code"}).sandbox is True
        assert caps({"code_executor": "run_code"}).sandbox_action == "run_code"
        assert caps({}).sandbox is False
        assert caps({"code_executor": "run_code"}, tool_calling=False).sandbox is False
        assert caps({"code_executor": "run_code"}, sandbox_available=False).sandbox is False

    def test_attachments_tool_seam(self):
        """The attachments tool is announced only once it is really in the turn."""
        without = build_turn_capabilities(
            supported_attachment_types=[], tool_calling=True, server_tools={},
            window=1000, is_v1=False, sandbox_available=False,
        )
        assert without.attachments_tool is False
        with_tool = build_turn_capabilities(
            supported_attachment_types=[], tool_calling=True,
            server_tools={ATTACHMENTS_TOOL_NAME: "attachments_read"},
            window=1000, is_v1=False, sandbox_available=False,
        )
        assert with_tool.attachments_tool is True
        no_calls = build_turn_capabilities(
            supported_attachment_types=[], tool_calling=False,
            server_tools={ATTACHMENTS_TOOL_NAME: "attachments_read"},
            window=1000, is_v1=False, sandbox_available=False,
        )
        assert no_calls.attachments_tool is False

    def test_is_frozen(self):
        caps = TurnCapabilities(
            tool_calling=False, vision=False, native_pdf=False, sandbox=False, window=1, is_v1=False,
        )
        with pytest.raises(Exception):
            caps.vision = True


@pytest.mark.unit
class TestSandboxConfigured:
    def test_daytona_needs_an_api_key(self, monkeypatch):
        from docsgpt.sandbox import sandbox_configured

        monkeypatch.setattr("docsgpt.core.settings.settings.SANDBOX_BACKEND", "daytona")
        monkeypatch.setattr("docsgpt.core.settings.settings.DAYTONA_API_KEY", None)
        assert sandbox_configured() is False
        monkeypatch.setattr("docsgpt.core.settings.settings.DAYTONA_API_KEY", "secret")
        assert sandbox_configured() is True

    def test_jupyter_needs_a_gateway_url(self, monkeypatch):
        from docsgpt.sandbox import sandbox_configured

        monkeypatch.setattr("docsgpt.core.settings.settings.SANDBOX_BACKEND", "jupyter")
        monkeypatch.setattr("docsgpt.core.settings.settings.SANDBOX_GATEWAY_URL", "")
        assert sandbox_configured() is False
        monkeypatch.setattr("docsgpt.core.settings.settings.SANDBOX_GATEWAY_URL", "http://runner:8888")
        assert sandbox_configured() is True


@pytest.mark.unit
class TestAgentComputesCapabilities:
    @pytest.fixture(autouse=True)
    def _window(self):
        with patch("docsgpt.core.model_utils.get_token_limit", return_value=200000):
            yield

    def test_prepare_tools_computes_once_from_the_final_tool_list(self):
        agent = _agent(_llm(types=["image/png", "application/pdf"]))
        with patch("docsgpt.agents.base.sandbox_configured", return_value=True):
            agent._prepare_tools(dict(CODE_TOOLS))

        caps = agent.turn_capabilities
        assert caps.tool_calling is True
        assert caps.vision is True and caps.native_pdf is True
        assert caps.sandbox is True
        assert caps.sandbox_action == "run_code"
        assert caps.window == 200000
        assert caps.is_v1 is False

    def test_no_tool_support_means_no_tool_calling_and_no_sandbox(self):
        agent = _agent(_llm(supports_tools=False))
        with patch("docsgpt.agents.base.sandbox_configured", return_value=True):
            agent._prepare_tools(dict(CODE_TOOLS))
        assert agent.turn_capabilities.tool_calling is False
        assert agent.turn_capabilities.sandbox is False

    def test_empty_tool_list_is_not_tool_calling(self):
        agent = _agent(_llm())
        agent._prepare_tools({})
        assert agent.turn_capabilities.tool_calling is False

    def test_unconfigured_backend_hides_the_sandbox(self):
        agent = _agent(_llm())
        with patch("docsgpt.agents.base.sandbox_configured", return_value=False):
            agent._prepare_tools(dict(CODE_TOOLS))
        assert agent.turn_capabilities.tool_calling is True
        assert agent.turn_capabilities.sandbox is False

    def test_client_side_code_tool_is_not_the_sandbox(self):
        agent = _agent(_llm())
        tools = {
            "client-1": {
                "name": "code_executor",
                "client_side": True,
                "actions": [{"name": "run_code", "description": "", "parameters": {}}],
            }
        }
        with patch("docsgpt.agents.base.sandbox_configured", return_value=True):
            agent._prepare_tools(tools)
        assert agent.turn_capabilities.sandbox is False

    def test_is_v1_flag_is_carried(self):
        agent = _agent(_llm(), is_v1=True)
        agent._prepare_tools({})
        assert agent.turn_capabilities.is_v1 is True

    def test_mock_llm_types_degrade_to_no_native_reading(self):
        llm = Mock()
        llm._supports_tools = Mock(return_value=True)
        agent = _agent(llm)
        agent._prepare_tools({})
        assert agent.turn_capabilities.vision is False


@pytest.mark.unit
class TestStreamProcessorMarksV1:
    def _run_create_agent(self, trace_source):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        sp = StreamProcessor(request_data={}, decoded_token={"sub": "u"}, trace_source=trace_source)
        sp._get_prompt_content = MagicMock(return_value="prompt")
        sp.agent_config = {"agent_type": "classic", "prompt_id": "default", "user_api_key": None}
        sp.model_id = "m1"
        sp.prompt_renderer = MagicMock()
        sp.prompt_renderer.render_prompt.return_value = "rendered"
        captured = {}

        def capture(agent_type, **kwargs):
            captured.update(kwargs)
            return MagicMock()

        with patch(
            "docsgpt.api.answer.services.stream_processor.get_provider_from_model_id",
            return_value="openai",
        ), patch(
            "docsgpt.api.answer.services.stream_processor.get_api_key_for_provider",
            return_value="key",
        ), patch("docsgpt.llm.llm_creator.LLMCreator.create_llm", return_value=MagicMock()), patch(
            "docsgpt.llm.handlers.handler_creator.LLMHandlerCreator.create_handler",
            return_value=MagicMock(),
        ), patch("docsgpt.agents.agent_creator.AgentCreator.create_agent", side_effect=capture), patch.object(
            StreamProcessor, "_enabled_tool_names", return_value=set()
        ):
            sp.create_agent()
        return captured

    def test_v1_requests_are_marked(self):
        assert self._run_create_agent("v1")["is_v1"] is True

    def test_web_stream_is_not_v1(self):
        assert self._run_create_agent("stream")["is_v1"] is False
