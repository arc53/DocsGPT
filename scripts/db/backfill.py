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
        INSERT INTO prompts (user_id, name, content)
        VALUES (:user_id, :name, :content)
        ON CONFLICT DO NOTHING
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


def _backfill_feedback(
    *, conn: Connection, mongo_db: Any, batch_size: int, dry_run: bool,
) -> dict:
    insert_sql = text(
        """
        INSERT INTO feedback (conversation_id, user_id, question_index, feedback_text, timestamp)
        VALUES (CAST(:conversation_id AS uuid), :user_id, :question_index, :feedback_text, :timestamp)
        ON CONFLICT DO NOTHING
        """
    )
    cursor = mongo_db["feedback"].find({}, no_cursor_timeout=True).batch_size(batch_size)
    seen = written = skipped = 0
    batch: list[dict] = []
    try:
        for doc in cursor:
            seen += 1
            user_id = doc.get("user")
            conv_id = doc.get("conversation_id")
            if not user_id or not conv_id:
                skipped += 1
                continue
            batch.append({
                "conversation_id": str(conv_id),
                "user_id": user_id,
                "question_index": doc.get("question_index", 0),
                "feedback_text": doc.get("feedback_text"),
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
    return {"seen": seen, "written": written, "skipped": skipped}


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
            shared, incoming_webhook_token
        ) VALUES (
            :user_id, :name, :status, :key, :description, :agent_type,
            :chunks, :retriever, :default_model_id,
            CAST(:tools AS jsonb), CAST(:json_schema AS jsonb), CAST(:models AS jsonb),
            :limited_token_mode, :token_limit, :limited_request_mode, :request_limit,
            :shared, :incoming_webhook_token
        )
        ON CONFLICT DO NOTHING
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
                "key": doc.get("key"),
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
        INSERT INTO attachments (user_id, filename, upload_path, mime_type, size)
        VALUES (:user_id, :filename, :upload_path, :mime_type, :size)
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
        ON CONFLICT DO NOTHING
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
    "feedback": _backfill_feedback,
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
