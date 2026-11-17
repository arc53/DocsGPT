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
    assert {"users_team_id_uidx", "conversations_user_ws_listed_idx", "conversations_team_idx"} <= indexes
    assert "conversations_user_listed_idx" not in indexes


def test_a_teams_chats_are_found_by_team_without_a_scan(pg_conn):
    team = _team(pg_conn)
    pg_conn.execute(text("SET LOCAL enable_seqscan = off"))
    # The export's page query and a team delete's cascade both start from the team.
    plan = "\n".join(
        r[0] for r in pg_conn.execute(
            text("EXPLAIN SELECT id FROM conversations WHERE team_id = CAST(:t AS uuid) ORDER BY id LIMIT 200"),
            {"t": team},
        )
    )
    assert "conversations_team_idx" in plan


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
        assert "conversations_team_idx" not in _indexes(pg_conn)
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


# ---------------------------------------------------------------------------
# Usage attribution and the payer pause reasons
# ---------------------------------------------------------------------------

#: Run error types a pause for the payer records.
_PAYER_ERRORS = ("payer_out_of_allowance", "payer_left", "no_payer")


def _constraints(conn, table: str) -> set:
    return {
        r[0]
        for r in conn.execute(
            text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass)"), {"t": table}
        )
    }


def _schedule(conn) -> str:
    return str(
        conn.execute(
            text(
                "INSERT INTO schedules (user_id, trigger_type, instruction, run_at) "
                "VALUES ('alice', 'once', 'x', now()) RETURNING id"
            )
        ).scalar()
    )


def _run(conn, schedule: str, error_type: str, offset: int = 0) -> None:
    conn.execute(
        text(
            "INSERT INTO schedule_runs (schedule_id, user_id, scheduled_for, status, error_type) "
            "VALUES (CAST(:s AS uuid), 'alice', now() + make_interval(days => :d), 'skipped', :e)"
        ),
        {"s": schedule, "d": offset, "e": error_type},
    )


def _usage(conn, **fields) -> None:
    columns = ", ".join(["user_id", *fields])
    values = ", ".join([":user_id", *(f":{k}" for k in fields)])
    conn.execute(text(f"INSERT INTO token_usage ({columns}) VALUES ({values})"), {"user_id": "alice", **fields})


def test_usage_rows_record_their_workspace_and_run_kind(pg_conn):
    assert {"team_id", "run_kind"} <= _columns(pg_conn, "token_usage")
    assert "token_usage_run_kind_chk" in _constraints(pg_conn, "token_usage")
    assert "token_usage_team_ts_idx" in _indexes(pg_conn)
    team = _team(pg_conn)
    for kind in ("chat", "schedule", "published", "knowledge", "monitor", "drafter"):
        _usage(pg_conn, run_kind=kind, team_id=team)
    # Rows written before attribution existed stay unset.
    _usage(pg_conn)
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _usage(pg_conn, run_kind="made_up")


def test_a_deleted_team_keeps_its_usage_rows(pg_conn):
    team = _team(pg_conn)
    _usage(pg_conn, run_kind="chat", team_id=team)
    pg_conn.execute(text("DELETE FROM teams WHERE id = CAST(:t AS uuid)"), {"t": team})
    assert pg_conn.execute(
        text("SELECT count(*) FROM token_usage WHERE team_id = CAST(:t AS uuid)"), {"t": team}
    ).scalar() == 1


@pytest.mark.parametrize("error_type", _PAYER_ERRORS)
def test_a_run_paused_for_its_payer_says_why(pg_conn, error_type):
    schedule = _schedule(pg_conn)
    _run(pg_conn, schedule, error_type)
    assert pg_conn.execute(
        text("SELECT error_type FROM schedule_runs WHERE schedule_id = CAST(:s AS uuid)"), {"s": schedule}
    ).scalar() == error_type


