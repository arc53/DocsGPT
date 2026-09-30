import base64
import functools
import hashlib
import hmac
import json
import logging
import os
from typing import Optional

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import algorithms, Cipher, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from docsgpt.core.settings import settings

logger = logging.getLogger(__name__)


def _derive_key(user_id: str, salt: bytes, app_secret: Optional[str] = None) -> bytes:
    """Derive the v1 record key for ``user_id``.

    Args:
        user_id: The owner the credentials are bound to.
        salt: The record's random salt.
        app_secret: The master secret; ``ENCRYPTION_SECRET_KEY`` when omitted.

    Returns:
        The 32-byte AES key.
    """
    app_secret = settings.ENCRYPTION_SECRET_KEY if app_secret is None else app_secret

    password = f"{app_secret}#{user_id}".encode()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend(),
    )

    return kdf.derive(password)


def encrypt_credentials(credentials: dict, user_id: str) -> str:
    if not credentials:
        return ""
    try:
        salt = os.urandom(16)
        iv = os.urandom(16)
        key = _derive_key(user_id, salt)

        json_str = json.dumps(credentials)

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()

        padded_data = _pad_data(json_str.encode())
        encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

        result = salt + iv + encrypted_data
        return base64.b64encode(result).decode()
    except Exception as e:
        logger.warning(f"Failed to encrypt credentials: {e}")
        return ""


def _v1_secrets() -> list[str]:
    """Master secrets a v1 blob may have been written with: current first, then the previous one."""
    secrets = [settings.ENCRYPTION_SECRET_KEY]
    previous = settings.ENCRYPTION_SECRET_KEY_PREVIOUS
    if previous and previous not in secrets:
        secrets.append(previous)
    return secrets


def _decrypt_v1(data: bytes, user_id: str, app_secret: str) -> dict:
    salt = data[:16]
    iv = data[16:32]
    encrypted_content = data[32:]

    key = _derive_key(user_id, salt, app_secret)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()

    decrypted_padded = decryptor.update(encrypted_content) + decryptor.finalize()
    decrypted_data = _unpad_data(decrypted_padded)

    result = json.loads(decrypted_data.decode())
    if not isinstance(result, dict):
        raise ValueError("Credential payload is not an object")
    return result


def decrypt_credentials(encrypted_data: str, user_id: str) -> dict:
    """Decrypt a v1 credential blob (tool, MCP and custom-model secrets).

    The blob is tried with ``ENCRYPTION_SECRET_KEY`` and then with
    ``ENCRYPTION_SECRET_KEY_PREVIOUS``, so secrets stay readable during a key
    rotation. New blobs are always written with the current key.

    Args:
        encrypted_data: The base64 blob from :func:`encrypt_credentials`.
        user_id: The owner the blob was written for.

    Returns:
        The credentials, or an empty dict when no key opens the blob.
    """
    if not encrypted_data:
        return {}
    try:
        data = base64.b64decode(encrypted_data.encode())
    except Exception as e:
        logger.warning(f"Failed to decrypt credentials: {e}")
        return {}
    error: Optional[Exception] = None
    for app_secret in _v1_secrets():
        try:
            return _decrypt_v1(data, user_id, app_secret)
        except Exception as e:
            error = e
    logger.warning(f"Failed to decrypt credentials: {error}")
    return {}


def reseal_credentials(encrypted_data: str, user_id: str) -> tuple[str, Optional[str]]:
    """Re-encrypt a v1 blob with ``ENCRYPTION_SECRET_KEY`` when it was written with the previous key.

    Used by ``docsgpt connectors reencrypt`` so ``ENCRYPTION_SECRET_KEY_PREVIOUS``
    can be removed afterwards. A blob no key opens is never replaced.

    Args:
        encrypted_data: The base64 blob from :func:`encrypt_credentials`.
        user_id: The owner the blob was written for.

    Returns:
        ``("current", None)`` when the current key already opens it,
        ``("rewritten", new_blob)`` when only the previous key does, and
        ``("failed", None)`` when neither does.
    """
    try:
        data = base64.b64decode(encrypted_data.encode(), validate=True)
    except Exception:
        return "failed", None
    current = settings.ENCRYPTION_SECRET_KEY
    try:
        _decrypt_v1(data, user_id, current)
        return "current", None
    except Exception:
        pass
    previous = settings.ENCRYPTION_SECRET_KEY_PREVIOUS
    if not previous or previous == current:
        return "failed", None
    try:
        credentials = _decrypt_v1(data, user_id, previous)
    except Exception:
        return "failed", None
    resealed = encrypt_credentials(credentials, user_id)
    return ("rewritten", resealed) if resealed else ("failed", None)


def _pad_data(data: bytes) -> bytes:
    block_size = 16
    padding_len = block_size - (len(data) % block_size)
    padding = bytes([padding_len]) * padding_len
    return data + padding


def _unpad_data(data: bytes) -> bytes:
    padding_len = data[-1]
    return data[:-padding_len]


