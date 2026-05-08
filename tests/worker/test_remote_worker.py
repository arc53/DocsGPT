"""Smoke tests for ``application.worker.remote_worker`` and ``sync_worker``.

``remote_worker`` in ``sync`` mode does one PG write: it bumps
``sources.date`` on the referenced source row to ``now()``. That's the
side-effect we assert here. The remote loader, chunker, embedding
pipeline, and the backend HTTP callback are all mocked — only the PG
update is real.

``sync_worker`` reads rows out of ``sources`` whose ``sync_frequency``
matches and dispatches them through ``sync`` → ``remote_worker``. We
assert one seeded row is discovered and forwarded.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock

import pytest

from application.parser.schema.base import Document
from application.storage.db.repositories.sources import SourcesRepository


@pytest.fixture
def _mock_remote_pipeline(monkeypatch):
    """Stub out the non-PG boundaries used by ``remote_worker``."""
    from application import worker

    fake_loader = MagicMock(name="remote_loader")
    fake_loader.load_data.return_value = [
        Document(
            text="page body",
            extra_info={"file_path": "guides/setup.md", "title": "setup"},
            doc_id="d1",
        )
    ]
    monkeypatch.setattr(
        worker.RemoteCreator, "create_loader", lambda loader: fake_loader
    )
    monkeypatch.setattr(
        worker,
        "embed_and_store_documents",
        lambda docs, full_path, source_id, task, **kw: None,
    )
    monkeypatch.setattr(
        worker, "upload_index", lambda full_path, file_data: None
    )


@pytest.mark.unit
class TestRemoteWorkerSyncUpdatesDate:
    def test_sync_mode_bumps_source_date(
        self,
        pg_conn,
        patch_worker_db,
        task_self,
        monkeypatch,
        _mock_remote_pipeline,
    ):
        from application import worker

        # Seed a source with a known old ``date`` we can compare against.
        import datetime as dt

        old_date = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
        src = SourcesRepository(pg_conn).create(
            "my-remote",
            user_id="bob",
            type="crawler",
            retriever="classic",
            sync_frequency="daily",
            remote_data={"urls": ["http://example.com"]},
            date=old_date,
        )
        source_id = str(src["id"])

        worker.remote_worker(
            task_self,
            {"urls": ["http://example.com"]},
            "my-remote",
            "bob",
            "crawler",
            directory="temp",
            retriever="classic",
            sync_frequency="daily",
            operation_mode="sync",
            doc_id=source_id,
        )

        refreshed = SourcesRepository(pg_conn).get(source_id, "bob")
        assert refreshed is not None
        # row_to_dict coerces datetimes to ISO 8601 strings; UTC
        # timezone-aware ISO strings sort chronologically.
        assert refreshed["date"] > old_date.isoformat(), (
            "remote_worker(sync) should push sources.date forward"
        )


@pytest.mark.unit
class TestSyncWorker:
    def test_reads_sources_and_dispatches_sync(
        self,
        pg_conn,
        patch_worker_db,
        task_self,
        monkeypatch,
    ):
        """``sync_worker`` selects rows by ``sync_frequency`` and passes
        each to ``sync``. We assert the seeded row is discovered and
        forwarded with the right doc_id — the nested ``sync`` call is
        stubbed so we don't re-run the whole remote pipeline here."""
        from application import worker

        src = SourcesRepository(pg_conn).create(
            "weekly-feed",
            user_id="carol",
            type="url",
            retriever="classic",
            sync_frequency="weekly",
            remote_data={"url": "http://example.com"},
        )

        captured: list[dict] = []

        def _fake_sync(self, source_data, name_job, user, loader,
                       sync_frequency, retriever, doc_id=None, directory="temp"):
            captured.append({
                "name_job": name_job,
                "user": user,
                "loader": loader,
                "sync_frequency": sync_frequency,
                "retriever": retriever,
                "doc_id": doc_id,
            })
            return {"status": "success"}

        monkeypatch.setattr(worker, "sync", _fake_sync)

        result = worker.sync_worker(task_self, "weekly")

        assert result["total_sync_count"] == 1
        assert result["sync_success"] == 1
        assert len(captured) == 1
        assert captured[0]["name_job"] == "weekly-feed"
        assert captured[0]["user"] == "carol"
        assert captured[0]["loader"] == "url"
        assert captured[0]["doc_id"] == str(src["id"])


