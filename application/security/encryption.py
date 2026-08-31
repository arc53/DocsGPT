import base64
import json
import logging
import os
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from application.core.settings import settings

logger = logging.getLogger(__name__)

NONCE_SIZE_BYTES = 12
SALT_SIZE_BYTES = 16
TAG_SIZE_BYTES = 16


def _derive_key(user_id: str, salt: bytes) -> bytes:
    """Derives an AES-256 key from app secret and user_id using PBKDF2.

    Args:
        user_id: Unique user identifier for per-user key diversification.
        salt: Cryptographic random salt.

    Returns:
        Derived 32-byte key.
    """
    app_secret = settings.ENCRYPTION_SECRET_KEY

    password = f"{app_secret}#{user_id}".encode()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend(),
    )

    return kdf.derive(password)


def encrypt_credentials(credentials: dict[str, Any], user_id: str) -> str:
    """Encrypts credentials dictionary using authenticated AES-256-GCM.

    Args:
        credentials: Dictionary containing sensitive credential values.
        user_id: User identifier for key derivation.

    Returns:
        Base64-encoded encrypted payload containing salt, nonce, ciphertext, and tag.
    """
    if not credentials:
        return ""
    try:
        salt = os.urandom(SALT_SIZE_BYTES)
        nonce = os.urandom(NONCE_SIZE_BYTES)
        key = _derive_key(user_id, salt)

        json_bytes = json.dumps(credentials).encode("utf-8")

        aesgcm = AESGCM(key)
        encrypted_payload = aesgcm.encrypt(nonce, json_bytes, None)

        result = salt + nonce + encrypted_payload
        return base64.b64encode(result).decode("utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to encrypt credentials: {e}")
        return ""


def decrypt_credentials(encrypted_data: str, user_id: str) -> dict[str, Any]:
    """Decrypts base64 payload and verifies data integrity using AES-256-GCM.

    Args:
        encrypted_data: Base64-encoded ciphertext payload.
        user_id: User identifier for key derivation.

    Returns:
        Decrypted credentials dictionary, or empty dict if decryption or authentication fails.
    """
    if not encrypted_data:
        return {}
    try:
        data = base64.b64decode(encrypted_data.encode("utf-8"))

        min_length = SALT_SIZE_BYTES + NONCE_SIZE_BYTES + TAG_SIZE_BYTES
        if len(data) < min_length:
            return {}

        salt = data[:SALT_SIZE_BYTES]
        nonce = data[SALT_SIZE_BYTES : SALT_SIZE_BYTES + NONCE_SIZE_BYTES]
        encrypted_payload = data[SALT_SIZE_BYTES + NONCE_SIZE_BYTES :]

        key = _derive_key(user_id, salt)

        aesgcm = AESGCM(key)
        decrypted_bytes = aesgcm.decrypt(nonce, encrypted_payload, None)

        return json.loads(decrypted_bytes.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to decrypt credentials: {e}")
        return {}
