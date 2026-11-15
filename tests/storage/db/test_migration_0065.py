"""Workspaces: team principals, the three stored team roles, provenance and the conversation workspace."""

import contextlib
import importlib
import uuid
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

_MIGRATION = "docsgpt.alembic.versions.0065_workspaces"

#: Every table that gains ``created_by``.
_PROVENANCE_TABLES = ("agents", "sources", "user_tools", "prompts", "workflows", "folders")


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


def _indexes(conn) -> set:
    return {r[0] for r in conn.execute(text("SELECT indexname FROM pg_indexes"))}


def _team(conn, name: str = "Ops", owner: str = "alice") -> str:
    return str(
        conn.execute(
            text("INSERT INTO teams (name, slug, owner_id) VALUES (:n, :s, :o) RETURNING id"),
            {"n": name, "s": f"{name.lower()}-{uuid.uuid4().hex[:6]}", "o": owner},
        ).scalar()
    )


def _principal(conn, team_id: str) -> str:
    """Insert the principal row the way ``TeamsRepository.create`` does; its user id."""
    principal = f"__team__{team_id}"
    conn.execute(
        text("INSERT INTO users (user_id, kind, team_id) VALUES (:u, 'team', CAST(:t AS uuid))"),
        {"u": principal, "t": team_id},
    )
    return principal


def _member(conn, team_id: str, user: str, role: str, source: str = "manual") -> None:
    conn.execute(
        text(
            "INSERT INTO team_members (team_id, user_id, role, source) "
            "VALUES (CAST(:t AS uuid), :u, :r, :s)"
        ),
        {"t": team_id, "u": user, "r": role, "s": source},
    )


def _roles(conn, team_id: str) -> set:
    return {
        tuple(r)
        for r in conn.execute(
            text("SELECT user_id, role, source FROM team_members WHERE team_id = CAST(:t AS uuid)"), {"t": team_id}
        )
    }


def _agent(conn, user: str, name: str = "A") -> str:
    return str(
        conn.execute(
            text("INSERT INTO agents (user_id, name, status) VALUES (:u, :n, 'draft') RETURNING id"),
            {"u": user, "n": name},
        ).scalar()
    )


def test_head_schema(pg_conn):
    assert {"kind", "team_id"} <= _columns(pg_conn, "users")
    for table in _PROVENANCE_TABLES:
        assert "created_by" in _columns(pg_conn, table), table
    assert "access_payer_id" in _columns(pg_conn, "agents")
    assert "team_id" in _columns(pg_conn, "conversations")
    indexes = _indexes(pg_conn)
    assert {"users_team_id_uidx", "conversations_user_ws_listed_idx"} <= indexes
    assert "conversations_user_listed_idx" not in indexes


def test_upgrade_backfills_principals_roles_kinds_and_provenance(pg_conn):
    with _ops(pg_conn) as migration:
        migration.downgrade()
        one, two = _team(pg_conn, "One"), _team(pg_conn, "Two")
        # alice is admin and member by hand: the member row folds into the admin one.
        _member(pg_conn, one, "alice", "team_admin")
        _member(pg_conn, one, "alice", "team_member")
        # bob is a member by hand and an admin through the IdP: the manual row becomes viewer.
        _member(pg_conn, one, "bob", "team_member")
        _member(pg_conn, one, "bob", "team_admin", "oidc_group")
        _member(pg_conn, two, "carol", "team_member")
        pg_conn.execute(text("INSERT INTO users (user_id) VALUES ('__system__') ON CONFLICT DO NOTHING"))
        agent = _agent(pg_conn, "alice")
        stamp = pg_conn.execute(
            text("UPDATE agents SET updated_at = '2026-01-01' WHERE id = CAST(:a AS uuid) RETURNING updated_at"),
            {"a": agent},
        ).scalar()
        pg_conn.execute(text("INSERT INTO prompts (user_id, name, content) VALUES ('bob', 'p', 'c')"))

        migration.upgrade()
        migration.upgrade()

        principals = pg_conn.execute(
            text("SELECT user_id, kind, team_id::text FROM users WHERE kind = 'team' ORDER BY user_id")
        ).fetchall()
        assert sorted(tuple(r) for r in principals) == sorted(
            [(f"__team__{one}", "team", one), (f"__team__{two}", "team", two)]
        )
        kinds = dict(
            pg_conn.execute(text("SELECT user_id, kind FROM users WHERE user_id IN ('__system__', 'alice')")).fetchall()
        )
        assert kinds == {"__system__": "system", "alice": "user"}
        assert _roles(pg_conn, one) == {
            ("alice", "team_admin", "manual"),
            ("bob", "team_viewer", "manual"),
            ("bob", "team_admin", "oidc_group"),
        }
        assert _roles(pg_conn, two) == {("carol", "team_viewer", "manual")}
        row = pg_conn.execute(
            text("SELECT created_by, updated_at FROM agents WHERE id = CAST(:a AS uuid)"), {"a": agent}
        ).fetchone()
        # The backfill doesn't make the agent look edited.
        assert tuple(row) == ("alice", stamp)
        assert pg_conn.execute(text("SELECT created_by FROM prompts WHERE user_id = 'bob'")).scalar() == "bob"