@pytest.mark.unit
class TestRemoteWorkerPathTraversal:
    """Regression: ``name_job`` must not be usable as a path segment.

    Historically ``remote_worker`` built its workspace from
    ``os.path.join(directory, user, name_job)`` and cleaned it up with
    ``shutil.rmtree`` in a ``finally``. A ``name_job`` like
    ``../../evil`` would therefore let an authenticated caller delete
    directories outside the intended ``<directory>/<user>/`` root.
    The fix uses a random uuid leaf; ``name_job`` is metadata only.
    """

    def test_traversal_name_job_does_not_escape_user_workspace(
        self,
        tmp_path,
        task_self,
        monkeypatch,
        _mock_remote_pipeline,
    ):
        from application import worker

        created_paths: list[str] = []
        deleted_paths: list[str] = []
        real_makedirs = os.makedirs
        real_rmtree = worker.shutil.rmtree

        def _spy_makedirs(path, *args, **kwargs):
            created_paths.append(path)
            return real_makedirs(path, *args, **kwargs)

        def _spy_rmtree(path, *args, **kwargs):
            deleted_paths.append(path)
            return real_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(worker.os, "makedirs", _spy_makedirs)
        monkeypatch.setattr(worker.shutil, "rmtree", _spy_rmtree)

        directory = str(tmp_path / "temp")
        user = "bob"
        malicious_name = "../../evil"

        worker.remote_worker(
            task_self,
            {"urls": ["http://example.com"]},
            malicious_name,
            user,
            "crawler",
            directory=directory,
            operation_mode="upload",
        )

        directory_real = os.path.realpath(directory)
        user_root = os.path.realpath(os.path.join(directory, user))

        rmtree_targets = [
            os.path.realpath(p)
            for p in deleted_paths
            if os.path.realpath(p).startswith(directory_real)
        ]
        assert len(rmtree_targets) == 1, rmtree_targets
        assert rmtree_targets[0].startswith(user_root + os.sep), (
            f"rmtree target {rmtree_targets[0]} escaped {user_root}"
        )
        assert malicious_name not in "".join(created_paths + deleted_paths)


@pytest.mark.unit
class TestRemoteWorkerDeterministicSourceId:
    """Upload-mode ``remote_worker`` derives a stable ``source_id`` from the key."""

    def test_uses_uuid5_when_idempotency_key_present(
        self,
        tmp_path,
        task_self,
        monkeypatch,
        _mock_remote_pipeline,
    ):
        from application import worker

        captured: list[dict] = []
        monkeypatch.setattr(
            worker, "upload_index",
            lambda full_path, file_data: captured.append(file_data),
        )

        for _ in range(2):
            worker.remote_worker(
                task_self,
                {"urls": ["http://example.com"]},
                "feed",
                "bob",
                "crawler",
                directory=str(tmp_path / "temp"),
                operation_mode="upload",
                idempotency_key="abc",
            )

        expected = str(uuid.uuid5(worker.DOCSGPT_INGEST_NAMESPACE, "abc"))
        assert len(captured) == 2
        assert captured[0]["id"] == expected
        assert captured[1]["id"] == expected

    def test_falls_back_to_uuid4_without_key(
        self,
        tmp_path,
        task_self,
        monkeypatch,
        _mock_remote_pipeline,
    ):
        from application import worker

        captured: list[dict] = []
        monkeypatch.setattr(
            worker, "upload_index",
            lambda full_path, file_data: captured.append(file_data),
        )

        for _ in range(2):
            worker.remote_worker(
                task_self,
                {"urls": ["http://example.com"]},
                "feed",
                "bob",
                "crawler",
                directory=str(tmp_path / "temp"),
                operation_mode="upload",
            )

        assert len(captured) == 2
        assert captured[0]["id"] != captured[1]["id"]
