"""
Simple encryption utility for securely storing sensitive credentials.
Uses XOR encryption with a key derived from app secret and user ID.
Note: This is basic obfuscation. For production, consider using cryptography library.
"""

import base64
import hashlib
import os
import json


def _get_encryption_key(user_id: str) -> bytes:
    """
    Generate a consistent encryption key for a specific user.
    Uses app secret + user ID to create a unique key per user.
    """
    # Get app secret from environment or use a default (in production, always use env)
    app_secret = os.environ.get(
        "APP_SECRET_KEY", "default-docsgpt-secret-key-change-in-production"
    )

    # Combine app secret with user ID for user-specific encryption
    combined = f"{app_secret}#{user_id}"

    # Create a 32-byte key
    key_material = hashlib.sha256(combined.encode()).digest()

    return key_material


def _xor_encrypt_decrypt(data: bytes, key: bytes) -> bytes:
    """Simple XOR encryption/decryption."""
    result = bytearray()
    for i, byte in enumerate(data):
        result.append(byte ^ key[i % len(key)])
    return bytes(result)


def encrypt_credentials(credentials: dict, user_id: str) -> str:
    """
    Encrypt credentials dictionary for secure storage.

    Args:
        credentials: Dictionary containing sensitive data
        user_id: User ID for creating user-specific encryption key

    Returns:
        Base64 encoded encrypted string
    """
    if not credentials:
        return ""

    try:
        key = _get_encryption_key(user_id)

        # Convert dict to JSON string and encrypt
        json_str = json.dumps(credentials)
        encrypted_data = _xor_encrypt_decrypt(json_str.encode(), key)

        # Return base64 encoded for storage
        return base64.b64encode(encrypted_data).decode()

    except Exception as e:
        # If encryption fails, store empty string (will require re-auth)
        print(f"Warning: Failed to encrypt credentials: {e}")
        return ""


def decrypt_credentials(encrypted_data: str, user_id: str) -> dict:
    """
    Decrypt credentials from storage.

    Args:
        encrypted_data: Base64 encoded encrypted string
        user_id: User ID for creating user-specific encryption key

    Returns:
        Dictionary containing decrypted credentials
    """
    if not encrypted_data:
        return {}

    try:
        key = _get_encryption_key(user_id)

        # Decode and decrypt
        encrypted_bytes = base64.b64decode(encrypted_data.encode())
        decrypted_data = _xor_encrypt_decrypt(encrypted_bytes, key)

        # Parse JSON back to dict
        return json.loads(decrypted_data.decode())

    except Exception as e:
        # If decryption fails, return empty dict (will require re-auth)
        print(f"Warning: Failed to decrypt credentials: {e}")
        return {}
