"""Team workspaces fail closed: one focused test per way they could fail open.

A team's items are owned by its principal (a ``users`` row of kind ``team``), so
every owner check that forgets about teams denies rather than grants. These
tests pin the checks that stand between a caller and a team's items or money,
each through the public route where one exists. Every test fails if the check
it names is removed. Other files test the same rules in depth; this file is the
one place that lists them all.

Risks covered:

* a forged identity that names a team principal (Flask and ASGI);
* a workspace header naming a team the caller isn't in, on a list and a create;
* a leftover per-item grant on a team's item, read by a non-member;
* a team principal billed for a run;
* someone who left a team still reading its chats or Activity;
* a move that re-owns what the mover doesn't own, or applies half-way;
* tool credentials that no longer decrypt after a move;
* a move that leaves a published personal agent using a team's item.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask, request
from sqlalchemy import text
from starlette.requests import Request

from docsgpt.security.encryption import (
    CredentialDecryptionError,
    decrypt_json,
    encrypt_credentials,
    encrypt_json,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id
from tests.workspaces.move_support import agent, body, grant, other_team, owner_of, prompt, source, team, tool

# Every module whose connection the routes below open.
_DB_TARGETS = (
    "docsgpt.workspaces.context.db_readonly",
    "docsgpt.api.user.prompts.routes.db_readonly",
    "docsgpt.api.user.prompts.routes.db_session",
    "docsgpt.api.user.agents.routes.db_readonly",
    "docsgpt.api.user.agents.routes.db_session",
    "docsgpt.api.user.conversations.routes.db_readonly",
    "docsgpt.api.user.conversations.routes.db_session",
    "docsgpt.api.user.activity.routes.db_readonly",
    "docsgpt.api.user.workspaces.routes.db_readonly",
    "docsgpt.api.user.workspaces.routes.db_session",
    "docsgpt.usage.db_session",
)


@pytest.fixture
def db(pg_conn, monkeypatch):
    @contextmanager
    def _yield():
        yield pg_conn

    for target in _DB_TARGETS:
        monkeypatch.setattr(target, _yield)
    return pg_conn


def _call(resource_cls, user, *, method="get", path="/api/x", workspace=None, json_body=None, query=None):
    """Call a route as ``user`` (a signed-in session), naming ``workspace`` in the header when given."""
    headers = {WORKSPACE_HEADER: workspace} if workspace is not None else {}
    kwargs = {"method": method.upper(), "headers": headers, "query_string": query or {}}
    if json_body is not None:
        kwargs["json"] = json_body
    with Flask(__name__).test_request_context(path, **kwargs):
        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method)()


# ---------------------------------------------------------------------------
# Nobody signs in as a team principal
# ---------------------------------------------------------------------------


class TestForgedPrincipal:
    FORGED = principal_id(uuid.uuid4())

    def test_flask_refuses_claims_that_name_a_principal(self):
        from docsgpt.app import app

        app.config["TESTING"] = True
        # The decoder is bypassed: the request hook itself must refuse the principal.
        with patch("docsgpt.app.handle_auth", return_value={"sub": self.FORGED}):
            refused = app.test_client().get("/api/health")
        with patch("docsgpt.app.handle_auth", return_value={"sub": "alice"}):
            allowed = app.test_client().get("/api/health")
        assert refused.status_code == 401
        assert refused.get_json()["error"] == "invalid_token"
        assert allowed.status_code == 200

    @pytest.mark.asyncio
    async def test_asgi_refuses_claims_that_name_a_principal(self):
        from docsgpt.api import asgi_auth

        scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"authorization", b"Bearer x")],
                 "query_string": b""}
        with patch.object(asgi_auth, "handle_auth", return_value={"sub": self.FORGED}):
            decoded, error = await asgi_auth.authenticate(Request(scope))
        assert decoded is None
        assert error.status_code == 401
        assert json.loads(error.body)["error"] == "invalid_token"


# ---------------------------------------------------------------------------
# The workspace header is a request, not a credential
# ---------------------------------------------------------------------------


class TestHeaderWithoutMembership:
    def test_a_list_of_a_team_the_caller_isnt_in_is_404(self, db):
        from docsgpt.api.user.prompts.routes import GetPrompts

        tid, principal = team(db)
        prompt(db, principal, "Team only")
        response = _call(GetPrompts, "olga", path="/api/get_prompts", workspace=tid)
        assert response.status_code == 404
        assert response.get_json()["error"] == "workspace_not_found"

    def test_a_create_into_a_team_the_caller_isnt_in_writes_nothing(self, db):
        from docsgpt.api.user.prompts.routes import CreatePrompt

        tid, principal = team(db)
        response = _call(CreatePrompt, "olga", method="post", path="/api/create_prompt", workspace=tid,
                         json_body={"name": "Planted", "content": "x"})
        assert response.status_code == 404
        assert response.get_json()["error"] == "workspace_not_found"
        assert PromptsRepository(db).list_for_user(principal) == []
        assert PromptsRepository(db).list_for_user("olga") == []


# ---------------------------------------------------------------------------
# A team's item is reached by team role only
# ---------------------------------------------------------------------------


class TestStaleGrant:
    """Two layers each refuse a grant row on a team's item: the grant lookups, and ``resolve`` itself."""

    def _forced_grant(self, conn) -> str:
        _tid, principal = team(conn)
        other = other_team(conn)
        aid = agent(conn, principal)
        # A row the CHECK would refuse today: forced, as a stale row from before it would be.
        conn.execute(text("ALTER TABLE team_resource_grants DROP CONSTRAINT team_resource_grants_personal_owner_chk"))
        grant(conn, other, "agent", aid, principal, level="editor")
        TeamMembersRepository(conn).add_member(other, "nora", role="team_editor")
        return aid

    def test_grant_lookups_skip_a_team_item(self, db):
        from docsgpt.storage.db.repositories.team_scope import TeamScopeRepository

        aid = self._forced_grant(db)
        scope = TeamScopeRepository(db)
        assert scope.effective_access("nora", "agent", aid) is None
        assert aid not in scope.visible_with_access("nora", "agent")

    def test_resolve_answers_a_team_item_from_the_team_role_only(self, db):
        from docsgpt.api.user.agents.routes import GetAgent
        from docsgpt.api.user.resource_access import resolve
        from docsgpt.storage.db.repositories.team_scope import TeamScopeRepository

        aid = self._forced_grant(db)
        # Even if a grant lookup let the row through, the team item answers from the team role alone.
        with patch.object(TeamScopeRepository, "effective_access", return_value="editor"):
            assert resolve(db, "agent", aid, "nora") is None
            response = _call(GetAgent, "nora", path="/api/get_agent", query={"id": aid})
        status = response[1] if isinstance(response, tuple) else response.status_code
        assert status == 404


