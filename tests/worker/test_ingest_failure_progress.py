"""A failed ingest closes its ``ingest_chunk_progress`` row.

Without it the row stays ``active`` and unfinished, so Activity › Now lists
the ingest as embedding and the sources list as processing until the
reconciler marks it stalled, about 30 minutes later and only with beat.
The row closes before ``source.ingest.failed`` goes out: the pages refetch
on that event.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.ingest_chunk_progress import (
    IngestChunkProgressRepository,
)
from tests.worker.test_worker_sse_publishes import (
    _patch_ingest_pipeline_min,
    _stub_connector_pipeline,
    _stub_remote_pipeline,
)


@pytest.fixture
def steps(monkeypatch):
    """Record closes and publishes, in order, as ``(what, source_id)``."""
    from docsgpt import worker

    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        worker,
        "close_failed_ingest_progress",
        lambda source_id, **kw: seen.append(("close", str(source_id))),
    )
    monkeypatch.setattr(
        worker,
        "publish_user_event",
        lambda user, kind, payload, **kw: seen.append((kind, str(payload.get("source_id")))),
    )
    return seen


def _closed_before_failed(steps: list[tuple[str, str]]) -> str:
    """Assert the row closed right before the failed event; return the source id."""
    failed = [i for i, (kind, _) in enumerate(steps) if kind == "source.ingest.failed"]
    assert len(failed) == 1
    i = failed[0]
    assert steps[i - 1] == ("close", steps[i][1])
    return steps[i][1]


@pytest.mark.unit
class TestFailedIngestClosesProgress:
    def test_ingest_worker_closes_the_row(self, patch_worker_db, pg_conn, task_self, monkeypatch):
        from docsgpt import worker

        monkeypatch.setattr(worker, "publish_user_event", lambda *a, **kw: None)
        source_id = str(uuid.uuid4())
        IngestChunkProgressRepository(pg_conn).init_progress(source_id, 10)
        _patch_ingest_pipeline_min(monkeypatch, raise_in_pipeline=True)

        with pytest.raises(RuntimeError, match="pipeline kaboom"):
            worker.ingest_worker(
                task_self,
                directory="inputs",
                formats=[".txt"],
                job_name="job1",
                file_path="inputs/eve/job1/a.txt",
                filename="a.txt",
                user="eve",
                retriever="classic",
                source_id=source_id,
            )

        status = pg_conn.execute(
            text("SELECT status FROM ingest_chunk_progress WHERE source_id = CAST(:id AS uuid)"),
            {"id": source_id},
        ).scalar()
        assert status == "stalled"

    def _failed_ingest_status(self, pg_conn, task_self, monkeypatch) -> str:
        """Fail an ingest with a half-embedded row; return the row's status after."""
        from docsgpt import worker

        monkeypatch.setattr(worker, "publish_user_event", lambda *a, **kw: None)
        source_id = str(uuid.uuid4())
        IngestChunkProgressRepository(pg_conn).init_progress(source_id, 10)
        _patch_ingest_pipeline_min(monkeypatch, raise_in_pipeline=True)
        with pytest.raises(RuntimeError):
            worker.ingest_worker(
                task_self,
                directory="inputs",
                formats=[".txt"],
                job_name="job1",
                file_path="inputs/eve/job1/a.txt",
                filename="a.txt",
                user="eve",
                retriever="classic",
                source_id=source_id,
            )
        return pg_conn.execute(
            text("SELECT status FROM ingest_chunk_progress WHERE source_id = CAST(:id AS uuid)"),
            {"id": source_id},
        ).scalar()

    @staticmethod
    def _durable(task_self, *, retries: int, dont_autoretry_for: tuple = ()):
        task_self.request.retries = retries
        task_self.max_retries = 3
        task_self.autoretry_for = (Exception,)
        task_self.dont_autoretry_for = dont_autoretry_for
        return task_self

    def test_a_failure_celery_will_retry_leaves_the_row_open(
        self, patch_worker_db, pg_conn, task_self, monkeypatch
    ):
        # Closed, the source would read as failed through the retry wait.
        task = self._durable(task_self, retries=1)
        assert self._failed_ingest_status(pg_conn, task, monkeypatch) == "active"

    def test_the_last_attempt_closes_the_row(self, patch_worker_db, pg_conn, task_self, monkeypatch):
        task = self._durable(task_self, retries=3)
        assert self._failed_ingest_status(pg_conn, task, monkeypatch) == "stalled"

    def test_an_error_celery_never_retries_closes_the_row(
        self, patch_worker_db, pg_conn, task_self, monkeypatch
    ):
        task = self._durable(task_self, retries=0, dont_autoretry_for=(RuntimeError,))
        assert self._failed_ingest_status(pg_conn, task, monkeypatch) == "stalled"

    def test_ingest_worker_closes_before_publishing(self, patch_worker_db, task_self, monkeypatch, steps):
        from docsgpt import worker

        source_id = str(uuid.uuid4())
        _patch_ingest_pipeline_min(monkeypatch, raise_in_pipeline=True)
        with pytest.raises(RuntimeError):
            worker.ingest_worker(
                task_self,
                directory="inputs",
                formats=[".txt"],
                job_name="job1",
                file_path="inputs/eve/job1/a.txt",
                filename="a.txt",
                user="eve",
                retriever="classic",
                source_id=source_id,
            )
        assert _closed_before_failed(steps) == source_id

    def test_reingest_closes_the_row(self, patch_worker_db, task_self, steps):
        from docsgpt import worker

        source_id = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(ValueError):
            worker.reingest_source_worker(task_self, source_id, "ghost")
        assert _closed_before_failed(steps) == source_id

    def test_remote_worker_closes_the_row(self, tmp_path, task_self, monkeypatch, steps):
        from docsgpt import worker

        _stub_remote_pipeline(monkeypatch, raise_in_pipeline=True)
        with pytest.raises(RuntimeError):
            worker.remote_worker(
                task_self,
                {"urls": ["http://example.com"]},
                "my-remote",
                "bob",
                "crawler",
                directory=str(tmp_path / "temp"),
                operation_mode="upload",
            )
        _closed_before_failed(steps)

    def test_connector_ingest_closes_the_row(self, task_self, monkeypatch, steps):
        from docsgpt import worker

        _stub_connector_pipeline(monkeypatch)

        def _boom(*a, **kw):
            raise RuntimeError("connector kaboom")

        monkeypatch.setattr(worker, "embed_and_store_documents", _boom)
        with pytest.raises(RuntimeError, match="connector kaboom"):
            worker.ingest_connector(
                task_self,
                "gdrive-folder",
                "dave",
                "google_drive",
                session_token="tok",
                file_ids=["f1"],
                folder_ids=[],
                operation_mode="upload",
            )
        _closed_before_failed(steps)


@pytest.mark.unit
def test_the_poison_guard_closes_the_row():
    from docsgpt.api.user.tasks import _emit_ingest_poison_event

    seen: list[tuple[str, str]] = []
    with patch(
        "docsgpt.worker.close_failed_ingest_progress",
        side_effect=lambda source_id: seen.append(("close", source_id)),
    ), patch(
        "docsgpt.events.publisher.publish_user_event",
        side_effect=lambda user, kind, payload, **kw: seen.append((kind, payload["source_id"])),
    ):
        _emit_ingest_poison_event("ingest", {"user": "u1", "source_id": "src-9"})
    assert seen == [("close", "src-9"), ("source.ingest.failed", "src-9")]
