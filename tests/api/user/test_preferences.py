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
        "body",
        [
            None,
            {},
            {"only_if_unset": True},
            {"chat_prompt_id": ""},
            {"chat_prompt_id": 5},
            {"chat_prompt_id": "agentic_default"},
        ],
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
        body = _call(app, pg_conn, "get").json
        assert {k: body[k] for k in ("success", "chat_prompt_id", "chat_prompt_set")} == {
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


def _registry(default="gpt-default"):
    """A catalog of two built-ins plus a disabled one, and Alice's own custom model."""
    from types import SimpleNamespace

    def get_model(model_id, user_id=None):
        if user_id == ALICE and model_id == "byom-alice":
            return SimpleNamespace(id=model_id, enabled=True)
        if model_id in ("gpt-a", "gpt-b", default):
            return SimpleNamespace(id=model_id, enabled=True)
        if model_id == "gpt-off":
            return SimpleNamespace(id=model_id, enabled=False)
        return None

    return SimpleNamespace(
        get_model=get_model,
        model_exists=lambda model_id, user_id=None: get_model(model_id, user_id) is not None,
        default_model_id=default,
    )


class TestTaskModel:
    """``task_model_id``: the model the caller's DocsGPT jobs run on; null uses the instance's."""

    @pytest.fixture(autouse=True)
    def catalog(self, monkeypatch):
        from docsgpt.core.settings import settings

        registry = _registry()
        monkeypatch.setattr("docsgpt.core.model_registry.ModelRegistry.get_instance", lambda: registry)
        monkeypatch.setattr(settings, "TASK_MODEL_ID", None)

    def test_nothing_set_reads_null_and_the_instance_default(self, app, pg_conn):
        body = _call(app, pg_conn, "get").json
        assert body["task_model_id"] is None
        assert body["instance_task_model_id"] == "gpt-default"

    def test_the_instance_default_follows_the_admin_then_the_env(self, app, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings
        from docsgpt.storage.db import model_defaults

        monkeypatch.setattr(settings, "TASK_MODEL_ID", "gpt-a")
        assert _call(app, pg_conn, "get").json["instance_task_model_id"] == "gpt-a"
        model_defaults.save_task_model(pg_conn, "gpt-b")
        assert _call(app, pg_conn, "get").json["instance_task_model_id"] == "gpt-b"

    @pytest.mark.parametrize("model_id", ["gpt-a", "byom-alice"])
    def test_round_trip(self, app, pg_conn, model_id):
        resp = _call(app, pg_conn, "put", json={"task_model_id": model_id})
        assert resp.status_code == 200
        assert resp.json == {"success": True, "task_model_id": model_id}
        assert _call(app, pg_conn, "get").json["task_model_id"] == model_id

    @pytest.mark.parametrize("cleared", [None, ""])
    def test_null_goes_back_to_the_instance_default(self, app, pg_conn, cleared):
        _call(app, pg_conn, "put", json={"task_model_id": "gpt-a"})
        resp = _call(app, pg_conn, "put", json={"task_model_id": cleared})
        assert resp.status_code == 200 and resp.json["task_model_id"] is None
        assert "task_model_id" not in UsersRepository(pg_conn).get(ALICE)["tool_preferences"]

    @pytest.mark.parametrize(
        "value", ["gone-model", "gpt-off", 5, ["gpt-a"], pytest.param("x" * 300, id="too-long")]
    )
    def test_unknown_models_are_400_and_not_stored(self, app, pg_conn, value):
        resp = _call(app, pg_conn, "put", json={"task_model_id": value})
        assert resp.status_code == 400
        assert resp.json["code"] == "invalid_model"
        assert (UsersRepository(pg_conn).get(ALICE) or {}).get("tool_preferences") in (None, {})

    def test_someone_elses_custom_model_is_400(self, app, pg_conn):
        resp = _call(app, pg_conn, "put", user=BOB, json={"task_model_id": "byom-alice"})
        assert resp.status_code == 400

    def test_a_stale_choice_reads_as_null(self, app, pg_conn):
        UsersRepository(pg_conn).set_task_model_id(ALICE, "gone-model")
        assert _call(app, pg_conn, "get").json["task_model_id"] is None

    def test_keeps_the_chat_prompt(self, app, pg_conn):
        _call(app, pg_conn, "put", json={"chat_prompt_id": "strict"})
        _call(app, pg_conn, "put", json={"task_model_id": "gpt-a"})
        body = _call(app, pg_conn, "get").json
        assert body["chat_prompt_id"] == "strict" and body["task_model_id"] == "gpt-a"

    def test_both_in_one_request(self, app, pg_conn):
        resp = _call(app, pg_conn, "put", json={"chat_prompt_id": "creative", "task_model_id": "gpt-b"})
        assert resp.json == {"success": True, "chat_prompt_id": "creative", "applied": True, "task_model_id": "gpt-b"}

    def test_a_bad_task_model_stores_neither(self, app, pg_conn):
        resp = _call(app, pg_conn, "put", json={"chat_prompt_id": "creative", "task_model_id": "gone-model"})
        assert resp.status_code == 400
        assert _chat_prompt(app, pg_conn) == "default"

    def test_a_token_needs_models_write(self, app, pg_conn):
        from docsgpt.api.pat.tokens import AUTH_METHOD_PAT

        token = {"sub": ALICE, "auth_method": AUTH_METHOD_PAT, "scopes": ["prompts:write"]}
        with _patch_db(pg_conn), app.test_request_context(
            "/api/user/preferences", method="PUT", json={"task_model_id": "gpt-a"}
        ):
            from flask import request

            from docsgpt.api.user.me.routes import PreferencesResource

            request.decoded_token = token
            resp = PreferencesResource().put()
        assert resp.status_code == 403 and resp.json["required_scope"] == "models:write"
