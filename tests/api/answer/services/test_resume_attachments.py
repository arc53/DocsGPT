"""A resumed turn keeps the files of the turn that paused.

A turn that waits on a client tool (or an approval) is rebuilt from its saved
state when the client answers. That rebuild used to drop the turn's files: the
messages still listed them, but the agent had none, so ``run_code`` with
``inputs: ["F1"]`` failed with "input artifact F1 not found", the ``F`` ref
listing vanished from the response, and an attachment-aware fallback had no
text to swap in. The pause now saves the files by id (plus the mode, the
listing, the compression point and the backup models) and the resume reads
them back as their owner.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, Mock, patch

import pytest

from docsgpt.agents.base import BaseAgent
from docsgpt.utils import num_tokens_from_string

OWNER = "owner"
BODY = "the indemnity cap is forty-two thousand euros"


class _Agent(BaseAgent):
    def _gen_inner(self, query, log_context=None):
        yield {"answer": "ok"}


def _att(name, *, att_id=None, mime="text/plain", body=BODY):
    return {
        "id": att_id or f"id-{name}",
        "filename": name,
        "mime_type": mime,
        "content": body,
        "token_count": num_tokens_from_string(body),
        "size": len(body) + 10,
        "metadata": {
            "content_hash": hashlib.sha256(f"{name}:{body}".encode()).hexdigest(),
            "extraction": {"status": "ok", "truncated": False},
        },
    }


def _agent(**kwargs):
    llm = Mock()
    llm.get_supported_attachment_types = Mock(return_value=[])
    llm._supports_tools = Mock(return_value=True)
    llm.model_id = "m"
    llm._backup_models = kwargs.pop("backup_models", [])
    kwargs.setdefault("attachment_planning", True)
    return _Agent(
        endpoint="stream",
        llm_name="openai",
        model_id="m",
        api_key="k",
        llm=llm,
        llm_handler=Mock(),
        decoded_token={"sub": OWNER},
        **kwargs,
    )


def _planned(**kwargs):
    agent = _agent(**kwargs)
    tools: dict = {}
    agent._add_attachments_tool(tools)
    agent._prepare_tools(tools)
    agent._build_messages("system prompt", "what is the cap?")
    return agent


@pytest.fixture(autouse=True)
def _window():
    with patch("docsgpt.core.model_utils.get_token_limit", return_value=100_000):
        yield


def _state(**agent_config) -> dict:
    return {
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}],
        "pending_tool_calls": [
            {"call_id": "call_1", "name": "search", "tool_name": "search", "llm_name": "search", "arguments": {}}
        ],
        "tools_dict": {},
        "tool_schemas": [],
        "agent_config": {
            "model_id": "gpt-test",
            "llm_name": "openai",
            "api_key": "k",
            "agent_type": "ClassicAgent",
            "prompt": "sys",
            **agent_config,
        },
    }


# ---------------------------------------------------------------------------
# What a pause saves
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPausedTurnState:
    def test_a_reference_turn_saves_its_files_mode_and_listing(self):
        agent = _planned(
            attachments=[_att("contract.txt", att_id="a-cur")],
            earlier_attachments=[_att("letterhead.docx", att_id="a-old", body="header")],
            skipped_attachments=[{"filename": "huge.pdf", "reason": "too large"}],
            attachments_mode="reference",
        )

        files = agent.paused_turn_state()["attachments"]

        assert files["current"] == ["a-cur"]
        assert files["earlier"] == ["a-old"]
        assert files["mode"] == "reference"
        assert files["planning"] is True
        assert files["skipped"] == [{"filename": "huge.pdf", "reason": "too large"}]
        assert [(e["ref"], e["id"], e["status"]) for e in files["listing"]] == [
            ("F1", "a-old", "earlier"),
            ("F2", "a-cur", "reference"),
        ]
        json.dumps(files)

    def test_a_turn_without_files_saves_none(self):
        assert _agent().paused_turn_state()["attachments"] is None

    def test_the_compression_point_and_backup_models_are_saved(self):
        agent = _agent(last_compression_at="2026-10-01 10:00:00+00:00", backup_models=["gpt-backup"])

        state = agent.paused_turn_state()

        assert state["last_compression_at"] == "2026-10-01 10:00:00+00:00"
        assert state["backup_models"] == ["gpt-backup"]

    def test_the_turns_decisions_are_saved(self):
        from docsgpt.decisions import record
        from docsgpt.decisions.testing import FakeDecider, installed

        rec = record.DecisionRecord()
        with installed(FakeDecider()), record.activate(rec):
            record.add("injection_input", {"p": 0.03}, status="ok", applied=False)
            state = _agent().paused_turn_state()

        assert state["decisions"] == rec.snapshot()
        assert state["decisions"]["entries"][0]["feature"] == "injection_input"
        json.dumps(state["decisions"])

    def test_a_turn_without_decisions_saves_none(self):
        assert _agent().paused_turn_state()["decisions"] is None

    def test_a_resumed_turn_saves_what_it_was_given_for_its_next_pause(self):
        listing = [{"ref": "F1", "id": "a-cur", "filename": "contract.txt", "status": "reference"}]
        agent = _agent(attachments=[_att("contract.txt", att_id="a-cur")], attachments_mode="reference")
        agent.resume_paused_attachments(listing)

        files = agent.paused_turn_state()["attachments"]

        assert files["current"] == ["a-cur"]
        assert files["mode"] == "reference"
        assert files["listing"] == listing


# ---------------------------------------------------------------------------
# What a resume restores
# ---------------------------------------------------------------------------


@pytest.fixture
def resume(monkeypatch):
    """Resume a saved state; returns (agent kwargs, create_llm kwargs, agent, processor)."""
    from docsgpt.agents import agent_creator as ac_mod
    from docsgpt.api.answer.services import continuation_service as cont_mod
    from docsgpt.api.answer.services import stream_processor as sp_mod
    from docsgpt.llm import llm_creator as llm_creator_mod
    from docsgpt.llm.handlers import handler_creator as handler_mod

    def _run(state: dict, *, rows: dict | None = None):
        rows = rows or {}
        cont_service = MagicMock()
        cont_service.claim_state.return_value = copy.deepcopy(state)
        monkeypatch.setattr(cont_mod, "ContinuationService", lambda: cont_service)
        llm_kwargs: dict = {}
        monkeypatch.setattr(
            llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: llm_kwargs.update(kw) or MagicMock()
        )
        monkeypatch.setattr(handler_mod.LLMHandlerCreator, "create_handler", lambda *a, **kw: MagicMock())
        created: dict = {}
        agent = MagicMock()
        monkeypatch.setattr(ac_mod.AgentCreator, "create_agent", lambda *a, **kw: created.update(kw) or agent)
        processor = sp_mod.StreamProcessor({}, {"sub": OWNER})
        processor._get_attachments_content = MagicMock(
            side_effect=lambda ids, user: [rows[i] for i in ids if i in rows]
        )
        processor._fetch_attachment_rows = MagicMock(side_effect=lambda ids: [rows[i] for i in ids if i in rows])
        processor.resume_from_tool_actions(
            tool_actions=[{"call_id": "call_1", "result": "ok"}],
            conversation_id=str(uuid.uuid4()),
        )
        return created, llm_kwargs, agent, processor

    return _run


@pytest.mark.unit
class TestResumeRestoresTheFiles:
    LISTING = [
        {"ref": "F1", "id": "a-old", "filename": "letterhead.docx", "status": "earlier"},
        {"ref": "F2", "id": "a-cur", "filename": "contract.txt", "status": "reference"},
    ]

    def _saved(self):
        return _state(
            attachments={
                "current": ["a-cur"],
                "earlier": ["a-old"],
                "skipped": [{"filename": "huge.pdf", "reason": "too large"}],
                "mode": "reference",
                "planning": True,
                "listing": self.LISTING,
            }
        )

    def test_the_paused_turns_files_reach_the_resumed_agent(self, resume):
        cur, old = _att("contract.txt", att_id="a-cur"), _att("letterhead.docx", att_id="a-old")
        kwargs, _, agent, processor = resume(self._saved(), rows={"a-cur": cur, "a-old": old})

        assert kwargs["attachments"] == [cur]
        assert kwargs["earlier_attachments"] == [old]
        assert kwargs["attachments_mode"] == "reference"
        assert kwargs["attachment_planning"] is True
        assert kwargs["skipped_attachments"] == [{"filename": "huge.pdf", "reason": "too large"}]
        processor._get_attachments_content.assert_called_once_with(["a-cur"], OWNER)
        processor._fetch_attachment_rows.assert_called_once_with(["a-old"])
        agent.resume_paused_attachments.assert_called_once_with(self.LISTING)

    def test_a_state_saved_before_files_were_kept_resumes_without_them(self, resume):
        kwargs, llm_kwargs, agent, processor = resume(_state())

        assert "attachments" not in kwargs
        assert "earlier_attachments" not in kwargs
        assert "last_compression_at" not in kwargs
        assert not llm_kwargs.get("backup_models")
        processor._get_attachments_content.assert_not_called()
        agent.resume_paused_attachments.assert_not_called()

    def test_the_compression_point_and_backup_models_come_back(self, resume):
        state = _state(last_compression_at="2026-10-01 10:00:00+00:00", backup_models=["gpt-backup"])

        kwargs, llm_kwargs, _, _ = resume(state)

        assert kwargs["last_compression_at"] == "2026-10-01 10:00:00+00:00"
        assert llm_kwargs["backup_models"] == ["gpt-backup"]

    def test_a_failed_read_resumes_without_the_files(self, resume, monkeypatch):
        from docsgpt.api.answer.services import stream_processor as sp_mod

        original = sp_mod.StreamProcessor._resumed_attachment_kwargs

        def _boom(self, saved):
            self._fetch_attachment_rows = MagicMock(side_effect=RuntimeError("db down"))
            return original(self, saved)

        monkeypatch.setattr(sp_mod.StreamProcessor, "_resumed_attachment_kwargs", _boom)
        kwargs, _, agent, _ = resume(self._saved(), rows={"a-cur": _att("contract.txt", att_id="a-cur")})

        assert kwargs["attachments"] == []
        assert kwargs["earlier_attachments"] == []
        agent.resume_paused_attachments.assert_called_once_with(None)

    def test_a_file_deleted_before_the_resume_restores_none_rather_than_shift_the_refs(self, resume):
        """F refs are positions: without F1 the current file would answer to F1."""
        kwargs, _, agent, _ = resume(self._saved(), rows={"a-cur": _att("contract.txt", att_id="a-cur")})

        assert kwargs["attachments"] == []
        assert kwargs["earlier_attachments"] == []
        assert kwargs["attachments_mode"] == "reference"
        agent.resume_paused_attachments.assert_called_once_with(None)


@pytest.mark.unit
class TestResumedAgentUsesTheFiles:
    def _resumed(self):
        agent = _agent(
            attachments=[_att("contract.txt", att_id="a-cur")],
            earlier_attachments=[_att("letterhead.docx", att_id="a-old")],
            attachments_mode="reference",
        )
        agent.resume_paused_attachments([{"ref": "F1", "id": "a-old", "status": "earlier"}])
        return agent

    def test_the_handler_does_not_merge_the_files_into_the_saved_messages_again(self):
        from docsgpt.llm.handlers.openai import OpenAILLMHandler

        agent = self._resumed()
        agent.llm.get_supported_attachment_types = Mock(return_value=["text/plain"])
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "q [files listed]"}]
        before = copy.deepcopy(messages)

        assert OpenAILLMHandler().prepare_messages(agent, messages, agent.attachments) == before

    def test_an_unresumed_unplanned_agent_still_gets_its_files(self):
        from docsgpt.llm.handlers.openai import OpenAILLMHandler

        agent = _agent(attachments=[_att("contract.txt")], attachment_planning=False)
        agent.llm.get_supported_attachment_types = Mock(return_value=[])
        messages = [{"role": "user", "content": "q"}]

        prepared = OpenAILLMHandler().prepare_messages(agent, messages, agent.attachments)

        assert BODY in json.dumps(prepared)

    def test_the_tools_see_the_conversations_files_in_ref_order(self):
        agent = self._resumed()
        seen = {}
        agent.tool_executor.execute = lambda *a, **kw: seen.update(rows=list(agent.tool_executor.attachments))

        agent._execute_tool_action({}, Mock())

        assert [row["id"] for row in seen["rows"]] == ["a-old", "a-cur"]

    def test_the_response_lists_the_paused_turns_refs(self):
        from docsgpt.api.answer.routes.base import _attachment_listing

        assert _attachment_listing(self._resumed()) == [{"ref": "F1", "id": "a-old", "status": "earlier"}]


# ---------------------------------------------------------------------------
# End to end against Postgres: pause, save, claim, resume, resolve ``F`` refs
# ---------------------------------------------------------------------------


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.answer.services.continuation_service.db_readonly", _yield), patch(
        "docsgpt.api.answer.services.continuation_service.db_session", _yield,
    ), patch("docsgpt.api.answer.services.stream_processor.db_readonly", _yield), patch(
        "docsgpt.agents.tools.attachment_bridge.db_readonly", _yield,
    ):
        yield


@pytest.mark.integration
class TestPauseAndResumeKeepTheFiles:
    def test_run_code_refs_resolve_after_a_client_tool_pause(self, pg_conn, monkeypatch):
        from docsgpt.agents.tools.attachment_bridge import match_attachment
        from docsgpt.api.answer.services import stream_processor as sp_mod
        from docsgpt.api.answer.services.continuation_service import ContinuationService
        from docsgpt.llm import llm_creator as llm_creator_mod
        from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
        from docsgpt.storage.db.repositories.conversations import ConversationsRepository

        repo = AttachmentsRepository(pg_conn)
        old = repo.create(
            OWNER, "letterhead.docx", "/uploads/letterhead.docx", mime_type="application/octet-stream",
            size=900, content="header", token_count=2, metadata={"extraction": {"status": "ok"}},
        )
        cur = repo.create(
            OWNER, "contract.txt", "/uploads/contract.txt", mime_type="text/plain", size=120,
            content=BODY, token_count=num_tokens_from_string(BODY), metadata={"extraction": {"status": "ok"}},
        )
        paused = _planned(attachments=[cur], earlier_attachments=[old], attachments_mode="reference")
        conv_id = str(ConversationsRepository(pg_conn).create(OWNER, "paused")["id"])
        llm = MagicMock()
        llm.capabilities = None
        monkeypatch.setattr(llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: llm)

        with _patch_db(pg_conn):
            ContinuationService().save_state(
                conv_id, OWNER,
                messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}],
                pending_tool_calls=[
                    {"call_id": "call_1", "name": "search", "tool_name": "search", "llm_name": "search",
                     "arguments": {"query": "cap"}},
                ],
                tools_dict={}, tool_schemas=[],
                agent_config={
                    "model_id": "gpt-test", "llm_name": "openai", "api_key": "k", "user_api_key": None,
                    "agent_type": "ClassicAgent", "agent_id": None, "prompt": "sys",
                    **paused.paused_turn_state(),
                },
            )
            processor = sp_mod.StreamProcessor({}, {"sub": OWNER})
            agent, *_ = processor.resume_from_tool_actions(
                tool_actions=[{"call_id": "call_1", "result": "hits"}], conversation_id=conv_id,
            )
            seen = {}
            agent.tool_executor.execute = lambda *a, **kw: seen.update(rows=list(agent.tool_executor.attachments))
            agent._execute_tool_action({}, Mock())

            assert agent.reference_attachments is True
            assert match_attachment(seen["rows"], "F1", OWNER)["id"] == old["id"]
            assert match_attachment(seen["rows"], "F2", OWNER)["id"] == cur["id"]
            assert match_attachment(seen["rows"], "contract.txt", OWNER)["id"] == cur["id"]
            assert agent.paused_turn_state()["attachments"]["listing"] == paused.paused_turn_state()[
                "attachments"
            ]["listing"]


# ---------------------------------------------------------------------------
# The route saves it
# ---------------------------------------------------------------------------


@contextmanager
def _patch_route_db(conn):
    """Route the stream's own connections to the test transaction."""

    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.answer.services.conversation_service.db_session", _yield), patch(
        "docsgpt.api.answer.services.conversation_service.db_readonly", _yield,
    ), patch("docsgpt.streaming.message_journal.db_session", _yield), patch(
        "docsgpt.api.answer.routes.base.db_readonly", _yield,
    ), patch("docsgpt.api.answer.routes.base.db_session", _yield):
        yield


