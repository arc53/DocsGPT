"""Team connections in 0065: who connected a team's account, team sign-ins, member-mode tools' service, and
one owner on both ends of a connection link."""

import contextlib
import importlib
import uuid
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

_MIGRATION = "docsgpt.alembic.versions.0065_workspaces"


@contextlib.contextmanager
def _ops(conn):
    migration = importlib.import_module(_MIGRATION)
    with patch.object(migration, "op", Operations(MigrationContext.configure(conn))):
        yield migration


def _columns(conn, table: str) -> set:
    return {
        r[0]
        for r in conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table}
        )
    }


def _constraints(conn, table: str) -> set:
    return {
        r[0]
        for r in conn.execute(
            text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass)"), {"t": table}
        )
    }


def _indexes(conn) -> set:
    return {r[0] for r in conn.execute(text("SELECT indexname FROM pg_indexes"))}


def _triggers(conn) -> set:
    return {r[0] for r in conn.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))}


def _team(conn) -> tuple[str, str]:
    """A team and its principal, inserted the way ``TeamsRepository.create`` does."""
    team = str(
        conn.execute(
            text("INSERT INTO teams (name, slug, owner_id) VALUES ('Ops', :s, 'alice') RETURNING id"),
            {"s": f"ops-{uuid.uuid4().hex[:6]}"},
        ).scalar()
    )
    principal = f"__team__{team}"
    conn.execute(
        text("INSERT INTO users (user_id, kind, team_id) VALUES (:u, 'team', CAST(:t AS uuid))"),
        {"u": principal, "t": team},
    )
    return team, principal


def _connection(conn, owner: str, connected_by=None, label=None) -> str:
    return str(
        conn.execute(
            text(
                "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, "
                "account_label, connected_by) VALUES (:u, 'google_drive', 'google_drive', 'oauth', 'connected', "
                ":l, :c) RETURNING id"
            ),
            {"u": owner, "c": connected_by, "l": label or f"{uuid.uuid4().hex[:6]}@example.com"},
        ).scalar()
    )


def _source(conn, owner: str, connection_id) -> str:
    return str(
        conn.execute(
            text(
                "INSERT INTO sources (user_id, name, type, connection_id) "
                "VALUES (:u, 'Docs', 'connector:file', CAST(:c AS uuid)) RETURNING id"
            ),
            {"u": owner, "c": connection_id},
        ).scalar()
    )


def _tool(conn, owner: str, connection_id) -> str:
    return str(
        conn.execute(
            text(
                "INSERT INTO user_tools (user_id, name, connection_id) "
                "VALUES (:u, 'mcp_tool', CAST(:c AS uuid)) RETURNING id"
            ),
            {"u": owner, "c": connection_id},
        ).scalar()
    )


def _insert(table: str):
    return _source if table == "sources" else _tool


def test_head_schema(pg_conn):
    assert "connected_by" in _columns(pg_conn, "connector_sessions")
    assert {"owner_id", "replace_account"} <= _columns(pg_conn, "connector_oauth_flows")
    assert "connector_key" in _columns(pg_conn, "user_tools")
    assert "connector_sessions_connected_by_chk" in _constraints(pg_conn, "connector_sessions")
    assert "connector_sessions_connected_by_idx" in _indexes(pg_conn)
    assert {"sources_connection_owner_matches", "user_tools_connection_owner_matches"} <= _triggers(pg_conn)


def test_a_team_connection_names_the_person_who_connected_it(pg_conn):
    _, principal = _team(pg_conn)
    # Without a person, a team's connection can't exist: every lazy creator fails closed.
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _connection(pg_conn, principal)
    # A principal never connects anything.
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _connection(pg_conn, principal, connected_by=principal)
    # A personal connection is its owner's; nobody else is recorded on it.
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _connection(pg_conn, "alice", connected_by="bob")
    _connection(pg_conn, principal, connected_by="alice")
    _connection(pg_conn, "alice")


def test_clearing_who_connected_a_team_row_is_refused(pg_conn):
    _, principal = _team(pg_conn)
    cid = _connection(pg_conn, principal, connected_by="alice")
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        pg_conn.execute(
            text("UPDATE connector_sessions SET connected_by = NULL WHERE id = CAST(:i AS uuid)"), {"i": cid}
        )
    pg_conn.execute(text("UPDATE connector_sessions SET connected_by = 'bob' WHERE id = CAST(:i AS uuid)"), {"i": cid})


def test_two_admins_connecting_one_account_for_a_team_share_a_row(pg_conn):
    _, principal = _team(pg_conn)
    _connection(pg_conn, principal, connected_by="alice", label="drive@ops.example")
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _connection(pg_conn, principal, connected_by="bob", label="drive@ops.example")


def test_a_team_sign_in_records_its_owner_and_whether_it_replaces_the_account(pg_conn):
    _, principal = _team(pg_conn)
    cid = _connection(pg_conn, principal, connected_by="alice")
    pg_conn.execute(
        text(
            "INSERT INTO connector_oauth_flows (user_id, provider, connection_id, state_hash, return_origin, "
            "expires_at) VALUES ('bob', 'google_drive', CAST(:c AS uuid), 'h1', 'http://app', now())"
        ),
        {"c": cid},
    )
    row = pg_conn.execute(
        text("SELECT owner_id, replace_account FROM connector_oauth_flows WHERE state_hash = 'h1'")
    ).fetchone()
    assert tuple(row) == (None, False)