def test_upgrade_refuses_a_person_row_with_the_principal_prefix(pg_conn):
    with _ops(pg_conn) as migration:
        migration.downgrade()
        pg_conn.execute(text("INSERT INTO users (user_id) VALUES ('__team__forged')"))
        with pytest.raises(DBAPIError, match="__team__"), pg_conn.begin_nested():
            migration.upgrade()


def test_the_user_trigger_cannot_mint_a_principal(pg_conn):
    team = _team(pg_conn)
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _agent(pg_conn, f"__team__{team}")
    principal = _principal(pg_conn, team)
    agent = _agent(pg_conn, principal)
    assert pg_conn.execute(
        text("SELECT user_id FROM agents WHERE id = CAST(:a AS uuid)"), {"a": agent}
    ).scalar() == principal


@pytest.mark.parametrize(
    "user_id, kind, team",
    [
        ("__team__{team}", "user", None),  # a person row can't carry the prefix
        ("__team__{team}", "team", None),  # a team row names its team
        ("someone", "team", "{team}"),  # and has the principal id
        ("__team__{other}", "team", "{team}"),  # of that very team
        ("bob", "user", "{team}"),  # a person has no team
        ("bob", "robot", None),
    ],
)
def test_principal_row_checks(pg_conn, user_id, kind, team):
    ids = {"team": _team(pg_conn), "other": str(uuid.uuid4())}
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        pg_conn.execute(
            text("INSERT INTO users (user_id, kind, team_id) VALUES (:u, :k, CAST(:t AS uuid))"),
            {"u": user_id.format(**ids), "k": kind, "t": team.format(**ids) if team else None},
        )


def test_one_principal_per_team(pg_conn):
    team = _team(pg_conn)
    _principal(pg_conn, team)
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _principal(pg_conn, team)


def test_team_members_take_three_roles_and_persons_only(pg_conn):
    team = _team(pg_conn)
    for role in ("team_admin", "team_editor", "team_viewer"):
        _member(pg_conn, team, f"u-{role}", role)
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _member(pg_conn, team, "dave", "team_member")
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _member(pg_conn, team, f"__team__{team}", "team_viewer")


def test_a_grant_never_has_a_principal_owner(pg_conn):
    team = _team(pg_conn)
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        pg_conn.execute(
            text(
                "INSERT INTO team_resource_grants (team_id, resource_type, resource_id, owner_id, granted_by) "
                "VALUES (CAST(:t AS uuid), 'agent', gen_random_uuid(), :o, 'alice')"
            ),
            {"t": team, "o": f"__team__{team}"},
        )


def test_access_payer_is_a_person_and_bookkeeping(pg_conn):
    team = _team(pg_conn)
    agent = _agent(pg_conn, _principal(pg_conn, team))
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        pg_conn.execute(
            text("UPDATE agents SET access_payer_id = :p WHERE id = CAST(:a AS uuid)"),
            {"p": f"__team__{team}", "a": agent},
        )
    pg_conn.execute(text("UPDATE agents SET updated_at = '2026-01-01' WHERE id = CAST(:a AS uuid)"), {"a": agent})
    pg_conn.execute(text("UPDATE agents SET access_payer_id = 'alice' WHERE id = CAST(:a AS uuid)"), {"a": agent})
    updated = pg_conn.execute(
        text("SELECT updated_at::date::text FROM agents WHERE id = CAST(:a AS uuid)"), {"a": agent}
    ).scalar()
    assert updated == "2026-01-01"


def test_created_by_defaults_to_a_person_owner_only(pg_conn):
    team = _team(pg_conn)
    principal = _principal(pg_conn, team)
    personal, owned_by_team = _agent(pg_conn, "alice"), _agent(pg_conn, principal)
    rows = dict(
        pg_conn.execute(
            text("SELECT id::text, created_by FROM agents WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": [personal, owned_by_team]},
        ).fetchall()
    )
    assert rows == {personal: "alice", owned_by_team: None}
    explicit = str(
        pg_conn.execute(
            text("INSERT INTO prompts (user_id, name, content, created_by) VALUES (:u, 'p', 'c', 'bob') RETURNING id"),
            {"u": principal},
        ).scalar()
    )
    assert pg_conn.execute(
        text("SELECT created_by FROM prompts WHERE id = CAST(:i AS uuid)"), {"i": explicit}
    ).scalar() == "bob"


