"""A personal agent that uses a team's items reaches only people who already reach each of them.

Ops owns a source, a tool, a prompt and a knowledge folder. Vera is a Viewer in Ops and in Dev; her personal
agent on Ops' items runs as her, so whoever chats with it reads Ops' documents and runs Ops' tool on Ops' stored
account. Sharing it with a whole team is allowed only when that team owns each item or receives it through a live
share; sharing it with one member only when that member can use each item. The refusal names what blocks it and
offers a team to move the agent to, when the caller may move it there. A save that adds a team's item to an agent
already shared with someone who can't use it is refused the same way. Items a person lent through a grant keep
today's behaviour. Uses real repositories on ``pg_conn``.
"""

from __future__ import annotations

import uuid

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.api.user.agents.graph_checks import (
    CODE_TEAM_ITEM_SHARED_OUTSIDE,
    CODE_USES_TEAM_ITEMS,
    agent_team_refs,
    team_confinement_refusal,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from tests.api.user.agents.test_borrowed_outside_access import _call, _json, _status
from tests.workspaces.move_support import agent, grant, prompt, source, team, tool

LENDER = "lena-lender"


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def w(pg_conn):
    """Ops (alice owner, adam admin, eddie editor, vera viewer); Dev (dora owner, dan editor, vera viewer,
    eddie viewer); QA (quinn owner, dan editor, vera viewer). Ops owns a source, a tool, a prompt and a
    folder; QA owns a tool."""
    ops, ops_p = team(pg_conn)
    dev, dev_p = team(pg_conn, owner="dora", name="Dev",
                      members=(("dan", "team_editor"), ("vera", "team_viewer"), ("eddie", "team_viewer")))
    qa, qa_p = team(pg_conn, owner="quinn", name="QA", members=(("dan", "team_editor"), ("vera", "team_viewer")))
    folder = str(FoldersRepository(pg_conn).create(ops_p, "Ops shelf", resource_type="source",
                                                   created_by="alice")["id"])
    return {
        "ops": ops, "ops_p": ops_p, "dev": dev, "dev_p": dev_p, "qa": qa, "qa_p": qa_p,
        "source": source(pg_conn, ops_p, "Ops handbook"),
        "tool": tool(pg_conn, ops_p, "api_tool", display_name="Ops CRM"),
        "prompt": prompt(pg_conn, ops_p, "Ops voice"),
        "folder": folder,
        "qa_tool": tool(pg_conn, qa_p, "api_tool", display_name="QA tracker"),
    }


def _agent(conn, owner="vera", **refs) -> dict:
    refs.setdefault("agent_type", "classic")
    return AgentsRepository(conn).get_by_id(agent(conn, owner, **refs))


def _share_in(conn, w, kind, into="dev", by="adam"):
    TeamItemSharesRepository(conn).share(w["ops"], w[into], kind, w[kind], by)


def _lent_source(conn, w) -> str:
    """Lena, a member of Dev, lends Vera her own source through Dev."""
    TeamMembersRepository(conn).add_member(w["dev"], LENDER, role="team_viewer")
    lent = source(conn, LENDER, "Lent")
    grant(conn, w["dev"], "source", lent, LENDER, target="vera")
    return lent


def _lock(conn, team_id):
    conn.execute(text("UPDATE teams SET outside_policy = 'locked' WHERE id = CAST(:t AS uuid)"), {"t": team_id})


def _keys(body) -> set:
    return {item["key"] for team_row in body["uses_team_items"] for item in team_row["items"]}


class TestTeamRefs:
    def test_sources_tools_prompts_and_folders_of_a_team_count(self, pg_conn, w):
        a = _agent(pg_conn, source_id=w["source"], tools=[w["tool"]], prompt_id=w["prompt"],
                   knowledge_folder_ids=[w["folder"]])
        assert {w["ops"]} == set(agent_team_refs(pg_conn, a))
        assert set(agent_team_refs(pg_conn, a)[w["ops"]]) == {
            ("source", w["source"]), ("tool", w["tool"]), ("prompt", w["prompt"]), ("folder", w["folder"]),
        }

    def test_own_items_presets_and_lent_items_dont(self, pg_conn, w):
        own = source(pg_conn, "vera", "Mine")
        lent = _lent_source(pg_conn, w)
        a = _agent(pg_conn, source_id=own, extra_source_ids=[lent], prompt_id="default")
        assert agent_team_refs(pg_conn, a) == {}

    def test_a_team_agent_doesnt_count_its_own_teams_items(self, pg_conn, w):
        a = _agent(pg_conn, owner=w["ops_p"], source_id=w["source"], tools=[w["qa_tool"]])
        assert agent_team_refs(pg_conn, a) == {w["qa"]: [("tool", w["qa_tool"])]}


class TestShareWithATeam:
    def test_a_viewer_cant_take_a_teams_source_and_tool_to_another_team(self, pg_conn, w):
        # Vera, a Viewer in Ops, builds a personal agent on Ops' source and tool and shares it with Dev.
        a = _agent(pg_conn, source_id=w["source"], tools=[w["tool"]])
        refusal = team_confinement_refusal(pg_conn, a, w["dev"], None, "vera")
        assert refusal is not None
        body, status = refusal
        assert status == 409
        assert body["success"] is False
        assert body["error"] == body["code"] == CODE_USES_TEAM_ITEMS
        assert body["uses_team_items"][0]["team_id"] == w["ops"]
        assert body["uses_team_items"][0]["name"] == "Ops"
        assert _keys(body) == {f"source:{w['source']}", f"tool:{w['tool']}"}
        assert "Ops handbook" in body["message"] and "Ops CRM" in body["message"] and "Dev" in body["message"]
        # Vera can't add agents to Ops, so there is nowhere to move it.
        assert body["move_to"] is None

    def test_the_owning_team_reaches_its_own_items(self, pg_conn, w):
        a = _agent(pg_conn, source_id=w["source"], tools=[w["tool"]], prompt_id=w["prompt"])
        assert team_confinement_refusal(pg_conn, a, w["ops"], None, "vera") is None

    def test_a_team_that_receives_the_item_reaches_it(self, pg_conn, w):
        _share_in(pg_conn, w, "source")
        a = _agent(pg_conn, source_id=w["source"])
        assert team_confinement_refusal(pg_conn, a, w["dev"], None, "vera") is None

    def test_only_what_the_team_doesnt_receive_is_named(self, pg_conn, w):
        _share_in(pg_conn, w, "source")
        a = _agent(pg_conn, source_id=w["source"], tools=[w["tool"]])
        body, _ = team_confinement_refusal(pg_conn, a, w["dev"], None, "vera")
        assert _keys(body) == {f"tool:{w['tool']}"}

    def test_a_share_paused_by_a_lock_doesnt_reach(self, pg_conn, w):
        _share_in(pg_conn, w, "source")
        _lock(pg_conn, w["ops"])
        a = _agent(pg_conn, source_id=w["source"])
        assert team_confinement_refusal(pg_conn, a, w["dev"], None, "vera") is not None

    def test_a_share_into_another_team_doesnt_reach(self, pg_conn, w):
        _share_in(pg_conn, w, "source", into="qa")
        a = _agent(pg_conn, source_id=w["source"])
        assert team_confinement_refusal(pg_conn, a, w["dev"], None, "vera") is not None

    def test_a_teams_prompt_alone_counts(self, pg_conn, w):
        a = _agent(pg_conn, prompt_id=w["prompt"])
        body, _ = team_confinement_refusal(pg_conn, a, w["dev"], None, "vera")
        assert _keys(body) == {f"prompt:{w['prompt']}"}

    def test_a_teams_knowledge_folder_counts(self, pg_conn, w):
        a = _agent(pg_conn, knowledge_folder_ids=[w["folder"]])
        body, _ = team_confinement_refusal(pg_conn, a, w["dev"], None, "vera")
        assert f"folder:{w['folder']}" in _keys(body)

    def test_a_teams_source_fed_by_a_personal_folder_counts(self, pg_conn, w):
        shelf = str(FoldersRepository(pg_conn).create("vera", "Shelf", resource_type="source")["id"])
        FolderItemsRepository(pg_conn).file("vera", "source", w["source"], shelf)
        a = _agent(pg_conn, knowledge_folder_ids=[shelf])
        body, _ = team_confinement_refusal(pg_conn, a, w["dev"], None, "vera")
        assert _keys(body) == {f"source:{w['source']}"}

    def test_a_workflow_nodes_refs_count(self, pg_conn, w):
        from tests.workspaces.move_support import workflow

        wid = workflow(pg_conn, "vera", nodes=({"agent_type": "classic", "sources": [w["source"]],
                                                "tools": [w["tool"]]},))
        a = _agent(pg_conn, agent_type="workflow", workflow_id=wid)
        body, _ = team_confinement_refusal(pg_conn, a, w["dev"], None, "vera")
        assert _keys(body) == {f"source:{w['source']}", f"tool:{w['tool']}"}
        assert team_confinement_refusal(pg_conn, a, w["ops"], None, "vera") is None

    def test_two_teams_items_need_a_team_reaching_both(self, pg_conn, w):
        a = _agent(pg_conn, source_id=w["source"], tools=[w["qa_tool"]])
        body, _ = team_confinement_refusal(pg_conn, a, w["ops"], None, "vera")
        assert body["uses_team_items"] == [
            {"team_id": w["qa"], "name": "QA",
             "items": [{"key": f"tool:{w['qa_tool']}", "type": "tool", "id": w["qa_tool"], "name": "QA tracker"}]},
        ]
        body, _ = team_confinement_refusal(pg_conn, a, w["qa"], None, "vera")
        assert _keys(body) == {f"source:{w['source']}"}

    def test_a_personally_lent_source_keeps_todays_behaviour(self, pg_conn, w):
        lent = _lent_source(pg_conn, w)
        a = _agent(pg_conn, source_id=lent)
        assert team_confinement_refusal(pg_conn, a, w["qa"], None, "vera") is None


class TestShareWithOneMember:
    def test_a_member_who_can_use_every_item(self, pg_conn, w):
        # Eddie is in Dev and an Editor in Ops.
        a = _agent(pg_conn, source_id=w["source"], tools=[w["tool"]], knowledge_folder_ids=[w["folder"]])
        assert team_confinement_refusal(pg_conn, a, w["dev"], "eddie", "vera") is None

    def test_a_member_who_cant(self, pg_conn, w):
        a = _agent(pg_conn, source_id=w["source"], tools=[w["tool"]])
        body, status = team_confinement_refusal(pg_conn, a, w["dev"], "dan", "vera")
        assert status == 409 and body["code"] == CODE_USES_TEAM_ITEMS
        assert _keys(body) == {f"source:{w['source']}", f"tool:{w['tool']}"}

    def test_a_member_reached_through_their_teams_share(self, pg_conn, w):
        _share_in(pg_conn, w, "source", into="qa")
        a = _agent(pg_conn, source_id=w["source"])
        assert team_confinement_refusal(pg_conn, a, w["dev"], "dan", "vera") is None

    def test_a_folder_needs_the_folders_team(self, pg_conn, w):
        a = _agent(pg_conn, knowledge_folder_ids=[w["folder"]])
        assert team_confinement_refusal(pg_conn, a, w["dev"], "dan", "vera") is not None


class TestMoveOffer:
    def test_an_editor_of_the_owning_team_is_offered_it(self, pg_conn, w):
        a = _agent(pg_conn, owner="eddie", source_id=w["source"], tools=[w["tool"]])
        body, _ = team_confinement_refusal(pg_conn, a, w["dev"], None, "eddie")
        assert body["move_to"] == {"team_id": w["ops"], "name": "Ops"}
        assert "Move it to Ops" in body["message"]

    def test_a_team_that_receives_every_item_is_offered(self, pg_conn, w):
        # Dan edits in Dev and QA; Ops shares its source with Dev only.
        _share_in(pg_conn, w, "source")
        a = _agent(pg_conn, owner="dan", source_id=w["source"])
        body, _ = team_confinement_refusal(pg_conn, a, w["qa"], None, "dan")
        assert body["move_to"] == {"team_id": w["dev"], "name": "Dev"}

    def test_no_team_reaching_every_item(self, pg_conn, w):
        TeamMembersRepository(pg_conn).add_member(w["qa"], "eddie", role="team_editor")
        a = _agent(pg_conn, owner="eddie", source_id=w["source"], tools=[w["qa_tool"]])
        body, _ = team_confinement_refusal(pg_conn, a, w["dev"], None, "eddie")
        assert body["move_to"] is None

    def test_only_the_agents_owner_is_offered_a_move(self, pg_conn, w):
        a = _agent(pg_conn, owner="eddie", source_id=w["source"])
        body, _ = team_confinement_refusal(pg_conn, a, w["dev"], None, "adam")
        assert body["move_to"] is None


def _put(app, conn, agent_id, body, user="vera"):
    from docsgpt.api.user.agents.routes import UpdateAgent

    return _call(app, conn, UpdateAgent, "put", f"/api/update_agent/{agent_id}", user, json=body, args=(agent_id,))


def _row(conn, agent_id) -> dict:
    return AgentsRepository(conn).get_by_id(agent_id)


class TestAddingToASharedAgent:
    def test_a_teams_source_refused_on_an_agent_shared_with_another_team(self, app, pg_conn, w):
        a = _agent(pg_conn)
        grant(pg_conn, w["dev"], "agent", str(a["id"]), "vera")
        resp = _put(app, pg_conn, str(a["id"]), {"sources": [w["source"]]})
        assert _status(resp) == 409, _json(resp)
        body = _json(resp)
        assert body["error"] == body["code"] == CODE_TEAM_ITEM_SHARED_OUTSIDE
        assert _keys(body) == {f"source:{w['source']}"}
        assert body["shared_with"] == [{"team_id": w["dev"], "name": "Dev"}]
        assert "Ops handbook" in body["message"]
        assert not _row(pg_conn, str(a["id"])).get("extra_source_ids")

    def test_allowed_when_shared_with_the_owning_team(self, app, pg_conn, w):
        a = _agent(pg_conn)
        grant(pg_conn, w["ops"], "agent", str(a["id"]), "vera")
        resp = _put(app, pg_conn, str(a["id"]), {"sources": [w["source"]], "tools": [w["tool"]]})
        assert _status(resp) == 200, _json(resp)
        assert [str(s) for s in _row(pg_conn, str(a["id"]))["extra_source_ids"]] == [w["source"]]

    def test_allowed_when_the_team_receives_it(self, app, pg_conn, w):
        _share_in(pg_conn, w, "source")
        a = _agent(pg_conn)
        grant(pg_conn, w["dev"], "agent", str(a["id"]), "vera")
        assert _status(_put(app, pg_conn, str(a["id"]), {"sources": [w["source"]]})) == 200

    def test_a_member_share_follows_that_member(self, app, pg_conn, w):
        a = _agent(pg_conn)
        grant(pg_conn, w["dev"], "agent", str(a["id"]), "vera", target="eddie")
        assert _status(_put(app, pg_conn, str(a["id"]), {"tools": [w["tool"]]})) == 200
        grant(pg_conn, w["dev"], "agent", str(a["id"]), "vera", target="dan")
        resp = _put(app, pg_conn, str(a["id"]), {"tools": [w["tool"]], "prompt_id": w["prompt"]})
        assert _status(resp) == 409, _json(resp)
        assert _keys(_json(resp)) == {f"prompt:{w['prompt']}"}

    def test_a_teams_prompt_refused(self, app, pg_conn, w):
        a = _agent(pg_conn)
        grant(pg_conn, w["qa"], "agent", str(a["id"]), "vera")
        resp = _put(app, pg_conn, str(a["id"]), {"prompt_id": w["prompt"]})
        assert _status(resp) == 409, _json(resp)

    def test_a_folder_feeding_a_teams_source_refused(self, app, pg_conn, w):
        shelf = str(FoldersRepository(pg_conn).create("vera", "Shelf", resource_type="source")["id"])
        FolderItemsRepository(pg_conn).file("vera", "source", w["source"], shelf)
        a = _agent(pg_conn)
        grant(pg_conn, w["dev"], "agent", str(a["id"]), "vera")
        resp = _put(app, pg_conn, str(a["id"]), {"folders": [shelf]})
        assert _status(resp) == 409, _json(resp)
        assert _keys(_json(resp)) == {f"source:{w['source']}"}

    def test_a_personally_lent_source_keeps_todays_behaviour(self, app, pg_conn, w):
        lent = _lent_source(pg_conn, w)
        a = _agent(pg_conn)
        grant(pg_conn, w["qa"], "agent", str(a["id"]), "vera")
        assert _status(_put(app, pg_conn, str(a["id"]), {"sources": [lent]})) == 200

    def test_a_team_item_already_on_it_still_saves(self, app, pg_conn, w):
        # An agent shared before the rule existed keeps saving; the run-time check stops the item.
        a = _agent(pg_conn, source_id=w["source"])
        grant(pg_conn, w["dev"], "agent", str(a["id"]), "vera")
        resp = _put(app, pg_conn, str(a["id"]), {"name": "Renamed", "sources": [w["source"]]})
        assert _status(resp) == 200, _json(resp)

    def test_an_agent_shared_with_nobody_takes_it(self, app, pg_conn, w):
        a = _agent(pg_conn)
        assert _status(_put(app, pg_conn, str(a["id"]), {"sources": [w["source"]]})) == 200

    def test_a_team_agent_shared_with_another_team(self, app, pg_conn, w):
        # Dev's agent, shared with QA, may not take on Ops' source that Ops shares with Dev only.
        _share_in(pg_conn, w, "source")
        a = _agent(pg_conn, owner=w["dev_p"])
        TeamItemSharesRepository(pg_conn).share(w["dev"], w["qa"], "agent", str(a["id"]), "dora")
        resp = _put(app, pg_conn, str(a["id"]), {"sources": [w["source"]]}, user="dan")
        assert _status(resp) == 409, _json(resp)
        assert _json(resp)["code"] == CODE_TEAM_ITEM_SHARED_OUTSIDE


class TestWorkflowNodes:
    def _wf_agent(self, conn, w, share_to="dev"):
        wid = str(WorkflowsRepository(conn).create("vera", "wf")["id"])
        a = _agent(conn, agent_type="workflow", workflow_id=wid)
        grant(conn, w[share_to], "agent", str(a["id"]), "vera")
        return wid, a

    def test_a_node_source_refused_when_the_agent_is_shared_outside(self, app, pg_conn, w):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        from tests.api.user.test_resource_sponsors import _wf_body

        wid, _ = self._wf_agent(pg_conn, w)
        resp = _call(app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", "vera",
                     json=_wf_body(source=w["source"]), args=(wid,))
        assert _status(resp) == 409, _json(resp)
        assert _json(resp)["code"] == CODE_TEAM_ITEM_SHARED_OUTSIDE
        assert _keys(_json(resp)) == {f"source:{w['source']}"}

    def test_a_node_tool_allowed_when_shared_with_the_owning_team(self, app, pg_conn, w):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        from tests.api.user.test_resource_sponsors import _wf_body

        wid, _ = self._wf_agent(pg_conn, w, share_to="ops")
        resp = _call(app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", "vera",
                     json=_wf_body(tool=w["tool"]), args=(wid,))
        assert _status(resp) == 200, _json(resp)

    def test_an_inline_graph_on_the_agent_save_refused(self, app, pg_conn, w):
        from tests.api.user.test_resource_sponsors import _wf_body

        _, a = self._wf_agent(pg_conn, w)
        graph = _wf_body(tool=w["tool"])
        resp = _put(app, pg_conn, str(a["id"]), {"workflow_graph": {"nodes": graph["nodes"],
                                                                     "edges": graph["edges"]}})
        assert _status(resp) == 409, _json(resp)
        assert _json(resp)["code"] == CODE_TEAM_ITEM_SHARED_OUTSIDE



class TestShareRoute:
    """``POST /api/teams/<id>/grants`` for a personal agent, through the app."""

    @pytest.fixture
    def client(self, pg_conn):
        from contextlib import ExitStack, contextmanager
        from unittest.mock import patch

        from docsgpt.app import app as flask_app

        @contextmanager
        def _yield():
            yield pg_conn

        flask_app.config["TESTING"] = True
        with ExitStack() as stack:
            for target in ("docsgpt.api.user.teams.routes.db_readonly", "docsgpt.api.user.teams.routes.db_session",
                           "docsgpt.api.user.team_authz.db_readonly"):
                stack.enter_context(patch(target, _yield))
            stack.enter_context(patch("docsgpt.api.user.teams.routes.publish_user_event"))
            stack.enter_context(patch("docsgpt.api.user.teams.routes._notify_resource_shared"))
            yield flask_app.test_client()

    @staticmethod
    def _share(client, team_id, agent_id, user="vera", **extra):
        from unittest.mock import patch

        with patch("docsgpt.app.handle_auth", return_value={"sub": user}), patch(
            "docsgpt.app.resolve_roles", return_value=["user"]
        ):
            return client.post(f"/api/teams/{team_id}/grants",
                               json={"resource_type": "agent", "resource_id": agent_id, **extra})

    @staticmethod
    def _grants(conn, agent_id):
        return conn.execute(
            text("SELECT team_id, target_user_id FROM team_resource_grants WHERE resource_id = CAST(:a AS uuid)"),
            {"a": agent_id},
        ).fetchall()

    def test_a_viewer_cant_share_a_teams_source_and_tool_with_another_team(self, client, pg_conn, w):
        aid = str(_agent(pg_conn, source_id=w["source"], tools=[w["tool"]])["id"])
        resp = self._share(client, w["dev"], aid)
        assert resp.status_code == 409, resp.get_json()
        assert resp.get_json()["error"] == CODE_USES_TEAM_ITEMS
        assert resp.get_json()["move_to"] is None
        assert self._grants(pg_conn, aid) == []

    def test_sharing_with_the_owning_team(self, client, pg_conn, w):
        aid = str(_agent(pg_conn, source_id=w["source"], tools=[w["tool"]])["id"])
        assert self._share(client, w["ops"], aid).status_code in (200, 201)
        assert len(self._grants(pg_conn, aid)) == 1

    def test_one_member_who_can_use_every_item(self, client, pg_conn, w):
        aid = str(_agent(pg_conn, source_id=w["source"], tools=[w["tool"]])["id"])
        assert self._share(client, w["dev"], aid, target_user_id="eddie").status_code in (200, 201)
        resp = self._share(client, w["dev"], aid, target_user_id="dan")
        assert resp.status_code == 409, resp.get_json()
        assert [row[1] for row in self._grants(pg_conn, aid)] == ["eddie"]


class TestTeamPromptOutsideAccess:
    """A team's prompt counts as the team's item: a personal agent using one gets no key, public link or
    webhook, and one can't be added to an agent that has one. A prompt a person lends keeps today's rule."""

    @staticmethod
    def _published(conn, **refs) -> str:
        return agent(conn, "vera", status="published", agent_type="classic", chunks=6, description="d", **refs)

    @staticmethod
    def _assert_refused(resp, name="Ops voice"):
        assert _status(resp) == 403, _json(resp)
        assert _json(resp)["code"] == "borrowed_resource"
        assert name in _json(resp)["message"]

    def test_no_public_link(self, app, pg_conn, w):
        from docsgpt.api.user.agents.sharing import ShareAgent

        aid = self._published(pg_conn, prompt_id=w["prompt"])
        resp = _call(app, pg_conn, ShareAgent, "put", "/api/share_agent", "vera", json={"id": aid, "shared": True})
        self._assert_refused(resp)
        assert not _row(pg_conn, aid).get("shared")

    def test_no_webhook(self, app, pg_conn, w):
        from docsgpt.api.user.agents.webhooks import AgentWebhook

        aid = self._published(pg_conn, prompt_id=w["prompt"])
        self._assert_refused(_call(app, pg_conn, AgentWebhook, "get", "/api/agent_webhook", "vera",
                                   query={"id": aid}))
        assert not _row(pg_conn, aid).get("incoming_webhook_token")

    def test_no_new_key(self, app, pg_conn, w):
        from docsgpt.api.user.agents.routes import RegenerateAgentKey

        aid = self._published(pg_conn, prompt_id=w["prompt"])
        self._assert_refused(_call(app, pg_conn, RegenerateAgentKey, "post", f"/api/regenerate_agent_key/{aid}",
                                   "vera", args=(aid,)))
        assert not _row(pg_conn, aid).get("key")

    def test_publishing_mints_no_key(self, app, pg_conn, w):
        aid = agent(pg_conn, "vera", agent_type="classic", chunks=6, description="d", prompt_id=w["prompt"])
        resp = _put(app, pg_conn, aid, {"status": "published"})
        assert _status(resp) == 200, _json(resp)
        assert _row(pg_conn, aid)["status"] == "published" and not _row(pg_conn, aid).get("key")

    def test_cant_be_added_to_an_agent_with_a_key(self, app, pg_conn, w):
        aid = self._published(pg_conn, key=f"k-{uuid.uuid4().hex}")
        self._assert_refused(_put(app, pg_conn, aid, {"prompt_id": w["prompt"]}))
        assert not _row(pg_conn, aid).get("prompt_id")

    def test_a_personally_lent_prompt_keeps_todays_rule(self, app, pg_conn, w):
        from docsgpt.api.user.agents.sharing import ShareAgent

        TeamMembersRepository(pg_conn).add_member(w["dev"], LENDER, role="team_viewer")
        lent = prompt(pg_conn, LENDER, "Lent voice")
        grant(pg_conn, w["dev"], "prompt", lent, LENDER, target="vera")
        aid = self._published(pg_conn, prompt_id=lent)
        resp = _call(app, pg_conn, ShareAgent, "put", "/api/share_agent", "vera", json={"id": aid, "shared": True})
        assert _status(resp) == 200, _json(resp)
