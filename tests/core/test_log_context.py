"""Unit tests for ``log_context`` + ``_ContextFilter``."""

from __future__ import annotations

import logging

import pytest

from application.core import log_context
from application.core.logging_config import _ContextFilter


@pytest.fixture(autouse=True)
def _clean_log_ctx():
    # The contextvar is module-scoped; snapshot at entry, restore at exit
    # to keep tests from leaking state into each other.
    token = log_context.bind()
    try:
        yield
    finally:
        log_context.reset(token)


@pytest.mark.unit
class TestBindAndSnapshot:

    def test_bind_returns_token_and_snapshot_reflects_overlay(self):
        token = log_context.bind(activity_id="a1", user_id="u1")
        assert log_context.snapshot() == {"activity_id": "a1", "user_id": "u1"}
        log_context.reset(token)
        assert log_context.snapshot() == {}

    def test_bind_drops_unknown_keys(self):
        token = log_context.bind(activity_id="a1", not_a_real_key="boom")
        try:
            assert log_context.snapshot() == {"activity_id": "a1"}
        finally:
            log_context.reset(token)

    def test_bind_drops_none_values(self):
        token = log_context.bind(activity_id="a1", agent_id=None)
        try:
            assert "agent_id" not in log_context.snapshot()
        finally:
            log_context.reset(token)

    def test_bind_coerces_values_to_str(self):
        token = log_context.bind(activity_id=42)
        try:
            assert log_context.snapshot()["activity_id"] == "42"
        finally:
            log_context.reset(token)

    def test_nested_bind_overlays_and_resets_lifo(self):
        outer = log_context.bind(activity_id="outer", user_id="u1")
        inner = log_context.bind(activity_id="inner", agent_id="agent-1")
        # Inner overrides activity_id, keeps user_id from outer, adds agent_id.
        assert log_context.snapshot() == {
            "activity_id": "inner",
            "user_id": "u1",
            "agent_id": "agent-1",
        }
        log_context.reset(inner)
        assert log_context.snapshot() == {"activity_id": "outer", "user_id": "u1"}
        log_context.reset(outer)
        assert log_context.snapshot() == {}

    def test_parent_activity_id_pattern(self):
        outer = log_context.bind(activity_id="parent-1")
        parent = log_context.snapshot().get("activity_id")
        inner = log_context.bind(activity_id="child-1", parent_activity_id=parent)
        try:
            snap = log_context.snapshot()
            assert snap["activity_id"] == "child-1"
            assert snap["parent_activity_id"] == "parent-1"
        finally:
            log_context.reset(inner)
            log_context.reset(outer)


@pytest.mark.unit
class TestContextFilter:

    def _make_record(self, **extra) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        for k, v in extra.items():
            setattr(record, k, v)
        return record

    def test_stamps_record_with_context(self):
        token = log_context.bind(activity_id="a1", user_id="u1")
        try:
            record = self._make_record()
            assert _ContextFilter().filter(record) is True
            assert record.activity_id == "a1"
            assert record.user_id == "u1"
        finally:
            log_context.reset(token)

    def test_explicit_extra_wins_over_context(self):
        # extra={} sets attributes on the record before the filter runs;
        # the filter must not overwrite them.
        token = log_context.bind(activity_id="from-ctx")
        try:
            record = self._make_record(activity_id="from-extra")
            _ContextFilter().filter(record)
            assert record.activity_id == "from-extra"
        finally:
            log_context.reset(token)

    def test_no_op_when_context_empty(self):
        record = self._make_record()
        assert _ContextFilter().filter(record) is True
        assert not hasattr(record, "activity_id")


@pytest.mark.unit
class TestFilterWiringEndToEnd:
    """Regression guard: the filter must be installed on handlers, not on
    loggers — Python skips logger-level filters during propagation.
    """

    def test_propagated_record_gets_stamped(self):
        from application.core.logging_config import _install_context_filter

        captured: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record):
                captured.append(record)

        root = logging.getLogger()
        saved_handlers = list(root.handlers)
        saved_level = root.level
        try:
            root.handlers = [_Capture()]
            root.setLevel(logging.DEBUG)
            _install_context_filter()

            child = logging.getLogger("test_log_context.propagation")
            child.setLevel(logging.DEBUG)

            token = log_context.bind(activity_id="propagated-id")
            try:
                child.info("from a child logger")
            finally:
                log_context.reset(token)

            assert captured, "Capture handler should have received the record"
            assert captured[0].activity_id == "propagated-id"
        finally:
            root.handlers = saved_handlers
            root.setLevel(saved_level)
