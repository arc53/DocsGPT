"""Repository for the ``user_custom_models`` table.

Backs the end-user "Bring Your Own Model" feature. Each row is one
user-supplied OpenAI-compatible endpoint (Mistral, Together, vLLM, ...).
The ``id`` UUID is the internal DocsGPT identifier (what agents store
in ``default_model_id``); ``upstream_model_id`` is what we send verbatim
to the provider's API.

API key handling: callers pass plaintext via ``api_key_plaintext``;
this module wraps the existing ``application.security.encryption``
helper (AES-CBC + per-user PBKDF2 salt) and writes the base64 ciphertext
to the ``api_key_encrypted`` column. Decryption is the caller's
responsibility (they hold the ``user_id``).
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Connection, func, text

from application.security.encryption import (
    decrypt_credentials,
    encrypt_credentials,
)
from application.storage.db.base_repository import row_to_dict
from application.storage.db.models import user_custom_models_table


_ALLOWED_CAPABILITY_KEYS = frozenset(
    {
        "supports_tools",
        "supports_structured_output",
        "supports_streaming",
        "attachments",
        "context_window",
    }
)


class UserCustomModelsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------ #
    # Encryption wrappers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _encrypt_api_key(api_key_plaintext: str, user_id: str) -> str:
        """Encrypt ``api_key_plaintext`` with the per-user PBKDF2 scheme."""
        return encrypt_credentials({"api_key": api_key_plaintext}, user_id)

    @staticmethod
    def _decrypt_api_key(api_key_encrypted: str, user_id: str) -> Optional[str]:
        """Decrypt the API key. Returns None on failure (which the caller
        should surface as a configuration error rather than silently
        proceeding with the upstream call)."""
        if not api_key_encrypted:
            return None
        creds = decrypt_credentials(api_key_encrypted, user_id)
        return creds.get("api_key") if creds else None

    @staticmethod
    def _normalize_capabilities(caps: Optional[dict]) -> dict:
        """Drop unknown keys; nothing else is forced. Callers (the route
        layer) are responsible for value validation (numeric ranges,
        attachment alias resolution)."""
        if not caps:
            return {}
        return {k: v for k, v in caps.items() if k in _ALLOWED_CAPABILITY_KEYS}

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #

    def create(
        self,
        user_id: str,
        upstream_model_id: str,
        display_name: str,
        base_url: str,
        api_key_plaintext: str,
        description: str = "",
        capabilities: Optional[dict] = None,
        enabled: bool = True,
    ) -> dict:
        values = {
            "user_id": user_id,
            "upstream_model_id": upstream_model_id,
            "display_name": display_name,
            "description": description or "",
            "base_url": base_url,
            "api_key_encrypted": self._encrypt_api_key(api_key_plaintext, user_id),
            "capabilities": self._normalize_capabilities(capabilities),
            "enabled": bool(enabled),
        }
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(user_custom_models_table)
            .values(**values)
            .returning(user_custom_models_table)
        )
        result = self._conn.execute(stmt)
        return row_to_dict(result.fetchone())

    def get(self, model_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM user_custom_models "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": str(model_id), "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM user_custom_models "
                "WHERE user_id = :user_id ORDER BY created_at DESC"
            ),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def update(self, model_id: str, user_id: str, fields: dict) -> bool:
        """Apply a partial update.

        Special-cases ``api_key_plaintext``: when present, it is encrypted
        and stored in ``api_key_encrypted``. When absent (or empty), the
        existing ciphertext is kept untouched. This is the wire-shape
        ``PATCH`` expects (the UI sends a blank password field when the
        operator wants to keep the existing key).
        """
        allowed = {
            "upstream_model_id",
            "display_name",
            "description",
            "base_url",
            "capabilities",
            "enabled",
        }
        values: dict[str, Any] = {}
        for col, val in fields.items():
            if col not in allowed or val is None:
                continue
            if col == "capabilities":
                values[col] = self._normalize_capabilities(val)
            elif col == "enabled":
                values[col] = bool(val)
            else:
                values[col] = val

        api_key_plaintext = fields.get("api_key_plaintext")
        if api_key_plaintext:
            values["api_key_encrypted"] = self._encrypt_api_key(
                api_key_plaintext, user_id
            )

        if not values:
            return False
        values["updated_at"] = func.now()

        t = user_custom_models_table
        stmt = (
            t.update()
            .where(t.c.id == str(model_id))
            .where(t.c.user_id == user_id)
            .values(**values)
        )
        result = self._conn.execute(stmt)
        return result.rowcount > 0

    def delete(self, model_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text(
                "DELETE FROM user_custom_models "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": str(model_id), "user_id": user_id},
        )
        return result.rowcount > 0

    # ------------------------------------------------------------------ #
    # Decryption helpers exposed to the registry layer
    # ------------------------------------------------------------------ #

    def get_decrypted_api_key(
        self, model_id: str, user_id: str
    ) -> Optional[str]:
        """Convenience: fetch the row and return the decrypted API key,
        or ``None`` if the row is missing or decryption fails."""
        row = self.get(model_id, user_id)
        if row is None:
            return None
        return self._decrypt_api_key(row.get("api_key_encrypted", ""), user_id)
