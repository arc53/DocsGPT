"""Applying a move: one transaction that re-owns what the plan named, and only that.

Grants and switches go, secrets are re-sealed for the new owner, filings follow
the move, members' chats follow the agent, schedules keep their payer and outside
access keeps running on the mover. A mismatched fingerprint or a borrowing
published agent refuses the move; a failure part-way leaves everything as it was.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.agents.tool_executor import API_TOOL_SECRETS_KEY
from docsgpt.api.user.resource_access import set_settings
from docsgpt.security.encryption import (
    CredentialDecryptionError,
    decrypt_credentials,
    decrypt_json,
    encrypt_credentials,
    encrypt_json,
)
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.user_tool_preferences import UserToolPreferencesRepository
from docsgpt.workspaces.move import MoveError, apply_move, parse_move_request
from tests.workspaces.move_support import (
    agent, apply, body, file, folder, grant, other_team, owner_of, plan, prompt, source, team, tool, workflow,
)


def _row(conn, table, item_id) -> dict:
    return dict(conn.execute(text(f"SELECT * FROM {table} WHERE id = CAST(:i AS uuid)"), {"i": item_id})
                .mappings().one())


def _grants(conn, item_id) -> int:
    return conn.execute(text("SELECT count(*) FROM team_resource_grants WHERE resource_id = CAST(:i AS uuid)"),
                        {"i": item_id}).scalar()


def _switches(conn, item_id) -> int:
    return conn.execute(text("SELECT count(*) FROM resource_share_settings WHERE resource_id = CAST(:i AS uuid)"),
                        {"i": item_id}).scalar()


def _events(conn, event) -> list[dict]:
    rows = conn.execute(text("SELECT actor_id, metadata FROM auth_events WHERE event = :e ORDER BY id"),
                        {"e": event}).mappings().all()
    return [dict(r) for r in rows]


class TestMoveIn:
    def test_the_agent_and_its_dependencies_belong_to_the_team(self, pg_conn):
        tid, principal = team(pg_conn)
        src, tl, pr = source(pg_conn, "eddie"), tool(pg_conn, "eddie"), prompt(pg_conn, "eddie")
        ag = agent(pg_conn, "eddie", source_id=src, tools=[tl], prompt_id=pr)
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        for kind, item in (("agent", ag), ("source", src), ("tool", tl), ("prompt", pr)):
            assert owner_of(pg_conn, kind, item) == principal
        row = _row(pg_conn, "agents", ag)
        assert row["created_by"] == "eddie"
        assert str(row["source_id"]) == src and row["tools"] == [tl] and str(row["prompt_id"]) == pr

    def test_grants_and_switches_are_deleted(self, pg_conn):
        tid, _ = team(pg_conn)
        other = other_team(pg_conn)
        ag = agent(pg_conn, "eddie")
        grant(pg_conn, other, "agent", ag, "eddie")
        grant(pg_conn, tid, "agent", ag, "eddie")
        set_settings(pg_conn, "agent", ag, {"editors_can_share": True}, "eddie")
        assert _grants(pg_conn, ag) == 2 and _switches(pg_conn, ag) == 1
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert _grants(pg_conn, ag) == 0 and _switches(pg_conn, ag) == 0

    def test_credentials_are_resealed_and_decrypt_under_the_team(self, pg_conn):
        tid, principal = team(pg_conn)
        v1 = tool(pg_conn, "eddie", "brave", config={"encrypted_credentials": encrypt_credentials({"k": "v1"}, "eddie")})
        v2 = tool(pg_conn, "eddie", "brave", config={"encrypted_credentials": encrypt_json({"k": "v2"}, "eddie")})
        api = tool(pg_conn, "eddie", "api_tool", config={
            "actions": {"get": {"url": "https://api.example.com", "headers": {"properties": {
                "Authorization": {"value": "", "has_value": True}}}}},
            API_TOOL_SECRETS_KEY: encrypt_credentials({"get": {"headers": {"Authorization": "Bearer s"}}}, "eddie"),
        })
        apply(pg_conn, "eddie", body(tid, [("tool", v1), ("tool", v2), ("tool", api)]))
        cfg = _row(pg_conn, "user_tools", v1)["config"]
        assert decrypt_credentials(cfg["encrypted_credentials"], principal) == {"k": "v1"}
        cfg = _row(pg_conn, "user_tools", v2)["config"]
        assert decrypt_json(cfg["encrypted_credentials"], principal) == {"k": "v2"}
        with pytest.raises(CredentialDecryptionError):
            decrypt_json(cfg["encrypted_credentials"], "eddie")
        cfg = _row(pg_conn, "user_tools", api)["config"]
        assert decrypt_credentials(cfg[API_TOOL_SECRETS_KEY], principal) == {
            "get": {"headers": {"Authorization": "Bearer s"}}
        }

    def test_a_key_based_mcp_server_carries_its_secret_without_a_connection(self, pg_conn):
        tid, principal = team(pg_conn)
        conn_row = ConnectorSessionsRepository(pg_conn).create(
            "eddie", "custom_mcp", connector_key="custom_mcp", auth_kind="api_key",
            server_url="https://mcp.example.com", account_label="mcp.example.com",
            encrypted_credentials=encrypt_json({"credentials": {"bearer_token": "tok"}}, "eddie"),
        )
        mcp = tool(pg_conn, "eddie", "mcp_tool", config={"server_url": "https://mcp.example.com/mcp",
                                                          "auth_type": "bearer"},
                   connection_id=str(conn_row["id"]))
        apply(pg_conn, "eddie", body(tid, [("tool", mcp)]))
        row = _row(pg_conn, "user_tools", mcp)
        assert row["connection_id"] is None
        assert decrypt_credentials(row["config"]["encrypted_credentials"], principal) == {"bearer_token": "tok"}

    def test_the_movers_chat_switch_becomes_their_preference(self, pg_conn):
        tid, _ = team(pg_conn)
        tl = tool(pg_conn, "eddie", status=True)
        apply(pg_conn, "eddie", body(tid, [("tool", tl)]))
        assert _row(pg_conn, "user_tools", tl)["status"] is False
        assert UserToolPreferencesRepository(pg_conn).in_chat_many("eddie", [tl]) == {tl: True}

    def test_slug_clash_gets_a_suffix_and_the_avatar_is_copied(self, pg_conn):
        tid, principal = team(pg_conn)
        agent(pg_conn, principal, "Theirs", slug="helper")
        ag = agent(pg_conn, "eddie", slug="helper", image="inputs/eddie/attachments/a_face.png")
        copied = f"inputs/{principal}/attachments/b_face.png"
        with patch("docsgpt.workspaces.move.copy_agent_image_for_user", return_value=copied) as copy:
            apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        row = _row(pg_conn, "agents", ag)
        assert row["slug"] == "helper-2"
        assert row["image"] == copied
        assert copy.call_args.args[:2] == ("inputs/eddie/attachments/a_face.png", principal)

    def test_moved_slugs_are_the_ones_the_plan_listed(self, pg_conn):
        tid, principal = team(pg_conn)
        agent(pg_conn, principal, "Theirs", slug="helper")
        first = agent(pg_conn, "eddie", slug="helper")
        second = agent(pg_conn, "eddie", "Two", slug="helper-2")
        out = apply(pg_conn, "eddie", body(tid, [("agent", first), ("agent", second)]))
        for rename in out["renames"]:
            assert _row(pg_conn, "agents", rename["id"])["slug"] == rename["to"]
        assert {r["id"] for r in out["renames"]} == {first, second}

    def test_filings_follow_the_move(self, pg_conn):
        tid, principal = team(pg_conn)
        other = other_team(pg_conn)
        target = folder(pg_conn, principal, "Shared")
        mine = folder(pg_conn, "eddie", "Mine")
        veras = folder(pg_conn, "vera", "From Eddie")
        pr = prompt(pg_conn, "eddie")
        grant(pg_conn, other, "prompt", pr, "eddie")
        file(pg_conn, "eddie", "prompt", pr, mine)
        file(pg_conn, "vera", "prompt", pr, veras)
        apply(pg_conn, "eddie", body(tid, [("prompt", pr)], folder_id=target))
        items = FolderItemsRepository(pg_conn)
        assert items.filing("vera", "prompt", pr) is None
        assert items.filing("eddie", "prompt", pr) is None
        assert items.filing(principal, "prompt", pr) == target

    def test_members_conversations_switch_others_stay(self, pg_conn):
        tid, _ = team(pg_conn)
        ag = agent(pg_conn, "eddie")
        convs = ConversationsRepository(pg_conn)
        veras = convs.create("vera", "c1", agent_id=ag)
        olgas = convs.create("olga", "c2", agent_id=ag)
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert convs.team_id_of(str(veras["id"])) == tid
        assert convs.team_id_of(str(olgas["id"])) is None

    def test_schedules_keep_their_payer_and_outside_access_bills_the_mover(self, pg_conn):
        tid, _ = team(pg_conn)
        # Bringing outside access into a team takes an Admin.
        ag = agent(pg_conn, "adam", key="k-move-1", status="published")
        sched = SchedulesRepository(pg_conn).create("vera", ag, "recurring", "Ping", cron="0 9 * * *")
        apply(pg_conn, "adam", body(tid, [("agent", ag)]))
        assert _row(pg_conn, "schedules", str(sched["id"]))["user_id"] == "vera"
        row = _row(pg_conn, "agents", ag)
        assert row["access_payer_id"] == "adam" and row["key"] == "k-move-1"

    def test_what_cant_move_is_removed_from_the_holder(self, pg_conn):
        tid, _ = team(pg_conn)
        other = other_team(pg_conn)
        theirs = tool(pg_conn, "olga")
        grant(pg_conn, other, "tool", theirs, "olga", level="editor")
        device = tool(pg_conn, "eddie", "remote_device")
        mine = tool(pg_conn, "eddie")
        ag = agent(pg_conn, "eddie", tools=[theirs, device, mine], resource_sponsors={f"tool:{theirs}": "olga"})
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        row = _row(pg_conn, "agents", ag)
        assert row["tools"] == [mine]
        assert row["resource_sponsors"] == {}
        assert owner_of(pg_conn, "tool", theirs) == "olga"
        assert owner_of(pg_conn, "tool", device) == "eddie"

    def test_workflow_nodes_keep_only_what_moved(self, pg_conn):
        tid, principal = team(pg_conn)
        mine = tool(pg_conn, "eddie")
        device = tool(pg_conn, "eddie", "remote_device")
        wid = workflow(pg_conn, "eddie", nodes=[{"config": {"tools": [mine, device]}}])
        first = agent(pg_conn, "eddie", "First", agent_type="workflow", workflow_id=wid)
        second = agent(pg_conn, "eddie", "Second", agent_type="workflow", workflow_id=wid)
        apply(pg_conn, "eddie", body(tid, [("agent", first)]))
        assert owner_of(pg_conn, "workflow", wid) == principal
        assert owner_of(pg_conn, "agent", second) == principal
        cfg = pg_conn.execute(text("SELECT config FROM workflow_nodes WHERE workflow_id = CAST(:w AS uuid)"),
                              {"w": wid}).scalar()
        assert cfg["config"]["tools"] == [mine]

    def test_audit_events(self, pg_conn):
        tid, _ = team(pg_conn)
        top = folder(pg_conn, "eddie", "Project")
        ag = agent(pg_conn, "eddie")
        apply(pg_conn, "eddie", body(tid, [("agent", ag), ("folder", top)]))
        items = _events(pg_conn, "team.item_moved_in")
        assert [(e["actor_id"], e["metadata"]["resource_id"]) for e in items] == [("eddie", ag)]
        assert items[0]["metadata"]["team_id"] == tid
        assert [e["metadata"]["folder_id"] for e in _events(pg_conn, "team.folder_moved_in")] == [top]


class TestRefusals:
    def test_a_changed_plan_is_refused_with_a_fresh_one(self, pg_conn):
        tid, _ = team(pg_conn)
        ag = agent(pg_conn, "eddie")
        request = body(tid, [("agent", ag)], fingerprint="stale")
        with pytest.raises(MoveError) as err:
            apply_move(pg_conn, "eddie", parse_move_request(request))
        assert (err.value.status, err.value.code) == (409, "move_plan_changed")
        assert err.value.extra["plan"]["fingerprint"] == plan(pg_conn, "eddie", body(tid, [("agent", ag)]))[
            "fingerprint"]
        assert owner_of(pg_conn, "agent", ag) == "eddie"

    def test_a_published_agent_that_would_borrow_refuses(self, pg_conn):
        tid, _ = team(pg_conn)
        src = source(pg_conn, "adam")
        moving = agent(pg_conn, "adam", "Moving", source_id=src)
        staying = agent(pg_conn, "adam", "Staying", source_id=src, key="key-st", status="published")
        with pytest.raises(MoveError) as err:
            apply(pg_conn, "adam", body(tid, [("agent", moving)]))
        assert (err.value.status, err.value.code) == (409, "move_would_borrow")
        assert err.value.extra["agents"] == [{"id": staying, "name": "Staying", "published": True}]
        assert "Staying" in err.value.message
        assert owner_of(pg_conn, "source", src) == "adam"
        # Taking the published agent along is the way through (an Admin may bring outside access in).
        apply(pg_conn, "adam", body(tid, [("agent", moving), ("agent", staying)]))
        assert owner_of(pg_conn, "source", src) != "adam"

    def test_a_dragged_item_not_owned_by_the_mover_is_never_reowned(self, pg_conn):
        tid, _ = team(pg_conn)
        other = other_team(pg_conn)
        theirs = prompt(pg_conn, "olga")
        mine = prompt(pg_conn, "eddie")
        grant(pg_conn, other, "prompt", theirs, "olga", level="editor")
        apply(pg_conn, "eddie", body(tid, [("prompt", theirs), ("prompt", mine)]))
        assert owner_of(pg_conn, "prompt", theirs) == "olga"
        assert _grants(pg_conn, theirs) == 1

    def test_nothing_to_move(self, pg_conn):
        tid, _ = team(pg_conn)
        device = tool(pg_conn, "eddie", "remote_device")
        with pytest.raises(MoveError) as err:
            apply(pg_conn, "eddie", body(tid, [("tool", device)]))
        assert (err.value.status, err.value.code) == (400, "nothing_to_move")

    def test_a_failure_part_way_leaves_everything_as_it_was(self, pg_conn):
        tid, _ = team(pg_conn)
        other = other_team(pg_conn)
        tl = tool(pg_conn, "eddie", "brave", config={"encrypted_credentials": encrypt_credentials({"k": "v"}, "eddie")})
        src = source(pg_conn, "eddie")
        ag = agent(pg_conn, "eddie", tools=[tl], source_id=src)
        grant(pg_conn, other, "agent", ag, "eddie")
        top = folder(pg_conn, "eddie", "Mine")
        file(pg_conn, "eddie", "agent", ag, top)
        request = body(tid, [("agent", ag)])
        fp = plan(pg_conn, "eddie", request)["fingerprint"]
        with patch("docsgpt.security.encryption.reseal_for_owner", side_effect=CredentialDecryptionError("boom")):
            with pytest.raises(Exception):
                apply_move(pg_conn, "eddie", parse_move_request({**request, "fingerprint": fp}))
        for kind, item in (("agent", ag), ("source", src), ("tool", tl), ("folder", top)):
            assert owner_of(pg_conn, kind, item) == "eddie"
        assert _grants(pg_conn, ag) == 1
        assert FolderItemsRepository(pg_conn).filing("eddie", "agent", ag) == top
        assert decrypt_credentials(_row(pg_conn, "user_tools", tl)["config"]["encrypted_credentials"], "eddie") == {
            "k": "v"
        }


    def test_a_failed_move_removes_the_avatar_it_copied(self, pg_conn):
        tid, principal = team(pg_conn)
        tl = tool(pg_conn, "eddie", "brave", config={"encrypted_credentials": encrypt_credentials({"k": "v"}, "eddie")})
        ag = agent(pg_conn, "eddie", tools=[tl], image="inputs/eddie/attachments/a_face.png")
        request = body(tid, [("agent", ag)])
        fp = plan(pg_conn, "eddie", request)["fingerprint"]
        copied = f"inputs/{principal}/attachments/b_face.png"
        with patch("docsgpt.workspaces.move.copy_agent_image_for_user", return_value=copied), patch(
            "docsgpt.workspaces.move.storage"
        ) as store, patch("docsgpt.security.encryption.reseal_for_owner",
                          side_effect=CredentialDecryptionError("boom")):
            with pytest.raises(MoveError):
                apply_move(pg_conn, "eddie", parse_move_request({**request, "fingerprint": fp}))
        store.delete_file.assert_called_once_with(copied)
        assert _row(pg_conn, "agents", ag)["image"] == "inputs/eddie/attachments/a_face.png"

    def test_a_move_keeps_the_original_avatar_and_its_copy(self, pg_conn):
        tid, principal = team(pg_conn)
        ag = agent(pg_conn, "eddie", image="inputs/eddie/attachments/a_face.png")
        copied = f"inputs/{principal}/attachments/b_face.png"
        with patch("docsgpt.workspaces.move.copy_agent_image_for_user", return_value=copied), patch(
            "docsgpt.workspaces.move.storage"
        ) as store:
            apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        store.delete_file.assert_not_called()

    def test_a_failed_commit_removes_the_avatar_the_move_copied(self, pg_conn):
        from flask import Flask, request

        from docsgpt.api.user.workspaces.routes import WorkspaceMoves

        tid, principal = team(pg_conn)
        ag = agent(pg_conn, "eddie", image="inputs/eddie/attachments/a_face.png")
        fp = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))["fingerprint"]
        copied = f"inputs/{principal}/attachments/b_face.png"

        class _Session:
            def __enter__(self):
                return pg_conn

            def __exit__(self, *exc):
                raise RuntimeError("commit failed")

        with patch("docsgpt.workspaces.move.copy_agent_image_for_user", return_value=copied), patch(
            "docsgpt.workspaces.move.storage"
        ) as store, patch("docsgpt.api.user.workspaces.routes.db_session", lambda: _Session()), Flask(
            __name__
        ).test_request_context("/api/workspace_moves", method="POST", json=body(tid, [("agent", ag)], fingerprint=fp)):
            request.decoded_token = {"sub": "eddie"}
            resp = WorkspaceMoves().post()
        assert resp.status_code == 500
        store.delete_file.assert_called_once_with(copied)


class TestFolders:
    def test_a_subtree_keeps_its_structure_and_leaves_others_items_in_personal(self, pg_conn):
        tid, principal = team(pg_conn)
        other = other_team(pg_conn)
        folder(pg_conn, principal, "Project")
        top = folder(pg_conn, "eddie", "Project")
        sub = folder(pg_conn, "eddie", "Specs", parent=top)
        src = source(pg_conn, "eddie")
        theirs = prompt(pg_conn, "olga")
        grant(pg_conn, other, "prompt", theirs, "olga")
        file(pg_conn, "eddie", "source", src, sub)
        file(pg_conn, "eddie", "prompt", theirs, sub)
        out = apply(pg_conn, "eddie", body(tid, [("folder", top)]))
        assert out["renames"] == [{"type": "folder", "id": top, "from": "Project", "to": "Project (2)"}]
        top_row, sub_row = _row(pg_conn, "folders", top), _row(pg_conn, "folders", sub)
        assert (top_row["user_id"], top_row["parent_id"], top_row["name"]) == (principal, None, "Project (2)")
        assert (sub_row["user_id"], str(sub_row["parent_id"])) == (principal, top)
        items = FolderItemsRepository(pg_conn)
        assert items.filing(principal, "source", src) == sub
        assert owner_of(pg_conn, "source", src) == principal
        assert owner_of(pg_conn, "prompt", theirs) == "olga"
        assert items.filing("eddie", "prompt", theirs) is None
        assert items.filing(principal, "prompt", theirs) is None


class TestMoveOut:
    def test_an_admin_takes_a_team_agent_to_personal(self, pg_conn):
        tid, principal = team(pg_conn)
        src = source(pg_conn, principal)
        tl = tool(pg_conn, principal, "brave",
                  config={"encrypted_credentials": encrypt_credentials({"k": "v"}, principal)})
        ag = agent(pg_conn, principal, source_id=src, tools=[tl], key="k-out", status="published",
                   access_payer_id="alice")
        UserToolPreferencesRepository(pg_conn).set_in_chat("adam", tl, True)
        convs = ConversationsRepository(pg_conn)
        adams = convs.create("adam", "c1", agent_id=ag, team_id=tid)
        veras = convs.create("vera", "c2", agent_id=ag, team_id=tid)
        apply(pg_conn, "adam", body("personal", [("agent", ag)]))
        for kind, item in (("agent", ag), ("source", src), ("tool", tl)):
            assert owner_of(pg_conn, kind, item) == "adam"
        row = _row(pg_conn, "agents", ag)
        assert row["access_payer_id"] is None
        tool_row = _row(pg_conn, "user_tools", tl)
        assert tool_row["status"] is True
        assert decrypt_credentials(tool_row["config"]["encrypted_credentials"], "adam") == {"k": "v"}
        assert convs.team_id_of(str(adams["id"])) is None
        assert convs.team_id_of(str(veras["id"])) == tid
        assert ag in [e["metadata"]["resource_id"] for e in _events(pg_conn, "team.item_moved_out")]

    def test_an_editor_cant_move_out(self, pg_conn):
        tid, principal = team(pg_conn)
        ag = agent(pg_conn, principal)
        with pytest.raises(MoveError) as err:
            apply(pg_conn, "eddie", body("personal", [("agent", ag)]))
        assert err.value.status == 403
        assert owner_of(pg_conn, "agent", ag) == principal

    def test_a_team_folder_moves_out(self, pg_conn):
        tid, principal = team(pg_conn)
        top = folder(pg_conn, principal, "Team stuff")
        pr = prompt(pg_conn, principal)
        file(pg_conn, principal, "prompt", pr, top)
        apply(pg_conn, "adam", body("personal", [("folder", top)]))
        assert owner_of(pg_conn, "folder", top) == "adam"
        assert owner_of(pg_conn, "prompt", pr) == "adam"
        assert FolderItemsRepository(pg_conn).filing("adam", "prompt", pr) == top
        assert _events(pg_conn, "team.folder_moved_out")[0]["metadata"]["folder_id"] == top
