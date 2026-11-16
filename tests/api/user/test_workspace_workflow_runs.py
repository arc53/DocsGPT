"""Workflow runs of a team's workflow close to someone who left the team, as their team chats do.

A run is owned by the person who started it, but what it read and produced is
the team's: after they leave, the run list, the run, its steps, its files and
its artifacts read as not found. Re-added, they see them again.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.api.pat.tokens import expand_scopes
from docsgpt.api.user.artifacts.authz import Principal, authorize_artifact, authorize_artifact_write
from docsgpt.api.user.workflow_runs.access import visible_run
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from docsgpt.workspaces.principal import principal_id


@pytest.fixture(scope="module")
def client():
    from docsgpt.app import app

    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def db(pg_conn, monkeypatch):
    @contextmanager
    def _use_conn():
        yield pg_conn

    monkeypatch.setattr("docsgpt.api.user.workflow_runs.routes.db_readonly", _use_conn)
    monkeypatch.setattr("docsgpt.api.user.artifacts.routes.db_readonly", _use_conn)
    return pg_conn


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    TeamMembersRepository(conn).add_member(tid, "alice", role="team_admin")
    TeamMembersRepository(conn).add_member(tid, "vera", role="team_editor")
    return tid, principal_id(tid)


def _workflow(conn, owner) -> str:
    return str(conn.execute(
        text("INSERT INTO workflows (user_id, name, created_by) VALUES (:u, 'wf', 'alice') RETURNING id"),
        {"u": owner},
    ).scalar())


def _run(conn, workflow_id, user="vera") -> str:
    return str(WorkflowRunsRepository(conn).create(workflow_id, user, "completed", inputs={"query": "q"})["id"])


def _artifact(conn, run_id, user="vera") -> dict:
    row = conn.execute(
        text(
            "INSERT INTO artifacts (user_id, workflow_run_id, kind, title) "
            "VALUES (:u, CAST(:r AS uuid), 'document', 'Doc') RETURNING *"
        ),
        {"u": user, "r": run_id},
    ).mappings().one()
    return dict(row)


def _list(client, user="vera"):
    claims = {"sub": user, "auth_method": "pat", "pat_id": "t1", "pat_name": "ci",
              "scopes": sorted(expand_scopes(["runs:read"])), "resource_filter": {}}
    with patch("docsgpt.app.handle_auth", return_value=claims):
        response = client.get("/api/workflow_runs")
    return [run["id"] for run in json.loads(response.data)["runs"]]


def _run_artifacts(client, run_id, user="vera"):
    with patch("docsgpt.app.handle_auth", return_value={"sub": user}):
        return client.get(f"/api/artifacts?workflow_run_id={run_id}")


class TestExMember:
    def test_a_team_workflows_runs_close_on_leaving_and_reopen_on_return(self, client, db):
        tid, principal = _team(db)
        team_run = _run(db, _workflow(db, principal))
        own_run = _run(db, _workflow(db, "vera"))
        artifact = _artifact(db, team_run)
        vera = Principal(user_id="vera")

        assert set(_list(client)) == {team_run, own_run}
        assert visible_run(db, team_run, "vera", None) is not None
        assert authorize_artifact(db, artifact, vera, {})

        TeamMembersRepository(db).remove_member(tid, "vera")

        assert _list(client) == [own_run]
        assert visible_run(db, team_run, "vera", None) is None
        assert visible_run(db, own_run, "vera", None) is not None
        assert not authorize_artifact(db, artifact, vera, {})
        assert not authorize_artifact_write(db, artifact, vera)

        TeamMembersRepository(db).add_member(tid, "vera")
        assert set(_list(client)) == {team_run, own_run}
        assert visible_run(db, team_run, "vera", None) is not None

    def test_an_ex_member_cannot_list_a_team_runs_artifacts(self, client, db):
        tid, principal = _team(db)
        team_run = _run(db, _workflow(db, principal))
        own_run = _run(db, _workflow(db, "vera"))
        _artifact(db, team_run)
        _artifact(db, own_run)

        listed = _run_artifacts(client, team_run)
        assert listed.status_code == 200
        assert len(json.loads(listed.data)["artifacts"]) == 1

        TeamMembersRepository(db).remove_member(tid, "vera")

        assert _run_artifacts(client, team_run).status_code == 403
        assert _run_artifacts(client, own_run).status_code == 200
