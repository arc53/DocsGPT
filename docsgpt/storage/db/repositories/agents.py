"""Repository for the ``agents`` table.

Covers every write operation the legacy Mongo code performs on ``agents_collection``:

- create, update, delete
- find by key (API key lookup)
- find by webhook token
- list for user, list templates
- folder assignment

The ``creative`` and ``strict`` prompt presets have no ``prompts`` row, so
``prompt_id`` (a foreign key) can't hold them: they are stored in
``prompt_preset``. Callers never see that column. Writes take the preset name
as ``prompt_id``, and every read returns it as ``prompt_id``; a raw ``SELECT``
elsewhere goes through :func:`agent_row_to_dict` to read it the same way.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Connection, cast, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict
from docsgpt.storage.db.models import agents_table

#: The prompt presets an agent stores in ``prompt_preset``. ``default`` is
#: stored as NULL in both prompt columns.
STORED_PROMPT_PRESETS = ("creative", "strict")


def split_prompt_ref(value: Any) -> tuple[Optional[str], Optional[str]]:
    """The ``(prompt_id, prompt_preset)`` columns for an agent's prompt.

    Args:
        value: A preset name, a prompt's id, or None/``""``/``default``.

    Returns:
        tuple: ``(None, None)`` for the default, ``(None, name)`` for a stored
        preset, else ``(id, None)``.
    """
    if value is None or value == "" or value == "default":
        return None, None
    ref = str(value)
    if ref in STORED_PROMPT_PRESETS:
        return None, ref
    return ref, None


def is_agent_prompt_ref(value: Any) -> bool:
    """Whether an agent can store ``value`` as its prompt.

    Args:
        value: The requested ``prompt_id``.

    Returns:
        bool: True for the default (None, ``""``, ``default``), a stored
        preset, or a UUID.
    """
    if value is None or value == "" or value == "default":
        return True
    return str(value) in STORED_PROMPT_PRESETS or looks_like_uuid(str(value))


def expose_prompt_preset(agent: dict) -> dict:
    """Fold ``prompt_preset`` into ``prompt_id`` on an agent dict, in place.

    Args:
        agent: An ``agents`` row as a dict.

    Returns:
        dict: The same dict, without ``prompt_preset``.
    """
    preset = agent.pop("prompt_preset", None)
    if preset and not agent.get("prompt_id"):
        agent["prompt_id"] = preset
    return agent


def agent_row_to_dict(row: Any) -> Optional[dict]:
    """An ``agents`` row from a raw ``SELECT`` as the repository returns it.

    Args:
        row: A SQLAlchemy row of the ``agents`` table, or None.

    Returns:
        dict | None: The row with its preset read as ``prompt_id``, or None.
    """
    if row is None:
        return None
    return expose_prompt_preset(row_to_dict(row))


class AgentsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    @staticmethod
    def _normalize_unique_text(col: str, val):
        """Coerce blank strings for nullable unique text columns to NULL."""
        if col in ("key", "slug") and val == "":
            return None
        return val

    def create(self, user_id: str, name: str, status: str, **kwargs) -> dict:
        values: dict = {"user_id": user_id, "name": name, "status": status}

        _ALLOWED = {
            "description", "agent_type", "key", "slug", "retriever",
            "default_model_id", "incoming_webhook_token",
            "source_id", "prompt_id", "folder_id", "workflow_id",
            "extra_source_ids", "image",
            "chunks", "token_limit", "request_limit",
            "limited_token_mode", "limited_request_mode",
            "allow_system_prompt_override",
            "shared", "shared_token", "shared_metadata",
            "tools", "json_schema", "models", "config", "resource_sponsors", "legacy_mongo_id",
            "created_at", "updated_at", "last_used_at",
        }

        for col, val in kwargs.items():
            if col not in _ALLOWED or val is None:
                continue
            if col == "prompt_id":
                prompt_id, prompt_preset = split_prompt_ref(val)
                if prompt_id is not None:
                    values["prompt_id"] = prompt_id
                if prompt_preset is not None:
                    values["prompt_preset"] = prompt_preset
                continue
            if col in ("tools", "json_schema", "models", "shared_metadata", "config", "resource_sponsors"):
                # JSONB columns: pass the Python object directly. SQLAlchemy
                # Core's JSONB type processor json.dumps it once during
                # bind; pre-serialising would double-encode and the value
                # would round-trip as a JSON string instead of the dict.
                values[col] = val
            elif col in ("chunks", "token_limit", "request_limit"):
                values[col] = int(val)
            elif col in (
                "limited_token_mode", "limited_request_mode",
                "shared", "allow_system_prompt_override",
            ):
                values[col] = bool(val)
            elif col in ("source_id", "folder_id", "workflow_id"):
                values[col] = str(val)
            elif col == "extra_source_ids":
                # ARRAY(UUID) — pass list of strings; psycopg adapts it.
                values[col] = [str(x) for x in val] if val else []
            else:
                values[col] = self._normalize_unique_text(col, val)

        stmt = pg_insert(agents_table).values(**values).returning(agents_table)
        result = self._conn.execute(stmt)
        return agent_row_to_dict(result.fetchone())

    def get(self, agent_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": agent_id, "user_id": user_id},
        )
        row = result.fetchone()
        return agent_row_to_dict(row)

    def get_any(self, agent_id: str, user_id: str) -> Optional[dict]:
        """Resolve an agent by either PG UUID or legacy Mongo ObjectId string.

        Cutover helper: URLs / bookmarks / old client state may still hold
        Mongo ObjectId-strings. Try the UUID path first (the post-cutover
        shape) and fall back to ``legacy_mongo_id`` — both are scoped by
        ``user_id`` so cross-user access is impossible.
        """
        if looks_like_uuid(agent_id):
            row = self.get(agent_id, user_id)
            if row is not None:
                return row
        return self.get_by_legacy_id(agent_id, user_id)

    def get_by_legacy_id(self, legacy_mongo_id: str, user_id: str | None = None) -> Optional[dict]:
        """Fetch an agent by the original Mongo ObjectId string."""
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        sql = "SELECT * FROM agents WHERE legacy_mongo_id = :legacy_id"
        params: dict[str, str] = {"legacy_id": legacy_mongo_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        result = self._conn.execute(text(sql), params)
        row = result.fetchone()
        return agent_row_to_dict(row)

    def find_by_key(self, key: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE key = :key"),
            {"key": key},
        )
        row = result.fetchone()
        return agent_row_to_dict(row)

    def find_by_shared_token(self, token: str) -> Optional[dict]:
        """Resolve a publicly-shared agent by its rotating share token.

        Only returns rows with ``shared = true`` so revoking a share
        (setting ``shared = false``) immediately stops token access even
        if the token value itself is still in the row.
        """
        result = self._conn.execute(
            text(
                "SELECT * FROM agents "
                "WHERE shared_token = :token AND shared = true"
            ),
            {"token": token},
        )
        row = result.fetchone()
        return agent_row_to_dict(row)

    def find_by_webhook_token(self, token: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE incoming_webhook_token = :token"),
            {"token": token},
        )
        row = result.fetchone()
        return agent_row_to_dict(row)

    def find_by_slug(self, user_id: str, slug: str) -> Optional[dict]:
        """Resolve one of a user's agents by its stable export/import slug."""
        if not slug:
            return None
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE user_id = :user_id AND slug = :slug"),
            {"user_id": user_id, "slug": slug},
        )
        row = result.fetchone()
        return agent_row_to_dict(row)

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE user_id = :user_id ORDER BY created_at DESC"),
            {"user_id": user_id},
        )
        return [agent_row_to_dict(r) for r in result.fetchall()]

    def count_by_workflow(self, workflow_id: str, user_id: str) -> int:
        """Number of this user's agents linked to ``workflow_id``."""
        if not looks_like_uuid(workflow_id):
            return 0
        result = self._conn.execute(
            text(
                "SELECT COUNT(*) FROM agents "
                "WHERE workflow_id = CAST(:wf AS uuid) AND user_id = :user_id"
            ),
            {"wf": workflow_id, "user_id": user_id},
        )
        return int(result.scalar() or 0)

    def get_by_id(self, agent_id: str) -> Optional[dict]:
        """Fetch an agent by id with NO ownership scoping.

        Used ONLY after a team-grant authorization check has already confirmed
        the caller may see this agent (see team sharing). Never call this on a
        raw user-supplied id without that check — it bypasses the dual-key guard.
        """
        if not looks_like_uuid(agent_id):
            return None
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE id = CAST(:id AS uuid)"),
            {"id": agent_id},
        )
        row = result.fetchone()
        return agent_row_to_dict(row)

    def find_image_record(self, agent_id: str) -> Optional[dict]:
        """Fetch only the fields needed to verify a public image capability.

        This lookup is intentionally not owner-scoped because the resulting
        row is not authorization: callers must verify its HMAC capability
        before reading or returning any storage bytes.
        """
        if not looks_like_uuid(agent_id):
            return None
        result = self._conn.execute(
            text(
                "SELECT id, user_id, image FROM agents "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": agent_id},
        )
        row = result.fetchone()
        return agent_row_to_dict(row)

    def list_by_ids(self, agent_ids) -> list[dict]:
        """Fetch agents whose id is in ``agent_ids`` (team-shared listing path)."""
        ids = [str(a) for a in agent_ids if looks_like_uuid(str(a))]
        if not ids:
            return []
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY created_at DESC"),
            {"ids": ids},
        )
        return [agent_row_to_dict(r) for r in result.fetchall()]

    def update_by_id(
        self, agent_id: str, fields: dict, expected_updated_at=None
    ) -> Optional[bool]:
        """Update an agent by id WITHOUT user scoping (team ``editor`` write path).

        The caller MUST have verified the principal holds an ``editor`` grant
        before calling. When ``expected_updated_at`` is given, the update is
        applied only if the row's ``updated_at`` still matches (optimistic lock);
        returns None on a version mismatch so the route can answer 409.
        """
        # Reuse the owner-path column allowlist + coercion by delegating, but
        # against the id-only predicate. We rebuild the same filtered values.
        allowed = {
            "name", "description", "agent_type", "status", "key", "slug", "source_id",
            "chunks", "retriever", "prompt_id", "tools", "json_schema", "models",
            "config", "resource_sponsors",
            "default_model_id", "folder_id", "workflow_id",
            "extra_source_ids", "image",
            "limited_token_mode", "token_limit",
            "limited_request_mode", "request_limit",
            "allow_system_prompt_override",
            "shared", "shared_token", "shared_metadata",
            "incoming_webhook_token", "last_used_at",
        }
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return False
        values: dict = {}
        for col, val in filtered.items():
            if col in ("tools", "json_schema", "models", "shared_metadata", "config", "resource_sponsors"):
                values[col] = val
            elif col == "prompt_id":
                values["prompt_id"], values["prompt_preset"] = split_prompt_ref(val)
            elif col in ("source_id", "folder_id", "workflow_id"):
                values[col] = str(val) if val else None
            elif col == "extra_source_ids":
                values[col] = [str(x) for x in val] if val else []
            elif col in (
                "limited_token_mode", "limited_request_mode",
                "shared", "allow_system_prompt_override",
            ):
                values[col] = bool(val)
            else:
                values[col] = self._normalize_unique_text(col, val)
        values["updated_at"] = func.now()

        t = agents_table
        stmt = t.update().where(t.c.id == agent_id)
        if expected_updated_at is not None:
            # Cast the (string/datetime) bind to timestamptz so PG compares the
            # optimistic-lock token against the column type, not text.
            stmt = stmt.where(t.c.updated_at == cast(expected_updated_at, t.c.updated_at.type))
        stmt = stmt.values(**values)
        result = self._conn.execute(stmt)
        if result.rowcount > 0:
            return True
        # Distinguish a stale optimistic-lock write (row exists) from a missing row.
        if expected_updated_at is not None and self.get_by_id(str(agent_id)) is not None:
            return None
        return False

    def list_templates(self) -> list[dict]:
        # Template/system agents are seeded under ``__system__`` (migration
        # 0001 + the seeder); the legacy ``'system'`` value is kept in the
        # match so older rows still surface.
        result = self._conn.execute(
            text(
                "SELECT * FROM agents WHERE user_id IN ('system', '__system__') "
                "ORDER BY name"
            ),
        )
        return [agent_row_to_dict(r) for r in result.fetchall()]

    def update(self, agent_id: str, user_id: str, fields: dict) -> bool:
        allowed = {
            "name", "description", "agent_type", "status", "key", "slug", "source_id",
            "chunks", "retriever", "prompt_id", "tools", "json_schema", "models",
            "config", "resource_sponsors",
            "default_model_id", "folder_id", "workflow_id",
            "extra_source_ids", "image",
            "limited_token_mode", "token_limit",
            "limited_request_mode", "request_limit",
            "allow_system_prompt_override",
            "shared", "shared_token", "shared_metadata",
            "incoming_webhook_token", "last_used_at",
        }
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return False

        values: dict = {}
        for col, val in filtered.items():
            if col in ("tools", "json_schema", "models", "shared_metadata", "config", "resource_sponsors"):
                # See note in create(): JSONB columns receive Python
                # objects, the type processor handles serialisation.
                values[col] = val
            elif col == "prompt_id":
                values["prompt_id"], values["prompt_preset"] = split_prompt_ref(val)
            elif col in ("source_id", "folder_id", "workflow_id"):
                values[col] = str(val) if val else None
            elif col == "extra_source_ids":
                values[col] = [str(x) for x in val] if val else []
            elif col in (
                "limited_token_mode", "limited_request_mode",
                "shared", "allow_system_prompt_override",
            ):
                values[col] = bool(val)
            else:
                values[col] = self._normalize_unique_text(col, val)
        values["updated_at"] = func.now()

        t = agents_table
        stmt = (
            t.update()
            .where(t.c.id == agent_id)
            .where(t.c.user_id == user_id)
            .values(**values)
        )
        result = self._conn.execute(stmt)
        return result.rowcount > 0

    def update_by_legacy_id(self, legacy_mongo_id: str, user_id: str, fields: dict) -> bool:
        """Update an agent addressed by the Mongo ObjectId string."""
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        agent = self.get_by_legacy_id(legacy_mongo_id, user_id)
        if agent is None:
            return False
        return self.update(agent["id"], user_id, fields)

    def delete(self, agent_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text("DELETE FROM agents WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": agent_id, "user_id": user_id},
        )
        return result.rowcount > 0

    def delete_by_legacy_id(self, legacy_mongo_id: str, user_id: str) -> bool:
        """Delete an agent addressed by the Mongo ObjectId string."""
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        result = self._conn.execute(
            text(
                "DELETE FROM agents "
                "WHERE legacy_mongo_id = :legacy_id AND user_id = :user_id"
            ),
            {"legacy_id": legacy_mongo_id, "user_id": user_id},
        )
        return result.rowcount > 0

    def set_folder(self, agent_id: str, user_id: str, folder_id: Optional[str]) -> None:
        self._conn.execute(
            text(
                """
                UPDATE agents SET folder_id = CAST(:folder_id AS uuid), updated_at = now()
                WHERE id = CAST(:id AS uuid) AND user_id = :user_id
                """
            ),
            {"id": agent_id, "user_id": user_id, "folder_id": folder_id},
        )

    def clear_folder_for_all(self, folder_id: str, user_id: str) -> None:
        """Remove folder assignment from all agents in a folder (used on folder delete)."""
        self._conn.execute(
            text(
                "UPDATE agents SET folder_id = NULL, updated_at = now() "
                "WHERE folder_id = CAST(:folder_id AS uuid) AND user_id = :user_id"
            ),
            {"folder_id": folder_id, "user_id": user_id},
        )
