import base64

import pytest
from application.security import encryption
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import algorithms, Cipher, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


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
    nonce = bytes(range(12))
    monkeypatch.setattr(
        encryption.os, "urandom", _fake_os_urandom_factory([salt, nonce])
    )

    credentials = {"token": "abc123", "refresh": "xyz789"}

    encrypted = encryption.encrypt_credentials(credentials, "user-123")

    decoded = base64.b64decode(encrypted)
    assert decoded[0:1] == encryption._VERSION_GCM
    assert decoded[1:17] == salt
    assert decoded[17:29] == nonce

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
def test_decrypt_legacy_cbc_format(monkeypatch):
    """Old AES-CBC encrypted data should still decrypt correctly."""
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")

    salt = bytes(range(16))
    iv = bytes(range(16, 32))
    key = encryption._derive_key("user-123", salt)

    import json

    plaintext = json.dumps({"token": "legacy-abc"}).encode()
    padded = encryption._pad_data(plaintext)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    legacy_blob = base64.b64encode(salt + iv + ciphertext).decode()

    result = encryption.decrypt_credentials(legacy_blob, "user-123")
    assert result == {"token": "legacy-abc"}


@pytest.mark.unit
def test_tampered_gcm_ciphertext_returns_empty(monkeypatch):
    """Tampered GCM ciphertext must fail authentication and return {}."""
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")
    monkeypatch.setattr(encryption.os, "urandom", lambda length: b"\x00" * length)

    credentials = {"secret": "value"}
    encrypted = encryption.encrypt_credentials(credentials, "user-123")

    raw = bytearray(base64.b64decode(encrypted))
    raw[-1] ^= 0xFF  # flip last byte of ciphertext+tag
    tampered = base64.b64encode(bytes(raw)).decode()

    assert encryption.decrypt_credentials(tampered, "user-123") == {}


@pytest.mark.unit
def test_gcm_cross_user_replay_returns_empty(monkeypatch):
    """GCM ciphertext encrypted for one user must not decrypt under another user."""
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")
    monkeypatch.setattr(encryption.os, "urandom", lambda length: b"\x00" * length)

    credentials = {"secret": "value"}
    encrypted = encryption.encrypt_credentials(credentials, "user-A")

    assert encryption.decrypt_credentials(encrypted, "user-B") == {}


@pytest.mark.unit
def test_legacy_cbc_salt_starting_with_version_byte(monkeypatch):
    """Legacy CBC blob whose salt starts with 0x01 must still decrypt via fallback."""
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")

    # Salt intentionally starts with 0x01 — same as _VERSION_GCM
    salt = b"\x01" + bytes(range(1, 16))
    iv = bytes(range(16, 32))
    key = encryption._derive_key("user-123", salt)

    import json

    plaintext = json.dumps({"token": "collision-test"}).encode()
    padded = encryption._pad_data(plaintext)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    legacy_blob = base64.b64encode(salt + iv + ciphertext).decode()

    result = encryption.decrypt_credentials(legacy_blob, "user-123")
    assert result == {"token": "collision-test"}


@pytest.mark.unit
def test_corrupt_legacy_cbc_payload_returns_empty(monkeypatch):
    """Structurally valid but corrupt CBC payload should return {} via unpad error."""
    monkeypatch.setattr(encryption.settings, "ENCRYPTION_SECRET_KEY", "test-secret")

    salt = bytes(range(16))
    iv = bytes(range(16, 32))

    # 16 bytes of garbage — valid block size but invalid padding and JSON
    corrupt_ciphertext = bytes(range(32, 48))

    corrupt_blob = base64.b64encode(salt + iv + corrupt_ciphertext).decode()

    assert encryption.decrypt_credentials(corrupt_blob, "user-123") == {}


@pytest.mark.unit
def test_pad_and_unpad_are_inverse():
    original = b"secret-data"

    padded = encryption._pad_data(original)

    assert len(padded) % 16 == 0
    assert encryption._unpad_data(padded) == original


@pytest.mark.unit
def test_pad_data_exact_block_size():
    # When input is exactly 16 bytes, a full block of padding is added
    original = b"0123456789abcdef"
    assert len(original) == 16

    padded = encryption._pad_data(original)

    # Should be 32 bytes (16 + 16 padding)
    assert len(padded) == 32
    assert encryption._unpad_data(padded) == original


@pytest.mark.unit
def test_pad_data_various_sizes():
    for size in range(1, 33):
        data = b"x" * size
        padded = encryption._pad_data(data)
        assert len(padded) % 16 == 0
        assert encryption._unpad_data(padded) == data


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

    # Decrypting with wrong user should fail gracefully
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
    # base64 of only 10 bytes - not enough for salt+iv
    import base64

    short = base64.b64encode(b"0123456789").decode()
    assert encryption.decrypt_credentials(short, "user-1") == {}
