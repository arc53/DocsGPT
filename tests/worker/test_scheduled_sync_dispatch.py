"""A scheduled sync runs as its own task on the ingest queue, never inline in the beat task.

``schedule_syncs`` runs on the default queue next to chat and beat work; a
sync can take hours. ``sync_worker`` only enqueues one ``sync_source`` per
remote source, each under its own idempotency key, so a redelivered tick
does not enqueue a source twice.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from docsgpt import worker
from docsgpt.storage.db.repositories.sources import SourcesRepository

USER = "sam"
SITE = {"entries": [{"url": "https://x.io/", "mode": "site"}]}


def _must_not_run(*args, **kwargs):
    raise AssertionError("a scheduled sync must not run inside the beat task")


@pytest.fixture
def dispatched(monkeypatch) -> MagicMock:
    """Capture ``sync_source.apply_async`` and keep the sync itself from running inline."""
    apply_async = MagicMock(name="sync_source.apply_async")
    monkeypatch.setattr("docsgpt.api.user.tasks.sync_source.apply_async", apply_async)
    monkeypatch.setattr(worker, "sync", _must_not_run)
    monkeypatch.setattr(worker, "remote_worker", _must_not_run)
    return apply_async


def _seed(pg_conn, name: str, **fields) -> str:
    src = SourcesRepository(pg_conn).create(name, user_id=USER, sync_frequency="daily", **fields)
    return str(src["id"])


@pytest.mark.unit
class TestScheduledSyncDispatch:
    def test_each_remote_source_is_enqueued_and_none_runs_inline(
        self, pg_conn, patch_worker_db, task_self, dispatched,
    ):
        site = _seed(pg_conn, "Docs", type="website", remote_data=SITE, retriever="classic")
        url = _seed(pg_conn, "Feed", type="url", remote_data={"url": "http://example.com"})
        task_self.request.id = "tick-1"

        counts = worker.sync_worker(task_self, "daily")

        assert counts["total_sync_count"] == 2
        assert counts["sync_dispatched"] == 2
        assert counts["sync_success"] == counts["sync_failure"] == counts["sync_skipped"] == 0
        calls = {call.kwargs["kwargs"]["doc_id"]: call.kwargs for call in dispatched.call_args_list}
        assert set(calls) == {site, url}
        site_call = calls[site]["kwargs"]
        assert site_call["loader"] == "website"
        assert site_call["user"] == USER
        assert site_call["job_name"] == "Docs"
        assert site_call["sync_frequency"] == "daily"
        # A source busy with another job is left to the next schedule, without a notice.
        assert site_call["lock_wait_seconds"] == 0
        assert site_call["notify_skip"] is False
        keys = {call["kwargs"]["idempotency_key"] for call in calls.values()}
        assert len(keys) == 2

    def test_a_redelivered_tick_does_not_enqueue_a_source_twice(
        self, pg_conn, patch_worker_db, task_self, dispatched,
    ):
        _seed(pg_conn, "Docs", type="website", remote_data=SITE)
        task_self.request.id = "tick-1"

        first = worker.sync_worker(task_self, "daily")
        again = worker.sync_worker(task_self, "daily")

        assert first["sync_dispatched"] == 1
        assert again["sync_dispatched"] == 0
        assert again["sync_skipped"] == 1
        assert dispatched.call_count == 1

        task_self.request.id = "tick-2"
        assert worker.sync_worker(task_self, "daily")["sync_dispatched"] == 1
        assert dispatched.call_count == 2

    def test_a_failed_enqueue_releases_its_claim_and_the_rest_still_queue(
        self, pg_conn, patch_worker_db, task_self, dispatched,
    ):
        from docsgpt.storage.db.repositories.idempotency import IdempotencyRepository

        first = _seed(pg_conn, "Docs", type="website", remote_data=SITE)
        second = _seed(pg_conn, "Feed", type="url", remote_data={"url": "http://example.com"})
        task_self.request.id = "tick-1"

        def _broker_down_for_first(**kwargs):
            if kwargs["kwargs"]["doc_id"] == first:
                raise ConnectionError("broker down")

        dispatched.side_effect = _broker_down_for_first
        counts = worker.sync_worker(task_self, "daily")

        assert counts["sync_failure"] == 1
        assert counts["sync_dispatched"] == 1
        assert {call.kwargs["kwargs"]["doc_id"] for call in dispatched.call_args_list} == {first, second}
        repo = IdempotencyRepository(pg_conn)
        assert repo.get_task(f"scheduled-sync:tick-1:{first}") is None

        # The same tick, delivered again, queues the source it could not queue before.
        dispatched.side_effect = None
        dispatched.reset_mock()
        again = worker.sync_worker(task_self, "daily")
        assert again["sync_dispatched"] == 1
        assert [call.kwargs["kwargs"]["doc_id"] for call in dispatched.call_args_list] == [first]

    def test_the_queued_task_id_is_the_claimed_one(
        self, pg_conn, patch_worker_db, task_self, dispatched,
    ):
        from docsgpt.storage.db.repositories.idempotency import IdempotencyRepository

        _seed(pg_conn, "Docs", type="website", remote_data=SITE)
        task_self.request.id = "tick-1"
        worker.sync_worker(task_self, "daily")

        [call] = dispatched.call_args_list
        row = IdempotencyRepository(pg_conn).get_task(call.kwargs["kwargs"]["idempotency_key"])
        assert row["task_name"] == "sync_source"
        assert row["task_id"] == call.kwargs["task_id"]

    def test_a_connection_source_is_queued_with_its_connection(
        self, pg_conn, patch_worker_db, task_self, dispatched,
    ):
        from sqlalchemy import text

        cid = pg_conn.execute(text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status) "
            "VALUES (:u, 'github', 'github', 'oauth', 'connected') RETURNING id"
        ), {"u": USER}).scalar()
        doc_id = _seed(pg_conn, "acme/api", type="github", remote_data={"repo_url": "acme/api"})
        pg_conn.execute(
            text("UPDATE sources SET connection_id = :c WHERE id = CAST(:id AS uuid)"), {"c": cid, "id": doc_id},
        )

        counts = worker.sync_worker(task_self, "daily")

        assert counts["sync_dispatched"] == 1
        [call] = dispatched.call_args_list
        assert call.kwargs["kwargs"]["doc_id"] == doc_id
        assert call.kwargs["kwargs"]["connection_id"] == str(cid)


@pytest.mark.unit
class TestSyncSourceTask:
    def test_a_busy_source_is_skipped_without_a_notice(
        self, pg_conn, patch_worker_db, monkeypatch, busy_lock, published,
    ):
        from docsgpt.api.user.tasks import sync_source

        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website", sync_frequency="daily", remote_data=SITE,
        )
        waits = busy_lock()
        remote = MagicMock(name="remote_worker")
        monkeypatch.setattr(worker, "remote_worker", remote)

        result = sync_source.run(
            SITE, "Docs", USER, "website", "daily", "classic", str(src["id"]),
            lock_wait_seconds=0, notify_skip=False,
        )

        assert waits == [0]
        assert result == {"status": "skipped", "reason": "busy"}
        remote.assert_not_called()
        assert published == []

    def test_an_asked_for_sync_still_waits_and_tells_the_user(
        self, pg_conn, patch_worker_db, monkeypatch, busy_lock, published,
    ):
        from docsgpt.api.user.tasks import sync_source

        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website", sync_frequency="daily", remote_data=SITE,
        )
        waits = busy_lock()

        result = sync_source.run(SITE, "Docs", USER, "website", "daily", "classic", str(src["id"]))

        assert waits == [worker.WORKER_WAIT_SECONDS]
        assert result["reason"] == "busy"
        assert published.kinds() == ["source.ingest.failed"]
