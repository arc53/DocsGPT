#!/usr/bin/env python3
"""End-to-end verification for the Tier 1 durability work.

Two tiers of coverage:

**Service-layer scenarios (s1-s10)** — exercise the WAL + reconciler +
idempotency + token-usage primitives without spinning up Flask, Celery
workers, or a live LLM:

* Service-level calls (e.g. ``ConversationService.save_user_question``)
  drive the same code paths the routes use.
* Flask ``test_request_context`` lets us hit ``Resource.post()`` directly
  for HTTP idempotency checks.
* The reconciler is invoked synchronously via ``run_reconciliation()``.
* Stuck-row scenarios are simulated by backdating ``timestamp`` /
  ``attempted_at`` columns so the reconciler treats them as past the
  threshold without having to wait the real 5/15 minutes.

**Live scenarios (s11-s13)** — boot the local mock LLM stub from
``scripts/e2e/mock_llm.py`` as a subprocess and drive real network
streams + real Celery workers:

* s11: real OpenAI-protocol stream through WAL + finalize + token_usage.
* s12: full ingest of a synthesised markdown file (chunker + embeddings
  + faiss). The final ``upload_index`` self-call to Flask is patched
  out — everything before that (chunk progress, source id, vector store
  on disk) runs for real.
* s13: ``kill -9`` a Celery worker subprocess mid-task; verify
  ``acks_late`` + ``visibility_timeout`` make the broker redeliver to a
  fresh worker. Uses isolated Redis DBs (11/12) and a unique queue so
  it can't interfere with production work on the same broker.

Usage::

    .venv/bin/python scripts/qa/durability_e2e.py
    .venv/bin/python scripts/qa/durability_e2e.py --list
    .venv/bin/python scripts/qa/durability_e2e.py --only s1,s5
    .venv/bin/python scripts/qa/durability_e2e.py --only s11,s12,s13
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Bootstrap: import application/* and connect to the configured Postgres.
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Suppress AUTO_MIGRATE / AUTO_CREATE_DB side-effects from app boot — this
# script only reads/writes data, the schema is assumed to be at head.
os.environ.setdefault("AUTO_MIGRATE", "false")
os.environ.setdefault("AUTO_CREATE_DB", "false")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from sqlalchemy import create_engine, text  # noqa: E402

POSTGRES_URI = os.environ.get("POSTGRES_URI", "")
if not POSTGRES_URI:
    print("POSTGRES_URI not set; cannot run E2E checks.", file=sys.stderr)
    sys.exit(2)
if POSTGRES_URI.startswith("postgresql://"):
    POSTGRES_URI = POSTGRES_URI.replace("postgresql://", "postgresql+psycopg://", 1)

ENGINE = create_engine(POSTGRES_URI, pool_pre_ping=True)
UNIQUE = f"qa_e2e_{int(time.time())}_{uuid.uuid4().hex[:6]}"


# Quiet noisy library loggers so the script's own output stays readable.
for name in (
    "application", "application.api", "application.storage",
    "application.usage", "application.parser",
    "application.api.user.reconciliation",
):
    logging.getLogger(name).setLevel(logging.ERROR)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def header(msg: str) -> None:
    print(f"\n{'=' * 72}\n{msg}\n{'=' * 72}")


def step(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {DIM}· {msg}{RESET}")


def fail(msg: str) -> None:
    print(f"  {RED}✗ {msg}{RESET}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}! {msg}{RESET}")


# ---------------------------------------------------------------------------
# Patch helpers — reroute service module-level db_session/db_readonly to
# OUR engine so all writes land on the same Postgres the script is observing.
# ---------------------------------------------------------------------------


@contextmanager
def patch_db_session(*module_paths: str):
    """Reroute ``db_session`` / ``db_readonly`` (whichever each module
    actually imports) at our engine. Modules that import only one of the
    two are handled gracefully — patches are skipped for missing attrs.
    """
    import importlib

    @contextmanager
    def _ses():
        with ENGINE.begin() as conn:
            yield conn

    @contextmanager
    def _ro():
        with ENGINE.connect() as conn:
            yield conn

    patches = []
    for module in module_paths:
        mod = importlib.import_module(module)
        if hasattr(mod, "db_session"):
            patches.append(patch(f"{module}.db_session", _ses))
        if hasattr(mod, "db_readonly"):
            patches.append(patch(f"{module}.db_readonly", _ro))
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# Cleanup helper — run after each scenario regardless of pass/fail.
# ---------------------------------------------------------------------------


def cleanup_artifacts(prefix: str = UNIQUE) -> None:
    with ENGINE.begin() as c:
        c.execute(
            text(
                "DELETE FROM stack_logs "
                "WHERE query LIKE 'reconciler_%' "
                "AND timestamp > now() - interval '15 minutes' "
                "AND (user_id LIKE :p OR query LIKE :p)"
            ),
            {"p": f"%{prefix}%"},
        )
        c.execute(
            text(
                "DELETE FROM tool_call_attempts WHERE call_id LIKE :p"
            ),
            {"p": f"{prefix}-%"},
        )
        c.execute(
            text(
                "DELETE FROM conversation_messages WHERE conversation_id IN ("
                "  SELECT id FROM conversations WHERE user_id LIKE :p"
                ")"
            ),
            {"p": f"{prefix}-%"},
        )
        c.execute(
            text(
                "DELETE FROM pending_tool_state WHERE user_id LIKE :p"
            ),
            {"p": f"{prefix}-%"},
        )
        c.execute(
            text(
                "DELETE FROM conversations WHERE user_id LIKE :p"
            ),
            {"p": f"{prefix}-%"},
        )
        c.execute(
            text(
                "DELETE FROM token_usage WHERE user_id LIKE :p"
            ),
            {"p": f"{prefix}-%"},
        )
        c.execute(
            text(
                "DELETE FROM webhook_dedup WHERE idempotency_key LIKE :p"
            ),
            {"p": f"%:{prefix}-%"},
        )
        c.execute(
            text(
                "DELETE FROM task_dedup WHERE idempotency_key LIKE :p"
            ),
            {"p": f"%:{prefix}-%"},
        )
        c.execute(
            text(
                "DELETE FROM ingest_chunk_progress WHERE source_id IN ("
                "  SELECT id FROM sources WHERE name LIKE :p"
                ")"
            ),
            {"p": f"{prefix}-%"},
        )
        c.execute(
            text(
                "DELETE FROM agents WHERE name LIKE :p"
            ),
            {"p": f"{prefix}-%"},
        )
        c.execute(
            text(
                "DELETE FROM prompts WHERE user_id LIKE :p"
            ),
            {"p": f"{prefix}-%"},
        )
        c.execute(
            text(
                "DELETE FROM users WHERE user_id LIKE :p"
            ),
            {"p": f"{prefix}-%"},
        )


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def s1_wal_and_reconciler() -> None:
    """WAL placeholder is reserved before LLM call; reconciler escalates
    a stuck pending row to ``failed`` after 3 attempts and emits a
    structured alert."""

    from application.api.answer.services.conversation_service import (
        ConversationService,
        TERMINATED_RESPONSE_PLACEHOLDER,
    )
    from application.api.user.reconciliation import run_reconciliation

    user = f"{UNIQUE}-s1"
    with ENGINE.begin() as c:
        c.execute(
            text("INSERT INTO users (user_id) VALUES (:u) ON CONFLICT DO NOTHING"),
            {"u": user},
        )

    with patch_db_session("application.api.answer.services.conversation_service"):
        res = ConversationService().save_user_question(
            conversation_id=None,
            question=f"{UNIQUE} s1 stuck WAL",
            decoded_token={"sub": user},
        )
    mid, cid = res["message_id"], res["conversation_id"]
    info(f"reserved message_id={mid} conv={cid}")

    with ENGINE.connect() as c:
        row = c.execute(
            text(
                "SELECT status, response FROM conversation_messages "
                "WHERE id = CAST(:m AS uuid)"
            ),
            {"m": mid},
        ).fetchone()
    assert row[0] == "pending", f"expected pending, got {row[0]!r}"
    assert row[1] == TERMINATED_RESPONSE_PLACEHOLDER, (
        f"placeholder text mismatch: {row[1]!r}"
    )
    step("placeholder reserved with status='pending' + terminated text")

    # Backdate timestamp so the reconciler sweep treats it as stuck.
    with ENGINE.begin() as c:
        c.execute(
            text(
                "UPDATE conversation_messages "
                "SET timestamp = now() - interval '6 minutes' "
                "WHERE id = CAST(:m AS uuid)"
            ),
            {"m": mid},
        )

    # Reconciler MAX_MESSAGE_RECONCILE_ATTEMPTS = 3 → 3 ticks to escalate.
    for i in range(3):
        summary = run_reconciliation()
        info(f"tick {i + 1}: {summary}")

    with ENGINE.connect() as c:
        row = c.execute(
            text(
                "SELECT status, message_metadata->>'reconcile_attempts', "
                "message_metadata->>'error' FROM conversation_messages "
                "WHERE id = CAST(:m AS uuid)"
            ),
            {"m": mid},
        ).fetchone()
    assert row[0] == "failed", f"expected failed, got {row[0]!r}"
    assert int(row[1] or 0) >= 3, f"expected attempts>=3, got {row[1]!r}"
    assert row[2] and "reconciler" in row[2], f"missing reconciler error text: {row[2]!r}"
    step(
        f"reconciler escalated to status='failed' "
        f"after attempts={row[1]} (error: {row[2][:60]}…)"
    )

    with ENGINE.connect() as c:
        alerts = c.execute(
            text(
                "SELECT count(*) FROM stack_logs "
                "WHERE query = 'reconciler_message_failed' "
                "AND timestamp > now() - interval '10 minutes'"
            ),
        ).scalar()
    assert alerts >= 1, f"expected stack_logs alert; got {alerts}"
    step(f"alert written to stack_logs (count={alerts})")


def s2_webhook_idempotency_and_scoping() -> None:
    """Webhook double-POST returns the same task_id; concurrent same-key
    POSTs only enqueue once; two agents sharing a raw key each get their
    own dedup row (cross-tenant scoping)."""

    from flask import Flask

    from application.api.user.agents.webhooks import AgentWebhookListener
    from application.storage.db.repositories.agents import AgentsRepository

    user_a = f"{UNIQUE}-s2a"
    user_b = f"{UNIQUE}-s2b"
    with ENGINE.begin() as c:
        for u in (user_a, user_b):
            c.execute(
                text("INSERT INTO users (user_id) VALUES (:u) ON CONFLICT DO NOTHING"),
                {"u": u},
            )
        agent_a = AgentsRepository(c).create(
            user_a, f"{UNIQUE}-s2-a", "published",
            incoming_webhook_token=f"{UNIQUE}-tok-a",
        )
        agent_b = AgentsRepository(c).create(
            user_b, f"{UNIQUE}-s2-b", "published",
            incoming_webhook_token=f"{UNIQUE}-tok-b",
        )
    info(f"seeded agents a={agent_a['id']} b={agent_b['id']}")

    app = Flask(__name__)

    apply_calls: list[dict] = []

    def _apply_async_side_effect(*_a, **kw):
        apply_calls.append(kw)
        return MagicMock(id=kw.get("task_id") or "auto")

    apply_mock = MagicMock(side_effect=_apply_async_side_effect)

    raw_key = f"{UNIQUE}-key-1"

    # Sequential dedup: same key twice → same task_id, single apply_async call.
    with patch_db_session("application.api.user.agents.webhooks"), patch(
        "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
        apply_mock,
    ):
        for _ in range(2):
            with app.test_request_context(
                f"/api/webhooks/agents/{agent_a['incoming_webhook_token']}",
                method="POST",
                json={"event": "x"},
                headers={"Idempotency-Key": raw_key},
            ):
                listener = AgentWebhookListener()
                resp = listener.post(
                    webhook_token=agent_a["incoming_webhook_token"],
                    agent=agent_a,
                    agent_id_str=str(agent_a["id"]),
                )
                assert resp.status_code == 200
        last_seq = resp.json["task_id"]
    assert apply_mock.call_count == 1, (
        f"sequential same-key: expected 1 apply_async, got {apply_mock.call_count}"
    )
    step(f"sequential same-key dedup: 1 apply_async, task_id={last_seq}")

    # Cross-agent same key — must NOT collide. Two distinct apply_async calls.
    apply_mock.reset_mock()
    apply_calls.clear()
    cross_key = f"{UNIQUE}-cross"
    with patch_db_session("application.api.user.agents.webhooks"), patch(
        "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
        apply_mock,
    ):
        for ag in (agent_a, agent_b):
            with app.test_request_context(
                f"/api/webhooks/agents/{ag['incoming_webhook_token']}",
                method="POST",
                json={"event": "x"},
                headers={"Idempotency-Key": cross_key},
            ):
                listener = AgentWebhookListener()
                resp = listener.post(
                    webhook_token=ag["incoming_webhook_token"],
                    agent=ag,
                    agent_id_str=str(ag["id"]),
                )
                assert resp.status_code == 200
    assert apply_mock.call_count == 2, (
        f"cross-agent same-key should NOT collide; got {apply_mock.call_count}"
    )
    with ENGINE.connect() as c:
        rows = c.execute(
            text(
                "SELECT idempotency_key, agent_id FROM webhook_dedup "
                "WHERE idempotency_key LIKE :p ORDER BY idempotency_key"
            ),
            {"p": f"%:{cross_key}"},
        ).fetchall()
    assert len(rows) == 2, f"expected 2 scoped dedup rows; got {len(rows)}"
    scopes = {str(r[1]) for r in rows}
    assert scopes == {str(agent_a["id"]), str(agent_b["id"])}, (
        f"scopes mismatch: {scopes}"
    )
    step(
        f"cross-agent same key did NOT collide; rows={[r[0] for r in rows]}"
    )


def s3_ingest_deterministic_and_resume() -> None:
    """Deterministic source_id is stable; chunk-progress checkpoint
    resumes from the next un-embedded chunk."""

    from application.parser.embedding_pipeline import _read_resume_index
    from application.storage.db.repositories.ingest_chunk_progress import (
        IngestChunkProgressRepository,
    )
    from application.worker import _derive_source_id

    # Same scoped key → same uuid5; different scope → different uuid5.
    a = _derive_source_id("alice:UPLOAD-1")
    b = _derive_source_id("alice:UPLOAD-1")
    c = _derive_source_id("bob:UPLOAD-1")
    assert a == b, f"deterministic mismatch: {a} vs {b}"
    assert a != c, f"cross-user collision: {a} vs {c}"
    step(f"_derive_source_id: stable for same key, distinct across scopes ({a}, {c})")

    # No key → uuid4 (random per call).
    r1 = _derive_source_id(None)
    r2 = _derive_source_id(None)
    assert r1 != r2, "uuid4 fallback should differ across calls"
    step("uuid4 fallback when no key supplied")

    # Checkpoint primitive: seed progress, observe resume index.
    src_id = uuid.uuid4()
    with patch_db_session("application.parser.embedding_pipeline"):
        with ENGINE.begin() as conn:
            repo = IngestChunkProgressRepository(conn)
            repo.init_progress(str(src_id), total_chunks=10)
            repo.record_chunk(str(src_id), last_index=3, embedded_chunks=4)
        idx = _read_resume_index(str(src_id))
    assert idx == 4, f"expected resume index=4 (next un-embedded); got {idx}"
    step(f"chunk-progress resume index correctly skips already-embedded ({idx}/10)")

    # Cleanup
    with ENGINE.begin() as conn:
        conn.execute(
            text("DELETE FROM ingest_chunk_progress WHERE source_id = CAST(:s AS uuid)"),
            {"s": str(src_id)},
        )


def s4_token_usage_atomic_rollback() -> None:
    """Patch ``update_message_by_id`` to raise after the token_usage
    insert; the surrounding transaction must roll back so no orphan
    token_usage row survives."""

    from application.api.answer.services.conversation_service import (
        ConversationService,
    )
    from application.storage.db.repositories import conversations as conv_mod
    from application.storage.db.repositories.conversations import (
        ConversationsRepository,
    )

    user = f"{UNIQUE}-s4"
    with ENGINE.begin() as c:
        c.execute(
            text("INSERT INTO users (user_id) VALUES (:u) ON CONFLICT DO NOTHING"),
            {"u": user},
        )
        repo = ConversationsRepository(c)
        conv = repo.create(user, f"{UNIQUE}-s4-conv")
        msg = repo.reserve_message(
            str(conv["id"]),
            prompt="q?",
            placeholder_response="...",
            request_id="r1",
            status="streaming",
        )
        mid = str(msg["id"])
    info(f"seeded message_id={mid}")

    original = conv_mod.ConversationsRepository.update_message_by_id

    def explode(self, *_a, **_kw):  # noqa: ANN001
        raise RuntimeError("intentional fault")

    try:
        conv_mod.ConversationsRepository.update_message_by_id = explode
        with patch_db_session(
            "application.api.answer.services.conversation_service",
        ), suppress_logging("application.api.answer.services.conversation_service"):
            try:
                ConversationService().finalize_message(
                    mid,
                    "answer",
                    status="complete",
                    token_usage={"prompt_tokens": 100, "generated_tokens": 50},
                    decoded_token={"sub": user},
                )
            except RuntimeError as exc:
                assert "intentional fault" in str(exc)
            else:
                raise AssertionError("expected RuntimeError to propagate")
    finally:
        conv_mod.ConversationsRepository.update_message_by_id = original

    with ENGINE.connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM token_usage WHERE user_id = :u"),
            {"u": user},
        ).scalar()
    assert n == 0, f"expected 0 token_usage rows after rollback; got {n}"
    step("rollback held: 0 token_usage rows for failed finalize")


@contextmanager
def suppress_logging(*names: str):
    saved = []
    for n in names:
        lg = logging.getLogger(n)
        saved.append((lg, lg.disabled, lg.level))
        lg.disabled = True
    try:
        yield
    finally:
        for lg, was_disabled, was_level in saved:
            lg.disabled = was_disabled
            lg.level = was_level


def s5_reconciler_tool_call_sweeps() -> None:
    """Seed stuck tool_call_attempts rows of each kind; the reconciler
    flips proposed→failed and executed→failed (or compensated when the
    tool exposes a working compensate)."""

    from application.api.user.reconciliation import run_reconciliation

    user = f"{UNIQUE}-s5"
    with ENGINE.begin() as c:
        c.execute(
            text("INSERT INTO users (user_id) VALUES (:u) ON CONFLICT DO NOTHING"),
            {"u": user},
        )

    proposed_id = f"{UNIQUE}-prop-{uuid.uuid4().hex[:6]}"
    executed_id = f"{UNIQUE}-exec-{uuid.uuid4().hex[:6]}"

    with ENGINE.begin() as c:
        c.execute(text("ALTER TABLE tool_call_attempts DISABLE TRIGGER USER"))
        try:
            c.execute(
                text(
                    "INSERT INTO tool_call_attempts "
                    "(call_id, tool_name, action_name, arguments, status, "
                    " attempted_at, updated_at) "
                    "VALUES (:c, 'telegram', 'send_message', '{}'::jsonb, "
                    " 'proposed', now() - interval '6 minutes', "
                    " now() - interval '6 minutes')"
                ),
                {"c": proposed_id},
            )
            c.execute(
                text(
                    "INSERT INTO tool_call_attempts "
                    "(call_id, tool_name, action_name, arguments, status, "
                    " attempted_at, updated_at) "
                    "VALUES (:c, 'telegram', 'send_message', '{}'::jsonb, "
                    " 'executed', now() - interval '20 minutes', "
                    " now() - interval '20 minutes')"
                ),
                {"c": executed_id},
            )
        finally:
            c.execute(text("ALTER TABLE tool_call_attempts ENABLE TRIGGER USER"))
    info(f"seeded proposed={proposed_id} executed={executed_id}")

    summary = run_reconciliation()
    info(f"reconciler summary: {summary}")
    assert summary["tool_calls_failed"] >= 2, (
        f"expected ≥2 tool_calls_failed; got {summary}"
    )

    with ENGINE.connect() as c:
        rows = c.execute(
            text(
                "SELECT call_id, status, error FROM tool_call_attempts "
                "WHERE call_id IN (:p, :e)"
            ),
            {"p": proposed_id, "e": executed_id},
        ).fetchall()
    by_id = {r[0]: r for r in rows}
    assert by_id[proposed_id][1] == "failed"
    assert "proposed" in by_id[proposed_id][2]
    assert by_id[executed_id][1] == "failed"
    assert "executed-not-confirmed" in by_id[executed_id][2]
    step("proposed→failed and executed→failed with descriptive error text")

    with ENGINE.connect() as c:
        n = c.execute(
            text(
                "SELECT count(*) FROM stack_logs "
                "WHERE query IN ('reconciler_tool_call_failed_proposed', "
                "'reconciler_tool_call_failed_executed') "
                "AND timestamp > now() - interval '5 minutes'"
            ),
        ).scalar()
    assert n >= 2, f"expected ≥2 reconciler tool-call alerts; got {n}"
    step(f"alerts written to stack_logs (count={n})")


def s6_resume_janitor() -> None:
    """A pending_tool_state row in ``status='resuming'`` whose
    ``resumed_at`` is older than the 10-min grace window is reverted to
    ``status='pending'`` by the cleanup janitor."""


    user = f"{UNIQUE}-s6"
    with ENGINE.begin() as c:
        c.execute(
            text("INSERT INTO users (user_id) VALUES (:u) ON CONFLICT DO NOTHING"),
            {"u": user},
        )
        conv = c.execute(
            text(
                "INSERT INTO conversations (user_id, name) VALUES (:u, :n) "
                "RETURNING id"
            ),
            {"u": user, "n": f"{UNIQUE}-s6"},
        ).fetchone()
        cid = str(conv[0])
        c.execute(
            text(
                "INSERT INTO pending_tool_state "
                "(conversation_id, user_id, messages, pending_tool_calls, "
                " tools_dict, tool_schemas, agent_config, "
                " created_at, expires_at, status, resumed_at) "
                "VALUES (CAST(:c AS uuid), :u, '[]'::jsonb, '[]'::jsonb, "
                " '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, "
                " now(), now() + interval '30 minutes', "
                " 'resuming', now() - interval '11 minutes')"
            ),
            {"c": cid, "u": user},
        )
    info(f"seeded pending_tool_state in 'resuming' (resumed_at=-11m) for conv={cid}")

    from application.api.user.tasks import cleanup_pending_tool_state

    res = cleanup_pending_tool_state.run()
    info(f"janitor result: {res}")
    assert res["reverted"] >= 1, f"expected reverted>=1; got {res}"

    with ENGINE.connect() as c:
        row = c.execute(
            text(
                "SELECT status, resumed_at FROM pending_tool_state "
                "WHERE conversation_id = CAST(:c AS uuid) AND user_id = :u"
            ),
            {"c": cid, "u": user},
        ).fetchone()
    assert row[0] == "pending", f"expected status=pending after revert; got {row[0]!r}"
    assert row[1] is None, f"expected resumed_at=NULL after revert; got {row[1]!r}"
    step("janitor reverted stale 'resuming' → 'pending' and cleared resumed_at")


def s7_token_usage_attribution() -> None:
    """``finalize_message`` reads from ``agent.llm.token_usage`` (the LLM
    the stream actually mutated); side-channel LLMs marked with
    ``_persist_token_usage_inline`` self-write a row; the canary fires
    when ``status='complete'`` arrives with zero counts."""

    from application.api.answer.services.conversation_service import (
        ConversationService,
    )
    from application.storage.db.repositories.conversations import (
        ConversationsRepository,
    )
    from application.usage import _maybe_persist_inline

    user = f"{UNIQUE}-s7"
    with ENGINE.begin() as c:
        c.execute(
            text("INSERT INTO users (user_id) VALUES (:u) ON CONFLICT DO NOTHING"),
            {"u": user},
        )
        repo = ConversationsRepository(c)
        conv = repo.create(user, f"{UNIQUE}-s7-conv")
        msg = repo.reserve_message(
            str(conv["id"]),
            prompt="q?",
            placeholder_response="...",
            request_id="r1",
            status="streaming",
        )
        mid_real = str(msg["id"])

        msg2 = repo.reserve_message(
            str(conv["id"]),
            prompt="q?",
            placeholder_response="...",
            request_id="r2",
            status="streaming",
        )
        mid_zero = str(msg2["id"])

    # 1. Real counts → row written, source='agent_stream'.
    with patch_db_session("application.api.answer.services.conversation_service"):
        ok = ConversationService().finalize_message(
            mid_real,
            "answer",
            status="complete",
            token_usage={"prompt_tokens": 3000, "generated_tokens": 800},
            decoded_token={"sub": user},
        )
    assert ok, "finalize_message returned False"

    with ENGINE.connect() as c:
        row = c.execute(
            text(
                "SELECT prompt_tokens, generated_tokens, source "
                "FROM token_usage WHERE user_id = :u "
                "ORDER BY timestamp DESC LIMIT 1"
            ),
            {"u": user},
        ).fetchone()
    assert row == (3000, 800, "agent_stream"), f"row mismatch: {row}"
    step(f"primary stream row written: {row}")

    # 2. Zero-count complete fires the canary alert.
    canary_logger = logging.getLogger(
        "application.api.answer.services.conversation_service"
    )
    seen: list[logging.LogRecord] = []

    class _Catch(logging.Handler):
        def emit(self, record):
            seen.append(record)

    handler = _Catch(level=logging.WARNING)
    canary_logger.addHandler(handler)
    prior_disabled = canary_logger.disabled
    prior_level = canary_logger.level
    canary_logger.disabled = False
    canary_logger.setLevel(logging.WARNING)
    try:
        with patch_db_session(
            "application.api.answer.services.conversation_service",
        ):
            ConversationService().finalize_message(
                mid_zero,
                "answer",
                status="complete",
                token_usage={"prompt_tokens": 0, "generated_tokens": 0},
                decoded_token={"sub": user},
            )
    finally:
        canary_logger.removeHandler(handler)
        canary_logger.disabled = prior_disabled
        canary_logger.setLevel(prior_level)

    assert any(
        getattr(r, "alert", None) == "token_usage_zero_on_complete" for r in seen
    ), (
        "expected structured warning with alert=token_usage_zero_on_complete; "
        f"saw alerts={[getattr(r, 'alert', None) for r in seen]}"
    )
    step("canary fired on zero-count 'complete' finalize")

    # 3. Side-channel inline persist via _maybe_persist_inline.
    class _SideLLM:
        decoded_token = {"sub": user}
        user_api_key = None
        agent_id = None
        _persist_token_usage_inline = True
        _token_usage_source = "compression"

    with patch_db_session("application.usage"):
        _maybe_persist_inline(
            _SideLLM(),
            {"prompt_tokens": 250, "generated_tokens": 80},
        )
    with ENGINE.connect() as c:
        side = c.execute(
            text(
                "SELECT prompt_tokens, generated_tokens, source "
                "FROM token_usage WHERE user_id = :u AND source = 'compression'"
            ),
            {"u": user},
        ).fetchone()
    assert side == (250, 80, "compression"), f"side-channel row mismatch: {side}"
    step(f"side-channel inline persist row written: {side}")


def s8_regenerate_replaces() -> None:
    """``save_user_question(index=N)`` truncates messages at and after
    position N before reserving the placeholder, so the new row lands at
    position=N (replacing the old) rather than appending at the end."""

    from application.api.answer.services.conversation_service import (
        ConversationService,
    )
    from application.storage.db.repositories.conversations import (
        ConversationsRepository,
    )

    user = f"{UNIQUE}-s8"
    with ENGINE.begin() as c:
        c.execute(
            text("INSERT INTO users (user_id) VALUES (:u) ON CONFLICT DO NOTHING"),
            {"u": user},
        )
        repo = ConversationsRepository(c)
        conv = repo.create(user, f"{UNIQUE}-s8-conv")
        cid = str(conv["id"])
        for i in range(5):
            repo.append_message(
                cid,
                {
                    "prompt": f"q{i}",
                    "response": f"a{i}",
                    "thought": "",
                    "sources": [],
                    "tool_calls": [],
                    "metadata": {},
                },
            )
        before = [m["position"] for m in repo.get_messages(cid)]
    assert before == [0, 1, 2, 3, 4], f"seed wrong: {before}"
    info(f"seeded conv={cid} positions={before}")

    with patch_db_session("application.api.answer.services.conversation_service"):
        result = ConversationService().save_user_question(
            conversation_id=cid,
            question=f"{UNIQUE}-regen",
            decoded_token={"sub": user},
            index=3,
        )
    info(f"regenerated at index=3 → message_id={result['message_id']}")

    with ENGINE.connect() as c:
        repo = ConversationsRepository(c)
        msgs = repo.get_messages(cid)
    positions = [m["position"] for m in msgs]
    assert positions == [0, 1, 2, 3], f"expected [0,1,2,3]; got {positions}"
    regen = next(m for m in msgs if m["position"] == 3)
    assert regen["prompt"] == f"{UNIQUE}-regen", f"prompt mismatch: {regen['prompt']!r}"
    assert regen["status"] == "pending", f"status mismatch: {regen['status']!r}"
    assert not any(m["response"] == "a3" for m in msgs), "old answer at index=3 not gone"
    assert not any(m["prompt"] == "q4" for m in msgs), "tail not truncated"
    step(f"regenerate replaced position 3 and truncated tail (positions={positions})")


def s9_idempotency_concurrent_claim() -> None:
    """N concurrent ``claim_task`` calls against the same scoped key:
    exactly one writer wins (returns a row), the rest get None.
    Confirms the ON CONFLICT DO NOTHING race semantics for the HTTP
    claim-first pattern."""

    from application.storage.db.repositories.idempotency import (
        IdempotencyRepository,
    )

    key = f"alice:{UNIQUE}-claim-race"
    n = 20

    def attempt(_idx: int) -> bool:
        # Each thread checks out its own engine connection so we don't
        # serialize at the SQLAlchemy Connection layer.
        with ENGINE.begin() as conn:
            row = IdempotencyRepository(conn).claim_task(
                key=key, task_name="ingest", task_id=f"task-{_idx}",
            )
        return row is not None

    with ThreadPoolExecutor(max_workers=n) as ex:
        winners = sum(1 for r in ex.map(attempt, range(n)) if r)

    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("SELECT count(*) FROM task_dedup WHERE idempotency_key = :k"),
            {"k": key},
        ).scalar()
    assert winners == 1, f"expected exactly 1 winner; got {winners}"
    assert rows == 1, f"expected exactly 1 dedup row; got {rows}"
    step(f"{n} concurrent claim_task → 1 winner, 1 row")

    with ENGINE.begin() as conn:
        conn.execute(
            text("DELETE FROM task_dedup WHERE idempotency_key = :k"),
            {"k": key},
        )


# ---------------------------------------------------------------------------
# Live-LLM scenarios: bootstrap helpers
# ---------------------------------------------------------------------------

import shutil  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
from typing import Optional  # noqa: E402


MOCK_LLM_HOST = "127.0.0.1"
MOCK_LLM_PORT = 7899
MOCK_LLM_BASE_URL = f"http://{MOCK_LLM_HOST}:{MOCK_LLM_PORT}/v1"


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for(predicate, timeout_s: float = 15.0, interval_s: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


class MockLLMService:
    """Owns a subprocess running ``scripts/e2e/mock_llm.py``. Idempotent —
    if the port is already open, treats that as "already running" and
    skips bootstrap (so a developer can run their own ``up.sh`` and have
    this script reuse it)."""

    def __init__(
        self,
        *,
        chunk_delay_ms: int = 0,
        total_delay_ms: int = 0,
    ) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._reused_existing = False
        self._chunk_delay_ms = chunk_delay_ms
        self._total_delay_ms = total_delay_ms
        self._log_path = (
            ROOT / ".e2e-tmp" / "logs" / f"mock-llm-{UNIQUE}.log"
        )

    def start(self) -> None:
        if _port_open(MOCK_LLM_HOST, MOCK_LLM_PORT):
            info(f"mock LLM already running at {MOCK_LLM_BASE_URL} — reusing")
            self._reused_existing = True
            return
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["MOCK_LLM_HOST"] = MOCK_LLM_HOST
        env["MOCK_LLM_PORT"] = str(MOCK_LLM_PORT)
        if self._chunk_delay_ms:
            env["MOCK_LLM_FORCE_STREAM_CHUNK_DELAY_MS"] = str(self._chunk_delay_ms)
        if self._total_delay_ms:
            env["MOCK_LLM_FORCE_TOTAL_DELAY_MS"] = str(self._total_delay_ms)
        env["PYTHONUNBUFFERED"] = "1"
        self._proc = subprocess.Popen(  # noqa: S603
            [sys.executable, str(ROOT / "scripts" / "e2e" / "mock_llm.py")],
            stdout=open(self._log_path, "w"),
            stderr=subprocess.STDOUT,
            env=env,
        )
        if not _wait_for(
            lambda: _port_open(MOCK_LLM_HOST, MOCK_LLM_PORT), timeout_s=10
        ):
            raise RuntimeError(
                f"mock LLM did not open port {MOCK_LLM_PORT} within 10s; "
                f"see {self._log_path}"
            )
        info(f"mock LLM started (pid={self._proc.pid}); log: {self._log_path}")

    def stop(self) -> None:
        if self._proc is None or self._reused_existing:
            return
        try:
            self._proc.send_signal(signal.SIGTERM)
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=2)
        finally:
            self._proc = None


def _build_openai_llm():
    """Construct an OpenAI-provider LLM pointing at the mock LLM. Skips
    the BYOM resolution path that LLMCreator usually goes through, since
    we just want a direct openai-client wrapper for the mock."""
    from application.llm.openai import OpenAILLM

    return OpenAILLM(
        api_key="mock-key",
        user_api_key=None,
        base_url=MOCK_LLM_BASE_URL,
        model_id="gpt-4o-mini",
    )


# ---------------------------------------------------------------------------
# s11: live LLM stream end-to-end
# ---------------------------------------------------------------------------


def s11_live_llm_stream_through_wal() -> None:
    """Reserve a WAL placeholder, drive a real OpenAI-protocol stream
    against the mock LLM, then ``finalize_message`` with the resulting
    ``llm.token_usage``. Verifies:

    * The OpenAI client + ``stream_token_usage`` decorator accumulate
      non-zero counts on the LLM instance during a real network stream.
    * ``finalize_message`` writes a ``token_usage`` row with
      ``source='agent_stream'`` and the recorded counts.
    * The conversation message is left at ``status='complete'`` with the
      streamed response captured.
    """

    from application.api.answer.services.conversation_service import (
        ConversationService,
    )

    user = f"{UNIQUE}-s11"
    with ENGINE.begin() as c:
        c.execute(
            text("INSERT INTO users (user_id) VALUES (:u) ON CONFLICT DO NOTHING"),
            {"u": user},
        )

    with patch_db_session("application.api.answer.services.conversation_service"):
        res = ConversationService().save_user_question(
            conversation_id=None,
            question=f"{UNIQUE} say hello",
            decoded_token={"sub": user},
        )
    mid = res["message_id"]
    info(f"reserved message_id={mid}")

    llm = _build_openai_llm()
    chunks = list(
        llm.gen_stream(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": f"{UNIQUE} say hello"},
            ],
            stream=True,
            tools=None,
        )
    )
    response_text = "".join(c for c in chunks if isinstance(c, str))
    assert response_text, f"no streamed content received; chunks={chunks!r}"
    assert llm.token_usage["prompt_tokens"] > 0, (
        f"expected prompt_tokens > 0; got {llm.token_usage}"
    )
    assert llm.token_usage["generated_tokens"] > 0, (
        f"expected generated_tokens > 0; got {llm.token_usage}"
    )
    step(
        f"streamed {len(chunks)} chunks; tokens={llm.token_usage}; "
        f"response[:40]={response_text[:40]!r}"
    )

    with patch_db_session("application.api.answer.services.conversation_service"):
        ok = ConversationService().finalize_message(
            mid,
            response_text,
            status="complete",
            token_usage=llm.token_usage,
            decoded_token={"sub": user},
        )
    assert ok, "finalize_message returned False"

    with ENGINE.connect() as c:
        msg_row = c.execute(
            text(
                "SELECT status, response FROM conversation_messages "
                "WHERE id = CAST(:m AS uuid)"
            ),
            {"m": mid},
        ).fetchone()
    assert msg_row[0] == "complete", f"expected complete; got {msg_row[0]!r}"
    assert msg_row[1] == response_text, "response mismatch"
    step("WAL row finalised at status='complete' with the streamed text")

    with ENGINE.connect() as c:
        usage = c.execute(
            text(
                "SELECT prompt_tokens, generated_tokens, source "
                "FROM token_usage WHERE user_id = :u "
                "ORDER BY timestamp DESC LIMIT 1"
            ),
            {"u": user},
        ).fetchone()
    assert usage is not None, "no token_usage row written"
    assert usage[0] == llm.token_usage["prompt_tokens"], (
        f"prompt mismatch: row={usage[0]} llm={llm.token_usage['prompt_tokens']}"
    )
    assert usage[1] == llm.token_usage["generated_tokens"], (
        f"generated mismatch: row={usage[1]} llm={llm.token_usage['generated_tokens']}"
    )
    assert usage[2] == "agent_stream", f"source mismatch: {usage[2]!r}"
    step(f"token_usage row written: {usage}")


# ---------------------------------------------------------------------------
# s12: full embedding loop with a mock markdown document
# ---------------------------------------------------------------------------


def s12_full_embedding_loop() -> None:
    """Drive ``ingest_worker`` end-to-end against a tiny markdown file:
    chunker runs, the mock LLM answers each ``/v1/embeddings`` call,
    chunks land in a faiss index, and the row in ``ingest_chunk_progress``
    reflects ``embedded_chunks == total_chunks``.

    Note: we do NOT go through Flask/Celery here — the worker entrypoint
    is just a regular Python function; ``self`` is a MagicMock with the
    minimum attrs the worker reads."""

    from application.core.settings import settings

    user = f"{UNIQUE}-s12"
    with ENGINE.begin() as c:
        c.execute(
            text("INSERT INTO users (user_id) VALUES (:u) ON CONFLICT DO NOTHING"),
            {"u": user},
        )

    # ``LocalStorage`` enforces a path-traversal guard against the project
    # root, so the markdown file has to live UNDER ``<root>/<UPLOAD_FOLDER>``.
    # We use the configured upload folder (relative path) and create a
    # uniquely-named subdir we can clean up afterwards.
    upload_folder_rel = settings.UPLOAD_FOLDER  # e.g. "inputs"
    upload_root = ROOT / upload_folder_rel
    upload_root.mkdir(parents=True, exist_ok=True)

    safe_user = user.replace("/", "_")
    job_dir_name = f"qa-md-{UNIQUE}"
    file_dir_abs = upload_root / safe_user / job_dir_name
    file_dir_abs.mkdir(parents=True, exist_ok=True)
    md_path = file_dir_abs / "qa.md"
    # The FAISS path seeds the index with ``docs[0]`` *before* the loop
    # that records per-chunk progress. To exercise both the seed AND at
    # least one progress-recorded chunk, the markdown needs to be long
    # enough to chunk into ≥2 pieces under the default token settings
    # (~1000 tokens / chunk). We use a synthesised body of clearly-
    # separated paragraphs to give the chunker something realistic to
    # split on.
    paragraph = (
        "DocsGPT durability is verified by an E2E script that drives "
        "the chunker, the embedding pipeline, and the vector store on "
        "a real Postgres + mock-LLM stack. This paragraph exists to "
        "give the chunker enough text to split into multiple chunks "
        "so the per-chunk progress recorder fires at least once after "
        "the FAISS seed step. "
    )
    body = (paragraph * 80) + "\n\n"  # ~80 paragraphs of ~50 tokens each
    md_path.write_text(
        "# QA E2E Document\n\n"
        + "## Section A\n\n" + body
        + "## Section B\n\n" + body
        + "## Section C\n\n" + body,
        encoding="utf-8",
    )

    # Path passed downstream is the relative form the upload route would
    # produce (``LocalStorage`` joins this against project root for I/O).
    file_path_rel = f"{upload_folder_rel}/{safe_user}/{job_dir_name}"

    # Point embeddings at the mock LLM via env+settings, but leave
    # UPLOAD_FOLDER alone so LocalStorage's cached base_dir still points
    # at the project root.
    saved = {
        "EMBEDDINGS_BASE_URL": settings.EMBEDDINGS_BASE_URL,
        "EMBEDDINGS_KEY": settings.EMBEDDINGS_KEY,
        "EMBEDDINGS_NAME": settings.EMBEDDINGS_NAME,
        "VECTOR_STORE": settings.VECTOR_STORE,
    }
    settings.EMBEDDINGS_BASE_URL = MOCK_LLM_BASE_URL
    settings.EMBEDDINGS_KEY = "mock-key"
    settings.EMBEDDINGS_NAME = "openai_text-embedding-3-small"
    settings.VECTOR_STORE = "faiss"

    idempotency_key = f"{user}:{UNIQUE}-s12-key"
    from application.worker import _derive_source_id

    expected_source_id = str(_derive_source_id(idempotency_key))

    fake_self = MagicMock()
    fake_self.update_state = MagicMock()
    fake_self.request = MagicMock()
    fake_self.request.id = f"{UNIQUE}-s12-task"

    # The final ``upload_index`` step in ingest_worker self-calls Flask to
    # register the index with the API. We're not running Flask here, so
    # patch it to a no-op — everything we want to assert (chunker,
    # embedding pipeline, ``ingest_chunk_progress`` rows, vector store
    # files written to disk) happens BEFORE that registration call.
    upload_index_calls: list = []

    def _fake_upload_index(full_path, file_data):
        upload_index_calls.append({"full_path": full_path, "file_data": file_data})
        # Sanity-check the faiss artefacts exist before we'd POST them.
        assert os.path.exists(full_path), f"vector store dir missing: {full_path}"

    try:
        with patch_db_session(
            "application.parser.embedding_pipeline",
            "application.worker",
            "application.api.answer.services.conversation_service",
        ), patch("application.worker.upload_index", _fake_upload_index):
            from application.worker import ingest_worker

            resp = ingest_worker(
                fake_self,
                directory=upload_folder_rel,
                formats=[".md"],
                job_name=job_dir_name,
                file_path=file_path_rel,
                filename=job_dir_name,
                user=user,
                file_name_map={"qa.md": "qa.md"},
                idempotency_key=idempotency_key,
            )
        info(f"ingest_worker returned: {str(resp)[:80]}")
    finally:
        for k, v in saved.items():
            setattr(settings, k, v)

    assert len(upload_index_calls) == 1, (
        f"expected 1 upload_index call; got {len(upload_index_calls)}"
    )
    captured = upload_index_calls[0]["file_data"]
    assert captured["id"] == expected_source_id, (
        f"upload_index id mismatch: {captured['id']} vs {expected_source_id}"
    )
    step(
        f"deterministic source_id derived from scoped key: {expected_source_id} "
        f"(would-have-been-POSTed to /api/upload_index)"
    )

    with ENGINE.connect() as c:
        prog = c.execute(
            text(
                "SELECT total_chunks, embedded_chunks, last_index "
                "FROM ingest_chunk_progress WHERE source_id = CAST(:s AS uuid)"
            ),
            {"s": expected_source_id},
        ).fetchone()
    assert prog is not None, "no ingest_chunk_progress row for source"
    assert prog[0] >= 1, f"expected at least 1 chunk; got total={prog[0]}"
    assert prog[1] == prog[0], (
        f"expected embedded == total; got embedded={prog[1]} total={prog[0]}"
    )
    step(
        f"ingest_chunk_progress: embedded={prog[1]}/{prog[0]} "
        f"last_index={prog[2]}"
    )

    # Cleanup
    with ENGINE.begin() as c:
        c.execute(
            text(
                "DELETE FROM ingest_chunk_progress WHERE source_id = CAST(:s AS uuid)"
            ),
            {"s": expected_source_id},
        )
    shutil.rmtree(file_dir_abs.parent, ignore_errors=True)


# ---------------------------------------------------------------------------
# s13: SIGKILL Celery worker mid-task; verify acks_late redelivers
# ---------------------------------------------------------------------------


class CeleryWorkerService:
    """Lightweight Celery worker subprocess for the chaos test. Uses
    isolated Redis DBs (11/12) so it can't grab DocsGPT production work
    by accident, and a unique queue name so two consecutive runs don't
    inherit each other's unacked messages."""

    _log_seq = 0

    def __init__(self, queue: str, label: str = "celery") -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._queue = queue
        CeleryWorkerService._log_seq += 1
        self._log_path = (
            ROOT / ".e2e-tmp" / "logs"
            / f"{label}-{UNIQUE}-{CeleryWorkerService._log_seq}.log"
        )

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc else None

    def start(self, env_overrides: dict) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(env_overrides)
        env["PYTHONUNBUFFERED"] = "1"
        self._proc = subprocess.Popen(  # noqa: S603
            [
                sys.executable, "-m", "celery",
                "-A", "application.app.celery", "worker",
                "-l", "INFO", "--pool=solo",
                "-Q", self._queue,
                "-n", f"qa-{UNIQUE}@%h",
                "--without-gossip", "--without-mingle", "--without-heartbeat",
            ],
            stdout=open(self._log_path, "w"),
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(ROOT),
        )

        def _ready() -> bool:
            try:
                txt = self._log_path.read_text()
            except OSError:
                return False
            return f"qa-{UNIQUE}@" in txt and "ready." in txt

        if not _wait_for(_ready, timeout_s=20):
            raise RuntimeError(
                f"celery worker not ready within 20s; see {self._log_path}"
            )
        info(f"celery worker started pid={self._proc.pid} log={self._log_path}")

    def kill(self, sig: int = signal.SIGKILL) -> None:
        if self._proc is None:
            return
        try:
            os.kill(self._proc.pid, sig)
        except ProcessLookupError:
            pass
        self._proc.wait(timeout=5)
        info(f"celery worker pid={self._proc.pid} terminated by signal {sig}")
        self._proc = None

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.send_signal(signal.SIGTERM)
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=2)
        self._proc = None


