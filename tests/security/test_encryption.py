import base64

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from application.security import encryption


def _fake_os_urandom_factory(values):
    values_iter = iter(values)

    def _fake(length):
        value = next(values_iter)
        assert len(value) == length
        return value

    return _fake


@pytest.mark.unit
def test_derive_key_uses_secret_and_user(monkeypatch):
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")
    salt = bytes(range(16))

    expected_kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend(),
    )
    expected_key = expected_kdf.derive(b"test-secret#user-123")

    derived = encryption._derive_key("user-123", salt)

    assert derived == expected_key


@pytest.mark.unit
def test_encrypt_and_decrypt_round_trip(monkeypatch):
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")
    salt = bytes(range(16))
    nonce = bytes(range(16, 28))
    monkeypatch.setattr(encryption.os, "urandom", _fake_os_urandom_factory([salt, nonce]))

    credentials = {"token": "abc123", "refresh": "xyz789"}

    encrypted = encryption.encrypt_credentials(credentials, "user-123")

    decoded = base64.b64decode(encrypted)
    assert decoded[:16] == salt
    assert decoded[16:28] == nonce

    decrypted = encryption.decrypt_credentials(encrypted, "user-123")

    assert decrypted == credentials


@pytest.mark.unit
def test_encrypt_credentials_returns_empty_for_empty_input(monkeypatch):
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")

    assert encryption.encrypt_credentials({}, "user-123") == ""
    assert encryption.encrypt_credentials(None, "user-123") == ""


@pytest.mark.unit
def test_encrypt_credentials_returns_empty_on_serialization_error(monkeypatch):
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")
    monkeypatch.setattr(encryption.os, "urandom", lambda length: b"\x00" * length)

    class NonSerializable:
        pass

    credentials = {"bad": NonSerializable()}

    assert encryption.encrypt_credentials(credentials, "user-123") == ""


@pytest.mark.unit
def test_decrypt_credentials_returns_empty_for_invalid_input(monkeypatch):
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")

    assert encryption.decrypt_credentials("", "user-123") == {}
    assert encryption.decrypt_credentials("not-base64", "user-123") == {}

    invalid_payload = base64.b64encode(b"short").decode()
    assert encryption.decrypt_credentials(invalid_payload, "user-123") == {}


@pytest.mark.unit
def test_encrypt_decrypt_complex_credentials(monkeypatch):
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "complex-secret")

    credentials = {
        "token": "abc123",
        "refresh": "xyz789",
        "nested": {"key": "value"},
        "list_field": [1, 2, 3],
        "unicode": "\u4f60\u597d\u4e16\u754c",
    }

    encrypted = encryption.encrypt_credentials(credentials, "user-456")
    decrypted = encryption.decrypt_credentials(encrypted, "user-456")

    assert decrypted == credentials


@pytest.mark.unit
def test_decrypt_with_wrong_user_returns_empty(monkeypatch):
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")

    credentials = {"token": "abc123"}
    encrypted = encryption.encrypt_credentials(credentials, "user-1")

    # Decrypting with wrong user should fail gracefully due to auth tag verification failure
    result = encryption.decrypt_credentials(encrypted, "user-2")
    assert result == {}


@pytest.mark.unit
def test_decrypt_with_wrong_secret_returns_empty(monkeypatch):
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "secret-1")
    credentials = {"token": "abc123"}
    encrypted = encryption.encrypt_credentials(credentials, "user-1")

    # Change the secret key
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "secret-2")
    result = encryption.decrypt_credentials(encrypted, "user-1")
    assert result == {}


@pytest.mark.unit
def test_encrypt_credentials_empty_dict(monkeypatch):
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")
    assert encryption.encrypt_credentials({}, "user-1") == ""


@pytest.mark.unit
def test_decrypt_credentials_truncated_payload(monkeypatch):
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")
    # base64 of only 10 bytes - not enough for salt + nonce + tag
    short = base64.b64encode(b"0123456789").decode()
    assert encryption.decrypt_credentials(short, "user-1") == {}


@pytest.mark.unit
def test_tampered_ciphertext_fails_integrity_verification(monkeypatch):
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")
    credentials = {"api_key": "sk-secret-12345", "service": "openai"}
    encrypted = encryption.encrypt_credentials(credentials, "user-1")

    raw_bytes = bytearray(base64.b64decode(encrypted.encode("utf-8")))

    # Tamper with the last byte (part of authentication tag / ciphertext)
    raw_bytes[-1] ^= 0x01
    tampered_encrypted = base64.b64encode(raw_bytes).decode("utf-8")

    assert encryption.decrypt_credentials(tampered_encrypted, "user-1") == {}


@pytest.mark.unit
def test_tampered_nonce_fails_integrity_verification(monkeypatch):
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")
    credentials = {"api_key": "sk-secret-12345"}
    encrypted = encryption.encrypt_credentials(credentials, "user-1")

    raw_bytes = bytearray(base64.b64decode(encrypted.encode("utf-8")))

    # Tamper with nonce byte (index 16-27)
    raw_bytes[18] ^= 0xFF
    tampered_encrypted = base64.b64encode(raw_bytes).decode("utf-8")

    assert encryption.decrypt_credentials(tampered_encrypted, "user-1") == {}
