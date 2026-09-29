"""Who may sponsor a resource, and only with their explicit consent.

A team editor who attaches a resource the agent's owner can't use makes it
run with the editor's access for everyone who uses the agent. That takes
owning the resource or having edit access to it (plain use is not enough),
an explicit ``confirm_sponsor`` on the save, and never happens silently when
a previous sponsor loses access. Uses real repositories on ``pg_conn``.
"""

from __future__ import annotations

import uuid

import pytest
from flask import Flask

from docsgpt.api.user.resource_access import (
    CODE_CONFIRMATION_REQUIRED,
    CODE_NOT_ALLOWED,
    CODE_UNEXPECTED_CONFIRMATION,
    REASON_CANNOT_EDIT_HOLDER,
    REASON_CANNOT_EDIT_RESOURCE,
    active_sponsor,
    parse_confirmations,
    plan_sponsors,
    sponsor_details,
    sponsor_key,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from tests.api.user.test_resource_sponsors import (
    EDITOR,
    OTHER,
    OWNER,
    _agent,
    _call,
    _editor_resources,
    _put,
    _row,
    _status,
    _wf_body,
)

STRANGER = "sp-stranger"


@pytest.fixture
def app():
    return Flask(__name__)


def _body(resp) -> dict:
    return resp[0] if isinstance(resp, tuple) else resp.get_json()


def _other_team(conn, *members):
    """A second team, owned by OTHER, that the agent is not shared with."""
    team = TeamsRepository(conn).create("Elsewhere", f"e-{uuid.uuid4().hex[:8]}", OTHER)
    tid = str(team["id"])
    for member in (OTHER, *members):
        if not TeamMembersRepository(conn).is_member(member, tid):
            TeamMembersRepository(conn).add_member(tid, member)
    return tid


def _others_tool(conn, team_id, user, level):
    """OTHER's tool, shared with ``user`` in ``team_id`` at ``level``."""
    tool = str(UserToolsRepository(conn).create(OTHER, "api_tool")["id"])
    TeamResourceGrantsRepository(conn).grant(team_id, "tool", tool, OTHER, OTHER, access_level=level,
                                             target_user_id=user)
    return tool


def _others_source(conn, team_id, user, level):
    source = str(SourcesRepository(conn).create("others-src", user_id=OTHER)["id"])
    TeamResourceGrantsRepository(conn).grant(team_id, "source", source, OTHER, OTHER, access_level=level,
                                             target_user_id=user)
    return source


def _add_agent_editor(conn, team_id, agent_id, user):
    if not TeamMembersRepository(conn).is_member(user, team_id):
        TeamMembersRepository(conn).add_member(team_id, user)
    TeamResourceGrantsRepository(conn).grant(
        team_id, "agent", agent_id, OWNER, OWNER, access_level="editor", target_user_id=user
    )


# ---------------------------------------------------------------------------
# A: who may sponsor
# ---------------------------------------------------------------------------


class TestWhoMaySponsor:
    def test_use_only_share_cannot_sponsor(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        team = _other_team(pg_conn, EDITOR)
        source = _others_source(pg_conn, team, EDITOR, "viewer")
        tool = _others_tool(pg_conn, team, EDITOR, "viewer")
        resp = _put(app, pg_conn, agent_id, EDITOR, {"sources": [source], "tools": [tool],
                                                     "confirm_sponsor": [f"source:{source}", f"tool:{tool}"]})
        assert _status(resp) == 403
        body = _body(resp)
        assert body["code"] == CODE_NOT_ALLOWED
        assert {r["key"] for r in body["resources"]} == {f"source:{source}", f"tool:{tool}"}
        row = _row(pg_conn, agent_id)
        assert not row["tools"] and not row["extra_source_ids"] and not row["source_id"]
        assert row["resource_sponsors"] == {}

    def test_edit_share_from_another_team_can_sponsor(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        team = _other_team(pg_conn, EDITOR)
        tool = _others_tool(pg_conn, team, EDITOR, "editor")
        resp = _put(app, pg_conn, agent_id, EDITOR, {"tools": [tool], "confirm_sponsor": [f"tool:{tool}"]})
        assert _status(resp) == 200, _body(resp)
        agent = _row(pg_conn, agent_id)
        assert agent["resource_sponsors"] == {sponsor_key("tool", tool): EDITOR}
        assert active_sponsor(pg_conn, "agent", agent, "tool", tool) == EDITOR

    def test_owner_usable_resource_needs_no_sponsor_or_consent(self, app, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "tool", tool, OWNER, OWNER, target_user_id=EDITOR)
        resp = _put(app, pg_conn, agent_id, EDITOR, {"tools": [tool]})
        assert _status(resp) == 200, _body(resp)
        assert _row(pg_conn, agent_id)["resource_sponsors"] == {}

    def test_existing_use_only_sponsorship_stops_running(self, pg_conn):
        agent_id, _ = _agent(pg_conn)
        team = _other_team(pg_conn, EDITOR)
        tool = _others_tool(pg_conn, team, EDITOR, "viewer")
        AgentsRepository(pg_conn).update_by_id(
            agent_id, {"tools": [tool], "resource_sponsors": {sponsor_key("tool", tool): EDITOR}}
        )
        agent = _row(pg_conn, agent_id)
        assert active_sponsor(pg_conn, "agent", agent, "tool", tool) is None
        [detail] = sponsor_details(pg_conn, "agent", agent)
        assert detail["state"] == "inactive"
        assert detail["reason"] == REASON_CANNOT_EDIT_RESOURCE


# ---------------------------------------------------------------------------
# B: explicit consent
# ---------------------------------------------------------------------------


class TestConsent:
    def test_new_sponsorship_needs_confirmation(self, app, pg_conn):
        from docsgpt.storage.db.repositories.users import UsersRepository

        agent_id, _ = _agent(pg_conn)
        UsersRepository(pg_conn).upsert(EDITOR)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"shared": True, "shared_token": uuid.uuid4().hex})
        tool, prompt, source = _editor_resources(pg_conn)
        resp = _put(app, pg_conn, agent_id, EDITOR, {"tools": [tool], "prompt_id": prompt, "source": source})
        assert _status(resp) == 409
        body = _body(resp)
        assert body["code"] == CODE_CONFIRMATION_REQUIRED
        by_key = {r["key"]: r for r in body["resources"]}
        assert set(by_key) == {f"tool:{tool}", f"prompt:{prompt}", f"source:{source}"}
        assert by_key[f"source:{source}"] == {"key": f"source:{source}", "type": "source", "id": source,
                                             "name": "editor-src"}
        assert by_key[f"prompt:{prompt}"]["name"] == "mine"
        assert body["audience"] == {"teams": ["T"], "api_key": True, "public_link": True, "webhook": False}
        row = _row(pg_conn, agent_id)
        assert not row["tools"] and row["resource_sponsors"] == {}

    def test_exact_confirmation_saves(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, prompt, _ = _editor_resources(pg_conn)
        confirm = [f"tool:{tool}", f"prompt:{prompt.upper()}"]
        resp = _put(app, pg_conn, agent_id, EDITOR, {"tools": [tool], "prompt_id": prompt, "confirm_sponsor": confirm})
        assert _status(resp) == 200, _body(resp)
        assert _row(pg_conn, agent_id)["resource_sponsors"] == {
            sponsor_key("tool", tool): EDITOR,
            sponsor_key("prompt", prompt): EDITOR,
        }

    def test_form_encoded_confirmation(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import UpdateAgent
        from tests.api.user.test_resource_sponsors import _patch_db

        agent_id, _ = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        data = {"tools": f'["{tool}"]', "confirm_sponsor": f'["tool:{tool}"]'}
        with _patch_db(pg_conn), app.test_request_context(f"/api/update_agent/{agent_id}", method="PUT",
                                                          data=data):
            from flask import request

            request.decoded_token = {"sub": EDITOR}
            resp = UpdateAgent().put(agent_id)
        assert _status(resp) == 200, _body(resp)
        assert _row(pg_conn, agent_id)["resource_sponsors"] == {sponsor_key("tool", tool): EDITOR}

    def test_partial_confirmation_is_refused(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, prompt, _ = _editor_resources(pg_conn)
        resp = _put(app, pg_conn, agent_id, EDITOR,
                    {"tools": [tool], "prompt_id": prompt, "confirm_sponsor": [f"tool:{tool}"]})
        assert _status(resp) == 409
        assert [r["key"] for r in _body(resp)["resources"]] == [f"prompt:{prompt}"]
        assert not _row(pg_conn, agent_id)["tools"]

    def test_unrelated_confirmation_is_rejected(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        stray = str(uuid.uuid4())
        resp = _put(app, pg_conn, agent_id, EDITOR,
                    {"tools": [tool], "confirm_sponsor": [f"tool:{tool}", f"source:{stray}"]})
        assert _status(resp) == 400
        body = _body(resp)
        assert body["code"] == CODE_UNEXPECTED_CONFIRMATION
        assert body["unexpected"] == [f"source:{stray}"]
        assert _row(pg_conn, agent_id)["resource_sponsors"] == {}

    def test_confirming_an_owner_usable_resource_is_rejected(self, app, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "tool", tool, OWNER, OWNER, target_user_id=EDITOR)
        resp = _put(app, pg_conn, agent_id, EDITOR, {"tools": [tool], "confirm_sponsor": [f"tool:{tool}"]})
        assert _status(resp) == 400

    def test_unchanged_save_needs_no_confirmation(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"tools": [tool], "confirm_sponsor": [f"tool:{tool}"]})) == 200
        assert _status(_put(app, pg_conn, agent_id, EDITOR, {"name": "Again", "tools": [tool]})) == 200
        assert _status(_put(app, pg_conn, agent_id, OWNER, {"name": "Owner", "tools": [tool]})) == 200
        assert _row(pg_conn, agent_id)["resource_sponsors"] == {sponsor_key("tool", tool): EDITOR}

    def test_parse_confirmations(self):
        rid = str(uuid.uuid4())
        assert parse_confirmations(None) == set()
        assert parse_confirmations([f"tool:{rid.upper()}"]) == {f"tool:{rid}"}
        assert parse_confirmations(f'["source:{rid}"]') == {f"source:{rid}"}
        assert parse_confirmations(f"prompt:{rid}, agent:{rid}, nonsense") == {f"prompt:{rid}"}
        assert parse_confirmations({"tool": rid}) == set()


# ---------------------------------------------------------------------------
# C: no silent handover
# ---------------------------------------------------------------------------


class TestNoSilentHandover:
    def _sponsored_then_lost(self, app, pg_conn):
        """EDITOR sponsors OTHER's tool (edit share), then loses edit on the agent.

        OTHER edits the agent too and may sponsor the tool themselves.
        """
        agent_id, team_id = _agent(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OTHER, "api_tool")["id"])
        TeamMembersRepository(pg_conn).add_member(team_id, OTHER)
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "tool", tool, OTHER, OTHER, access_level="editor")
        _add_agent_editor(pg_conn, team_id, agent_id, OTHER)
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"tools": [tool], "confirm_sponsor": [f"tool:{tool}"]})) == 200
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
        return agent_id, team_id, tool

    def test_lost_sponsor_is_inactive(self, app, pg_conn):
        agent_id, _, tool = self._sponsored_then_lost(app, pg_conn)
        agent = _row(pg_conn, agent_id)
        assert active_sponsor(pg_conn, "agent", agent, "tool", tool) is None
        [detail] = sponsor_details(pg_conn, "agent", agent, viewer=OTHER)
        assert detail["state"] == "inactive"
        assert detail["reason"] == REASON_CANNOT_EDIT_HOLDER
        assert detail["user_id"] == EDITOR
        assert detail["can_confirm"] is True
        assert sponsor_details(pg_conn, "agent", agent, viewer=OWNER)[0]["can_confirm"] is False

    def test_unrelated_save_does_not_transfer(self, app, pg_conn):
        agent_id, _, tool = self._sponsored_then_lost(app, pg_conn)
        resp = _put(app, pg_conn, agent_id, OTHER, {"name": "Renamed", "tools": [tool]})
        assert _status(resp) == 200, _body(resp)
        agent = _row(pg_conn, agent_id)
        assert [str(t) for t in agent["tools"]] == [tool]
        assert agent["resource_sponsors"] == {sponsor_key("tool", tool): EDITOR}
        assert active_sponsor(pg_conn, "agent", agent, "tool", tool) is None

    def test_explicit_confirmation_transfers(self, app, pg_conn):
        agent_id, _, tool = self._sponsored_then_lost(app, pg_conn)
        resp = _put(app, pg_conn, agent_id, OTHER, {"tools": [tool], "confirm_sponsor": [f"tool:{tool}"]})
        assert _status(resp) == 200, _body(resp)
        agent = _row(pg_conn, agent_id)
        assert agent["resource_sponsors"] == {sponsor_key("tool", tool): OTHER}
        assert active_sponsor(pg_conn, "agent", agent, "tool", tool) == OTHER

    def test_takeover_needs_edit_on_the_resource(self, app, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool = _others_tool(pg_conn, _other_team(pg_conn, EDITOR), EDITOR, "editor")
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"tools": [tool], "confirm_sponsor": [f"tool:{tool}"]})) == 200
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
        _add_agent_editor(pg_conn, team_id, agent_id, STRANGER)
        # STRANGER edits the agent but has no access to the tool at all.
        resp = _put(app, pg_conn, agent_id, STRANGER, {"tools": [tool], "confirm_sponsor": [f"tool:{tool}"]})
        assert _status(resp) == 400
        assert _row(pg_conn, agent_id)["resource_sponsors"] == {sponsor_key("tool", tool): EDITOR}

    def test_sponsor_demoted_on_resource_stops(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        team = _other_team(pg_conn, EDITOR)
        tool = _others_tool(pg_conn, team, EDITOR, "editor")
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"tools": [tool], "confirm_sponsor": [f"tool:{tool}"]})) == 200
        TeamResourceGrantsRepository(pg_conn).grant(team, "tool", tool, OTHER, OTHER, access_level="viewer",
                                                    target_user_id=EDITOR)
        agent = _row(pg_conn, agent_id)
        assert active_sponsor(pg_conn, "agent", agent, "tool", tool) is None
        assert sponsor_details(pg_conn, "agent", agent)[0]["reason"] == REASON_CANNOT_EDIT_RESOURCE
        # The same editor saving again doesn't quietly keep it running either.
        assert _status(_put(app, pg_conn, agent_id, EDITOR, {"name": "x", "tools": [tool]})) == 200
        assert active_sponsor(pg_conn, "agent", _row(pg_conn, agent_id), "tool", tool) is None

    def test_plan_keeps_stopped_record_without_confirmation(self, app, pg_conn):
        agent_id, _, tool = self._sponsored_then_lost(app, pg_conn)
        agent = _row(pg_conn, agent_id)
        refs = [("tool", tool)]
        plan = plan_sponsors(pg_conn, "agent", agent, OWNER, OTHER, refs, previous_refs=refs)
        assert plan.sponsors == {sponsor_key("tool", tool): EDITOR}
        assert not plan.needs_confirmation and not plan.not_allowed and not plan.unexpected


