"""The attachments tool joins the turn's tools, and stays server-side."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from docsgpt.agents.agentic_agent import AgenticAgent
from docsgpt.agents.attachment_context import render_attachment_block
from docsgpt.agents.classic_agent import ClassicAgent
from docsgpt.agents.research_agent import ResearchAgent
from docsgpt.agents.tools.attachments import ATTACHMENTS_TOOL_ID
from docsgpt.agents.turn_capabilities import ATTACHMENTS_TOOL_NAME
from docsgpt.api.v1.translator import StreamTranslationState, translate_stream_event
from docsgpt.utils import num_tokens_from_string

pytestmark = pytest.mark.unit

WINDOW = 100_000


@pytest.fixture(autouse=True)
def _window():
    with patch("docsgpt.core.model_utils.get_token_limit", return_value=WINDOW):
        yield


@pytest.fixture
def client_tools(monkeypatch):
    """Tools the executor returns: none of the user's, plus any client tools set."""
    holder = {"client": []}

    def _fake_get_tools(self):
        tools = {}
        if holder["client"]:
            self.merge_client_tools(tools, holder["client"])
        return tools

    monkeypatch.setattr("docsgpt.agents.tool_executor.ToolExecutor.get_tools", _fake_get_tools)
    return holder


def text_att(name, tokens, att_id):
    body = "lorem ipsum " * (tokens // 2 + 1)
    return {
        "id": att_id,
        "filename": name,
        "mime_type": "text/plain",
        "content": body,
        "token_count": num_tokens_from_string(body),
        "metadata": {"extraction": {"status": "ok", "truncated": False}},
    }


def make(cls, agent_base_params, mock_llm, **kwargs):
    mock_llm.get_supported_attachment_types = Mock(return_value=[])
    params = {**agent_base_params, "attachment_planning": True, **kwargs}
    agent = cls(**params)
    agent.initial_user_id = agent.user
    return agent


def capture_tools(agent):
    captured = {}
    original = agent._prepare_tools

    def _spy(tools_dict):
        captured["tools_dict"] = tools_dict
        return original(tools_dict)

    agent._prepare_tools = _spy
    return captured


def run(agent, log_context):
    agent.llm.gen_stream = Mock(return_value=iter(["answer"]))

    def _handler(*args, **kwargs):
        yield "answer"

    agent.llm_handler.process_message_flow = Mock(side_effect=_handler)
    list(agent._gen_inner("question", log_context))


@pytest.mark.parametrize("cls", [ClassicAgent, AgenticAgent])
def test_added_when_the_conversation_has_files(
    cls, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator, client_tools, log_context
):
    agent = make(cls, agent_base_params, mock_llm, attachments=[text_att("a.txt", 300, "id-a")])
    captured = capture_tools(agent)
    run(agent, log_context)

    entry = captured["tools_dict"][ATTACHMENTS_TOOL_ID]
    assert entry["name"] == ATTACHMENTS_TOOL_NAME
    assert not entry.get("client_side")
    assert not any(a.get("require_approval") for a in entry["actions"])
    assert agent.turn_capabilities.attachments_tool
    assert set(agent.turn_capabilities.attachments_actions) >= {"attachments_list", "attachments_read"}
    assert entry["config"]["current_ids"] == ["id-a"]


def test_research_agent_adds_it_too(
    agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator, client_tools
):
    agent = make(ResearchAgent, agent_base_params, mock_llm,
                 earlier_attachments=[text_att("old.txt", 300, "id-old")])
    tools_dict = agent._setup_tools()
    assert ATTACHMENTS_TOOL_ID in tools_dict
    assert tools_dict[ATTACHMENTS_TOOL_ID]["config"]["earlier_ids"] == ["id-old"]


def test_earlier_files_alone_add_it(
    agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator, client_tools, log_context
):
    agent = make(ClassicAgent, agent_base_params, mock_llm, earlier_attachments=[text_att("old.txt", 300, "id-old")])
    captured = capture_tools(agent)
    run(agent, log_context)
    assert ATTACHMENTS_TOOL_ID in captured["tools_dict"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"attachments": []},
        {"attachment_planning": False},
    ],
)
def test_not_added_without_files_or_planning(
    overrides, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator, client_tools, log_context
):
    kwargs = {"attachments": [text_att("a.txt", 300, "id-a")], **overrides}
    agent = make(ClassicAgent, agent_base_params, mock_llm, **kwargs)
    captured = capture_tools(agent)
    run(agent, log_context)
    assert ATTACHMENTS_TOOL_ID not in captured["tools_dict"]


