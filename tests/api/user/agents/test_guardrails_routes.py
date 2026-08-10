"""Tests for application/api/user/agents/guardrails.py and config validation.

Uses the ephemeral ``pg_conn`` fixture so the repository code is real.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.agents.guardrails.db_readonly", _yield
    ):
        yield


def _seed_agent(pg_conn, user="u-gr"):
    from application.storage.db.repositories.agents import AgentsRepository

    return AgentsRepository(pg_conn).create(user, "guarded", "published")


# ---------------------------------------------------------------------------
# normalize_agent_config — the strict-on-write boundary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeAgentConfig:
    def _norm(self, raw):
        from application.api.user.agents.routes import normalize_agent_config

        return normalize_agent_config(raw)

    @pytest.mark.parametrize("empty", [None, ""])
    def test_empty_input_returns_none(self, empty):
        assert self._norm(empty) is None

    def test_accepts_a_json_string(self):
        out = self._norm('{"guardrails": {"enabled": true}}')
        assert out["guardrails"]["enabled"] is True

    def test_rejects_malformed_json(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            self._norm("{not json")

    def test_rejects_a_non_object(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            self._norm("[1, 2, 3]")

    def test_fills_defaults_so_the_stored_config_is_self_describing(self):
        out = self._norm({"guardrails": {"enabled": True}})
        guardrails = out["guardrails"]
        assert guardrails["mode"] == "monitor_only", "detect-first is the default"
        assert guardrails["fail_open"] is True
        assert guardrails["timeout_ms"] == 2000
        assert guardrails["block_message"]

    def test_normalizes_per_check_settings(self):
        out = self._norm(
            {"guardrails": {"controls": [{"check": "pii", "stage": "input"}]}}
        )
        assert out["guardrails"]["controls"][0]["settings"]["entities"]

    def test_rejects_unknown_check(self):
        with pytest.raises(ValueError, match="unknown check"):
            self._norm({"guardrails": {"controls": [{"check": "nope", "stage": "input"}]}})

    def test_rejects_stage_the_check_does_not_support(self):
        with pytest.raises(ValueError, match="does not support stage"):
            self._norm(
                {"guardrails": {"controls": [
                    {"check": "groundedness", "stage": "input"}
                ]}}
            )

    def test_rejects_require_approval_outside_tool_call(self):
        with pytest.raises(ValueError, match="not valid at stage"):
            self._norm(
                {"guardrails": {"controls": [
                    {"check": "pii", "stage": "input", "action": "require_approval"}
                ]}}
            )

    def test_rejects_redact_on_a_spanless_check(self):
        with pytest.raises(ValueError, match="cannot redact"):
            self._norm(
                {"guardrails": {"controls": [
                    {"check": "groundedness", "stage": "output", "action": "redact"}
                ]}}
            )

    def test_rejects_duplicate_control(self):
        with pytest.raises(ValueError, match="duplicate control"):
            self._norm(
                {"guardrails": {"controls": [
                    {"check": "pii", "stage": "input"},
                    {"check": "pii", "stage": "input"},
                ]}}
            )

    def test_rejects_denylist_with_no_terms(self):
        with pytest.raises(ValueError):
            self._norm(
                {"guardrails": {"controls": [
                    {"check": "denylist", "stage": "input", "settings": {"terms": []}}
                ]}}
            )

    def test_rejects_unknown_top_level_key(self):
        with pytest.raises(ValueError):
            self._norm({"nope": 1})

    def test_error_message_names_the_offending_field(self):
        with pytest.raises(ValueError) as exc:
            self._norm({"guardrails": {"timeout_ms": 5}})
        assert "timeout_ms" in str(exc.value), (
            f"error should point at the field, got: {exc.value}"
        )

    def test_rejects_overlong_block_message(self):
        with pytest.raises(ValueError, match="500"):
            self._norm({"guardrails": {"block_message": "x" * 501}})

    def test_rejects_bad_mode(self):
        with pytest.raises(ValueError, match="mode"):
            self._norm({"guardrails": {"mode": "yolo"}})


# ---------------------------------------------------------------------------
# GET /api/guardrails/catalog
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCatalogRoute:
    def _get(self, app, decoded_token={"sub": "u-gr"}):
        from application.api.user.agents.guardrails import GuardrailCatalog

        with app.test_request_context("/api/guardrails/catalog"):
            from flask import request

            request.decoded_token = decoded_token
            return GuardrailCatalog().get()

    def test_requires_auth(self, app):
        body, status = self._get(app, decoded_token=None)
        assert status == 401

    def test_lists_every_builtin_check(self, app):
        import json

        payload = json.loads(self._get(app).get_data(as_text=True))
        names = {c["name"] for c in payload["checks"]}
        assert names == {
            "pii", "secrets", "denylist", "url", "injection",
            "groundedness", "topic", "policy", "moderation", "tool_policy",
        }, f"unexpected catalog: {sorted(names)}"

    def test_each_check_carries_the_ui_contract(self, app):
        import json

        payload = json.loads(self._get(app).get_data(as_text=True))
        for check in payload["checks"]:
            assert isinstance(check["latency_hint_ms"], int)
            assert check["stages"], f"{check['name']} declares no stages"
            assert "supports_redaction" in check
            assert "available" in check

    def test_exposes_stage_action_matrix(self, app):
        import json

        payload = json.loads(self._get(app).get_data(as_text=True))
        assert payload["actions_by_stage"]["tool_call"] == [
            "block", "flag", "require_approval",
        ]
        assert "require_approval" not in payload["actions_by_stage"]["input"]

    def test_reports_the_instance_floor(self, app, monkeypatch):
        import json

        from application.core.settings import settings

        monkeypatch.setattr(
            settings,
            "GUARDRAILS_FLOOR",
            {"enabled": True,
             "controls": [{"check": "secrets", "stage": "output",
                           "action": "redact"}]},
        )
        payload = json.loads(self._get(app).get_data(as_text=True))
        assert payload["floor"] is not None
        assert payload["floor"]["controls"][0]["check"] == "secrets"

    def test_floor_is_null_when_unset(self, app, monkeypatch):
        import json

        from application.core.settings import settings

        monkeypatch.setattr(settings, "GUARDRAILS_FLOOR", {})
        payload = json.loads(self._get(app).get_data(as_text=True))
        assert payload["floor"] is None


# ---------------------------------------------------------------------------
# GET /api/guardrails/events
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEventsRoute:
    def _get(self, app, pg_conn, args="", decoded_token={"sub": "u-gr"}):
        from application.api.user.agents.guardrails import GuardrailEvents

        with app.test_request_context(f"/api/guardrails/events{args}"):
            from flask import request

            request.decoded_token = decoded_token
            with _patch_db(pg_conn):
                return GuardrailEvents().get()

    def test_requires_auth(self, app, pg_conn):
        _body, status = self._get(app, pg_conn, decoded_token=None)
        assert status == 401

    def test_requires_agent_id(self, app, pg_conn):
        resp = self._get(app, pg_conn)
        assert resp.status_code == 400

    def test_unknown_agent_is_404(self, app, pg_conn):
        import uuid

        resp = self._get(app, pg_conn, f"?agent_id={uuid.uuid4()}")
        assert resp.status_code == 404

    def test_another_users_agent_is_404(self, app, pg_conn):
        agent = _seed_agent(pg_conn, "owner")
        resp = self._get(
            app, pg_conn, f"?agent_id={agent['id']}",
            decoded_token={"sub": "intruder"},
        )
        assert resp.status_code == 404, "must not leak another user's agent"

    def test_returns_recorded_events(self, app, pg_conn):
        import json

        from application.storage.db.repositories.guardrail_events import (
            GuardrailEventsRepository,
        )

        agent = _seed_agent(pg_conn)
        GuardrailEventsRepository(pg_conn).record_many(
            [{"user_id": "u-gr", "agent_id": str(agent["id"]), "stage": "input",
              "check_name": "denylist", "detector_type": "DENYLIST",
              "action": "block", "outcome": "triggered"}]
        )
        resp = self._get(app, pg_conn, f"?agent_id={agent['id']}")
        payload = json.loads(resp.get_data(as_text=True))
        assert len(payload["events"]) == 1
        assert payload["events"][0]["check_name"] == "denylist"

    def test_rejects_non_integer_paging(self, app, pg_conn):
        agent = _seed_agent(pg_conn)
        resp = self._get(app, pg_conn, f"?agent_id={agent['id']}&limit=abc")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/guardrails/summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSummaryRoute:
    def _get(self, app, pg_conn, args="", decoded_token={"sub": "u-gr"}):
        from application.api.user.agents.guardrails import GuardrailSummary

        with app.test_request_context(f"/api/guardrails/summary{args}"):
            from flask import request

            request.decoded_token = decoded_token
            with _patch_db(pg_conn):
                return GuardrailSummary().get()

    def test_requires_auth(self, app, pg_conn):
        _body, status = self._get(app, pg_conn, decoded_token=None)
        assert status == 401

    def test_splits_blocked_from_flagged_from_unevaluated(self, app, pg_conn):
        import json

        from application.storage.db.repositories.guardrail_events import (
            GuardrailEventsRepository,
        )

        agent = _seed_agent(pg_conn)
        GuardrailEventsRepository(pg_conn).record_many(
            [
                {"user_id": "u-gr", "agent_id": str(agent["id"]),
                 "stage": "input", "check_name": "denylist",
                 "detector_type": "DENYLIST", "action": "block",
                 "outcome": "triggered"},
                {"user_id": "u-gr", "agent_id": str(agent["id"]),
                 "stage": "output", "check_name": "pii",
                 "detector_type": "PII", "action": "flag",
                 "outcome": "triggered"},
                {"user_id": "u-gr", "agent_id": str(agent["id"]),
                 "stage": "output", "check_name": "topic",
                 "detector_type": "TOPIC", "action": "flag",
                 "outcome": "not_evaluated"},
            ]
        )
        payload = json.loads(self._get(app, pg_conn).get_data(as_text=True))
        # "we refused", "we noticed" and "we could not tell" are three
        # different product problems; conflating them hides outages.
        assert payload["totals"] == {
            "blocked": 1, "flagged": 1, "redacted": 0, "not_evaluated": 1,
        }

    def test_rejects_non_integer_days(self, app, pg_conn):
        resp = self._get(app, pg_conn, "?days=lots")
        assert resp.status_code == 400


@pytest.mark.unit
class TestSummaryAgentScoping:
    """The agent-logs panel needs per-agent aggregates, not per-user ones."""

    def _get(self, app, pg_conn, args="", decoded_token={"sub": "u-gr"}):
        from application.api.user.agents.guardrails import GuardrailSummary

        with app.test_request_context(f"/api/guardrails/summary{args}"):
            from flask import request

            request.decoded_token = decoded_token
            with _patch_db(pg_conn):
                return GuardrailSummary().get()

    def _seed(self, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.guardrail_events import (
            GuardrailEventsRepository,
        )

        repo = AgentsRepository(pg_conn)
        first = str(repo.create("u-gr", "a", "published")["id"])
        second = str(repo.create("u-gr", "b", "published")["id"])
        GuardrailEventsRepository(pg_conn).record_many(
            [
                {"user_id": "u-gr", "agent_id": first, "stage": "input",
                 "check_name": "denylist", "detector_type": "DENYLIST",
                 "action": "block", "outcome": "triggered"},
                {"user_id": "u-gr", "agent_id": second, "stage": "output",
                 "check_name": "pii", "detector_type": "PII",
                 "action": "redact", "outcome": "triggered"},
            ]
        )
        return first, second

    def test_scopes_totals_to_one_agent(self, app, pg_conn):
        import json

        first, _second = self._seed(pg_conn)
        payload = json.loads(
            self._get(app, pg_conn, f"?agent_id={first}").get_data(as_text=True)
        )
        assert payload["totals"]["blocked"] == 1
        assert payload["totals"]["redacted"] == 0, (
            "the other agent's decisions must not leak into this agent's panel"
        )

    def test_without_agent_id_it_still_aggregates_everything(self, app, pg_conn):
        import json

        self._seed(pg_conn)
        payload = json.loads(self._get(app, pg_conn).get_data(as_text=True))
        assert payload["totals"]["blocked"] == 1
        assert payload["totals"]["redacted"] == 1

    def test_unreadable_agent_is_404(self, app, pg_conn):
        first, _second = self._seed(pg_conn)
        resp = self._get(
            app, pg_conn, f"?agent_id={first}", decoded_token={"sub": "intruder"}
        )
        assert resp.status_code == 404
