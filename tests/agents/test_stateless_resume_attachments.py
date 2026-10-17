"""A stateless /v1 tool round re-plans the resent turn's files."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from docsgpt.agents.attachment_budget import AttachmentPlan, FileStatus
from docsgpt.agents.classic_agent import ClassicAgent
from docsgpt.agents.tools.attachments import ATTACHMENTS_TOOL_ID
from docsgpt.llm.handlers.openai import OpenAILLMHandler
from tests.agents.test_attachments_tool_wiring import client_tools, make, text_att  # noqa: F401

pytestmark = pytest.mark.unit

WINDOW = 100_000


@pytest.fixture(autouse=True)
def _window():
    with patch("docsgpt.core.model_utils.get_token_limit", return_value=WINDOW):
        yield


def _resent():
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": [{"type": "text", "text": "assess the filings"}]},
    ]


class TestPrepareResentAttachments:
    def test_plans_the_files_against_the_resent_messages(
        self, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator, client_tools  # noqa: F811
    ):
        files = [text_att("a.txt", 2_000, "id-a"), text_att("big.txt", 80_000, "id-b")]
        agent = make(ClassicAgent, agent_base_params, mock_llm, attachments=files)
        messages = _resent()
        tools_dict = {}

        agent.prepare_resent_attachments(tools_dict, messages)

        plan = agent.attachment_plan
        assert isinstance(plan, AttachmentPlan)
        assert plan.files[0].status == FileStatus.INLINE
        assert plan.files[1].status in (FileStatus.PARTIAL, FileStatus.TOOL)
        assert plan.reserved_tokens <= plan.budget
        assert agent._current_turn_message is messages[-1]
        # The manifest's tool is in the round's tools, server-side.
        assert ATTACHMENTS_TOOL_ID in tools_dict
        assert agent.turn_capabilities.attachments_tool

    def test_the_handler_merges_the_plan_into_the_resent_turn(
        self, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator, client_tools  # noqa: F811
    ):
        files = [text_att("a.txt", 2_000, "id-a")]
        agent = make(ClassicAgent, agent_base_params, mock_llm, attachments=files)
        agent.llm_handler = OpenAILLMHandler()
        messages = _resent()
        agent.prepare_resent_attachments({}, messages)

        agent.llm_handler.prepare_messages(agent, messages, files)

        text = " ".join(p.get("text", "") for p in messages[-1]["content"])
        assert "a.txt" in text and "lorem ipsum" in text
        assert "assess the filings" in text

    def test_nothing_happens_without_files(
        self, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator, client_tools  # noqa: F811
    ):
        agent = make(ClassicAgent, agent_base_params, mock_llm, attachments=[])
        tools_dict = {}
        agent.prepare_resent_attachments(tools_dict, _resent())
        assert agent.attachment_plan is None
        assert tools_dict == {}


class TestStatelessContinuationUsesIt:
    def test_build_continuation_plans_the_resent_files(self):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor.__new__(StreamProcessor)
        processor.data = {}
        processor.decoded_token = {"sub": "u"}
        processor.trace = None
        processor.trace_source = "v1"
        agent = MagicMock()
        tools = {"t1": {"name": "client"}}
        agent.tool_executor.get_tools.return_value = tools
        processor.build_agent = Mock(return_value=agent)
        messages = [
            *_resent(),
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "result"},
        ]

        _, prior, tools_dict, *_ = StreamProcessor.build_continuation_from_messages.__wrapped__(
            processor, messages, [{"call_id": "c1", "result": "result"}]
        )

        agent.prepare_resent_attachments.assert_called_once_with(tools_dict, prior)
        assert prior[-1]["role"] == "user"
