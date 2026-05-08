"""Guardrail tests for :mod:`application.storage.db.session`.

Two invariants are covered here:

* :func:`db_readonly` must actively *enforce* read-only on the connection
  at the Postgres layer — not by convention. A write inside the block
  must raise, not silently mutate.
* The engine installs a server-side ``statement_timeout`` so a runaway
  query has a hard wall-clock cap.

These tests run against a real ephemeral Postgres (via ``pg_engine``)
rather than mocks. They rebuild the module-level engine cache so the
engine factory's ``statement_timeout`` setup is actually exercised.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InternalError, OperationalError

from application.storage.db import engine as engine_module
from application.storage.db.engine import STATEMENT_TIMEOUT_MS
from application.storage.db.session import db_readonly, db_session


# ---------------------------------------------------------------------------
# Helper: wire the session module's engine cache to the ephemeral Postgres
# for the duration of a test.
# ---------------------------------------------------------------------------


@pytest.fixture()
def wired_engine(pg_engine, monkeypatch):
    """Rebuild the module-level engine against the ephemeral DB.

    ``pg_engine`` already creates its own SQLAlchemy engine, but that
    engine does not install our ``statement_timeout`` connect-event
    hook. We reconstruct one via :func:`get_engine` so the real
    production factory code path is exercised.
    """
    # Reset the module-level cache so get_engine() re-reads the URL and
    # applies the production connect_args.
    monkeypatch.setattr(engine_module, "_engine", None)
    eng = engine_module.get_engine()
    yield eng
    # Clean up so other tests don't inherit our engine.
    eng.dispose()
    monkeypatch.setattr(engine_module, "_engine", None)


# ---------------------------------------------------------------------------
# db_readonly enforcement
# ---------------------------------------------------------------------------


class TestDbReadonlyEnforcement:
    def test_select_is_allowed(self, wired_engine):
        with db_readonly() as conn:
            row = conn.execute(text("SELECT 1 AS n")).one()
        assert row.n == 1

    def test_insert_raises_readonly_violation(self, wired_engine):
        """A write inside ``db_readonly`` must blow up, not silently succeed.

        Postgres raises SQLSTATE ``25006`` (``read_only_sql_transaction``)
        which SQLAlchemy surfaces as ``InternalError``. We assert on the
        SQLSTATE / message rather than on a schema error, so a future
        rename of ``users`` can't accidentally turn this into a
        false-positive.
        """
        with pytest.raises(DBAPIError) as exc_info:
            with db_readonly() as conn:
                conn.execute(
                    text(
                        "INSERT INTO users (user_id, agent_preferences) "
                        "VALUES (:uid, '{}'::jsonb)"
                    ),
                    {"uid": "should-never-be-written"},
                )

        # psycopg3 exposes sqlstate on the underlying DBAPI error.
        orig = exc_info.value.orig
        assert getattr(orig, "sqlstate", None) == "25006" or (
            "read-only transaction" in str(exc_info.value).lower()
        )
        # And the SA wrapper class is the read-only branch, not a generic
        # ProgrammingError / DataError.
        assert isinstance(exc_info.value, InternalError)

    def test_update_raises_readonly_violation(self, wired_engine):
        with pytest.raises(DBAPIError) as exc_info:
            with db_readonly() as conn:
                conn.execute(
                    text("UPDATE users SET agent_preferences = '{}'::jsonb")
                )
        assert "read-only transaction" in str(exc_info.value).lower()

    def test_db_session_still_allows_writes(self, wired_engine):
        """Regression: tightening db_readonly must not leak into db_session."""
        with db_session() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (user_id, agent_preferences) "
                    "VALUES (:uid, '{}'::jsonb)"
                ),
                {"uid": "writes-still-work"},
            )
        # Confirm it really landed — use a fresh session so we're not
        # reading from the same txn that wrote.
        with db_session() as conn:
            row = conn.execute(
                text("SELECT user_id FROM users WHERE user_id = :uid"),
                {"uid": "writes-still-work"},
            ).first()
        assert row is not None
        # Clean up so we don't leak state to sibling tests that share the
        # ephemeral DB across the session.
        with db_session() as conn:
            conn.execute(
                text("DELETE FROM users WHERE user_id = :uid"),
                {"uid": "writes-still-work"},
            )


# ---------------------------------------------------------------------------
# statement_timeout
# ---------------------------------------------------------------------------


class TestStatementTimeout:
    """The engine factory installs ``statement_timeout`` on every new
    connection.

    We verify two things:

    1. ``SHOW statement_timeout`` on a fresh connection returns the
       configured value. This is cheap and deterministic — no sleeps.
    2. A query that exceeds a tight per-txn override raises a timeout
       error. We override ``SET LOCAL statement_timeout = '100ms'``
       inside the test itself so the suite stays fast; that also proves
       the knob is respected end-to-end.
    """

    def test_show_statement_timeout_matches_engine_setting(self, wired_engine):
        with db_session() as conn:
            value = conn.execute(text("SHOW statement_timeout")).scalar()
        # Postgres normalizes "30000" (ms) → "30s".
        assert value == f"{STATEMENT_TIMEOUT_MS // 1000}s"

    def test_show_statement_timeout_also_applied_to_readonly(self, wired_engine):
        with db_readonly() as conn:
            value = conn.execute(text("SHOW statement_timeout")).scalar()
        assert value == f"{STATEMENT_TIMEOUT_MS // 1000}s"

    def test_statement_timeout_actually_cancels_runaway_query(self, wired_engine):
        """End-to-end: a slow query under a tight override gets killed."""
        with pytest.raises((OperationalError, DBAPIError)) as exc_info:
            with db_session() as conn:
                conn.execute(text("SET LOCAL statement_timeout = '100ms'"))
                conn.execute(text("SELECT pg_sleep(2)"))
        assert (
            "statement timeout" in str(exc_info.value).lower()
            or "canceling statement" in str(exc_info.value).lower()
        )


# ---------------------------------------------------------------------------
# Engine factory: connect_args are on the engine we hand out
# ---------------------------------------------------------------------------


class TestEngineConnectArgs:
    def test_constant_defines_expected_timeout(self):
        """Pin the public constant so accidental edits get caught.

        The real end-to-end coverage is the ``SHOW`` test above; this is
        a cheap guard against someone lowering the timeout to a value
        that would break production hot paths without reviewing it.
        """
        # 30s is the documented default. If this needs to change, update
        # the constant *and* this test, and explain why in the PR.
        assert STATEMENT_TIMEOUT_MS == 30_000
