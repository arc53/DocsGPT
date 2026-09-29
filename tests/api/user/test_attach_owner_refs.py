"""What a team editor may newly reference from the owner's agent or workflow.

An agent (and its workflow) runs as its owner, so owning a resource is not
enough for an editor to wire it in: the editor must be able to use it
themselves. Otherwise an editor of one shared agent could attach the owner's
private tool (run with the owner's credentials), source or prompt, or the
workflow of another of the owner's agents and then edit that graph.

Also covers id casing: an uppercase UUID must resolve the same switches as
the canonical lowercase one. Uses real repositories on ``pg_conn``.
"""

from __future__ import annotations

import uuid

import pytest

from docsgpt.api.user.resource_access import resolve, set_settings
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

from tests.api.user.test_resource_sponsors import (
    EDITOR,
    OWNER,
    _agent,
    _call,
    _put,
    _row,
    _status,
    _wf_body,
)


@pytest.fixture
def app():
    from flask import Flask

    return Flask(__name__)


def _owner_private(conn):
    """A tool, prompt and source the owner never shared."""
    tool = str(UserToolsRepository(conn).create(OWNER, "api_tool")["id"])
    prompt = str(PromptsRepository(conn).create(OWNER, "private", "Owner prompt")["id"])
    source = str(SourcesRepository(conn).create("owner-src", user_id=OWNER)["id"])
    return tool, prompt, source


def _share_tool_with_editor(conn, team_id, tool, level="viewer"):
    TeamResourceGrantsRepository(conn).grant(
        team_id, "tool", tool, OWNER, OWNER, access_level=level, target_user_id=EDITOR
    )


