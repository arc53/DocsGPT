"""Tests for scripts/grant_admin.py orchestration (grant/revoke/list/exit codes).

Drives ``grant_admin.main(argv)`` against the ephemeral ``pg_conn`` by
redirecting the script's ``db_session`` / ``db_readonly`` to yield that
transactional connection — so every write rolls back at teardown. The
underlying repository SQL is covered by
``tests/storage/db/repositories/test_user_roles.py``; these tests pin the
script's own decision logic (audit-gating, manual-only revoke, exit codes).
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

# Project root on sys.path so ``scripts`` is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import grant_admin  # noqa: E402
from application.storage.db.repositories.auth_events import (  # noqa: E402
    AuthEventsRepository,
)
from application.storage.db.repositories.user_roles import (  # noqa: E402
    UserRolesRepository,
)
from application.storage.db.repositories.users import UsersRepository  # noqa: E402


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

    def test_idempotent_grant_does_not_double_audit(self, patched_db):
        assert grant_admin.main(["alice", "--force"]) == 0
        assert grant_admin.main(["alice", "--force"]) == 0
        assert _audit_count(patched_db, "alice", "role_granted") == 1


class TestRevoke:
    def test_revoke_removes_manual_only_and_audits(self, patched_db):
        repo = UserRolesRepository(patched_db)
        repo.grant("alice", source="manual")
        repo.grant("alice", source="oidc_group")
        assert grant_admin.main(["alice", "--revoke"]) == 0
        assert {r["source"] for r in repo.list_for("alice")} == {"oidc_group"}
        assert _audit_count(patched_db, "alice", "role_revoked") == 1

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
