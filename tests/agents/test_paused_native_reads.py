"""Images an attachments read queued survive a pause for a client tool."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from docsgpt.agents.tools import attachments as tool
from docsgpt.llm.handlers.openai import OpenAILLMHandler

pytestmark = pytest.mark.unit

PATH_IMAGE = {
    "attachment": {"path": "inputs/u/attachments/a/plan.png", "mime_type": "image/png", "filename": "plan.png"},
    "label": "F2 plan.png",
}
PAGE_IMAGE = {
    "attachment": {"data": "QUJD" * 1000, "mime_type": "image/png", "page": 3, "source_path": "inputs/u/scan.pdf"},
    "label": "F1 scan.pdf page 3",
}


class TestSerialization:
    def test_no_image_bytes_are_kept(self):
        saved = tool.serialize_native_reads([PATH_IMAGE, PAGE_IMAGE])

        assert json.loads(json.dumps(saved)) == saved
        assert "QUJD" not in json.dumps(saved)
        assert saved[0] == {"label": "F2 plan.png", "attachment": PATH_IMAGE["attachment"]}
        assert saved[1] == {"label": "F1 scan.pdf page 3", "render": {"path": "inputs/u/scan.pdf", "page": 3}}

    def test_a_rendered_page_without_its_source_cannot_be_kept(self):
        orphan = {"attachment": {"data": "QUJD", "mime_type": "image/png", "page": 1}, "label": "x"}
        assert tool.serialize_native_reads([orphan]) == []

    def test_restore_renders_pages_again(self):
        saved = tool.serialize_native_reads([PATH_IMAGE, PAGE_IMAGE])
        rendered = {"data": "REDRAWN", "mime_type": "image/png", "page": 3}
        with patch.object(tool, "_read_original", return_value=b"%PDF") as read, patch.object(
            tool, "_render_pages", return_value=[rendered]
        ) as render:
            parts = tool.restore_native_reads(saved)

        read.assert_called_once_with("inputs/u/scan.pdf")
        render.assert_called_once_with(b"%PDF", [3])
        assert parts[0] == PATH_IMAGE
        assert parts[1]["attachment"]["data"] == "REDRAWN"
        assert parts[1]["label"] == "F1 scan.pdf page 3"

    def test_a_page_that_cannot_be_rendered_is_skipped(self):
        saved = tool.serialize_native_reads([PAGE_IMAGE])
        with patch.object(tool, "_read_original", side_effect=FileNotFoundError):
            assert tool.restore_native_reads(saved) == []


class TestPausedBatchKeepsTheImages:
    def test_the_images_wait_on_the_executor_instead_of_being_dropped(self):
        handler = OpenAILLMHandler()
        executor = SimpleNamespace(pending_native_parts=[PATH_IMAGE])
        agent = SimpleNamespace(tool_executor=executor, llm=Mock())

        messages = handler.append_native_reads(agent, [{"role": "user", "content": "q"}], paused=True)

        assert messages == [{"role": "user", "content": "q"}]
        assert executor.pending_native_parts == []
        assert executor.paused_native_parts == [PATH_IMAGE]

    def test_the_pause_state_carries_them(self):
        handler = OpenAILLMHandler()
        executor = SimpleNamespace(pending_native_parts=[], paused_native_parts=[PATH_IMAGE, PAGE_IMAGE])
        agent = SimpleNamespace(tool_executor=executor)

        saved = handler._paused_native_reads(agent)

        assert saved == tool.serialize_native_reads([PATH_IMAGE, PAGE_IMAGE])
        assert executor.paused_native_parts == []


class TestResumeShowsThem:
    def test_gen_continuation_appends_the_saved_images_after_the_tool_results(self):
        from docsgpt.agents.classic_agent import ClassicAgent

        agent = ClassicAgent.__new__(ClassicAgent)
        agent.llm = MagicMock()
        agent.llm.prepare_messages_with_attachments.side_effect = lambda messages, attachments: [
            *messages[:-1],
            {**messages[-1], "content": [*messages[-1]["content"], {"type": "image_url", "image_url": {"url": "x"}}]},
        ]
        agent.llm_handler = OpenAILLMHandler()
        agent.tool_executor = MagicMock()
        agent.tool_executor.pending_native_parts = [PATH_IMAGE]
        agent._prepare_tools = Mock()
        agent._guard_tool_result_text = lambda text: text
        agent.retrieved_docs = []
        agent._get_truncated_tool_calls = Mock(return_value=[])
        agent._emit_responses_metadata = Mock(return_value=iter([]))
        sent = {}

        def _gen(messages, **kwargs):
            sent["messages"] = list(messages)
            return iter([])

        agent._llm_gen = _gen
        agent._handle_response = Mock(return_value=iter([]))
        pending = [{"call_id": "c1", "name": "search", "arguments": {}}]
        list(
            agent._gen_continuation_inner(
                [{"role": "user", "content": "q"}], {}, pending, [{"call_id": "c1", "result": "found"}]
            )
        )

        roles = [m["role"] for m in sent["messages"]]
        assert roles == ["user", "assistant", "tool", "user"]
        assert any(p.get("type") == "image_url" for p in sent["messages"][-1]["content"])
