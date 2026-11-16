"""A team agent's outside access pauses while the person who pays for it no longer holds the Admin role.

Whoever turned on a team agent's key, public link or webhook pays for the traffic that comes in through it
(``agents.access_payer_id``). When that person is demoted below Admin or leaves the team, every way in from
outside is refused as ``agent_paused`` (the caller is told nothing more), until they are given the role back or
someone takes over. A personal agent's owner always pays, so it never pauses for that reason. The payer's
allowance is not this gate's business: ``check_usage`` and the run's own checks enforce it.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.api.owner_pause import (
    PAUSED_CODE,
    PAUSED_MESSAGE,
    AgentPausedError,
    AgentPayerLeftError,
    outside_access_refusal,
)
from docsgpt.quotas.service import QuotaService
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import principal_id

# Every module that opens a connection on the gates these tests drive.
_DB_TARGETS = (
    "docsgpt.api.answer.services.stream_processor",
    "docsgpt.api.answer.services.conversation_service",
    "docsgpt.services.search_service",
    "docsgpt.api.user.base",
    "docsgpt.api.user.attachments.routes",
    "docsgpt.api.v1.routes",
    "docsgpt.worker",
)


@pytest.fixture
def db(pg_conn, monkeypatch):
    @contextmanager
    def _yield():
        yield pg_conn

    for module in _DB_TARGETS:
        for attr in ("db_readonly", "db_session"):
            monkeypatch.setattr(f"{module}.{attr}", _yield, raising=False)
    monkeypatch.setattr("docsgpt.mcp_server.origin_refusal", lambda *a, **k: None)

    # The gate never asks for anyone's allowance: that is check_usage's job, worded for outsiders.
    def _no_quota_here(*_a, **_k):
        raise AssertionError("the outside-access gate must not check an allowance")

    monkeypatch.setattr(QuotaService, "check", classmethod(_no_quota_here))
    return pg_conn


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "alice", role="team_admin")
    repo.add_member(tid, "adam", role="team_admin")
    repo.add_member(tid, "eddie", role="team_editor")
    return tid, principal_id(tid)


def _set_role(conn, team_id, user_id, role):
    conn.execute(
        text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"), {"t": team_id, "u": user_id}
    )
    if role:
        TeamMembersRepository(conn).add_member(team_id, user_id, role=role)


def _published(conn, owner, *, payer="adam"):
    """An agent with every way in switched on: a key, a public link and a webhook."""
    suffix = uuid.uuid4().hex[:8]
    source = SourcesRepository(conn).create("Docs", user_id=owner, created_by="alice")
    return AgentsRepository(conn).create(
        owner, "Desk", "published", key=f"k-{suffix}", shared=True, shared_token=f"tok-{suffix}",
        incoming_webhook_token=f"wh-{suffix}", access_payer_id=payer, created_by="alice",
        default_model_id="m", agent_type="classic", extra_source_ids=[str(source["id"])],
    )


def _fresh(conn, agent):
    return AgentsRepository(conn).get_by_id(str(agent["id"]))


# --- each gate, as an outside caller reaches it -------------------------------------------------------


def _key_chat(conn, agent):
    from docsgpt.api.answer.services.stream_processor import StreamProcessor

    StreamProcessor({"question": "q", "api_key": agent["key"]}, {"sub": "stranger"})._configure_agent()


def _link_chat(conn, agent):
    from docsgpt.api.answer.services.stream_processor import StreamProcessor

    data = {"question": "q", "agent_id": str(agent["id"]), "shared_token": agent["shared_token"]}
    StreamProcessor(data, {"sub": "stranger"})._configure_agent()


def _webhook_route(conn, agent):
    from docsgpt.api.user.base import require_agent

    @require_agent
    def _hook(webhook_token=None, agent=None, agent_id_str=None):
        return {"ran": agent_id_str}

    with Flask(__name__).app_context():
        result = _hook(webhook_token=agent["incoming_webhook_token"])
    if not isinstance(result, dict):
        assert result.status_code == 403
        raise AgentPausedError() if result.json["code"] == PAUSED_CODE else AssertionError(result.json)


def _webhook_task(conn, agent):
    from docsgpt import worker
    from docsgpt.agents import headless_runner

    ran = MagicMock(return_value={"answer": "ok"})
    with patch.object(headless_runner, "run_agent_headless", ran):
        result = worker.agent_webhook_worker(MagicMock(), str(agent["id"]), {"event": "ping"})
    if result["status"] != "success":
        assert result["status"] == PAUSED_CODE and not ran.called
        raise AgentPausedError()


def _v1(conn, agent):
    from docsgpt.api.v1.routes import v1_bp

    app = Flask(__name__)
    app.register_blueprint(v1_bp)
    # Past the gate the request is checked for options: stop there, so an open gate shows as 299.
    with patch("docsgpt.api.v1.routes._validate_request_options", return_value=("past the gate", 299)):
        with app.test_client() as client:
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
                headers={"Authorization": f"Bearer {agent['key']}"},
            )
    if response.status_code != 299:
        assert response.status_code == 403
        error = response.get_json()["error"]
        assert error["code"] == PAUSED_CODE and error["message"] == PAUSED_MESSAGE
        raise AgentPausedError()


def _search(conn, agent):
    from docsgpt.services import search_service

    with patch.object(search_service, "_search_sources", return_value=[]), patch.object(search_service, "tracing"):
        search_service.search(agent["key"], "hi")


def _mcp(conn, agent):
    from docsgpt.mcp_server import search_docs
    from docsgpt.services import search_service

    headers = {"authorization": f"Bearer {agent['key']}"}
    with patch("docsgpt.mcp_server.get_http_headers", return_value=headers), patch.object(
        search_service, "_search_sources", return_value=[]
    ), patch.object(search_service, "tracing"):
        try:
            asyncio.run(search_docs(query="hi"))
        except PermissionError as exc:
            assert str(exc) == PAUSED_MESSAGE
            raise AgentPausedError() from exc


def _attachment_key(conn, agent):
    from docsgpt.api.user.attachments.routes import _resolve_authenticated_user

    with Flask(__name__).test_request_context(f"/api/store_attachment?api_key={agent['key']}", method="POST"):
        from flask import request

        request.decoded_token = None
        result = _resolve_authenticated_user()
    if not isinstance(result, str):
        assert result.status_code == 403 and result.get_json()["code"] == PAUSED_CODE
        raise AgentPausedError()


GATES = {
    "key": _key_chat,
    "link": _link_chat,
    "webhook_route": _webhook_route,
    "webhook_task": _webhook_task,
    "v1": _v1,
    "search": _search,
    "mcp": _mcp,
    "attachment_key": _attachment_key,
}


class TestTheGate:
    def test_the_payer_still_an_admin_answers(self, db):
        _, principal = _team(db)
        assert outside_access_refusal(db, _published(db, principal)) is None

    @pytest.mark.parametrize("role", ["team_editor", "team_viewer", None])
    def test_the_payer_below_admin_or_gone_is_refused_payer_left(self, db, role):
        tid, principal = _team(db)
        agent = _published(db, principal)
        _set_role(db, tid, "adam", role)

        refusal = outside_access_refusal(db, agent)

        assert isinstance(refusal, AgentPayerLeftError) and isinstance(refusal, AgentPausedError)
        assert refusal.code == PAUSED_CODE and refusal.message == PAUSED_MESSAGE
        assert refusal.reason == "payer_left"

    def test_re_promoted_it_answers_again_with_nothing_written(self, db):
        tid, principal = _team(db)
        agent = _published(db, principal)
        _set_role(db, tid, "adam", None)
        assert outside_access_refusal(db, agent) is not None

        _set_role(db, tid, "adam", "team_admin")

        assert outside_access_refusal(db, _fresh(db, agent)) is None
        assert _fresh(db, agent)["access_payer_id"] == "adam"

    def test_the_team_owner_as_payer_answers(self, db):
        _, principal = _team(db)
        assert outside_access_refusal(db, _published(db, principal, payer="alice")) is None

    def test_a_link_already_turned_off_still_pauses_a_caller_that_got_through(self, db):
        """A queued webhook or a paused turn resumed later may reach the gate after its way in closed."""
        tid, principal = _team(db)
        agent = _published(db, principal)
        AgentsRepository(db).update(
            str(agent["id"]), principal, {"key": None, "shared": False, "shared_token": None,
                                          "incoming_webhook_token": None},
        )
        _set_role(db, tid, "adam", "team_editor")

        assert isinstance(outside_access_refusal(db, _fresh(db, agent)), AgentPayerLeftError)

    def test_no_payer_and_a_deactivated_payer_keep_their_answers(self, db):
        _, principal = _team(db)
        assert outside_access_refusal(db, _published(db, principal, payer=None)).code == "no_payer"
        agent = _published(db, principal)
        UsersRepository(db).upsert("adam")
        db.execute(text("UPDATE users SET active = false WHERE user_id = 'adam'"))
        refusal = outside_access_refusal(db, agent)
        assert refusal.code == PAUSED_CODE and not isinstance(refusal, AgentPayerLeftError)


class TestEveryWayIn:
    @pytest.mark.parametrize("gate", list(GATES))
    def test_refused_while_the_payer_is_an_editor_and_answers_once_promoted(self, db, gate):
        tid, principal = _team(db)
        agent = _published(db, principal)
        _set_role(db, tid, "adam", "team_editor")

        with pytest.raises(AgentPausedError):
            GATES[gate](db, agent)

        _set_role(db, tid, "adam", "team_admin")
        GATES[gate](db, _fresh(db, agent))

    @pytest.mark.parametrize("gate", list(GATES))
    def test_refused_once_the_payer_left_the_team(self, db, gate):
        tid, principal = _team(db)
        agent = _published(db, principal)
        _set_role(db, tid, "adam", None)

        with pytest.raises(AgentPausedError):
            GATES[gate](db, agent)


class TestPersonalAgents:
    def test_a_personal_agent_never_pauses_for_a_payer_who_left(self, db):
        from docsgpt.quotas.pause import outside_access_pause

        tid, _ = _team(db)
        agent = _published(db, "eddie", payer=None)
        _set_role(db, tid, "eddie", None)

        assert outside_access_refusal(db, agent) is None
        with patch.object(QuotaService, "check", classmethod(lambda cls, *a, **k: None)):
            assert outside_access_pause(db, agent) is None

    @pytest.mark.parametrize("gate", ["key", "v1", "search"])
    def test_its_key_answers_whatever_its_owner_does_in_a_team(self, db, gate):
        tid, _ = _team(db)
        agent = _published(db, "adam", payer=None)
        _set_role(db, tid, "adam", "team_viewer")

        GATES[gate](db, agent)
