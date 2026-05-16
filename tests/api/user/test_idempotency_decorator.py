"""Unit-level behavior of the per-Celery-task idempotency wrapper."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text


@contextmanager
def _patch_decorator_db(conn):
    """Route the wrapper's ``db_session`` / ``db_readonly`` at ``conn``."""

    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.idempotency.db_session", _yield
    ), patch(
        "application.api.user.idempotency.db_readonly", _yield
    ):
        yield


def _fake_celery_self(task_id="task-123"):
    """Minimal stand-in mirroring ``self.request.id`` on a Celery task."""
    self_ = MagicMock(name="celery_self")
    self_.request.id = task_id
    return self_


def _row_for(conn, key):
    return conn.execute(
        text(
            "SELECT task_name, task_id, status, result_json "
            "FROM task_dedup WHERE idempotency_key = :k"
        ),
        {"k": key},
    ).fetchone()


@pytest.mark.unit
class TestNoKey:
    def test_pass_through_no_db_hit(self, pg_conn):
        from application.api.user.idempotency import with_idempotency

        calls = []

        @with_idempotency(task_name="thing")
        def task(self, x, idempotency_key=None):
            calls.append(x)
            return {"x": x}

        with patch(
            "application.api.user.idempotency.db_session"
        ) as mock_session, patch(
            "application.api.user.idempotency.db_readonly"
        ) as mock_readonly:
            result = task(_fake_celery_self(), 7)

        assert result == {"x": 7}
        assert calls == [7]
        assert mock_session.call_count == 0
        assert mock_readonly.call_count == 0

    def test_empty_string_key_treated_as_absent(self, pg_conn):
        from application.api.user.idempotency import with_idempotency

        @with_idempotency(task_name="thing")
        def task(self, idempotency_key=None):
            return {"ran": True}

        with _patch_decorator_db(pg_conn):
            result = task(_fake_celery_self(), idempotency_key="")

        assert result == {"ran": True}
        count = pg_conn.execute(
            text("SELECT count(*) FROM task_dedup")
        ).scalar()
        assert count == 0


@pytest.mark.unit
class TestFirstRunWithKey:
    def test_records_completed_row(self, pg_conn):
        from application.api.user.idempotency import with_idempotency

        @with_idempotency(task_name="thing")
        def task(self, idempotency_key=None):
            return {"answer": 42}

        with _patch_decorator_db(pg_conn):
            result = task(_fake_celery_self("tid-1"), idempotency_key="k-first")

        assert result == {"answer": 42}
        row = _row_for(pg_conn, "k-first")
        assert row is not None
        assert row[0] == "thing"
        assert row[1] == "tid-1"
        assert row[2] == "completed"
        assert row[3] == {"answer": 42}


@pytest.mark.unit
class TestSecondRunCompletedShortCircuits:
    def test_returns_cached_without_invoking(self, pg_conn):
        from application.api.user.idempotency import with_idempotency

        invocations = {"count": 0}

        @with_idempotency(task_name="thing")
        def task(self, value, idempotency_key=None):
            invocations["count"] += 1
            return {"value": value, "n": invocations["count"]}

        with _patch_decorator_db(pg_conn):
            first = task(_fake_celery_self("tid-A"), 1, idempotency_key="k-rep")
            second = task(_fake_celery_self("tid-B"), 2, idempotency_key="k-rep")

        assert first == {"value": 1, "n": 1}
        assert second == first
        assert invocations["count"] == 1


@pytest.mark.unit
class TestFirstRunFails:
    def test_propagates_and_leaves_pending(self, pg_conn):
        """An exception propagates so Celery's retry policy fires; the row
        stays in ``pending`` (with bumped attempt_count) so the next
        attempt isn't gated as already-completed.
        """
        from application.api.user.idempotency import with_idempotency

        @with_idempotency(task_name="thing")
        def task(self, idempotency_key=None):
            raise RuntimeError("kaboom")

        with _patch_decorator_db(pg_conn), pytest.raises(RuntimeError, match="kaboom"):
            task(_fake_celery_self("tid-X"), idempotency_key="k-fail")

        row = _row_for(pg_conn, "k-fail")
        assert row is not None
        assert row[0] == "thing"
        assert row[2] == "pending"
        assert row[3] is None


