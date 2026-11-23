"""Move planning: what a move to a team (or out of one) takes along, what can't come, and who gains or loses.

The plan is read-only and carries a fingerprint the apply step checks.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
from docsgpt.workspaces.move import MoveError
from tests.workspaces.move_support import (
    agent, body, file, folder, grant, keyed, other_team, plan, prompt, source, team, tool, workflow,
)


def _custom_model(conn, owner) -> str:
    return str(UserCustomModelsRepository(conn).create(
        owner, "gpt-x", "My model", "https://models.example.com/v1", "sk-test",
    )["id"])


def _connection(conn, owner, auth_kind="oauth") -> str:
    return str(ConnectorSessionsRepository(conn).create(
        owner, "github", connector_key="github", auth_kind=auth_kind, account_label=owner,
    )["id"])


class TestDependencies:
    def test_an_agent_brings_its_own_source_tool_and_prompt(self, pg_conn):
        tid, _ = team(pg_conn)
        src, tl, pr = source(pg_conn, "eddie"), tool(pg_conn, "eddie"), prompt(pg_conn, "eddie")
        ag = agent(pg_conn, "eddie", source_id=src, tools=[tl], prompt_id=pr)
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert [(i["type"], i["id"]) for i in out["items"]] == [("agent", ag)]
        moves = keyed(out["moves_with"])
        for key in (("source", src), ("tool", tl), ("prompt", pr)):
            assert moves[key]["reason"] == "used_by_agent"
            assert moves[key]["via"] == {"type": "agent", "id": ag}
        assert out["cannot_move"] == []
        assert out["to"]["workspace"] == {"kind": "team", "team_id": tid, "name": "Ops"}

    def test_a_connected_account_tool_cant_come(self, pg_conn):
        tid, _ = team(pg_conn)
        tl = tool(pg_conn, "eddie", "github", connection_id=_connection(pg_conn, "eddie"))
        ag = agent(pg_conn, "eddie", tools=[tl])
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        entry = keyed(out["cannot_move"])[("tool", tl)]
        assert entry["reason"] == "connection_account"
        assert entry["effect"] == "removed_from_holder"
        assert ("tool", tl) not in keyed(out["moves_with"])

    def test_a_member_mode_connected_tool_comes(self, pg_conn):
        tid, _ = team(pg_conn)
        tl = tool(pg_conn, "eddie", "github", connection_id=_connection(pg_conn, "eddie"), credential_mode="member")
        ag = agent(pg_conn, "eddie", tools=[tl])
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert ("tool", tl) in keyed(out["moves_with"])

    def test_a_paired_device_tool_cant_come(self, pg_conn):
        tid, _ = team(pg_conn)
        tl = tool(pg_conn, "eddie", "remote_device")
        out = plan(pg_conn, "eddie", body(tid, [("tool", tl)]))
        assert out["items"] == []
        assert keyed(out["cannot_move"])[("tool", tl)] | {} == {
            "type": "tool", "id": tl, "name": "remote_device", "reason": "remote_device", "effect": "stays",
        }

    def test_a_connector_synced_source_cant_come(self, pg_conn):
        tid, _ = team(pg_conn)
        src = source(pg_conn, "eddie", type="connector:file")
        ag = agent(pg_conn, "eddie", source_id=src)
        entry = keyed(plan(pg_conn, "eddie", body(tid, [("agent", ag)]))["cannot_move"])[("source", src)]
        assert (entry["reason"], entry["effect"]) == ("connector_synced", "removed_from_holder")

    def test_a_personal_custom_model_is_removed(self, pg_conn):
        tid, _ = team(pg_conn)
        model = _custom_model(pg_conn, "eddie")
        ag = agent(pg_conn, "eddie", default_model_id=model, models=[model, "gpt-4o"])
        entry = keyed(plan(pg_conn, "eddie", body(tid, [("agent", ag)]))["cannot_move"])[("model", model)]
        assert (entry["reason"], entry["effect"], entry["name"]) == ("custom_model", "removed_from_holder", "My model")

    def test_a_teammates_sponsored_tool_is_removed_not_moved(self, pg_conn):
        tid, _ = team(pg_conn)
        other = other_team(pg_conn)
        theirs = tool(pg_conn, "olga")
        grant(pg_conn, other, "tool", theirs, "olga", level="editor")
        ag = agent(pg_conn, "eddie", tools=[theirs], resource_sponsors={f"tool:{theirs}": "olga"})
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        entry = keyed(out["cannot_move"])[("tool", theirs)]
        assert (entry["reason"], entry["effect"]) == ("not_yours", "removed_from_holder")
        assert ("tool", theirs) not in keyed(out["moves_with"])

    def test_a_workflow_with_two_agents_moves_both(self, pg_conn):
        tid, _ = team(pg_conn)
        tl = tool(pg_conn, "eddie")
        wid = workflow(pg_conn, "eddie", nodes=[{"tools": [tl], "sources": [], "folders": []}])
        first = agent(pg_conn, "eddie", "First", agent_type="workflow", workflow_id=wid)
        second = agent(pg_conn, "eddie", "Second", agent_type="workflow", workflow_id=wid)
        out = plan(pg_conn, "eddie", body(tid, [("agent", first)]))
        moves = keyed(out["moves_with"])
        assert moves[("agent", second)]["reason"] == "same_workflow"
        assert moves[("tool", tl)]["reason"] == "used_by_agent"

    def test_a_workflow_node_custom_model_is_removed(self, pg_conn):
        tid, _ = team(pg_conn)
        model = _custom_model(pg_conn, "eddie")
        wid = workflow(pg_conn, "eddie", nodes=[{"config": {"model_id": model}}])
        ag = agent(pg_conn, "eddie", agent_type="workflow", workflow_id=wid)
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert keyed(out["cannot_move"])[("model", model)]["reason"] == "custom_model"

    def test_a_live_knowledge_folder_comes_with_its_sources(self, pg_conn):
        tid, _ = team(pg_conn)
        kf = folder(pg_conn, "eddie", "Docs")
        src = source(pg_conn, "eddie")
        file(pg_conn, "eddie", "source", src, kf)
        ag = agent(pg_conn, "eddie", knowledge_folder_ids=[kf])
        moves = keyed(plan(pg_conn, "eddie", body(tid, [("agent", ag)]))["moves_with"])
        assert moves[("folder", kf)]["reason"] == "used_by_agent"
        assert moves[("source", src)] | {} == {
            "type": "source", "id": src, "name": "Docs", "via": {"type": "folder", "id": kf}, "reason": "in_folder",
        }


class TestFolders:
    def test_a_subtree_moves_and_leaves_others_items(self, pg_conn):
        tid, _ = team(pg_conn)
        other = other_team(pg_conn)
        top = folder(pg_conn, "eddie", "Project")
        sub = folder(pg_conn, "eddie", "Specs", parent=top)
        ag = agent(pg_conn, "eddie")
        src = source(pg_conn, "eddie")
        theirs = prompt(pg_conn, "olga")
        grant(pg_conn, other, "prompt", theirs, "olga")
        file(pg_conn, "eddie", "agent", ag, top)
        file(pg_conn, "eddie", "source", src, sub)
        file(pg_conn, "eddie", "prompt", theirs, sub)
        out = plan(pg_conn, "eddie", body(tid, [("folder", top)]))
        assert [(i["type"], i["id"]) for i in out["items"]] == [("folder", top)]
        moves = keyed(out["moves_with"])
        assert moves[("folder", sub)]["reason"] == "in_folder"
        assert moves[("agent", ag)]["via"] == {"type": "folder", "id": top}
        assert moves[("source", src)]["via"] == {"type": "folder", "id": sub}
        entry = keyed(out["cannot_move"])[("prompt", theirs)]
        assert (entry["reason"], entry["effect"]) == ("not_yours", "stays")

    def test_a_name_clash_in_the_team_is_renamed(self, pg_conn):
        tid, principal = team(pg_conn)
        folder(pg_conn, principal, "Project")
        top = folder(pg_conn, "eddie", "project")
        out = plan(pg_conn, "eddie", body(tid, [("folder", top)]))
        assert out["renames"] == [{"type": "folder", "id": top, "from": "project", "to": "project (2)"}]

    def test_a_slug_clash_in_the_team_is_listed(self, pg_conn):
        tid, principal = team(pg_conn)
        agent(pg_conn, principal, "Theirs", slug="helper")
        clashing = agent(pg_conn, "eddie", slug="helper")
        free = agent(pg_conn, "eddie", "Other", slug="other")
        out = plan(pg_conn, "eddie", body(tid, [("agent", clashing), ("agent", free)]))
        assert out["renames"] == [{"type": "agent", "id": clashing, "field": "slug", "from": "helper", "to": "helper-2"}]

    def test_two_moving_agents_never_take_the_same_slug(self, pg_conn):
        tid, principal = team(pg_conn)
        agent(pg_conn, principal, "Theirs", slug="helper")
        first = agent(pg_conn, "eddie", slug="helper")
        second = agent(pg_conn, "eddie", "Two", slug="helper-2")
        out = plan(pg_conn, "eddie", body(tid, [("agent", first), ("agent", second)]))
        to = {r["id"]: r["to"] for r in out["renames"]}
        assert to[first] == "helper-2"
        assert to[second] not in ("helper", "helper-2")

    def test_the_fingerprint_covers_a_slug_rename(self, pg_conn):
        tid, principal = team(pg_conn)
        ag = agent(pg_conn, "eddie", slug="helper")
        before = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert before["renames"] == []
        agent(pg_conn, principal, "Theirs", slug="helper")
        assert plan(pg_conn, "eddie", body(tid, [("agent", ag)]))["fingerprint"] != before["fingerprint"]

    def test_into_a_team_folder(self, pg_conn):
        tid, principal = team(pg_conn)
        target = folder(pg_conn, principal, "Shared")
        pr = prompt(pg_conn, "eddie")
        out = plan(pg_conn, "eddie", body(tid, [("prompt", pr)], folder_id=target))
        assert out["to"]["folder"] == {"id": target, "name": "Shared", "path": [{"id": target, "name": "Shared"}]}

    def test_a_personal_folder_as_target_is_not_found(self, pg_conn):
        tid, _ = team(pg_conn)
        mine = folder(pg_conn, "eddie", "Mine")
        pr = prompt(pg_conn, "eddie")
        with pytest.raises(MoveError) as err:
            plan(pg_conn, "eddie", body(tid, [("prompt", pr)], folder_id=mine))
        assert (err.value.status, err.value.code) == (404, "folder_not_found")


class TestWhoAndWhat:
    def test_access_gained_and_lost(self, pg_conn):
        tid, _ = team(pg_conn)
        other = other_team(pg_conn)
        ag = agent(pg_conn, "eddie")
        grant(pg_conn, other, "agent", ag, "eddie")
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert out["access"]["gains"] == {"total": 3, "viewers": 1, "editors": 0, "admins": 2}
        # vera is in both teams; olga is only in Other.
        assert [(p["user_id"], p["via"]) for p in out["access"]["loses"]] == [("olga", "Other")]

    def test_schedules_and_outside_access_are_kept(self, pg_conn):
        tid, _ = team(pg_conn)
        ag = agent(pg_conn, "eddie", key="k-" + tid[:8], status="published")
        sched = SchedulesRepository(pg_conn).create("vera", ag, "recurring", "Ping", cron="0 9 * * *")
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert out["kept"]["schedules"] == [
            {"id": str(sched["id"]), "agent_id": ag, "paid_by": {"user_id": "vera", "label": out["kept"]["schedules"][0]
                                                                  ["paid_by"]["label"]}}
        ]
        outside = out["kept"]["outside_access"]
        assert (outside["api_key"], outside["public_link"], outside["webhook"]) == (True, False, False)
        assert outside["paid_by"]["user_id"] == "eddie"

    def test_only_the_movers_own_conversations_are_counted(self, pg_conn):
        tid, _ = team(pg_conn)
        ag = agent(pg_conn, "eddie")
        convs = ConversationsRepository(pg_conn)
        convs.create("vera", "c1", agent_id=ag)
        convs.create("eddie", "c2", agent_id=ag)
        convs.create("olga", "c3", agent_id=ag)
        assert plan(pg_conn, "eddie", body(tid, [("agent", ag)]))["conversations_switched"] == 1

    def test_a_published_agent_left_behind_borrows(self, pg_conn):
        tid, _ = team(pg_conn)
        src = source(pg_conn, "eddie")
        moving = agent(pg_conn, "eddie", "Moving", source_id=src)
        staying = agent(pg_conn, "eddie", "Staying", source_id=src, key="key-staying", status="published")
        out = plan(pg_conn, "eddie", body(tid, [("agent", moving)]))
        assert out["borrowing_agents"] == [{"id": staying, "name": "Staying", "published": True}]

    def test_the_fingerprint_is_stable_and_follows_the_data(self, pg_conn):
        tid, _ = team(pg_conn)
        ag = agent(pg_conn, "eddie")
        first = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert plan(pg_conn, "eddie", body(tid, [("agent", ag)]))["fingerprint"] == first["fingerprint"]
        agent(pg_conn, "eddie", "Again")  # unrelated: same plan
        assert plan(pg_conn, "eddie", body(tid, [("agent", ag)]))["fingerprint"] == first["fingerprint"]
        pg_conn.execute(text("UPDATE agents SET tools = CAST(:t AS jsonb) WHERE id = CAST(:i AS uuid)"),
                        {"t": f'["{tool(pg_conn, "eddie")}"]', "i": ag})
        assert plan(pg_conn, "eddie", body(tid, [("agent", ag)]))["fingerprint"] != first["fingerprint"]


class TestWhoMayMove:
    def test_a_viewer_target_is_refused(self, pg_conn):
        tid, _ = team(pg_conn)
        ag = agent(pg_conn, "vera")
        with pytest.raises(MoveError) as err:
            plan(pg_conn, "vera", body(tid, [("agent", ag)]))
        assert (err.value.status, err.value.code) == (403, "workspace_role_required")

    def test_a_non_member_target_is_not_found(self, pg_conn):
        tid, _ = team(pg_conn)
        ag = agent(pg_conn, "olga")
        with pytest.raises(MoveError) as err:
            plan(pg_conn, "olga", body(tid, [("agent", ag)]))
        assert (err.value.status, err.value.code) == (404, "workspace_not_found")

    def test_someone_elses_item_is_listed_never_moved(self, pg_conn):
        tid, _ = team(pg_conn)
        other = other_team(pg_conn)
        theirs = prompt(pg_conn, "olga")
        grant(pg_conn, other, "prompt", theirs, "olga", level="editor")
        out = plan(pg_conn, "eddie", body(tid, [("prompt", theirs)]))
        assert out["items"] == [] and out["moves_with"] == []
        assert keyed(out["cannot_move"])[("prompt", theirs)]["reason"] == "not_yours"

    def test_an_item_the_mover_cant_see_is_not_found(self, pg_conn):
        tid, _ = team(pg_conn)
        hidden = prompt(pg_conn, "olga")
        with pytest.raises(MoveError) as err:
            plan(pg_conn, "eddie", body(tid, [("prompt", hidden)]))
        assert err.value.status == 404

    def test_move_out_by_an_admin(self, pg_conn):
        tid, principal = team(pg_conn)
        src = source(pg_conn, principal)
        ag = agent(pg_conn, principal, source_id=src)
        out = plan(pg_conn, "adam", body("personal", [("agent", ag)]))
        assert out["to"]["workspace"] == {"kind": "personal", "team_id": None, "name": "Personal"}
        assert keyed(out["moves_with"])[("source", src)]["reason"] == "used_by_agent"
        assert {p["user_id"] for p in out["access"]["loses"]} == {"alice", "eddie", "vera"}

    def test_move_out_is_refused_for_an_editor(self, pg_conn):
        tid, principal = team(pg_conn)
        ag = agent(pg_conn, principal)
        with pytest.raises(MoveError) as err:
            plan(pg_conn, "eddie", body("personal", [("agent", ag)]))
        assert (err.value.status, err.value.code) == (403, "workspace_role_required")

    def test_move_out_of_a_folder_needs_admin(self, pg_conn):
        tid, principal = team(pg_conn)
        top = folder(pg_conn, principal, "Team stuff")
        with pytest.raises(MoveError) as err:
            plan(pg_conn, "eddie", body("personal", [("folder", top)]))
        assert err.value.status == 403
        assert keyed(plan(pg_conn, "adam", body("personal", [("folder", top)]))["items"]) == {
            ("folder", top): {"type": "folder", "id": top, "name": "Team stuff"}
        }

    def test_move_out_with_a_team_agent_left_behind_borrows(self, pg_conn):
        tid, principal = team(pg_conn)
        src = source(pg_conn, principal)
        moving = agent(pg_conn, principal, "Moving", source_id=src)
        staying = agent(pg_conn, principal, "Staying", source_id=src)
        out = plan(pg_conn, "adam", body("personal", [("agent", moving)]))
        assert out["borrowing_agents"] == [{"id": staying, "name": "Staying", "published": False}]

    def test_moving_personal_items_to_personal(self, pg_conn):
        team(pg_conn)
        mine = prompt(pg_conn, "eddie")
        with pytest.raises(MoveError) as err:
            plan(pg_conn, "eddie", body("personal", [("prompt", mine)]))
        assert (err.value.status, err.value.code) == (400, "already_in_workspace")
        with pytest.raises(MoveError) as err:
            plan(pg_conn, "eddie", body("personal", [("prompt", prompt(pg_conn, "olga"))]))
        assert err.value.status == 404

    def test_a_folder_too_deep_for_the_target(self, pg_conn):
        tid, principal = team(pg_conn)
        deep = folder(pg_conn, principal, "B", parent=folder(pg_conn, principal, "A"))
        top = folder(pg_conn, "eddie", "Top")
        folder(pg_conn, "eddie", "Child", parent=top)
        with pytest.raises(MoveError) as err:
            plan(pg_conn, "eddie", body(tid, [("folder", top)], folder_id=deep))
        assert (err.value.status, err.value.code) == (400, "folder_too_deep")

    def test_bad_requests(self, pg_conn):
        from docsgpt.workspaces.move import parse_move_request

        for bad in ({}, {"to": {"workspace": "personal"}, "items": []},
                    {"to": {"workspace": "personal"}, "items": [{"type": "car", "id": "x"}]}):
            with pytest.raises(MoveError) as err:
                parse_move_request(bad)
            assert err.value.status == 400
