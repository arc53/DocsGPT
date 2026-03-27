import base64
import json
import os

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import algorithms, Cipher, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from application.core.settings import settings

_VERSION_GCM = b"\x01"


def _derive_key(user_id: str, salt: bytes) -> bytes:
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


def encrypt_credentials(credentials: dict, user_id: str) -> str:
    if not credentials:
        return ""
    try:
        salt = os.urandom(16)
        nonce = os.urandom(12)
        key = _derive_key(user_id, salt)

        json_bytes = json.dumps(credentials).encode()

        aesgcm = AESGCM(key)
        ciphertext_with_tag = aesgcm.encrypt(nonce, json_bytes, None)

        result = _VERSION_GCM + salt + nonce + ciphertext_with_tag
        return base64.b64encode(result).decode()
    except Exception as e:
        print(f"Warning: Failed to encrypt credentials: {e}")
        return ""


def decrypt_credentials(encrypted_data: str, user_id: str) -> dict:
    if not encrypted_data:
        return {}
    try:
        data = base64.b64decode(encrypted_data.encode())

        if data[0:1] == _VERSION_GCM:
            return _decrypt_gcm(data[1:], user_id)
        else:
            return _decrypt_legacy_cbc(data, user_id)
    except Exception as e:
        print(f"Warning: Failed to decrypt credentials: {e}")
        return {}


def _decrypt_gcm(data: bytes, user_id: str) -> dict:
    salt = data[:16]
    nonce = data[16:28]
    ciphertext_with_tag = data[28:]

    key = _derive_key(user_id, salt)

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, None)

    return json.loads(plaintext.decode())


def _decrypt_legacy_cbc(data: bytes, user_id: str) -> dict:
    """Decrypt data encrypted with the old AES-CBC format for backward compatibility."""
    salt = data[:16]
    iv = data[16:32]
    encrypted_content = data[32:]

    key = _derive_key(user_id, salt)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()

    decrypted_padded = decryptor.update(encrypted_content) + decryptor.finalize()
    decrypted_data = _unpad_data(decrypted_padded)

    return json.loads(decrypted_data.decode())


def _pad_data(data: bytes) -> bytes:
    block_size = 16
    padding_len = block_size - (len(data) % block_size)
    padding = bytes([padding_len]) * padding_len
    return data + padding


def _unpad_data(data: bytes) -> bytes:
    padding_len = data[-1]
    return data[:-padding_len]