# ---------------------------------------------------------------------------
# A team principal never pays
# ---------------------------------------------------------------------------


class TestPrincipalNeverPays:
    def test_the_quota_check_refuses_a_principal_before_any_lookup(self, monkeypatch):
        from docsgpt.quotas.service import NoPayerError, QuotaService

        reads = []
        monkeypatch.setattr(QuotaService, "status", staticmethod(lambda *a, **k: reads.append(a) or []))
        with pytest.raises(NoPayerError):
            QuotaService.check(principal_id(uuid.uuid4()), "agent")
        assert reads == []

    def test_a_usage_row_never_names_a_principal(self, db, caplog):
        from docsgpt.usage import gen_token_usage

        _tid, principal = team(db)
        aid = agent(db, principal, key="team-key", status="published")

        class _LLM:
            decoded_token = {"sub": principal}
            user_api_key = "team-key"
            agent_id = aid
            token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

        @gen_token_usage
        def _model_call(self, model, messages, stream, tools, **kwargs):
            return "an answer"

        with caplog.at_level(logging.ERROR, logger="docsgpt.usage"):
            _model_call(_LLM(), "m", [{"role": "user", "content": "hi"}], False, None)
        payers = db.execute(
            text("SELECT user_id FROM token_usage WHERE agent_id = CAST(:a AS uuid)"), {"a": aid}
        ).scalars().all()
        assert payers == [None]


# ---------------------------------------------------------------------------
# Someone who left a team loses its chats and Activity
# ---------------------------------------------------------------------------


class TestExMember:
    def _team_chat(self, conn, tid) -> str:
        repo = ConversationsRepository(conn)
        cid = str(repo.create("vera", "Ours", team_id=tid, visibility="listed")["id"])
        repo.append_message(cid, {"prompt": "about the plan", "response": "ok", "metadata": {}})
        return cid

    def test_team_chats_close_on_leaving(self, db):
        from docsgpt.api.user.conversations.routes import GetConversations, GetSingleConversation

        tid, _ = team(db)
        cid = self._team_chat(db, tid)
        assert _call(GetSingleConversation, "vera", query={"id": cid}).status_code == 200

        TeamMembersRepository(db).remove_member(tid, "vera")

        assert _call(GetSingleConversation, "vera", query={"id": cid}).status_code == 404
        assert _call(GetConversations, "vera", workspace=tid).status_code == 404
        assert _call(GetConversations, "vera").get_json() == []

    def test_activity_closes_on_leaving(self, db):
        from docsgpt.api.user.activity.routes import ActivityNow

        tid, _ = team(db)
        assert _call(ActivityNow, "vera", path="/api/activity/now", workspace=tid).status_code == 200
        TeamMembersRepository(db).remove_member(tid, "vera")
        response = _call(ActivityNow, "vera", path="/api/activity/now", workspace=tid)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Move
