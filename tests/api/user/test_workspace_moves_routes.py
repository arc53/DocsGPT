"""``GET /api/workspaces`` and the Move routes ``POST /api/workspace_moves/plan`` and ``POST /api/workspace_moves``."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.api.pat import rules
from tests.workspaces.move_support import agent, body, owner_of, team


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    targets = [
        "docsgpt.api.user.workspaces.routes.db_session",
        "docsgpt.api.user.workspaces.routes.db_readonly",
        "docsgpt.workspaces.context.db_readonly",
    ]
    patches = [patch(t, _yield) for t in targets]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in reversed(patches):
            p.stop()


def _call(app, conn, resource, user, *, method="post", json=None, path="/api/x"):
    kwargs = {"method": method.upper()}
    if json is not None:
        kwargs["json"] = json
    with _patch_db(conn), app.test_request_context(path, **kwargs):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        response = getattr(resource(), method)()
    return response.status_code, response.get_json()


def _plan(app, conn, user, payload):
    from docsgpt.api.user.workspaces.routes import WorkspaceMovePlan

    return _call(app, conn, WorkspaceMovePlan, user, json=payload, path="/api/workspace_moves/plan")


def _apply(app, conn, user, payload):
    from docsgpt.api.user.workspaces.routes import WorkspaceMoves

    return _call(app, conn, WorkspaceMoves, user, json=payload, path="/api/workspace_moves")


class TestWorkspacesList:
    def test_personal_then_each_team_with_the_callers_role(self, app, pg_conn):
        from docsgpt.api.user.workspaces.routes import Workspaces

        tid, principal = team(pg_conn)
        team(pg_conn, owner="olga", name="Elsewhere", members=())
        status, out = _call(app, pg_conn, Workspaces, "eddie", method="get", path="/api/workspaces")
        assert status == 200
        personal, ops = out["workspaces"]
        assert personal == {"id": "personal", "kind": "personal", "name": "Personal"}
        assert ops["id"] == tid and ops["kind"] == "team" and ops["name"] == "Ops"
        assert ops["role"] == "editor" and ops["member_count"] == 4
        assert ops["slug"].startswith("ops-") and ops["principal_label"] == "Team Ops"
        _, out = _call(app, pg_conn, Workspaces, "alice", method="get", path="/api/workspaces")
        assert out["workspaces"][1]["role"] == "owner"

    def test_needs_a_caller(self, app, pg_conn):
        from docsgpt.api.user.workspaces.routes import Workspaces

        assert _call(app, pg_conn, Workspaces, None, method="get", path="/api/workspaces")[0] == 401


class TestMoveRoutes:
    def test_plan_then_apply(self, app, pg_conn):
        tid, principal = team(pg_conn)
        ag = agent(pg_conn, "eddie")
        status, out = _plan(app, pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert status == 200 and out["plan"]["items"][0]["id"] == ag
        status, out = _apply(app, pg_conn, "eddie", body(tid, [("agent", ag)], fingerprint=out["plan"]["fingerprint"]))
        assert status == 200 and out["success"] is True
        assert owner_of(pg_conn, "agent", ag) == principal

    def test_apply_needs_a_fingerprint(self, app, pg_conn):
        tid, _ = team(pg_conn)
        ag = agent(pg_conn, "eddie")
        status, out = _apply(app, pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert status == 400

    def test_a_stale_fingerprint_answers_409_with_a_fresh_plan(self, app, pg_conn):
        tid, _ = team(pg_conn)
        ag = agent(pg_conn, "eddie")
        status, out = _apply(app, pg_conn, "eddie", body(tid, [("agent", ag)], fingerprint="old"))
        assert status == 409 and out["error"] == "move_plan_changed"
        assert out["plan"]["items"][0]["id"] == ag
        assert owner_of(pg_conn, "agent", ag) == "eddie"

    def test_a_viewer_target_is_403_and_a_stranger_404(self, app, pg_conn):
        tid, _ = team(pg_conn)
        ag = agent(pg_conn, "vera")
        status, out = _plan(app, pg_conn, "vera", body(tid, [("agent", ag)]))
        assert (status, out["error"]) == (403, "workspace_role_required")
        status, out = _plan(app, pg_conn, "olga", body(tid, [("agent", agent(pg_conn, "olga"))]))
        assert (status, out["error"]) == (404, "workspace_not_found")

    def test_bad_body_is_400(self, app, pg_conn):
        assert _plan(app, pg_conn, "eddie", {"items": "nope"})[0] == 400

    def test_needs_a_caller(self, app, pg_conn):
        assert _plan(app, pg_conn, None, {})[0] == 401


class TestTokens:
    @staticmethod
    def _authorize(path, method, scopes):
        request = SimpleNamespace(url_rule=SimpleNamespace(rule=path), method=method)
        return rules.authorize(request, {"sub": "eddie", "scopes": scopes})

    @pytest.mark.parametrize("path", ["/api/workspace_moves/plan", "/api/workspace_moves"])
    def test_moves_are_closed_to_tokens(self, path):
        refusal = self._authorize(path, "POST", ["teams:read", "agents:write"])
        assert refusal is not None and refusal[1] == 403
        assert refusal[0]["error"] == "not_available_to_tokens"

    def test_workspace_list_needs_teams_read(self):
        assert self._authorize("/api/workspaces", "GET", ["teams:read"]) is None
        refusal = self._authorize("/api/workspaces", "GET", ["agents:read"])
        assert refusal is not None and refusal[1] == 403