def s13_sigkill_redelivers_via_acks_late() -> None:
    """Real-process chaos test:

    1. Start a Celery worker in a subprocess (isolated Redis DBs + queue).
    2. Dispatch ``process_agent_webhook`` configured to hit a slow mock
       LLM stream (``MOCK_LLM_FORCE_STREAM_CHUNK_DELAY_MS=400``).
    3. ``kill -9`` the worker mid-task before the LLM finishes.
    4. Restart the worker with the same broker.
    5. Watch the broker re-deliver the same task; the second run completes
       the LLM stream and exits cleanly.
    """

    import redis  # type: ignore[import-not-found]

    queue = f"docsgpt-chaos-{UNIQUE}"
    broker_db = 11
    backend_db = 12
    broker_url = f"redis://127.0.0.1:6379/{broker_db}"
    backend_url = f"redis://127.0.0.1:6379/{backend_db}"

    # Make sure these Redis DBs are clean of leftovers from prior runs.
    r = redis.Redis(host="127.0.0.1", port=6379, db=broker_db)
    r.flushdb()
    redis.Redis(host="127.0.0.1", port=6379, db=backend_db).flushdb()
    # Bust the stream-response cache (DB 0) too — without this, a prior
    # run's cached response satisfies the stream instantly and the mock
    # LLM's chunk delay never gets exercised, so SIGKILL fires after the
    # task already completed.
    redis.Redis(host="127.0.0.1", port=6379, db=0).flushdb()

    # The mock LLM running on the main port (started by the runner) has
    # no chunk delay. s13 needs a slow stream so SIGKILL lands while the
    # worker is still consuming chunks. Stop the existing mock and start
    # a delayed one in its place; the delay env reaches mock_llm.py via
    # ``MOCK_LLM_FORCE_STREAM_CHUNK_DELAY_MS``.
    delayed_mock = MockLLMService(chunk_delay_ms=400)
    # Force-restart even if the existing one is reused: kill via port.
    if _port_open(MOCK_LLM_HOST, MOCK_LLM_PORT):
        # The runner's mock is owned by ``main()``; we need to take it
        # offline temporarily so our delayed copy can bind the port.
        # Send SIGTERM to whoever owns the port via lsof (best-effort).
        try:
            pids = subprocess.check_output(
                ["lsof", "-tiTCP:7899", "-sTCP:LISTEN"], text=True
            ).split()
            for pid in pids:
                os.kill(int(pid), signal.SIGTERM)
            time.sleep(0.3)
        except (subprocess.CalledProcessError, FileNotFoundError, ProcessLookupError):
            pass
    delayed_mock.start()

    # We need an agent (with key + webhook token + prompt) to drive the
    # webhook task. The mock LLM has no idea about retrieval, so the
    # 'classic' agent_type is fine.
    user = f"{UNIQUE}-s13"
    with ENGINE.begin() as c:
        c.execute(
            text("INSERT INTO users (user_id) VALUES (:u) ON CONFLICT DO NOTHING"),
            {"u": user},
        )
        prompt_row = c.execute(
            text(
                "INSERT INTO prompts (user_id, name, content) "
                "VALUES (:u, :n, :c) RETURNING id"
            ),
            {"u": user, "n": f"{UNIQUE}-s13", "c": "you are a tester"},
        ).fetchone()
        prompt_id = str(prompt_row[0])
        agent_id = str(uuid.uuid4())
        agent_key = f"{UNIQUE}-akey-{uuid.uuid4().hex[:8]}"
        c.execute(
            text(
                "INSERT INTO agents (id, user_id, name, status, retriever, "
                "prompt_id, tools, agent_type, key, chunks) "
                "VALUES (CAST(:id AS uuid), :u, :n, 'published', 'classic', "
                "CAST(:p AS uuid), '[]'::jsonb, 'classic', :k, '2')"
            ),
            {
                "id": agent_id, "u": user, "n": f"{UNIQUE}-s13",
                "p": prompt_id, "k": agent_key,
            },
        )
    info(f"seeded agent={agent_id} user={user}")

    env_overrides = {
        "POSTGRES_URI": os.environ["POSTGRES_URI"],
        "CELERY_BROKER_URL": broker_url,
        "CELERY_RESULT_BACKEND": backend_url,
        "LLM_PROVIDER": "openai",
        "LLM_NAME": "gpt-4o-mini",
        "API_KEY": "mock-key",
        "OPENAI_API_KEY": "mock-key",
        "OPENAI_BASE_URL": MOCK_LLM_BASE_URL,
        "EMBEDDINGS_BASE_URL": MOCK_LLM_BASE_URL,
        "EMBEDDINGS_KEY": "mock-key",
        "EMBEDDINGS_NAME": "openai_text-embedding-3-small",
        "VECTOR_STORE": "faiss",
        "MOCK_LLM_FORCE_STREAM_CHUNK_DELAY_MS": "400",
        "AUTO_MIGRATE": "false",
        "AUTO_CREATE_DB": "false",
        # Short visibility window so the broker re-queues the SIGKILLed
        # task within seconds rather than the 1-hour production default.
        # Has to be set on BOTH workers — the unack entry's age is
        # checked by whichever worker scans next.
        "CELERY_VISIBILITY_TIMEOUT": "5",
    }

    worker = CeleryWorkerService(queue=queue)
    worker.start(env_overrides)

    # Dispatch via celery's send_task using the same broker URL the worker
    # listens on. The DocsGPT celery instance has already loaded
    # ``application.celeryconfig`` (broker = production .env DB 0); since
    # Celery's conf re-reads ``CELERY_BROKER_URL`` from the env at publish
    # time, we override the env for the *whole* dispatch + wait block.
    from celery import Celery

    saved_broker = os.environ.get("CELERY_BROKER_URL")
    saved_backend = os.environ.get("CELERY_RESULT_BACKEND")
    os.environ["CELERY_BROKER_URL"] = broker_url
    os.environ["CELERY_RESULT_BACKEND"] = backend_url

    try:
        chaos_app = Celery("chaos", broker=broker_url, backend=backend_url)
        chaos_app.conf.broker_url = broker_url
        chaos_app.conf.result_backend = backend_url
        chaos_app.conf.task_default_queue = queue
        chaos_app.conf.task_default_exchange = queue
        chaos_app.conf.task_default_routing_key = queue
        chaos_app.conf.task_acks_late = True
        chaos_app.conf.task_reject_on_worker_lost = True
        info(
            f"chaos_app broker={chaos_app.conf.broker_url} "
            f"queue={chaos_app.conf.task_default_queue}"
        )

        idempotency_key = f"{agent_id}:{UNIQUE}-s13-key"
        task_id = str(uuid.uuid4())
        info(f"dispatching task_id={task_id} key={idempotency_key}")
        chaos_app.send_task(
            "application.api.user.tasks.process_agent_webhook",
            kwargs={
                "agent_id": agent_id,
                "payload": {"event": f"{UNIQUE}-s13"},
                "idempotency_key": idempotency_key,
            },
            queue=queue,
            task_id=task_id,
        )

        # Sanity: the task should be visible in the broker for at least a
        # brief moment before the worker pulls it. If it never appears,
        # the publish missed the queue entirely.
        queue_seen = _wait_for(
            lambda: r.llen(queue) >= 1, timeout_s=2.0, interval_s=0.05,
        )
        info(
            f"after send_task: queue len={r.llen(queue)} "
            f"(visible-briefly={queue_seen}) "
            f"unacked={r.hlen('unacked') if r.exists('unacked') else 0}"
        )

        # Wait until the worker actually starts running the task. The
        # mock LLM streams 5 chunks at 400ms each (= 2s), giving us a
        # window to SIGKILL while the task is still in flight.
        def _task_received() -> bool:
            try:
                txt = worker._log_path.read_text()  # noqa: SLF001
            except OSError:
                return False
            return task_id in txt

        started = _wait_for(_task_received, timeout_s=20)
        if not started:
            try:
                tail = worker._log_path.read_text()[-2000:]  # noqa: SLF001
                warn(f"worker log tail:\n{tail}")
            except OSError:
                pass
            qlen = r.llen(queue)
            unacked_now = r.hlen("unacked") if r.exists("unacked") else 0
            warn(f"broker state: queue len={qlen} unacked={unacked_now}")
            worker.stop()
            raise AssertionError(
                f"task did not start on worker 1 within 20s — "
                f"see {worker._log_path}"
            )
        info("task picked up by worker 1; killing mid-flight")
        sigkill_pid = worker.pid
        worker.kill(signal.SIGKILL)
        info(f"SIGKILLed worker pid={sigkill_pid}")

        unacked_count = r.hlen("unacked") if r.exists("unacked") else 0
        info(f"broker 'unacked' hash size after SIGKILL: {unacked_count}")

        # Restart the worker — acks_late + reject_on_worker_lost should
        # make the broker redeliver the same task to it.
        worker2 = CeleryWorkerService(queue=queue)
        worker2.start(env_overrides)

        def _task_completed() -> bool:
            try:
                txt = worker2._log_path.read_text()  # noqa: SLF001
            except OSError:
                return False
            return (
                task_id in txt
                and ("succeeded in" in txt or "Task succeeded" in txt)
            )

        completed = _wait_for(_task_completed, timeout_s=60)
        worker2.stop()
        assert completed, (
            f"redelivered task did not complete within 60s; "
            f"see {worker2._log_path}"
        )
        step(f"task {task_id} redelivered after SIGKILL and completed cleanly")
    finally:
        if saved_broker is not None:
            os.environ["CELERY_BROKER_URL"] = saved_broker
        else:
            os.environ.pop("CELERY_BROKER_URL", None)
        if saved_backend is not None:
            os.environ["CELERY_RESULT_BACKEND"] = saved_backend
        else:
            os.environ.pop("CELERY_RESULT_BACKEND", None)

    # Cleanup
    delayed_mock.stop()
    redis.Redis(host="127.0.0.1", port=6379, db=broker_db).flushdb()
    redis.Redis(host="127.0.0.1", port=6379, db=backend_db).flushdb()
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM agents WHERE id = CAST(:a AS uuid)"), {"a": agent_id})
        c.execute(text("DELETE FROM prompts WHERE id = CAST(:p AS uuid)"), {"p": prompt_id})


