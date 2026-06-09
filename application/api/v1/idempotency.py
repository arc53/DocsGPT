"""Layer-1 idempotency for the OpenAI-compatible ``/v1/chat/completions`` route.

The ``/v1`` tool round-trip is fully stateless (the pause finalizes the prior
turn as ``complete`` and resumes via ``build_continuation_from_messages`` with
no ``pending_tool_state``). Dropping the native ``resume_from_tool_actions``
path also dropped its ``mark_resuming`` guard, so a duplicated/retried POST
could re-run the agent → a duplicate answer row + double token billing.

This module restores protection the OpenAI-compatible way: a client-supplied
``Idempotency-Key`` header makes retries return the *stored first response*
instead of re-running the agent. It is opt-in (no header → today's behavior,
byte-for-byte) and scoped to **non-streaming** requests only (the b2b client
and the actual regression); streaming replay is intentionally unsupported.

Storage reuses the existing ``task_dedup`` table via
:class:`~application.storage.db.repositories.idempotency.IdempotencyRepository`
— no new table or migration. The contract maps onto its claim/finalize
semantics:

- **No record** → ``claim_task`` inserts a ``pending`` row (we run + finalize).
- **``completed`` within 24h TTL** → return the cached body + status code.
- **Fresh ``pending``** (in-flight) → HTTP 409 idempotency conflict.
- **Stale ``pending``** (older than :data:`STALE_PENDING_SECONDS` — the
  original request likely died) → release and re-claim.
- **``failed`` / past-TTL** → ``claim_task`` re-claims automatically.

Only successful (2xx) responses are cached; a 4xx/5xx releases the claim so a
genuine retry can still succeed (matches OpenAI).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional, Tuple

from flask import jsonify, make_response, request, Response
from sqlalchemy import text as sql_text

from application.storage.db.repositories.idempotency import IdempotencyRepository
from application.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

# Distinct ``task_name`` so v1 chat dedup rows never collide with ingest /
# webhook rows that share the ``task_dedup`` table.
TASK_NAME = "v1_chat_completion"

_IDEMPOTENCY_KEY_MAX_LEN = 256

# A ``pending`` claim older than this is treated as a dead in-flight request
# (the process crashed before finalize), so a genuine retry may re-claim it
# rather than waiting out the full 24h TTL or getting a permanent 409. Kept
# short enough to unblock retries quickly, long enough that a normal
# non-streaming completion (which finalizes on the same request) never trips
# it while still running.
STALE_PENDING_SECONDS = 300


def read_idempotency_key() -> Tuple[Optional[str], Optional[Response]]:
    """Read and validate the ``Idempotency-Key`` request header.

    Returns:
        ``(key, error_response)``. An absent/empty header yields
        ``(None, None)`` (idempotency is opt-in). An oversized header yields
        ``(None, <400 response>)`` so the caller can short-circuit.
    """
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None, None
    if len(key) > _IDEMPOTENCY_KEY_MAX_LEN:
        return None, make_response(
            jsonify(
                {
                    "error": {
                        "message": (
                            f"Idempotency-Key exceeds maximum length of "
                            f"{_IDEMPOTENCY_KEY_MAX_LEN} characters"
                        ),
                        "type": "invalid_request",
                    }
                }
            ),
            400,
        )
    return key, None


def scoped_key(idempotency_key: Optional[str], agent_id: Optional[str]) -> Optional[str]:
    """Compose ``{agent_id}:{idempotency_key}`` so tenants never collide.

    Two agents replaying the same key value resolve to distinct stored rows.
    Falls back to ``api_key`` scoping at the call site when no agent id is
    available; returns ``None`` when either component is missing (idempotency
    is then skipped, preserving today's behavior).
    """
    if not idempotency_key or not agent_id:
        return None
    return f"{agent_id}:{idempotency_key}"


def _release_stale_pending(key: str) -> None:
    """Delete a stale ``pending`` claim so the caller can re-claim it.

    Scoped to ``status = 'pending'`` and the staleness window so we never
    clobber a live in-flight claim or a ``completed`` cache row.
    """
    try:
        with db_session() as conn:
            conn.execute(
                sql_text(
                    "DELETE FROM task_dedup "
                    "WHERE idempotency_key = :k "
                    "AND status = 'pending' "
                    "AND created_at <= now() - make_interval(secs => :secs)"
                ),
                {"k": key, "secs": STALE_PENDING_SECONDS},
            )
    except Exception:
        logger.exception("Failed to release stale v1 idempotency claim for key=%s", key)


def claim_or_replay(key: str) -> Tuple[bool, Optional[Response]]:
    """Claim ``key`` for this request, or return the prior outcome.

    Claim-before-process: atomically insert a ``pending`` row. The three
    outcomes map onto the existing ``task_dedup`` contract:

    - **claimed** → ``(True, None)``: this caller runs the agent and must call
      :func:`finalize` (success) or :func:`release` (error) afterwards.
    - **``completed`` within TTL** → ``(False, <cached response>)``: replay the
      stored body + status code without re-running.
    - **fresh ``pending``** → ``(False, <409 response>)``: a same-key request is
      already in progress.

    A ``pending`` row older than :data:`STALE_PENDING_SECONDS` is released and
    re-claimed (the original request likely died). ``failed`` / past-TTL rows
    are re-claimed by ``claim_task`` itself.

    Args:
        key: The tenant-scoped idempotency key.

    Returns:
        ``(claimed, response)``. When ``claimed`` is True the caller owns the
        run; otherwise ``response`` is the replay/409 to return immediately.
    """
    predetermined_id = str(uuid.uuid4())
    with db_session() as conn:
        claimed = IdempotencyRepository(conn).claim_task(
            key=key, task_name=TASK_NAME, task_id=predetermined_id,
        )
    if claimed is not None:
        return True, None

    # Lost the claim — resolve why against the within-TTL row.
    with db_readonly() as conn:
        existing = IdempotencyRepository(conn).get_task(key)

    if existing is not None and existing.get("status") == "completed":
        return False, _replay_response(existing.get("result_json"))

    if existing is not None and existing.get("status") == "pending":
        # In-flight? Re-claim only if the prior claim is stale (dead request).
        _release_stale_pending(key)
        with db_session() as conn:
            reclaimed = IdempotencyRepository(conn).claim_task(
                key=key, task_name=TASK_NAME, task_id=predetermined_id,
            )
        if reclaimed is not None:
            return True, None
        return False, _conflict_response()

    # Row vanished between claim and read (TTL cleanup / release race) — one
    # more claim attempt; treat a persistent loss as a conflict.
    with db_session() as conn:
        reclaimed = IdempotencyRepository(conn).claim_task(
            key=key, task_name=TASK_NAME, task_id=predetermined_id,
        )
    if reclaimed is not None:
        return True, None
    with db_readonly() as conn:
        existing = IdempotencyRepository(conn).get_task(key)
    if existing is not None and existing.get("status") == "completed":
        return False, _replay_response(existing.get("result_json"))
    return False, _conflict_response()


def finalize(key: str, response: Response) -> None:
    """Cache a successful (2xx) response under ``key``; release otherwise.

    Stores ``{"status_code", "body"}`` in ``task_dedup.result_json`` so a
    retry replays byte-for-byte. Non-2xx responses are not cached — the claim
    is released so a genuine retry can still succeed (matches OpenAI).

    Args:
        key: The tenant-scoped idempotency key claimed by :func:`claim_or_replay`.
        response: The Flask response produced by running the request.
    """
    status_code = response.status_code
    if not (200 <= status_code < 300):
        release(key)
        return
    try:
        body = response.get_json(silent=True)
    except Exception:
        body = None
    result_json = {"status_code": status_code, "body": body}
    try:
        with db_session() as conn:
            IdempotencyRepository(conn).finalize_task(
                key=key, result_json=result_json, status="completed",
            )
    except Exception:
        logger.exception("Failed to finalize v1 idempotency record for key=%s", key)


def release(key: str) -> None:
    """Drop this request's ``pending`` claim so a retry can re-claim it.

    Used on the error path (non-2xx or an exception before finalize) so a
    failed first attempt never blocks a legitimate retry for the full TTL.
    """
    try:
        with db_session() as conn:
            conn.execute(
                sql_text(
                    "DELETE FROM task_dedup "
                    "WHERE idempotency_key = :k AND status = 'pending'"
                ),
                {"k": key},
            )
    except Exception:
        logger.exception("Failed to release v1 idempotency claim for key=%s", key)


def _replay_response(result_json: Optional[Dict[str, Any]]) -> Response:
    """Rebuild a Flask response from a cached ``result_json`` row."""
    status_code = 200
    body: Any = None
    if isinstance(result_json, dict):
        status_code = int(result_json.get("status_code", 200))
        body = result_json.get("body")
    return make_response(jsonify(body), status_code)


def _conflict_response() -> Response:
    """OpenAI-shaped 409 for a same-key request already in progress."""
    return make_response(
        jsonify(
            {
                "error": {
                    "message": (
                        "A request with this Idempotency-Key is already in progress"
                    ),
                    "type": "idempotency_conflict",
                }
            }
        ),
        409,
    )
