"""Images an attachments_read asked for reach the model after the tool results.

Chat Completions takes no images inside ``tool`` messages, so the handler
adds them as image parts in a user message that follows the turn's tool
results. Each provider then formats that message its own way.
"""

import base64
import types
from typing import Any, Dict, Generator
from unittest.mock import Mock

import pytest

from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.agents.tools.attachments import ATTACHMENTS_TOOL_ID, add_attachments_tool
from docsgpt.llm.handlers.base import LLMHandler, LLMResponse, ToolCall

pytestmark = pytest.mark.unit

PNG = base64.b64encode(b"\x89PNG fake").decode()
PAGE = {"attachment": {"data": PNG, "mime_type": "image/png", "page": 2}, "label": "F3 scan.pdf page 2"}
SHOT = {"attachment": {"path": "inputs/u/shot.png", "mime_type": "image/png", "filename": "shot.png"},
        "label": "F1 shot.png"}


class _Handler(LLMHandler):
    def parse_response(self, response: Any) -> LLMResponse:
        return LLMResponse(content=str(response), tool_calls=[], finish_reason="stop", raw_response=response)

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        return {"role": "tool", "content": str(result), "tool_call_id": tool_call.id}

    def _iterate_stream(self, response: Any) -> Generator:
        yield from response


def _openai_style_prepare(messages, attachments):
    prepared = messages.copy()
    user = prepared[-1]
    for attachment in attachments:
        user["content"].append(
            {"type": "image_url", "image_url": {"url": f"data:{attachment['mime_type']};base64,x"}}
        )
    return prepared


def _agent(parts, pause=None):
    executor = Mock()
    executor.pending_native_parts = list(parts)
    executor.check_pause = Mock(return_value=pause)

    def _execute(tools_dict, call):
        yield {"type": "tool_call", "data": {"status": "pending"}}
        return "Image F1 shot.png is attached below in a follow-up message.", call.id

    agent = Mock()
    agent.tool_executor = executor
    agent._check_context_limit = Mock(return_value=False)
    agent._execute_tool_action = Mock(side_effect=_execute)
    agent.llm = Mock()
    agent.llm.__class__.__name__ = "OpenAILLM"
    agent.llm.prepare_messages_with_attachments = Mock(side_effect=_openai_style_prepare)
    return agent


def _run(handler, agent, calls):
    gen = handler.handle_tool_calls(agent, calls, {}, [{"role": "user", "content": "q"}])
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


class TestHandlerAppendsTheImages:
    def test_images_follow_the_tool_results_in_a_user_message(self):
        agent = _agent([SHOT, PAGE])
        messages, pending = _run(_Handler(), agent, [ToolCall(id="c1", name="attachments_read", arguments={})])

        assert pending is None
        roles = [m["role"] for m in messages]
        assert roles == ["user", "assistant", "tool", "user"]
        note = messages[-1]
        text = note["content"][0]["text"]
        assert "F1 shot.png" in text and "F3 scan.pdf page 2" in text
        assert "untrusted" in text
        assert [p["type"] for p in note["content"][1:]] == ["image_url", "image_url"]
        agent.llm.prepare_messages_with_attachments.assert_called_once()
        assert [a for a in agent.llm.prepare_messages_with_attachments.call_args.args[1]] == [
            SHOT["attachment"], PAGE["attachment"]
        ]
        assert agent.tool_executor.pending_native_parts == []

    def test_nothing_is_added_without_images(self):
        agent = _agent([])
        messages, _ = _run(_Handler(), agent, [ToolCall(id="c1", name="attachments_list", arguments={})])
        assert [m["role"] for m in messages] == ["user", "assistant", "tool"]
        agent.llm.prepare_messages_with_attachments.assert_not_called()

    def test_a_paused_batch_drops_the_images(self):
        pause = {"call_id": "c2", "name": "client_tool", "tool_name": "client", "tool_id": "ct0",
                 "action_name": "client_tool", "llm_name": "client_tool", "arguments": {},
                 "pause_type": "requires_client_execution"}
        agent = _agent([SHOT])
        agent.tool_executor.check_pause = Mock(side_effect=[None, pause])
        messages, pending = _run(
            _Handler(), agent,
            [ToolCall(id="c1", name="attachments_read", arguments={}), ToolCall(id="c2", name="client_tool",
                                                                              arguments={})],
        )
        assert pending
        assert all(m["role"] != "user" or m["content"] == "q" for m in messages)
        assert agent.tool_executor.pending_native_parts == []

    def test_a_provider_failure_leaves_a_note_instead(self):
        agent = _agent([SHOT])
        agent.llm.prepare_messages_with_attachments = Mock(side_effect=RuntimeError("boom"))
        messages, _ = _run(_Handler(), agent, [ToolCall(id="c1", name="attachments_read", arguments={})])
        assert messages[-1]["role"] == "user"
        assert "could not be attached" in messages[-1]["content"]