def s10_celery_default_queue() -> None:
    """Sanity: the broker queue is project-scoped so a sibling worker on
    the same Redis can't grab DocsGPT tasks."""

    from application import celeryconfig

    assert celeryconfig.task_default_queue == "docsgpt", (
        f"expected default queue 'docsgpt'; got {celeryconfig.task_default_queue!r}"
    )
    assert celeryconfig.task_acks_late is True
    assert celeryconfig.task_reject_on_worker_lost is True
    assert celeryconfig.broker_transport_options.get("visibility_timeout") == 3600, (
        f"visibility_timeout mismatch: "
        f"{celeryconfig.broker_transport_options}"
    )
    step("celeryconfig: docsgpt queue, acks_late, reject_on_lost, visibility=3600")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

SCENARIOS = [
    ("s1", s1_wal_and_reconciler,
     "WAL placeholder + reconciler escalation"),
    ("s2", s2_webhook_idempotency_and_scoping,
     "webhook idempotency + cross-agent scope"),
    ("s3", s3_ingest_deterministic_and_resume,
     "deterministic source_id + chunk-progress resume"),
    ("s4", s4_token_usage_atomic_rollback,
     "token_usage rolls back atomically with message update"),
    ("s5", s5_reconciler_tool_call_sweeps,
     "reconciler escalates stuck tool_call_attempts"),
    ("s6", s6_resume_janitor,
     "pending_tool_state janitor reverts stale 'resuming'"),
    ("s7", s7_token_usage_attribution,
     "token_usage attribution + canary + side-channel inline persist"),
    ("s8", s8_regenerate_replaces,
     "regenerate at index truncates tail and replaces"),
    ("s9", s9_idempotency_concurrent_claim,
     "concurrent claim_task race: exactly one winner"),
    ("s10", s10_celery_default_queue,
     "celeryconfig sanity: docsgpt queue + durability defaults"),
    ("s11", s11_live_llm_stream_through_wal,
     "LIVE: real OpenAI-protocol stream → WAL → finalize → token_usage"),
    ("s12", s12_full_embedding_loop,
     "LIVE: ingest a markdown file end-to-end (chunker + embeddings + faiss)"),
    ("s13", s13_sigkill_redelivers_via_acks_late,
     "LIVE: SIGKILL Celery worker mid-task; verify acks_late redelivers"),
]


