"""The attachment plan wired into message building and the context gate."""

from unittest.mock import Mock, patch

import pytest

from docsgpt.agents.attachment_budget import AttachmentPlan, FileStatus
from docsgpt.agents.base import BaseAgent
from docsgpt.agents.context_overflow import ContextOverflowError
from docsgpt.utils import num_tokens_from_string

pytestmark = pytest.mark.unit

WINDOW = 100_000


class _Agent(BaseAgent):
    def _gen_inner(self, query, log_context=None):
        yield {"answer": "ok"}


def _llm(types=()):
    llm = Mock()
    llm.get_supported_attachment_types = Mock(return_value=list(types))
    llm._supports_tools = Mock(return_value=True)
    llm.model_id = "m"
    return llm


def text_att(name, tokens, att_id=None):
    body = ("lorem ipsum " * (tokens // 2 + 1))
    return {
        "id": att_id or f"id-{name}",
        "filename": name,
        "mime_type": "text/plain",
        "content": body,
        "token_count": num_tokens_from_string(body),
        "metadata": {"extraction": {"status": "ok", "truncated": False}},
    }


def _agent(**kwargs):
    kwargs.setdefault("attachment_planning", True)
    agent = _Agent(
        endpoint="stream",
        llm_name="openai",
        model_id="m",
        api_key="k",
        llm=kwargs.pop("llm", _llm()),
        llm_handler=Mock(),
        decoded_token={"sub": "u"},
        **kwargs,
    )
    return agent


@pytest.fixture(autouse=True)
def _window():
    with patch("docsgpt.core.model_utils.get_token_limit", return_value=WINDOW):
        yield


class TestPlanIsBuiltWithTheMessages:
    def test_small_attachments_are_planned_inline(self):
        agent = _agent(attachments=[text_att("a.txt", 500), text_att("b.txt", 700)])
        agent._prepare_tools({})

        messages = agent._build_messages("system prompt", "what is in the files?")

        plan = agent.attachment_plan
        assert isinstance(plan, AttachmentPlan)
        assert [f.status for f in plan.files] == [FileStatus.INLINE, FileStatus.INLINE]
        # The current turn's message is remembered so later stages can find it.
        assert messages[-1] is agent._current_turn_message

    def test_without_planning_nothing_changes(self):
        agent = _agent(attachments=[text_att("a.txt", 500)], attachment_planning=False)
        agent._build_messages("system prompt", "q")
        assert agent.attachment_plan is None

    def test_no_files_no_plan(self):
        agent = _agent(attachments=[])
        agent._build_messages("system prompt", "q")
        assert agent.attachment_plan is None

    def test_earlier_files_alone_still_get_a_plan(self):
        agent = _agent(attachments=[], earlier_attachments=[text_att("old.txt", 500)])
        agent._build_messages("system prompt", "q")
        assert [f.status for f in agent.attachment_plan.files] == [FileStatus.EARLIER]

    def test_capabilities_are_computed_when_tools_were_not_prepared(self):
        agent = _agent(attachments=[text_att("a.txt", 500)])
        agent._build_messages("system prompt", "q")
        assert agent.turn_capabilities is not None
        assert agent.attachment_plan.capabilities is agent.turn_capabilities


class TestBudgetAgainstTheTurn:
    def test_attach_after_compression_budgets_against_the_summary_and_kept_history(self):
        files = [text_att(f"r{i}.txt", 9_000) for i in range(8)]
        fresh = _agent(attachments=files)
        fresh._build_messages("system prompt", "q")
        assert fresh.attachment_plan.budget == WINDOW // 2

        summary = "summary " * 20_000
        history = [{"prompt": "earlier " * 15_000, "response": "answer " * 15_000}]
        compressed = _agent(attachments=files, compressed_summary=summary, chat_history=history)
        compressed._build_messages("system prompt", "q")

        kept = num_tokens_from_string(summary) + num_tokens_from_string(
            history[0]["prompt"]
        ) + num_tokens_from_string(history[0]["response"])
        assert compressed.attachment_plan.budget <= int(WINDOW * 0.9) - kept
        assert compressed.attachment_plan.budget < fresh.attachment_plan.budget
        # Whatever was planned fits next to the summary and the kept history.
        assert compressed.attachment_plan.reserved_tokens <= compressed.attachment_plan.budget

    def test_a_full_attach_turn_does_not_trigger_tool_loop_compression(self):
        # History alone sits well under the compression threshold; a turn
        # that fills its attachment budget must not cross it before the
        # first tool call.
        files = [text_att(f"r{i}.txt", 9_000) for i in range(8)]
        history = [{"prompt": "earlier " * 18_000, "response": "answer " * 18_000}]
        agent = _agent(attachments=files, chat_history=history)
        agent._prepare_tools({})
        messages = agent._build_messages("system prompt", "q")

        assert agent.attachment_plan.inline_tokens > 0
        assert agent._check_context_limit(messages) is False

    def test_documents_shed_before_attachments(self):
        docs = [{"title": f"d{i}", "text": "doc text " * 1500, "source": "s"} for i in range(20)]
        agent = _agent(attachments=[text_att("a.txt", 30_000)], retrieved_docs=list(docs))
        messages = agent._build_messages("system prompt", "q")

        plan = agent.attachment_plan
        assert plan.files[0].status == FileStatus.INLINE
        assert len(agent.retrieved_docs) < len(docs)
        total = sum(num_tokens_from_string(m["content"]) for m in messages if isinstance(m["content"], str))
        assert total + plan.reserved_tokens < WINDOW


class TestContextGateCountsThePlan:
    def test_pending_attachments_are_counted_before_they_are_merged(self):
        agent = _agent(attachments=[text_att("a.txt", 20_000)])
        messages = agent._build_messages("system prompt", "q")
        bare = sum(num_tokens_from_string(m["content"]) for m in messages)

        counted = agent._calculate_current_context_tokens(messages)

        assert counted >= bare + agent.attachment_plan.inline_tokens

    def test_planned_native_size_replaces_the_flat_estimate(self):
        pdf = {
            "id": "p1",
            "filename": "long.pdf",
            "mime_type": "application/pdf",
            "content": "x",
            "token_count": 30_000,
            "metadata": {"page_count": 10, "extraction": {"status": "ok", "original_tokens": 30_000}},
        }
        agent = _agent(attachments=[pdf], llm=_llm(types=["application/pdf"]))
        messages = agent._build_messages("system prompt", "q")
        carrier = agent._current_turn_message
        # What a provider appends for a native PDF.
        carrier["content"] = [{"type": "text", "text": "q"}, {"type": "file", "file": {"file_id": "f"}}]
        agent.note_attachments_merged(carrier, native_estimate=1500)

        counted = agent._calculate_current_context_tokens(messages)

        assert counted >= 30_000

    def test_a_rebuilt_list_without_the_turn_message_adds_nothing(self):
        agent = _agent(attachments=[text_att("a.txt", 20_000)])
        agent._build_messages("system prompt", "q")
        other = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
        assert agent._calculate_current_context_tokens(other) < 100


class TestTypedOverflow:
    def test_enforce_raises_a_typed_error_with_sizes(self):
        agent = _agent()
        agent.llm = Mock()
        huge = [{"role": "user", "content": "word " * (WINDOW + 10)}]

        with pytest.raises(ContextOverflowError) as info:
            agent._enforce_context_window(huge)

        assert info.value.needed_tokens > WINDOW
        assert info.value.available_tokens == WINDOW
        # Still a ValueError for callers that catch the old type.
        assert isinstance(info.value, ValueError)

    def test_system_prompt_with_no_room_is_typed(self):
        agent = _agent()
        with pytest.raises(ContextOverflowError):
            agent._build_messages("word " * WINDOW, "q")


class TestSandboxToolsSeeTheConversationFiles:
    def test_executor_gets_earlier_files_then_this_turns_in_upload_order(self):
        old = text_att("old.csv", 10, att_id="old")
        new = text_att("new.csv", 10, att_id="new")
        agent = _agent(attachments=[new], earlier_attachments=[old])
        agent.tool_executor = Mock()

        agent._execute_tool_action({}, Mock())

        # Refs F1, F2 resolve against this order, exactly as the manifest numbers them.
        assert [a["id"] for a in agent.tool_executor.attachments] == ["old", "new"]

    def test_without_earlier_files_only_this_turns_are_passed(self):
        new = text_att("new.csv", 10, att_id="new")
        agent = _agent(attachments=[new])
        agent.tool_executor = Mock()

        agent._execute_tool_action({}, Mock())

        assert [a["id"] for a in agent.tool_executor.attachments] == ["new"]
