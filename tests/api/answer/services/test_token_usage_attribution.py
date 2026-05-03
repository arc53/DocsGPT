"""Token-usage attribution tests for the always-on inline-persist model.

Persistence is owned by the per-call decorator in ``application.usage``.
``finalize_message`` no longer writes ``token_usage`` rows. These tests
exercise the decorator path through ``stream_token_usage`` /
``gen_token_usage``:

1. Every LLM call writes one row, regardless of whether the route saves
   the conversation.
2. ``_token_usage_source`` on the LLM instance flows to the row's
   ``source`` column for cost-attribution dashboards.
3. ``_request_id`` on the LLM instance flows to the row's ``request_id``
   column so ``count_in_range`` can DISTINCT-collapse multi-call agent
   runs into a single request.
4. Calls with no attribution (no ``user_id`` and no ``user_api_key``)
   warn and skip — the repository would otherwise raise on the
   ``token_usage_attribution_chk`` constraint.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text


@contextmanager
def _patch_db_session_for(modules, conn):
    """Reroute every named module's ``db_session`` to ``conn``."""

    @contextmanager
    def _yield():
        yield conn

    patches = [patch(f"{m}.db_session", _yield) for m in modules]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


def _seed_user(conn) -> str:
    user_id = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO users (user_id) VALUES (:u) "
            "ON CONFLICT (user_id) DO NOTHING"
        ),
        {"u": user_id},
    )
    return user_id


@pytest.mark.unit
class TestDecoratorAlwaysPersists:
    """Per-call inline persistence — no opt-in flag."""

    def test_primary_stream_writes_agent_stream_row(self, pg_conn):
        from application.usage import stream_token_usage

        user_id = _seed_user(pg_conn)

        class _PrimaryLLM:
            decoded_token = {"sub": user_id}
            user_api_key = None
            agent_id = None

            def __init__(self):
                self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

            @stream_token_usage
            def _raw(self, model, messages, stream, tools, **kwargs):
                yield "chunk-a"
                yield "chunk-b"

        llm = _PrimaryLLM()
        with _patch_db_session_for(("application.usage",), pg_conn):
            for _ in llm._raw(
                "m", [{"role": "user", "content": "hi"}], True, None,
            ):
                pass

        row = pg_conn.execute(
            text(
                "SELECT prompt_tokens, generated_tokens, source, request_id "
                "FROM token_usage WHERE user_id = :u"
            ),
            {"u": user_id},
        ).fetchone()
        assert row is not None
        assert row[2] == "agent_stream"
        assert row[3] is None  # No request_id stamped on this LLM.
        assert row[0] > 0
        assert row[1] > 0

    def test_side_channel_source_flows_to_row(self, pg_conn):
        """``_token_usage_source`` overrides the default ``agent_stream``."""
        from application.usage import stream_token_usage

        user_id = _seed_user(pg_conn)

        class _RagLLM:
            decoded_token = {"sub": user_id}
            user_api_key = None
            agent_id = None
            _token_usage_source = "rag_condense"

            def __init__(self):
                self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

            @stream_token_usage
            def _raw(self, model, messages, stream, tools, **kwargs):
                yield "chunk"

        llm = _RagLLM()
        with _patch_db_session_for(("application.usage",), pg_conn):
            for _ in llm._raw("m", [{"role": "user", "content": "q"}], True, None):
                pass

        row = pg_conn.execute(
            text(
                "SELECT source FROM token_usage WHERE user_id = :u"
            ),
            {"u": user_id},
        ).fetchone()
        assert row is not None
        assert row[0] == "rag_condense"

    def test_request_id_propagates_to_row(self, pg_conn):
        """``_request_id`` on the LLM (stamped by the route) lands in
        ``token_usage.request_id`` so ``count_in_range`` can DISTINCT it.
        """
        from application.usage import stream_token_usage

        user_id = _seed_user(pg_conn)
        request_id = f"req-{uuid.uuid4().hex[:12]}"

        class _PrimaryLLM:
            decoded_token = {"sub": user_id}
            user_api_key = None
            agent_id = None

            def __init__(self):
                self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}
                self._request_id = request_id

            @stream_token_usage
            def _raw(self, model, messages, stream, tools, **kwargs):
                yield "chunk"

        llm = _PrimaryLLM()
        with _patch_db_session_for(("application.usage",), pg_conn):
            # Call twice — the route invokes the LLM once per tool round.
            for _ in llm._raw("m", [{"role": "user", "content": "q"}], True, None):
                pass
            for _ in llm._raw("m", [{"role": "user", "content": "q2"}], True, None):
                pass

        rows = pg_conn.execute(
            text(
                "SELECT request_id FROM token_usage WHERE user_id = :u"
            ),
            {"u": user_id},
        ).fetchall()
        assert len(rows) == 2
        assert all(r[0] == request_id for r in rows)

    def test_zero_count_call_is_skipped(self, pg_conn):
        from application.usage import gen_token_usage

        user_id = _seed_user(pg_conn)

        class _EmptyLLM:
            decoded_token = {"sub": user_id}
            user_api_key = None
            agent_id = None

            def __init__(self):
                self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

            @gen_token_usage
            def _raw(self, model, messages, stream, tools, **kwargs):
                return None  # empty result → 0 generated tokens, 0 prompt tokens

        llm = _EmptyLLM()
        with _patch_db_session_for(("application.usage",), pg_conn):
            llm._raw("m", [], False, None)

        n = pg_conn.execute(
            text("SELECT count(*) FROM token_usage WHERE user_id = :u"),
            {"u": user_id},
        ).scalar()
        assert n == 0

    def test_no_attribution_warns_and_skips(self, pg_conn, caplog):
        """No user_id and no api_key → log a warning, don't insert.

        The repository would otherwise raise on the attribution CHECK
        constraint; the decorator skips before that to keep the stream
        running.
        """
        from application.usage import stream_token_usage

        class _OrphanLLM:
            decoded_token = None
            user_api_key = None
            agent_id = None

            def __init__(self):
                self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

            @stream_token_usage
            def _raw(self, model, messages, stream, tools, **kwargs):
                yield "chunk"

        llm = _OrphanLLM()
        with _patch_db_session_for(
            ("application.usage",), pg_conn,
        ), caplog.at_level(logging.WARNING, logger="application.usage"):
            for _ in llm._raw("m", [{"role": "user", "content": "q"}], True, None):
                pass

        n = pg_conn.execute(text("SELECT count(*) FROM token_usage")).scalar()
        # New attribution rows specifically for this orphan path: nothing
        # should land. The fixture pins state, so an existing baseline is
        # 0 by default.
        assert n == 0
        assert any(
            "no user_id/api_key" in r.message
            for r in caplog.records
        )