class TestExecutorCollectsTheImages:
    def test_execute_moves_queued_images_to_the_executor(self, monkeypatch):
        executor = ToolExecutor(user="u")
        tools_dict = {}
        add_attachments_tool(tools_dict, user="u", current_ids=["id-a"], earlier_ids=[])
        executor.prepare_tools_for_llm(tools_dict)

        fake = Mock()
        fake.execute_action = Mock(return_value="Image F1 x.png is attached below in a follow-up message.")
        fake.drain_native_parts = Mock(return_value=[SHOT])
        fake.get_artifact_id = None
        fake.get_artifacts = None
        monkeypatch.setattr(executor, "_get_or_load_tool", lambda *a, **k: fake)
        monkeypatch.setattr("docsgpt.agents.tool_executor._record_proposed", lambda *a, **k: False)
        monkeypatch.setattr("docsgpt.agents.tool_executor._mark_executed", lambda *a, **k: None)

        call = types.SimpleNamespace(id="c1", name="attachments_read", arguments={"ref": "F1"},
                                     thought_signature=None)
        gen = executor.execute(tools_dict, call, "OpenAILLM")
        while True:
            try:
                next(gen)
            except StopIteration:
                break
        assert executor.pending_native_parts == [SHOT]
        assert tools_dict[ATTACHMENTS_TOOL_ID]["name"] == "attachments"


class TestProvidersFormatTheFollowUpMessage:
    def _messages(self):
        return [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "attachments_read", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "c1", "content": "Image F1 is attached below."},
            {"role": "user", "content": [{"type": "text", "text": "Images requested: F1"}]},
        ]

    def test_openai_chat_completions_and_responses(self, monkeypatch):
        from tests.llm.test_openai_responses import _make_llm

        llm = _make_llm(monkeypatch)
        prepared = llm.prepare_messages_with_attachments(self._messages(), [PAGE["attachment"]])
        assert prepared[-1]["content"][-1]["type"] == "image_url"
        # The image lands on the follow-up message, not on the turn's question.
        assert prepared[1]["content"] == "q"

        cleaned = llm._clean_messages_openai(prepared)
        assert cleaned[-1]["role"] == "user"
        assert any(p.get("type") == "image_url" for p in cleaned[-1]["content"])

        chained = llm._to_responses_input(llm._trim_for_previous_response(cleaned), chained=True)
        kinds = [item.get("type") for item in chained]
        assert "function_call_output" in kinds
        user_items = [item for item in chained if item.get("role") == "user"]
        assert user_items and any(
            part.get("type") == "input_image" for part in user_items[-1]["content"]
        )
        assert kinds.index("function_call_output") < chained.index(user_items[-1])

    def test_anthropic_merges_it_with_the_tool_results(self):
        from docsgpt.llm.anthropic import AnthropicLLM

        llm = AnthropicLLM.__new__(AnthropicLLM)
        prepared = llm.prepare_messages_with_attachments(self._messages(), [PAGE["attachment"]])
        mapped, _system = AnthropicLLM._clean_messages_anthropic(prepared)
        last = mapped[-1]
        assert last["role"] == "user"
        kinds = [block["type"] for block in last["content"]]
        assert kinds[0] == "tool_result" and "image" in kinds

    def test_google_reads_rendered_pages_from_their_data(self):
        from docsgpt.llm.google_ai import GoogleLLM

        llm = GoogleLLM.__new__(GoogleLLM)
        llm.storage = Mock()
        assert llm._read_attachment_bytes(PAGE["attachment"]) == b"\x89PNG fake"
        llm.storage.file_exists.assert_not_called()


class TestResearchStepsGetTheImagesToo:
    def test_step_tools_append_the_images(self):
        from docsgpt.agents.research_agent import ResearchAgent

        agent = ResearchAgent.__new__(ResearchAgent)
        agent.llm = Mock()
        agent.llm.__class__.__name__ = "OpenAILLM"
        agent.llm.prepare_messages_with_attachments = Mock(side_effect=_openai_style_prepare)
        agent.llm_handler = _Handler()

        executor = Mock()
        executor.pending_native_parts = [SHOT]
        executor.check_pause = Mock(return_value=None)

        def _execute(tools_dict, call, llm_class):
            yield {"type": "tool_call", "data": {}}
            return "Image F1 shot.png is attached below in a follow-up message.", call.id

        executor.execute = Mock(side_effect=_execute)
        messages, _ = agent._execute_step_tools_with_refinement(
            [ToolCall(id="c1", name="attachments_read", arguments={})], {}, [{"role": "user", "content": "q"}],
            executor, False,
        )
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"][-1]["type"] == "image_url"
