"""Move and a team's connections: what is bound to a team's account stays in the team.

A team source or tool that runs on a connection the team owns can't move out (the connection never moves,
and an item may only point at its own owner's connection); it is listed as ``cannot_move`` and taken off the
agents that move. A member-mode tool runs on each person's own account, so it moves either way; moving one
in keeps the service it is for, read from the connection it leaves behind.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from docsgpt.security.encryption import encrypt_json
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from tests.workspaces.move_support import agent, apply, body, keyed, owner_of, plan, team, tool
from tests.workspaces.move_support import source as _source


def source(conn, owner, *, connection_id=None, **kwargs) -> str:
    """A source, bound to ``connection_id`` when given."""
    sid = _source(conn, owner, **kwargs)
    if connection_id:
        conn.execute(text("UPDATE sources SET connection_id = CAST(:c AS uuid) WHERE id = CAST(:i AS uuid)"),
                     {"c": connection_id, "i": sid})
    return sid


def _team_connection(conn, principal, *, connected_by="adam", auth_kind="oauth", provider="google_drive") -> str:
    return str(ConnectorSessionsRepository(conn).create(
        principal, provider, connector_key=provider, auth_kind=auth_kind,
        account_label=f"{uuid.uuid4().hex[:6]}@example.com", connected_by=connected_by,
        encrypted_credentials=encrypt_json({"access_token": "t", "api_key": "k"}, principal),
    )["id"])


def _personal_connection(conn, owner, provider="github") -> str:
    return str(ConnectorSessionsRepository(conn).create(
        owner, provider, connector_key=provider, auth_kind="oauth", account_label=owner,
    )["id"])


def _row(conn, table, item_id) -> dict:
    return dict(conn.execute(text(f"SELECT * FROM {table} WHERE id = CAST(:i AS uuid)"), {"i": item_id})
                .mappings().one())


class TestMoveOut:
    def test_a_team_connector_source_cant_move_out(self, pg_conn):
        tid, principal = team(pg_conn)
        cid = _team_connection(pg_conn, principal)
        src = source(pg_conn, principal, type="connector:file", connection_id=cid)
        out = plan(pg_conn, "adam", body("personal", [("source", src)]))
        assert out["items"] == []
        entry = keyed(out["cannot_move"])[("source", src)]
        assert (entry["reason"], entry["effect"]) == ("connector_synced", "stays")

    def test_a_team_source_on_a_team_connection_cant_move_out(self, pg_conn):
        tid, principal = team(pg_conn)
        cid = _team_connection(pg_conn, principal, provider="s3", auth_kind="api_key")
        src = source(pg_conn, principal, type="s3", connection_id=cid)
        out = plan(pg_conn, "adam", body("personal", [("source", src)]))
        assert keyed(out["cannot_move"])[("source", src)]["reason"] == "connection_account"

    def test_a_team_tool_on_a_team_connection_cant_move_out(self, pg_conn):
        tid, principal = team(pg_conn)
        cid = _team_connection(pg_conn, principal, provider="github")
        tl = tool(pg_conn, principal, "github", connection_id=cid)
        out = plan(pg_conn, "adam", body("personal", [("tool", tl)]))
        assert out["items"] == []
        assert keyed(out["cannot_move"])[("tool", tl)]["reason"] == "connection_account"

    def test_a_team_key_server_on_a_team_connection_cant_move_out(self, pg_conn):
        # Moving it would copy the team's saved key onto a personal tool.
        tid, principal = team(pg_conn)
        cid = _team_connection(pg_conn, principal, provider="mcp", auth_kind="api_key")
        tl = tool(pg_conn, principal, "mcp_tool", connection_id=cid, config={"server_url": "https://m.example"})
        out = plan(pg_conn, "adam", body("personal", [("tool", tl)]))
        assert keyed(out["cannot_move"])[("tool", tl)]["reason"] == "connection_account"

    def test_moving_the_agent_out_leaves_them_in_the_team_and_takes_them_off(self, pg_conn):
        tid, principal = team(pg_conn)
        cid = _team_connection(pg_conn, principal, provider="github")
        tl = tool(pg_conn, principal, "github", connection_id=cid)
        src = source(pg_conn, principal, type="connector:file", connection_id=_team_connection(pg_conn, principal))
        ag = agent(pg_conn, principal, source_id=src, tools=[tl])
        out = plan(pg_conn, "adam", body("personal", [("agent", ag)]))
        cannot = keyed(out["cannot_move"])
        assert cannot[("tool", tl)]["effect"] == "removed_from_holder"
        assert cannot[("source", src)]["effect"] == "removed_from_holder"
        # The apply never meets the database check that keeps items on their own owner's connection.
        apply(pg_conn, "adam", body("personal", [("agent", ag)]))
        assert owner_of(pg_conn, "agent", ag) == "adam"
        assert owner_of(pg_conn, "tool", tl) == principal
        assert owner_of(pg_conn, "source", src) == principal
        moved = _row(pg_conn, "agents", ag)
        assert tl not in (moved["tools"] or [])
        assert moved["source_id"] is None

    def test_a_member_mode_team_tool_moves_out(self, pg_conn):
        tid, principal = team(pg_conn)
        tl = tool(pg_conn, principal, "github", credential_mode="member")
        pg_conn.execute(text("UPDATE user_tools SET connector_key = 'github' WHERE id = CAST(:i AS uuid)"), {"i": tl})
        apply(pg_conn, "adam", body("personal", [("tool", tl)]))
        row = _row(pg_conn, "user_tools", tl)
        assert row["user_id"] == "adam"
        assert row["connection_id"] is None
        assert row["connector_key"] == "github"


class TestMoveIn:
    def test_a_member_mode_tool_keeps_its_service_when_its_connection_is_cleared(self, pg_conn):
        tid, principal = team(pg_conn)
        tl = tool(pg_conn, "eddie", "github", connection_id=_personal_connection(pg_conn, "eddie"),
                  credential_mode="member")
        apply(pg_conn, "eddie", body(tid, [("tool", tl)]))
        row = _row(pg_conn, "user_tools", tl)
        assert row["user_id"] == principal
        assert row["connection_id"] is None
        assert row["connector_key"] == "github"

    def test_a_member_mode_tool_keeps_a_service_it_already_names(self, pg_conn):
        tid, principal = team(pg_conn)
        tl = tool(pg_conn, "eddie", "github", credential_mode="member")
        pg_conn.execute(text("UPDATE user_tools SET connector_key = 'github' WHERE id = CAST(:i AS uuid)"), {"i": tl})
        apply(pg_conn, "eddie", body(tid, [("tool", tl)]))
        assert _row(pg_conn, "user_tools", tl)["connector_key"] == "github"

    def test_a_personal_connector_source_still_cant_move_in(self, pg_conn):
        tid, _ = team(pg_conn)
        src = source(pg_conn, "eddie", type="connector:file", connection_id=_personal_connection(pg_conn, "eddie"))
        out = plan(pg_conn, "eddie", body(tid, [("source", src)]))
        assert keyed(out["cannot_move"])[("source", src)]["reason"] == "connector_synced"
