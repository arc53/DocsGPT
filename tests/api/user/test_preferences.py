"""GET/PUT /api/user/preferences: the chat prompt, stored on the server."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository

ALICE = "alice"
BOB = "bob"


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.me.routes.db_session", _yield), patch(
        "docsgpt.api.user.me.routes.db_readonly", _yield
    ):
        yield


def _call(app, conn, method, user=ALICE, json=None):
    from docsgpt.api.user.me.routes import PreferencesResource

    with _patch_db(conn), app.test_request_context("/api/user/preferences", method=method.upper(), json=json):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        return getattr(PreferencesResource(), method)()


def _chat_prompt(app, conn, user=ALICE):
    resp = _call(app, conn, "get", user)
    assert resp.status_code == 200
    return resp.json["chat_prompt_id"]


def _share_prompt(conn, prompt_id, owner, member):
    team = TeamsRepository(conn).create("Acme", f"t-{uuid.uuid4().hex[:8]}", owner)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), "prompt", str(prompt_id), owner, owner, access_level="viewer"
    )
    return team


class TestPreferences:
    def test_unauthenticated_is_401(self, app, pg_conn):
        assert _call(app, pg_conn, "get", user=None).status_code == 401
        assert _call(app, pg_conn, "put", user=None, json={"chat_prompt_id": "default"}).status_code == 401

    def test_defaults_to_the_default_preset(self, app, pg_conn):
        assert _chat_prompt(app, pg_conn) == "default"

    @pytest.mark.parametrize("preset", ["default", "creative", "strict"])
    def test_presets_round_trip(self, app, pg_conn, preset):
        resp = _call(app, pg_conn, "put", json={"chat_prompt_id": preset})
        assert resp.status_code == 200
        assert resp.json == {"success": True, "chat_prompt_id": preset, "applied": True}
        assert _chat_prompt(app, pg_conn) == preset

    def test_own_and_team_prompts(self, app, pg_conn):
        own = str(PromptsRepository(pg_conn).create(ALICE, "Mine", "x")["id"])
        team = str(PromptsRepository(pg_conn).create(BOB, "Bob's", "y")["id"])
        _share_prompt(pg_conn, team, BOB, ALICE)
        assert _call(app, pg_conn, "put", json={"chat_prompt_id": own}).status_code == 200
        assert _chat_prompt(app, pg_conn) == own
        assert _call(app, pg_conn, "put", json={"chat_prompt_id": team.upper()}).status_code == 200
        assert _chat_prompt(app, pg_conn) == team

    def test_unreadable_prompt_is_refused_and_not_stored(self, app, pg_conn):
        _call(app, pg_conn, "put", json={"chat_prompt_id": "strict"})
        strangers = str(PromptsRepository(pg_conn).create(BOB, "Private", "z")["id"])
        resp = _call(app, pg_conn, "put", json={"chat_prompt_id": strangers})
        assert resp.status_code == 404
        assert _chat_prompt(app, pg_conn) == "strict"

    @pytest.mark.parametrize(
        "body", [None, {}, {"chat_prompt_id": ""}, {"chat_prompt_id": 5}, {"chat_prompt_id": "agentic_default"}]
    )
    def test_bad_values_are_400(self, app, pg_conn, body):
        assert _call(app, pg_conn, "put", json=body).status_code == 400

    def test_a_deleted_prompt_reads_as_default(self, app, pg_conn):
        pid = str(PromptsRepository(pg_conn).create(ALICE, "Gone", "x")["id"])
        _call(app, pg_conn, "put", json={"chat_prompt_id": pid})
        PromptsRepository(pg_conn).delete(pid, ALICE)
        assert _chat_prompt(app, pg_conn) == "default"

    def test_a_revoked_share_reads_as_default(self, app, pg_conn):
        pid = str(PromptsRepository(pg_conn).create(BOB, "Bob's", "y")["id"])
        team = _share_prompt(pg_conn, pid, BOB, ALICE)
        _call(app, pg_conn, "put", json={"chat_prompt_id": pid})
        TeamMembersRepository(pg_conn).remove_member(str(team["id"]), ALICE)
        assert _chat_prompt(app, pg_conn) == "default"

    # A browser's pre-upgrade choice moves to the server only when nothing
    # was ever stored; a deliberate default (or a gone prompt) is a choice.
    def test_says_whether_a_chat_prompt_was_ever_stored(self, app, pg_conn):
        assert _call(app, pg_conn, "get").json == {
            "success": True,
            "chat_prompt_id": "default",
            "chat_prompt_set": False,
        }
        _call(app, pg_conn, "put", json={"chat_prompt_id": "default"})
        assert _call(app, pg_conn, "get").json["chat_prompt_set"] is True

    def test_a_gone_prompt_still_counts_as_stored(self, app, pg_conn):
        pid = str(PromptsRepository(pg_conn).create(ALICE, "Gone", "x")["id"])
        _call(app, pg_conn, "put", json={"chat_prompt_id": pid})
        PromptsRepository(pg_conn).delete(pid, ALICE)
        body = _call(app, pg_conn, "get").json
        assert body["chat_prompt_id"] == "default"
        assert body["chat_prompt_set"] is True

    def test_keeps_the_default_tool_switches(self, app, pg_conn):
        UsersRepository(pg_conn).set_default_tool_enabled(ALICE, "memory", False)
        _call(app, pg_conn, "put", json={"chat_prompt_id": "creative"})
        prefs = UsersRepository(pg_conn).get(ALICE)["tool_preferences"]
        assert prefs["disabled_default_tools"] == ["memory"]
        assert prefs["chat_prompt_id"] == "creative"


class TestMoveOnlyIfUnset:
    """``only_if_unset``: a browser's pre-upgrade choice never overwrites a stored one."""

    def test_stores_when_nothing_was_stored(self, app, pg_conn):
        resp = _call(app, pg_conn, "put", json={"chat_prompt_id": "creative", "only_if_unset": True})
        assert resp.status_code == 200
        assert resp.json == {"success": True, "chat_prompt_id": "creative", "applied": True}
        assert _chat_prompt(app, pg_conn) == "creative"

    # Another browser saved a pick after this one read chat_prompt_set=false.
    @pytest.mark.parametrize("stored", ["strict", "default"])
    def test_keeps_a_stored_choice_and_returns_it(self, app, pg_conn, stored):
        _call(app, pg_conn, "put", json={"chat_prompt_id": stored})
        resp = _call(app, pg_conn, "put", json={"chat_prompt_id": "creative", "only_if_unset": True})
        assert resp.status_code == 200
        assert resp.json == {"success": True, "chat_prompt_id": stored, "applied": False}
        assert _chat_prompt(app, pg_conn) == stored

    def test_returns_a_gone_stored_prompt_as_default(self, app, pg_conn):
        pid = str(PromptsRepository(pg_conn).create(ALICE, "Gone", "x")["id"])
        _call(app, pg_conn, "put", json={"chat_prompt_id": pid})
        PromptsRepository(pg_conn).delete(pid, ALICE)
        resp = _call(app, pg_conn, "put", json={"chat_prompt_id": "creative", "only_if_unset": True})
        assert resp.json == {"success": True, "chat_prompt_id": "default", "applied": False}

    def test_keeps_the_default_tool_switches(self, app, pg_conn):
        UsersRepository(pg_conn).set_default_tool_enabled(ALICE, "memory", False)
        _call(app, pg_conn, "put", json={"chat_prompt_id": "creative", "only_if_unset": True})
        prefs = UsersRepository(pg_conn).get(ALICE)["tool_preferences"]
        assert prefs == {"disabled_default_tools": ["memory"], "chat_prompt_id": "creative"}

    @pytest.mark.parametrize("flag", ["yes", 1, None])
    def test_a_non_boolean_flag_is_400(self, app, pg_conn, flag):
        resp = _call(app, pg_conn, "put", json={"chat_prompt_id": "creative", "only_if_unset": flag})
        assert resp.status_code == 400


