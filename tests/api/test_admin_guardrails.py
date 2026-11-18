"""Admin > Guardrails: the floor every agent follows, the MCP description warnings, and the injection model's cost."""

from __future__ import annotations

import dataclasses
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.guardrails import floor
from docsgpt.guardrails.config import GuardrailsConfig

FLOOR = {"enabled": True, "mode": "scan_all", "controls": [{"check": "injection_model", "stage": "input"}]}
URL = "/api/admin/guardrails"


@contextmanager
def _yielding(conn):
    yield conn


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def db(pg_conn):
    with ExitStack() as stack:
        for target in (
            "docsgpt.api.admin.guardrails.db_readonly",
            "docsgpt.api.admin.guardrails.db_session",
            "docsgpt.guardrails.floor.db_readonly",
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


def _audit_rows(db):
    return db.execute(
        text("SELECT actor_id, metadata FROM auth_events WHERE event = 'guardrails_settings_set'")
    ).fetchall()


@pytest.mark.unit
class TestAuth:
    @pytest.mark.parametrize("method", ["get", "put"])
    def test_unauthenticated(self, client, method):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert getattr(client, method)(URL, json={}).status_code == 401

    @pytest.mark.parametrize("method", ["get", "put"])
    def test_non_admin_forbidden(self, client, db, method):
        with _as("member"):
            resp = getattr(client, method)(URL, json={"floor": FLOOR})
        assert resp.status_code == 403
        assert floor.stored(db) is None

    def test_a_token_may_not_call_it(self):
        from docsgpt.api.pat.rules import is_denied

        assert is_denied(URL, "GET") and is_denied(URL, "PUT")


@pytest.mark.unit
class TestRoutes:
    def test_get_without_a_row_and_without_measuring(self, client, db, monkeypatch):
        from docsgpt import decisions
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "DECISION_MODE", None)
        monkeypatch.setattr(settings, "DECISION_MODEL", None)

        def refuse(*args, **kwargs):
            raise AssertionError("the Guardrails page must not load or time the model")

        monkeypatch.setattr(decisions, "warm", refuse)
        monkeypatch.setattr(decisions, "auto_on", refuse)
        with _admin():
            resp = client.get(URL)
        assert resp.status_code == 200
        assert resp.json == {
            "success": True,
            "floor": None,
            "mcp_description_warnings": False,
            "injection_model": {
                "enabled": False, "runtime": "onnx-int8", "predicted_input_s": None, "timeout_s": 2.0,
            },
        }
        assert decisions.get_decider()._backend is None

    def test_the_cost_comes_from_the_measured_profile(self, client, db, monkeypatch):
        from docsgpt.core.settings import settings
        from docsgpt.decisions import features
        from docsgpt.decisions.latency import SpeedProfile
        from docsgpt.decisions.testing import FakeDecider, installed

        profile = SpeedProfile(c=0.01, a=0.0001, b=0.0, overhead=50, threads=4, measured_at=0.0)
        fake = FakeDecider(profile=profile)
        fake.info = dataclasses.replace(fake.info, runtime="vllm")
        monkeypatch.setattr(settings, "DECISION_INJECTION_ENABLED", True)
        with installed(fake), _admin():
            model = client.get(URL).json["injection_model"]
        assert model == {
            "enabled": True,
            "runtime": "vllm",
            "predicted_input_s": round(profile.predict_s(features.INJECTION_INPUT.shape), 3),
            "timeout_s": 2.0,
        }
        assert fake.calls == [] and fake.warmed == 0

    def test_put_stores_the_floor_applies_it_at_once_and_audits_once(self, client, db):
        with _admin():
            resp = client.put(URL, json={"floor": FLOOR})
            again = client.put(URL, json={"floor": FLOOR})
            got = client.get(URL)
        assert resp.status_code == 200 and again.status_code == 200
        stored = GuardrailsConfig.model_validate(FLOOR).model_dump(mode="json")
        assert resp.json["floor"] == stored == got.json["floor"]
        assert set(resp.json) == {"success", "floor", "mcp_description_warnings", "injection_model"}
        # The writing process does not wait for the TTL.
        assert [c.check for c in floor.current().controls] == ["injection_model"]
        rows = _audit_rows(db)
        assert len(rows) == 1, "an unchanged save records nothing"
        actor, metadata = rows[0]
        assert actor == "admin1" and metadata["changes"] == {"floor": [None, stored]}

    def test_put_null_clears_the_floor(self, client, db):
        with _admin():
            client.put(URL, json={"floor": FLOOR})
            resp = client.put(URL, json={"floor": None})
        assert resp.status_code == 200 and resp.json["floor"] is None
        assert floor.current() is None and len(_audit_rows(db)) == 2

    def test_put_the_mcp_warnings_alone_keeps_the_floor(self, client, db):
        with _admin():
            client.put(URL, json={"floor": FLOOR})
            resp = client.put(URL, json={"mcp_description_warnings": True})
        assert resp.json["mcp_description_warnings"] is True and resp.json["floor"]["enabled"] is True
        assert floor.mcp_description_warnings(db) is True
        assert _audit_rows(db)[-1][1]["changes"] == {"mcp_description_warnings": [False, True]}

    @pytest.mark.parametrize(
        "body, message",
        [
            ({}, "Send floor, mcp_description_warnings or both"),
            ([], "Send floor, mcp_description_warnings or both"),
            ({"floor": []}, "floor must be an object or null"),
            ({"floor": {"mode": "loud"}}, "floor.mode: mode must be one of monitor_only, scan_all"),
            ({"floor": {"controls": [{"check": "nope", "stage": "input"}]}},
             "floor.controls.0.check: unknown check 'nope'"),
            ({"floor": {"controls": [{"check": "injection_model", "stage": "output"}]}},
             "floor.controls.0: check 'injection_model' does not support stage 'output' "
             "(supported: attachment, input, retrieval, tool_result)"),
            ({"mcp_description_warnings": "yes"}, "mcp_description_warnings must be true or false"),
        ],
    )
    def test_put_validates(self, client, db, body, message):
        with _admin():
            resp = client.put(URL, json=body)
        assert resp.status_code == 400 and resp.json == {"success": False, "message": message}
        assert floor.stored(db) is None and _audit_rows(db) == []

    def test_saving_never_touches_an_agent_row(self, client, db):
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        repo = AgentsRepository(db)
        agent = repo.create("u", "A", "draft", config={"guardrails": {"enabled": False}})
        with _admin():
            assert client.put(URL, json={"floor": FLOOR}).status_code == 200
        assert repo.get(str(agent["id"]), "u")["config"] == agent["config"]
