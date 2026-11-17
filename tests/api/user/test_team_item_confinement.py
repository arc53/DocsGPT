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

import pytest
from sqlalchemy import text

from docsgpt.api.user.agents.graph_checks import (
    CODE_USES_TEAM_ITEMS,
    agent_team_refs,
    team_confinement_refusal,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from tests.workspaces.move_support import agent, grant, prompt, source, team, tool

LENDER = "lena-lender"


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
        lent = source(pg_conn, LENDER, "Lent")
        grant(pg_conn, w["dev"], "source", lent, LENDER, target="vera")
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
        lent = source(pg_conn, LENDER, "Lent")
        grant(pg_conn, w["dev"], "source", lent, LENDER, target="vera")
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

