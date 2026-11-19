"""Repository for the ``user_custom_models`` table.

Backs the end-user "Bring Your Own Model" feature. Each row is one
user-supplied OpenAI-compatible endpoint (Mistral, Together, vLLM, ...).
The ``id`` UUID is the internal DocsGPT identifier (what agents store
in ``default_model_id``); ``upstream_model_id`` is what we send verbatim
to the provider's API.

API key handling: callers pass plaintext via ``api_key_plaintext``;
this module wraps the existing ``docsgpt.security.encryption``
helper (AES-CBC + per-user PBKDF2 salt) and writes the base64 ciphertext
to the ``api_key_encrypted`` column. Decryption is the caller's
responsibility (they hold the ``user_id``).
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Connection, func, text

from docsgpt.security.encryption import (
    decrypt_credentials,
    encrypt_credentials,
)
from docsgpt.storage.db.base_repository import row_to_dict
from docsgpt.storage.db.models import user_custom_models_table


_ALLOWED_CAPABILITY_KEYS = frozenset(
    {
        "supports_tools",
        "supports_structured_output",
        "supports_streaming",
        "attachments",
        "context_window",
        "api_flavor",
        "reasoning_effort",
        "tool_result_images",
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
        created_by: Optional[str] = None,
    ) -> dict:
        """Insert a model; its key is sealed with ``user_id``, the owner (a person or a team's principal).

        Args:
            user_id: The owner.
            upstream_model_id: The id sent to the provider.
            display_name: The name shown in pickers.
            base_url: The OpenAI-compatible endpoint.
            api_key_plaintext: The provider key.
            description: Shown under the name.
            capabilities: What the model supports (unknown keys dropped).
            enabled: Whether pickers offer it.
            created_by: The person adding a team's model. Left None for a person's own, which the
                ``fill_created_by`` trigger sets to the owner.

        Returns:
            The new row.
        """
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
        if created_by:
            values["created_by"] = created_by
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

    def get_by_id(self, model_id: str) -> Optional[dict]:
        """One model by id, whoever owns it; callers authorize (``workspaces.team_models``).

        Args:
            model_id: The model's id; one that isn't a UUID finds nothing.

        Returns:
            The row, or None.
        """
        from docsgpt.storage.db.base_repository import looks_like_uuid

        if not model_id or not looks_like_uuid(str(model_id)):
            return None
        row = self._conn.execute(
            text("SELECT * FROM user_custom_models WHERE id = CAST(:id AS uuid)"), {"id": str(model_id)}
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def owned_ids(self, owner_id: str, model_ids: list[str]) -> list[str]:
        """Which of ``model_ids`` are custom models ``owner_id`` owns.

        Args:
            owner_id: A person or a team's principal.
            model_ids: Candidate ids; ones that aren't UUIDs are ignored.

        Returns:
            The ids (as given) that name a row of ``owner_id``.
        """
        from docsgpt.storage.db.base_repository import looks_like_uuid

        candidates = {str(m).lower(): str(m) for m in model_ids if m and looks_like_uuid(str(m))}
        if not candidates or not owner_id:
            return []
        rows = self._conn.execute(
            text(
                "SELECT id::text FROM user_custom_models "
                "WHERE id = ANY(CAST(:ids AS uuid[])) AND user_id = :owner"
            ),
            {"ids": sorted(candidates), "owner": owner_id},
        ).fetchall()
        found = {str(r[0]).lower() for r in rows}
        return [given for key, given in candidates.items() if key in found]

    def usage(self, owner_id: str, model_id: str) -> dict[str, list[dict]]:
        """The owner's agents and workflows that name a model, so a delete can say what falls back.

        An agent names it as its default or in its model list; a workflow in an agent node of its current
        graph. Only ``owner_id``'s items count: no one else's item can run on the model.

        Args:
            owner_id: The model's owner.
            model_id: The model's id.

        Returns:
            ``{"agents": [{id, name}], "workflows": [{id, name}]}``, each by name.
        """
        params = {"owner": owner_id, "m": str(model_id).lower()}
        agents = self._conn.execute(
            text(
                """
                SELECT a.id::text, a.name FROM agents a
                WHERE a.user_id = :owner AND (
                    lower(a.default_model_id) = :m
                    OR (jsonb_typeof(a.models) = 'array' AND EXISTS (
                        SELECT 1 FROM jsonb_array_elements_text(a.models) e WHERE lower(e) = :m))
                )
                ORDER BY a.name, a.id
                """
            ),
            params,
        ).fetchall()
        workflows = self._conn.execute(
            text(
                """
                SELECT w.id::text, w.name FROM workflows w
                WHERE w.user_id = :owner AND EXISTS (
                    SELECT 1 FROM workflow_nodes n
                    WHERE n.workflow_id = w.id AND n.graph_version = w.current_graph_version
                      AND n.node_type = 'agent'
                      AND lower(COALESCE(n.config -> 'config' ->> 'model_id', n.config ->> 'model_id')) = :m)
                ORDER BY w.name, w.id
                """
            ),
            params,
        ).fetchall()
        return {
            "agents": [{"id": r[0], "name": r[1]} for r in agents],
            "workflows": [{"id": r[0], "name": r[1]} for r in workflows],
        }

    def existing_ids(self, model_ids: list[str]) -> list[str]:
        """Which of ``model_ids`` are custom models of anyone.

        Args:
            model_ids: Candidate ids; ones that aren't UUIDs are ignored.

        Returns:
            The ids (as given) that name a ``user_custom_models`` row.
        """
        from docsgpt.storage.db.base_repository import looks_like_uuid

        candidates = {str(m).lower(): str(m) for m in model_ids if m and looks_like_uuid(str(m))}
        if not candidates:
            return []
        rows = self._conn.execute(
            text("SELECT id::text FROM user_custom_models WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": sorted(candidates)},
        ).fetchall()
        found = {str(r[0]).lower() for r in rows}
        return [given for key, given in candidates.items() if key in found]

    def added_by_counts(self, owner_id: str, user_ids: list[str]) -> dict[str, int]:
        """How many of an owner's custom models each person added (``created_by``).

        Args:
            owner_id: The owner, a team's principal.
            user_ids: The people to count for.

        Returns:
            ``{user_id: count}`` for every id given, 0 for those who added none.
        """
        ids = sorted({str(u) for u in user_ids if u})
        if not ids or not owner_id:
            return {}
        counts = dict.fromkeys(ids, 0)
        rows = self._conn.execute(
            text(
                "SELECT created_by, count(*) FROM user_custom_models "
                "WHERE user_id = :owner AND created_by = ANY(:ids) GROUP BY created_by"
            ),
            {"owner": owner_id, "ids": ids},
        ).fetchall()
        for user_id, count in rows:
            counts[user_id] = int(count)
        return counts

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