@pytest.mark.unit
class TestPoisonLoopGuard:
    def test_refuses_after_max_attempts(self, pg_conn):
        from application.api.user.idempotency import (
            MAX_TASK_ATTEMPTS, with_idempotency,
        )

        invocations = {"count": 0}

        @with_idempotency(task_name="thing")
        def task(self, idempotency_key=None):
            invocations["count"] += 1
            raise RuntimeError("never converges")

        with _patch_decorator_db(pg_conn):
            for _ in range(MAX_TASK_ATTEMPTS):
                with pytest.raises(RuntimeError):
                    task(_fake_celery_self(), idempotency_key="k-poison")
            # The next entry trips the guard and *does not* call fn.
            result = task(_fake_celery_self(), idempotency_key="k-poison")
        assert invocations["count"] == MAX_TASK_ATTEMPTS
        assert result["success"] is False
        assert "poison-loop" in result["error"]
        row = _row_for(pg_conn, "k-poison")
        assert row[2] == "failed"


@pytest.mark.unit
class TestPreviousPendingReruns:
    def test_pending_row_does_not_short_circuit(self, pg_conn):
        """HTTP boundary writes ``pending``; on first arrival the wrapper still runs."""
        from application.api.user.idempotency import with_idempotency
        from application.storage.db.repositories.idempotency import (
            IdempotencyRepository,
        )

        IdempotencyRepository(pg_conn).claim_task(
            key="k-pending-prior", task_name="thing",
            task_id="enq-task-id",
        )

        invocations = {"count": 0}

        @with_idempotency(task_name="thing")
        def task(self, idempotency_key=None):
            invocations["count"] += 1
            return {"final": "answer"}

        with _patch_decorator_db(pg_conn):
            result = task(
                _fake_celery_self("worker-tid"),
                idempotency_key="k-pending-prior",
            )

        assert result == {"final": "answer"}
        assert invocations["count"] == 1
        row = _row_for(pg_conn, "k-pending-prior")
        assert row[2] == "completed"
        assert row[3] == {"final": "answer"}
        # The HTTP-claimed task_id is preserved across worker bumps so
        # losers still see the same predetermined id.
        assert row[1] == "enq-task-id"


@pytest.mark.unit
class TestRaceWithCompletedRow:
    """A second worker finishing after the first should not clobber the completed row."""

    def test_second_record_no_ops_on_completed(self, pg_conn):
        from application.api.user.idempotency import with_idempotency
        from application.storage.db.repositories.idempotency import (
            IdempotencyRepository,
        )

        # Seed a completed row directly via SQL (bypasses claim_task's
        # ON CONFLICT DO NOTHING guard so this row exists for the test).
        from sqlalchemy import text
        pg_conn.execute(
            text(
                "INSERT INTO task_dedup (idempotency_key, task_name, task_id, "
                "result_json, status) VALUES (:k, :tn, :tid, "
                "CAST(:rj AS jsonb), 'completed')"
            ),
            {
                "k": "k-race", "tn": "thing", "tid": "winner",
                "rj": '{"who": "winner"}',
            },
        )
        # IdempotencyRepository present but unused — keep as smoke check
        # the constructor still works.
        IdempotencyRepository(pg_conn)

        @with_idempotency(task_name="thing")
        def task(self, idempotency_key=None):
            return {"who": "loser"}

        with _patch_decorator_db(pg_conn):
            result = task(_fake_celery_self("loser-tid"), idempotency_key="k-race")

        assert result == {"who": "winner"}
        row = _row_for(pg_conn, "k-race")
        assert row[1] == "winner"
        assert row[3] == {"who": "winner"}