# ---------------------------------------------------------------------------


def _move(user, request_body):
    """Plan then apply through the routes; returns the apply response's ``(status, body)``."""
    from docsgpt.api.user.workspaces.routes import WorkspaceMovePlan, WorkspaceMoves

    planned = _call(WorkspaceMovePlan, user, method="post", path="/api/workspace_moves/plan", json_body=request_body)
    assert planned.status_code == 200, planned.get_json()
    fingerprint = planned.get_json()["plan"]["fingerprint"]
    applied = _call(WorkspaceMoves, user, method="post", path="/api/workspace_moves",
                    json_body={**request_body, "fingerprint": fingerprint})
    return applied.status_code, applied.get_json()


class TestMove:
    def test_an_item_the_mover_only_edits_is_never_reowned(self, db):
        tid, principal = team(db)
        other = other_team(db)
        theirs = prompt(db, "olga")
        mine = prompt(db, "eddie")
        grant(db, other, "prompt", theirs, "olga", level="editor")

        status, _ = _move("eddie", body(tid, [("prompt", theirs), ("prompt", mine)]))

        assert status == 200
        assert owner_of(db, "prompt", mine) == principal
        assert owner_of(db, "prompt", theirs) == "olga"

    def test_a_failure_part_way_changes_nothing(self, db):
        from docsgpt.workspaces.move import apply_move, parse_move_request
        from tests.workspaces.move_support import plan

        tid, _ = team(db)
        tl = tool(db, "eddie", "brave", config={"encrypted_credentials": encrypt_credentials({"k": "v"}, "eddie")})
        src = source(db, "eddie")
        ag = agent(db, "eddie", tools=[tl], source_id=src)
        request_body = body(tid, [("agent", ag)])
        fingerprint = plan(db, "eddie", request_body)["fingerprint"]

        with patch("docsgpt.security.encryption.reseal_for_owner", side_effect=CredentialDecryptionError("boom")):
            with pytest.raises(Exception):
                apply_move(db, "eddie", parse_move_request({**request_body, "fingerprint": fingerprint}))

        for kind, item in (("agent", ag), ("source", src), ("tool", tl)):
            assert owner_of(db, kind, item) == "eddie"

    def test_credentials_decrypt_for_the_team_after_a_move(self, db):
        tid, principal = team(db)
        v1 = tool(db, "eddie", "brave", config={"encrypted_credentials": encrypt_credentials({"k": "v1"}, "eddie")})
        v2 = tool(db, "eddie", "brave", config={"encrypted_credentials": encrypt_json({"k": "v2"}, "eddie")})

        status, _ = _move("eddie", body(tid, [("tool", v1), ("tool", v2)]))

        assert status == 200
        configs = {
            str(row["id"]): row["config"]
            for row in db.execute(
                text("SELECT id, config FROM user_tools WHERE id IN (CAST(:a AS uuid), CAST(:b AS uuid))"),
                {"a": v1, "b": v2},
            ).mappings()
        }
        assert decrypt_json(configs[v1]["encrypted_credentials"], principal) == {"k": "v1"}
        assert decrypt_json(configs[v2]["encrypted_credentials"], principal) == {"k": "v2"}
        with pytest.raises(CredentialDecryptionError):
            decrypt_json(configs[v2]["encrypted_credentials"], "eddie")

    def test_a_move_that_would_leave_a_published_agent_borrowing_is_refused(self, db):
        tid, _ = team(db)
        src = source(db, "eddie")
        moving = agent(db, "eddie", "Moving", source_id=src)
        staying = agent(db, "eddie", "Staying", source_id=src, key="key-st", status="published")

        status, out = _move("eddie", body(tid, [("agent", moving)]))

        assert (status, out["error"]) == (409, "move_would_borrow")
        assert [a["id"] for a in out["agents"]] == [staying]
        assert owner_of(db, "source", src) == "eddie"
        assert owner_of(db, "agent", moving) == "eddie"
        assert AgentsRepository(db).get_by_id(staying)["user_id"] == "eddie"