class TestUnexpectedErrors:
    """A failure that isn't the request's fault is a 5xx, which the UI's start-up read retries."""

    def test_a_failed_read_is_500(self, app, pg_conn):
        with patch.object(UsersRepository, "get", side_effect=RuntimeError("connection reset")):
            resp = _call(app, pg_conn, "get")
        assert resp.status_code == 500
        assert resp.json == {"success": False}

    @pytest.mark.parametrize("only_if_unset", [False, True])
    def test_a_failed_write_is_500(self, app, pg_conn, only_if_unset):
        with patch.object(UsersRepository, "set_chat_prompt_id", side_effect=RuntimeError("connection reset")):
            resp = _call(app, pg_conn, "put", json={"chat_prompt_id": "strict", "only_if_unset": only_if_unset})
        assert resp.status_code == 500
        assert resp.json == {"success": False}


class TestSetChatPromptIdRepository:
    def test_only_if_unset_reports_whether_it_wrote(self, pg_conn):
        repo = UsersRepository(pg_conn)
        assert repo.set_chat_prompt_id(ALICE, "strict", only_if_unset=True) is True
        assert repo.set_chat_prompt_id(ALICE, "creative", only_if_unset=True) is False
        assert repo.get(ALICE)["tool_preferences"]["chat_prompt_id"] == "strict"

    def test_a_plain_write_always_replaces(self, pg_conn):
        repo = UsersRepository(pg_conn)
        assert repo.set_chat_prompt_id(ALICE, "strict") is True
        assert repo.set_chat_prompt_id(ALICE, "creative") is True
        assert repo.get(ALICE)["tool_preferences"]["chat_prompt_id"] == "creative"