# Scenarios that need the mock LLM running. The runner starts/stops it
# automatically when any of these are selected.
_LIVE_SCENARIOS = {"s11", "s12", "s13"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list scenarios and exit")
    parser.add_argument(
        "--only",
        help="comma-separated scenario keys to run (e.g. s1,s5)",
    )
    args = parser.parse_args()

    if args.list:
        for key, _, desc in SCENARIOS:
            print(f"  {key}: {desc}")
        return 0

    selected = SCENARIOS
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        selected = [s for s in SCENARIOS if s[0] in wanted]
        missing = wanted - {s[0] for s in selected}
        if missing:
            print(f"unknown scenarios: {sorted(missing)}", file=sys.stderr)
            return 2

    print(f"{DIM}prefix: {UNIQUE}{RESET}")
    print(f"{DIM}engine: {POSTGRES_URI[:60]}…{RESET}")

    selected_keys = {k for k, _, _ in selected}
    needs_mock_llm = bool(selected_keys & _LIVE_SCENARIOS)
    mock_llm: Optional[MockLLMService] = None
    if needs_mock_llm:
        mock_llm = MockLLMService()
        try:
            mock_llm.start()
        except Exception as exc:  # noqa: BLE001
            print(f"  {RED}failed to start mock LLM: {exc}{RESET}", file=sys.stderr)
            return 2

    passes = 0
    fails: list[tuple[str, str]] = []

    try:
        for key, fn, desc in selected:
            header(f"[{key}] {desc}")
            try:
                fn()
                passes += 1
            except AssertionError as exc:
                fail(str(exc))
                fails.append((key, str(exc)))
            except Exception as exc:  # noqa: BLE001
                fail(f"{type(exc).__name__}: {exc}")
                traceback.print_exc()
                fails.append((key, f"{type(exc).__name__}: {exc}"))
            finally:
                try:
                    cleanup_artifacts(UNIQUE)
                except Exception as exc:  # noqa: BLE001
                    warn(f"cleanup raised: {exc}")
    finally:
        if mock_llm is not None:
            mock_llm.stop()

    print()
    header("summary")
    print(f"  {GREEN}{passes} passed{RESET}, {RED}{len(fails)} failed{RESET}")
    if fails:
        print()
        for key, why in fails:
            print(f"  {RED}{key}{RESET}: {why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
