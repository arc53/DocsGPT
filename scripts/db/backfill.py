"""Backfill DocsGPT's Postgres user-data tables from MongoDB.

One script for every migrated collection. Adding a new collection is a
two-step change in this file:

1. Write a ``_backfill_<name>`` function that takes keyword args
   ``conn``, ``mongo_db``, ``batch_size``, ``dry_run`` and returns a
   stats ``dict``.
2. Add a single entry to :data:`BACKFILLERS`.

There are intentionally no per-collection CLI flags or environment
variables — ``USE_POSTGRES`` / ``READ_POSTGRES`` in ``.env`` are the
only knobs operators need. This script discovers what's available from
the :data:`BACKFILLERS` registry and runs whichever tables were asked for.

This script imports ``pymongo`` directly. ``pymongo`` is not part of the
base ``application/requirements.txt`` post-migration — install it
directly before running::

    pip install 'pymongo>=4.6'

Usage::

    python scripts/db/backfill.py                     # every registered table
    python scripts/db/backfill.py --tables users     # only specific tables
    python scripts/db/backfill.py --dry-run          # count without writing
    python scripts/db/backfill.py --batch 1000       # tune commit size

Exit codes:
    0 — every requested table completed successfully
    1 — misconfiguration (missing env var, unknown table name)
    2 — at least one table failed at runtime (others may still have succeeded)
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# Make the project root importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import Connection, text  # noqa: E402

from application.core.settings import settings  # noqa: E402
from application.storage.db.engine import get_engine  # noqa: E402


# The backfill tool is the one remaining consumer of MongoDB in this repo.
# It reads from Mongo and writes to Postgres, so it keeps its own client
# rather than going through the (now-deleted) ``application.core.mongo_db``
# wrapper. The DB name is hard-coded to ``docsgpt`` — historically surfaced
# as ``settings.MONGO_DB_NAME`` but that setting has been removed post-cutover.
_MONGO_DB_NAME = "docsgpt"

logger = logging.getLogger("backfill")


# ---------------------------------------------------------------------------
# Per-table backfillers
# ---------------------------------------------------------------------------


_WORKFLOW_RUN_STATUS_MAP: dict[str, str] = {
    "pending": "pending",
    "queued": "pending",
    "waiting": "pending",
    "running": "running",
    "in_progress": "running",
    "active": "running",
    "completed": "completed",
    "success": "completed",
    "done": "completed",
    "finished": "completed",
    "failed": "failed",
    "error": "failed",
    "failure": "failed",
    "aborted": "failed",
    "timeout": "failed",
    "cancelled": "failed",
}


def _coerce_workflow_run_status(raw: Any) -> str:
    """Map Mongo-era ``workflow_runs.status`` into the PG CHECK-allowed set.

    The Postgres ``workflow_runs`` table's CHECK constraint only accepts
    ``pending|running|completed|failed``. Legacy Mongo docs used a wider
    vocabulary. Unknown / unmappable values collapse to ``failed`` so a
    stray row never aborts the batch insert.
    """
    if raw is None:
        return "failed"
    key = str(raw).strip().lower()
    return _WORKFLOW_RUN_STATUS_MAP.get(key, "failed")


SYSTEM_USER_ID = "__system__"


def _normalize_system_user(raw_user: Any) -> str:
    """Coerce legacy "system" / missing / empty user values to the sentinel.

    Template rows created by the seeder (premade agents, sources,
    prompts) landed in Mongo with ``user="system"``. Older documents may
    have no ``user`` field or an empty string. Postgres enforces
    ``user_id TEXT NOT NULL`` and the cleanup triggers expect the
    sentinel ``__system__`` — unifying all three shapes here prevents
    mid-batch aborts and keeps template ownership predictable.
    """
    if raw_user is None:
        return SYSTEM_USER_ID
    text_value = str(raw_user)
    if text_value == "" or text_value == "system":
        return SYSTEM_USER_ID
    return text_value


def _ensure_system_user(conn: Connection) -> None:
    """Insert the ``__system__`` row in ``users`` if it doesn't already exist.

    Template rows all land with ``user_id = '__system__'``; without the
    row present, the UI's "who owns this?" joins show blank. Idempotent.
    """
    conn.execute(
        text(
            "INSERT INTO users (user_id) VALUES (:uid) "
            "ON CONFLICT (user_id) DO NOTHING"
        ),
        {"uid": SYSTEM_USER_ID},
    )


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_uuid_str(value: Any) -> bool:
    """Canonical UUID-string shape check (8-4-4-4-12 hex with dashes).

    Strict on purpose: any non-hex or mis-segmented string passed into a
    raw ``CAST(:x AS uuid)`` inside a backfill batch would raise
    ``invalid input syntax for type uuid`` and abort the whole batch,
    losing all other rows in the current commit window.
    """
    return isinstance(value, str) and bool(_UUID_RE.match(value))


def _is_object_id_str(value: str) -> bool:
    """24-char lowercase hex check — the shape of Mongo ObjectId strings."""
    if not isinstance(value, str) or len(value) != 24:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _extract_mongo_id_text(value: Any) -> str | None:
    """Return a Mongo ObjectId-like value as text across legacy shapes.

    Handles raw ObjectId values, DBRef-like objects exposing ``.id``, and
    dict encodings such as ``{"$id": {"$oid": "..."}}`` that show up in
    imported / normalised BSON payloads.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        if "$id" in value:
            return _extract_mongo_id_text(value["$id"])
        if "_id" in value:
            return _extract_mongo_id_text(value["_id"])
        if "$oid" in value:
            return str(value["$oid"])
        return None
    ref_id = getattr(value, "id", None)
    if ref_id is not None:
        return _extract_mongo_id_text(ref_id)
    return str(value)


def _coerce_document_timestamp(doc: dict[str, Any], *keys: str):
    """Return the first populated timestamp-like field from ``doc``.

    Mongo user data is not fully uniform across older deployments. Some
    records only carry ``created_at`` / ``updated_at`` and a few legacy
    documents have no explicit timestamp at all. In that final case we
    fall back to "now" so the backfill can preserve the row instead of
    failing a NOT NULL constraint.
    """
    for key in keys:
        value = doc.get(key)
        if value is not None:
            return value
    return datetime.now(timezone.utc)