@pytest.mark.unit
class TestLiveLeaseDefersConcurrentRun:
    """Two-worker concurrency: Worker 1 owns a fresh lease, Worker 2's
    redelivery must ``self.retry`` instead of running the task body.
    """

    def test_second_worker_reraises_retry_without_running(self, pg_conn):
        from application.api.user.idempotency import (
            LEASE_TTL_SECONDS, with_idempotency,
        )
        from application.storage.db.repositories.idempotency import (
            IdempotencyRepository,
        )

        # Worker 1 has already claimed a fresh lease.
        IdempotencyRepository(pg_conn).try_claim_lease(
            key="k-busy", task_name="thing",
            task_id="t-worker-1", owner_id="worker-1",
        )

        invocations = {"count": 0}

        @with_idempotency(task_name="thing")
        def task(self, idempotency_key=None):
            invocations["count"] += 1
            return {"ran": True}

        # ``self.retry`` raises celery.exceptions.Retry; mirror that
        # contract here so the wrapper's ``raise self.retry(...)``
        # propagates a real exception.
        class _RetrySignal(Exception):
            pass

        worker2 = _fake_celery_self("t-worker-2")
        worker2.retry.side_effect = _RetrySignal("retry scheduled")

        with _patch_decorator_db(pg_conn), pytest.raises(_RetrySignal):
            task(worker2, idempotency_key="k-busy")

        # Task body never executed.
        assert invocations["count"] == 0
        # ``self.retry`` was invoked with countdown == lease TTL.
        worker2.retry.assert_called_once()
        kwargs = worker2.retry.call_args.kwargs
        assert kwargs.get("countdown") == LEASE_TTL_SECONDS

    def test_expired_lease_can_be_reclaimed_by_next_worker(self, pg_conn):
        """After the lease TTL elapses, the next attempt claims and runs
        — the original "Worker 1 died" recovery path.
        """
        from sqlalchemy import text

        from application.api.user.idempotency import with_idempotency
        from application.storage.db.repositories.idempotency import (
            IdempotencyRepository,
        )

        IdempotencyRepository(pg_conn).try_claim_lease(
            key="k-stale", task_name="thing",
            task_id="t-1", owner_id="dead-worker",
        )
        # Force the lease into the past.
        pg_conn.execute(
            text(
                "UPDATE task_dedup "
                "SET lease_expires_at = clock_timestamp() "
                "                       - make_interval(secs => 5) "
                "WHERE idempotency_key = :k"
            ),
            {"k": "k-stale"},
        )

        @with_idempotency(task_name="thing")
        def task(self, idempotency_key=None):
            return {"ran": True}

        with _patch_decorator_db(pg_conn):
            result = task(_fake_celery_self("t-2"), idempotency_key="k-stale")

        assert result == {"ran": True}
        row = _row_for(pg_conn, "k-stale")
        assert row[2] == "completed"


@pytest.mark.unit
class TestExceptionPathReleasesLease:
    """When ``fn`` raises, the lease is dropped so the next attempt
    doesn't have to wait the full TTL before re-claiming.
    """

    def test_release_clears_lease_owner(self, pg_conn):
        from sqlalchemy import text

        from application.api.user.idempotency import with_idempotency

        @with_idempotency(task_name="thing")
        def task(self, idempotency_key=None):
            raise RuntimeError("boom")

        with _patch_decorator_db(pg_conn), pytest.raises(RuntimeError):
            task(_fake_celery_self("tid-1"), idempotency_key="k-released")

        row = pg_conn.execute(
            text(
                "SELECT status, lease_owner_id, lease_expires_at "
                "FROM task_dedup WHERE idempotency_key = :k"
            ),
            {"k": "k-released"},
        ).fetchone()
        assert row[0] == "pending"
        assert row[1] is None
        assert row[2] is None

    def test_next_attempt_can_reclaim_after_release(self, pg_conn):
        """Sequential retries don't get blocked by the lease TTL."""
        from application.api.user.idempotency import with_idempotency

        invocations = {"count": 0}

        @with_idempotency(task_name="thing")
        def task(self, idempotency_key=None):
            invocations["count"] += 1
            if invocations["count"] < 3:
                raise RuntimeError("transient")
            return {"finally": True}

        with _patch_decorator_db(pg_conn):
            for _ in range(2):
                with pytest.raises(RuntimeError):
                    task(_fake_celery_self(), idempotency_key="k-converge")
            result = task(_fake_celery_self(), idempotency_key="k-converge")

        assert invocations["count"] == 3
        assert result == {"finally": True}
        row = _row_for(pg_conn, "k-converge")
        assert row[2] == "completed"


@pytest.mark.unit
class TestSuccessfulRunClearsLease:
    """``finalize_task`` clears the lease columns so operator dashboards
    don't show stale ``lease_expires_at`` on completed rows.
    """

    def test_completed_row_has_null_lease(self, pg_conn):
        from sqlalchemy import text

        from application.api.user.idempotency import with_idempotency

        @with_idempotency(task_name="thing")
        def task(self, idempotency_key=None):
            return {"ok": True}

        with _patch_decorator_db(pg_conn):
            task(_fake_celery_self("tid-1"), idempotency_key="k-done")

        row = pg_conn.execute(
            text(
                "SELECT status, lease_owner_id, lease_expires_at "
                "FROM task_dedup WHERE idempotency_key = :k"
            ),
            {"k": "k-done"},
        ).fetchone()
        assert row[0] == "completed"
        assert row[1] is None
        assert row[2] is None
