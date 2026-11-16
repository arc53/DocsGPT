"""``GET /api/teams/<team_id>/chats/export``: every chat of a team workspace as one NDJSON file.

Driven through the real app.py chokepoint against real Postgres; only ``handle_auth`` / ``resolve_roles`` are
patched, and the modules' sessions are pointed at the per-test ``pg_conn``.
"""

from __future__ import annotations

import json
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.api.pat.tokens import expand_scopes
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import principal_id


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def db(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    with ExitStack() as stack:
        for target in (
            "docsgpt.api.user.teams.routes.db_readonly",
            "docsgpt.api.user.teams.routes.db_session",
            "docsgpt.api.user.teams.chat_export.db_readonly",
            "docsgpt.api.user.teams.chat_export.db_session",
            "docsgpt.api.user.team_authz.db_readonly",
        ):
            stack.enter_context(patch(target, _yield))
        yield pg_conn


@pytest.fixture
def export_on():
    with patch("docsgpt.api.user.teams.chat_export.settings.TEAM_CHAT_EXPORT_ENABLED", True):
        yield


@contextmanager
def _as(sub):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=["user"]
    ):
        yield


def _team(conn, name="Ops", owner="alice", members=(("adam", "team_admin"), ("eddie", "team_editor"),
                                                    ("vera", "team_viewer"))):
    users = UsersRepository(conn)
    for user in (owner, *(u for u, _ in members)):
        users.upsert(user, email=f"{user}@x.io")
    team = TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid


def _chat(conn, user, team_id, name, *, agent_id=None, messages=None, attachments=()):
    conv = str(conn.execute(
        text(
            "INSERT INTO conversations (user_id, name, team_id, agent_id) "
            "VALUES (:u, :n, CAST(:t AS uuid), CAST(:a AS uuid)) RETURNING id"
        ),
        {"u": user, "n": name, "t": team_id, "a": agent_id},
    ).scalar())
    attachment_ids = []
    for filename in attachments:
        attachment_ids.append(str(conn.execute(
            text(
                "INSERT INTO attachments (user_id, filename, upload_path, content) "
                "VALUES (:u, :f, '/x', 'SECRET-ATTACHMENT-BODY') RETURNING id"
            ),
            {"u": user, "f": filename},
        ).scalar()))
    for position, (prompt, response) in enumerate(messages or [("Hi", "Hello")]):
        conn.execute(
            text(
                "INSERT INTO conversation_messages (conversation_id, user_id, position, prompt, response, thought, "
                "sources, tool_calls, attachments, model_id, feedback) VALUES (CAST(:c AS uuid), :u, :p, :q, :r, "
                "'SECRET-REASONING', CAST(:s AS jsonb), CAST(:tc AS jsonb), CAST(:att AS uuid[]), 'gpt-x', "
                "CAST(:fb AS jsonb))"
            ),
            {
                "c": conv, "u": user, "p": position, "q": prompt, "r": response,
                "s": json.dumps([{"title": "Rate card", "text": "SECRET-CHUNK-TEXT"}]),
                "tc": json.dumps([{"tool_name": "api", "action_name": "lookup", "call_id": "1",
                                   "arguments": {"q": "SECRET-ARGS"}, "result": "SECRET-RESULT"}]),
                "att": attachment_ids if position == 0 else [],
                "fb": json.dumps({"text": "like"}) if position == 0 else None,
            },
        )
    return conv


def _export(client, tid, user="alice"):
    with _as(user):
        return client.get(f"/api/teams/{tid}/chats/export")


def _lines(resp):
    return [json.loads(line) for line in resp.data.decode().splitlines() if line.strip()]


def _audits(conn):
    return conn.execute(
        text("SELECT actor_id, metadata FROM auth_events WHERE event = 'team.chats_exported' ORDER BY id")
    ).fetchall()


class TestSetting:
    def test_off_is_404(self, client, db):
        tid = _team(db)
        with patch("docsgpt.api.user.teams.chat_export.settings.TEAM_CHAT_EXPORT_ENABLED", False):
            resp = _export(client, tid)
        assert resp.status_code == 404
        assert _audits(db) == []


class TestWho:
    @pytest.mark.parametrize("user", ["alice", "adam"])
    def test_owner_and_admins(self, client, db, export_on, user):
        tid = _team(db)
        assert _export(client, tid, user).status_code == 200

    @pytest.mark.parametrize("user", ["eddie", "vera"])
    def test_below_admin_is_403(self, client, db, export_on, user):
        tid = _team(db)
        resp = _export(client, tid, user)
        assert resp.status_code == 403
        assert json.loads(resp.data)["error"] == "workspace_role_required"
        assert _audits(db) == []

    def test_a_non_member_is_404(self, client, db, export_on):
        tid = _team(db)
        assert _export(client, tid, "olga").status_code == 404

    def test_an_instance_admin_outside_the_team_is_404(self, client, db, export_on):
        tid = _team(db)
        _chat(db, "eddie", tid, "Team chat")
        with patch("docsgpt.app.handle_auth", return_value={"sub": "root"}), patch(
            "docsgpt.app.resolve_roles", return_value=["admin", "user"]
        ):
            assert client.get(f"/api/teams/{tid}/chats/export").status_code == 404

    def test_a_token_is_refused(self, client, db, export_on):
        tid = _team(db)
        claims = {"sub": "alice", "auth_method": "pat", "pat_id": "t1", "pat_name": "ci",
                  "scopes": sorted(expand_scopes(["teams:read", "conversations:read"])), "resource_filter": {}}
        with patch("docsgpt.app.handle_auth", return_value=claims):
            resp = client.get(f"/api/teams/{tid}/chats/export")
        assert resp.status_code == 403
        assert json.loads(resp.data)["error"] == "not_available_to_tokens"


