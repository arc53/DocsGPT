"""A tool signed in to a team's account never goes outside the team.

A team's owner-mode tool on a connection the team owns runs on that account, for every member. It can't be
shared with another team, and a team agent that uses one gets no API key (nor the widget on it), public link
or webhook, nor a share with another team: 409 ``team_connection_outside`` naming the tools. Publishing such an
agent still works, keyless, as for a borrowed tool. Adding one to an agent that already reaches outside is
refused the same way. A team source synced from a team connection is ordinary team knowledge and may go out,
and a member-mode tool runs on each person's own account, so it may too. Real repositories on ``pg_conn``.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.connectors.team import TEAM_CONNECTION_OUTSIDE
from docsgpt.security.encryption import encrypt_json
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from tests.api.user.agents.test_workspace_agents import (
    ADMIN,
    OWNER,
    _agent,
    _call,
    _json,
    _row,
    _source,
    _status,
    _team,
)


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def w(pg_conn):
    """Ops (alice owner, adam admin, eddie editor, vera viewer) with a GitHub account adam connected for it and
    a tool on it; Dev, a team adam is in too."""
    tid, principal = _team(pg_conn)
    cid = str(ConnectorSessionsRepository(pg_conn).create(
        principal, "github", connector_key="github", auth_kind="oauth",
        account_label=f"{uuid.uuid4().hex[:6]}@example.com", connected_by=ADMIN,
        encrypted_credentials=encrypt_json({"access_token": "t"}, principal),
    )["id"])
    tool_id = str(UserToolsRepository(pg_conn).create(
        principal, "github", custom_name="Ops GitHub", connection_id=cid, created_by=ADMIN,
    )["id"])
    dev = str(TeamsRepository(pg_conn).create("Dev", f"dev-{uuid.uuid4().hex[:6]}", "dora")["id"])
    TeamMembersRepository(pg_conn).add_member(dev, "dora", role="team_admin")
    TeamMembersRepository(pg_conn).add_member(dev, ADMIN, role="team_viewer")
    return {"ops": tid, "principal": principal, "connection": cid, "tool": tool_id, "dev": dev}


def _assert_refused(resp, w):
    assert _status(resp) == 409, _json(resp)
    body = _json(resp)
    assert body["success"] is False
    assert body["error"] == TEAM_CONNECTION_OUTSIDE
    assert body["tools"] == [{"id": w["tool"], "name": "Ops GitHub", "connector_name": "GitHub"}]
    assert "Ops GitHub" in body["message"]
    return body


def _member_tool(conn, principal) -> str:
    tool_id = str(UserToolsRepository(conn).create(
        principal, "github", custom_name="Each own GitHub", credential_mode="member", created_by=ADMIN,
    )["id"])
    conn.execute(text("UPDATE user_tools SET connector_key = 'github' WHERE id = CAST(:i AS uuid)"), {"i": tool_id})
    return tool_id


class TestPublishing:
    def test_no_public_link(self, app, pg_conn, w):
        from docsgpt.api.user.agents.sharing import ShareAgent

        aid = _agent(pg_conn, w["principal"], status="published", tools=[w["tool"]])
        resp = _call(app, pg_conn, ShareAgent, "put", "/api/share_agent", ADMIN, json={"id": aid, "shared": True})
        _assert_refused(resp, w)
        assert not _row(pg_conn, aid)["shared"]

    def test_no_webhook(self, app, pg_conn, w):
        from docsgpt.api.user.agents.webhooks import AgentWebhook

        aid = _agent(pg_conn, w["principal"], status="published", tools=[w["tool"]])
        _assert_refused(_call(app, pg_conn, AgentWebhook, "get", "/api/agent_webhook", ADMIN, query={"id": aid}), w)
        assert not _row(pg_conn, aid)["incoming_webhook_token"]

    def test_no_first_key(self, app, pg_conn, w):
        from docsgpt.api.user.agents.routes import RegenerateAgentKey

        aid = _agent(pg_conn, w["principal"], status="published", tools=[w["tool"]])
        _assert_refused(_call(app, pg_conn, RegenerateAgentKey, "post", f"/api/regenerate_agent_key/{aid}", ADMIN,
                              args=(aid,)), w)
        assert not _row(pg_conn, aid)["key"]

    def test_publishing_mints_no_key(self, app, pg_conn, w):
        from docsgpt.api.user.agents.routes import UpdateAgent

        aid = _agent(pg_conn, w["principal"], tools=[w["tool"]])
        resp = _call(app, pg_conn, UpdateAgent, "put", f"/api/update_agent/{aid}", ADMIN,
                     json={"status": "published", "chunks": 2, "retriever": "classic", "prompt_id": "default"},
                     args=(aid,))
        assert _status(resp) == 200, _json(resp)
        row = _row(pg_conn, aid)
        assert row["status"] == "published"
        assert not row["key"]

    def test_creating_it_published_mints_no_key(self, app, pg_conn, w):
        from tests.api.user.agents.test_workspace_agents import _PUBLISHED, _create

        resp = _create(app, pg_conn, ADMIN, w["ops"], tools=[w["tool"]], **_PUBLISHED)
        assert _status(resp) == 201, _json(resp)
        assert not _row(pg_conn, _json(resp)["id"])["key"]

    def test_cant_be_added_to_an_agent_with_a_key(self, app, pg_conn, w):
        from docsgpt.api.user.agents.routes import UpdateAgent

        aid = _agent(pg_conn, w["principal"], status="published", key=f"k-{uuid.uuid4().hex}", access_payer_id=ADMIN)
        resp = _call(app, pg_conn, UpdateAgent, "put", f"/api/update_agent/{aid}", ADMIN,
                     json={"tools": [w["tool"]]}, args=(aid,))
        _assert_refused(resp, w)
        assert not _row(pg_conn, aid)["tools"]

    def test_cant_be_added_to_an_agent_shared_with_another_team(self, app, pg_conn, w):
        from docsgpt.api.user.agents.routes import UpdateAgent

        aid = _agent(pg_conn, w["principal"], status="published")
        TeamItemSharesRepository(pg_conn).share(w["ops"], w["dev"], "agent", aid, ADMIN)
        resp = _call(app, pg_conn, UpdateAgent, "put", f"/api/update_agent/{aid}", ADMIN,
                     json={"tools": [w["tool"]]}, args=(aid,))
        _assert_refused(resp, w)

    def test_cant_be_added_to_a_workflow_node_whose_agent_has_a_key(self, app, pg_conn, w):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        from tests.api.user.test_resource_sponsors import _wf_body

        wid = str(WorkflowsRepository(pg_conn).create(w["principal"], "wf", created_by=ADMIN)["id"])
        _agent(pg_conn, w["principal"], agent_type="workflow", workflow_id=wid, status="published",
               key=f"k-{uuid.uuid4().hex}", access_payer_id=ADMIN)
        resp = _call(app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", ADMIN,
                     json=_wf_body(tool=w["tool"]), args=(wid,))
        _assert_refused(resp, w)

    def test_a_member_mode_tool_and_a_team_source_dont_hold_it_back(self, app, pg_conn, w):
        from docsgpt.api.user.agents.sharing import ShareAgent

        src = _source(pg_conn, w["principal"])
        pg_conn.execute(text("UPDATE sources SET type = 'connector:file', connection_id = CAST(:c AS uuid) "
                             "WHERE id = CAST(:i AS uuid)"), {"c": w["connection"], "i": src})
        aid = _agent(pg_conn, w["principal"], status="published", source_id=src,
                     tools=[_member_tool(pg_conn, w["principal"])])
        resp = _call(app, pg_conn, ShareAgent, "put", "/api/share_agent", ADMIN, json={"id": aid, "shared": True})
        assert _status(resp) == 200, _json(resp)

    def test_the_owner_is_refused_too(self, app, pg_conn, w):
        from docsgpt.api.user.agents.sharing import ShareAgent

        aid = _agent(pg_conn, w["principal"], status="published", tools=[w["tool"]])
        _assert_refused(_call(app, pg_conn, ShareAgent, "put", "/api/share_agent", OWNER,
                              json={"id": aid, "shared": True}), w)


class TestShareWithAnotherTeam:
    def _share(self, app, pg_conn, kind, item_id, into):
        from docsgpt.api.user.teams import outside

        with app.app_context():
            refusal, share = outside.share_team_item(pg_conn, ADMIN, into, kind, item_id, "viewer", None)
        return refusal, share

    def test_the_tool_cant_be_shared(self, app, pg_conn, w):
        refusal, share = self._share(app, pg_conn, "tool", w["tool"], w["dev"])
        assert share is None
        _assert_refused(refusal, w)
        assert TeamItemSharesRepository(pg_conn).get(w["dev"], "tool", w["tool"]) is None

    def test_an_agent_using_it_cant_be_shared(self, app, pg_conn, w):
        aid = _agent(pg_conn, w["principal"], tools=[w["tool"]])
        refusal, share = self._share(app, pg_conn, "agent", aid, w["dev"])
        assert share is None
        _assert_refused(refusal, w)

    def test_a_workflow_agent_using_it_on_a_node_cant_be_shared(self, app, pg_conn, w):
        from docsgpt.api.user.workflows.routes import _write_graph

        from tests.api.user.test_resource_sponsors import _wf_body

        wid = str(WorkflowsRepository(pg_conn).create(w["principal"], "wf", created_by=ADMIN)["id"])
        graph = _wf_body(tool=w["tool"])
        _write_graph(pg_conn, wid, 1, graph["nodes"], graph["edges"])
        aid = _agent(pg_conn, w["principal"], agent_type="workflow", workflow_id=wid)
        refusal, _ = self._share(app, pg_conn, "agent", aid, w["dev"])
        _assert_refused(refusal, w)

    def test_a_team_connector_source_can_be_shared(self, app, pg_conn, w):
        src = _source(pg_conn, w["principal"])
        pg_conn.execute(text("UPDATE sources SET type = 'connector:file', connection_id = CAST(:c AS uuid) "
                             "WHERE id = CAST(:i AS uuid)"), {"c": w["connection"], "i": src})
        refusal, share = self._share(app, pg_conn, "source", src, w["dev"])
        assert refusal is None
        assert share["created"]

    def test_a_member_mode_tool_can_be_shared(self, app, pg_conn, w):
        refusal, share = self._share(app, pg_conn, "tool", _member_tool(pg_conn, w["principal"]), w["dev"])
        assert refusal is None
        assert share["created"]


class TestShareDialog:
    def test_a_member_mode_tool_warns_that_it_runs_on_each_persons_account(self, pg_conn, w):
        from docsgpt.api.user.teams.outside import _warning_kind

        ra = SimpleNamespace(resource_type="tool", resource_id=_member_tool(pg_conn, w["principal"]))
        assert _warning_kind(pg_conn, ra) == "tool_member"