# ---------------------------------------------------------------------------
# Envelope v2: connection credentials
# ---------------------------------------------------------------------------
#
# ``v2:<key_id>:<base64(salt | nonce | ciphertext+tag)>``
#
# AES-256-GCM, so a tampered blob fails to decrypt instead of returning
# garbage. The master key is derived once per process from
# ENCRYPTION_SECRET_KEY (PBKDF2, cached); each record gets its own key from
# HKDF(master, salt, owner id), which keeps the v1 owner binding without
# paying 100k PBKDF2 iterations on every token read in the worker. The owner
# id is also the GCM associated data, so a blob copied onto another user's
# row does not decrypt. ``key_id`` names the master key, so a blob written
# under ENCRYPTION_SECRET_KEY_PREVIOUS is still readable during a rotation.

_V2_PREFIX = "v2"
_V2_MASTER_SALT = b"docsgpt-credentials-v2"
_V2_ITERATIONS = 200_000
_V2_SALT_BYTES = 16
_V2_NONCE_BYTES = 12
DEFAULT_ENCRYPTION_KEY = "default-docsgpt-encryption-key"


class CredentialDecryptionError(Exception):
    """A stored credential could not be decrypted (wrong key, tampering, bad format)."""


@functools.lru_cache(maxsize=8)
def _master_key(secret: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_V2_MASTER_SALT,
        iterations=_V2_ITERATIONS,
        backend=default_backend(),
    )
    return kdf.derive(secret.encode())


def _key_id(master: bytes) -> str:
    return hmac.new(master, b"docsgpt-key-id", hashlib.sha256).hexdigest()[:8]


def _record_key(master: bytes, owner_id: str, salt: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"docsgpt-v2|" + owner_id.encode(),
        backend=default_backend(),
    ).derive(master)


def _candidate_keys() -> dict[str, bytes]:
    """Master keys this process can decrypt with, by key id (current first)."""
    keys: dict[str, bytes] = {}
    for secret in (settings.ENCRYPTION_SECRET_KEY, settings.ENCRYPTION_SECRET_KEY_PREVIOUS):
        if secret:
            master = _master_key(secret)
            keys.setdefault(_key_id(master), master)
    return keys


def current_key_id() -> str:
    """Key id of ENCRYPTION_SECRET_KEY, as written into new v2 blobs."""
    return _key_id(_master_key(settings.ENCRYPTION_SECRET_KEY))


def is_default_encryption_key() -> bool:
    """Whether ENCRYPTION_SECRET_KEY is still the public default."""
    return settings.ENCRYPTION_SECRET_KEY == DEFAULT_ENCRYPTION_KEY


def encrypt_json(data: dict, owner_id: str) -> str:
    """Encrypt ``data`` for ``owner_id`` into a v2 envelope.

    Args:
        data: JSON-serialisable credentials.
        owner_id: The user the credentials belong to; decryption needs it.

    Returns:
        The ``v2:<key_id>:<payload>`` string.
    """
    master = _master_key(settings.ENCRYPTION_SECRET_KEY)
    key_id = _key_id(master)
    salt = os.urandom(_V2_SALT_BYTES)
    nonce = os.urandom(_V2_NONCE_BYTES)
    key = _record_key(master, owner_id, salt)
    plaintext = json.dumps(data, separators=(",", ":")).encode()
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, owner_id.encode())
    payload = base64.b64encode(salt + nonce + ciphertext).decode()
    return f"{_V2_PREFIX}:{key_id}:{payload}"


def envelope_key_id(blob: str) -> Optional[str]:
    """The key id a v2 blob was written with, or None for anything else."""
    parts = (blob or "").split(":", 2)
    if len(parts) != 3 or parts[0] != _V2_PREFIX:
        return None
    return parts[1]


def decrypt_json(blob: str, owner_id: str) -> dict:
    """Decrypt a v2 envelope written for ``owner_id``.

    Raises:
        CredentialDecryptionError: The blob is malformed, was written with a
            key this process does not have, belongs to another owner, or was
            tampered with.
    """
    key_id = envelope_key_id(blob)
    if key_id is None:
        raise CredentialDecryptionError("Not a v2 credential envelope")
    master = _candidate_keys().get(key_id)
    if master is None:
        raise CredentialDecryptionError("Credential was encrypted with an unknown key")
    try:
        raw = base64.b64decode(blob.split(":", 2)[2].encode(), validate=True)
        salt = raw[:_V2_SALT_BYTES]
        nonce = raw[_V2_SALT_BYTES:_V2_SALT_BYTES + _V2_NONCE_BYTES]
        ciphertext = raw[_V2_SALT_BYTES + _V2_NONCE_BYTES:]
        key = _record_key(master, owner_id, salt)
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, owner_id.encode())
        data = json.loads(plaintext.decode())
    except Exception as exc:
        raise CredentialDecryptionError("Credential could not be decrypted") from exc
    if not isinstance(data, dict):
        raise CredentialDecryptionError("Credential payload is not an object")
    return data
