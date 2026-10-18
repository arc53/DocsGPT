"""The admin's default guardrails for new agents: storage, routes, and seeding on every path that creates an agent."""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.guardrails.config import GuardrailsConfig
from docsgpt.storage.db import agent_defaults
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository

INJECTION_FLAG = {"check": "injection_model", "stage": "input", "action": "flag"}
SECRETS = {"check": "secrets", "stage": "output", "action": "redact"}
DEFAULTS = {"enabled": True, "fail_open": False, "timeout_ms": 3000, "controls": [INJECTION_FLAG]}
URL = "/api/admin/defaults/agents"


@contextmanager
def _yielding(conn):
    yield conn


def _store(conn, **guardrails):
    return agent_defaults.save(conn, GuardrailsConfig.model_validate(guardrails))


def _checks(config):
    return [c["check"] for c in config["guardrails"]["controls"]]


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def db(pg_conn):
    with ExitStack() as stack:
        for target in (
            "docsgpt.api.admin.defaults.db_readonly",
            "docsgpt.api.admin.defaults.db_session",
            "docsgpt.api.user.agents.guardrails.db_readonly",
            "docsgpt.api.user.agents.routes.db_readonly",
            "docsgpt.api.user.agents.routes.db_session",
            "docsgpt.api.user.sharing.routes.db_readonly",
            "docsgpt.api.user.sharing.routes.db_session",
        ):
            stack.enter_context(patch(target, lambda: _yielding(pg_conn)))
        yield pg_conn


@contextmanager
def _as(sub, *roles):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=list(roles) or ["user"]
    ):
        yield


def _admin():
    return _as("admin1", "admin", "user")


