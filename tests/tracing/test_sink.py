"""Tests for writing a finished trace to Postgres and OTel."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from docsgpt import tracing
from docsgpt.core.settings import settings


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(settings, "TRACES_ENABLED", True)


def _trace_with_span():
    trace = tracing.start_trace(source="stream", request_id="r1", user_id="u1")
    with tracing.activate(trace):
        with tracing.span(tracing.KIND_LLM, "chat m"):
            pass
    return trace


@contextmanager
def _patched_store():
    repo = MagicMock()
    repo.insert.return_value = True

    @contextmanager
    def _session():
        yield MagicMock()

    with patch("docsgpt.storage.db.session.db_session", _session), patch(
        "docsgpt.storage.db.repositories.request_traces.RequestTracesRepository",
        return_value=repo,
    ):
        yield repo


class TestFlush:
    def test_flush_writes_once(self):
        trace = _trace_with_span()
        with _patched_store() as repo:
            tracing.flush(trace)
            tracing.flush(trace)
        assert repo.insert.call_count == 1
        record = repo.insert.call_args[0][0]
        assert record["request_id"] == "r1"
        assert record["status"] == "ok"
        assert trace.finished and trace.flushed

    def test_flush_status_override(self):
        trace = _trace_with_span()
        with _patched_store() as repo:
            tracing.flush(trace, status="paused")
        assert repo.insert.call_args[0][0]["status"] == "paused"

    def test_empty_trace_is_not_stored(self):
        trace = tracing.start_trace(source="stream")
        with _patched_store() as repo:
            tracing.flush(trace)
        repo.insert.assert_not_called()

    def test_store_failure_is_swallowed(self):
        trace = _trace_with_span()
        with _patched_store() as repo:
            repo.insert.side_effect = RuntimeError("db down")
            tracing.flush(trace)  # must not raise

    def test_otel_failure_does_not_block_store(self):
        trace = _trace_with_span()
        with _patched_store() as repo, patch(
            "docsgpt.tracing.otel.export_trace", side_effect=RuntimeError("otel")
        ):
            tracing.flush(trace)
        repo.insert.assert_called_once()

    def test_otel_trace_id_is_stored(self):
        trace = _trace_with_span()
        with _patched_store() as repo, patch(
            "docsgpt.tracing.otel.export_trace", return_value="ab" * 16
        ):
            tracing.flush(trace)
        assert repo.insert.call_args[0][0]["otel_trace_id"] == "ab" * 16

    def test_none_is_ignored(self):
        tracing.flush(None)
        tracing.discard(None)


class TestDiscard:
    def test_discard_never_writes(self):
        trace = _trace_with_span()
        with _patched_store() as repo:
            tracing.discard(trace)
            tracing.flush(trace)
        repo.insert.assert_not_called()


class TestBackgroundFlush:
    def test_background_flush_writes_off_the_calling_thread(self):
        import threading

        trace = _trace_with_span()
        seen = {}

        def _insert(record):
            seen["thread"] = threading.current_thread().name
            return True

        with _patched_store() as repo:
            repo.insert.side_effect = _insert
            future = tracing.flush(trace, background=True)
            assert trace.finished  # frozen at once, written later
            future.result(timeout=5)
        assert seen["thread"].startswith("trace-writer")
        assert repo.insert.call_count == 1

    def test_background_flush_is_still_once(self):
        trace = _trace_with_span()
        with _patched_store() as repo:
            future = tracing.flush(trace, background=True)
            assert tracing.flush(trace, background=True) is None
            future.result(timeout=5)
        assert repo.insert.call_count == 1
