"""Tests for docsgpt/api/user/agents/guardrails.py and config validation.

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
        "docsgpt.api.user.agents.guardrails.db_readonly", _yield
    ):
        yield


def _seed_agent(pg_conn, user="u-gr"):
    from docsgpt.storage.db.repositories.agents import AgentsRepository

    return AgentsRepository(pg_conn).create(user, "guarded", "published")


# ---------------------------------------------------------------------------
# normalize_agent_config — the strict-on-write boundary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeAgentConfig:
    def _norm(self, raw):
        from docsgpt.api.user.agents.routes import normalize_agent_config

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
        from docsgpt.api.user.agents.guardrails import GuardrailCatalog

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
            "groundedness", "policy",
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
        for stage in ("input", "retrieval", "tool_result", "output"):
            assert payload["actions_by_stage"][stage] == ["block", "flag", "redact"]
        assert "tool_call" not in payload["actions_by_stage"]

    def test_reports_the_instance_floor(self, app, monkeypatch):
        import json

        from docsgpt.core.settings import settings

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

        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "GUARDRAILS_FLOOR", {})
        payload = json.loads(self._get(app).get_data(as_text=True))
        assert payload["floor"] is None


# ---------------------------------------------------------------------------
# GET /api/guardrails/events
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEventsRoute:
    def _get(self, app, pg_conn, args="", decoded_token={"sub": "u-gr"}):
        from docsgpt.api.user.agents.guardrails import GuardrailEvents

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

        from docsgpt.storage.db.repositories.guardrail_events import (
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


@pytest.mark.unit
class TestEventsFilters:
    """Server-side ``days`` / ``check`` / ``outcome`` filters on the events list."""

    def _get(self, app, pg_conn, args="", decoded_token={"sub": "u-gr"}):
        from docsgpt.api.user.agents.guardrails import GuardrailEvents

        with app.test_request_context(f"/api/guardrails/events{args}"):
            from flask import request

            request.decoded_token = decoded_token
            with _patch_db(pg_conn):
                return GuardrailEvents().get()

    def _events(self, app, pg_conn, agent_id, query=""):
        import json

        resp = self._get(app, pg_conn, f"?agent_id={agent_id}{query}")
        assert resp.status_code == 200
        payload = json.loads(resp.get_data(as_text=True))
        assert payload["success"] is True
        return payload["events"]

    def _seed(self, pg_conn):
        """Five rows on one agent, one on another, with distinct ages.

        Ages (days): pii/redact 0, denylist/block 2, pii/flag 5,
        policy/not_evaluated 10, denylist/flag 40. The other agent has a
        fresh denylist/block row that must never show up.
        """
        from sqlalchemy import text

        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.guardrail_events import (
            GuardrailEventsRepository,
        )

        agents = AgentsRepository(pg_conn)
        agent = str(agents.create("u-gr", "a", "published")["id"])
        other = str(agents.create("u-gr", "b", "published")["id"])

        def row(agent_id, check, action, outcome, request_id):
            return {"user_id": "u-gr", "agent_id": agent_id, "stage": "input",
                    "check_name": check, "detector_type": check.upper(),
                    "action": action, "outcome": outcome,
                    "request_id": request_id}

        GuardrailEventsRepository(pg_conn).record_many(
            [
                row(agent, "pii", "redact", "triggered", "age-0"),
                row(agent, "denylist", "block", "triggered", "age-2"),
                row(agent, "pii", "flag", "triggered", "age-5"),
                row(agent, "policy", "block", "not_evaluated", "age-10"),
                row(agent, "denylist", "flag", "triggered", "age-40"),
                row(other, "denylist", "block", "triggered", "other"),
            ]
        )
        for age in (2, 5, 10, 40):
            pg_conn.execute(
                text(
                    "UPDATE guardrail_events SET created_at = "
                    "NOW() - CAST(:days || ' days' AS interval) "
                    "WHERE request_id = :rid"
                ),
                {"days": str(age), "rid": f"age-{age}"},
            )
        return agent

    @staticmethod
    def _ids(events):
        return [e["request_id"] for e in events]

    def test_no_filters_returns_everything_newest_first(self, app, pg_conn):
        agent = self._seed(pg_conn)
        assert self._ids(self._events(app, pg_conn, agent)) == [
            "age-0", "age-2", "age-5", "age-10", "age-40",
        ]

    def test_days_keeps_only_the_trailing_window(self, app, pg_conn):
        agent = self._seed(pg_conn)
        assert self._ids(self._events(app, pg_conn, agent, "&days=7")) == [
            "age-0", "age-2", "age-5",
        ]

    @pytest.mark.parametrize("raw", ["0", "-3"])
    def test_days_below_one_clamps_to_one(self, app, pg_conn, raw):
        agent = self._seed(pg_conn)
        assert self._ids(self._events(app, pg_conn, agent, f"&days={raw}")) == ["age-0"]

    def test_days_above_365_clamps_to_365(self, app, pg_conn):
        from sqlalchemy import text

        agent = self._seed(pg_conn)
        pg_conn.execute(
            text(
                "UPDATE guardrail_events SET created_at = NOW() - interval '400 days' "
                "WHERE request_id = 'age-40'"
            )
        )
        assert "age-40" not in self._ids(self._events(app, pg_conn, agent, "&days=9999"))

    @pytest.mark.parametrize("raw", ["lots", "", "1.5"])
    def test_invalid_days_is_ignored(self, app, pg_conn, raw):
        agent = self._seed(pg_conn)
        assert len(self._events(app, pg_conn, agent, f"&days={raw}")) == 5

    def test_check_is_an_exact_match(self, app, pg_conn):
        agent = self._seed(pg_conn)
        assert self._ids(self._events(app, pg_conn, agent, "&check=denylist")) == [
            "age-2", "age-40",
        ]
        assert self._events(app, pg_conn, agent, "&check=deny") == []

    def test_empty_check_is_ignored(self, app, pg_conn):
        agent = self._seed(pg_conn)
        assert len(self._events(app, pg_conn, agent, "&check=")) == 5

    @pytest.mark.parametrize(
        "outcome, expected",
        [
            ("block", ["age-2"]),
            ("redact", ["age-0"]),
            ("flag", ["age-5", "age-40"]),
            ("not_evaluated", ["age-10"]),
        ],
    )
    def test_outcome_matches_the_summary_buckets(self, app, pg_conn, outcome, expected):
        # ``block`` means "we refused": a block control that could not run is
        # ``not_evaluated``, exactly as the summary totals count it.
        agent = self._seed(pg_conn)
        assert self._ids(self._events(app, pg_conn, agent, f"&outcome={outcome}")) == expected

    @pytest.mark.parametrize("raw", ["triggered", "BLOCK", "nope", ""])
    def test_unknown_outcome_is_ignored(self, app, pg_conn, raw):
        agent = self._seed(pg_conn)
        assert len(self._events(app, pg_conn, agent, f"&outcome={raw}")) == 5

    def test_filters_combine_with_and(self, app, pg_conn):
        agent = self._seed(pg_conn)
        assert self._ids(
            self._events(app, pg_conn, agent, "&check=denylist&outcome=flag")
        ) == ["age-40"]
        assert self._events(
            app, pg_conn, agent, "&check=denylist&outcome=flag&days=30"
        ) == []
        assert self._ids(
            self._events(app, pg_conn, agent, "&check=pii&outcome=flag&days=30")
        ) == ["age-5"]

    def test_offset_pages_within_the_filtered_set(self, app, pg_conn):
        agent = self._seed(pg_conn)
        query = "&check=pii&days=30&limit=1"
        assert self._ids(self._events(app, pg_conn, agent, query)) == ["age-0"]
        assert self._ids(self._events(app, pg_conn, agent, f"{query}&offset=1")) == ["age-5"]
        assert self._events(app, pg_conn, agent, f"{query}&offset=2") == []

    def test_filters_do_not_widen_access(self, app, pg_conn):
        agent = self._seed(pg_conn)
        resp = self._get(
            app, pg_conn, f"?agent_id={agent}&check=denylist&days=30",
            decoded_token={"sub": "intruder"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/guardrails/summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSummaryRoute:
    def _get(self, app, pg_conn, args="", decoded_token={"sub": "u-gr"}):
        from docsgpt.api.user.agents.guardrails import GuardrailSummary

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

        from docsgpt.storage.db.repositories.guardrail_events import (
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
                 "stage": "output", "check_name": "policy",
                 "detector_type": "POLICY", "action": "flag",
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
        from docsgpt.api.user.agents.guardrails import GuardrailSummary

        with app.test_request_context(f"/api/guardrails/summary{args}"):
            from flask import request

            request.decoded_token = decoded_token
            with _patch_db(pg_conn):
                return GuardrailSummary().get()

    def _seed(self, pg_conn):
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.guardrail_events import (
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


@pytest.mark.unit
class TestConfigRejectionDoesNotLeakInternals:
    """CodeQL: exception text must not reach the caller.

    ``normalize_agent_config`` still raises a detailed error — portability
    warnings and the unit tests above rely on it — but the HTTP boundary
    returns a static message and logs the detail, matching the SourceConfig
    write path in ``api/user/sources/routes.py``.
    """

    def test_the_static_message_is_not_derived_from_the_exception(self):
        from docsgpt.api.user.agents.routes import (
            INVALID_CONFIG_MESSAGE,
            normalize_agent_config,
        )

        with pytest.raises(ValueError) as exc:
            normalize_agent_config(
                {"guardrails": {"controls": [{"check": "nope", "stage": "input"}]}}
            )
        detail = str(exc.value)
        assert "nope" in detail, "the internal error stays specific"
        assert "nope" not in INVALID_CONFIG_MESSAGE
        assert INVALID_CONFIG_MESSAGE not in detail

    def test_internal_validator_text_still_names_the_field(self):
        from docsgpt.api.user.agents.routes import normalize_agent_config

        with pytest.raises(ValueError, match="timeout_ms"):
            normalize_agent_config({"guardrails": {"timeout_ms": 5}})
