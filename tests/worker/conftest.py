"""Fixtures for Celery worker smoke tests.

These tests exercise the task *bodies* in ``docsgpt.worker`` against a
real Postgres schema (via the ephemeral ``pg_conn`` fixture from the root
``tests/conftest.py``). External I/O — storage, the embedding pipeline,
the retriever, the LLM, the backend HTTP callback — is mocked, but every
PG write is allowed to hit the real ephemeral DB so the assertions can
read the resulting rows back.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Callable, Iterator, List
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Connection

from docsgpt import worker
from docsgpt.parser.schema.base import Document
from docsgpt.vectorstore.index_lock import SourceBusy


@pytest.fixture
def patch_worker_db(pg_conn, monkeypatch):
    """Redirect ``db_session`` / ``db_readonly`` in ``docsgpt.worker``.

    Both helpers yield the per-test transactional ``pg_conn``, so any
    writes a task performs are visible to the test and roll back on
    teardown. Without this patch the worker would open its own pooled
    engine and punch past the per-test transaction.
    """

    @contextmanager
    def _use_pg_conn() -> Iterator[Connection]:
        yield pg_conn

    monkeypatch.setattr("docsgpt.worker.db_session", _use_pg_conn)
    monkeypatch.setattr("docsgpt.worker.db_readonly", _use_pg_conn)


@pytest.fixture
def task_self():
    """Minimal stand-in for the Celery task ``self`` passed to workers.

    ``update_state`` and ``request.retries`` are the only attributes the
    worker bodies touch in our tests. Defaulting ``retries`` to 0 makes
    every fixture instance behave like a fresh first attempt, which is
    what the queued-event publishes are gated on. Tests covering the
    retry path override this to a positive int.
    """
    task = MagicMock(name="celery_task_self")
    task.request.retries = 0
    return task


class Published(list):
    """``(kind, payload)`` of every event the worker published, in order; ``users`` holds each one's recipient."""

    def __init__(self) -> None:
        super().__init__()
        self.users: List[str] = []

    def kinds(self) -> List[str]:
        return [kind for kind, _payload in self]

    def recipients(self, kind: str) -> List[str]:
        """Who heard the events of ``kind``, sorted."""
        return sorted(user for user, (event_kind, _payload) in zip(self.users, self) if event_kind == kind)


@pytest.fixture
def published(monkeypatch) -> Published:
    """Capture ``publish_user_event`` in ``docsgpt.worker``."""
    events = Published()

    def _publish(user, kind, payload, **kwargs):
        events.users.append(user)
        events.append((kind, payload))

    monkeypatch.setattr(worker, "publish_user_event", _publish)
    return events


@pytest.fixture
def busy_lock(monkeypatch) -> Callable[..., List]:
    """Make a worker lock refuse with ``SourceBusy``.

    Call it with the lock's name (``source_index_lock`` by default, or
    ``graph_extract_lock``); it returns the ``wait_seconds`` each try asked for.
    """
    waits: List = []

    def _use(name: str = "source_index_lock") -> List:
        @contextmanager
        def _busy(source_id, wait_seconds=None, **kwargs):
            waits.append(wait_seconds)
            raise SourceBusy("busy")
            yield  # pragma: no cover

        monkeypatch.setattr(worker, name, _busy)
        return waits

    return _use


class HeldLock(list):
    """What happened under a fake lock: the locked id, the test's own entries, then ``"released"``.

    ``while_waiting`` holds changes that land while the job waits for the
    lock; ``lock`` is the fake, to stand in for another lock too.
    """

    def __init__(self) -> None:
        super().__init__()
        self.while_waiting: List[Callable[[], None]] = []

    @contextmanager
    def lock(self, source_id, **kwargs):
        for change in self.while_waiting:
            change()
        self.append(source_id)
        yield
        self.append("released")


@pytest.fixture
def held_lock(monkeypatch) -> HeldLock:
    """Replace ``source_index_lock`` with one that records when it is held."""
    held = HeldLock()
    monkeypatch.setattr(worker, "source_index_lock", held.lock)
    return held


@pytest.fixture
def remote_pipeline(monkeypatch) -> SimpleNamespace:
    """Stub ``remote_worker``'s loader, embedding and upload.

    ``loader.load_data`` returns one page (``guide.md``) unless a test sets
    it; ``uploads`` collects the ``file_data`` sent to the API, and
    ``answer`` is what ``upload_index`` returns (a refusal, say).
    """
    loader = MagicMock(name="remote_loader")
    loader.load_data.return_value = [
        Document(text="page body", extra_info={"file_path": "guide.md", "title": "Guide"}, doc_id="d1"),
    ]
    loader.report = {"pages": 1, "sites": []}
    pipeline = SimpleNamespace(loader=loader, uploads=[], answer=None)

    def _upload(full_path, file_data):
        pipeline.uploads.append(file_data)
        return pipeline.answer

    monkeypatch.setattr(worker.RemoteCreator, "create_loader", lambda name: loader)
    monkeypatch.setattr(worker, "embed_and_store_documents", lambda *a, **k: None)
    monkeypatch.setattr(worker, "assert_index_complete", lambda *a, **k: None)
    monkeypatch.setattr(worker, "upload_index", _upload)
    return pipeline


@pytest.fixture
def _mock_connector_pipeline(monkeypatch):
    """Stub the connector + pipeline so only PG writes are real."""
    fake_connector = MagicMock(name="connector")
    fake_connector.connection_id = None
    fake_connector.download_to_directory.return_value = {
        "files_downloaded": 1,
        "empty_result": False,
    }
    monkeypatch.setattr(
        worker.ConnectorCreator, "is_supported", staticmethod(lambda s: True)
    )
    monkeypatch.setattr(
        worker.ConnectorCreator,
        "create_connector",
        staticmethod(lambda source_type, session_token=None, connection_id=None: fake_connector),
    )

    fake_reader = MagicMock(name="reader")
    fake_reader.load_data.return_value = [
        Document(
            text="connector body",
            extra_info={"source": "connector/file.md", "file_path": "file.md"},
        )
    ]
    fake_reader.directory_structure = {
        "file.md": {
            "type": "text/markdown",
            "size_bytes": 12,
            "token_count": 3,
        }
    }
    monkeypatch.setattr(
        worker, "SimpleDirectoryReader", lambda *a, **kw: fake_reader
    )

    monkeypatch.setattr(
        worker,
        "embed_and_store_documents",
        lambda docs, full_path, source_id, task, **kw: None,
    )
    monkeypatch.setattr(
        worker, "upload_index", lambda full_path, file_data: None
    )
    return fake_connector
