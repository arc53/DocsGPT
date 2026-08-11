"""Tests for IdempotencyRepository against a real Postgres instance.

The HTTP-boundary tests at ``tests/api/user/{sources,agents}/...`` cover
the upload/webhook flows; this file pins the repository contract:

- TTL-aware upsert: stale-row replacement is atomic, fresh-row conflict
  still returns ``None``.
- ``cleanup_expired`` deletes only past-TTL rows from both tables.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from application.storage.db.repositories.idempotency import IdempotencyRepository


def _repo(conn) -> IdempotencyRepository:
    return IdempotencyRepository(conn)


def _backdate_task(conn, key: str, secs_ago: int) -> None:
    """Force ``task_dedup.created_at`` into the past — the only way to
    drive TTL-aware code paths inside a single test transaction.
    """
    conn.execute(
        text(
            "UPDATE task_dedup "
            "SET created_at = clock_timestamp() "
            "             - make_interval(secs => :secs) "
            "WHERE idempotency_key = :key"
        ),
        {"secs": secs_ago, "key": key},
    )


def _backdate_webhook(conn, key: str, secs_ago: int) -> None:
    conn.execute(
        text(
            "UPDATE webhook_dedup "
            "SET created_at = clock_timestamp() "
            "             - make_interval(secs => :secs) "
            "WHERE idempotency_key = :key"
        ),
        {"secs": secs_ago, "key": key},
    )


def _read_task(conn, key: str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM task_dedup WHERE idempotency_key = :k"),
        {"k": key},
    ).fetchone()
    if row is None:
        return None
    return dict(row._mapping)


def _read_webhook(conn, key: str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM webhook_dedup WHERE idempotency_key = :k"),
        {"k": key},
    ).fetchone()
    if row is None:
        return None
    return dict(row._mapping)


# ----------------------------------------------------------------------
# claim_task
# ----------------------------------------------------------------------


class TestClaimTask:
    def test_fresh_key_returns_row(self, pg_conn):
        repo = _repo(pg_conn)
        row = repo.claim_task(
            key="k1", task_name="ingest", task_id="task-1",
        )
        assert row is not None
        assert row["task_id"] == "task-1"
        assert row["task_name"] == "ingest"
        assert row["status"] == "pending"
        assert row["attempt_count"] == 0
        assert row["result_json"] is None

    def test_same_key_within_ttl_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        repo.claim_task(key="k2", task_name="ingest", task_id="task-1")
        # Second writer with the same key, row still fresh.
        loser = repo.claim_task(
            key="k2", task_name="ingest", task_id="task-2",
        )
        assert loser is None
        # The first writer's task_id stays — the loser must not see "deduplicated".
        existing = _read_task(pg_conn, "k2")
        assert existing["task_id"] == "task-1"

    def test_stale_row_is_replaced(self, pg_conn):
        """The bug-fix: a past-TTL row no longer blocks new work."""
        repo = _repo(pg_conn)
        repo.claim_task(key="k3", task_name="ingest", task_id="old-id")
        # 25h old — past the 24h TTL.
        _backdate_task(pg_conn, "k3", secs_ago=25 * 3600)

        winner = repo.claim_task(
            key="k3", task_name="ingest_remote", task_id="new-id",
        )
        assert winner is not None
        # Stale-row replacement resets the row to fresh-claim defaults.
        assert winner["task_id"] == "new-id"
        assert winner["task_name"] == "ingest_remote"
        assert winner["status"] == "pending"
        assert winner["attempt_count"] == 0
        assert winner["result_json"] is None

        # Disk state matches the returned row.
        on_disk = _read_task(pg_conn, "k3")
        assert on_disk["task_id"] == "new-id"

    def test_completed_stale_row_is_replaced(self, pg_conn):
        """A *completed* stale row also gets replaced — otherwise a
        24h-old success would forever block re-runs of the same key.
        """
        repo = _repo(pg_conn)
        repo.claim_task(key="k4", task_name="ingest", task_id="t-old")
        repo.finalize_task(
            key="k4", result_json={"ok": True}, status="completed",
        )
        _backdate_task(pg_conn, "k4", secs_ago=25 * 3600)

        winner = repo.claim_task(
            key="k4", task_name="ingest", task_id="t-new",
        )
        assert winner is not None
        assert winner["status"] == "pending"
        assert winner["result_json"] is None
        assert winner["task_id"] == "t-new"

    def test_just_under_ttl_does_not_replace(self, pg_conn):
        """Boundary case: 23h59m old must still block."""
        repo = _repo(pg_conn)
        repo.claim_task(key="k5", task_name="ingest", task_id="t-orig")
        _backdate_task(pg_conn, "k5", secs_ago=24 * 3600 - 60)  # 23h59m

        loser = repo.claim_task(
            key="k5", task_name="ingest", task_id="t-replace",
        )
        assert loser is None
        on_disk = _read_task(pg_conn, "k5")
        assert on_disk["task_id"] == "t-orig"

    def test_failed_row_is_replaced_within_ttl(self, pg_conn):
        """Regression: a fresh ``status='failed'`` row (poison-loop
        guard or reconciler-promoted) must let the next same-key
        request re-claim immediately. Pre-fix the WHERE clause only
        gated on TTL, so failed rows blocked retries for 24 h while
        the HTTP path returned a stale ``task_id`` for a task that
        had already terminated.
        """
        repo = _repo(pg_conn)
        repo.claim_task(key="k-failed", task_name="ingest", task_id="orig")
        # Pretend the worker hit the poison-loop guard or the
        # reconciler escalated the row.
        ok = repo.finalize_task(
            key="k-failed",
            result_json={"success": False, "error": "abandoned"},
            status="failed",
        )
        assert ok is True

        # Fresh retry should win.
        winner = repo.claim_task(
            key="k-failed", task_name="ingest", task_id="retry",
        )
        assert winner is not None
        assert winner["task_id"] == "retry"
        assert winner["status"] == "pending"
        # Replacement also resets the cached error and attempts.
        assert winner["result_json"] is None
        assert winner["attempt_count"] == 0

    def test_completed_row_still_blocks_within_ttl(self, pg_conn):
        """Symmetric guard: success caching must remain. ``completed``
        rows continue to block until TTL expires.
        """
        repo = _repo(pg_conn)
        repo.claim_task(key="k-done", task_name="ingest", task_id="winner-id")
        repo.finalize_task(
            key="k-done", result_json={"ok": True}, status="completed",
        )
        loser = repo.claim_task(
            key="k-done", task_name="ingest", task_id="latecomer",
        )
        assert loser is None
        row = _read_task(pg_conn, "k-done")
        assert row["status"] == "completed"
        assert row["task_id"] == "winner-id"

    def test_pending_row_still_blocks_within_ttl(self, pg_conn):
        """Concurrency contract: while a task is in flight, same-key
        requests still collapse onto the in-flight ``task_id``.
        """
        repo = _repo(pg_conn)
        repo.claim_task(key="k-flight", task_name="ingest", task_id="t-1")
        loser = repo.claim_task(
            key="k-flight", task_name="ingest", task_id="t-2",
        )
        assert loser is None
        row = _read_task(pg_conn, "k-flight")
        assert row["task_id"] == "t-1"


# ----------------------------------------------------------------------
# record_webhook
# ----------------------------------------------------------------------


class TestRecordWebhook:
    def test_fresh_key_returns_row(self, pg_conn):
        repo = _repo(pg_conn)
        agent_id = str(uuid.uuid4())
        row = repo.record_webhook(
            key="w1", agent_id=agent_id, task_id="t-1",
            response_json={"success": True, "task_id": "t-1"},
        )
        assert row is not None
        assert row["task_id"] == "t-1"
        # row_to_dict normalises UUID → str.
        assert row["agent_id"] == agent_id

    def test_same_key_within_ttl_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        agent_id = str(uuid.uuid4())
        repo.record_webhook(
            key="w2", agent_id=agent_id, task_id="t-1",
            response_json={"success": True, "task_id": "t-1"},
        )
        loser = repo.record_webhook(
            key="w2", agent_id=agent_id, task_id="t-2",
            response_json={"success": True, "task_id": "t-2"},
        )
        assert loser is None
        existing = _read_webhook(pg_conn, "w2")
        assert existing["task_id"] == "t-1"

    def test_stale_row_is_replaced(self, pg_conn):
        repo = _repo(pg_conn)
        agent_a = str(uuid.uuid4())
        agent_b = str(uuid.uuid4())
        repo.record_webhook(
            key="w3", agent_id=agent_a, task_id="t-old",
            response_json={"success": True, "task_id": "t-old"},
        )
        _backdate_webhook(pg_conn, "w3", secs_ago=25 * 3600)

        winner = repo.record_webhook(
            key="w3", agent_id=agent_b, task_id="t-new",
            response_json={"success": True, "task_id": "t-new"},
        )
        assert winner is not None
        assert winner["task_id"] == "t-new"
        assert winner["agent_id"] == agent_b
        # response_json is JSONB on read — already a dict.
        assert winner["response_json"] == {"success": True, "task_id": "t-new"}


# ----------------------------------------------------------------------
# cleanup_expired
# ----------------------------------------------------------------------


class TestCleanupExpired:
    def test_returns_zero_counts_when_empty(self, pg_conn):
        repo = _repo(pg_conn)
        counts = repo.cleanup_expired()
        assert counts == {"task_dedup_deleted": 0, "webhook_dedup_deleted": 0}

    def test_only_deletes_past_ttl_rows(self, pg_conn):
        repo = _repo(pg_conn)
        agent_id = str(uuid.uuid4())

        # task_dedup: one fresh, one past-TTL.
        repo.claim_task(key="t-fresh", task_name="ingest", task_id="t1")
        repo.claim_task(key="t-stale", task_name="ingest", task_id="t2")
        _backdate_task(pg_conn, "t-stale", secs_ago=25 * 3600)

        # webhook_dedup: one fresh, one past-TTL.
        repo.record_webhook(
            key="w-fresh", agent_id=agent_id, task_id="w1",
            response_json={"success": True},
        )
        repo.record_webhook(
            key="w-stale", agent_id=agent_id, task_id="w2",
            response_json={"success": True},
        )
        _backdate_webhook(pg_conn, "w-stale", secs_ago=25 * 3600)

        counts = repo.cleanup_expired()
        assert counts == {"task_dedup_deleted": 1, "webhook_dedup_deleted": 1}

        # Fresh rows survive.
        assert _read_task(pg_conn, "t-fresh") is not None
        assert _read_webhook(pg_conn, "w-fresh") is not None
        # Stale rows are gone.
        assert _read_task(pg_conn, "t-stale") is None
        assert _read_webhook(pg_conn, "w-stale") is None

    def test_boundary_just_under_ttl_survives(self, pg_conn):
        repo = _repo(pg_conn)
        repo.claim_task(key="t-edge", task_name="ingest", task_id="t1")
        _backdate_task(pg_conn, "t-edge", secs_ago=24 * 3600 - 60)  # 23h59m

        counts = repo.cleanup_expired()
        assert counts["task_dedup_deleted"] == 0
        assert _read_task(pg_conn, "t-edge") is not None


# ----------------------------------------------------------------------
# try_claim_lease / refresh_lease / release_lease
# ----------------------------------------------------------------------


def _expire_lease(conn, key: str, secs_ago: int = 1) -> None:
    """Force ``lease_expires_at`` into the past — the only way to
    drive lease-expired code paths inside a single test transaction.
    """
    conn.execute(
        text(
            "UPDATE task_dedup "
            "SET lease_expires_at = clock_timestamp() "
            "                       - make_interval(secs => :secs) "
            "WHERE idempotency_key = :key"
        ),
        {"secs": secs_ago, "key": key},
    )


class TestTryClaimLease:
    def test_fresh_key_inserts_with_lease(self, pg_conn):
        repo = _repo(pg_conn)
        attempt = repo.try_claim_lease(
            key="lease-fresh", task_name="ingest",
            task_id="task-1", owner_id="owner-A",
        )
        assert attempt == 1
        row = _read_task(pg_conn, "lease-fresh")
        assert row["lease_owner_id"] == "owner-A"
        assert row["lease_expires_at"] is not None
        assert row["status"] == "pending"

    def test_live_lease_refuses_second_claimant(self, pg_conn):
        """Worker 1 owns a fresh lease; Worker 2 must get None back so
        the wrapper can ``self.retry(countdown=...)`` instead of running.
        """
        repo = _repo(pg_conn)
        repo.try_claim_lease(
            key="lease-busy", task_name="ingest",
            task_id="t1", owner_id="worker-1",
        )
        loser = repo.try_claim_lease(
            key="lease-busy", task_name="ingest",
            task_id="t1", owner_id="worker-2",
        )
        assert loser is None
        # Original owner intact.
        row = _read_task(pg_conn, "lease-busy")
        assert row["lease_owner_id"] == "worker-1"

    def test_expired_lease_can_be_reclaimed(self, pg_conn):
        """A crashed worker's lease (past TTL) becomes fair game; the
        new claimant takes ownership and bumps ``attempt_count``.
        """
        repo = _repo(pg_conn)
        repo.try_claim_lease(
            key="lease-stale", task_name="ingest",
            task_id="t1", owner_id="dead-worker",
        )
        _expire_lease(pg_conn, "lease-stale", secs_ago=1)

        attempt = repo.try_claim_lease(
            key="lease-stale", task_name="ingest",
            task_id="t1", owner_id="new-worker",
        )
        # First insert was 1; conflict path bumps to 2.
        assert attempt == 2
        row = _read_task(pg_conn, "lease-stale")
        assert row["lease_owner_id"] == "new-worker"

    def test_completed_row_does_not_reset_lease(self, pg_conn):
        """``try_claim_lease`` must not touch a completed row — the
        cache short-circuit (``_lookup_completed``) is the right path
        for that case, not a lease takeover.
        """
        repo = _repo(pg_conn)
        repo.try_claim_lease(
            key="lease-done", task_name="ingest",
            task_id="t1", owner_id="winner",
        )
        repo.finalize_task(
            key="lease-done", result_json={"ok": True}, status="completed",
        )

        attempt = repo.try_claim_lease(
            key="lease-done", task_name="ingest",
            task_id="t2", owner_id="latecomer",
        )
        assert attempt is None
        row = _read_task(pg_conn, "lease-done")
        assert row["status"] == "completed"
        # finalize_task cleared the lease columns.
        assert row["lease_owner_id"] is None

    def test_pending_row_with_null_lease_can_be_claimed(self, pg_conn):
        """The HTTP-side ``claim_task`` writes a pending row with NULL
        lease columns. The wrapper's first entry for the same key must
        be able to take the lease.
        """
        repo = _repo(pg_conn)
        repo.claim_task(
            key="lease-http", task_name="ingest", task_id="enq-id",
        )

        attempt = repo.try_claim_lease(
            key="lease-http", task_name="ingest",
            task_id="enq-id", owner_id="worker-1",
        )
        assert attempt == 1
        row = _read_task(pg_conn, "lease-http")
        assert row["lease_owner_id"] == "worker-1"


class TestRefreshLease:
    def test_owner_refreshes_lease(self, pg_conn):
        repo = _repo(pg_conn)
        repo.try_claim_lease(
            key="hb", task_name="ingest", task_id="t1", owner_id="owner-X",
        )
        before = _read_task(pg_conn, "hb")["lease_expires_at"]
        # Push the existing lease into the past so the refresh has
        # something to advance.
        _expire_lease(pg_conn, "hb", secs_ago=10)

        ok = repo.refresh_lease("hb", "owner-X", ttl_seconds=60)
        assert ok is True
        after = _read_task(pg_conn, "hb")["lease_expires_at"]
        assert after > before

    def test_non_owner_cannot_refresh(self, pg_conn):
        """A worker that lost the lease via expiry must not be able to
        refresh someone else's claim.
        """
        repo = _repo(pg_conn)
        repo.try_claim_lease(
            key="hb-lost", task_name="ingest",
            task_id="t1", owner_id="owner-X",
        )
        ok = repo.refresh_lease("hb-lost", "different-owner")
        assert ok is False

    def test_completed_row_cannot_be_refreshed(self, pg_conn):
        """Finalised rows reject refresh — the lease is moot at that point."""
        repo = _repo(pg_conn)
        repo.try_claim_lease(
            key="hb-done", task_name="ingest",
            task_id="t1", owner_id="owner-X",
        )
        repo.finalize_task(
            key="hb-done", result_json={"ok": True}, status="completed",
        )
        assert repo.refresh_lease("hb-done", "owner-X") is False


class TestReleaseLease:
    def test_owner_releases_lease(self, pg_conn):
        repo = _repo(pg_conn)
        repo.try_claim_lease(
            key="rel", task_name="ingest", task_id="t1", owner_id="owner-X",
        )
        ok = repo.release_lease("rel", "owner-X")
        assert ok is True
        row = _read_task(pg_conn, "rel")
        assert row["lease_owner_id"] is None
        assert row["lease_expires_at"] is None
        # Status stays pending so the next attempt can re-claim.
        assert row["status"] == "pending"

    def test_non_owner_release_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        repo.try_claim_lease(
            key="rel-other", task_name="ingest",
            task_id="t1", owner_id="owner-X",
        )
        ok = repo.release_lease("rel-other", "different-owner")
        assert ok is False
        row = _read_task(pg_conn, "rel-other")
        # Original owner intact.
        assert row["lease_owner_id"] == "owner-X"


class TestFinalizeClearsLease:
    def test_completed_clears_lease_columns(self, pg_conn):
        repo = _repo(pg_conn)
        repo.try_claim_lease(
            key="fin-clear", task_name="ingest",
            task_id="t1", owner_id="owner-X",
        )
        repo.finalize_task(
            key="fin-clear", result_json={"ok": True}, status="completed",
        )
        row = _read_task(pg_conn, "fin-clear")
        assert row["status"] == "completed"
        assert row["lease_owner_id"] is None
        assert row["lease_expires_at"] is None
