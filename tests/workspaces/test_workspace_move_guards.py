"""Move guards: outside access never ends up serving a team's items, and a move never drops knowledge silently.

* Any agent with outside access (key, live link, webhook) left behind that uses
  a moved item refuses a move in, whoever owns it; the mover sees the ones they
  can open by name and a count of the rest.
* Bringing outside access into a team takes a team Admin.
* A folder an agent reads as knowledge brings its sub-folders and sources, not
  the agents, tools and prompts filed in it.
* Moving out, a team agent that reads a moved source through a folder refuses.
* Workflow sponsors are cleared; unreadable credentials are planned around, and
  apply re-seals the tool's current secrets.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.security.encryption import CredentialDecryptionError, decrypt_credentials, encrypt_credentials
from docsgpt.storage.db.repositories.folders import FolderItemsRepository
from docsgpt.workspaces.move import MoveError, apply_move, parse_move_request
from tests.workspaces.move_support import (
    agent, apply, body, file, folder, grant, keyed, owner_of, plan, prompt, source, team, tool, workflow,
)


def _refused(conn, mover, request_body) -> MoveError:
    with pytest.raises(MoveError) as err:
        apply(conn, mover, request_body)
    return err.value


class TestOutsideAccessNeverBorrows:
    def test_someone_elses_published_agent_using_a_moved_source_refuses(self, pg_conn):
        tid, _ = team(pg_conn)
        src = source(pg_conn, "eddie")
        theirs = agent(pg_conn, "adam", "Adam's bot", extra_source_ids=[src], key="k-adam",
                       status="published", resource_sponsors={f"source:{src}": "eddie"})
        grant(pg_conn, tid, "agent", theirs, "adam", target="eddie", level="editor")
        out = plan(pg_conn, "eddie", body(tid, [("source", src)]))
        assert out["borrowing_agents"] == [{"id": theirs, "name": "Adam's bot", "published": True}]
        assert out["borrowing_others"] == 0
        err = _refused(pg_conn, "eddie", body(tid, [("source", src)]))
        assert (err.status, err.code) == (409, "move_would_borrow")
        assert err.extra["agents"] == [{"id": theirs, "name": "Adam's bot", "published": True}]
        assert owner_of(pg_conn, "source", src) == "eddie"

    def test_an_agent_the_mover_cant_see_is_counted_not_named(self, pg_conn):
        tid, _ = team(pg_conn)
        tl = tool(pg_conn, "eddie")
        agent(pg_conn, "olga", "Secret", tools=[tl], incoming_webhook_token="wh-olga")
        out = plan(pg_conn, "eddie", body(tid, [("tool", tl)]))
        assert out["borrowing_agents"] == [] and out["borrowing_others"] == 1
        err = _refused(pg_conn, "eddie", body(tid, [("tool", tl)]))
        assert (err.status, err.code, err.extra["agents"], err.extra["others"]) == (409, "move_would_borrow", [], 1)
        assert "Secret" not in err.message
        assert owner_of(pg_conn, "tool", tl) == "eddie"

    def test_a_workflow_node_reference_refuses(self, pg_conn):
        tid, _ = team(pg_conn)
        src = source(pg_conn, "eddie")
        wid = workflow(pg_conn, "olga", nodes=[{"config": {"sources": [src]}}])
        agent(pg_conn, "olga", "Flow bot", agent_type="workflow", workflow_id=wid, shared=True, shared_token="tok-o")
        assert plan(pg_conn, "eddie", body(tid, [("source", src)]))["borrowing_others"] == 1
        assert _refused(pg_conn, "eddie", body(tid, [("source", src)])).code == "move_would_borrow"

    def test_a_live_knowledge_folder_refuses(self, pg_conn):
        tid, _ = team(pg_conn)
        kf = folder(pg_conn, "eddie", "Docs")
        mine = agent(pg_conn, "eddie", "Reader", knowledge_folder_ids=[kf], key="k-reader", status="published")
        err = _refused(pg_conn, "eddie", body(tid, [("folder", kf)]))
        assert err.code == "move_would_borrow" and [a["id"] for a in err.extra["agents"]] == [mine]

    def test_a_prompt_used_by_a_published_agent_refuses(self, pg_conn):
        tid, _ = team(pg_conn)
        pr = prompt(pg_conn, "eddie")
        agent(pg_conn, "eddie", "Prompted", prompt_id=pr, key="k-prompted", status="published")
        assert _refused(pg_conn, "eddie", body(tid, [("prompt", pr)])).code == "move_would_borrow"

    def test_an_unpublished_agent_of_someone_else_does_not_refuse(self, pg_conn):
        tid, principal = team(pg_conn)
        src = source(pg_conn, "eddie")
        agent(pg_conn, "olga", "Draft", source_id=src)
        apply(pg_conn, "eddie", body(tid, [("source", src)]))
        assert owner_of(pg_conn, "source", src) == principal


class TestOutsideAccessNeedsAdmin:
    def test_an_editor_moving_a_published_agent_is_refused(self, pg_conn):
        tid, _ = team(pg_conn)
        ag = agent(pg_conn, "eddie", "Public", key="k-public", status="published")
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert out["needs_admin"] == [{"id": ag, "name": "Public"}]
        err = _refused(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert (err.status, err.code, err.extra["agents"]) == (403, "move_needs_admin", [{"id": ag, "name": "Public"}])
        assert owner_of(pg_conn, "agent", ag) == "eddie"

    def test_an_agent_that_comes_along_counts_too(self, pg_conn):
        tid, _ = team(pg_conn)
        wid = workflow(pg_conn, "eddie")
        first = agent(pg_conn, "eddie", "First", agent_type="workflow", workflow_id=wid)
        hooked = agent(pg_conn, "eddie", "Hooked", agent_type="workflow", workflow_id=wid,
                       incoming_webhook_token="wh-hooked")
        assert plan(pg_conn, "eddie", body(tid, [("agent", first)]))["needs_admin"] == [
            {"id": hooked, "name": "Hooked"}
        ]

    def test_an_admin_may(self, pg_conn):
        tid, principal = team(pg_conn)
        ag = agent(pg_conn, "adam", "Public", shared=True, shared_token="tok-adam")
        assert plan(pg_conn, "adam", body(tid, [("agent", ag)]))["needs_admin"] == []
        apply(pg_conn, "adam", body(tid, [("agent", ag)]))
        assert owner_of(pg_conn, "agent", ag) == principal

    def test_without_outside_access_an_editor_may(self, pg_conn):
        tid, principal = team(pg_conn)
        ag = agent(pg_conn, "eddie", shared=True)  # a switched-on link without a token is not live
        assert plan(pg_conn, "eddie", body(tid, [("agent", ag)]))["needs_admin"] == []
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert owner_of(pg_conn, "agent", ag) == principal


class TestKnowledgeFolders:
    def test_a_knowledge_folder_brings_sources_not_agents_tools_or_prompts(self, pg_conn):
        tid, principal = team(pg_conn)
        kf = folder(pg_conn, "eddie", "Docs")
        sub = folder(pg_conn, "eddie", "More", parent=kf)
        src, deep = source(pg_conn, "eddie", "A"), source(pg_conn, "eddie", "B")
        other_agent, tl, pr = agent(pg_conn, "eddie", "Unrelated"), tool(pg_conn, "eddie"), prompt(pg_conn, "eddie")
        file(pg_conn, "eddie", "source", src, kf)
        file(pg_conn, "eddie", "source", deep, sub)
        for kind, item in (("agent", other_agent), ("tool", tl), ("prompt", pr)):
            file(pg_conn, "eddie", kind, item, kf)
        ag = agent(pg_conn, "eddie", knowledge_folder_ids=[kf])
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        moves = keyed(out["moves_with"])
        assert {("folder", kf), ("folder", sub), ("source", src), ("source", deep)} <= set(moves)
        cannot = keyed(out["cannot_move"])
        for key in (("agent", other_agent), ("tool", tl), ("prompt", pr)):
            assert key not in moves
            assert (cannot[key]["reason"], cannot[key]["effect"]) == ("in_knowledge_folder", "stays")
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert owner_of(pg_conn, "folder", kf) == principal and owner_of(pg_conn, "source", deep) == principal
        items = FolderItemsRepository(pg_conn)
        for kind, item in (("agent", other_agent), ("tool", tl), ("prompt", pr)):
            assert owner_of(pg_conn, kind, item) == "eddie"
            assert items.filing("eddie", kind, item) is None

    def test_an_item_the_agent_also_uses_still_moves(self, pg_conn):
        tid, principal = team(pg_conn)
        kf = folder(pg_conn, "eddie", "Docs")
        tl = tool(pg_conn, "eddie")
        file(pg_conn, "eddie", "tool", tl, kf)
        ag = agent(pg_conn, "eddie", knowledge_folder_ids=[kf], tools=[tl])
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert ("tool", tl) in keyed(out["moves_with"]) and ("tool", tl) not in keyed(out["cannot_move"])
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert owner_of(pg_conn, "tool", tl) == principal
        assert FolderItemsRepository(pg_conn).filing(principal, "tool", tl) == kf

    def test_a_dragged_folder_still_takes_everything(self, pg_conn):
        tid, principal = team(pg_conn)
        top = folder(pg_conn, "eddie", "Project")
        kf = folder(pg_conn, "eddie", "Docs", parent=top)
        filed = agent(pg_conn, "eddie", "Filed")
        file(pg_conn, "eddie", "agent", filed, kf)
        ag = agent(pg_conn, "eddie", knowledge_folder_ids=[kf])
        # The agent comes first, so the folder is reached as its knowledge before the dragged tree.
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag), ("folder", top)]))
        assert ("agent", filed) in keyed(out["moves_with"]) and not out["cannot_move"]
        apply(pg_conn, "eddie", body(tid, [("agent", ag), ("folder", top)]))
        assert owner_of(pg_conn, "agent", filed) == principal


class TestMoveOutFolderUse:
    @pytest.mark.parametrize("nested", [False, True])
    def test_a_team_agent_reading_it_through_a_folder_refuses(self, pg_conn, nested):
        tid, principal = team(pg_conn)
        top = folder(pg_conn, principal, "Team docs")
        holder = folder(pg_conn, principal, "Deeper", parent=top) if nested else top
        src = source(pg_conn, principal)
        file(pg_conn, principal, "source", src, holder)
        reader = agent(pg_conn, principal, "Reader", knowledge_folder_ids=[top])
        out = plan(pg_conn, "adam", body("personal", [("source", src)]))
        assert out["borrowing_agents"] == [{"id": reader, "name": "Reader", "published": False}]
        err = _refused(pg_conn, "adam", body("personal", [("source", src)]))
        assert err.code == "move_would_borrow"
        assert owner_of(pg_conn, "source", src) == principal
        assert FolderItemsRepository(pg_conn).filing(principal, "source", src) == holder

    def test_a_workflow_node_reading_the_folder_refuses(self, pg_conn):
        tid, principal = team(pg_conn)
        top = folder(pg_conn, principal, "Team docs")
        src = source(pg_conn, principal)
        file(pg_conn, principal, "source", src, top)
        wid = workflow(pg_conn, principal, nodes=[{"config": {"folders": [top]}}])
        flow = agent(pg_conn, principal, "Flow", agent_type="workflow", workflow_id=wid)
        out = plan(pg_conn, "adam", body("personal", [("source", src)]))
        assert [a["id"] for a in out["borrowing_agents"]] == [flow]

    def test_a_source_in_an_unread_folder_moves(self, pg_conn):
        tid, principal = team(pg_conn)
        top = folder(pg_conn, principal, "Team docs")
        src = source(pg_conn, principal)
        file(pg_conn, principal, "source", src, top)
        apply(pg_conn, "adam", body("personal", [("source", src)]))
        assert owner_of(pg_conn, "source", src) == "adam"


class TestWorkflowSponsors:
    def test_are_cleared(self, pg_conn):
        tid, _ = team(pg_conn)
        wid = workflow(pg_conn, "eddie")
        pg_conn.execute(text("UPDATE workflows SET resource_sponsors = CAST(:s AS jsonb) WHERE id = CAST(:w AS uuid)"),
                        {"s": '{"tool:00000000-0000-0000-0000-000000000001": "olga"}', "w": wid})
        ag = agent(pg_conn, "eddie", agent_type="workflow", workflow_id=wid)
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        sponsors = pg_conn.execute(text("SELECT resource_sponsors FROM workflows WHERE id = CAST(:w AS uuid)"),
                                   {"w": wid}).scalar()
        assert sponsors == {}


class TestCredentials:
    def test_an_unreadable_secret_is_planned_around(self, pg_conn):
        tid, principal = team(pg_conn)
        broken = tool(pg_conn, "eddie", "brave",
                      config={"encrypted_credentials": encrypt_credentials({"k": "v"}, "somebody-else")})
        fine = tool(pg_conn, "eddie")
        ag = agent(pg_conn, "eddie", tools=[broken, fine])
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        entry = keyed(out["cannot_move"])[("tool", broken)]
        assert (entry["reason"], entry["effect"]) == ("credentials_unreadable", "removed_from_holder")
        dragged = keyed(plan(pg_conn, "eddie", body(tid, [("tool", broken)]))["cannot_move"])[("tool", broken)]
        assert (dragged["reason"], dragged["effect"]) == ("credentials_unreadable", "stays")
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert owner_of(pg_conn, "tool", broken) == "eddie"
        assert owner_of(pg_conn, "tool", fine) == principal
        tools = pg_conn.execute(text("SELECT tools FROM agents WHERE id = CAST(:a AS uuid)"), {"a": ag}).scalar()
        assert tools == [fine]

    def test_a_secret_that_fails_at_apply_answers_409_naming_the_tool(self, pg_conn):
        tid, _ = team(pg_conn)
        tl = tool(pg_conn, "eddie", "brave", display_name="Brave",
                  config={"encrypted_credentials": encrypt_credentials({"k": "v"}, "eddie")})
        request = body(tid, [("tool", tl)])
        fp = plan(pg_conn, "eddie", request)["fingerprint"]
        with patch("docsgpt.security.encryption.reseal_for_owner", side_effect=CredentialDecryptionError("boom")):
            with pytest.raises(MoveError) as err:
                apply_move(pg_conn, "eddie", parse_move_request({**request, "fingerprint": fp}))
        assert (err.value.status, err.value.code) == (409, "credentials_unreadable")
        assert err.value.extra["tools"] == [{"id": tl, "name": "Brave"}]
        assert owner_of(pg_conn, "tool", tl) == "eddie"

    def test_apply_reseals_the_secret_as_it_is_now(self, pg_conn):
        from docsgpt.workspaces import move

        tid, principal = team(pg_conn)
        tl = tool(pg_conn, "eddie", "brave", config={"encrypted_credentials": encrypt_credentials({"k": "old"}, "eddie")})
        request = body(tid, [("tool", tl)])
        fp = plan(pg_conn, "eddie", request)["fingerprint"]
        real_plan = move.plan_move

        def plan_then_edit(conn, mover, req):
            planned = real_plan(conn, mover, req)
            # Someone saves a new key after the plan read the row.
            conn.execute(
                text("UPDATE user_tools SET config = CAST(:c AS jsonb) WHERE id = CAST(:i AS uuid)"),
                {"c": f'{{"encrypted_credentials": "{encrypt_credentials({"k": "new"}, "eddie")}"}}', "i": tl},
            )
            return planned

        with patch("docsgpt.workspaces.move.plan_move", side_effect=plan_then_edit):
            apply_move(pg_conn, "eddie", parse_move_request({**request, "fingerprint": fp}))
        config = pg_conn.execute(text("SELECT config FROM user_tools WHERE id = CAST(:i AS uuid)"), {"i": tl}).scalar()
        assert decrypt_credentials(config["encrypted_credentials"], principal) == {"k": "new"}

