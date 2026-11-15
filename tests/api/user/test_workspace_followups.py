"""Routes that act within one workspace: schedule stats, delete all chats, Now's ingests, and models on a team agent.

A team's agent is owned by the team's principal and its schedules by the members who set them, so the stats of
a team agent's schedules cover every member's for those who manage them. "Delete all conversations" deletes the
caller's chats of the workspace the request names. A new upload's Activity marker shows in the workspace the
upload runs in. A team agent runs with the team's models only, so a person's custom model is refused at save.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from flask import Flask, request
from sqlalchemy import text

from docsgpt.activity.now import build_now
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.schedule_runs import ScheduleRunsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER, Workspace
from docsgpt.workspaces.principal import principal_id

OWNER, ADMIN, EDITOR, VIEWER, STRANGER = "fu-alice", "fu-adam", "fu-eddie", "fu-vera", "fu-stan"

_DB_MODULES = (
    "docsgpt.api.user.agents.routes",
    "docsgpt.api.user.agents.sharing",
    "docsgpt.api.user.agents.webhooks",
    "docsgpt.api.user.workflows.routes",
    "docsgpt.api.user.folder_knowledge",
    "docsgpt.api.user.base",
    "docsgpt.api.user.schedules.routes",
    "docsgpt.api.user.conversations.routes",
)


@contextmanager
def _patch_db(conn):
    import importlib

    @contextmanager
    def _yield():
        yield conn

    with ExitStack() as stack:
        for mod_name in _DB_MODULES:
            mod = importlib.import_module(mod_name)
            for attr in ("db_session", "db_readonly"):
                if hasattr(mod, attr):
                    stack.enter_context(patch(f"{mod_name}.{attr}", _yield))
        yield


def _call(conn, resource_cls, method, path, user, *, json=None, args=(), team=None, query=None):
    kwargs = {"method": method.upper(), "query_string": query or {}}
    if json is not None:
        kwargs["json"] = json
    if team is not None:
        kwargs["headers"] = {WORKSPACE_HEADER: team}
    with _patch_db(conn), Flask(__name__).test_request_context(path, **kwargs):
        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method.lower())(*args)


def _status(resp) -> int:
    return resp[1] if isinstance(resp, tuple) else resp.status_code


def _json(resp):
    return resp[0] if isinstance(resp, tuple) else resp.get_json()


def _team(conn) -> tuple[str, str]:
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", OWNER)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, OWNER, role="team_admin")
    for user, role in ((ADMIN, "team_admin"), (EDITOR, "team_editor"), (VIEWER, "team_viewer")):
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- schedule stats


def _schedule_with_run(conn, user, agent_id, *, status="failed", tokens=10) -> str:
    schedule = SchedulesRepository(conn).create(
        user_id=user, agent_id=agent_id, trigger_type="recurring", instruction="hi", cron="0 * * * *",
        next_run_at=_now() + timedelta(hours=1),
    )
    runs = ScheduleRunsRepository(conn)
    run = runs.record_pending(str(schedule["id"]), user, agent_id, _now() - timedelta(hours=1))
    runs.update(str(run["id"]), {"status": status, "prompt_tokens": tokens, "generated_tokens": 0})
    return str(schedule["id"])


def _stats(conn, user, agent_id):
    from docsgpt.api.user.schedules.routes import AgentScheduleStats

    return _call(conn, AgentScheduleStats, "get", f"/api/agents/{agent_id}/schedules/stats", user, args=(agent_id,))


class TestScheduleStatsOnATeamAgent:
    def test_an_editor_sees_every_members_runs(self, pg_conn):
        _, principal = _team(pg_conn)
        agent_id = str(AgentsRepository(pg_conn).create(principal, "Bot", "published", agent_type="classic")["id"])
        _schedule_with_run(pg_conn, ADMIN, agent_id, status="failed", tokens=10)
        _schedule_with_run(pg_conn, EDITOR, agent_id, status="success", tokens=5)

        body = _json(_stats(pg_conn, EDITOR, agent_id))

        assert body["runs"] == 2
        assert body["failed"] == 1
        assert body["tokens"] == 15

    def test_a_viewer_gets_no_stats(self, pg_conn):
        _, principal = _team(pg_conn)
        agent_id = str(AgentsRepository(pg_conn).create(principal, "Bot", "published", agent_type="classic")["id"])
        _schedule_with_run(pg_conn, ADMIN, agent_id)
        assert _status(_stats(pg_conn, VIEWER, agent_id)) == 403

    def test_a_personal_agent_counts_its_owners_schedules_only(self, pg_conn):
        agent_id = str(AgentsRepository(pg_conn).create(OWNER, "Mine", "published", agent_type="classic")["id"])
        _schedule_with_run(pg_conn, OWNER, agent_id, tokens=3)
        _schedule_with_run(pg_conn, STRANGER, agent_id, tokens=100)

        body = _json(_stats(pg_conn, OWNER, agent_id))

        assert body["runs"] == 1
        assert body["tokens"] == 3

    def test_the_repository_counts_every_setter_when_asked(self, pg_conn):
        _, principal = _team(pg_conn)
        agent_id = str(AgentsRepository(pg_conn).create(principal, "Bot", "published", agent_type="classic")["id"])
        _schedule_with_run(pg_conn, ADMIN, agent_id)
        _schedule_with_run(pg_conn, EDITOR, agent_id)
        repo = ScheduleRunsRepository(pg_conn)
        assert repo.stats_for_agent(agent_id, None)["runs"] == 2
        assert repo.stats_for_agent(agent_id, EDITOR)["runs"] == 1


# --------------------------------------------------------------------------- delete all conversations


def _chat(conn, user, team_id=None) -> str:
    return str(ConversationsRepository(conn).create(user, "Chat", team_id=team_id, visibility="listed")["id"])


def _delete_all(conn, user, team=None):
    from docsgpt.api.user.conversations.routes import DeleteAllConversations

    return _call(conn, DeleteAllConversations, "get", "/api/delete_all_conversations", user, team=team)


def _exists(conn, cid) -> bool:
    return bool(conn.execute(text("SELECT 1 FROM conversations WHERE id = CAST(:id AS uuid)"), {"id": cid}).fetchone())


class TestDeleteAllIsPerWorkspace:
    def test_no_header_deletes_personal_chats_only(self, pg_conn):
        tid, _ = _team(pg_conn)
        mine, ours = _chat(pg_conn, VIEWER), _chat(pg_conn, VIEWER, tid)

        resp = _delete_all(pg_conn, VIEWER)

        assert _status(resp) == 200
        assert _json(resp) == {"success": True}
        assert not _exists(pg_conn, mine)
        assert _exists(pg_conn, ours)

    def test_a_team_header_deletes_the_callers_team_chats_only(self, pg_conn):
        tid, _ = _team(pg_conn)
        mine, ours, theirs = _chat(pg_conn, VIEWER), _chat(pg_conn, VIEWER, tid), _chat(pg_conn, EDITOR, tid)

        resp = _delete_all(pg_conn, VIEWER, team=tid)

        assert _status(resp) == 200
        assert _json(resp) == {"success": True}
        assert _exists(pg_conn, mine)
        assert not _exists(pg_conn, ours)
        assert _exists(pg_conn, theirs)

    def test_a_team_the_caller_is_not_in_deletes_nothing(self, pg_conn):
        tid, _ = _team(pg_conn)
        TeamMembersRepository(pg_conn).remove_member(tid, VIEWER)
        mine, ours = _chat(pg_conn, VIEWER), _chat(pg_conn, VIEWER, tid)

        resp = _delete_all(pg_conn, VIEWER, team=tid)

        assert _status(resp) == 404
        assert _exists(pg_conn, mine)
        assert _exists(pg_conn, ours)


# --------------------------------------------------------------------------- Now: a new upload's marker


def _ws(tid, role="viewer"):
    return Workspace(kind="team", team_id=tid, owner_id=principal_id(tid), role=role)


def _upload_marker(team_id=..., source_id=None):
    marker = {
        "kind": "ingest", "id": "ingest:x", "source_id": source_id or str(uuid.uuid4()), "name": "handbook.pdf",
        "operation": "upload", "started_at": _now().timestamp(), "expires_at": _now().timestamp() + 600,
    }
    if team_id is not ...:
        marker["team_id"] = team_id
    return marker


def _ingests(now):
    return [item["source_id"] for item in now["running"] if item["kind"] == "ingest"]


class TestNowPlacesANewUpload:
    def test_a_team_upload_shows_in_that_team_only(self, pg_conn, monkeypatch):
        tid, _ = _team(pg_conn)
        other, _ = _team(pg_conn)
        marker = _upload_marker(tid)
        monkeypatch.setattr("docsgpt.activity.now.list_runs", lambda user: [marker] if user == EDITOR else [])

        assert _ingests(build_now(pg_conn, EDITOR, workspace=_ws(tid, "editor"))) == [marker["source_id"]]
        assert _ingests(build_now(pg_conn, EDITOR)) == []
        assert _ingests(build_now(pg_conn, EDITOR, workspace=_ws(other, "editor"))) == []

    def test_a_personal_upload_shows_in_personal_only(self, pg_conn, monkeypatch):
        tid, _ = _team(pg_conn)
        marker = _upload_marker(None)
        monkeypatch.setattr("docsgpt.activity.now.list_runs", lambda user: [marker] if user == EDITOR else [])

        assert _ingests(build_now(pg_conn, EDITOR)) == [marker["source_id"]]
        assert _ingests(build_now(pg_conn, EDITOR, workspace=_ws(tid, "editor"))) == []

    def test_an_old_marker_without_the_field_counts_as_personal(self, pg_conn, monkeypatch):
        tid, _ = _team(pg_conn)
        marker = _upload_marker()
        monkeypatch.setattr("docsgpt.activity.now.list_runs", lambda user: [marker] if user == EDITOR else [])

        assert _ingests(build_now(pg_conn, EDITOR)) == [marker["source_id"]]
        assert _ingests(build_now(pg_conn, EDITOR, workspace=_ws(tid, "editor"))) == []


# --------------------------------------------------------------------------- custom models on a team agent


def _custom_model(conn, user) -> str:
    return str(UserCustomModelsRepository(conn).create(user, "llama-3", "My Llama", "https://m.example/v1", "sk")["id"])


def _create(conn, user, team, **body):
    from docsgpt.api.user.agents.routes import CreateAgent

    payload = {"name": "Team bot", "description": "d", "status": "draft", "agent_type": "classic", **body}
    return _call(conn, CreateAgent, "post", "/api/create_agent", user, json=payload, team=team)


def _update(conn, user, agent_id, **body):
    from docsgpt.api.user.agents.routes import UpdateAgent

    return _call(conn, UpdateAgent, "put", f"/api/update_agent/{agent_id}", user, json=body, args=(agent_id,))


def _graph(model_id):
    cfg = {"agent_type": "classic", "system_prompt": "s", "tools": [], "sources": [], "model_id": model_id}
    return {
        "nodes": [
            {"id": "start1", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "a1", "type": "agent", "title": "A", "position": {"x": 50, "y": 0}, "data": {"config": cfg}},
            {"id": "end1", "type": "end", "position": {"x": 100, "y": 0}, "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start1", "target": "a1"},
            {"id": "e2", "source": "a1", "target": "end1"},
        ],
    }


CODE = "custom_model_personal_only"


class TestCustomModelsOnATeamAgent:
    def test_the_callers_custom_default_model_is_refused(self, pg_conn):
        tid, principal = _team(pg_conn)
        resp = _create(pg_conn, EDITOR, tid, default_model_id=_custom_model(pg_conn, EDITOR))
        assert _status(resp) == 400, _json(resp)
        assert _json(resp)["error"] == CODE
        assert AgentsRepository(pg_conn).list_for_user(principal) == []

    def test_someone_elses_custom_model_in_models_is_refused(self, pg_conn):
        tid, _ = _team(pg_conn)
        resp = _create(pg_conn, EDITOR, tid, models=["gpt-4o", _custom_model(pg_conn, ADMIN)])
        assert _status(resp) == 400
        assert _json(resp)["error"] == CODE

    def test_a_custom_model_on_an_inline_graph_node_is_refused(self, pg_conn):
        tid, principal = _team(pg_conn)
        resp = _create(pg_conn, EDITOR, tid, agent_type="workflow",
                       workflow_graph=_graph(_custom_model(pg_conn, EDITOR)))
        assert _status(resp) == 400, _json(resp)
        assert _json(resp)["error"] == CODE
        assert WorkflowsRepository(pg_conn).list_for_user(principal) == []

    def test_an_update_naming_a_custom_model_is_refused(self, pg_conn):
        _, principal = _team(pg_conn)
        agent_id = str(AgentsRepository(pg_conn).create(principal, "Bot", "draft", agent_type="classic")["id"])
        resp = _update(pg_conn, EDITOR, agent_id, default_model_id=_custom_model(pg_conn, EDITOR))
        assert _status(resp) == 400, _json(resp)
        assert _json(resp)["error"] == CODE
        assert not AgentsRepository(pg_conn).get_by_id(agent_id).get("default_model_id")

    def test_a_team_workflow_node_naming_a_custom_model_is_refused(self, pg_conn):
        from docsgpt.api.user.workflows.routes import WorkflowList

        tid, principal = _team(pg_conn)
        body = {"name": "WF", "description": "d", **_graph(_custom_model(pg_conn, OWNER))}
        resp = _call(pg_conn, WorkflowList, "post", "/api/workflows", EDITOR, json=body, team=tid)
        assert _status(resp) == 400, _json(resp)
        assert _json(resp)["code"] == CODE
        assert WorkflowsRepository(pg_conn).list_for_user(principal) == []

    def test_a_team_workflow_save_naming_a_custom_model_is_refused(self, pg_conn):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        _, principal = _team(pg_conn)
        wf = str(WorkflowsRepository(pg_conn).create(principal, "wf")["id"])
        body = {"name": "WF", "description": "d", **_graph(_custom_model(pg_conn, EDITOR))}
        resp = _call(pg_conn, WorkflowDetail, "put", f"/api/workflows/{wf}", EDITOR, json=body, args=(wf,))
        assert _status(resp) == 400, _json(resp)
        assert _json(resp)["code"] == CODE

    def test_a_personal_agent_keeps_its_owners_custom_model(self, pg_conn):
        model = _custom_model(pg_conn, EDITOR)
        resp = _create(pg_conn, EDITOR, None, default_model_id=model, models=[model])
        assert _status(resp) == 201, _json(resp)
        assert AgentsRepository(pg_conn).get_by_id(_json(resp)["id"])["default_model_id"] == model


# --------------------------------------------------------------------------- adopting a template into a team


def _template(conn, *, default_model_id=None, models=None, node_model_id=None) -> str:
    from docsgpt.storage.db.repositories.users import UsersRepository
    from docsgpt.storage.db.repositories.workflow_nodes import WorkflowNodesRepository

    UsersRepository(conn).upsert("__system__")
    extra: dict = {}
    if node_model_id is not None:
        wf = str(WorkflowsRepository(conn).create("__system__", "tpl-wf")["id"])
        WorkflowNodesRepository(conn).create(
            wf, 1, "a1", "agent", config={"agent_type": "classic", "model_id": node_model_id},
        )
        extra = {"agent_type": "workflow", "workflow_id": wf}
    else:
        extra = {"agent_type": "classic"}
    if default_model_id is not None:
        extra["default_model_id"] = default_model_id
    if models is not None:
        extra["models"] = models
    return str(AgentsRepository(conn).create("__system__", "Template", "published", **extra)["id"])


def _adopt(conn, user, template, team=None):
    from docsgpt.api.user.agents.routes import AdoptAgent

    resp = _call(conn, AdoptAgent, "post", "/api/adopt_agent", user, team=team, query={"id": template})
    assert _status(resp) == 200, _json(resp)
    return AgentsRepository(conn).get_by_id(_json(resp)["agent"]["id"])


def _node_model(conn, workflow_id):
    from docsgpt.storage.db.repositories.workflow_nodes import WorkflowNodesRepository

    nodes = WorkflowNodesRepository(conn).find_by_version(str(workflow_id), 1)
    cfg = next(n for n in nodes if n["node_type"] == "agent")["config"]
    return cfg.get("model_id")


class TestAdoptingATemplateIntoATeam:
    def test_the_adopters_custom_default_model_is_dropped(self, pg_conn):
        tid, principal = _team(pg_conn)
        model = _custom_model(pg_conn, EDITOR)
        row = _adopt(pg_conn, EDITOR, _template(pg_conn, default_model_id=model), tid)
        assert row["user_id"] == principal
        assert not row.get("default_model_id")

    def test_custom_models_in_models_are_dropped_and_the_rest_kept(self, pg_conn):
        tid, _ = _team(pg_conn)
        model = _custom_model(pg_conn, ADMIN)
        row = _adopt(pg_conn, ADMIN, _template(pg_conn, models=["gpt-4o", model], default_model_id="gpt-4o"), tid)
        assert row["models"] == ["gpt-4o"]
        assert row["default_model_id"] == "gpt-4o"

    def test_a_custom_model_on_a_graph_node_is_dropped(self, pg_conn):
        tid, _ = _team(pg_conn)
        model = _custom_model(pg_conn, EDITOR)
        row = _adopt(pg_conn, EDITOR, _template(pg_conn, node_model_id=model), tid)
        assert _node_model(pg_conn, row["workflow_id"]) is None

    def test_a_personal_adoption_keeps_the_adopters_own_custom_model(self, pg_conn):
        model = _custom_model(pg_conn, EDITOR)
        row = _adopt(pg_conn, EDITOR, _template(pg_conn, default_model_id=model, models=[model], node_model_id=model))
        assert row["default_model_id"] == model
        assert row["models"] == [model]
        assert _node_model(pg_conn, row["workflow_id"]) == model