class TestAgentAttach:
    def test_editor_cannot_attach_owner_private_tool(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, _, _ = _owner_private(pg_conn)
        resp = _put(app, pg_conn, agent_id, EDITOR, {"tools": [tool]})
        assert _status(resp) == 403
        assert _row(pg_conn, agent_id)["tools"] in (None, [])

    def test_editor_cannot_attach_owner_private_source(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        _, _, source = _owner_private(pg_conn)
        resp = _put(app, pg_conn, agent_id, EDITOR, {"sources": [source]})
        assert _status(resp) == 403

    def test_editor_cannot_attach_owner_private_prompt(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        _, prompt, _ = _owner_private(pg_conn)
        resp = _put(app, pg_conn, agent_id, EDITOR, {"prompt_id": prompt})
        assert _status(resp) == 403

    def test_editor_may_attach_owner_tool_shared_with_them(self, app, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool, _, _ = _owner_private(pg_conn)
        _share_tool_with_editor(pg_conn, team_id, tool)
        resp = _put(app, pg_conn, agent_id, EDITOR, {"tools": [tool]})
        assert _status(resp) == 200, resp.get_json()
        row = _row(pg_conn, agent_id)
        assert [str(t) for t in row["tools"]] == [tool]
        # The owner owns it, so it runs as the owner: no sponsor.
        assert not row.get("resource_sponsors")

    def test_editor_keeps_owner_refs_already_on_agent(self, app, pg_conn):
        tool, prompt, source = _owner_private(pg_conn)
        agent_id, _ = _agent(pg_conn, tools=[tool], prompt_id=prompt, source_id=source)
        resp = _put(
            app, pg_conn, agent_id, EDITOR,
            {"tools": [tool], "prompt_id": prompt, "source": source},
        )
        assert _status(resp) == 200, resp.get_json()

    def test_owner_may_attach_own_private_tool(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, _, _ = _owner_private(pg_conn)
        assert _status(_put(app, pg_conn, agent_id, OWNER, {"tools": [tool]})) == 200


class TestAgentWorkflowSwap:
    def _two_workflow_agents(self, pg_conn):
        """Agent A (shared with EDITOR) and the owner's private agent B, each with a workflow."""
        wf_a = str(WorkflowsRepository(pg_conn).create(OWNER, "A")["id"])
        wf_b = str(WorkflowsRepository(pg_conn).create(OWNER, "B")["id"])
        agent_a, _ = _agent(pg_conn, agent_type="workflow", workflow_id=wf_a)
        AgentsRepository(pg_conn).create(
            OWNER, "Private B", "published", description="d", key=f"k-{uuid.uuid4().hex}",
            agent_type="workflow", workflow_id=wf_b,
        )
        return agent_a, wf_a, wf_b

    def test_editor_cannot_swap_in_another_owner_workflow(self, app, pg_conn):
        agent_a, wf_a, wf_b = self._two_workflow_agents(pg_conn)
        resp = _put(app, pg_conn, agent_a, EDITOR, {"workflow": wf_b})
        assert _status(resp) == 403
        assert str(_row(pg_conn, agent_a)["workflow_id"]) == wf_a

    def test_editor_may_resend_current_workflow(self, app, pg_conn):
        agent_a, wf_a, _ = self._two_workflow_agents(pg_conn)
        resp = _put(app, pg_conn, agent_a, EDITOR, {"workflow": wf_a})
        assert _status(resp) == 200, resp.get_json()

    def test_owner_may_swap_workflow(self, app, pg_conn):
        agent_a, _, wf_b = self._two_workflow_agents(pg_conn)
        assert _status(_put(app, pg_conn, agent_a, OWNER, {"workflow": wf_b})) == 200
        assert str(_row(pg_conn, agent_a)["workflow_id"]) == wf_b

    def test_editor_cannot_detach_workflow(self, app, pg_conn):
        # Unpublishing in the same request makes the empty workflow allowed
        # for a draft; detaching is still the owner's call.
        agent_a, wf_a, _ = self._two_workflow_agents(pg_conn)
        resp = _put(app, pg_conn, agent_a, EDITOR, {"status": "draft", "workflow": ""})
        assert _status(resp) == 403
        assert str(_row(pg_conn, agent_a)["workflow_id"]) == wf_a

    def test_owner_may_detach_workflow(self, app, pg_conn):
        agent_a, _, _ = self._two_workflow_agents(pg_conn)
        resp = _put(app, pg_conn, agent_a, OWNER, {"status": "draft", "workflow": ""})
        assert _status(resp) == 200, resp.get_json()
        assert _row(pg_conn, agent_a)["workflow_id"] is None

    def test_editor_empty_workflow_on_agent_without_one_is_a_no_op(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        resp = _put(app, pg_conn, agent_id, EDITOR, {"status": "draft", "workflow": ""})
        assert _status(resp) == 200, resp.get_json()


class TestWorkflowNodeAttach:
    def _setup(self, pg_conn):
        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        _, team_id = _agent(pg_conn, agent_type="workflow", workflow_id=str(wf["id"]))
        return str(wf["id"]), team_id

    def _put_wf(self, app, pg_conn, wid, user, body):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        return _call(app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", user,
                     json=body, args=(wid,))

    def test_editor_cannot_add_owner_private_tool_to_node(self, app, pg_conn):
        wid, _ = self._setup(pg_conn)
        tool, _, _ = _owner_private(pg_conn)
        assert _status(self._put_wf(app, pg_conn, wid, EDITOR, _wf_body(tool=tool))) == 403

    def test_editor_cannot_add_owner_private_source_to_node(self, app, pg_conn):
        wid, _ = self._setup(pg_conn)
        _, _, source = _owner_private(pg_conn)
        assert _status(self._put_wf(app, pg_conn, wid, EDITOR, _wf_body(source=source))) == 403

    def test_editor_keeps_owner_node_refs_already_in_graph(self, app, pg_conn):
        wid, _ = self._setup(pg_conn)
        tool, _, source = _owner_private(pg_conn)
        body = _wf_body(tool=tool, source=source)
        assert _status(self._put_wf(app, pg_conn, wid, OWNER, body)) == 200
        resp = self._put_wf(app, pg_conn, wid, EDITOR, body)
        assert _status(resp) == 200, resp.get_json()

    def test_editor_may_add_tool_shared_with_them(self, app, pg_conn):
        wid, team_id = self._setup(pg_conn)
        tool, _, _ = _owner_private(pg_conn)
        _share_tool_with_editor(pg_conn, team_id, tool)
        resp = self._put_wf(app, pg_conn, wid, EDITOR, _wf_body(tool=tool))
        assert _status(resp) == 200, resp.get_json()


class TestUppercaseIds:
    def _tool_not_usable_in_own(self, pg_conn, team_id):
        """An owner tool the EDITOR only views, with ``viewers_can_use_in_agents`` off."""
        tool, _, _ = _owner_private(pg_conn)
        _share_tool_with_editor(pg_conn, team_id, tool)
        set_settings(pg_conn, "tool", tool, {"viewers_can_use_in_agents": False}, OWNER)
        return tool

    def test_resolve_applies_switches_to_uppercase_id(self, pg_conn):
        _, team_id = _agent(pg_conn)
        tool = self._tool_not_usable_in_own(pg_conn, team_id)
        lower = resolve(pg_conn, "tool", tool, EDITOR)
        upper = resolve(pg_conn, "tool", tool.upper(), EDITOR)
        assert lower is not None and upper is not None
        assert not upper.can("use_in_own")
        assert upper.settings == lower.settings
        assert upper.resource_id == tool

    def test_uppercase_tool_id_does_not_bypass_switch_on_attach(self, app, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool = self._tool_not_usable_in_own(pg_conn, team_id)
        resp = _put(app, pg_conn, agent_id, EDITOR, {"tools": [tool.upper()]})
        assert _status(resp) == 403

    def test_attached_ids_are_stored_canonical(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, prompt, source = _owner_private(pg_conn)
        resp = _put(
            app, pg_conn, agent_id, OWNER,
            {"tools": [tool.upper()], "prompt_id": prompt.upper(), "sources": [source.upper()]},
        )
        assert _status(resp) == 200, resp.get_json()
        row = _row(pg_conn, agent_id)
        assert [str(t) for t in row["tools"]] == [tool]
        assert str(row["prompt_id"]) == prompt
        assert [str(s) for s in row["extra_source_ids"] or []] + (
            [str(row["source_id"])] if row.get("source_id") else []
        ) == [source]
