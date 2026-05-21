"""Tests for the schedules REST API."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from application.storage.db.repositories.schedules import SchedulesRepository


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.schedules.routes.db_session", _yield,
    ), patch(
        "application.api.user.schedules.routes.db_readonly", _yield,
    ):
        yield


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_agent(conn, user_id: str = "u1") -> str:
    row = conn.execute(
        text(
            "INSERT INTO agents (user_id, name, status) "
            "VALUES (:u, 'a', 'draft') RETURNING id"
        ),
        {"u": user_id},
    ).fetchone()
    return str(row[0])


class TestCreateRecurring:
    def test_unauthorized(self, app):
        from application.api.user.schedules.routes import AgentSchedules

        with app.test_request_context(
            "/api/agents/x/schedules", method="POST", json={},
        ):
            from flask import request
            request.decoded_token = None
            resp = AgentSchedules().post("x")
        assert resp.status_code == 401

    def test_agent_not_found(self, app, pg_conn):
        from application.api.user.schedules.routes import AgentSchedules

        with _patch_db(pg_conn), app.test_request_context(
            "/api/agents/00000000-0000-0000-0000-000000000000/schedules",
            method="POST", json={"instruction": "x", "cron": "* * * * *"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = AgentSchedules().post(
                "00000000-0000-0000-0000-000000000000",
            )
        assert resp.status_code == 404

    def test_invalid_cron(self, app, pg_conn):
        from application.api.user.schedules.routes import AgentSchedules

        agent_id = _make_agent(pg_conn)
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/agents/{agent_id}/schedules",
            method="POST",
            json={"instruction": "x", "cron": "not a cron"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = AgentSchedules().post(agent_id)
        assert resp.status_code == 400

    def test_create_success(self, app, pg_conn):
        from application.api.user.schedules.routes import AgentSchedules

        agent_id = _make_agent(pg_conn)
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/agents/{agent_id}/schedules",
            method="POST",
            json={
                "instruction": "weekly digest",
                "cron": "0 9 * * 1",
                "timezone": "Europe/Warsaw",
                "tool_allowlist": [],
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = AgentSchedules().post(agent_id)
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["schedule"]["cron"] == "0 9 * * 1"
        assert body["schedule"]["timezone"] == "Europe/Warsaw"


class TestCreateOnce:
    def test_creates_once_with_run_at(self, app, pg_conn):
        from application.api.user.schedules.routes import AgentSchedules

        agent_id = _make_agent(pg_conn)
        run_at = (_now() + timedelta(hours=2)).isoformat().replace(
            "+00:00", "Z",
        )
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/agents/{agent_id}/schedules",
            method="POST",
            json={
                "instruction": "remind me",
                "trigger_type": "once",
                "run_at": run_at,
                "timezone": "UTC",
                "tool_allowlist": [],
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = AgentSchedules().post(agent_id)
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["schedule"]["trigger_type"] == "once"
        assert body["schedule"]["run_at"] is not None

    def test_once_requires_run_at(self, app, pg_conn):
        from application.api.user.schedules.routes import AgentSchedules

        agent_id = _make_agent(pg_conn)
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/agents/{agent_id}/schedules",
            method="POST",
            json={
                "instruction": "remind me",
                "trigger_type": "once",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = AgentSchedules().post(agent_id)
        assert resp.status_code == 400

    def test_once_rejects_past_run_at(self, app, pg_conn):
        from application.api.user.schedules.routes import AgentSchedules

        agent_id = _make_agent(pg_conn)
        past = (_now() - timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z",
        )
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/agents/{agent_id}/schedules",
            method="POST",
            json={
                "instruction": "x",
                "trigger_type": "once",
                "run_at": past,
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = AgentSchedules().post(agent_id)
        assert resp.status_code == 400

    def test_recurring_default_when_trigger_type_omitted(self, app, pg_conn):
        """Backwards compat: a payload with cron but no trigger_type still works."""
        from application.api.user.schedules.routes import AgentSchedules

        agent_id = _make_agent(pg_conn)
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/agents/{agent_id}/schedules",
            method="POST",
            json={
                "instruction": "hourly",
                "cron": "0 * * * *",
                "timezone": "UTC",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = AgentSchedules().post(agent_id)
        assert resp.status_code == 201
        assert resp.get_json()["schedule"]["trigger_type"] == "recurring"


class TestListForAgent:
    def test_list(self, app, pg_conn):
        from application.api.user.schedules.routes import AgentSchedules

        agent_id = _make_agent(pg_conn)
        SchedulesRepository(pg_conn).create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() + timedelta(hours=1),
        )
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/agents/{agent_id}/schedules", method="GET",
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = AgentSchedules().get(agent_id)
        assert resp.status_code == 200
        assert len(resp.get_json()["schedules"]) == 1


class TestGetEditPatchDelete:
    def _make(self, conn, **kwargs):
        return SchedulesRepository(conn).create(**kwargs)

    def test_get_owner_scoped(self, app, pg_conn):
        from application.api.user.schedules.routes import ScheduleResource

        agent_id = _make_agent(pg_conn)
        s = self._make(
            pg_conn,
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() + timedelta(hours=1),
        )
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/schedules/{s['id']}", method="GET",
        ):
            from flask import request
            request.decoded_token = {"sub": "u2"}
            resp = ScheduleResource().get(str(s["id"]))
        assert resp.status_code == 404

    def test_pause_then_resume(self, app, pg_conn):
        from application.api.user.schedules.routes import ScheduleResource

        agent_id = _make_agent(pg_conn)
        s = self._make(
            pg_conn,
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() + timedelta(hours=1),
        )
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/schedules/{s['id']}",
            method="PATCH",
            json={"action": "pause"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = ScheduleResource().patch(str(s["id"]))
        assert resp.status_code == 200
        assert resp.get_json()["schedule"]["status"] == "paused"
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/schedules/{s['id']}",
            method="PATCH",
            json={"action": "resume"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = ScheduleResource().patch(str(s["id"]))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["schedule"]["status"] == "active"
        assert body["schedule"]["next_run_at"] is not None

    def test_delete_owner_scoped(self, app, pg_conn):
        from application.api.user.schedules.routes import ScheduleResource

        agent_id = _make_agent(pg_conn)
        s = self._make(
            pg_conn,
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() + timedelta(hours=1),
        )
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/schedules/{s['id']}", method="DELETE",
        ):
            from flask import request
            request.decoded_token = {"sub": "u2"}
            resp = ScheduleResource().delete(str(s["id"]))
        assert resp.status_code == 404
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/schedules/{s['id']}", method="DELETE",
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = ScheduleResource().delete(str(s["id"]))
        assert resp.status_code == 200

    def test_put_invalid_cron(self, app, pg_conn):
        from application.api.user.schedules.routes import ScheduleResource

        agent_id = _make_agent(pg_conn)
        s = self._make(
            pg_conn,
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() + timedelta(hours=1),
        )
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/schedules/{s['id']}",
            method="PUT", json={"cron": "bad"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = ScheduleResource().put(str(s["id"]))
        assert resp.status_code == 400


class TestRunNow:
    def test_runs_returns_202(self, app, pg_conn):
        from application.api.user.schedules.routes import ScheduleRunNow

        agent_id = _make_agent(pg_conn)
        s = SchedulesRepository(pg_conn).create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() + timedelta(hours=1),
        )
        with _patch_db(pg_conn), patch(
            "application.api.user.tasks.execute_scheduled_run",
            type("T", (), {"apply_async": staticmethod(lambda **k: None)}),
        ), app.test_request_context(
            f"/api/schedules/{s['id']}/run", method="POST",
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = ScheduleRunNow().post(str(s["id"]))
        assert resp.status_code == 202

    def test_second_run_blocked_by_active(self, app, pg_conn):
        """Run-Now serializes via FOR UPDATE + has_active_run; second 409s."""
        from application.api.user.schedules.routes import ScheduleRunNow

        agent_id = _make_agent(pg_conn)
        s = SchedulesRepository(pg_conn).create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="0 9 * * 1",
            next_run_at=_now() + timedelta(hours=1),
        )
        with _patch_db(pg_conn), patch(
            "application.api.user.tasks.execute_scheduled_run",
            type("T", (), {"apply_async": staticmethod(lambda **k: None)}),
        ), app.test_request_context(
            f"/api/schedules/{s['id']}/run", method="POST",
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            first = ScheduleRunNow().post(str(s["id"]))
            assert first.status_code == 202
            second = ScheduleRunNow().post(str(s["id"]))
            assert second.status_code == 409


class TestMinInterval:
    def test_create_rejects_below_min_interval(self, app, pg_conn):
        from application.api.user.schedules.routes import AgentSchedules

        agent_id = _make_agent(pg_conn)
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/agents/{agent_id}/schedules",
            method="POST",
            json={"instruction": "x", "cron": "* * * * *"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = AgentSchedules().post(agent_id)
        assert resp.status_code == 400
        assert "minimum interval" in resp.get_json()["message"]

    def test_put_rejects_below_min_interval(self, app, pg_conn):
        from application.api.user.schedules.routes import ScheduleResource

        agent_id = _make_agent(pg_conn)
        s = SchedulesRepository(pg_conn).create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="0 9 * * 1",
            next_run_at=_now() + timedelta(hours=1),
        )
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/schedules/{s['id']}", method="PUT",
            json={"cron": "*/5 * * * *"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = ScheduleResource().put(str(s["id"]))
        assert resp.status_code == 400
        assert "minimum interval" in resp.get_json()["message"]


class TestResumeOnceStale:
    def test_stale_run_at_returns_clear_409(self, app, pg_conn):
        from application.api.user.schedules.routes import ScheduleResource

        agent_id = _make_agent(pg_conn)
        s = SchedulesRepository(pg_conn).create(
            user_id="u1", agent_id=agent_id, trigger_type="once",
            instruction="i", run_at=_now() + timedelta(hours=1),
            next_run_at=_now() + timedelta(hours=1),
            status="paused",
        )
        pg_conn.execute(
            text(
                "UPDATE schedules SET run_at = now() - interval '1 day' "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": str(s["id"])},
        )
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/schedules/{s['id']}", method="PATCH",
            json={"action": "resume"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = ScheduleResource().patch(str(s["id"]))
        assert resp.status_code == 409
        assert "elapsed" in resp.get_json()["message"]

    def test_resume_accepts_new_run_at(self, app, pg_conn):
        from application.api.user.schedules.routes import ScheduleResource

        agent_id = _make_agent(pg_conn)
        s = SchedulesRepository(pg_conn).create(
            user_id="u1", agent_id=agent_id, trigger_type="once",
            instruction="i", run_at=_now() + timedelta(hours=1),
            next_run_at=_now() + timedelta(hours=1),
            status="paused",
        )
        pg_conn.execute(
            text(
                "UPDATE schedules SET run_at = now() - interval '1 day' "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": str(s["id"])},
        )
        new_run_at = (_now() + timedelta(hours=3)).isoformat()
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/schedules/{s['id']}", method="PATCH",
            json={"action": "resume", "run_at": new_run_at},
        ):
            from flask import request
            request.decoded_token = {"sub": "u1"}
            resp = ScheduleResource().patch(str(s["id"]))
        assert resp.status_code == 200
        body = resp.get_json()["schedule"]
        assert body["status"] == "active"


class TestRunList:
    def test_list_owner_scoped(self, app, pg_conn):
        from application.api.user.schedules.routes import ScheduleRunList

        agent_id = _make_agent(pg_conn)
        s = SchedulesRepository(pg_conn).create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() + timedelta(hours=1),
        )
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/schedules/{s['id']}/runs", method="GET",
        ):
            from flask import request
            request.decoded_token = {"sub": "u2"}
            resp = ScheduleRunList().get(str(s["id"]))
        assert resp.status_code == 404
