"""Unit tests for the shared request-scoped audit helper."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from docsgpt.api.audit import ACTIVITY_CATEGORIES, category_for, record_event


@pytest.fixture
def app():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


@pytest.mark.unit
class TestRecordEvent:
    def test_writes_actor_target_and_request_context(self, app):
        repo = Mock()
        conn = MagicMock()
        with app.test_request_context(
            "/api/anything",
            environ_base={"REMOTE_ADDR": "203.0.113.7"},
            headers={"User-Agent": "curl/8"},
        ):
            with patch("docsgpt.api.audit.AuthEventsRepository", return_value=repo):
                record_event(
                    conn, "source.deleted", actor="u1", target=None, source_id="s1"
                )
        kwargs = repo.insert.call_args.kwargs
        assert kwargs["event"] == "source.deleted"
        assert kwargs["actor_id"] == "u1"
        assert kwargs["target_id"] is None
        assert kwargs["ip"] == "203.0.113.7"
        assert kwargs["user_agent"] == "curl/8"
        assert kwargs["metadata"] == {"source_id": "s1"}

    def test_drops_none_metadata_values(self, app):
        repo = Mock()
        with app.test_request_context("/api/anything"):
            with patch("docsgpt.api.audit.AuthEventsRepository", return_value=repo):
                record_event(MagicMock(), "agent.created", actor="u1", name=None, id="a1")
        assert repo.insert.call_args.kwargs["metadata"] == {"id": "a1"}

    def test_insert_failure_never_raises(self, app):
        """An audit write must not be able to fail the action it records."""
        conn = Mock()
        conn.begin_nested.side_effect = RuntimeError("boom")
        with app.test_request_context("/api/anything"):
            record_event(conn, "source.deleted", actor="u1")

    def test_runs_in_a_savepoint(self, app):
        """A poisoned audit insert must roll back alone, not the action."""
        repo = Mock()
        conn = MagicMock()
        with app.test_request_context("/api/anything"):
            with patch("docsgpt.api.audit.AuthEventsRepository", return_value=repo):
                record_event(conn, "agent.deleted", actor="u1")
        conn.begin_nested.assert_called_once()

    def test_works_without_a_request_context(self, app):
        """Celery tasks have no request; the row still records."""
        repo = Mock()
        with patch("docsgpt.api.audit.AuthEventsRepository", return_value=repo):
            record_event(MagicMock(), "source.created", actor="u1")
        kwargs = repo.insert.call_args.kwargs
        assert kwargs["ip"] is None and kwargs["user_agent"] is None

    def test_anonymous_actor_falls_back(self, app):
        repo = Mock()
        with app.test_request_context("/api/anything"):
            with patch("docsgpt.api.audit.AuthEventsRepository", return_value=repo):
                record_event(MagicMock(), "agent.created", actor=None)
        assert repo.insert.call_args.kwargs["actor_id"] == "unknown"


@pytest.mark.unit
class TestCategories:
    @pytest.mark.parametrize(
        "event,expected",
        [
            ("oidc_login", "identity"),
            ("oidc_login_denied", "identity"),
            ("pat_created", "identity"),
            ("scim_created", "identity"),
            ("role_granted", "access"),
            ("admin_user_deactivated", "access"),
            ("team.member_add", "access"),
            ("quota_policy_set", "config"),
            ("source.deleted", "data"),
            ("agent.created", "data"),
            ("conversation.deleted", "data"),
        ],
    )
    def test_known_events(self, event, expected):
        assert category_for(event) == expected

    def test_unknown_event_is_other(self):
        assert category_for("something_new") == "other"

    @pytest.mark.parametrize(
        "event,expected",
        [("device.run_command", "device"), ("guardrail.input", "safety")],
    )
    def test_merged_feed_namespaces(self, event, expected):
        assert category_for(event) == expected

    def test_every_produced_category_is_declared(self):
        assert "other" in ACTIVITY_CATEGORIES
        for event in (
            "oidc_login",
            "role_granted",
            "quota_policy_set",
            "source.deleted",
            "device.run_command",
            "guardrail.input",
            "mystery",
        ):
            assert category_for(event) in ACTIVITY_CATEGORIES
