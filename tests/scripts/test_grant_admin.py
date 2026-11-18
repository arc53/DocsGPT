"""Tests for ``docsgpt grant-admin`` (docsgpt/scripts/grant_admin.py) orchestration (grant/revoke/list/exit codes).

Drives ``grant_admin.main(argv)`` against the ephemeral ``pg_conn`` by
redirecting the script's ``db_session`` / ``db_readonly`` to yield that
transactional connection — so every write rolls back at teardown. The
underlying repository SQL is covered by
``tests/storage/db/repositories/test_user_roles.py``; these tests pin the
script's own decision logic (audit-gating, manual-only revoke, exit codes).
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from docsgpt.scripts import grant_admin
from docsgpt.storage.db.repositories.auth_events import AuthEventsRepository
from docsgpt.storage.db.repositories.user_roles import UserRolesRepository
from docsgpt.storage.db.repositories.users import UsersRepository


@pytest.fixture
def patched_db(pg_conn, monkeypatch):
    @contextmanager
    def _use_pg_conn():
        yield pg_conn

    monkeypatch.setattr(grant_admin, "db_session", _use_pg_conn)
    monkeypatch.setattr(grant_admin, "db_readonly", _use_pg_conn)
    return pg_conn


def _audit_count(conn, user_id: str, event: str) -> int:
    rows = AuthEventsRepository(conn).list_recent(user_id, limit=100)
    return sum(1 for r in rows if r["event"] == event)


def _audit_actors(conn, user_id: str, event: str) -> list:
    rows = AuthEventsRepository(conn).list_recent(user_id, limit=100)
    return [r["actor_id"] for r in rows if r["event"] == event]


class TestGrant:
    def test_missing_user_without_force_returns_1_and_writes_nothing(self, patched_db):
        assert grant_admin.main(["ghost"]) == 1
        assert UserRolesRepository(patched_db).role_names_for("ghost") == []
        assert _audit_count(patched_db, "ghost", "role_granted") == 0

    def test_force_inserts_grant_and_exactly_one_audit(self, patched_db):
        assert grant_admin.main(["alice", "--force"]) == 0
        assert UserRolesRepository(patched_db).role_names_for("alice") == ["admin"]
        assert _audit_count(patched_db, "alice", "role_granted") == 1

    def test_existing_user_grants_without_force(self, patched_db):
        UsersRepository(patched_db).upsert("bob")
        assert grant_admin.main(["bob"]) == 0
        assert UserRolesRepository(patched_db).role_names_for("bob") == ["admin"]

    def test_grant_audit_names_the_cli_as_actor(self, patched_db):
        assert grant_admin.main(["alice", "--force"]) == 0
        assert _audit_actors(patched_db, "alice", "role_granted") == ["cli"]

    def test_idempotent_grant_does_not_double_audit(self, patched_db):
        assert grant_admin.main(["alice", "--force"]) == 0
        assert grant_admin.main(["alice", "--force"]) == 0
        assert _audit_count(patched_db, "alice", "role_granted") == 1

    @pytest.mark.parametrize("force", [False, True])
    def test_a_team_principal_is_never_granted_even_with_force(self, patched_db, force):
        from docsgpt.storage.db.repositories.teams import TeamsRepository
        from docsgpt.workspaces.principal import principal_id

        team = TeamsRepository(patched_db).create("Ops", "ops-wp2", owner_id="alice")
        principal = principal_id(team["id"])
        argv = [principal, "--force"] if force else [principal]
        assert grant_admin.main(argv) == 1
        assert UserRolesRepository(patched_db).role_names_for(principal) == []
        assert _audit_count(patched_db, principal, "role_granted") == 0

    def test_an_unknown_principal_id_is_refused_with_force(self, patched_db):
        assert grant_admin.main(["__team__not-a-team", "--force"]) == 1
        assert UserRolesRepository(patched_db).role_names_for("__team__not-a-team") == []

    def test_the_system_row_is_never_granted(self, patched_db):
        assert grant_admin.main(["__system__", "--force"]) == 1
        assert UserRolesRepository(patched_db).role_names_for("__system__") == []


class TestRevoke:
    def test_revoke_removes_manual_only_and_audits(self, patched_db):
        repo = UserRolesRepository(patched_db)
        repo.grant("alice", source="manual")
        repo.grant("alice", source="oidc_group")
        assert grant_admin.main(["alice", "--revoke"]) == 0
        assert {r["source"] for r in repo.list_for("alice")} == {"oidc_group"}
        assert _audit_count(patched_db, "alice", "role_revoked") == 1

    def test_revoke_audit_names_the_cli_as_actor(self, patched_db):
        UserRolesRepository(patched_db).grant("alice", source="manual")
        assert grant_admin.main(["alice", "--revoke"]) == 0
        assert _audit_actors(patched_db, "alice", "role_revoked") == ["cli"]

    def test_revoke_without_grant_returns_0_and_no_audit(self, patched_db):
        assert grant_admin.main(["nobody", "--revoke"]) == 0
        assert _audit_count(patched_db, "nobody", "role_revoked") == 0


class TestList:
    def test_list_prints_admins(self, patched_db, capsys):
        UserRolesRepository(patched_db).grant("alice", source="manual")
        assert grant_admin.main(["--list"]) == 0
        assert "alice" in capsys.readouterr().out


class TestErrors:
    def test_db_error_returns_2(self, monkeypatch):
        @contextmanager
        def _boom():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        monkeypatch.setattr(grant_admin, "db_session", _boom)
        monkeypatch.setattr(grant_admin, "db_readonly", _boom)
        assert grant_admin.main(["alice", "--force"]) == 2
