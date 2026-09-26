"""How the agent plans attachments into a turn's messages.

The planner itself is covered in ``test_attachment_budget.py``; these tests
pin the wiring: where the manifest and file text land, what gives way to
make room, what the LLM handler and usage accounting are handed, and the
events the client receives.
"""

from unittest.mock import Mock

import pytest

from docsgpt.agents.classic_agent import ClassicAgent
from docsgpt.agents.tools.attachments import ATTACHMENTS_TOOL_ID
from docsgpt.utils import num_tokens_from_string


def _att(idx, tokens, *, mime="text/plain", filename=None, pages=None, words=None):
    content = ("word " * tokens) if words is None else words
    extraction = {"status": "ok", "truncated": False, "original_tokens": tokens, "stored_tokens": tokens}
    if pages:
        extraction["page_count"] = pages
    return {
        "id": f"00000000-0000-0000-0000-{idx:012d}",
        "filename": filename or f"file_{idx}.txt",
        "mime_type": mime,
        "content": content,
        "token_count": tokens,
        "path": f"attachments/{idx}/file",
        "metadata": {"extraction": extraction},
    }


@pytest.fixture
def window(monkeypatch):
    def _set(limit):
        monkeypatch.setattr("docsgpt.core.model_utils.get_token_limit", lambda *a, **k: limit)

    return _set


def _agent(params, attachments, earlier=None, native=(), tools=True):
    params = dict(params)
    params["attachments"] = attachments
    params["earlier_attachments"] = earlier or []
    agent = ClassicAgent(**params)
    agent.llm.get_supported_attachment_types = Mock(return_value=list(native))
    agent.llm._supports_tools = tools
    return agent


def _enable_tool(agent):
    agent.attachments_tool_enabled = True
    tools_dict = {}
    agent._add_attachments_tool(tools_dict)
    return tools_dict


