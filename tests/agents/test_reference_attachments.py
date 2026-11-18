"""``attachments_mode: "reference"``: files are listed for the tools and never inlined."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, Mock, patch

import pytest

from docsgpt.agents.attachment_budget import (
    AttachmentPlan,
    FileStatus,
    plan_attachments,
    plan_listing,
)
from docsgpt.agents.attachment_context import render_attachment_block
from docsgpt.agents.base import BaseAgent
from docsgpt.agents.turn_capabilities import TurnCapabilities
from docsgpt.utils import num_tokens_from_string

pytestmark = pytest.mark.unit

SECRET = "the indemnity cap is forty-two thousand euros"


def caps(*, attachments_tool=True, sandbox=True, vision=False):
    return TurnCapabilities(
        tool_calling=True,
        vision=vision,
        native_pdf=False,
        sandbox=sandbox,
        window=200_000,
        is_v1=True,
        attachments_tool=attachments_tool,
        sandbox_action="run_code" if sandbox else None,
        attachments_actions=("attachments_list", "attachments_read", "attachments_search") if attachments_tool else (),
        supported_attachment_types=("image/png",) if vision else (),
    )


def att(name, body=SECRET, *, att_id=None, mime="text/plain", status="ok", pages=None, size=None, archive=None):
    metadata = {
        "content_hash": hashlib.sha256(f"{name}:{body}".encode()).hexdigest(),
        "extraction": {"status": status, "truncated": False},
    }
    if pages:
        metadata["page_count"] = pages
    if archive:
        metadata["archive"] = archive
    return {
        "id": att_id or f"id-{name}",
        "filename": name,
        "mime_type": mime,
        "content": body,
        "token_count": num_tokens_from_string(body) if body else 0,
        "size": size if size is not None else len(body) + 10,
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class TestPlanner:
    def test_reference_files_are_listed_not_inlined(self):
        files = [att("contract.txt"), att("prices.csv", "a,b\n1,2", mime="text/csv"), att("scan.png", mime="image/png")]
        plan = plan_attachments(files, caps(vision=True), budget=100_000, reference=True)
        assert [f.status for f in plan.files] == [FileStatus.REFERENCE] * 3
        assert plan.inline_tokens == 0
        assert all(not f.in_context for f in plan.files)

    def test_earlier_unreadable_and_archive_files_keep_their_status(self):
        earlier = [att("old.txt")]
        current = [
            att("broken.docx", "", status="failed"),
            att("bundle.zip", "index", mime="application/zip", archive={"members": 2}),
            att("new.txt"),
        ]
        plan = plan_attachments(current, caps(), budget=100_000, earlier=earlier, reference=True)
        assert [f.status for f in plan.files] == [
            FileStatus.EARLIER,
            FileStatus.UNREADABLE,
            FileStatus.ARCHIVE,
            FileStatus.REFERENCE,
        ]

    def test_without_the_attachments_tool_the_mode_is_ignored(self):
        files = [att("contract.txt")]
        reference = plan_attachments(files, caps(attachments_tool=False, sandbox=False), budget=100_000, reference=True)
        default = plan_attachments(files, caps(attachments_tool=False, sandbox=False), budget=100_000)
        assert [f.status for f in reference.files] == [f.status for f in default.files] == [FileStatus.INLINE]

    def test_default_mode_is_unchanged(self):
        files = [att("contract.txt"), att("prices.csv", "a,b\n1,2", mime="text/csv")]
        plan = plan_attachments(files, caps(), budget=100_000)
        assert [f.status for f in plan.files] == [FileStatus.INLINE, FileStatus.SANDBOX]


# ---------------------------------------------------------------------------
# What the model is told
# ---------------------------------------------------------------------------


class TestManifest:
    def test_manifest_lists_the_files_and_how_to_reach_them_without_their_content(self):
        files = [att("contract.txt", pages=None), att("report.pdf", mime="application/pdf", pages=120)]
        plan = plan_attachments(files, caps(), budget=100_000, reference=True)
        block = render_attachment_block(plan)

        assert SECRET not in block
        assert "<attached_file " not in block
        assert "- F1 contract.txt | text/plain" in block and "| reference" in block
        assert "F2 report.pdf | application/pdf" in block and "120 pages" in block
        assert "Files marked reference (F1, F2)" in block
        assert "attachments_search" in block and "attachments_read" in block
        assert 'load them into run_code by passing the ref in "inputs"' in block

    def test_without_the_sandbox_only_the_attachments_tool_is_named(self):
        plan = plan_attachments([att("contract.txt")], caps(sandbox=False), budget=100_000, reference=True)
        block = render_attachment_block(plan)
        assert "run_code" not in block and "attachments_read" in block

    def test_default_manifest_is_unchanged_by_the_new_status(self):
        plan = plan_attachments([att("contract.txt")], caps(), budget=100_000)
        block = render_attachment_block(plan)
        assert "reference" not in block
        assert SECRET in block


class TestListing:
    def test_listing_maps_refs_to_attachment_ids(self):
        files = [att("contract.txt", att_id="a-1", size=2048), att("report.pdf", mime="application/pdf", pages=3)]
        plan = plan_attachments(files, caps(), budget=100_000, earlier=[att("old.txt", att_id="a-0")], reference=True)
        listing = plan_listing(plan)
        assert [(e["ref"], e["id"], e["filename"], e["status"]) for e in listing] == [
            ("F1", "a-0", "old.txt", "earlier"),
            ("F2", "a-1", "contract.txt", "reference"),
            ("F3", "id-report.pdf", "report.pdf", "reference"),
        ]
        assert listing[1]["size"] == 2048 and listing[1]["mime_type"] == "text/plain"
        assert listing[2]["pages"] == 3 and listing[2]["tokens"] > 0

    def test_a_resent_copy_is_listed_once_under_its_first_id(self):
        first = att("contract.txt", att_id="a-1")
        again = {**att("contract.txt", att_id="a-2")}
        plan = plan_attachments([again], caps(), budget=100_000, earlier=[first], reference=True)
        assert [(e["ref"], e["id"]) for e in plan_listing(plan)] == [("F1", "a-1")]


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------


class _Agent(BaseAgent):
    def _gen_inner(self, query, log_context=None):
        yield {"answer": "ok"}


def _agent(**kwargs):
    llm = Mock()
    llm.get_supported_attachment_types = Mock(return_value=[])
    llm._supports_tools = Mock(return_value=True)
    llm.model_id = "m"
    return _Agent(
        endpoint="stream",
        llm_name="openai",
        model_id="m",
        api_key="k",
        llm=llm,
        llm_handler=Mock(),
        decoded_token={"sub": "u"},
        attachment_planning=True,
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _window():
    with patch("docsgpt.core.model_utils.get_token_limit", return_value=100_000):
        yield


class TestAgent:
    def _plan(self, **kwargs):
        agent = _agent(**kwargs)
        tools: dict = {}
        agent._add_attachments_tool(tools)
        agent._prepare_tools(tools)
        agent._build_messages("system prompt", "what is the cap?")
        return agent

    def test_reference_mode_plans_reference(self):
        agent = self._plan(attachments=[att("contract.txt")], attachments_mode="reference")
        assert agent.reference_attachments is True
        assert [f.status for f in agent.attachment_plan.files] == [FileStatus.REFERENCE]
        assert SECRET not in render_attachment_block(agent.attachment_plan)
        # The tool's listing shows the same status.
        assert agent._attachments_tool_config["plan"]["F1"]["status"] == "reference"

    @pytest.mark.parametrize("mode", [None, "auto", "anything"])
    def test_other_modes_inline_as_before(self, mode):
        agent = self._plan(attachments=[att("contract.txt")], attachments_mode=mode)
        assert [f.status for f in agent.attachment_plan.files] == [FileStatus.INLINE]

    def test_a_resent_round_keeps_reference_mode(self):
        agent = _agent(attachments=[att("contract.txt")], attachments_mode="reference")
        agent.agent_tools = []
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
        agent.prepare_resent_attachments({}, messages)
        assert [f.status for f in agent.attachment_plan.files] == [FileStatus.REFERENCE]


# ---------------------------------------------------------------------------
# Refs reach the tools
# ---------------------------------------------------------------------------


class TestRefsReachTheTools:
    def test_attachments_tool_reads_a_reference_file(self, pg_conn, monkeypatch):
        from docsgpt.agents.tools.attachments import AttachmentsTool, build_attachments_tool_config
        from docsgpt.storage.db.repositories.attachments import AttachmentsRepository

        @contextmanager
        def _use():
            yield pg_conn

        monkeypatch.setattr("docsgpt.agents.tools.attachments.db_readonly", _use)
        row = AttachmentsRepository(pg_conn).create(
            "u", "contract.txt", "/uploads/contract.txt", mime_type="text/plain", size=100,
            content=SECRET, token_count=num_tokens_from_string(SECRET),
            metadata={"extraction": {"status": "ok"}},
        )
        config = build_attachments_tool_config(user="u", current_ids=[str(row["id"])], earlier_ids=[])
        config["plan"] = {"F1": {"status": "reference"}}
        tool = AttachmentsTool(config)

        assert "F1 contract.txt" in tool.execute_action("attachments_list")
        assert "| reference" in tool.execute_action("attachments_list")
        assert SECRET in tool.execute_action("attachments_read", ref="F1")
        assert "forty-two" in tool.execute_action("attachments_search", query="indemnity cap")

    def test_code_executor_inputs_resolve_a_reference_files_ref(self, monkeypatch):
        from docsgpt.agents.tools import attachment_bridge

        rows = [att("old.csv", att_id="a-0"), att("contract.txt", att_id="a-1")]
        monkeypatch.setattr(attachment_bridge, "_verify_owner", lambda attachment, user_id: attachment)
        assert attachment_bridge.match_attachment(rows, "F2", "u")["id"] == "a-1"


# ---------------------------------------------------------------------------
# The request and the response
# ---------------------------------------------------------------------------


class TestRequestAndResponse:
    def test_v1_request_carries_the_mode_on_a_turn_and_a_resent_round(self):
        from docsgpt.api.v1.translator import translate_request

        turn = translate_request(
            {"messages": [{"role": "user", "content": "q"}], "docsgpt": {"attachments_mode": "reference"}}, "k"
        )
        assert turn["attachments_mode"] == "reference"
        resent = translate_request(
            {
                "messages": [
                    {"role": "user", "content": "q"},
                    {"role": "assistant", "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": "{}"}}]},
                    {"role": "tool", "tool_call_id": "c", "content": "r"},
                ],
                "docsgpt": {"attachments_mode": "reference"},
            },
            "k",
        )
        assert resent["attachments_mode"] == "reference"
        plain = translate_request({"messages": [{"role": "user", "content": "q"}]}, "k")
        assert "attachments_mode" not in plain

    @pytest.mark.parametrize("mode, ok", [("reference", True), ("auto", True), ("inline", False), (1, False)])
    def test_v1_validates_the_mode(self, flask_app, mode, ok):
        from docsgpt.api.v1.routes import _validate_request_options

        with flask_app.app_context():
            error = _validate_request_options({"docsgpt": {"attachments_mode": mode}}, {})
        if ok:
            assert error is None
        else:
            assert error.status_code == 400
            assert error.get_json()["error"]["code"] == "invalid_attachments_mode"

    def test_processor_reads_the_mode(self):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor.__new__(StreamProcessor)
        processor.data = {"attachments_mode": "reference"}
        assert processor.attachments_mode() == "reference"
        processor.data = {"attachments_mode": "whatever"}
        assert processor.attachments_mode() == "auto"
        processor.data = {}
        assert processor.attachments_mode() == "auto"

    def test_stream_end_and_non_stream_result_carry_the_listing(self, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        plan = plan_attachments([att("contract.txt", att_id="a-1")], caps(), budget=100_000, reference=True)
        agent = MagicMock()
        agent.gen.return_value = iter([{"answer": "The cap is in F1."}])
        agent.tool_calls = []
        agent.attachment_plan = plan
        with flask_app.app_context():
            resource = BaseAnswerResource()
            stream = list(
                resource.complete_stream(
                    question="q", agent=agent, conversation_id=None, user_api_key=None,
                    decoded_token={"sub": "u"}, should_persist=False,
                )
            )
            result = resource.process_response_stream(iter(stream))
        end = json.loads(stream[-1].split("data:", 1)[1])
        assert end["type"] == "end"
        assert end["attachments"] == plan_listing(plan)
        assert result["attachments"][0]["ref"] == "F1" and result["attachments"][0]["id"] == "a-1"

    def test_v1_response_carries_the_listing(self):
        from docsgpt.api.v1.translator import StreamTranslationState, translate_response, translate_stream_event

        listing = [{"ref": "F1", "id": "a-1", "filename": "contract.txt", "mime_type": "text/plain", "status": "reference"}]
        response = translate_response("c", "x", None, None, "", "agent", attachments=listing)
        assert response["docsgpt"]["attachments"] == listing
        chunks = translate_stream_event({"type": "end", "attachments": listing}, "id", "agent", state=StreamTranslationState())
        first = json.loads(chunks[0][len("data: "):])
        assert first["docsgpt"] == {"type": "attachments", "attachments": listing}
        assert chunks[-1] == "data: [DONE]\n\n"

    def test_a_listing_that_fails_never_breaks_the_turn(self, monkeypatch):
        from docsgpt.api.answer.routes import base

        def _boom(plan):
            raise RuntimeError("bad row")

        monkeypatch.setattr(base, "plan_listing", _boom)
        agent = MagicMock()
        agent.attachment_plan = plan_attachments([att("a.txt")], caps(), budget=100_000)
        assert base._attachment_listing(agent) == []

    def test_an_agent_without_a_plan_adds_nothing(self):
        from docsgpt.api.answer.routes.base import _attachment_listing

        assert _attachment_listing(MagicMock()) == []
        agent = MagicMock()
        agent.attachment_plan = AttachmentPlan(files=[], capabilities=caps(), budget=0)
        assert _attachment_listing(agent) == []
