import base64
import hashlib
import hmac
import json
import logging
import os

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import algorithms, Cipher, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from application.core.settings import settings

logger = logging.getLogger(__name__)

# Version tag prepended to newly-encrypted blobs.
# v1 blobs (no tag) remain decryptable for backward compatibility.
_V2_TAG = b"\x02"


def _derive_key(user_id: str, salt: bytes) -> bytes:
    """Derive a 32-byte AES key (v1 legacy path)."""
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


def _derive_keys(user_id: str, salt: bytes) -> tuple:
    """Derive separate 32-byte AES and HMAC keys (v2 path)."""
    app_secret = settings.ENCRYPTION_SECRET_KEY
    password = f"{app_secret}#{user_id}".encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=64,
        salt=salt,
        iterations=100000,
        backend=default_backend(),
    )
    material = kdf.derive(password)
    return material[:32], material[32:]


def encrypt_credentials(credentials: dict, user_id: str) -> str:
    if not credentials:
        return ""
    try:
        salt = os.urandom(16)
        iv = os.urandom(16)
        enc_key, mac_key = _derive_keys(user_id, salt)

        json_str = json.dumps(credentials)
        cipher = Cipher(algorithms.AES(enc_key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        padded_data = _pad_data(json_str.encode())
        encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

        mac_input = salt + iv + encrypted_data
        tag = hmac.new(mac_key, mac_input, digestmod=hashlib.sha256).digest()

        result = _V2_TAG + salt + iv + tag + encrypted_data
        return base64.b64encode(result).decode()
    except Exception as e:
        logger.warning(f"Failed to encrypt credentials: {e}")
        return ""


def decrypt_credentials(encrypted_data: str, user_id: str) -> dict:
    if not encrypted_data:
        return {}
    try:
        data = base64.b64decode(encrypted_data.encode())
        if data[:1] == _V2_TAG:
            return _decrypt_v2(data[1:], user_id)
        return _decrypt_v1(data, user_id)
    except Exception as e:
        logger.warning(f"Failed to decrypt credentials: {e}")
        return {}


def _decrypt_v2(data: bytes, user_id: str) -> dict:
    """Decrypt a v2 blob (AES-CBC + HMAC-SHA256)."""
    salt = data[:16]
    iv = data[16:32]
    stored_tag = data[32:64]
    encrypted_content = data[64:]

    enc_key, mac_key = _derive_keys(user_id, salt)

    expected_tag = hmac.new(
        mac_key, salt + iv + encrypted_content, digestmod=hashlib.sha256
    ).digest()
    if not hmac.compare_digest(stored_tag, expected_tag):
        raise ValueError("HMAC verification failed: credential data may be tampered")

    cipher = Cipher(algorithms.AES(enc_key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(encrypted_content) + decryptor.finalize()
    return json.loads(_unpad_data(decrypted_padded).decode())


def _decrypt_v1(data: bytes, user_id: str) -> dict:
    """Decrypt a legacy v1 blob (AES-CBC, no HMAC)."""
    salt = data[:16]
    iv = data[16:32]
    encrypted_content = data[32:]

    key = _derive_key(user_id, salt)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(encrypted_content) + decryptor.finalize()
    return json.loads(_unpad_data(decrypted_padded).decode())


def _pad_data(data: bytes) -> bytes:
    block_size = 16
    padding_len = block_size - (len(data) % block_size)
    padding = bytes([padding_len]) * padding_len
    return data + padding


def _unpad_data(data: bytes) -> bytes:
    padding_len = data[-1]
    return data[:-padding_len]