@pytest.mark.parametrize("table", ["sources", "user_tools"])
def test_an_item_only_ever_links_its_own_owners_connection(pg_conn, table):
    _, principal = _team(pg_conn)
    team_cid = _connection(pg_conn, principal, connected_by="alice")
    alice_cid = _connection(pg_conn, "alice")
    insert = _insert(table)
    # A team item on a person's connection, and a person's item on the team's: both refused.
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        insert(pg_conn, principal, alice_cid)
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        insert(pg_conn, "alice", team_cid)
    team_item = insert(pg_conn, principal, team_cid)
    alice_item = insert(pg_conn, "alice", alice_cid)
    # Pointing an existing item at someone else's connection is refused too.
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        pg_conn.execute(
            text(f"UPDATE {table} SET connection_id = CAST(:c AS uuid) WHERE id = CAST(:i AS uuid)"),
            {"c": alice_cid, "i": team_item},
        )
    # And so is re-owning it while it keeps the old owner's connection (a move).
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        pg_conn.execute(
            text(f"UPDATE {table} SET user_id = :p WHERE id = CAST(:i AS uuid)"), {"p": principal, "i": alice_item}
        )
    # A move that lets go of the connection, and an unbound item, are fine.
    pg_conn.execute(
        text(f"UPDATE {table} SET user_id = :p, connection_id = NULL WHERE id = CAST(:i AS uuid)"),
        {"p": principal, "i": alice_item},
    )
    insert(pg_conn, principal, None)


def test_upgrade_twice_is_idempotent_and_downgrade_drops_it_all(pg_conn):
    _, principal = _team(pg_conn)
    cid = _connection(pg_conn, "alice")
    with _ops(pg_conn) as migration:
        migration.upgrade()
        migration.upgrade()
        assert "connected_by" in _columns(pg_conn, "connector_sessions")
        assert "connector_sessions_connected_by_chk" in _constraints(pg_conn, "connector_sessions")

        migration.downgrade()
        migration.downgrade()
        assert "connected_by" not in _columns(pg_conn, "connector_sessions")
        assert not {"owner_id", "replace_account"} & _columns(pg_conn, "connector_oauth_flows")
        assert "connector_key" not in _columns(pg_conn, "user_tools")
        assert "connector_sessions_connected_by_idx" not in _indexes(pg_conn)
        assert not {t for t in _triggers(pg_conn) if "connection_owner_matches" in t}
        assert "connection_owner_matches" not in {
            r[0] for r in pg_conn.execute(text("SELECT proname FROM pg_proc"))
        }

        migration.upgrade()
    assert pg_conn.execute(
        text("SELECT connected_by FROM connector_sessions WHERE id = CAST(:i AS uuid)"), {"i": cid}
    ).fetchone() == (None,)
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _source(pg_conn, principal, cid)


def test_downgrade_refuses_while_a_team_holds_a_connection(pg_conn):
    _, principal = _team(pg_conn)
    _connection(pg_conn, principal, connected_by="alice")
    with _ops(pg_conn) as migration:
        with pytest.raises(Exception, match="connector_sessions"), pg_conn.begin_nested():
            migration.downgrade()


def test_upgrade_keeps_existing_mismatched_links_and_counts_them(pg_conn, caplog):
    _, principal = _team(pg_conn)
    with _ops(pg_conn) as migration:
        # Before this revision nothing stopped a team item from naming a person's connection.
        pg_conn.execute(text("DROP TRIGGER IF EXISTS sources_connection_owner_matches ON sources"))
        alice_cid = _connection(pg_conn, "alice")
        source = _source(pg_conn, principal, alice_cid)
        with caplog.at_level("WARNING"):
            migration.upgrade()
    assert pg_conn.execute(
        text("SELECT connection_id::text FROM sources WHERE id = CAST(:i AS uuid)"), {"i": source}
    ).scalar() == alice_cid
    assert any("1 source" in r.getMessage() for r in caplog.records)


def test_a_team_row_stored_before_this_revision_keeps_the_upgrade_going(pg_conn):
    _, principal = _team(pg_conn)
    with _ops(pg_conn) as migration:
        pg_conn.execute(
            text("ALTER TABLE connector_sessions DROP CONSTRAINT IF EXISTS connector_sessions_connected_by_chk")
        )
        # e.g. a team's MCP sign-in written lazily under the principal.
        cid = _connection(pg_conn, principal)
        migration.upgrade()
    assert "connector_sessions_connected_by_chk" in _constraints(pg_conn, "connector_sessions")
    assert pg_conn.execute(
        text("SELECT connected_by FROM connector_sessions WHERE id = CAST(:i AS uuid)"), {"i": cid}
    ).fetchone() == (None,)
    # New rows are still checked.
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _connection(pg_conn, principal)