def test_upgrade_twice_keeps_the_attribution_and_the_reasons(pg_conn):
    with _ops(pg_conn) as migration:
        migration.upgrade()
        migration.upgrade()
    assert {"team_id", "run_kind"} <= _columns(pg_conn, "token_usage")
    schedule = _schedule(pg_conn)
    _run(pg_conn, schedule, "payer_left")
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _usage(pg_conn, run_kind="made_up")


def test_downgrade_clears_the_payer_reasons_and_the_attribution(pg_conn):
    schedule = _schedule(pg_conn)
    for offset, error_type in enumerate((*_PAYER_ERRORS, "owner_inactive", "timeout")):
        _run(pg_conn, schedule, error_type, offset)
    _usage(pg_conn, run_kind="chat", team_id=_team(pg_conn))
    with _ops(pg_conn) as migration:
        migration.downgrade()
        migration.downgrade()
        assert not {"team_id", "run_kind"} & _columns(pg_conn, "token_usage")
        assert "token_usage_team_ts_idx" not in _indexes(pg_conn)
        kept = sorted(
            r[0] or ""
            for r in pg_conn.execute(
                text("SELECT error_type FROM schedule_runs WHERE schedule_id = CAST(:s AS uuid)"), {"s": schedule}
            )
        )
        # Pause reasons go back to unset; a failure's type stays.
        assert kept == ["", "", "", "", "timeout"]
        with pytest.raises(IntegrityError), pg_conn.begin_nested():
            _run(pg_conn, schedule, "payer_left", 10)
        migration.upgrade()
    _run(pg_conn, schedule, "payer_left", 11)


# ---------------------------------------------------------------------------
# Taking a team's items outside: the policy and shares with other teams
# ---------------------------------------------------------------------------

#: The item tables a team can share with another team, and the kind each one is.
_SHAREABLE = {"agents": "agent", "sources": "source", "user_tools": "tool", "prompts": "prompt"}


def _item(conn, table: str, owner: str) -> str:
    """One row of ``table`` owned by ``owner``."""
    sql = {
        "agents": "INSERT INTO agents (user_id, name, status) VALUES (:u, 'A', 'draft') RETURNING id",
        "sources": "INSERT INTO sources (user_id, name) VALUES (:u, 'S') RETURNING id",
        "user_tools": "INSERT INTO user_tools (user_id, name) VALUES (:u, 'api_tool') RETURNING id",
        "prompts": "INSERT INTO prompts (user_id, name, content) VALUES (:u, 'P', 'Be brief.') RETURNING id",
    }[table]
    return str(conn.execute(text(sql), {"u": owner}).scalar())


def _share(conn, owner_team: str, team: str, kind: str, item: str, by: str = "alice") -> None:
    conn.execute(
        text(
            "INSERT INTO team_item_shares (owner_team_id, team_id, resource_type, resource_id, shared_by) "
            "VALUES (CAST(:o AS uuid), CAST(:t AS uuid), :k, CAST(:i AS uuid), :b)"
        ),
        {"o": owner_team, "t": team, "k": kind, "i": item, "b": by},
    )


def _shares(conn, item: str) -> int:
    return conn.execute(
        text("SELECT count(*) FROM team_item_shares WHERE resource_id = CAST(:i AS uuid)"), {"i": item}
    ).scalar()


def _functions(conn) -> set:
    return {r[0] for r in conn.execute(text("SELECT proname FROM pg_proc"))}


def _triggers(conn) -> set:
    return {r[0] for r in conn.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))}


def test_teams_take_items_outside_through_admins_by_default(pg_conn):
    team = _team(pg_conn)
    assert pg_conn.execute(
        text("SELECT outside_policy FROM teams WHERE id = CAST(:t AS uuid)"), {"t": team}
    ).scalar() == "admins"
    for policy in ("editors", "locked", "admins"):
        pg_conn.execute(
            text("UPDATE teams SET outside_policy = :p WHERE id = CAST(:t AS uuid)"), {"p": policy, "t": team}
        )
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        pg_conn.execute(
            text("UPDATE teams SET outside_policy = 'everyone' WHERE id = CAST(:t AS uuid)"), {"t": team}
        )