def _backfill_users(
    *,
    conn: Connection,
    mongo_db: Any,
    batch_size: int,
    dry_run: bool,
) -> dict:
    """Sync the ``users`` table from Mongo ``users`` collection.

    Merges each Postgres row's ``agent_preferences`` with the Mongo state
    rather than overwriting: on a re-run after cutover, any keys the app
    has written to Postgres are preserved unless Mongo has a value for
    the same key (Mongo wins on collision, which is what we want during
    a re-backfill). Missing ``pinned`` / ``shared_with_me`` keys are
    filled with empty arrays so the Postgres row always has the full
    shape the application expects.

    Merge semantics: we use the PG ``||`` JSONB concatenation, which is a
    shallow top-level merge — nested objects are replaced, not deep-merged.
    """
    upsert_sql = text(
        """
        INSERT INTO users (user_id, agent_preferences)
        VALUES (:user_id, CAST(:prefs AS jsonb))
        ON CONFLICT (user_id) DO UPDATE
            SET agent_preferences = users.agent_preferences || EXCLUDED.agent_preferences,
                updated_at = now()
        """
    )

    cursor = (
        mongo_db["users"]
        .find({}, no_cursor_timeout=True)
        .batch_size(batch_size)
    )

    seen = 0
    written = 0
    skipped = 0
    batch: list[dict] = []

    try:
        for doc in cursor:
            seen += 1
            user_id = doc.get("user_id")
            if not user_id:
                skipped += 1
                continue

            raw_prefs = doc.get("agent_preferences") or {}
            # Start from the full Mongo doc so any historic/theme/settings
            # keys survive the backfill untouched, then normalise the two
            # known lists (pinned, shared_with_me). The agents read-path
            # cutover (_remediate_user_agent_prefs) handles ObjectId ↔ UUID
            # translation for those two fields.
            prefs = dict(raw_prefs) if isinstance(raw_prefs, dict) else {}
            prefs["pinned"] = list(raw_prefs.get("pinned") or [])
            prefs["shared_with_me"] = list(raw_prefs.get("shared_with_me") or [])
            batch.append({"user_id": user_id, "prefs": json.dumps(prefs, default=str)})

            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(upsert_sql, batch)
                written += len(batch)
                batch.clear()

        if batch:
            if not dry_run:
                conn.execute(upsert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()

    return {"seen": seen, "written": written, "skipped_no_user_id": skipped}


def _backfill_prompts(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    upsert_sql = text(
        """
        INSERT INTO prompts (user_id, name, content, legacy_mongo_id)
        VALUES (:user_id, :name, :content, :legacy_mongo_id)
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            name = EXCLUDED.name,
            content = EXCLUDED.content,
            updated_at = now()
        """
    )
    cursor = mongo_db["prompts"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            user_id = _normalize_system_user(doc.get("user"))
            batch.append({
                "user_id": user_id,
                "name": doc.get("name", ""),
                "content": doc.get("content", ""),
                "legacy_mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(upsert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(upsert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped_no_user": skipped}


def _backfill_user_tools(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    insert_sql = text(
        """
        INSERT INTO user_tools (
            user_id, name, custom_name, display_name, description,
            config, config_requirements, actions, status,
            created_at, updated_at, legacy_mongo_id
        )
        VALUES (
            :user_id, :name, :custom_name, :display_name, :description,
            CAST(:config AS jsonb),
            CAST(:config_requirements AS jsonb),
            CAST(:actions AS jsonb),
            :status,
            COALESCE(:created_at, now()),
            COALESCE(:updated_at, now()),
            :legacy_mongo_id
        )
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            name = EXCLUDED.name,
            custom_name = EXCLUDED.custom_name,
            display_name = EXCLUDED.display_name,
            description = EXCLUDED.description,
            config = EXCLUDED.config,
            config_requirements = EXCLUDED.config_requirements,
            actions = EXCLUDED.actions,
            status = EXCLUDED.status,
            updated_at = EXCLUDED.updated_at
        """
    )
    cursor = mongo_db["user_tools"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            user_id = _normalize_system_user(doc.get("user"))
            batch.append({
                "user_id": user_id,
                "name": doc.get("name", ""),
                "custom_name": doc.get("customName"),
                "display_name": doc.get("displayName"),
                "description": doc.get("description"),
                "config": json.dumps(doc.get("config") or {}, default=str),
                "config_requirements": json.dumps(doc.get("configRequirements") or {}, default=str),
                "actions": json.dumps(doc.get("actions") or [], default=str),
                "status": bool(doc.get("status", True)),
                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at"),
                "legacy_mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped_no_user": skipped}


def _backfill_stack_logs(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    insert_sql = text(
        """
        INSERT INTO stack_logs (activity_id, endpoint, level, user_id, api_key, query, stacks, timestamp, mongo_id)
        VALUES (:activity_id, :endpoint, :level, :user_id, :api_key, :query, CAST(:stacks AS jsonb), :timestamp, :mongo_id)
        ON CONFLICT (mongo_id) WHERE mongo_id IS NOT NULL DO NOTHING
        """
    )
    cursor = mongo_db["stack_logs"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            activity_id = doc.get("id")
            if not activity_id:
                skipped += 1
                continue
            batch.append({
                "activity_id": str(activity_id),
                "endpoint": doc.get("endpoint"),
                "level": doc.get("level"),
                "user_id": doc.get("user"),
                "api_key": doc.get("api_key"),
                "query": doc.get("query"),
                "stacks": json.dumps(doc.get("stacks") or [], default=str),
                "timestamp": doc.get("timestamp"),
                "mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped_no_id": skipped}


def _backfill_user_logs(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    insert_sql = text(
        """
        INSERT INTO user_logs (user_id, endpoint, data, timestamp, mongo_id)
        VALUES (:user_id, :endpoint, CAST(:data AS jsonb), :timestamp, :mongo_id)
        ON CONFLICT (mongo_id) WHERE mongo_id IS NOT NULL DO NOTHING
        """
    )
    cursor = mongo_db["user_logs"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            data_payload = {k: v for k, v in doc.items() if k != "_id"}
            for k, v in data_payload.items():
                if hasattr(v, "__str__") and type(v).__name__ == "ObjectId":
                    data_payload[k] = str(v)
            batch.append({
                "user_id": doc.get("user"),
                "endpoint": doc.get("action") or doc.get("endpoint"),
                "data": json.dumps(data_payload, default=str),
                "timestamp": doc.get("timestamp"),
                "mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written}


def _backfill_token_usage(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    insert_sql = text(
        """
        INSERT INTO token_usage (user_id, api_key, agent_id, prompt_tokens, generated_tokens, timestamp, mongo_id)
        VALUES (
            :user_id, :api_key,
            CAST(:agent_id AS uuid),
            :prompt_tokens, :generated_tokens, :timestamp, :mongo_id
        )
        ON CONFLICT (mongo_id) WHERE mongo_id IS NOT NULL DO NOTHING
        """
    )
    cursor = mongo_db["token_usage"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            agent_id = doc.get("agent_id")
            agent_id_str = None
            if agent_id:
                s = str(agent_id)
                if _is_uuid_str(s):
                    agent_id_str = s
            # Legacy Mongo docs: sometimes stored under ``user``, sometimes
            # ``user_id``. Normalise so the attribution CHECK doesn't reject
            # rows that actually have a user.
            user_id = doc.get("user_id") or doc.get("user")
            api_key = doc.get("api_key")
            # token_usage_attribution_chk requires at least one of
            # (user_id, api_key) to be non-null (agent_id alone is not
            # sufficient per the PG CHECK). Rows missing both carry no
            # usable attribution — skip them rather than fail the batch.
            if not user_id and not api_key:
                skipped += 1
                continue
            batch.append({
                "user_id": user_id,
                "api_key": api_key,
                "agent_id": agent_id_str,
                "prompt_tokens": doc.get("prompt_tokens", 0),
                "generated_tokens": doc.get("generated_tokens", 0),
                "timestamp": doc.get("timestamp"),
                "mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped": skipped}


# ---------------------------------------------------------------------------
# Phase 2 backfillers
# ---------------------------------------------------------------------------


def _backfill_agent_folders(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    """Backfill ``agent_folders`` in two passes.

    Folders are self-referential via ``parent_id``. Pass 1 inserts every
    folder with ``parent_id = NULL`` so legacy_mongo_ids are present in PG.
    Pass 2 issues ``UPDATE`` statements that resolve the Mongo parent
    ObjectId to the corresponding Postgres UUID via ``legacy_mongo_id``.
    """
    insert_sql = text(
        """
        INSERT INTO agent_folders (
            user_id, name, description, created_at, updated_at, legacy_mongo_id
        )
        VALUES (
            :user_id, :name, :description,
            COALESCE(:created_at, now()),
            COALESCE(:updated_at, now()),
            :legacy_mongo_id
        )
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            updated_at = EXCLUDED.updated_at
        """
    )
    update_parent_sql = text(
        """
        UPDATE agent_folders
        SET parent_id = CAST(:parent_pg_id AS uuid)
        WHERE legacy_mongo_id = :legacy_id AND user_id = :user_id
        """
    )

    # Pass 1 — insert all folders without resolving parent_id
    cursor = mongo_db["agent_folders"].find(
        {}, no_cursor_timeout=True,
    ).batch_size(batch_size)
    seen = written = skipped = 0
    parent_links: list[dict] = []
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            user_id = _normalize_system_user(doc.get("user"))
            legacy_id = str(doc["_id"])
            batch.append({
                "user_id": user_id,
                "name": doc.get("name", ""),
                "description": doc.get("description"),
                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at"),
                "legacy_mongo_id": legacy_id,
            })
            if doc.get("parent_id"):
                parent_links.append({
                    "user_id": user_id,
                    "legacy_id": legacy_id,
                    "parent_legacy_id": str(doc["parent_id"]),
                })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()

    # Pass 2 — resolve parent_id once every folder row has a legacy_mongo_id
    parent_links_resolved = 0
    if parent_links and not dry_run:
        folders_id_map = _build_legacy_id_map(conn, "agent_folders")
        update_batch: list[dict] = []
        for link in parent_links:
            parent_pg_id = folders_id_map.get(link["parent_legacy_id"])
            if not parent_pg_id:
                continue
            update_batch.append({
                "user_id": link["user_id"],
                "legacy_id": link["legacy_id"],
                "parent_pg_id": parent_pg_id,
            })
        if update_batch:
            conn.execute(update_parent_sql, update_batch)
            parent_links_resolved = len(update_batch)

    return {
        "seen": seen,
        "written": written,
        "skipped": skipped,
        "parent_links_resolved": parent_links_resolved,
    }


def _normalize_mongo_jsonb(value: Any) -> Optional[str]:
    """Serialize a Mongo field into a bind value for a Postgres JSONB column.

    Mongo docs store ``remote_data`` as either a dict or a JSON string, and
    may embed ``ObjectId`` values inside nested dicts. This helper returns a
    JSON string (or ``None``) suitable for ``CAST(:x AS jsonb)``.

    Seeder-created template sources store ``remote_data`` as a bare URL
    string (``"https://docs.docsgpt.cloud/"``). The connector-sync path
    expects a dict with ``provider``/``url`` keys, so URL-shaped strings
    are wrapped as ``{"provider": "crawler", "url": <s>}`` instead of
    the lossless-but-unusable ``{"raw": <s>}`` fallback.
    """
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.startswith("http://") or stripped.startswith("https://"):
            return json.dumps({"provider": "crawler", "url": stripped})
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return json.dumps({"raw": value})
        return json.dumps(parsed, default=str)
    return json.dumps(value, default=str)


def _backfill_sources(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    insert_sql = text(
        """
        INSERT INTO sources (
            user_id, name, type, metadata,
            retriever, sync_frequency, tokens, file_path,
            remote_data, directory_structure, file_name_map,
            language, model, date, created_at, updated_at, legacy_mongo_id
        )
        VALUES (
            :user_id, :name, :type, CAST(:metadata AS jsonb),
            :retriever, :sync_frequency, :tokens, :file_path,
            CAST(:remote_data AS jsonb),
            CAST(:directory_structure AS jsonb),
            CAST(:file_name_map AS jsonb),
            :language, :model,
            COALESCE(:date, now()),
            COALESCE(:created_at, now()),
            COALESCE(:updated_at, now()),
            :legacy_mongo_id
        )
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            name = EXCLUDED.name,
            type = EXCLUDED.type,
            metadata = EXCLUDED.metadata,
            retriever = EXCLUDED.retriever,
            sync_frequency = EXCLUDED.sync_frequency,
            tokens = EXCLUDED.tokens,
            file_path = EXCLUDED.file_path,
            remote_data = EXCLUDED.remote_data,
            directory_structure = EXCLUDED.directory_structure,
            file_name_map = EXCLUDED.file_name_map,
            language = EXCLUDED.language,
            model = EXCLUDED.model,
            date = EXCLUDED.date,
            updated_at = EXCLUDED.updated_at
        """
    )
    cursor = mongo_db["sources"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = 0
    batch: list[dict] = []
    # Legacy ingestion/status fields that never got promoted columns. We
    # fold them under metadata.ingestion so nothing is silently dropped
    # on backfill — if any consumer still needs them they can read the
    # JSONB.
    _LEGACY_INGESTION_KEYS = {
        "status", "status_code", "uploaded", "reason", "task_id", "file_token",
    }
    # Known top-level columns we don't want duplicated in metadata.
    _SOURCES_KNOWN_TOP = {
        "_id", "user", "name", "type", "metadata", "retriever",
        "sync_frequency", "tokens", "file_path", "remote_data",
        "directory_structure", "file_name_map", "language", "model",
        "date", "created_at", "updated_at",
    }
    try:
        for doc in cursor:
            seen += 1
            # user may be absent for system sources
            raw_meta = doc.get("metadata") or {}
            # Strip non-serializable values from metadata
            clean_meta = {}
            for k, v in raw_meta.items():
                if hasattr(v, "__str__") and type(v).__name__ == "ObjectId":
                    clean_meta[k] = str(v)
                else:
                    clean_meta[k] = v
            # Preserve any legacy/unknown top-level keys under metadata so
            # they round-trip through backfill rather than being dropped.
            extras: dict = {}
            for k, v in doc.items():
                if k in _SOURCES_KNOWN_TOP:
                    continue
                if k in _LEGACY_INGESTION_KEYS or k not in _SOURCES_KNOWN_TOP:
                    if hasattr(v, "__str__") and type(v).__name__ == "ObjectId":
                        extras[k] = str(v)
                    else:
                        extras[k] = v
            if extras:
                existing_legacy = clean_meta.get("legacy_fields") or {}
                if isinstance(existing_legacy, dict):
                    existing_legacy = {**existing_legacy, **extras}
                else:
                    existing_legacy = extras
                clean_meta["legacy_fields"] = existing_legacy
            tokens_val = doc.get("tokens")
            if tokens_val is not None and not isinstance(tokens_val, str):
                tokens_val = str(tokens_val)
            batch.append({
                "user_id": _normalize_system_user(doc.get("user")),
                "name": doc.get("name", ""),
                "type": doc.get("type"),
                "metadata": json.dumps(clean_meta, default=str),
                "retriever": doc.get("retriever"),
                "sync_frequency": doc.get("sync_frequency"),
                "tokens": tokens_val,
                "file_path": doc.get("file_path"),
                "remote_data": _normalize_mongo_jsonb(doc.get("remote_data")),
                "directory_structure": _normalize_mongo_jsonb(
                    doc.get("directory_structure")
                ),
                "file_name_map": _normalize_mongo_jsonb(doc.get("file_name_map")),
                "language": doc.get("language"),
                "model": doc.get("model"),
                "date": doc.get("date"),
                "created_at": doc.get("date") or doc.get("created_at"),
                "updated_at": doc.get("date") or doc.get("updated_at"),
                "legacy_mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written}


def _resolve_one_source_ref(entry: Any, sources_id_map: dict[str, str]) -> Optional[str]:
    """Resolve a single Mongo source reference (DBRef | ObjectId | str) to a PG UUID."""
    if entry is None or entry == "" or entry == "default":
        return None
    # bson.dbref.DBRef has an `.id` attr; duck-type to avoid a hard bson import.
    if hasattr(entry, "id"):
        oid = str(entry.id)
    else:
        oid = str(entry)
    if not oid or oid == "default":
        return None
    return sources_id_map.get(oid)


def _resolve_source_refs(
    source_field: Any,
    sources_field: Any,
    sources_id_map: dict[str, str],
) -> tuple[Optional[str], list[str]]:
    """Map Mongo agent ``source`` (singular, primary) + ``sources`` (array, extras)
    to PG (source_id, extra_source_ids).

    Mongo's schema uses ``source`` (DBRef or ObjectId-string or the
    literal ``"default"``) for the primary attached source, and
    ``sources`` (array of DBRefs) for any additional ones. Earlier audit
    iterations missed the singular field; backfilling only the array
    dropped the primary FK on ~13 of our dev agents.
    """
    primary = _resolve_one_source_ref(source_field, sources_id_map)
    extras: list[str] = []
    if sources_field:
        for entry in sources_field:
            mapped = _resolve_one_source_ref(entry, sources_id_map)
            if mapped and mapped != primary and mapped not in extras:
                extras.append(mapped)
    return primary, extras


_FAISS_INDEX_FILES = ("index.faiss", "index.pkl")


def _rename_faiss_indexes(
    *,
    conn: Connection,
    mongo_db: Any,  # unused; kept for registry signature uniformity
    batch_size: int,  # unused; filesystem work, not DB batching
    dry_run: bool,
) -> dict:
    """Rename FAISS index dirs from legacy Mongo ObjectId to PG UUID.

    FAISS-specific: other vector stores (Qdrant, Elasticsearch, Chroma,
    pgvector, Milvus, LanceDB, MongoDB Atlas Vector Search) key their
    collections/indexes by the source identifier the application hands
    them at query time — once the app starts emitting PG UUIDs post-
    cutover, the next write re-keys the remote collection automatically
    and any stale ObjectId-keyed collections are harmless orphans the
    operator can clean up separately. FAISS, by contrast, stores each
    index as a directory on disk (``indexes/<source_id>/index.faiss`` +
    ``index.pkl``), so its on-disk layout must be physically renamed to
    match the new PG UUIDs or the app will ``FileNotFoundError`` on the
    first query after cutover.

    This backfiller is a no-op (log-only) unless ``settings.VECTOR_STORE``
    is ``"faiss"``.

    It reads ``sources.legacy_mongo_id -> sources.id`` from Postgres and,
    for each row, renames ``indexes/<legacy_mongo_id>/`` to
    ``indexes/<pg_uuid>/`` via the storage abstraction so both local and
    S3 backends are handled. Orphan directories (names matching no live
    source) are left alone and only counted in the stats. Idempotent:
    if the target dir already exists it is treated as a collision and
    skipped.
    """
    stats = {
        "seen": 0,
        "renamed": 0,
        "skipped_missing": 0,
        "skipped_collision": 0,
        "other_vector_store": False,
    }

    vector_store = (settings.VECTOR_STORE or "").strip().lower()
    if vector_store != "faiss":
        stats["other_vector_store"] = True
        logger.info(
            "rename_faiss_indexes: VECTOR_STORE=%s (not 'faiss'); "
            "skipping FAISS-specific index directory rename. Other vector "
            "stores re-key their collections on the first post-cutover write.",
            vector_store or "<unset>",
        )
        return stats

    from application.storage.storage_creator import StorageCreator

    storage = StorageCreator.get_storage()
    storage_type = getattr(storage, "__class__", type(storage)).__name__
    base_dir = "indexes"

    rows = conn.execute(
        text(
            "SELECT id::text AS id, legacy_mongo_id "
            "FROM sources "
            "WHERE legacy_mongo_id IS NOT NULL"
        )
    ).mappings().all()

    live_legacy_ids = {row["legacy_mongo_id"] for row in rows}

    for row in rows:
        legacy_id = row["legacy_mongo_id"]
        pg_uuid = row["id"]
        stats["seen"] += 1

        src_dir = f"{base_dir}/{legacy_id}"
        dst_dir = f"{base_dir}/{pg_uuid}"

        if not storage.is_directory(src_dir):
            stats["skipped_missing"] += 1
            continue

        if storage.is_directory(dst_dir):
            logger.info(
                "rename_faiss_indexes: target already exists, skipping: "
                "%s -> %s",
                src_dir,
                dst_dir,
            )
            stats["skipped_collision"] += 1
            continue

        if dry_run:
            logger.info(
                "rename_faiss_indexes: would rename %s -> %s", src_dir, dst_dir
            )
            stats["renamed"] += 1
            continue

        # No directory-move primitive on BaseStorage. Copy each known
        # FAISS file, then delete the source file(s). This works for
        # both LocalStorage and S3Storage since both implement
        # get_file/save_file/delete_file on BaseStorage.
        moved_files: list[str] = []
        try:
            for fname in _FAISS_INDEX_FILES:
                src_path = f"{src_dir}/{fname}"
                dst_path = f"{dst_dir}/{fname}"
                if not storage.file_exists(src_path):
                    # Partial/legacy index dir. Copy whatever else is there
                    # via list_files so we don't silently drop data.
                    continue
                data = storage.get_file(src_path).read()
                storage.save_file(io.BytesIO(data), dst_path)
                moved_files.append(src_path)

            # Pick up any auxiliary files that aren't in _FAISS_INDEX_FILES.
            for rel_path in storage.list_files(src_dir):
                # storage.list_files returns paths relative to the storage
                # root (e.g. ``indexes/<legacy_id>/index.faiss``). Skip the
                # two canonical files we already handled.
                leaf = rel_path.rsplit("/", 1)[-1]
                if leaf in _FAISS_INDEX_FILES:
                    continue
                dst_extra = f"{dst_dir}/{leaf}"
                data = storage.get_file(rel_path).read()
                storage.save_file(io.BytesIO(data), dst_extra)
                moved_files.append(rel_path)

            # Only remove the source dir once every copy succeeded.
            storage.remove_directory(src_dir)
            stats["renamed"] += 1
            logger.info(
                "rename_faiss_indexes: renamed %s -> %s (%s)",
                src_dir,
                dst_dir,
                storage_type,
            )
        except Exception:
            logger.exception(
                "rename_faiss_indexes: failed to rename %s -> %s; "
                "partial state may exist on %s. Files copied so far: %s",
                src_dir,
                dst_dir,
                storage_type,
                moved_files,
            )
            raise

    # Count orphan dirs (in indexes/ but no matching live source) purely
    # for operator visibility — leave them alone, as they may be
    # previously-deleted sources unrelated to this migration.
    try:
        orphan_count = 0
        if storage.is_directory(base_dir):
            seen_dirs: set[str] = set()
            for rel_path in storage.list_files(base_dir):
                parts = rel_path.split("/")
                if len(parts) < 2:
                    continue
                dir_name = parts[1]
                if dir_name in seen_dirs:
                    continue
                seen_dirs.add(dir_name)
                if dir_name not in live_legacy_ids and not _is_uuid_str(dir_name):
                    orphan_count += 1
            if orphan_count:
                logger.info(
                    "rename_faiss_indexes: %d orphan index director(y/ies) "
                    "under %s/ do not match any live source — left untouched.",
                    orphan_count,
                    base_dir,
                )
    except Exception:
        # Orphan counting is diagnostic only; never let it fail the backfill.
        logger.debug(
            "rename_faiss_indexes: orphan scan skipped", exc_info=True
        )

    return stats


def _backfill_agents(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    sources_id_map = _build_legacy_id_map(conn, "sources")
    prompts_id_map = _build_legacy_id_map(conn, "prompts")
    folders_id_map = _build_legacy_id_map(conn, "agent_folders")
    workflows_id_map = _build_legacy_id_map(conn, "workflows")

    insert_sql = text(
        """
        INSERT INTO agents (
            user_id, name, status, key, image, description, agent_type,
            source_id, extra_source_ids,
            chunks, retriever, default_model_id,
            prompt_id, folder_id, workflow_id,
            tools, json_schema, models,
            limited_token_mode, token_limit, limited_request_mode, request_limit,
            allow_system_prompt_override,
            shared, shared_token, shared_metadata,
            incoming_webhook_token,
            created_at, updated_at, last_used_at,
            legacy_mongo_id
        ) VALUES (
            :user_id, :name, :status, :key, :image, :description, :agent_type,
            CAST(:source_id AS uuid), CAST(:extra_source_ids AS uuid[]),
            :chunks, :retriever, :default_model_id,
            CAST(:prompt_id AS uuid), CAST(:folder_id AS uuid), CAST(:workflow_id AS uuid),
            CAST(:tools AS jsonb), CAST(:json_schema AS jsonb), CAST(:models AS jsonb),
            :limited_token_mode, :token_limit, :limited_request_mode, :request_limit,
            :allow_system_prompt_override,
            :shared, :shared_token, CAST(:shared_metadata AS jsonb),
            :incoming_webhook_token,
            COALESCE(:created_at, now()),
            COALESCE(:updated_at, now()),
            :last_used_at,
            :legacy_mongo_id
        )
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            name = EXCLUDED.name,
            status = EXCLUDED.status,
            image = EXCLUDED.image,
            description = EXCLUDED.description,
            agent_type = EXCLUDED.agent_type,
            source_id = EXCLUDED.source_id,
            extra_source_ids = EXCLUDED.extra_source_ids,
            chunks = EXCLUDED.chunks,
            retriever = EXCLUDED.retriever,
            default_model_id = EXCLUDED.default_model_id,
            prompt_id = EXCLUDED.prompt_id,
            folder_id = EXCLUDED.folder_id,
            workflow_id = EXCLUDED.workflow_id,
            tools = EXCLUDED.tools,
            json_schema = EXCLUDED.json_schema,
            models = EXCLUDED.models,
            limited_token_mode = EXCLUDED.limited_token_mode,
            token_limit = EXCLUDED.token_limit,
            limited_request_mode = EXCLUDED.limited_request_mode,
            request_limit = EXCLUDED.request_limit,
            allow_system_prompt_override = EXCLUDED.allow_system_prompt_override,
            shared = EXCLUDED.shared,
            shared_token = EXCLUDED.shared_token,
            shared_metadata = EXCLUDED.shared_metadata,
            updated_at = EXCLUDED.updated_at,
            last_used_at = EXCLUDED.last_used_at
        """
    )
    cursor = mongo_db["agents"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            user_id = _normalize_system_user(doc.get("user"))

            primary_source_id, extra_source_ids = _resolve_source_refs(
                doc.get("source"), doc.get("sources"), sources_id_map,
            )

            prompt_oid = doc.get("prompt_id")
            prompt_pg = (
                prompts_id_map.get(str(prompt_oid))
                if prompt_oid and str(prompt_oid) != "default"
                else None
            )

            folder_oid = doc.get("folder_id")
            folder_pg = folders_id_map.get(str(folder_oid)) if folder_oid else None

            workflow_oid = doc.get("workflow")
            workflow_pg = (
                workflows_id_map.get(str(workflow_oid)) if workflow_oid else None
            )

            batch.append({
                "user_id": user_id,
                "name": doc.get("name", ""),
                "status": doc.get("status", "draft"),
                # Mongo allows multiple agents with key="" but Postgres
                # CITEXT UNIQUE treats them as a collision. Coerce empty
                # strings to NULL so the unique constraint is only
                # enforced for actual API keys.
                "key": (doc.get("key") or None),
                "image": doc.get("image"),
                "description": doc.get("description"),
                "agent_type": doc.get("agent_type"),
                "source_id": primary_source_id,
                "extra_source_ids": extra_source_ids,
                "chunks": doc.get("chunks"),
                "retriever": doc.get("retriever"),
                "default_model_id": doc.get("default_model_id"),
                "prompt_id": prompt_pg,
                "folder_id": folder_pg,
                "workflow_id": workflow_pg,
                "tools": json.dumps(doc.get("tools") or [], default=str),
                "json_schema": json.dumps(doc.get("json_schema"), default=str) if doc.get("json_schema") else None,
                "models": json.dumps(doc.get("models"), default=str) if doc.get("models") else None,
                "limited_token_mode": bool(doc.get("limited_token_mode", False)),
                "token_limit": doc.get("token_limit"),
                "limited_request_mode": bool(doc.get("limited_request_mode", False)),
                "request_limit": doc.get("request_limit"),
                "allow_system_prompt_override": bool(
                    doc.get("allow_system_prompt_override", False)
                ),
                # Mongo field is `shared_publicly`; accept `shared` too for
                # forward-compatibility with any PG-native writes that
                # somehow end up in Mongo during the dual-write window.
                "shared": bool(
                    doc.get("shared_publicly", doc.get("shared", False))
                ),
                "shared_token": doc.get("shared_token") or None,
                "shared_metadata": (
                    json.dumps(doc.get("shared_metadata"), default=str)
                    if doc.get("shared_metadata") else None
                ),
                "incoming_webhook_token": doc.get("incoming_webhook_token"),
                "created_at": doc.get("createdAt") or doc.get("created_at"),
                "updated_at": doc.get("updatedAt") or doc.get("updated_at"),
                "last_used_at": doc.get("lastUsedAt") or doc.get("last_used_at"),
                "legacy_mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped": skipped}


def _backfill_attachments(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    insert_sql = text(
        """
        INSERT INTO attachments (
            user_id, filename, upload_path, mime_type, size,
            content, token_count, openai_file_id, google_file_uri,
            metadata, created_at, legacy_mongo_id
        )
        VALUES (
            :user_id, :filename, :upload_path, :mime_type, :size,
            :content, :token_count, :openai_file_id, :google_file_uri,
            CAST(:metadata AS jsonb),
            COALESCE(:created_at, now()),
            :legacy_mongo_id
        )
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            filename = EXCLUDED.filename,
            upload_path = EXCLUDED.upload_path,
            mime_type = EXCLUDED.mime_type,
            size = EXCLUDED.size,
            content = EXCLUDED.content,
            token_count = EXCLUDED.token_count,
            openai_file_id = EXCLUDED.openai_file_id,
            google_file_uri = EXCLUDED.google_file_uri,
            metadata = EXCLUDED.metadata
        """
    )
    cursor = mongo_db["attachments"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            user_id = doc.get("user")
            if not user_id:
                skipped += 1
                continue
            batch.append({
                "user_id": user_id,
                "filename": doc.get("filename", ""),
                # Mongo writes this column as ``path`` (see worker.py);
                # the PG column is ``upload_path``. Earlier backfill
                # copies read doc["upload_path"] and always got "".
                "upload_path": doc.get("path") or doc.get("upload_path", ""),
                "mime_type": doc.get("mime_type"),
                "size": doc.get("size"),
                "content": doc.get("content"),
                "token_count": doc.get("token_count"),
                "openai_file_id": doc.get("openai_file_id"),
                "google_file_uri": doc.get("google_file_uri"),
                "metadata": (
                    json.dumps(doc.get("metadata"), default=str)
                    if doc.get("metadata") else None
                ),
                "created_at": doc.get("date") or doc.get("created_at"),
                "legacy_mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped": skipped}


def _build_tool_id_map(conn: Connection, mongo_db: Any) -> dict[str, str]:
    """Build a mapping from Mongo user_tools ObjectId → Postgres user_tools UUID.

    The Mongo ``_id`` (ObjectId) for each user_tools doc has no equivalent in
    Postgres. We match rows by ``(user_id, name)`` — which is the natural key
    for a tool — and return ``{str(mongo_oid): str(pg_uuid)}``.

    This is called once before memories/todos/notes backfill so those
    collections can resolve their ``tool_id`` foreign keys.
    """
    # Build the Postgres side: (user_id, name) → UUID
    pg_rows = conn.execute(
        text("SELECT id, user_id, name FROM user_tools")
    ).fetchall()
    pg_lookup: dict[tuple[str, str], str] = {}
    for row in pg_rows:
        m = row._mapping
        pg_lookup[(m["user_id"], m["name"])] = str(m["id"])

    # Walk the Mongo side and match
    mapping: dict[str, str] = {}
    for doc in mongo_db["user_tools"].find({}, {"_id": 1, "user": 1, "name": 1}):
        user_id = doc.get("user")
        name = doc.get("name")
        if not user_id or not name:
            continue
        pg_uuid = pg_lookup.get((user_id, name))
        if pg_uuid:
            mapping[str(doc["_id"])] = pg_uuid

    return mapping


def _resolve_tool_id(tool_id_raw: Any, tool_id_map: dict[str, str]) -> str | None:
    """Convert a Mongo tool_id (ObjectId or string) to a Postgres UUID string.

    Returns the mapped UUID, or None if the tool_id can't be resolved.
    """
    if not tool_id_raw:
        return None
    s = str(tool_id_raw)
    # Already a well-formed PG UUID — pass through
    if _is_uuid_str(s):
        return s
    # Mongo ObjectId (24 hex chars) — look up in map
    return tool_id_map.get(s)


def _backfill_memories(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    """Backfill ``memories``.

    Mongo memory docs don't carry the body inline — ``content`` lives on
    disk at ``doc["storage_path"]`` (e.g.
    ``inputs/local/memories/<oid>/memory.txt``) and is accessed through
    :class:`application.storage.storage_creator.StorageCreator`. We read
    the file lazily here so the PG ``content`` column gets the actual
    memory text rather than an empty string. Missing/unreadable files are
    logged and fall back to an empty ``content`` so one bad row doesn't
    abort the whole batch. Import is lazy (matches ``_rename_faiss_indexes``)
    so ``storage`` / backend creds aren't required to import this module.
    """
    from application.storage.storage_creator import StorageCreator

    storage = StorageCreator.get_storage()

    tool_id_map = _build_tool_id_map(conn, mongo_db)
    insert_sql = text(
        """
        INSERT INTO memories (user_id, tool_id, path, content, created_at, updated_at)
        VALUES (
            :user_id, CAST(:tool_id AS uuid), :path, :content,
            COALESCE(:created_at, now()),
            COALESCE(:updated_at, now())
        )
        ON CONFLICT DO NOTHING
        """
    )
    cursor = mongo_db["memories"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            user_id = doc.get("user_id")
            pg_tool_id = _resolve_tool_id(doc.get("tool_id"), tool_id_map)
            if not user_id or not pg_tool_id:
                skipped += 1
                continue
            content = doc.get("content")
            if not content:
                storage_path = doc.get("storage_path")
                if storage_path:
                    try:
                        if storage.file_exists(storage_path):
                            raw = storage.get_file(storage_path).read()
                            if isinstance(raw, bytes):
                                content = raw.decode("utf-8", errors="replace")
                            else:
                                content = str(raw)
                        else:
                            logger.warning(
                                "memories backfill: storage_path missing, "
                                "keeping empty content: user=%s mongo_id=%s "
                                "path=%s",
                                user_id,
                                doc.get("_id"),
                                storage_path,
                            )
                    except Exception:
                        logger.warning(
                            "memories backfill: failed to read storage_path, "
                            "keeping empty content: user=%s mongo_id=%s "
                            "path=%s",
                            user_id,
                            doc.get("_id"),
                            storage_path,
                            exc_info=True,
                        )
            batch.append({
                "user_id": user_id,
                "tool_id": pg_tool_id,
                "path": doc.get("path", "/"),
                "content": content or "",
                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at") or doc.get("created_at"),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped": skipped}


_TODOS_KNOWN_TOP = {
    "_id", "user_id", "tool_id", "todo_id", "title", "status",
    "completed", "created_at", "updated_at",
}


def _backfill_todos(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    """Backfill ``todos`` idempotently.

    Preserves the Mongo ``todo_id`` (per-tool monotonic integer the LLM
    uses as a handle), maps Mongo ``status`` → PG ``completed``, and
    carries ``created_at`` / ``updated_at``. Any unmapped top-level Mongo
    field (e.g. legacy ``conversation_id``) is stashed under
    ``metadata.legacy_fields`` rather than dropped. Idempotent via
    ``legacy_mongo_id``.
    """
    tool_id_map = _build_tool_id_map(conn, mongo_db)
    upsert_sql = text(
        """
        INSERT INTO todos (
            user_id, tool_id, todo_id, title, completed, metadata,
            legacy_mongo_id, created_at, updated_at
        )
        VALUES (
            :user_id, CAST(:tool_id AS uuid), :todo_id, :title, :completed,
            CAST(:metadata AS jsonb), :legacy_mongo_id,
            COALESCE(:created_at, now()),
            COALESCE(:updated_at, now())
        )
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            title      = EXCLUDED.title,
            completed  = EXCLUDED.completed,
            todo_id    = EXCLUDED.todo_id,
            metadata   = EXCLUDED.metadata,
            updated_at = EXCLUDED.updated_at
        """
    )
    cursor = mongo_db["todos"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            user_id = doc.get("user_id")
            pg_tool_id = _resolve_tool_id(doc.get("tool_id"), tool_id_map)
            if not user_id or not pg_tool_id:
                skipped += 1
                continue
            status = doc.get("status", "open")
            todo_id_raw = doc.get("todo_id")
            try:
                todo_id_value = int(todo_id_raw) if todo_id_raw is not None else None
            except (TypeError, ValueError):
                todo_id_value = None
            extras = {
                k: str(v) if type(v).__name__ == "ObjectId" else v
                for k, v in doc.items()
                if k not in _TODOS_KNOWN_TOP
            }
            metadata = {"legacy_fields": extras} if extras else {}
            batch.append({
                "user_id": user_id,
                "tool_id": pg_tool_id,
                "todo_id": todo_id_value,
                "title": doc.get("title", ""),
                "completed": status == "completed",
                "metadata": json.dumps(metadata, default=str),
                "legacy_mongo_id": str(doc["_id"]),
                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at"),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(upsert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(upsert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped": skipped}


_NOTES_KNOWN_TOP = {
    "_id", "user_id", "tool_id", "title", "content", "note",
    "created_at", "updated_at",
}


def _backfill_notes(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    """Backfill ``notes``. Body lives in Mongo's ``note`` field; PG splits
    it into ``content`` + a NOT NULL ``title``. When title is missing,
    fall back through ``path`` → stable ``"note"`` constant. Any unmapped
    Mongo top-level field (e.g. the raw legacy ``path``) is stashed under
    ``metadata.legacy_fields`` rather than dropped. Timestamps are
    preserved.
    """
    tool_id_map = _build_tool_id_map(conn, mongo_db)
    insert_sql = text(
        """
        INSERT INTO notes (
            user_id, tool_id, title, content, metadata,
            created_at, updated_at, legacy_mongo_id
        )
        VALUES (
            :user_id, CAST(:tool_id AS uuid), :title, :content,
            CAST(:metadata AS jsonb),
            COALESCE(:created_at, now()),
            COALESCE(:updated_at, now()),
            :legacy_mongo_id
        )
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            content    = EXCLUDED.content,
            title      = EXCLUDED.title,
            metadata   = EXCLUDED.metadata,
            updated_at = EXCLUDED.updated_at
        """
    )
    cursor = mongo_db["notes"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            user_id = doc.get("user_id")
            pg_tool_id = _resolve_tool_id(doc.get("tool_id"), tool_id_map)
            if not user_id or not pg_tool_id:
                skipped += 1
                continue
            title = doc.get("title") or doc.get("path") or "note"
            content = doc.get("content") or doc.get("note") or ""
            extras = {
                k: str(v) if type(v).__name__ == "ObjectId" else v
                for k, v in doc.items()
                if k not in _NOTES_KNOWN_TOP
            }
            metadata = {"legacy_fields": extras} if extras else {}
            batch.append({
                "user_id": user_id,
                "tool_id": pg_tool_id,
                "title": title,
                "content": content,
                "metadata": json.dumps(metadata, default=str),
                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at"),
                "legacy_mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped": skipped}


def _backfill_connector_sessions(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    insert_sql = text(
        """
        INSERT INTO connector_sessions (
            user_id, provider, server_url,
            session_token, user_email, status, token_info,
            session_data, expires_at, created_at, legacy_mongo_id
        )
        VALUES (
            :user_id, :provider, :server_url,
            :session_token, :user_email, :status, CAST(:token_info AS jsonb),
            CAST(:session_data AS jsonb), :expires_at,
            COALESCE(:created_at, now()), :legacy_mongo_id
        )
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            server_url    = EXCLUDED.server_url,
            session_token = EXCLUDED.session_token,
            user_email    = EXCLUDED.user_email,
            status        = EXCLUDED.status,
            token_info    = EXCLUDED.token_info,
            session_data  = EXCLUDED.session_data,
            expires_at    = EXCLUDED.expires_at
        """
    )
    # Dedupe stale pending OAuth starts: multiple Mongo rows often share
    # the same ``(user_id, server_url, provider)`` triple because each
    # OAuth button click inserts a pending row; only the last one
    # successfully authorized. The PG composite unique constraint would
    # reject the duplicates, so keep the newest row per triple — prefer
    # authorized rows over pending ones, then newer ``created_at``.
    raw_docs = list(mongo_db["connector_sessions"].find({}, no_cursor_timeout=True))
    dedup: dict[tuple, dict] = {}
    for doc in raw_docs:
        user_id = doc.get("user_id") or doc.get("user")
        provider = doc.get("provider")
        if not user_id or not provider:
            continue
        server_url = doc.get("server_url") or ""
        key = (user_id, server_url, provider)
        existing = dedup.get(key)
        if existing is None:
            dedup[key] = doc
            continue
        # Prefer authorized (has token_info) over pending.
        existing_has_token = bool(existing.get("token_info"))
        doc_has_token = bool(doc.get("token_info"))
        if doc_has_token and not existing_has_token:
            dedup[key] = doc
            continue
        if existing_has_token and not doc_has_token:
            continue
        # Both same class — newer wins.
        existing_ts = existing.get("created_at")
        doc_ts = doc.get("created_at")
        if doc_ts and (existing_ts is None or doc_ts > existing_ts):
            dedup[key] = doc

    seen = len(raw_docs)
    skipped = seen - len(dedup)
    written = 0
    # Mongo top-level keys that are now promoted to dedicated PG columns
    # should NOT also end up stuffed into session_data.
    _PROMOTED = {
        "_id", "user_id", "user", "provider", "server_url",
        "session_token", "user_email", "status", "token_info",
        "expires_at", "created_at",
    }
    batch: list[dict] = []
    try:
        for doc in dedup.values():
            user_id = doc.get("user_id") or doc.get("user")
            provider = doc.get("provider")
            session_data = {k: v for k, v in doc.items() if k not in _PROMOTED}
            batch.append({
                "user_id": user_id,
                "provider": provider,
                "server_url": doc.get("server_url"),
                "session_token": doc.get("session_token"),
                "user_email": doc.get("user_email"),
                "status": doc.get("status"),
                "token_info": (
                    json.dumps(doc.get("token_info"), default=str)
                    if doc.get("token_info") else None
                ),
                "session_data": json.dumps(session_data, default=str),
                "expires_at": doc.get("expires_at"),
                "created_at": doc.get("created_at"),
                "legacy_mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        # ``raw_docs`` was materialised up-front (to support the dedupe
        # pass), so there's no cursor to close here.
        pass
    return {"seen": seen, "written": written, "skipped": skipped}


# ---------------------------------------------------------------------------
# Phase 3 backfillers
# ---------------------------------------------------------------------------


def _backfill_conversations(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    """Sync the ``conversations`` table from Mongo ``conversations`` collection.

    Also flattens the nested ``queries`` array into
    ``conversation_messages`` rows (one per query, position = array index).

    Idempotent via the ``legacy_mongo_id`` column: rerunning replaces any
    previously migrated row's mutable fields and re-syncs its messages.
    """
    agent_id_map = _build_legacy_id_map(conn, "agents")
    attachment_id_map = _build_legacy_id_map(conn, "attachments")

    conv_sql = text(
        """
        INSERT INTO conversations
            (user_id, name, agent_id, api_key, is_shared_usage, shared_token,
             shared_with, compression_metadata, date, legacy_mongo_id)
        VALUES
            (:user_id, :name, CAST(:agent_id AS uuid), :api_key,
             :is_shared_usage, :shared_token,
             CAST(:shared_with AS text[]), CAST(:compression_metadata AS jsonb),
             :date, :legacy_mongo_id)
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            name = EXCLUDED.name,
            agent_id = EXCLUDED.agent_id,
            api_key = EXCLUDED.api_key,
            is_shared_usage = EXCLUDED.is_shared_usage,
            shared_token = EXCLUDED.shared_token,
            shared_with = EXCLUDED.shared_with,
            compression_metadata = EXCLUDED.compression_metadata,
            updated_at = now()
        RETURNING id
        """
    )
    truncate_sql = text(
        """
        DELETE FROM conversation_messages
        WHERE conversation_id = CAST(:conv_id AS uuid)
        AND position > :max_pos
        """
    )
    msg_sql = text(
        """
        INSERT INTO conversation_messages
            (conversation_id, position, prompt, response, thought,
             sources, tool_calls, attachments, model_id, message_metadata, feedback,
             timestamp)
        VALUES
            (CAST(:conv_id AS uuid), :position, :prompt, :response, :thought,
             CAST(:sources AS jsonb), CAST(:tool_calls AS jsonb),
             CAST(:attachments AS uuid[]),
             :model_id, CAST(:metadata AS jsonb), CAST(:feedback AS jsonb),
             :timestamp)
        ON CONFLICT (conversation_id, position) DO UPDATE SET
            prompt = EXCLUDED.prompt,
            response = EXCLUDED.response,
            thought = EXCLUDED.thought,
            sources = EXCLUDED.sources,
            tool_calls = EXCLUDED.tool_calls,
            attachments = EXCLUDED.attachments,
            model_id = EXCLUDED.model_id,
            message_metadata = EXCLUDED.message_metadata,
            feedback = EXCLUDED.feedback,
            timestamp = EXCLUDED.timestamp
        """
    )

    cursor = mongo_db["conversations"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = msg_written = skipped = 0
    malformed_messages = 0
    unresolved_attachment_refs = 0

    try:
        for doc in cursor:
            seen += 1
            user_id = doc.get("user")
            if not user_id:
                skipped += 1
                continue

            shared_with = doc.get("shared_with") or []
            comp_meta = doc.get("compression_metadata")

            if dry_run:
                # In dry-run we don't write, so we can't get a returning id.
                # Skip message insertion too — they need the FK.
                continue

            mongo_agent_id = doc.get("agent_id")
            pg_agent_id = agent_id_map.get(str(mongo_agent_id)) if mongo_agent_id else None

            result = conn.execute(conv_sql, {
                "user_id": user_id,
                "name": doc.get("name"),
                "agent_id": pg_agent_id,
                "api_key": doc.get("api_key"),
                "is_shared_usage": bool(doc.get("is_shared_usage", False)),
                "shared_token": doc.get("shared_token"),
                "shared_with": list(shared_with),
                "compression_metadata": json.dumps(comp_meta, default=str) if comp_meta else None,
                "date": _coerce_document_timestamp(doc, "date", "created_at", "updated_at"),
                "legacy_mongo_id": str(doc["_id"]),
            })
            pg_conv_id = str(result.scalar())
            written += 1

            # Flatten queries array → conversation_messages rows
            queries = doc.get("queries") or []
            msg_batch: list[dict] = []
            for pos, q in enumerate(queries):
                if not isinstance(q, dict):
                    malformed_messages += 1
                    logger.warning(
                        "Skipping malformed conversation query during backfill: "
                        "conversation=%s position=%s type=%s",
                        doc.get("_id"),
                        pos,
                        type(q).__name__,
                    )
                    continue
                fb = q.get("feedback")
                fb_ts = q.get("feedback_timestamp")
                feedback_json = None
                if fb is not None:
                    feedback_json = json.dumps({"text": fb, "timestamp": str(fb_ts)} if fb_ts else {"text": fb})

                # Resolve attachment ObjectIds → Postgres UUIDs; drop unresolved.
                raw_attachments = q.get("attachments") or []
                resolved_attachments: list[str] = []
                for a in raw_attachments:
                    if not a:
                        continue
                    s = str(a)
                    if _is_uuid_str(s):
                        resolved_attachments.append(s)
                    else:
                        mapped = attachment_id_map.get(s)
                        if mapped:
                            resolved_attachments.append(mapped)
                        else:
                            unresolved_attachment_refs += 1
                            logger.warning(
                                "Conversation backfill dropped unresolved attachment ref: "
                                "conversation=%s position=%s attachment=%s",
                                doc.get("_id"),
                                pos,
                                s,
                            )

                msg_batch.append({
                    "conv_id": pg_conv_id,
                    "position": pos,
                    "prompt": q.get("prompt"),
                    "response": q.get("response"),
                    "thought": q.get("thought"),
                    "sources": json.dumps(q.get("sources") or [], default=str),
                    "tool_calls": json.dumps(q.get("tool_calls") or [], default=str),
                    "attachments": resolved_attachments,
                    "model_id": q.get("model_id"),
                    "metadata": json.dumps(q.get("metadata") or {}, default=str),
                    "feedback": feedback_json,
                    "timestamp": (
                        q.get("timestamp")
                        or doc.get("date")
                        or doc.get("created_at")
                        or doc.get("updated_at")
                        or datetime.now(timezone.utc)
                    ),
                })

            if msg_batch and not dry_run:
                conn.execute(msg_sql, msg_batch)
            msg_written += len(msg_batch)

            # Converge: drop any messages past the Mongo queries length
            # (handles the case where a conversation was truncated in Mongo
            # after a previous backfill).
            if not dry_run:
                conn.execute(truncate_sql, {
                    "conv_id": pg_conv_id,
                    "max_pos": len(queries) - 1,
                })

    finally:
        cursor.close()

    return {
        "seen": seen,
        "written": written,
        "messages_written": msg_written,
        "skipped": skipped,
        "malformed_messages": malformed_messages,
        "unresolved_attachment_refs": unresolved_attachment_refs,
    }


def _build_legacy_id_map(conn: Connection, table: str) -> dict[str, str]:
    """Return ``{legacy_mongo_id: pg_uuid}`` for the given table.

    Used by Phase 3 backfills to resolve FK references that were Mongo
    ObjectIds in the source data into the new Postgres UUIDs.
    """
    rows = conn.execute(
        text(
            f"SELECT id, legacy_mongo_id FROM {table} "
            "WHERE legacy_mongo_id IS NOT NULL"
        )
    ).fetchall()
    return {r._mapping["legacy_mongo_id"]: str(r._mapping["id"]) for r in rows}


def _remediate_user_agent_prefs(
    *, conn: Connection, mongo_db: Any = None, batch_size: int = 500, dry_run: bool = False,
) -> dict:
    """Rewrite ``users.agent_preferences`` ObjectId entries to Postgres UUIDs.

    Pre-cutover Mongo data stored ``agent_preferences.pinned`` /
    ``agent_preferences.shared_with_me`` as 24-char ObjectId strings. The
    Postgres ``cleanup_user_agent_prefs`` trigger compares
    ``agents.id::text`` (UUID, 36 chars) against those entries, so
    without remediation deleted agents leave stale pinned/shared rows
    that no UI lookup can resolve.

    Idempotent: already-UUID entries pass through untouched.
    """
    legacy_to_uuid = _build_legacy_id_map(conn, "agents")

    rows = conn.execute(
        text("SELECT user_id, agent_preferences FROM users")
    ).fetchall()

    seen = updated = entries_kept = entries_remapped = entries_dropped = 0
    for row in rows:
        seen += 1
        user_id = row._mapping["user_id"]
        prefs = row._mapping["agent_preferences"] or {}
        if not isinstance(prefs, dict):
            continue
        new_prefs = dict(prefs)
        changed = False
        for key in ("pinned", "shared_with_me"):
            original = list(prefs.get(key) or [])
            rewritten: list[str] = []
            for entry in original:
                if not isinstance(entry, str):
                    entry = str(entry)
                if _is_uuid_str(entry):
                    rewritten.append(entry)
                    entries_kept += 1
                elif _is_object_id_str(entry):
                    pg_uuid = legacy_to_uuid.get(entry)
                    if pg_uuid:
                        rewritten.append(pg_uuid)
                        entries_remapped += 1
                    else:
                        entries_dropped += 1
                else:
                    rewritten.append(entry)
                    entries_kept += 1
            if rewritten != original:
                changed = True
            new_prefs[key] = rewritten
        if changed:
            updated += 1
            if not dry_run:
                conn.execute(
                    text(
                        "UPDATE users SET agent_preferences = CAST(:prefs AS jsonb), "
                        "updated_at = now() WHERE user_id = :uid"
                    ),
                    {"prefs": json.dumps(new_prefs), "uid": user_id},
                )

    return {
        "seen": seen,
        "updated": updated,
        "entries_kept": entries_kept,
        "entries_remapped": entries_remapped,
        "entries_dropped": entries_dropped,
    }


def _backfill_shared_conversations(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    """Sync the ``shared_conversations`` table.

    Resolves Mongo ``conversation_id`` (ObjectId) → Postgres
    ``conversations.id`` (UUID) via the ``conversations.legacy_mongo_id``
    column populated during the conversations backfill. Rows whose
    parent conversation was not migrated are skipped.
    """
    conv_id_map = _build_legacy_id_map(conn, "conversations")
    prompt_id_map = _build_legacy_id_map(conn, "prompts")
    agent_meta_by_key = {
        doc.get("key"): {
            "prompt_id": doc.get("prompt_id"),
            "chunks": doc.get("chunks"),
        }
        for doc in mongo_db["agents"].find({}, {"key": 1, "prompt_id": 1, "chunks": 1})
        if doc.get("key")
    }
    insert_sql = text(
        """
        INSERT INTO shared_conversations
            (uuid, conversation_id, user_id, is_promptable, first_n_queries,
             api_key, prompt_id, chunks)
        VALUES
            (CAST(:uuid AS uuid), CAST(:conv_id AS uuid), :user_id,
             :is_promptable, :first_n_queries, :api_key,
             CAST(:prompt_id AS uuid), :chunks)
        ON CONFLICT (uuid) DO UPDATE SET
            conversation_id = EXCLUDED.conversation_id,
            user_id = EXCLUDED.user_id,
            is_promptable = EXCLUDED.is_promptable,
            first_n_queries = EXCLUDED.first_n_queries,
            api_key = EXCLUDED.api_key,
            prompt_id = EXCLUDED.prompt_id,
            chunks = EXCLUDED.chunks
        """
    )
    cursor = (
        mongo_db["shared_conversations"]
        .find({}, no_cursor_timeout=True)
        .batch_size(batch_size)
    )
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            user_id = doc.get("user")
            mongo_conv_id = _extract_mongo_id_text(doc.get("conversation_id"))
            mongo_uuid = doc.get("uuid")
            if not user_id or not mongo_conv_id or not mongo_uuid:
                skipped += 1
                continue
            pg_conv_id = conv_id_map.get(mongo_conv_id)
            if not pg_conv_id:
                skipped += 1
                continue

            # Mongo stores ``uuid`` as BSON Binary (standard UUID subtype).
            # Unwrap to a plain uuid.UUID → string for Postgres CAST.
            try:
                share_uuid_str = str(mongo_uuid.as_uuid()) if hasattr(mongo_uuid, "as_uuid") else str(mongo_uuid)
            except Exception:
                share_uuid_str = str(mongo_uuid)

            # prompt_id may be either a prompt ObjectId or the literal string
            # "default" (see sharing/routes.py); only resolvable ObjectIds
            # get a real FK value.
            agent_meta = agent_meta_by_key.get(doc.get("api_key")) or {}
            raw_prompt_id = doc.get("prompt_id")
            if raw_prompt_id is None:
                raw_prompt_id = agent_meta.get("prompt_id")
            prompt_legacy_id = _extract_mongo_id_text(raw_prompt_id)
            resolved_prompt_id = (
                prompt_id_map.get(prompt_legacy_id) if prompt_legacy_id else None
            )

            chunks_raw = doc.get("chunks")
            if chunks_raw is None:
                chunks_raw = agent_meta.get("chunks")
            chunks_val: int | None = None
            if chunks_raw is not None:
                try:
                    chunks_val = int(chunks_raw)
                except (TypeError, ValueError):
                    chunks_val = None

            batch.append({
                "uuid": share_uuid_str,
                "conv_id": pg_conv_id,
                "user_id": user_id,
                "is_promptable": bool(doc.get("isPromptable", False)),
                "first_n_queries": doc.get("first_n_queries", 0),
                "api_key": doc.get("api_key"),
                "prompt_id": resolved_prompt_id,
                "chunks": chunks_val,
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped": skipped}


def _backfill_pending_tool_state(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    """Sync ``pending_tool_state`` from Mongo.

    Most rows will be expired by the time the backfill runs (30-min TTL).
    We copy them anyway; the Celery cleanup task will purge stale rows on
    its first tick. Resolves ``conversation_id`` via
    ``conversations.legacy_mongo_id``.
    """
    conv_id_map = _build_legacy_id_map(conn, "conversations")
    insert_sql = text(
        """
        INSERT INTO pending_tool_state
            (conversation_id, user_id, messages, pending_tool_calls,
             tools_dict, tool_schemas, agent_config, client_tools,
             created_at, expires_at)
        VALUES
            (CAST(:conv_id AS uuid), :user_id,
             CAST(:messages AS jsonb), CAST(:pending AS jsonb),
             CAST(:tools_dict AS jsonb), CAST(:schemas AS jsonb),
             CAST(:agent_config AS jsonb), CAST(:client_tools AS jsonb),
             :created_at, :expires_at)
        ON CONFLICT (conversation_id, user_id) DO UPDATE SET
            messages = EXCLUDED.messages,
            pending_tool_calls = EXCLUDED.pending_tool_calls,
            tools_dict = EXCLUDED.tools_dict,
            tool_schemas = EXCLUDED.tool_schemas,
            agent_config = EXCLUDED.agent_config,
            client_tools = EXCLUDED.client_tools,
            created_at = EXCLUDED.created_at,
            expires_at = EXCLUDED.expires_at
        """
    )
    cursor = (
        mongo_db["pending_tool_state"]
        .find({}, no_cursor_timeout=True)
        .batch_size(batch_size)
    )
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            mongo_conv_id = doc.get("conversation_id")
            user_id = doc.get("user")
            if not mongo_conv_id or not user_id:
                skipped += 1
                continue
            pg_conv_id = conv_id_map.get(str(mongo_conv_id))
            if not pg_conv_id:
                skipped += 1
                continue
            batch.append({
                "conv_id": pg_conv_id,
                "user_id": user_id,
                "messages": json.dumps(doc.get("messages") or [], default=str),
                "pending": json.dumps(doc.get("pending_tool_calls") or [], default=str),
                "tools_dict": json.dumps(doc.get("tools_dict") or {}, default=str),
                "schemas": json.dumps(doc.get("tool_schemas") or [], default=str),
                "agent_config": json.dumps(doc.get("agent_config") or {}, default=str),
                "client_tools": json.dumps(doc.get("client_tools"), default=str) if doc.get("client_tools") else None,
                "created_at": doc.get("created_at"),
                "expires_at": doc.get("expires_at"),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped": skipped}


def _backfill_workflows(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    """Sync the ``workflows`` table from Mongo ``workflows`` collection.

    Idempotent via ``legacy_mongo_id``.
    """
    insert_sql = text(
        """
        INSERT INTO workflows (
            user_id, name, description, current_graph_version,
            created_at, updated_at, legacy_mongo_id
        )
        VALUES (
            :user_id, :name, :description, :current_graph_version,
            COALESCE(:created_at, now()),
            COALESCE(:updated_at, now()),
            :legacy_mongo_id
        )
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            current_graph_version = EXCLUDED.current_graph_version,
            updated_at = COALESCE(EXCLUDED.updated_at, now())
        """
    )
    cursor = mongo_db["workflows"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            user_id = doc.get("user")
            if not user_id:
                skipped += 1
                continue
            batch.append({
                "user_id": user_id,
                "name": doc.get("name", ""),
                "description": doc.get("description"),
                "current_graph_version": doc.get("current_graph_version", 1),
                "created_at": doc.get("created_at") or doc.get("createdAt"),
                "updated_at": doc.get("updated_at") or doc.get("updatedAt"),
                "legacy_mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped": skipped}


def _backfill_workflow_nodes(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    """Sync ``workflow_nodes``.

    Resolves Mongo ``workflow_id`` (string ObjectId) →
    ``workflows.id`` (UUID) via ``workflows.legacy_mongo_id``.
    Idempotent via ``legacy_mongo_id``.
    """
    workflow_id_map = _build_legacy_id_map(conn, "workflows")
    insert_sql = text(
        """
        INSERT INTO workflow_nodes
            (workflow_id, graph_version, node_id, node_type, title, description,
             position, config, legacy_mongo_id)
        VALUES
            (CAST(:workflow_id AS uuid), :graph_version, :node_id, :node_type,
             :title, :description, CAST(:position AS jsonb), CAST(:config AS jsonb),
             :legacy_mongo_id)
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            graph_version = EXCLUDED.graph_version,
            node_id = EXCLUDED.node_id,
            node_type = EXCLUDED.node_type,
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            position = EXCLUDED.position,
            config = EXCLUDED.config
        """
    )
    cursor = mongo_db["workflow_nodes"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            mongo_wf_id = doc.get("workflow_id")
            if not mongo_wf_id:
                skipped += 1
                continue
            pg_wf_id = workflow_id_map.get(str(mongo_wf_id))
            if not pg_wf_id:
                skipped += 1
                continue
            position = doc.get("position") or {"x": 0, "y": 0}
            batch.append({
                "workflow_id": pg_wf_id,
                "graph_version": doc.get("graph_version", 1),
                "node_id": doc.get("id", ""),
                "node_type": doc.get("type", ""),
                "title": doc.get("title"),
                "description": doc.get("description"),
                "position": json.dumps(position, default=str),
                "config": json.dumps(doc.get("config") or {}, default=str),
                "legacy_mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped": skipped}


def _backfill_workflow_edges(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    """Sync the ``workflow_edges`` table from Mongo ``workflow_edges`` collection.

    Must run after ``workflow_nodes`` because ``from_node_id`` and
    ``to_node_id`` are FKs into ``workflow_nodes``.

    The Mongo doc stores ``source_id`` and ``target_id`` as user-provided
    node-id strings. We need to resolve them to Postgres UUIDs by looking
    up the ``workflow_nodes`` row with matching ``(workflow_id,
    graph_version, node_id)``.
    """
    workflow_id_map = _build_legacy_id_map(conn, "workflows")
    # Build a lookup: (pg_workflow_uuid, graph_version, node_id_str) → pg node UUID
    pg_nodes = conn.execute(
        text("SELECT id, workflow_id, graph_version, node_id FROM workflow_nodes")
    ).fetchall()
    node_lookup: dict[tuple[str, int, str], str] = {}
    for row in pg_nodes:
        m = row._mapping
        node_lookup[(str(m["workflow_id"]), m["graph_version"], m["node_id"])] = str(m["id"])

    insert_sql = text(
        """
        INSERT INTO workflow_edges
            (workflow_id, graph_version, edge_id, from_node_id, to_node_id,
             source_handle, target_handle, config)
        VALUES
            (CAST(:workflow_id AS uuid), :graph_version, :edge_id,
             CAST(:from_node_id AS uuid), CAST(:to_node_id AS uuid),
             :source_handle, :target_handle, CAST(:config AS jsonb))
        ON CONFLICT (workflow_id, graph_version, edge_id) DO UPDATE SET
            from_node_id = EXCLUDED.from_node_id,
            to_node_id = EXCLUDED.to_node_id,
            source_handle = EXCLUDED.source_handle,
            target_handle = EXCLUDED.target_handle,
            config = EXCLUDED.config
        """
    )
    cursor = mongo_db["workflow_edges"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            mongo_wf_id = doc.get("workflow_id")
            if not mongo_wf_id:
                skipped += 1
                continue

            pg_wf_id = workflow_id_map.get(str(mongo_wf_id))
            if not pg_wf_id:
                skipped += 1
                continue

            gv = doc.get("graph_version", 1)
            source_nid = doc.get("source_id", "")
            target_nid = doc.get("target_id", "")

            from_uuid = node_lookup.get((pg_wf_id, gv, source_nid))
            to_uuid = node_lookup.get((pg_wf_id, gv, target_nid))
            if not from_uuid or not to_uuid:
                skipped += 1
                continue

            batch.append({
                "workflow_id": pg_wf_id,
                "graph_version": gv,
                "edge_id": doc.get("id", ""),
                "from_node_id": from_uuid,
                "to_node_id": to_uuid,
                "source_handle": doc.get("source_handle"),
                "target_handle": doc.get("target_handle"),
                "config": json.dumps(doc.get("config") or {}, default=str),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped": skipped}


def _backfill_workflow_runs(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    """Sync the ``workflow_runs`` table from Mongo ``workflow_runs`` collection.

    Resolves Mongo ``workflow_id`` (string) → PG UUID via
    ``workflows.legacy_mongo_id``. Rows whose parent workflow was never
    migrated (e.g. legacy ``workflow_id='unknown'``) are skipped.
    """
    workflow_id_map = _build_legacy_id_map(conn, "workflows")
    insert_sql = text(
        """
        INSERT INTO workflow_runs
            (workflow_id, user_id, status, inputs, result, steps,
             started_at, ended_at, legacy_mongo_id)
        VALUES
            (CAST(:workflow_id AS uuid), :user_id, :status,
             CAST(:inputs AS jsonb), CAST(:result AS jsonb),
             CAST(:steps AS jsonb), :started_at, :ended_at, :legacy_mongo_id)
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            status = EXCLUDED.status,
            inputs = EXCLUDED.inputs,
            result = EXCLUDED.result,
            steps = EXCLUDED.steps,
            ended_at = EXCLUDED.ended_at
        """
    )
    cursor = mongo_db["workflow_runs"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            mongo_wf_id = doc.get("workflow_id")
            if not mongo_wf_id:
                skipped += 1
                continue
            pg_wf_id = workflow_id_map.get(str(mongo_wf_id))
            if not pg_wf_id:
                skipped += 1
                continue
            batch.append({
                "workflow_id": pg_wf_id,
                "user_id": doc.get("user_id") or doc.get("user") or SYSTEM_USER_ID,
                "status": _coerce_workflow_run_status(doc.get("status")),
                "inputs": json.dumps(doc.get("inputs") or {}, default=str),
                "result": json.dumps(doc.get("outputs") or doc.get("result"), default=str),
                "steps": json.dumps(doc.get("steps") or [], default=str),
                "started_at": doc.get("started_at") or doc.get("created_at"),
                "ended_at": doc.get("ended_at") or doc.get("completed_at"),
                "legacy_mongo_id": str(doc["_id"]),
            })
            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(insert_sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            if not dry_run:
                conn.execute(insert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()
    return {"seen": seen, "written": written, "skipped": skipped}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


BackfillFn = Callable[..., dict]

# Register new tables here. Order matters only in the sense that
# ``--tables`` without arguments iterates in insertion order — put tables
# with FK dependencies after the tables they reference so a full-run
# backfill doesn't hit FK errors.
BACKFILLERS: dict[str, BackfillFn] = {
    # Phase 1
    "users": _backfill_users,
    "prompts": _backfill_prompts,
    "user_tools": _backfill_user_tools,
    "stack_logs": _backfill_stack_logs,
    "user_logs": _backfill_user_logs,
    "token_usage": _backfill_token_usage,
    # Phase 2 (order: FK targets first)
    "agent_folders": _backfill_agent_folders,
    "sources": _backfill_sources,
    # Filesystem rename of FAISS index dirs (legacy Mongo ObjectId -> PG UUID).
    # No-op unless VECTOR_STORE=faiss. Runs after `sources` so the
    # legacy_mongo_id -> id mapping is queryable, and before `agents` to keep
    # the vector-store plumbing adjacent to the table it depends on.
    "rename_faiss_indexes": _rename_faiss_indexes,
    "attachments": _backfill_attachments,
    # Workflows are migrated before agents because agents.workflow_id
    # FK-references the workflows table and the agents backfill resolves
    # the Mongo `workflow` ObjectId via a `legacy_mongo_id` lookup that
    # only works if workflows rows are already in place.
    "workflows": _backfill_workflows,
    "agents": _backfill_agents,
    # Remediation pass: rewrite any ObjectId-shaped entries in
    # ``users.agent_preferences.{pinned,shared_with_me}`` to PG UUIDs.
    # Must run after ``agents`` so the legacy→UUID lookup table is full.
    "users_prefs_remediation": _remediate_user_agent_prefs,
    "memories": _backfill_memories,
    "todos": _backfill_todos,
    "notes": _backfill_notes,
    "connector_sessions": _backfill_connector_sessions,
    # Phase 3 (order: conversations first, then dependents)
    "conversations": _backfill_conversations,
    "shared_conversations": _backfill_shared_conversations,
    "pending_tool_state": _backfill_pending_tool_state,
    "workflow_nodes": _backfill_workflow_nodes,
    "workflow_edges": _backfill_workflow_edges,
    "workflow_runs": _backfill_workflow_runs,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill DocsGPT Postgres tables from MongoDB."
    )
    parser.add_argument(
        "--tables",
        default="",
        help=(
            "Comma-separated table names to backfill. "
            f"Defaults to every registered table ({','.join(BACKFILLERS)})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Iterate Mongo without writing to Postgres.",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=500,
        help="How many rows to commit per Postgres statement (default: 500).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    )

    if not settings.POSTGRES_URI:
        logger.error("POSTGRES_URI is not set. Configure it in .env first.")
        return 1
    if not settings.MONGO_URI:
        logger.error("MONGO_URI is not set. Configure it in .env first.")
        return 1

    requested = [t.strip() for t in args.tables.split(",") if t.strip()]
    if not requested:
        requested = list(BACKFILLERS)

    unknown = [t for t in requested if t not in BACKFILLERS]
    if unknown:
        logger.error(
            "Unknown table(s): %s. Available: %s",
            ", ".join(unknown),
            ", ".join(BACKFILLERS),
        )
        return 1

    try:
        from pymongo import MongoClient
    except ImportError:
        logger.error(
            "pymongo is not installed. Install it to run the "
            "backfill: pip install 'pymongo>=4.6'"
        )
        return 1

    mongo = MongoClient(settings.MONGO_URI)
    mongo_db = mongo[_MONGO_DB_NAME]
    engine = get_engine()

    # Ensure the ``__system__`` sentinel user exists before any template
    # rows try to attach to it. Cheap, idempotent, safe to run every time.
    if not args.dry_run:
        with engine.begin() as conn:
            _ensure_system_user(conn)

    failures = 0
    for table in requested:
        logger.info("backfill %s: start", table)
        try:
            with engine.begin() as conn:
                stats = BACKFILLERS[table](
                    conn=conn,
                    mongo_db=mongo_db,
                    batch_size=args.batch,
                    dry_run=args.dry_run,
                )
            logger.info(
                "backfill %s: done %s dry_run=%s", table, stats, args.dry_run
            )
        except Exception:
            failures += 1
            logger.exception("backfill %s: failed", table)

    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