def test_an_empty_team_takes_its_chats_with_it(pg_conn):
    team = _team(pg_conn)
    principal = _principal(pg_conn, team)
    pg_conn.execute(
        text("INSERT INTO conversations (user_id, name, team_id) VALUES ('alice', 'in team', CAST(:t AS uuid))"),
        {"t": team},
    )
    pg_conn.execute(text("INSERT INTO conversations (user_id, name) VALUES ('alice', 'personal')"))
    # The principal row holds the team in place until it goes.
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        pg_conn.execute(text("DELETE FROM teams WHERE id = CAST(:t AS uuid)"), {"t": team})
    pg_conn.execute(text("DELETE FROM users WHERE user_id = :p"), {"p": principal})
    pg_conn.execute(text("DELETE FROM teams WHERE id = CAST(:t AS uuid)"), {"t": team})
    names = [r[0] for r in pg_conn.execute(text("SELECT name FROM conversations WHERE user_id = 'alice'"))]
    assert names == ["personal"]


def test_owner_inactive_is_a_run_error_type(pg_conn):
    schedule = pg_conn.execute(
        text(
            "INSERT INTO schedules (user_id, trigger_type, instruction, run_at) "
            "VALUES ('alice', 'once', 'x', now()) RETURNING id"
        )
    ).scalar()
    pg_conn.execute(
        text(
            "INSERT INTO schedule_runs (schedule_id, user_id, scheduled_for, status, error_type) "
            "VALUES (:s, 'alice', now(), 'skipped', 'owner_inactive')"
        ),
        {"s": schedule},
    )
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        pg_conn.execute(
            text(
                "INSERT INTO schedule_runs (schedule_id, user_id, scheduled_for, status, error_type) "
                "VALUES (:s, 'alice', now() + interval '1 day', 'skipped', 'made_up')"
            ),
            {"s": schedule},
        )


def test_downgrade_refuses_while_a_principal_owns_anything(pg_conn):
    team = _team(pg_conn)
    _agent(pg_conn, _principal(pg_conn, team))
    with _ops(pg_conn) as migration:
        with pytest.raises(DBAPIError, match="agents"), pg_conn.begin_nested():
            migration.downgrade()
    assert "kind" in _columns(pg_conn, "users")


def test_round_trip(pg_conn):
    team = _team(pg_conn)
    principal = _principal(pg_conn, team)
    _member(pg_conn, team, "alice", "team_admin")
    _member(pg_conn, team, "bob", "team_editor")
    _member(pg_conn, team, "carol", "team_viewer")
    # Two IdP roles that both fold into team_member keep one row.
    _member(pg_conn, team, "dave", "team_editor", "oidc_group")
    _member(pg_conn, team, "dave", "team_viewer", "oidc_group")
    pg_conn.execute(
        text("INSERT INTO conversations (user_id, name, team_id) VALUES ('alice', 'c', CAST(:t AS uuid))"),
        {"t": team},
    )
    with _ops(pg_conn) as migration:
        migration.downgrade()
        migration.downgrade()
        assert not {"kind", "team_id"} & _columns(pg_conn, "users")
        for table in _PROVENANCE_TABLES:
            assert "created_by" not in _columns(pg_conn, table), table
        assert "access_payer_id" not in _columns(pg_conn, "agents")
        assert "team_id" not in _columns(pg_conn, "conversations")
        assert "conversations_user_listed_idx" in _indexes(pg_conn)
        assert pg_conn.execute(text("SELECT count(*) FROM users WHERE user_id = :p"), {"p": principal}).scalar() == 0
        assert _roles(pg_conn, team) == {
            ("alice", "team_admin", "manual"),
            ("bob", "team_member", "manual"),
            ("carol", "team_member", "manual"),
            ("dave", "team_member", "oidc_group"),
        }
        # The old trigger mints any id again, and the old role set is back.
        _agent(pg_conn, "__team__anything")
        _member(pg_conn, team, "erin", "team_member")

        pg_conn.execute(text("DELETE FROM agents WHERE user_id = '__team__anything'"))
        pg_conn.execute(text("DELETE FROM users WHERE user_id = '__team__anything'"))
        migration.upgrade()
        assert pg_conn.execute(
            text("SELECT kind FROM users WHERE user_id = :p"), {"p": principal}
        ).scalar() == "team"
        assert ("erin", "team_viewer", "manual") in _roles(pg_conn, team)