@pytest.mark.integration
class TestTheRouteSavesTheTurnState:
    def test_the_pause_saves_the_agents_turn_state(self, pg_conn, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        turn_state = {
            "attachments": {"current": ["a-cur"], "earlier": [], "skipped": [], "mode": "reference",
                            "planning": True, "listing": []},
            "last_compression_at": None,
            "backup_models": ["gpt-backup"],
        }
        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [{"type": "tool_calls_pending", "data": {"pending_tool_calls": [{"call_id": "c1"}]}}]
            )
            mock_agent._pending_continuation = {"messages": [], "tools_dict": {}, "pending_tool_calls": [{"call_id": "c1"}]}
            mock_agent.tool_calls = []
            mock_agent.compression_metadata = None
            mock_agent.compression_saved = False
            mock_agent.paused_turn_state.return_value = turn_state

            with _patch_route_db(pg_conn), patch(
                "docsgpt.api.answer.services.continuation_service.ContinuationService.save_state",
            ) as save_state:
                list(
                    resource.complete_stream(
                        question="run my tool",
                        agent=mock_agent,
                        conversation_id=None,
                        user_api_key=None,
                        decoded_token={"sub": "u-tap"},
                        should_persist=True,
                        model_id="gpt-4",
                    )
                )

            saved = save_state.call_args.kwargs["agent_config"]
            assert saved["attachments"] == turn_state["attachments"]
            assert saved["backup_models"] == ["gpt-backup"]
            assert "last_compression_at" not in saved

    def test_an_agent_without_turn_state_saves_none(self):
        from docsgpt.api.answer.routes.base import _paused_turn_state

        assert _paused_turn_state(MagicMock()) == {}
        assert _paused_turn_state(object()) == {}


@pytest.mark.unit
def test_an_agent_whose_turn_state_fails_pauses_without_it():
    from docsgpt.api.answer.routes.base import _paused_turn_state

    agent = MagicMock()
    agent.paused_turn_state.side_effect = RuntimeError("boom")
    assert _paused_turn_state(agent) == {}