@pytest.mark.unit
class TestStorage:
    def test_without_a_row_new_agents_get_what_they_always_did(self, pg_conn):
        assert agent_defaults.stored(pg_conn) is None
        assert agent_defaults.load(pg_conn) == GuardrailsConfig().model_dump(mode="json")
        config = {"api_write_allowlist": ["t:a"]}
        assert agent_defaults.seed(pg_conn, config) is config
        assert agent_defaults.seed(pg_conn, None) is None

    def test_the_defaults_fill_a_config_without_guardrails(self, pg_conn):
        _store(pg_conn, **DEFAULTS)
        seeded = agent_defaults.seed(pg_conn, {"api_write_allowlist": ["t:a"]})
        assert seeded["api_write_allowlist"] == ["t:a"] and _checks(seeded) == ["injection_model"]
        assert agent_defaults.seed(pg_conn, None)["guardrails"]["fail_open"] is False

    def test_the_request_wins_key_by_key_and_its_controls_replace_the_defaults(self, pg_conn):
        _store(pg_conn, **DEFAULTS)
        seeded = agent_defaults.seed(pg_conn, {"guardrails": {"mode": "scan_all", "controls": [SECRETS]}})
        assert seeded["guardrails"]["mode"] == "scan_all" and seeded["guardrails"]["timeout_ms"] == 3000
        assert _checks(seeded) == ["secrets"]
        seeded = agent_defaults.seed(pg_conn, {"guardrails": {"enabled": False}})
        assert seeded["guardrails"]["enabled"] is False and _checks(seeded) == ["injection_model"]

    def test_a_form_post_sends_json_text(self, pg_conn):
        _store(pg_conn, **DEFAULTS)
        assert _checks(agent_defaults.seed(pg_conn, json.dumps({"guardrails": {"controls": [SECRETS]}}))) == [
            "secrets"
        ]
        assert _checks(agent_defaults.seed(pg_conn, "")) == ["injection_model"]

    @pytest.mark.parametrize("config", ["{not json", ["list"], {"guardrails": "on"}])
    def test_a_malformed_config_is_left_to_validation(self, pg_conn, config):
        _store(pg_conn, **DEFAULTS)
        assert agent_defaults.seed(pg_conn, config) is config

    def test_a_control_this_instance_no_longer_allows_is_dropped_alone(self, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings

        _store(pg_conn, **{**DEFAULTS, "controls": [INJECTION_FLAG, SECRETS]})
        monkeypatch.setattr(settings, "GUARDRAILS_CHECKS_ENABLED", ["secrets"])
        assert [c["check"] for c in agent_defaults.load(pg_conn)["controls"]] == ["secrets"]

    def test_an_unreadable_row_is_no_row(self, pg_conn):
        AppMetadataRepository(pg_conn).set(agent_defaults.KEY, "{oops")
        assert agent_defaults.stored(pg_conn) is None


@pytest.mark.unit
class TestAdminRoutes:
    @pytest.mark.parametrize("method", ["get", "put"])
    def test_unauthenticated(self, client, method):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert getattr(client, method)(URL, json={}).status_code == 401

    @pytest.mark.parametrize("method", ["get", "put"])
    def test_non_admin_forbidden(self, client, db, method):
        with _as("member"):
            resp = getattr(client, method)(URL, json={"guardrails": DEFAULTS})
        assert resp.status_code == 403
        assert agent_defaults.stored(db) is None

    def test_get_without_a_row(self, client, db):
        with _admin():
            resp = client.get(URL)
        assert resp.status_code == 200
        assert resp.json["guardrails"] == GuardrailsConfig().model_dump(mode="json")
        assert set(resp.json["injection_model"]) == {"enabled", "runtime", "predicted_input_s", "timeout_s"}

    def test_put_stores_returns_the_get_body_and_audits_once(self, client, db):
        with _admin():
            resp = client.put(URL, json={"guardrails": DEFAULTS})
            again = client.put(URL, json={"guardrails": DEFAULTS})
            got = client.get(URL)
        assert resp.status_code == 200 and again.status_code == 200
        stored = GuardrailsConfig.model_validate(DEFAULTS).model_dump(mode="json")
        assert resp.json["guardrails"] == stored == got.json["guardrails"]
        rows = db.execute(text("SELECT actor_id, metadata FROM auth_events WHERE event = 'agent_defaults_set'"))
        rows = rows.fetchall()
        assert len(rows) == 1, "an unchanged save records nothing"
        actor, metadata = rows[0]
        assert actor == "admin1"
        assert set(metadata["changes"]) == {"enabled", "fail_open", "timeout_ms", "controls"}

    @pytest.mark.parametrize(
        "body, message",
        [
            ({}, "guardrails must be an object"),
            ({"guardrails": []}, "guardrails must be an object"),
            ({"guardrails": {"timeout_ms": 5}}, "guardrails.timeout_ms: must be >= 100"),
            ({"guardrails": {"controls": [INJECTION_FLAG, INJECTION_FLAG]}},
             "guardrails.controls: duplicate control for check 'injection_model' at stage 'input'"),
            ({"guardrails": {"bogus": 1}}, "guardrails.bogus: Extra inputs are not permitted"),
        ],
    )
    def test_put_validates(self, client, db, body, message):
        with _admin():
            resp = client.put(URL, json=body)
        assert resp.status_code == 400 and resp.json == {"success": False, "message": message}
        assert agent_defaults.stored(db) is None

    def test_saving_defaults_never_touches_an_existing_agent(self, client, db):
        repo = AgentsRepository(db)
        before = repo.create("u", "Old", "draft", config={"guardrails": {"enabled": False}})
        with _admin():
            assert client.put(URL, json={"guardrails": DEFAULTS}).status_code == 200
        assert repo.get(str(before["id"]), "u")["config"] == before["config"]


@pytest.mark.unit
class TestMemberRead:
    def test_unauthenticated(self, client):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.get("/api/agents/defaults").status_code == 401

    def test_any_user_reads_the_guardrails_only(self, client, db):
        with _as("member"):
            empty = client.get("/api/agents/defaults")
        _store(db, **DEFAULTS)
        with _as("member"):
            stored = client.get("/api/agents/defaults")
        assert empty.status_code == 200
        assert empty.json == {"success": True, "guardrails": GuardrailsConfig().model_dump(mode="json")}
        assert stored.json == {
            "success": True, "guardrails": GuardrailsConfig.model_validate(DEFAULTS).model_dump(mode="json")
        }

    def test_a_token_may_read_it(self):
        from docsgpt.api.pat.rules import RULES, is_denied

        rule = RULES[("/api/agents/defaults", "GET")]
        assert rule.scopes == ("agents:read",) and rule.open
        assert is_denied(URL, "GET") and is_denied(URL, "PUT")


# ── Seeding: every path that creates an agent ─────────────────────────────────


def _create(app, user, body=None, form=None):
    from docsgpt.api.user.agents.routes import CreateAgent

    base = {"name": f"Agent of {user}", "description": "d", "agent_type": "classic", "status": "draft"}
    kwargs = {"data": {**base, **form}} if form is not None else {"json": {**base, **(body or {})}}
    with app.test_request_context("/api/create_agent", method="POST", **kwargs):
        from flask import request

        request.decoded_token = {"sub": user}
        response = CreateAgent().post()
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json["id"]


@pytest.mark.unit
class TestSeeding:
    @pytest.fixture
    def app(self):
        return Flask(__name__)

    def test_create_without_a_config_starts_from_the_defaults(self, app, db):
        _store(db, **DEFAULTS)
        agent = AgentsRepository(db).get(_create(app, "u-create-1"), "u-create-1")
        assert agent["config"]["guardrails"] == GuardrailsConfig.model_validate(DEFAULTS).model_dump(mode="json")

    def test_create_overlays_the_request_guardrails(self, app, db):
        _store(db, **DEFAULTS)
        body = {"config": {"guardrails": {"mode": "scan_all", "controls": [SECRETS]}}}
        guardrails = AgentsRepository(db).get(_create(app, "u-create-2", body), "u-create-2")["config"]["guardrails"]
        assert guardrails["mode"] == "scan_all" and guardrails["timeout_ms"] == 3000
        assert [c["check"] for c in guardrails["controls"]] == ["secrets"]

    def test_create_from_a_form_post(self, app, db):
        _store(db, **DEFAULTS)
        form = {"config": json.dumps({"guardrails": {"fail_open": True}})}
        guardrails = AgentsRepository(db).get(_create(app, "u-create-3", form=form), "u-create-3")["config"][
            "guardrails"
        ]
        assert guardrails["fail_open"] is True and guardrails["controls"][0]["check"] == "injection_model"

    def test_create_without_defaults_stores_what_it_always_did(self, app, db):
        assert AgentsRepository(db).get(_create(app, "u-create-4"), "u-create-4")["config"] == {}

    def test_a_merged_config_that_does_not_validate_is_refused(self, app, db):
        from docsgpt.api.user.agents.routes import CreateAgent

        _store(db, **DEFAULTS)
        body = {"name": "Bad", "description": "d", "status": "draft",
                "config": {"guardrails": {"controls": [INJECTION_FLAG, INJECTION_FLAG]}}}
        with app.test_request_context("/api/create_agent", method="POST", json=body):
            from flask import request

            request.decoded_token = {"sub": "u-create-5"}
            assert CreateAgent().post().status_code == 400

    @pytest.mark.parametrize("template_config", [None, {"guardrails": {"mode": "scan_all"}}])
    def test_adopting_a_template(self, app, db, template_config):
        from docsgpt.api.user.agents.routes import AdoptAgent

        _store(db, **DEFAULTS)
        extra = {"config": template_config} if template_config else {}
        template = AgentsRepository(db).create("__system__", "Tpl", "template", description="t", **extra)
        with app.test_request_context(f"/api/adopt_agent?id={template['id']}", method="POST"):
            from flask import request

            request.decoded_token = {"sub": "u-adopter"}
            response = AdoptAgent().post()
        assert response.status_code == 200
        (adopted,) = AgentsRepository(db).list_for_user("u-adopter")
        guardrails = adopted["config"]["guardrails"]
        assert guardrails["controls"][0]["check"] == "injection_model"
        assert guardrails["mode"] == ("scan_all" if template_config else "monitor_only")

    def test_importing_a_new_agent(self, app, db):
        from docsgpt.api.user.agents.portability import API_VERSION, apply_import

        _store(db, **DEFAULTS)
        doc = {"apiVersion": API_VERSION, "kind": "Agent", "metadata": {"slug": "imp"},
               "spec": {"name": "Imported", "config": {"guardrails": {"mode": "scan_all"}}}}
        with app.app_context():
            result = apply_import(db, "u-importer", doc)
        guardrails = AgentsRepository(db).get(result["agent_id"], "u-importer")["config"]["guardrails"]
        assert guardrails["mode"] == "scan_all" and guardrails["controls"][0]["check"] == "injection_model"

    def test_importing_a_new_agent_with_an_invalid_config_keeps_the_defaults(self, app, db):
        from docsgpt.api.user.agents.portability import API_VERSION, apply_import

        _store(db, **DEFAULTS)
        doc = {"apiVersion": API_VERSION, "kind": "Agent", "metadata": {"slug": "imp-bad"},
               "spec": {"name": "Imported", "config": {"guardrails": {"controls": "not a list"}}}}
        with app.app_context():
            result = apply_import(db, "u-importer3", doc)
        guardrails = AgentsRepository(db).get(result["agent_id"], "u-importer3")["config"]["guardrails"]
        assert guardrails["controls"][0]["check"] == "injection_model"

    def test_reimporting_over_an_agent_never_reseeds_it(self, app, db):
        from docsgpt.api.user.agents.portability import API_VERSION, apply_import

        doc = {"apiVersion": API_VERSION, "kind": "Agent", "metadata": {"slug": "imp2"},
               "spec": {"name": "Imported"}}
        with app.app_context():
            first = apply_import(db, "u-importer2", doc)
            _store(db, **DEFAULTS)
            second = apply_import(db, "u-importer2", doc)
        assert second["action"] == "updated" and second["agent_id"] == first["agent_id"]
        assert AgentsRepository(db).get(first["agent_id"], "u-importer2")["config"] == {}

    def test_a_shared_conversation_agent(self, app, db):
        from docsgpt.api.user.sharing.routes import ShareConversation
        from docsgpt.storage.db.repositories.conversations import ConversationsRepository
        from docsgpt.storage.db.repositories.shared_conversations import SharedConversationsRepository

        _store(db, **DEFAULTS)
        conv = ConversationsRepository(db).create("u-sharer", name="C")
        ConversationsRepository(db).append_message(str(conv["id"]), {"prompt": "p", "response": "r"})
        with app.test_request_context(
            "/api/share?isPromptable=true", method="POST", json={"conversation_id": str(conv["id"])}
        ):
            from flask import request

            request.decoded_token = {"sub": "u-sharer"}
            response = ShareConversation().post()
        assert response.status_code == 201
        share = SharedConversationsRepository(db).find_by_uuid(response.json["identifier"])
        agent = AgentsRepository(db).find_by_key(share["api_key"])
        assert agent["config"]["guardrails"]["controls"][0]["check"] == "injection_model"

    def test_an_existing_agent_is_never_reseeded(self, app, db):
        agent_id = _create(app, "u-create-6")
        _store(db, **DEFAULTS)
        assert AgentsRepository(db).get(agent_id, "u-create-6")["config"] == {}
