"""Tests for UserRolesRepository against a real Postgres instance."""

from __future__ import annotations

from application.storage.db.repositories.user_roles import UserRolesRepository


def _repo(conn) -> UserRolesRepository:
    return UserRolesRepository(conn)


class TestGrantRevoke:
    def test_grant_then_role_names(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.grant("alice") is True
        assert repo.role_names_for("alice") == ["admin"]

    def test_grant_is_idempotent(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.grant("alice") is True
        assert repo.grant("alice") is False
        assert repo.role_names_for("alice") == ["admin"]

    def test_revoke_removes_grant(self, pg_conn):
        repo = _repo(pg_conn)
        repo.grant("alice")
        assert repo.revoke("alice") is True
        assert repo.role_names_for("alice") == []

    def test_revoke_missing_is_false(self, pg_conn):
        assert _repo(pg_conn).revoke("nobody") is False

    def test_role_names_unknown_user(self, pg_conn):
        assert _repo(pg_conn).role_names_for("nobody") == []

    def test_role_names_empty_sub_short_circuits(self, pg_conn):
        assert _repo(pg_conn).role_names_for("") == []

    def test_granted_by_recorded(self, pg_conn):
        repo = _repo(pg_conn)
        repo.grant("alice", granted_by="cli")
        rows = repo.list_for("alice")
        assert rows[0]["granted_by"] == "cli"


class TestSourceCoexistence:
    def test_manual_and_oidc_grants_coexist(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.grant("alice", source="manual") is True
        assert repo.grant("alice", source="oidc_group") is True
        # role_names_for dedups to a single role across sources
        assert repo.role_names_for("alice") == ["admin"]
        assert {r["source"] for r in repo.list_for("alice")} == {"manual", "oidc_group"}

    def test_revoking_one_source_keeps_other(self, pg_conn):
        repo = _repo(pg_conn)
        repo.grant("alice", source="manual")
        repo.grant("alice", source="oidc_group")
        repo.revoke("alice", source="oidc_group")
        assert repo.role_names_for("alice") == ["admin"]
        assert {r["source"] for r in repo.list_for("alice")} == {"manual"}


class TestReconcileOidcAdmin:
    def test_reconcile_grants_then_no_change(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.reconcile_oidc_admin("alice", True) == "granted"
        assert repo.reconcile_oidc_admin("alice", True) is None
        assert repo.role_names_for("alice") == ["admin"]

    def test_reconcile_revokes_then_no_change(self, pg_conn):
        repo = _repo(pg_conn)
        repo.reconcile_oidc_admin("alice", True)
        assert repo.reconcile_oidc_admin("alice", False) == "revoked"
        assert repo.reconcile_oidc_admin("alice", False) is None
        assert repo.role_names_for("alice") == []

    def test_reconcile_revoke_preserves_manual_grant(self, pg_conn):
        repo = _repo(pg_conn)
        repo.grant("alice", source="manual")
        repo.reconcile_oidc_admin("alice", True)
        assert repo.reconcile_oidc_admin("alice", False) == "revoked"
        # manual grant survives the oidc-group revoke
        assert repo.role_names_for("alice") == ["admin"]
        assert {r["source"] for r in repo.list_for("alice")} == {"manual"}


class TestListAdmins:
    def test_empty(self, pg_conn):
        assert _repo(pg_conn).list_admins() == []

    def test_lists_distinct_users(self, pg_conn):
        repo = _repo(pg_conn)
        repo.grant("alice", source="manual")
        repo.grant("bob", source="oidc_group")
        assert {a["user_id"] for a in repo.list_admins()} == {"alice", "bob"}

    def test_dedups_user_with_multiple_sources(self, pg_conn):
        repo = _repo(pg_conn)
        repo.grant("alice", source="manual")
        repo.grant("alice", source="oidc_group")
        admins = repo.list_admins()
        assert len(admins) == 1
        assert set(admins[0]["sources"]) == {"manual", "oidc_group"}
