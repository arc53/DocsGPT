"""Tests for UserCustomModelsRepository against a real Postgres instance."""

from __future__ import annotations

from application.storage.db.repositories.user_custom_models import (
    UserCustomModelsRepository,
)


def _repo(conn) -> UserCustomModelsRepository:
    return UserCustomModelsRepository(conn)


def _make(repo, user="user-1", upstream="mistral-large-latest", **kwargs):
    return repo.create(
        user_id=user,
        upstream_model_id=upstream,
        display_name=kwargs.pop("display_name", "My Mistral"),
        base_url=kwargs.pop("base_url", "https://api.mistral.ai/v1"),
        api_key_plaintext=kwargs.pop("api_key_plaintext", "sk-mistral-test"),
        **kwargs,
    )


class TestCreate:
    def test_creates_minimal(self, pg_conn):
        repo = _repo(pg_conn)
        row = _make(repo)
        assert row["user_id"] == "user-1"
        assert row["upstream_model_id"] == "mistral-large-latest"
        assert row["display_name"] == "My Mistral"
        assert row["base_url"] == "https://api.mistral.ai/v1"
        assert row["enabled"] is True
        assert row["id"] is not None
        # Plaintext key never lands in the row
        assert row["api_key_encrypted"] != "sk-mistral-test"
        assert "sk-mistral-test" not in row["api_key_encrypted"]

    def test_capabilities_normalized_drops_unknown_keys(self, pg_conn):
        repo = _repo(pg_conn)
        row = _make(
            repo,
            capabilities={
                "supports_tools": True,
                "context_window": 200_000,
                "garbage_key": "should be dropped",
            },
        )
        assert row["capabilities"] == {
            "supports_tools": True,
            "context_window": 200_000,
        }


class TestGet:
    def test_get_by_id_returns_row(self, pg_conn):
        repo = _repo(pg_conn)
        created = _make(repo)
        fetched = repo.get(created["id"], "user-1")
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_get_other_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = _make(repo, user="alice")
        # Bob cannot fetch Alice's row even with the right id
        assert repo.get(created["id"], "bob") is None

    def test_get_missing_id_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        _make(repo)
        # A different (but valid) UUID
        assert repo.get("00000000-0000-0000-0000-000000000000", "user-1") is None


class TestListForUser:
    def test_lists_only_users_own(self, pg_conn):
        repo = _repo(pg_conn)
        _make(repo, user="alice", upstream="alice-1")
        _make(repo, user="alice", upstream="alice-2")
        _make(repo, user="bob", upstream="bob-1")
        alice = repo.list_for_user("alice")
        assert {r["upstream_model_id"] for r in alice} == {"alice-1", "alice-2"}
        bob = repo.list_for_user("bob")
        assert {r["upstream_model_id"] for r in bob} == {"bob-1"}


class TestUpdate:
    def test_update_partial(self, pg_conn):
        repo = _repo(pg_conn)
        created = _make(repo)
        ok = repo.update(
            created["id"],
            "user-1",
            {"display_name": "Renamed", "enabled": False},
        )
        assert ok is True
        fetched = repo.get(created["id"], "user-1")
        assert fetched["display_name"] == "Renamed"
        assert fetched["enabled"] is False

    def test_update_capabilities_normalizes(self, pg_conn):
        repo = _repo(pg_conn)
        created = _make(repo)
        repo.update(
            created["id"],
            "user-1",
            {"capabilities": {"supports_tools": False, "garbage": 1}},
        )
        fetched = repo.get(created["id"], "user-1")
        assert fetched["capabilities"] == {"supports_tools": False}

    def test_update_api_key_re_encrypts(self, pg_conn):
        repo = _repo(pg_conn)
        created = _make(repo)
        before = created["api_key_encrypted"]
        repo.update(
            created["id"],
            "user-1",
            {"api_key_plaintext": "sk-mistral-new"},
        )
        fetched = repo.get(created["id"], "user-1")
        # Ciphertext changed
        assert fetched["api_key_encrypted"] != before
        # Plaintext absent
        assert "sk-mistral-new" not in fetched["api_key_encrypted"]
        # And decrypts back to the new value
        plaintext = repo.get_decrypted_api_key(created["id"], "user-1")
        assert plaintext == "sk-mistral-new"

    def test_update_other_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = _make(repo, user="alice")
        # Bob can't update Alice's row
        ok = repo.update(created["id"], "bob", {"display_name": "Hacked"})
        assert ok is False
        # And Alice's row is untouched
        fetched = repo.get(created["id"], "alice")
        assert fetched["display_name"] == "My Mistral"


class TestDelete:
    def test_delete_removes_row(self, pg_conn):
        repo = _repo(pg_conn)
        created = _make(repo)
        assert repo.delete(created["id"], "user-1") is True
        assert repo.get(created["id"], "user-1") is None

    def test_delete_other_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = _make(repo, user="alice")
        assert repo.delete(created["id"], "bob") is False
        # Alice's row still there
        assert repo.get(created["id"], "alice") is not None


class TestEncryptionRoundtrip:
    def test_decrypted_matches_original(self, pg_conn):
        repo = _repo(pg_conn)
        created = _make(repo, api_key_plaintext="my-very-secret-key-12345")
        plaintext = repo.get_decrypted_api_key(created["id"], "user-1")
        assert plaintext == "my-very-secret-key-12345"

    def test_decryption_with_wrong_user_fails_silently(self, pg_conn):
        repo = _repo(pg_conn)
        # Per-user PBKDF2 salt: Alice's record can't be decrypted with
        # Bob's user_id even if Bob somehow has the row.
        created = _make(repo, user="alice", api_key_plaintext="alice-secret")
        # Manually call decrypt with the wrong user_id (simulates the
        # registry layer being given the wrong user context).
        wrong = repo._decrypt_api_key(created["api_key_encrypted"], "bob")
        assert wrong != "alice-secret"  # either None or garbage; not the secret