def test_not_added_when_the_model_takes_no_tools(
    agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator, client_tools, log_context
):
    mock_llm._supports_tools = False
    agent = make(ClassicAgent, agent_base_params, mock_llm, attachments=[text_att("a.txt", 300, "id-a")])
    captured = capture_tools(agent)
    run(agent, log_context)
    assert ATTACHMENTS_TOOL_ID not in captured["tools_dict"]
    assert not agent.turn_capabilities.attachments_tool


def test_plan_statuses_reach_the_tool(
    agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator, client_tools, log_context
):
    files = [text_att("small.txt", 300, "id-s"), text_att("big.txt", 60_000, "id-b")]
    agent = make(ClassicAgent, agent_base_params, mock_llm, attachments=files)
    captured = capture_tools(agent)
    run(agent, log_context)

    config = captured["tools_dict"][ATTACHMENTS_TOOL_ID]["config"]
    statuses = {ref: info["status"] for ref, info in config["plan"].items()}
    assert statuses["F1"] == "inline"
    assert statuses["F2"] in {"partial", "tool"}
    # The partial marker points at the tool's real read action.
    block = render_attachment_block(agent.attachment_plan)
    if statuses["F2"] == "partial":
        assert 'attachments_read(ref="F2"' in block


def test_config_survives_pause_serialization(
    agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator, client_tools, log_context
):
    agent = make(ClassicAgent, agent_base_params, mock_llm, attachments=[text_att("a.txt", 300, "id-a")])
    captured = capture_tools(agent)
    run(agent, log_context)
    json.dumps(captured["tools_dict"][ATTACHMENTS_TOOL_ID])


class TestClientToolsKeepTheirNames:
    def test_colliding_client_tool_is_not_renamed(
        self, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator, client_tools, log_context
    ):
        client_tools["client"] = [
            {"type": "function", "function": {"name": "attachments_read", "description": "client", "parameters": {}}},
            {"type": "function", "function": {"name": "read", "description": "client", "parameters": {}}},
        ]
        agent = make(ClassicAgent, agent_base_params, mock_llm, attachments=[text_att("a.txt", 300, "id-a")])
        run(agent, log_context)

        names = [t["function"]["name"] for t in agent.tools]
        assert "attachments_read" in names and "read" in names
        assert agent.tool_executor._name_to_tool["attachments_read"][0].startswith("ct")
        ours = [n for n, (tid, _a) in agent.tool_executor._name_to_tool.items() if tid == ATTACHMENTS_TOOL_ID]
        assert any(n.endswith("attachments_read") and n != "attachments_read" for n in ours)
        assert any(a.endswith("attachments_read") for a in agent.turn_capabilities.attachments_actions)
        assert "attachments_read" not in agent.turn_capabilities.attachments_actions


class TestNeverReachesTheClient:
    def _executor_with_tool(self, **flags):
        from docsgpt.agents.tool_executor import ToolExecutor
        from docsgpt.agents.tools.attachments import add_attachments_tool

        executor = ToolExecutor(user="u", **flags)
        tools_dict = {}
        executor.merge_client_tools(
            tools_dict, [{"type": "function", "function": {"name": "search", "parameters": {}}}]
        )
        add_attachments_tool(tools_dict, user="u", current_ids=["id-a"], earlier_ids=[])
        executor.prepare_tools_for_llm(tools_dict)
        return executor, tools_dict

    @pytest.mark.parametrize(
        "flags", [{}, {"headless": True}, {"external_caller": True}, {"public_link_caller": True}]
    )
    def test_check_pause_never_pauses_it(self, flags):
        executor, tools_dict = self._executor_with_tool(**flags)
        for action in ("attachments_list", "attachments_read"):
            call = SimpleNamespace(id="c1", name=action, arguments={"ref": "F1"}, thought_signature=None)
            assert executor.check_pause(tools_dict, call, "OpenAILLM") is None

    def test_v1_stream_shows_it_only_in_the_extension(self):
        for status in ("pending", "completed"):
            event = {
                "type": "tool_call",
                "data": {
                    "tool_name": ATTACHMENTS_TOOL_NAME,
                    "call_id": "c1",
                    "action_name": "attachments_read",
                    "arguments": {"ref": "F1"},
                    "status": status,
                },
            }
            chunks = translate_stream_event(event, "cmpl-1", "m", state=StreamTranslationState())
            assert chunks
            for chunk in chunks:
                payload = json.loads(chunk.removeprefix("data: ").strip())
                assert "docsgpt" in payload
                assert "tool_calls" not in payload["choices"][0]["delta"]
