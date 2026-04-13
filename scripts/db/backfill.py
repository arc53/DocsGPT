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
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Make the project root importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import Connection, text  # noqa: E402

from application.core.mongo_db import MongoDB  # noqa: E402
from application.core.settings import settings  # noqa: E402
from application.storage.db.engine import get_engine  # noqa: E402

logger = logging.getLogger("backfill")


# ---------------------------------------------------------------------------
# Per-table backfillers
# ---------------------------------------------------------------------------


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

    Overwrites each Postgres row's ``agent_preferences`` with the Mongo
    state (Mongo is source of truth during the cutover window). Missing
    ``pinned`` / ``shared_with_me`` keys are filled with empty arrays so
    the Postgres row always has the full shape the application expects.
    """
    upsert_sql = text(
        """
        INSERT INTO users (user_id, agent_preferences)
        VALUES (:user_id, CAST(:prefs AS jsonb))
        ON CONFLICT (user_id) DO UPDATE
            SET agent_preferences = EXCLUDED.agent_preferences,
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
            prefs = {
                "pinned": list(raw_prefs.get("pinned") or []),
                "shared_with_me": list(raw_prefs.get("shared_with_me") or []),
            }
            batch.append({"user_id": user_id, "prefs": json.dumps(prefs)})

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
            user_id = doc.get("user")
            if not user_id:
                skipped += 1
                continue
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
        INSERT INTO user_tools (user_id, name, custom_name, display_name, config)
        VALUES (:user_id, :name, :custom_name, :display_name, CAST(:config AS jsonb))
        ON CONFLICT DO NOTHING
        """
    )
    cursor = mongo_db["user_tools"].find({}, no_cursor_timeout=True).batch_size(batch_size)
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
                "custom_name": doc.get("customName"),
                "display_name": doc.get("displayName"),
                "config": json.dumps(doc.get("config") or {}),
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
        INSERT INTO stack_logs (activity_id, endpoint, level, user_id, api_key, query, stacks, timestamp)
        VALUES (:activity_id, :endpoint, :level, :user_id, :api_key, :query, CAST(:stacks AS jsonb), :timestamp)
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
                "stacks": json.dumps(doc.get("stacks") or []),
                "timestamp": doc.get("timestamp"),
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
        INSERT INTO user_logs (user_id, endpoint, data, timestamp)
        VALUES (:user_id, :endpoint, CAST(:data AS jsonb), :timestamp)
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
        INSERT INTO token_usage (user_id, api_key, agent_id, prompt_tokens, generated_tokens, timestamp)
        VALUES (
            :user_id, :api_key,
            CAST(:agent_id AS uuid),
            :prompt_tokens, :generated_tokens, :timestamp
        )
        """
    )
    cursor = mongo_db["token_usage"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            agent_id = doc.get("agent_id")
            agent_id_str = None
            if agent_id:
                s = str(agent_id)
                if len(s) == 36 and "-" in s:
                    agent_id_str = s
            batch.append({
                "user_id": doc.get("user_id"),
                "api_key": doc.get("api_key"),
                "agent_id": agent_id_str,
                "prompt_tokens": doc.get("prompt_tokens", 0),
                "generated_tokens": doc.get("generated_tokens", 0),
                "timestamp": doc.get("timestamp"),
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


# ---------------------------------------------------------------------------
# Phase 2 backfillers
# ---------------------------------------------------------------------------


def _backfill_agent_folders(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    upsert_sql = text(
        """
        INSERT INTO agent_folders (user_id, name, description)
        VALUES (:user_id, :name, :description)
        ON CONFLICT DO NOTHING
        """
    )
    cursor = mongo_db["agent_folders"].find({}, no_cursor_timeout=True).batch_size(batch_size)
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


def _backfill_sources(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    insert_sql = text(
        """
        INSERT INTO sources (user_id, name, type, metadata)
        VALUES (:user_id, :name, :type, CAST(:metadata AS jsonb))
        ON CONFLICT DO NOTHING
        """
    )
    cursor = mongo_db["sources"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = 0
    batch: list[dict] = []
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
            batch.append({
                "user_id": doc.get("user"),
                "name": doc.get("name", ""),
                "type": doc.get("type"),
                "metadata": json.dumps(clean_meta, default=str),
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


def _backfill_agents(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    insert_sql = text(
        """
        INSERT INTO agents (
            user_id, name, status, key, description, agent_type,
            chunks, retriever, default_model_id,
            tools, json_schema, models,
            limited_token_mode, token_limit, limited_request_mode, request_limit,
            shared, incoming_webhook_token, legacy_mongo_id
        ) VALUES (
            :user_id, :name, :status, :key, :description, :agent_type,
            :chunks, :retriever, :default_model_id,
            CAST(:tools AS jsonb), CAST(:json_schema AS jsonb), CAST(:models AS jsonb),
            :limited_token_mode, :token_limit, :limited_request_mode, :request_limit,
            :shared, :incoming_webhook_token, :legacy_mongo_id
        )
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            name = EXCLUDED.name,
            status = EXCLUDED.status,
            description = EXCLUDED.description,
            agent_type = EXCLUDED.agent_type,
            chunks = EXCLUDED.chunks,
            retriever = EXCLUDED.retriever,
            default_model_id = EXCLUDED.default_model_id,
            tools = EXCLUDED.tools,
            json_schema = EXCLUDED.json_schema,
            models = EXCLUDED.models,
            limited_token_mode = EXCLUDED.limited_token_mode,
            token_limit = EXCLUDED.token_limit,
            limited_request_mode = EXCLUDED.limited_request_mode,
            request_limit = EXCLUDED.request_limit,
            shared = EXCLUDED.shared,
            updated_at = now()
        """
    )
    cursor = mongo_db["agents"].find({}, no_cursor_timeout=True).batch_size(batch_size)
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
                "status": doc.get("status", "draft"),
                # Mongo allows multiple agents with key="" but Postgres
                # CITEXT UNIQUE treats them as a collision. Coerce empty
                # strings to NULL so the unique constraint is only
                # enforced for actual API keys.
                "key": (doc.get("key") or None),
                "description": doc.get("description"),
                "agent_type": doc.get("agent_type"),
                "chunks": doc.get("chunks"),
                "retriever": doc.get("retriever"),
                "default_model_id": doc.get("default_model_id"),
                "tools": json.dumps(doc.get("tools") or []),
                "json_schema": json.dumps(doc.get("json_schema")) if doc.get("json_schema") else None,
                "models": json.dumps(doc.get("models")) if doc.get("models") else None,
                "limited_token_mode": bool(doc.get("limited_token_mode", False)),
                "token_limit": doc.get("token_limit"),
                "limited_request_mode": bool(doc.get("limited_request_mode", False)),
                "request_limit": doc.get("request_limit"),
                "shared": bool(doc.get("shared", False)),
                "incoming_webhook_token": doc.get("incoming_webhook_token"),
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
        INSERT INTO attachments (user_id, filename, upload_path, mime_type, size,
                                 legacy_mongo_id)
        VALUES (:user_id, :filename, :upload_path, :mime_type, :size,
                :legacy_mongo_id)
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            filename = EXCLUDED.filename,
            upload_path = EXCLUDED.upload_path,
            mime_type = EXCLUDED.mime_type,
            size = EXCLUDED.size
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
                "upload_path": doc.get("upload_path", ""),
                "mime_type": doc.get("mime_type"),
                "size": doc.get("size"),
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
    # Already a UUID (36 chars with dashes) — pass through
    if len(s) == 36 and "-" in s:
        return s
    # Mongo ObjectId (24 hex chars) — look up in map
    return tool_id_map.get(s)


def _backfill_memories(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    tool_id_map = _build_tool_id_map(conn, mongo_db)
    insert_sql = text(
        """
        INSERT INTO memories (user_id, tool_id, path, content)
        VALUES (:user_id, CAST(:tool_id AS uuid), :path, :content)
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
            batch.append({
                "user_id": user_id,
                "tool_id": pg_tool_id,
                "path": doc.get("path", "/"),
                "content": doc.get("content", ""),
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


def _backfill_todos(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    tool_id_map = _build_tool_id_map(conn, mongo_db)
    insert_sql = text(
        """
        INSERT INTO todos (user_id, tool_id, title, completed)
        VALUES (:user_id, CAST(:tool_id AS uuid), :title, :completed)
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
            batch.append({
                "user_id": user_id,
                "tool_id": pg_tool_id,
                "title": doc.get("title", ""),
                "completed": status == "completed",
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


def _backfill_notes(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    tool_id_map = _build_tool_id_map(conn, mongo_db)
    insert_sql = text(
        """
        INSERT INTO notes (user_id, tool_id, title, content)
        VALUES (:user_id, CAST(:tool_id AS uuid), :title, :content)
        ON CONFLICT (user_id, tool_id) DO UPDATE
            SET content = EXCLUDED.content, title = EXCLUDED.title
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
            batch.append({
                "user_id": user_id,
                "tool_id": pg_tool_id,
                "title": doc.get("title", "note"),
                "content": doc.get("note") or doc.get("content", ""),
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
        INSERT INTO connector_sessions (user_id, provider, session_data)
        VALUES (:user_id, :provider, CAST(:session_data AS jsonb))
        ON CONFLICT (user_id, provider) DO UPDATE
            SET session_data = EXCLUDED.session_data
        """
    )
    cursor = mongo_db["connector_sessions"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            user_id = doc.get("user_id") or doc.get("user")
            provider = doc.get("provider")
            if not user_id or not provider:
                skipped += 1
                continue
            session_data = {k: v for k, v in doc.items() if k not in ("_id", "user_id", "user", "provider")}
            batch.append({
                "user_id": user_id,
                "provider": provider,
                "session_data": json.dumps(session_data, default=str),
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
                "compression_metadata": json.dumps(comp_meta) if comp_meta else None,
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
                    if len(s) == 36 and "-" in s:
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
                    "sources": json.dumps(q.get("sources") or []),
                    "tool_calls": json.dumps(q.get("tool_calls") or []),
                    "attachments": resolved_attachments,
                    "model_id": q.get("model_id"),
                    "metadata": json.dumps(q.get("metadata") or {}),
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
        INSERT INTO workflows (user_id, name, description, current_graph_version,
                               legacy_mongo_id)
        VALUES (:user_id, :name, :description, :current_graph_version,
                :legacy_mongo_id)
        ON CONFLICT (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL
        DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            current_graph_version = EXCLUDED.current_graph_version,
            updated_at = now()
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
                "position": json.dumps(position),
                "config": json.dumps(doc.get("config") or {}),
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
                "config": json.dumps(doc.get("config") or {}),
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
                "user_id": doc.get("user_id") or doc.get("user") or "",
                "status": doc.get("status", "unknown"),
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
    "attachments": _backfill_attachments,
    "agents": _backfill_agents,
    "memories": _backfill_memories,
    "todos": _backfill_todos,
    "notes": _backfill_notes,
    "connector_sessions": _backfill_connector_sessions,
    # Phase 3 (order: conversations first, then dependents)
    "conversations": _backfill_conversations,
    "shared_conversations": _backfill_shared_conversations,
    "pending_tool_state": _backfill_pending_tool_state,
    "workflows": _backfill_workflows,
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

    mongo = MongoDB.get_client()
    mongo_db = mongo[settings.MONGO_DB_NAME]
    engine = get_engine()

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
