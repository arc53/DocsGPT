"""``reseal_for_owner``: a credential blob moved from one owner to another (a person and a team principal)."""

from __future__ import annotations

import pytest

from docsgpt.security import encryption as enc

TEAM = "__team__3f2a1c6e-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    from docsgpt.core.settings import settings

    monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "current-key-for-tests")
    monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY_PREVIOUS", None)
    yield


class TestV1:
    def test_a_v1_blob_comes_out_as_a_v2_envelope(self):
        blob = enc.encrypt_credentials({"api_key": "sk-1"}, "alice")
        moved = enc.reseal_for_owner(blob, "alice", TEAM)
        assert moved.startswith("v2:")
        assert enc.decrypt_json(moved, TEAM) == {"api_key": "sk-1"}
        with pytest.raises(enc.CredentialDecryptionError):
            enc.decrypt_json(moved, "alice")
        back = enc.reseal_for_owner(moved, TEAM, "alice")
        assert back.startswith("v2:")
        assert enc.decrypt_json(back, "alice") == {"api_key": "sk-1"}

    def test_a_blob_written_with_the_previous_key_is_rewritten_with_the_current(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "old-key")
        blob = enc.encrypt_credentials({"token": "t"}, "alice")
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "current-key-for-tests")
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY_PREVIOUS", "old-key")
        moved = enc.reseal_for_owner(blob, "alice", TEAM)
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY_PREVIOUS", None)
        assert moved.startswith("v2:")
        assert enc.decrypt_json(moved, TEAM) == {"token": "t"}

    def test_wrong_old_owner_raises_and_never_returns_an_empty_blob(self):
        blob = enc.encrypt_credentials({"api_key": "sk-1"}, "alice")
        with pytest.raises(enc.CredentialDecryptionError):
            enc.reseal_for_owner(blob, "bob", TEAM)

    def test_garbage_raises(self):
        with pytest.raises(enc.CredentialDecryptionError):
            enc.reseal_for_owner("not base64 !!", "alice", TEAM)


class TestV2:
    def test_round_trip_to_a_team(self):
        blob = enc.encrypt_json({"access_token": "at"}, "alice")
        moved = enc.reseal_for_owner(blob, "alice", TEAM)
        assert moved.startswith("v2:")
        assert enc.decrypt_json(moved, TEAM) == {"access_token": "at"}
        with pytest.raises(enc.CredentialDecryptionError):
            enc.decrypt_json(moved, "alice")

    def test_wrong_old_owner_raises(self):
        blob = enc.encrypt_json({"access_token": "at"}, "alice")
        with pytest.raises(enc.CredentialDecryptionError):
            enc.reseal_for_owner(blob, "bob", TEAM)


class TestNothingToReseal:
    @pytest.mark.parametrize("blob", ["", None])
    def test_empty_stays_empty(self, blob):
        assert enc.reseal_for_owner(blob, "alice", TEAM) == ""

    def test_same_owner_is_returned_as_is(self):
        blob = enc.encrypt_credentials({"api_key": "sk-1"}, "alice")
        assert enc.reseal_for_owner(blob, "alice", "alice") == blob
