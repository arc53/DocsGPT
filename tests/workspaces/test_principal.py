"""Team principals: ids, the row created with the team, team deletion and the person-only user writes."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamNotEmpty, TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import (
    ADMIN_NOTICE_KINDS,
    PRINCIPAL_PREFIX,
    create_principal,
    is_principal_id,
    principal_id,
    route_owner_notice,
    team_of_principal,
)


def _team(conn, owner: str = "alice", name: str = "Ops") -> dict:
    return TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner_id=owner)


def _count(conn, sql: str, **params) -> int:
    return int(conn.execute(text(sql), params).scalar())


class TestIds:
    def test_principal_id_is_the_prefix_and_the_canonical_team_id(self):
        team_id = uuid.uuid4()
        assert principal_id(str(team_id).upper()) == f"__team__{team_id}"
        assert principal_id(team_id) == f"{PRINCIPAL_PREFIX}{team_id}"

    @pytest.mark.parametrize("bad", ["", None, "ops", "__team__x"])
    def test_principal_id_refuses_a_non_uuid(self, bad):
        with pytest.raises(ValueError):
            principal_id(bad)

    def test_is_principal_id_is_syntax_only(self):
        assert is_principal_id("__team__anything")
        assert not is_principal_id("alice")
        assert not is_principal_id("__system__")
        assert not is_principal_id(None)
        assert not is_principal_id(42)

    def test_team_of_principal(self):
        team_id = str(uuid.uuid4())
        assert team_of_principal(principal_id(team_id)) == team_id
        assert team_of_principal("__team__not-a-uuid") is None
        assert team_of_principal("alice") is None
        assert team_of_principal(None) is None


class TestCreateWithTeam:
    def test_the_principal_row_is_created_with_the_team(self, pg_conn):
        team = _team(pg_conn)
        row = UsersRepository(pg_conn).team_principal(str(team["id"]))
        assert row["user_id"] == principal_id(team["id"])
        assert row["kind"] == "team"
        assert str(row["team_id"]) == str(team["id"])

    def test_create_principal_is_idempotent(self, pg_conn):
        team = _team(pg_conn)
        again = create_principal(pg_conn, str(team["id"]))
        assert again["user_id"] == principal_id(team["id"])
        assert _count(pg_conn, "SELECT count(*) FROM users WHERE kind = 'team'") == 1

    def test_team_principal_is_none_for_an_unknown_team(self, pg_conn):
        assert UsersRepository(pg_conn).team_principal(str(uuid.uuid4())) is None
        assert UsersRepository(pg_conn).team_principal("nope") is None

    def test_items_can_be_written_under_the_principal(self, pg_conn):
        principal = principal_id(_team(pg_conn)["id"])
        pg_conn.execute(
            text("INSERT INTO agents (user_id, name, status, created_by) VALUES (:u, 'A', 'draft', 'alice')"),
            {"u": principal},
        )
        assert _count(pg_conn, "SELECT count(*) FROM agents WHERE user_id = :u", u=principal) == 1

    def test_a_principal_id_of_no_team_cannot_own_items(self, pg_conn):
        with pytest.raises(IntegrityError), pg_conn.begin_nested():
            pg_conn.execute(
                text("INSERT INTO agents (user_id, name, status) VALUES (:u, 'A', 'draft')"),
                {"u": principal_id(uuid.uuid4())},
            )

    def test_a_principal_is_never_a_member(self, pg_conn):
        team = _team(pg_conn)
        with pytest.raises(IntegrityError), pg_conn.begin_nested():
            TeamMembersRepository(pg_conn).add_member(str(team["id"]), principal_id(team["id"]))


class TestDelete:
    def test_a_team_that_owns_items_is_not_deleted(self, pg_conn):
        team = _team(pg_conn)
        team_id = str(team["id"])
        principal = principal_id(team_id)
        pg_conn.execute(text("INSERT INTO agents (user_id, name, status) VALUES (:u, 'A', 'draft')"), {"u": principal})
        pg_conn.execute(text("INSERT INTO agents (user_id, name, status) VALUES (:u, 'B', 'draft')"), {"u": principal})
        pg_conn.execute(text("INSERT INTO prompts (user_id, name, content) VALUES (:u, 'p', 'c')"), {"u": principal})
        pg_conn.execute(text("INSERT INTO folders (user_id, name) VALUES (:u, 'F')"), {"u": principal})
        with pytest.raises(TeamNotEmpty) as refused:
            TeamsRepository(pg_conn).delete(team_id)
        assert refused.value.counts == {"agent": 2, "prompt": 1, "folder": 1}
        assert TeamsRepository(pg_conn).get(team_id) is not None
        assert UsersRepository(pg_conn).team_principal(team_id) is not None

    def test_holdings_name_other_tables_by_table(self, pg_conn):
        team_id = str(_team(pg_conn)["id"])
        pg_conn.execute(
            text("INSERT INTO memories (user_id, path, content) VALUES (:u, '/m', 'x')"), {"u": principal_id(team_id)}
        )
        assert TeamsRepository(pg_conn).principal_holdings(team_id) == {"memories": 1}

    def test_an_empty_team_goes_with_its_principal_and_chats(self, pg_conn):
        team_id = str(_team(pg_conn)["id"])
        principal = principal_id(team_id)
        TeamMembersRepository(pg_conn).add_member(team_id, "bob", role="team_viewer")
        pg_conn.execute(
            text("INSERT INTO conversations (user_id, name, team_id) VALUES ('bob', 'b', CAST(:t AS uuid))"),
            {"t": team_id},
        )
        # A widget chat of a team agent that was deleted since is the principal's own.
        pg_conn.execute(text("INSERT INTO conversations (user_id, name) VALUES (:u, 'w')"), {"u": principal})
        pg_conn.execute(text("INSERT INTO conversations (user_id, name) VALUES ('bob', 'personal')"))
        assert TeamsRepository(pg_conn).delete(team_id) is True
        assert TeamsRepository(pg_conn).get(team_id) is None
        assert _count(pg_conn, "SELECT count(*) FROM users WHERE user_id = :u", u=principal) == 0
        names = [r[0] for r in pg_conn.execute(text("SELECT name FROM conversations ORDER BY name"))]
        assert names == ["personal"]

    def test_deleting_a_missing_team_is_false(self, pg_conn):
        assert TeamsRepository(pg_conn).delete(str(uuid.uuid4())) is False


class TestUsersArePersons:
    def test_upsert_leaves_a_principal_row_alone(self, pg_conn):
        principal = principal_id(_team(pg_conn)["id"])
        row = UsersRepository(pg_conn).upsert(principal, email="team@example.com")
        assert row["kind"] == "team"
        assert row["email"] is None

    def test_upsert_refuses_a_principal_id_with_no_team(self, pg_conn):
        with pytest.raises(ValueError):
            UsersRepository(pg_conn).upsert(principal_id(uuid.uuid4()))

    def test_upsert_reads_back_kind_for_a_person(self, pg_conn):
        row = UsersRepository(pg_conn).upsert("dana", email="dana@example.com")
        assert (row["kind"], row["email"]) == ("user", "dana@example.com")

    def test_set_email_skips_non_persons(self, pg_conn):
        principal = principal_id(_team(pg_conn)["id"])
        repo = UsersRepository(pg_conn)
        repo.set_email(principal, "team@example.com")
        assert repo.get(principal)["email"] is None
        pg_conn.execute(text("INSERT INTO users (user_id, kind) VALUES ('__system__', 'system') ON CONFLICT DO NOTHING"))
        repo.set_email("__system__", "sys@example.com")
        assert repo.get("__system__")["email"] is None

    def test_find_by_email_matches_persons_only(self, pg_conn):
        principal = principal_id(_team(pg_conn)["id"])
        pg_conn.execute(text("UPDATE users SET email = 'shared@example.com' WHERE user_id = :u"), {"u": principal})
        assert UsersRepository(pg_conn).find_by_email("shared@example.com") is None

    def test_scim_create_refuses_the_reserved_prefix(self, pg_conn):
        assert UsersRepository(pg_conn).create("__team__whatever") is None


class TestRouteOwnerNotice:
    def test_a_person_owner_is_told(self, pg_conn):
        assert route_owner_notice(pg_conn, "alice", None, "schedule_failed") == ["alice"]
        assert route_owner_notice(pg_conn, "alice", "bob", "schedule") == ["alice"]

    def test_a_principal_owner_routes_to_the_actor(self, pg_conn):
        principal = principal_id(_team(pg_conn)["id"])
        assert route_owner_notice(pg_conn, principal, "bob", "source.ingest.failed") == ["bob"]

    def test_a_principal_actor_is_never_a_recipient(self, pg_conn):
        principal = principal_id(_team(pg_conn)["id"])
        assert route_owner_notice(pg_conn, principal, principal, "schedule") == []

    def test_a_failure_with_no_actor_reaches_the_admins_and_owner(self, pg_conn):
        team_id = str(_team(pg_conn, owner="alice")["id"])
        members = TeamMembersRepository(pg_conn)
        members.add_member(team_id, "alice", role="team_admin")
        members.add_member(team_id, "erin", role="team_admin", source="oidc_group")
        members.add_member(team_id, "bob", role="team_editor")
        assert "schedule_failed" in ADMIN_NOTICE_KINDS
        assert route_owner_notice(pg_conn, principal_id(team_id), None, "schedule_failed") == ["alice", "erin"]

    def test_anything_else_with_no_actor_is_dropped(self, pg_conn):
        team_id = str(_team(pg_conn)["id"])
        assert route_owner_notice(pg_conn, principal_id(team_id), None, "source.ingest.completed") == []

    def test_no_owner_no_recipient(self, pg_conn):
        assert route_owner_notice(pg_conn, None, None, "schedule_failed") == []
