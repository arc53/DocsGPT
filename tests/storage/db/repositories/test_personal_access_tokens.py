"""Tests for PersonalAccessTokensRepository against a real Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.personal_access_tokens import (
    PersonalAccessTokensRepository,
)


def _create(repo, user_id="u1", name="ci", token_hash="h1", **kwargs):
    kwargs.setdefault("scopes", ["agents:read"])
    return repo.create(
        user_id, name, token_hash=token_hash, token_prefix="dgpt_pat_abc123", **kwargs
    )


class TestCreateAndRead:
    def test_create_returns_public_columns_only(self, pg_conn):
        row = _create(
            PersonalAccessTokensRepository(pg_conn),
            resource_filter={"agents": ["00000000-0000-0000-0000-000000000001"]},
        )
        assert "token_hash" not in row
        assert row["status"] == "active"
        assert row["scopes"] == ["agents:read"]
        assert row["resource_filter"] == {"agents": ["00000000-0000-0000-0000-000000000001"]}
        assert row["expires_at"] is None

    def test_get_is_owner_scoped(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        row = _create(repo)
        assert repo.get(str(row["id"]), "u1")["name"] == "ci"
        assert repo.get(str(row["id"]), "someone-else") is None
        assert repo.get(str(row["id"]))["user_id"] == "u1"

    def test_list_hides_revoked_by_default(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        kept = _create(repo, name="kept", token_hash="h1")
        gone = _create(repo, name="gone", token_hash="h2")
        repo.revoke(str(gone["id"]), "u1")
        assert [r["id"] for r in repo.list_for_user("u1")] == [kept["id"]]
        assert len(repo.list_for_user("u1", include_revoked=True)) == 2
        assert repo.list_for_user("u2") == []


class TestUniqueness:
    def test_duplicate_active_name_rejected(self, pg_conn):
        from sqlalchemy.exc import IntegrityError

        repo = PersonalAccessTokensRepository(pg_conn)
        _create(repo, token_hash="h1")
        with pytest.raises(IntegrityError), pg_conn.begin_nested():
            _create(repo, token_hash="h2")

    def test_revoked_name_can_be_reused(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        first = _create(repo, token_hash="h1")
        repo.revoke(str(first["id"]), "u1")
        assert not repo.name_in_use("u1", "ci")
        assert _create(repo, token_hash="h2")["name"] == "ci"

    def test_same_name_for_other_user_is_fine(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        _create(repo, user_id="u1", token_hash="h1")
        _create(repo, user_id="u2", token_hash="h2")
        assert repo.name_in_use("u1", "ci") and repo.name_in_use("u2", "ci")


class TestFindActiveByHash:
    def test_finds_live_token(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        _create(repo)
        found = repo.find_active_by_hash("h1")
        assert found["user_id"] == "u1"
        assert "token_hash" not in found

    def test_unknown_hash(self, pg_conn):
        assert PersonalAccessTokensRepository(pg_conn).find_active_by_hash("nope") is None

    def test_revoked_token_never_matches(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        row = _create(repo)
        repo.revoke(str(row["id"]), "u1")
        assert repo.find_active_by_hash("h1") is None

    def test_expired_token_never_matches(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        _create(repo, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        assert repo.find_active_by_hash("h1") is None

    def test_future_expiry_matches(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        _create(repo, expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        assert repo.find_active_by_hash("h1") is not None

    def test_deactivated_user_token_never_matches(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        _create(repo)
        pg_conn.execute(
            text("INSERT INTO users (user_id, active) VALUES ('u1', false)")
        )
        assert repo.find_active_by_hash("h1") is None
        pg_conn.execute(text("UPDATE users SET active = true WHERE user_id = 'u1'"))
        assert repo.find_active_by_hash("h1") is not None


class TestRevoke:
    def test_revoke_is_owner_scoped(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        row = _create(repo)
        assert repo.revoke(str(row["id"]), "someone-else") is False
        assert repo.revoke(str(row["id"]), "u1") is True
        assert repo.revoke(str(row["id"]), "u1") is False
        stored = repo.get(str(row["id"]))
        assert stored["status"] == "revoked"
        assert stored["revoke_reason"] == "user_revoked"
        assert stored["revoked_at"] is not None

    def test_admin_revoke_needs_no_owner(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        row = _create(repo)
        assert repo.revoke(str(row["id"]), reason="admin_revoked") is True
        assert repo.get(str(row["id"]))["revoke_reason"] == "admin_revoked"

    def test_revoke_all_for_user(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        _create(repo, name="a", token_hash="h1")
        _create(repo, name="b", token_hash="h2")
        _create(repo, user_id="u2", token_hash="h3")
        assert repo.revoke_all_for_user("u1") == 2
        assert repo.list_for_user("u1") == []
        assert len(repo.list_for_user("u2")) == 1


class TestCountAndUsage:
    def test_count_active_ignores_revoked_and_expired(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        _create(repo, name="live", token_hash="h1")
        _create(
            repo,
            name="expired",
            token_hash="h2",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        revoked = _create(repo, name="revoked", token_hash="h3")
        repo.revoke(str(revoked["id"]), "u1")
        assert repo.count_active("u1") == 1

    def test_touch_last_used_is_throttled(self, pg_conn):
        repo = PersonalAccessTokensRepository(pg_conn)
        row = _create(repo)
        repo.touch_last_used(str(row["id"]), "10.0.0.1")
        first = repo.get(str(row["id"]))
        assert first["last_used_ip"] == "10.0.0.1"
        repo.touch_last_used(str(row["id"]), "10.0.0.2")
        assert repo.get(str(row["id"]))["last_used_ip"] == "10.0.0.1"
        repo.touch_last_used(str(row["id"]), "10.0.0.3", min_interval_seconds=0)
        assert repo.get(str(row["id"]))["last_used_ip"] == "10.0.0.3"
