"""Tests for the Activity REST routes."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.pending_tool_state import PendingToolStateRepository


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.activity.routes.db_readonly", _yield):
        yield


def _message(conn, status: str, user_id: str = "u1") -> str:
    repo = ConversationsRepository(conn)
    conv = repo.create(user_id, "chat")
    return str(repo.reserve_message(str(conv["id"]), prompt="q", placeholder_response="", status=status)["id"])


def _call(app, path, method, view, *args, user="u1"):
    with app.test_request_context(path, method=method):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        return view(*args)


class TestNow:
    def test_unauthorized(self, app):
        from docsgpt.api.user.activity.routes import ActivityNow

        assert _call(app, "/api/activity/now", "GET", ActivityNow().get, user=None).status_code == 401

    def test_returns_the_snapshot(self, app, pg_conn):
        from docsgpt.api.user.activity.routes import ActivityNow

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.activity.routes.build_now", return_value={"running": [], "stats": {}}
        ) as build:
            resp = _call(app, "/api/activity/now", "GET", ActivityNow().get)
        assert resp.status_code == 200
        assert resp.get_json() == {"running": [], "stats": {}}
        build.assert_called_once_with(pg_conn, "u1")


class TestPlanned:
    def test_unauthorized(self, app):
        from docsgpt.api.user.activity.routes import ActivityPlanned

        assert _call(app, "/api/activity/planned", "GET", ActivityPlanned().get, user=None).status_code == 401

    def test_rejects_a_bad_window(self, app):
        from docsgpt.api.user.activity.routes import ActivityPlanned

        resp = _call(app, "/api/activity/planned?from=2030-03-11&to=2030-03-04", "GET", ActivityPlanned().get)
        assert resp.status_code == 400

    def test_returns_the_window(self, app, pg_conn):
        from docsgpt.api.user.activity.routes import ActivityPlanned

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.activity.routes.build_planned", return_value={"events": []}
        ) as build:
            resp = _call(
                app, "/api/activity/planned?from=2030-03-04T00:00:00Z&to=2030-03-11T00:00:00Z",
                "GET", ActivityPlanned().get,
            )
        assert resp.status_code == 200
        assert build.call_args.args[1] == "u1"

    def test_passes_the_viewers_time_zone(self, app, pg_conn):
        from docsgpt.api.user.activity.routes import ActivityPlanned

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.activity.routes.build_planned", return_value={"events": []}
        ) as build:
            _call(
                app, "/api/activity/planned?from=2030-03-04T00:00:00Z&to=2030-03-11T00:00:00Z&tz=Europe/Warsaw",
                "GET", ActivityPlanned().get,
            )
        assert build.call_args.kwargs["tz"] == "Europe/Warsaw"

    def test_rejects_an_unknown_time_zone(self, app, pg_conn):
        from docsgpt.api.user.activity.routes import ActivityPlanned

        with _patch_db(pg_conn):
            resp = _call(
                app, "/api/activity/planned?from=2030-03-04T00:00:00Z&to=2030-03-11T00:00:00Z&tz=Mars/Olympus",
                "GET", ActivityPlanned().get,
            )
        assert resp.status_code == 400


class TestHistory:
    def test_unauthorized(self, app):
        from docsgpt.api.user.activity.routes import ActivityHistory

        assert _call(app, "/api/activity/history", "GET", ActivityHistory().get, user=None).status_code == 401

    def test_rejects_an_unknown_kind(self, app, pg_conn):
        from docsgpt.api.user.activity.routes import ActivityHistory

        with _patch_db(pg_conn):
            resp = _call(app, "/api/activity/history?kind=chat", "GET", ActivityHistory().get)
        assert resp.status_code == 400

    def test_passes_the_filters(self, app, pg_conn):
        from docsgpt.api.user.activity.routes import ActivityHistory

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.activity.routes.list_history", return_value={"runs": [], "has_more": False}
        ) as listing:
            resp = _call(
                app, "/api/activity/history?kind=webhook&status=failed&q=desk&limit=20&offset=40",
                "GET", ActivityHistory().get,
            )
        assert resp.status_code == 200
        kwargs = listing.call_args.kwargs
        assert (kwargs["kind"], kwargs["status"], kwargs["query"]) == ("webhook", "failed", "desk")
        assert (kwargs["limit"], kwargs["offset"]) == (20, 40)


class TestCancel:
    def test_unauthorized(self, app):
        from docsgpt.api.user.activity.routes import MessageCancel

        assert _call(app, "/api/messages/x/cancel", "POST", MessageCancel().post, "x", user=None).status_code == 401

    def test_stops_a_running_answer(self, app, pg_conn):
        from docsgpt.api.user.activity.routes import MessageCancel

        message_id = _message(pg_conn, "streaming")
        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.activity.routes.request_stop", return_value=True
        ) as stop:
            resp = _call(app, f"/api/messages/{message_id}/cancel", "POST", MessageCancel().post, message_id)
        assert resp.status_code == 202
        stop.assert_called_once_with(message_id)

    def test_someone_elses_answer_is_not_found(self, app, pg_conn):
        from docsgpt.api.user.activity.routes import MessageCancel

        message_id = _message(pg_conn, "streaming", user_id="u2")
        with _patch_db(pg_conn), patch("docsgpt.api.user.activity.routes.request_stop") as stop:
            resp = _call(app, f"/api/messages/{message_id}/cancel", "POST", MessageCancel().post, message_id)
        assert resp.status_code == 404
        stop.assert_not_called()

    def test_a_finished_answer_conflicts(self, app, pg_conn):
        from docsgpt.api.user.activity.routes import MessageCancel

        message_id = _message(pg_conn, "complete")
        with _patch_db(pg_conn), patch("docsgpt.api.user.activity.routes.request_stop") as stop:
            resp = _call(app, f"/api/messages/{message_id}/cancel", "POST", MessageCancel().post, message_id)
        assert resp.status_code == 409
        stop.assert_not_called()

    def _pause(self, conn, message_id: str) -> str:
        conv = str(conn.execute(
            text("SELECT conversation_id FROM conversation_messages WHERE id = CAST(:id AS uuid)"),
            {"id": message_id},
        ).scalar())
        repo = PendingToolStateRepository(conn)
        repo.save_state(
            conv, "u1",
            messages=[], tools_dict={}, tool_schemas=[], agent_config={"reserved_message_id": message_id},
            pending_tool_calls=[{"call_id": "c1", "tool_name": "send_email", "pause_type": "awaiting_approval"}],
        )
        return conv

    def test_an_answer_paused_for_approval_conflicts(self, app, pg_conn):
        # Its stream has ended: nothing would clear the flag, and the resumed
        # answer (same message id) would stop on it after the user approves.
        from docsgpt.api.user.activity.routes import MessageCancel

        message_id = _message(pg_conn, "streaming")
        self._pause(pg_conn, message_id)
        with _patch_db(pg_conn), patch("docsgpt.api.user.activity.routes.request_stop") as stop:
            resp = _call(app, f"/api/messages/{message_id}/cancel", "POST", MessageCancel().post, message_id)
        assert resp.status_code == 409
        stop.assert_not_called()

    def test_a_resuming_answer_can_be_stopped(self, app, pg_conn):
        from docsgpt.api.user.activity.routes import MessageCancel

        message_id = _message(pg_conn, "streaming")
        conv = self._pause(pg_conn, message_id)
        PendingToolStateRepository(pg_conn).mark_resuming(conv, "u1")
        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.activity.routes.request_stop", return_value=True
        ) as stop:
            resp = _call(app, f"/api/messages/{message_id}/cancel", "POST", MessageCancel().post, message_id)
        assert resp.status_code == 202
        stop.assert_called_once_with(message_id)

    def test_without_redis_it_is_unavailable(self, app, pg_conn):
        from docsgpt.api.user.activity.routes import MessageCancel

        message_id = _message(pg_conn, "pending")
        with _patch_db(pg_conn), patch("docsgpt.api.user.activity.routes.request_stop", return_value=False):
            resp = _call(app, f"/api/messages/{message_id}/cancel", "POST", MessageCancel().post, message_id)
        assert resp.status_code == 503

    def test_rejects_a_bad_id(self, app):
        from docsgpt.api.user.activity.routes import MessageCancel

        assert _call(app, "/api/messages/nope/cancel", "POST", MessageCancel().post, "nope").status_code == 404