# ---------------------------------------------------------------------------
# get_agent
# ---------------------------------------------------------------------------


class TestGetAgentDetails:
    def test_sponsor_details_carry_state(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import GetAgent

        agent_id, _ = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"tools": [tool], "confirm_sponsor": [f"tool:{tool}"]})) == 200
        data = _call(app, pg_conn, GetAgent, "get", f"/api/get_agent?id={agent_id}", EDITOR).get_json()
        assert data["resource_sponsors"] == [{
            "key": f"tool:{tool}", "type": "tool", "id": tool, "name": "api_tool", "user_id": EDITOR,
            "label": EDITOR, "state": "active", "reason": None, "active": True, "can_confirm": False,
        }]


# ---------------------------------------------------------------------------
# workflows
# ---------------------------------------------------------------------------


class TestWorkflowConsent:
    def _setup(self, pg_conn):
        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        agent_id, team_id = _agent(pg_conn, agent_type="workflow", workflow_id=str(wf["id"]))
        return str(wf["id"]), agent_id, team_id

    def _put(self, app, pg_conn, wid, user, body):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        return _call(app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", user, json=body, args=(wid,))

    def test_new_node_sponsorship_needs_confirmation(self, app, pg_conn):
        wid, _, _ = self._setup(pg_conn)
        tool, _, source = _editor_resources(pg_conn)
        resp = self._put(app, pg_conn, wid, EDITOR, _wf_body(tool, source))
        assert _status(resp) == 409
        body = _body(resp)
        assert body["code"] == CODE_CONFIRMATION_REQUIRED
        assert {r["key"] for r in body["resources"]} == {f"tool:{tool}", f"source:{source}"}
        assert body["audience"]["teams"] == ["T"]
        row = WorkflowsRepository(pg_conn).get_by_id(wid)
        assert row["resource_sponsors"] == {}
        assert row["current_graph_version"] in (None, 0, 1)

        confirmed = {**_wf_body(tool, source), "confirm_sponsor": [f"tool:{tool}", f"source:{source}"]}
        resp = self._put(app, pg_conn, wid, EDITOR, confirmed)
        assert _status(resp) == 200, _body(resp)
        assert WorkflowsRepository(pg_conn).get_by_id(wid)["resource_sponsors"] == {
            sponsor_key("tool", tool): EDITOR,
            sponsor_key("source", source): EDITOR,
        }

    def test_use_only_node_resource_is_refused(self, app, pg_conn):
        wid, _, _ = self._setup(pg_conn)
        tool = _others_tool(pg_conn, _other_team(pg_conn, EDITOR), EDITOR, "viewer")
        resp = self._put(app, pg_conn, wid, EDITOR, {**_wf_body(tool), "confirm_sponsor": [f"tool:{tool}"]})
        assert _status(resp) == 403
        assert _body(resp)["code"] == CODE_NOT_ALLOWED

    def test_unrelated_confirmation_is_rejected(self, app, pg_conn):
        wid, _, _ = self._setup(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        body = {**_wf_body(tool), "confirm_sponsor": [f"tool:{tool}", f"tool:{uuid.uuid4()}"]}
        assert _status(self._put(app, pg_conn, wid, EDITOR, body)) == 400

    def test_lost_sponsor_not_transferred_without_confirmation(self, app, pg_conn):
        wid, agent_id, team_id = self._setup(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OTHER, "api_tool")["id"])
        TeamMembersRepository(pg_conn).add_member(team_id, OTHER)
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "tool", tool, OTHER, OTHER, access_level="editor")
        _add_agent_editor(pg_conn, team_id, agent_id, OTHER)
        assert _status(self._put(app, pg_conn, wid, EDITOR,
                                 {**_wf_body(tool), "confirm_sponsor": [f"tool:{tool}"]})) == 200
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)

        assert _status(self._put(app, pg_conn, wid, OTHER, _wf_body(tool))) == 200
        row = WorkflowsRepository(pg_conn).get_by_id(wid)
        assert row["resource_sponsors"] == {sponsor_key("tool", tool): EDITOR}
        assert active_sponsor(pg_conn, "workflow", row, "tool", tool) is None

        assert _status(self._put(app, pg_conn, wid, OTHER,
                                 {**_wf_body(tool), "confirm_sponsor": [f"tool:{tool}"]})) == 200
        row = WorkflowsRepository(pg_conn).get_by_id(wid)
        assert row["resource_sponsors"] == {sponsor_key("tool", tool): OTHER}
        assert active_sponsor(pg_conn, "workflow", row, "tool", tool) == OTHER

    def test_workflow_details_carry_state(self, app, pg_conn):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        wid, _, _ = self._setup(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        assert _status(self._put(app, pg_conn, wid, EDITOR,
                                 {**_wf_body(tool), "confirm_sponsor": [f"tool:{tool}"]})) == 200
        resp = _call(app, pg_conn, WorkflowDetail, "get", f"/api/workflows/{wid}", OWNER, args=(wid,))
        [detail] = _body(resp)["data"]["resource_sponsors"]
        assert detail["state"] == "active" and detail["reason"] is None and detail["name"] == "api_tool"