@pytest.mark.unit
class TestUserMessage:
    def test_text_attachments_go_into_the_user_turn_with_refs(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = _agent(agent_base_params, [_att(0, 50, filename="notes.txt", words="alpha beta gamma")])
        messages = agent._build_messages("SYSTEM", "What is in my file?")

        assert "alpha beta" not in messages[0]["content"], "system prompt stays cache-stable"
        user = messages[-1]["content"]
        assert user.startswith("<attached_files")
        assert '<file_content ref="F1" name="notes.txt">' in user
        assert "alpha beta gamma" in user
        assert user.rstrip().endswith("What is in my file?")

    def test_overflow_is_listed_not_inlined(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator, window
    ):
        window(20_000)
        files = [_att(i, 3_000) for i in range(10)]
        agent = _agent(agent_base_params, files)
        _enable_tool(agent)
        messages = agent._build_messages("SYSTEM", "Summarise these")

        user = messages[-1]["content"]
        for i in range(1, 11):
            assert f'ref="F{i}"' in user
        assert 'status="not_in_context"' in user
        total = sum(num_tokens_from_string(m["content"]) for m in messages)
        assert total < 20_000
        statuses = [f.status for f in agent.attachment_plan.files]
        assert statuses.count("inline") == 3
        assert "tool" in statuses

    def test_history_is_shed_to_make_room(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator, window
    ):
        window(20_000)
        agent_base_params["chat_history"] = [
            {"prompt": "old question " * 500, "response": "old answer " * 500} for _ in range(6)
        ]
        agent = _agent(agent_base_params, [_att(0, 8_000)])
        messages = agent._build_messages("SYSTEM", "Q?")

        assert agent.attachment_plan.files[0].status == "inline"
        total = sum(num_tokens_from_string(m["content"]) for m in messages)
        assert total < 20_000
        assert len(messages) < 2 + 2 * 6, "older history made way for the attachment"

    def test_earlier_turn_files_are_listed_but_not_inlined(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        earlier = _att(0, 50, filename="old.txt", words="earlier secret text")
        earlier.pop("content")
        agent = _agent(agent_base_params, [], earlier=[earlier])
        _enable_tool(agent)
        user = agent._build_messages("SYSTEM", "and now?")[-1]["content"]

        assert 'name="old.txt"' in user
        assert 'status="not_in_context"' in user
        assert "earlier secret text" not in user

    def test_no_attachments_leaves_the_turn_untouched(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = _agent(agent_base_params, [])
        assert agent._build_messages("SYSTEM", "Q?")[-1]["content"] == "Q?"
        assert agent.attachment_plan is None


@pytest.mark.unit
class TestNativeParts:
    def test_only_native_files_reach_the_handler(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        pdf = _att(0, 1_000, mime="application/pdf", filename="a.pdf", pages=2)
        txt = _att(1, 100, filename="b.txt")
        agent = _agent(agent_base_params, [pdf, txt], native=["application/pdf"])
        agent.llm_handler.prepare_messages = Mock(side_effect=lambda agent, msgs, atts: msgs)
        agent._build_messages("SYSTEM", "Q?")

        agent.llm_handler.prepare_messages.assert_called_once()
        assert agent.llm_handler.prepare_messages.call_args[0][2] == [pdf]

    def test_handler_does_not_merge_attachments_again(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = _agent(agent_base_params, [_att(0, 100)])
        messages = agent._build_messages("SYSTEM", "Q?")
        agent.llm_handler.process_message_flow = Mock(return_value=iter(()))
        list(agent._handle_response(iter(()), {}, messages, None))

        args = agent.llm_handler.process_message_flow.call_args[0]
        assert args[4] is None

    def test_context_count_sees_native_size(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        pdf = _att(0, 20_000, mime="application/pdf", filename="a.pdf", pages=40)
        agent = _agent(agent_base_params, [pdf], native=["application/pdf"])
        agent.llm_handler.prepare_messages = Mock(
            side_effect=lambda agent, msgs, atts: msgs[:-1]
            + [{"role": "user", "content": [
                {"type": "text", "text": msgs[-1]["content"]},
                {"type": "file", "file": {"file_id": "file-1"}},
            ]}]
        )
        messages = agent._build_messages("SYSTEM", "Q?")
        counted = agent._calculate_current_context_tokens(messages)
        assert counted >= 20_000


@pytest.mark.unit
class TestUsage:
    def test_text_attachments_are_not_counted_twice(
        self, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = _agent(agent_base_params, [_att(0, 500)])
        messages = agent._build_messages("SYSTEM", "Q?")
        agent._llm_gen(messages)
        kwargs = mock_llm.gen_stream.call_args[1]
        assert "_usage_attachments" not in kwargs

    def test_native_estimate_is_counted(
        self, agent_base_params, mock_llm, mock_llm_creator, mock_llm_handler_creator
    ):
        pdf = _att(0, 1_000, mime="application/pdf", filename="a.pdf", pages=2)
        agent = _agent(agent_base_params, [pdf], native=["application/pdf"])
        agent.llm_handler.prepare_messages = Mock(side_effect=lambda agent, msgs, atts: msgs)
        messages = agent._build_messages("SYSTEM", "Q?")
        agent._llm_gen(messages)
        kwargs = mock_llm.gen_stream.call_args[1]
        assert kwargs["_usage_attachments"] == agent.attachment_plan.native_tokens
        assert mock_llm._attachment_plan is agent.attachment_plan


@pytest.mark.unit
class TestToolAndEvents:
    def test_tool_added_only_when_enabled(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = _agent(agent_base_params, [_att(0, 10)])
        tools_dict = {}
        agent._add_attachments_tool(tools_dict)
        assert tools_dict == {}
        assert ATTACHMENTS_TOOL_ID in _enable_tool(agent)

    def test_tool_learns_the_plan(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator, window
    ):
        window(20_000)
        agent = _agent(agent_base_params, [_att(i, 3_000) for i in range(6)])
        tools_dict = _enable_tool(agent)
        agent._build_messages("SYSTEM", "Q?")
        statuses = tools_dict[ATTACHMENTS_TOOL_ID]["config"]["statuses"]
        assert statuses["F1"] == "inline"
        assert statuses["F6"] in ("tool", "partial")

    def test_refs_reach_sandbox_tools(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        earlier = _att(0, 10, filename="old.txt")
        agent = _agent(agent_base_params, [_att(1, 10)], earlier=[earlier])
        rows = agent._referenceable_attachments()
        assert [r["ref"] for r in rows] == ["F1", "F2"]

    def test_gen_emits_the_plan_before_the_answer(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = _agent(agent_base_params, [_att(0, 10)])

        def _inner(query, log_context):
            agent._build_messages("SYSTEM", query)
            yield {"answer": "hi"}

        agent._gen_inner = _inner
        agent.llm._uses_responses_api = Mock(return_value=False)
        events = list(agent.gen("Q?"))
        kinds = [next(iter(e)) if "type" not in e else e["type"] for e in events]
        assert kinds.index("attachment_plan") < kinds.index("answer")
        meta = next(e for e in events if "metadata" in e)
        assert meta["metadata"]["attachment_plan"][0]["ref"] == "F1"


@pytest.mark.unit
class TestModelsWithoutTools:
    def test_overflow_files_contribute_matching_excerpts(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator, window
    ):
        window(20_000)
        files = [_att(i, 3_000) for i in range(5)]
        files.append(
            _att(5, 3_000, words=("filler " * 1500) + "the capybara exam question answer " + "filler " * 1400)
        )
        agent = _agent(agent_base_params, files, tools=False)
        user = agent._build_messages("SYSTEM", "What did the capybara exam ask?")[-1]["content"]

        assert "<file_excerpts" in user
        assert 'ref="F6"' in user.split("<file_excerpts", 1)[1]
        assert "capybara exam question" in user
        total = num_tokens_from_string(user)
        assert total < 20_000

    def test_no_excerpts_when_the_model_can_use_the_tool(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator, window
    ):
        window(20_000)
        files = [_att(i, 3_000) for i in range(5)]
        files.append(_att(5, 3_000, words=("filler " * 1500) + "capybara " + "filler " * 1400))
        agent = _agent(agent_base_params, files)
        _enable_tool(agent)
        user = agent._build_messages("SYSTEM", "capybara?")[-1]["content"]
        assert "<file_excerpts" not in user

    def test_earlier_files_are_loaded_for_excerpts(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator, monkeypatch
    ):
        earlier = _att(0, 50, filename="old.txt")
        earlier.pop("content")
        agent = _agent(agent_base_params, [], earlier=[earlier], tools=False)
        loaded = {**earlier, "content": "the walrus section explains tusks"}
        monkeypatch.setattr(agent, "_load_attachment_texts", lambda ids: {earlier["id"]: loaded["content"]})
        user = agent._build_messages("SYSTEM", "walrus tusks?")[-1]["content"]
        assert "walrus section explains tusks" in user


@pytest.mark.unit
class TestAgentsThatBuildTheirOwnMessages:
    def test_apply_attachments_prefixes_the_last_user_message(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = _agent(agent_base_params, [_att(0, 50, words="synthesis input text")])
        messages = [
            {"role": "system", "content": "Write the report."},
            {"role": "user", "content": "Please write the report."},
        ]
        out = agent._apply_attachments(messages)
        assert out[-1]["content"].startswith("<attached_files")
        assert "synthesis input text" in out[-1]["content"]
        assert agent.attachment_plan is not None

    def test_apply_attachments_without_files_is_a_no_op(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = _agent(agent_base_params, [])
        messages = [{"role": "user", "content": "q"}]
        assert agent._apply_attachments(messages) == [{"role": "user", "content": "q"}]

    def test_listing_only_when_the_tool_is_offered(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = _agent(agent_base_params, [_att(0, 50)])
        assert agent._attachment_listing() == ""
        _enable_tool(agent)
        listing = agent._attachment_listing()
        assert 'ref="F1"' in listing and 'status="not_in_context"' in listing

    def test_supported_types_that_fail_mean_no_native_parts(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = _agent(agent_base_params, [])
        agent.llm.get_supported_attachment_types = Mock(side_effect=RuntimeError("x"))
        assert agent._native_attachment_types() == []
        agent.llm.get_supported_attachment_types = Mock(return_value="image/png")
        assert agent._native_attachment_types() == []

    def test_loading_text_for_excerpts(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator, pg_conn
    ):
        from contextlib import contextmanager
        from unittest.mock import patch

        from docsgpt.storage.db.repositories.attachments import AttachmentsRepository

        agent = _agent(agent_base_params, [])
        row = AttachmentsRepository(pg_conn).create(agent.user, "a.txt", "/a", content="stored text")

        @contextmanager
        def _yield():
            yield pg_conn

        with patch("docsgpt.storage.db.session.db_readonly", _yield):
            assert agent._load_attachment_texts([str(row["id"])]) == {str(row["id"]): "stored text"}
        assert agent._load_attachment_texts([]) == {}

        @contextmanager
        def _broken():
            raise RuntimeError("db down")
            yield

        with patch("docsgpt.storage.db.session.db_readonly", _broken):
            assert agent._load_attachment_texts(["x"]) == {}

    def test_excerpts_skip_when_there_is_no_room(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        from docsgpt.agents.attachment_budget import plan_attachments

        agent = _agent(agent_base_params, [])
        # Every file fits: there is nothing to excerpt, whatever the room.
        all_in = plan_attachments([_att(0, 100)], budget=10_000, supports_tools=False)
        assert all_in.files[0].status == "inline"
        assert agent._attachment_excerpts(all_in, "word", 5_000) == ""

        # A file was left out and matches the question, but no room is left.
        left_out = plan_attachments([_att(0, 2_000)], budget=100, supports_tools=False)
        assert left_out.files[0].status == "omitted"
        assert agent._attachment_excerpts(left_out, "word", 0) == ""
        assert agent._attachment_excerpts(left_out, "word", 100) == ""
        # With room, the same file does contribute an excerpt.
        assert "<file_excerpts>" in agent._attachment_excerpts(left_out, "word", 2_000)


@pytest.mark.unit
def test_tool_schemas_are_reserved_before_attachments_are_planned(
    agent_base_params, mock_llm_creator, mock_llm_handler_creator, window
):
    window(12_000)
    files = [_att(i, 3_000) for i in range(4)]
    without_tools = _agent(agent_base_params, files)
    without_tools._build_messages("SYSTEM", "Q?")

    with_tools = _agent(agent_base_params, files)
    with_tools.tools = [
        {"type": "function", "function": {"name": f"t{i}", "description": "word " * 1000}}
        for i in range(6)
    ]
    with_tools._build_messages("SYSTEM", "Q?")

    assert with_tools.attachment_plan.budget < without_tools.attachment_plan.budget


@pytest.mark.unit
def test_document_shedding_stops_when_no_documents_remain(
    agent_base_params, mock_llm_creator, mock_llm_handler_creator, window
):
    """With attachments taking the room, the "searched, found nothing" note
    alone can exceed the document budget; shedding must stop at an empty
    list rather than loop on it."""
    window(4_000)
    agent_base_params["retrieved_docs"] = [{"filename": "d.pdf", "text": "doc " * 300}]
    agent_base_params["sources_were_searched"] = True
    agent = _agent(agent_base_params, [_att(0, 2_000)])
    real_block = agent._build_document_block
    calls = []

    def _counted():
        calls.append(1)
        if len(calls) > 20:
            raise RuntimeError("document shedding did not stop")
        return real_block()

    agent._build_document_block = _counted
    messages = agent._build_messages("SYSTEM", "question " * 800)
    assert agent.retrieved_docs == []
    assert messages[-1]["role"] == "user"