def test_a_share_names_a_kind_another_team_and_a_person(pg_conn):
    one, two = _team(pg_conn, "One"), _team(pg_conn, "Two")
    item = str(uuid.uuid4())
    _share(pg_conn, one, two, "source", item)
    # One row per receiving team and item.
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _share(pg_conn, one, two, "source", item, by="adam")
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _share(pg_conn, one, two, "workflow", str(uuid.uuid4()))
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _share(pg_conn, one, one, "source", str(uuid.uuid4()))
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _share(pg_conn, one, two, "tool", str(uuid.uuid4()), by=f"__team__{one}")
    assert {"team_item_shares_resource_idx", "team_item_shares_owner_team_idx"} <= _indexes(pg_conn)


@pytest.mark.parametrize("which", ["owner", "receiver"])
def test_a_share_goes_with_either_team(pg_conn, which):
    one, two = _team(pg_conn, "One"), _team(pg_conn, "Two")
    item = str(uuid.uuid4())
    _share(pg_conn, one, two, "prompt", item)
    pg_conn.execute(text("DELETE FROM teams WHERE id = CAST(:t AS uuid)"), {"t": one if which == "owner" else two})
    assert _shares(pg_conn, item) == 0


@pytest.mark.parametrize("table", list(_SHAREABLE))
def test_deleting_or_moving_the_item_drops_its_shares(pg_conn, table):
    kind = _SHAREABLE[table]
    one, two = _team(pg_conn, "One"), _team(pg_conn, "Two")
    principal = _principal(pg_conn, one)
    deleted, moved, renamed = (_item(pg_conn, table, principal) for _ in range(3))
    for item in (deleted, moved, renamed):
        _share(pg_conn, one, two, kind, item)

    pg_conn.execute(text(f"DELETE FROM {table} WHERE id = CAST(:i AS uuid)"), {"i": deleted})
    # A move out re-owns the row: the team's shares of it end.
    pg_conn.execute(text(f"UPDATE {table} SET user_id = 'alice' WHERE id = CAST(:i AS uuid)"), {"i": moved})
    # Any other change, or a write that keeps the owner, leaves them.
    pg_conn.execute(text(f"UPDATE {table} SET name = 'Renamed' WHERE id = CAST(:i AS uuid)"), {"i": renamed})
    pg_conn.execute(text(f"UPDATE {table} SET user_id = user_id WHERE id = CAST(:i AS uuid)"), {"i": renamed})

    assert (_shares(pg_conn, deleted), _shares(pg_conn, moved), _shares(pg_conn, renamed)) == (0, 0, 1)


def test_upgrade_twice_and_downgrade_for_shares_and_the_policy(pg_conn):
    one, two = _team(pg_conn, "One"), _team(pg_conn, "Two")
    _share(pg_conn, one, two, "agent", str(uuid.uuid4()))
    with _ops(pg_conn) as migration:
        migration.upgrade()
        migration.upgrade()
        assert "outside_policy" in _columns(pg_conn, "teams")
        assert pg_conn.execute(text("SELECT count(*) FROM team_item_shares")).scalar() == 1
        assert {f"{t}_cleanup_team_item_shares" for t in _SHAREABLE} <= _triggers(pg_conn)
        assert {f"{t}_reown_team_item_shares" for t in _SHAREABLE} <= _triggers(pg_conn)

        migration.downgrade()
        migration.downgrade()
        assert "outside_policy" not in _columns(pg_conn, "teams")
        assert "teams_outside_policy_chk" not in _constraints(pg_conn, "teams")
        assert not _columns(pg_conn, "team_item_shares")
        assert "cleanup_team_item_shares" not in _functions(pg_conn)
        assert not {t for t in _triggers(pg_conn) if "team_item_shares" in t}

        migration.upgrade()
    assert pg_conn.execute(
        text("SELECT outside_policy FROM teams WHERE id = CAST(:t AS uuid)"), {"t": one}
    ).scalar() == "admins"
    _share(pg_conn, one, two, "agent", str(uuid.uuid4()))