class TestFile:
    def test_header_then_one_line_per_team_chat(self, client, db, export_on):
        tid = _team(db)
        agent = str(AgentsRepository(db).create(principal_id(tid), "Carrier desk", "published")["id"])
        first = _chat(db, "eddie", tid, "Rates", agent_id=agent, messages=[("Q1", "A1"), ("Q2", "A2")],
                      attachments=["quote.pdf"])
        second = _chat(db, "vera", tid, "Plain")
        resp = _export(client, tid)
        assert resp.status_code == 200
        assert resp.mimetype == "application/x-ndjson"
        slug = TeamsRepository(db).get(tid)["slug"]
        assert resp.headers["Content-Disposition"] == (
            f'attachment; filename="docsgpt-{slug}-chats-{datetime.now(timezone.utc).date().isoformat()}.ndjson"'
        )
        header, *rows = _lines(resp)
        assert header["type"] == "export"
        assert header["team"] == {"id": tid, "name": "Ops"}
        assert header["exported_by"] == "alice" and header["conversations"] == 2
        assert header["exported_at"]
        by_id = {row["id"]: row for row in rows}
        assert set(by_id) == {first, second}
        row = by_id[first]
        assert row["type"] == "conversation" and row["name"] == "Rates"
        assert row["user"] == {"user_id": "eddie", "label": "eddie@x.io", "member": True}
        assert row["agent"] == {"id": agent, "name": "Carrier desk"}
        assert row["via"] == "app"
        assert row["created_at"] and row["updated_at"]
        assert [m["prompt"] for m in row["messages"]] == ["Q1", "Q2"]
        message = row["messages"][0]
        assert message["response"] == "A1" and message["model_id"] == "gpt-x"
        assert message["sources"] == ["Rate card"]
        assert message["tool_calls"] == ["lookup"]
        assert message["attachments"] == ["quote.pdf"]
        assert message["feedback"] == {"text": "like"}
        assert message["created_at"]
        assert by_id[second]["agent"] is None

    def test_reasoning_tool_results_and_contents_are_absent(self, client, db, export_on):
        tid = _team(db)
        _chat(db, "eddie", tid, "Rates", attachments=["quote.pdf"])
        raw = _export(client, tid).data.decode()
        for secret in ("SECRET-REASONING", "SECRET-ARGS", "SECRET-RESULT", "SECRET-CHUNK-TEXT",
                       "SECRET-ATTACHMENT-BODY"):
            assert secret not in raw

    def test_no_personal_chat_and_no_other_teams_chat_even_for_the_same_person(self, client, db, export_on):
        tid = _team(db)
        other = _team(db, name="Elsewhere", owner="olga", members=(("eddie", "team_admin"), ("alice", "team_admin")))
        team_chat = _chat(db, "eddie", tid, "Team chat")
        _chat(db, "eddie", None, "PERSONAL-CHAT-OF-EDDIE")
        _chat(db, "eddie", other, "OTHER-TEAM-CHAT-OF-EDDIE")
        _chat(db, "alice", None, "PERSONAL-CHAT-OF-ALICE")
        resp = _export(client, tid)
        raw = resp.data.decode()
        assert "PERSONAL-CHAT" not in raw and "OTHER-TEAM-CHAT" not in raw
        header, *rows = _lines(resp)
        assert [row["id"] for row in rows] == [team_chat]
        assert header["conversations"] == 1

    def test_a_departed_members_chat_is_included(self, client, db, export_on):
        tid = _team(db)
        conv = _chat(db, "vera", tid, "Before leaving")
        TeamMembersRepository(db).change_membership(tid, "vera", None, actor="alice")
        _, row = _lines(_export(client, tid))
        assert row["id"] == conv
        assert row["user"] == {"user_id": "vera", "label": "vera@x.io", "member": False}

    def test_the_principals_chats_are_outside_traffic(self, client, db, export_on):
        tid = _team(db)
        conv = _chat(db, principal_id(tid), tid, "Widget visitor")
        _, row = _lines(_export(client, tid))
        assert row["id"] == conv and row["via"] == "outside"
        assert row["user"]["member"] is False

    def test_an_empty_team_exports_just_the_header(self, client, db, export_on):
        tid = _team(db)
        (header,) = _lines(_export(client, tid))
        assert header["conversations"] == 0

    def test_pages_through_many_chats(self, client, db, export_on):
        tid = _team(db)
        ids = {_chat(db, "eddie", tid, f"Chat {n}") for n in range(7)}
        with patch("docsgpt.api.user.teams.chat_export.PAGE_SIZE", 3):
            _, *rows = _lines(_export(client, tid))
        assert [row["id"] for row in rows if row["id"] in ids] and {row["id"] for row in rows} == ids
        assert len(rows) == 7


class TestAudit:
    def test_records_counts(self, client, db, export_on):
        tid = _team(db)
        _chat(db, "eddie", tid, "One")
        _chat(db, "eddie", tid, "Two")
        _chat(db, "vera", tid, "Three")
        _chat(db, principal_id(tid), tid, "Widget")
        _export(client, tid, "adam")
        ((actor, metadata),) = _audits(db)
        assert actor == "adam"
        assert metadata == {"team_id": tid, "conversations": 4, "people": 2}

    def test_no_audit_row_no_file(self, client, db, export_on):
        tid = _team(db)
        _chat(db, "eddie", tid, "Secret plans")

        with patch("docsgpt.api.audit.AuthEventsRepository.insert", side_effect=RuntimeError("audit down")):
            resp = _export(client, tid)

        assert resp.status_code == 503
        assert b"Secret plans" not in resp.data
        assert json.loads(resp.data)["error"] == "audit_unavailable"
        assert _audits(db) == []
