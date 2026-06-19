"""Layer-1 idempotency for ``/v1/chat/completions`` (non-streaming, OpenAI-style).

Dropping the native ``resume_from_tool_actions`` path removed its
``mark_resuming`` guard, so a duplicated/retried non-streaming POST could
re-run the agent → a duplicate answer row + double token billing. The fix
honors a client-supplied ``Idempotency-Key`` header: a retry returns the
*stored first response* instead of re-running.

These tests pin both layers against an ephemeral Postgres (``pg_engine``):

- the ``application.api.v1.idempotency`` helper contract directly
  (completed → cached, fresh-pending → 409, stale-pending → re-claim,
  non-2xx → not cached); and
- the real ``/v1/chat/completions`` route end-to-end: the same key twice
  returns the cached body and does NOT re-run the agent or append a second
  conversation row; no key / different keys run independently; a 5xx first
  response is not cached so a retry re-runs.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from application.api.v1 import idempotency as v1_idem
from application.api.v1.idempotency import (
    STALE_PENDING_SECONDS,
    TASK_NAME,
    claim_or_replay,
    finalize,
    release,
    scoped_key,
)
from application.api.v1.routes import v1_bp

# Reuse the route-level DB wiring + fake answering agent from the tool-pause
# suite so a real two-POST round-trip runs against the ephemeral Postgres.
from tests.api.v1.test_v1_tool_pause_finalization import (
    _seed_agent,
    _seed_user,
    _wire_v1_route_db,
)


# ---------------------------------------------------------------------------
# Helper-contract tests (drive the real task_dedup row directly)
# ---------------------------------------------------------------------------


def _make_response(app: Flask, body: Dict[str, Any], status: int):
    """Build a real Flask Response inside an app context (for ``finalize``)."""
    from flask import jsonify, make_response

    with app.test_request_context():
        return make_response(jsonify(body), status)


def _wire_idem_db(engine, monkeypatch) -> None:
    """Point the v1 idempotency helper's ``db_session``/``db_readonly`` at
    the ephemeral engine (each call opens its own short-lived connection)."""

    @contextmanager
    def _session():
        conn = engine.connect()
        txn = conn.begin()
        try:
            yield conn
            txn.commit()
        except Exception:
            txn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _readonly():
        conn = engine.connect()
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(v1_idem, "db_session", _session)
    monkeypatch.setattr(v1_idem, "db_readonly", _readonly)


def _backdate_pending(engine, key: str, secs_ago: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE task_dedup "
                "SET created_at = clock_timestamp() - make_interval(secs => :s) "
                "WHERE idempotency_key = :k"
            ),
            {"s": secs_ago, "k": key},
        )


@pytest.mark.integration
class TestIdempotencyHelperContract:
    """The three-outcome claim-before-process contract, against a real row."""

    def test_scoped_key_namespaces_by_agent(self):
        assert scoped_key("abc", "agent-1") == "agent-1:abc"
        # Two agents with the same key value never collide.
        assert scoped_key("abc", "agent-1") != scoped_key("abc", "agent-2")
        # Opt-in: missing either component disables idempotency.
        assert scoped_key(None, "agent-1") is None
        assert scoped_key("abc", None) is None

    def test_first_claim_then_completed_replays_cached(self, pg_engine, monkeypatch):
        # ``claim_or_replay`` builds Flask responses (``jsonify``) for the
        # replay/409 paths, so it runs inside an app context — exactly as it
        # does in the real route.
        app = Flask(__name__)
        _wire_idem_db(pg_engine, monkeypatch)
        key = f"agent:{uuid.uuid4().hex}"

        with app.app_context():
            claimed, replay = claim_or_replay(key)
            assert claimed is True
            assert replay is None

            # Finalize a 200 with a body, then a retry replays it byte-for-byte
            # without re-claiming.
            body = {"id": "chatcmpl-1", "choices": [{"x": 1}]}
            finalize(key, _make_response(app, body, 200))

            claimed2, replay2 = claim_or_replay(key)
            assert claimed2 is False
            assert replay2 is not None
            assert replay2.status_code == 200
            assert replay2.get_json() == body

    def test_fresh_pending_returns_409(self, pg_engine, monkeypatch):
        app = Flask(__name__)
        _wire_idem_db(pg_engine, monkeypatch)
        key = f"agent:{uuid.uuid4().hex}"

        with app.app_context():
            claimed, _ = claim_or_replay(key)
            assert claimed is True  # first request in flight, never finalized

            # A concurrent same-key request sees a fresh pending row → 409.
            claimed2, replay2 = claim_or_replay(key)
            assert claimed2 is False
            assert replay2 is not None
            assert replay2.status_code == 409
            assert replay2.get_json()["error"]["type"] == "idempotency_conflict"

    def test_stale_pending_is_reclaimed(self, pg_engine, monkeypatch):
        app = Flask(__name__)
        _wire_idem_db(pg_engine, monkeypatch)
        key = f"agent:{uuid.uuid4().hex}"

        with app.app_context():
            claimed, _ = claim_or_replay(key)
            assert claimed is True
            # The original request "died" before finalize; age the claim past
            # the safety window so a retry may re-claim instead of 409-ing
            # forever.
            _backdate_pending(pg_engine, key, secs_ago=STALE_PENDING_SECONDS + 5)

            claimed2, replay2 = claim_or_replay(key)
            assert claimed2 is True
            assert replay2 is None

    def test_non_2xx_response_is_not_cached(self, pg_engine, monkeypatch):
        app = Flask(__name__)
        _wire_idem_db(pg_engine, monkeypatch)
        key = f"agent:{uuid.uuid4().hex}"

        with app.app_context():
            claimed, _ = claim_or_replay(key)
            assert claimed is True
            # A 5xx must release the claim (not cache the error).
            finalize(key, _make_response(app, {"error": {"message": "boom"}}, 500))

        with pg_engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM task_dedup WHERE idempotency_key = :k"),
                {"k": key},
            ).fetchone()
        assert row is None  # released → a genuine retry can re-claim

    def test_release_drops_pending_claim(self, pg_engine, monkeypatch):
        app = Flask(__name__)
        _wire_idem_db(pg_engine, monkeypatch)
        key = f"agent:{uuid.uuid4().hex}"
        with app.app_context():
            claim_or_replay(key)
            release(key)
        with pg_engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM task_dedup WHERE idempotency_key = :k"),
                {"k": key},
            ).fetchone()
        assert row is None


# ---------------------------------------------------------------------------
# Route-level tests — same key twice does NOT re-run the agent
# ---------------------------------------------------------------------------


class _CountingAnswerAgent:
    """Agent that answers once per ``gen`` and records how often it ran.

    A class-level counter survives across the fresh instances handed back by
    the patched ``build_agent``, so the route-level test can assert the agent
    ran exactly once across two same-key POSTs.
    """

    ANSWER_TEXT = "The answer is 42."
    gen_calls = 0

    def __init__(self) -> None:
        from tests.api.v1.test_v1_tool_pause_finalization import (
            _FakeClientToolExecutor,
            _FakeLLM,
        )

        self.llm = _FakeLLM()
        self.tool_executor = _FakeClientToolExecutor()
        self.conversation_id = None
        self.initial_user_id = None
        self.tools: List[Dict[str, Any]] = []

    def gen(self, query: str = ""):
        # Write the base-class counter explicitly so subclasses (e.g. a
        # failing variant) share one run-count rather than shadowing it.
        _CountingAnswerAgent.gen_calls += 1
        yield {"answer": self.ANSWER_TEXT}


def _build_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(v1_bp)
    return app


def _post_chat(client, body, api_key, idem_key=None):
    headers = {"Authorization": f"Bearer {api_key}"}
    if idem_key is not None:
        headers["Idempotency-Key"] = idem_key
    return client.post("/v1/chat/completions", headers=headers, json=body)


def _conv_count(conn, user_id: str) -> int:
    return conn.execute(
        text("SELECT count(*) FROM conversations WHERE user_id = :u"),
        {"u": user_id},
    ).scalar()


def _row_count(conn, user_id: str) -> int:
    return conn.execute(
        text(
            "SELECT count(*) FROM conversation_messages cm "
            "JOIN conversations c ON c.id = cm.conversation_id "
            "WHERE c.user_id = :u"
        ),
        {"u": user_id},
    ).scalar()


@pytest.mark.integration
class TestV1IdempotencyRoute:
    """Drive the real ``/v1/chat/completions`` route with/without a key."""

    QUESTION = {"messages": [{"role": "user", "content": "what is the answer?"}],
                "docsgpt": {"save_conversation": True}}

    def _fake_build_agent(self, question):  # noqa: ARG002
        return _CountingAnswerAgent()

    def test_same_key_twice_replays_without_rerunning_agent(
        self, pg_engine, monkeypatch
    ):
        user_id = f"user-{uuid.uuid4().hex[:8]}"
        api_key = f"key-{uuid.uuid4().hex[:8]}"
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)
            _seed_agent(conn, user_id, api_key)

        app = _build_app()
        idem_key = f"idem-{uuid.uuid4().hex}"
        _CountingAnswerAgent.gen_calls = 0

        with _wire_v1_route_db(pg_engine, monkeypatch), patch(
            "application.api.answer.services.stream_processor.StreamProcessor"
            ".build_agent",
            self._fake_build_agent,
        ):
            _wire_idem_db(pg_engine, monkeypatch)
            with app.test_client() as c:
                resp1 = _post_chat(c, self.QUESTION, api_key, idem_key=idem_key)
                resp2 = _post_chat(c, self.QUESTION, api_key, idem_key=idem_key)

        assert resp1.status_code == 200, resp1.get_data(as_text=True)
        assert resp2.status_code == 200, resp2.get_data(as_text=True)
        body1, body2 = resp1.get_json(), resp2.get_json()
        # The retry returns the cached first response byte-for-byte.
        assert body2 == body1
        assert body2["choices"][0]["message"]["content"] == (
            _CountingAnswerAgent.ANSWER_TEXT
        )

        # Real dedup: the agent ran exactly once across the two POSTs...
        assert _CountingAnswerAgent.gen_calls == 1
        # ...and no duplicate conversation / answer row was appended.
        with pg_engine.connect() as conn:
            assert _conv_count(conn, user_id) == 1
            # One conversation, one terminal answer row (not two).
            assert _row_count(conn, user_id) == 1

    def test_no_key_runs_each_time(self, pg_engine, monkeypatch):
        """Opt-in: without a key, behavior is today's — each POST runs."""
        user_id = f"user-{uuid.uuid4().hex[:8]}"
        api_key = f"key-{uuid.uuid4().hex[:8]}"
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)
            _seed_agent(conn, user_id, api_key)

        app = _build_app()
        _CountingAnswerAgent.gen_calls = 0

        with _wire_v1_route_db(pg_engine, monkeypatch), patch(
            "application.api.answer.services.stream_processor.StreamProcessor"
            ".build_agent",
            self._fake_build_agent,
        ):
            _wire_idem_db(pg_engine, monkeypatch)
            with app.test_client() as c:
                resp1 = _post_chat(c, self.QUESTION, api_key)
                resp2 = _post_chat(c, self.QUESTION, api_key)

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Two independent runs → two conversations.
        assert _CountingAnswerAgent.gen_calls == 2
        with pg_engine.connect() as conn:
            assert _conv_count(conn, user_id) == 2

    def test_different_keys_run_independently(self, pg_engine, monkeypatch):
        user_id = f"user-{uuid.uuid4().hex[:8]}"
        api_key = f"key-{uuid.uuid4().hex[:8]}"
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)
            _seed_agent(conn, user_id, api_key)

        app = _build_app()
        _CountingAnswerAgent.gen_calls = 0

        with _wire_v1_route_db(pg_engine, monkeypatch), patch(
            "application.api.answer.services.stream_processor.StreamProcessor"
            ".build_agent",
            self._fake_build_agent,
        ):
            _wire_idem_db(pg_engine, monkeypatch)
            with app.test_client() as c:
                _post_chat(c, self.QUESTION, api_key, idem_key="k-A")
                _post_chat(c, self.QUESTION, api_key, idem_key="k-B")

        assert _CountingAnswerAgent.gen_calls == 2
        with pg_engine.connect() as conn:
            assert _conv_count(conn, user_id) == 2

    def test_5xx_first_response_is_not_cached_and_retry_reruns(
        self, pg_engine, monkeypatch
    ):
        """A failed first response must NOT be cached: a retry re-runs."""
        user_id = f"user-{uuid.uuid4().hex[:8]}"
        api_key = f"key-{uuid.uuid4().hex[:8]}"
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)
            _seed_agent(conn, user_id, api_key)

        app = _build_app()
        idem_key = f"idem-{uuid.uuid4().hex}"

        class _BoomAgent(_CountingAnswerAgent):
            def gen(self, query: str = ""):
                _CountingAnswerAgent.gen_calls += 1
                raise RuntimeError("upstream exploded")
                yield  # pragma: no cover - keeps gen a generator

        boom_state = {"fail": True}

        def _build(self, question):  # noqa: ARG001
            return _BoomAgent() if boom_state["fail"] else _CountingAnswerAgent()

        _CountingAnswerAgent.gen_calls = 0

        with _wire_v1_route_db(pg_engine, monkeypatch), patch(
            "application.api.answer.services.stream_processor.StreamProcessor"
            ".build_agent",
            _build,
        ):
            _wire_idem_db(pg_engine, monkeypatch)
            with app.test_client() as c:
                resp1 = _post_chat(c, self.QUESTION, api_key, idem_key=idem_key)
                # First attempt blew up (500) and released the claim. The key
                # is agent-id scoped at the route, so confirm release via a
                # table-wide count for this task_name (no live claim left).
                assert resp1.status_code == 500, resp1.get_data(as_text=True)
                with pg_engine.connect() as conn:
                    rows = conn.execute(
                        text(
                            "SELECT count(*) FROM task_dedup "
                            "WHERE task_name = :n"
                        ),
                        {"n": TASK_NAME},
                    ).scalar()
                assert rows == 0  # error was not cached; claim released

                # Retry: the agent now answers; idempotency did NOT cache the error.
                boom_state["fail"] = False
                resp2 = _post_chat(c, self.QUESTION, api_key, idem_key=idem_key)

        assert resp2.status_code == 200, resp2.get_data(as_text=True)
        # Agent ran twice total: the failing first + the successful retry.
        assert _CountingAnswerAgent.gen_calls == 2
        # The successful retry IS now cached.
        with pg_engine.connect() as conn:
            completed = conn.execute(
                text(
                    "SELECT count(*) FROM task_dedup "
                    "WHERE task_name = :n AND status = 'completed'"
                ),
                {"n": TASK_NAME},
            ).scalar()
        assert completed == 1
