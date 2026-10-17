"""Tests for the v2 credential envelope."""

from __future__ import annotations

import base64

import pytest

from docsgpt.security import encryption as enc


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    from docsgpt.core.settings import settings

    monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "current-key-for-tests")
    monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY_PREVIOUS", None)
    yield


class TestEnvelope:
    def test_round_trip(self):
        blob = enc.encrypt_json({"access_token": "at", "n": 1}, "alice")
        assert blob.startswith("v2:")
        assert enc.decrypt_json(blob, "alice") == {"access_token": "at", "n": 1}

    def test_plaintext_never_in_blob(self):
        blob = enc.encrypt_json({"refresh_token": "very-secret-refresh"}, "alice")
        assert "very-secret-refresh" not in blob
        assert "very-secret-refresh".encode() not in base64.b64decode(blob.split(":", 2)[2])

    def test_each_blob_is_unique(self):
        assert enc.encrypt_json({"a": 1}, "alice") != enc.encrypt_json({"a": 1}, "alice")

    def test_bound_to_owner(self):
        blob = enc.encrypt_json({"a": 1}, "alice")
        with pytest.raises(enc.CredentialDecryptionError):
            enc.decrypt_json(blob, "bob")

    def test_tampering_is_detected(self):
        blob = enc.encrypt_json({"a": 1}, "alice")
        prefix, key_id, payload = blob.split(":", 2)
        raw = bytearray(base64.b64decode(payload))
        raw[-1] ^= 0x01
        tampered = f"{prefix}:{key_id}:{base64.b64encode(bytes(raw)).decode()}"
        with pytest.raises(enc.CredentialDecryptionError):
            enc.decrypt_json(tampered, "alice")

    @pytest.mark.parametrize("blob", ["", "v1:abc", "v2:only-two", "v2:deadbeef:%%%not-base64"])
    def test_malformed(self, blob):
        with pytest.raises(enc.CredentialDecryptionError):
            enc.decrypt_json(blob, "alice")

    def test_key_id_names_the_key(self):
        blob = enc.encrypt_json({"a": 1}, "alice")
        assert enc.envelope_key_id(blob) == enc.current_key_id()
        assert enc.envelope_key_id("not an envelope") is None


class TestRotation:
    def test_unknown_key_fails(self, monkeypatch):
        from docsgpt.core.settings import settings

        blob = enc.encrypt_json({"a": 1}, "alice")
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "a-new-key")
        with pytest.raises(enc.CredentialDecryptionError):
            enc.decrypt_json(blob, "alice")

    def test_previous_key_still_decrypts(self, monkeypatch):
        from docsgpt.core.settings import settings

        blob = enc.encrypt_json({"a": 1}, "alice")
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "a-new-key")
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY_PREVIOUS", "current-key-for-tests")
        assert enc.decrypt_json(blob, "alice") == {"a": 1}
        assert enc.envelope_key_id(enc.encrypt_json({"a": 1}, "alice")) == enc.current_key_id()
        assert enc.envelope_key_id(blob) != enc.current_key_id()


class TestDefaultKey:
    def test_detects_default(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", enc.DEFAULT_ENCRYPTION_KEY)
        assert enc.is_default_encryption_key()

    def test_custom_key(self):
        assert not enc.is_default_encryption_key()


class TestLegacyV1Unchanged:
    def test_v1_round_trip_still_works(self):
        blob = enc.encrypt_credentials({"token": "t"}, "alice")
        assert enc.decrypt_credentials(blob, "alice") == {"token": "t"}
