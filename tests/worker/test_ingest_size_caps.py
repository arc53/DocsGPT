"""An ingest over INGEST_MAX_FILES or INGEST_MAX_TOKENS fails before anything is embedded."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from docsgpt import worker
from docsgpt.core.settings import settings
from docsgpt.parser.ingest_limits import IngestTooLarge
from docsgpt.parser.schema.base import Document


def _docs(count: int, text: str = "body") -> list:
    return [Document(text=text, extra_info={"file_path": f"f{i}.md"}, doc_id=f"d{i}") for i in range(count)]


@pytest.fixture
def caps(monkeypatch):
    """Set the two caps; both start disabled."""

    def _set(files: int = 0, tokens: int = 0) -> None:
        monkeypatch.setattr(settings, "INGEST_MAX_FILES", files)
        monkeypatch.setattr(settings, "INGEST_MAX_TOKENS", tokens)

    _set()
    return _set


@pytest.fixture
def embeds(monkeypatch) -> list:
    """Every ``embed_and_store_documents`` call."""
    calls: list = []
    monkeypatch.setattr(worker, "embed_and_store_documents", lambda *a, **k: calls.append(a))
    return calls


def _failed(published) -> dict:
    return next(payload for kind, payload in published if kind == "source.ingest.failed")


@pytest.mark.unit
class TestRemoteWorkerCaps:
    def _run(self, task_self, tmp_path):
        worker.remote_worker(
            task_self, "https://example.com", "feed", "bob", "crawler",
            directory=str(tmp_path / "temp"), operation_mode="upload",
        )

    def test_too_many_files_fails_before_embedding(
        self, tmp_path, task_self, remote_pipeline, embeds, published, caps,
    ):
        caps(files=2)
        remote_pipeline.loader.load_data.return_value = _docs(3)

        with pytest.raises(IngestTooLarge):
            self._run(task_self, tmp_path)

        assert embeds == []
        assert remote_pipeline.uploads == []
        failed = _failed(published)
        assert failed["reason"] == "too_many_files"
        assert failed["limit"] == 2
        assert "3 files" in failed["error"]

    def test_too_many_tokens_fails_before_embedding(
        self, tmp_path, task_self, remote_pipeline, embeds, published, caps,
    ):
        caps(tokens=5)
        remote_pipeline.loader.load_data.return_value = _docs(1, text="word " * 50)

        with pytest.raises(IngestTooLarge):
            self._run(task_self, tmp_path)

        assert embeds == []
        failed = _failed(published)
        assert failed["reason"] == "too_many_tokens"
        assert failed["limit"] == 5

    def test_within_the_caps_embeds(self, tmp_path, task_self, remote_pipeline, embeds, published, caps):
        caps(files=3, tokens=10_000)
        remote_pipeline.loader.load_data.return_value = _docs(3)

        self._run(task_self, tmp_path)

        assert len(embeds) == 1

    def test_zero_disables_both(self, tmp_path, task_self, remote_pipeline, embeds, published, caps):
        remote_pipeline.loader.load_data.return_value = _docs(50, text="word " * 50)

        self._run(task_self, tmp_path)

        assert len(embeds) == 1


@pytest.fixture
def upload_reader(monkeypatch):
    """Stub ``ingest_worker``'s storage and reader; ``reader.input_files`` is what it listed."""
    storage = MagicMock(name="storage")
    storage.is_directory.return_value = False
    storage.get_file.return_value = MagicMock(read=lambda: b"x")
    monkeypatch.setattr(worker.StorageCreator, "get_storage", lambda: storage)
    reader = MagicMock(name="reader")
    reader.input_files = ["a.md"]
    reader.load_data.return_value = _docs(1)
    reader.directory_structure = {}
    monkeypatch.setattr(worker, "SimpleDirectoryReader", lambda *a, **k: reader)
    monkeypatch.setattr(worker, "assert_index_complete", lambda *a, **k: None)
    monkeypatch.setattr(worker, "upload_index", lambda *a, **k: None)
    return reader


@pytest.mark.unit
class TestUploadIngestCaps:
    def _run(self, task_self):
        worker.ingest_worker(task_self, "inputs", [".md"], "job", "inputs/bob/job/a.md", "a.md", "bob")

    def test_too_many_files_fails_before_parsing(self, task_self, upload_reader, embeds, published, caps):
        caps(files=1)
        upload_reader.input_files = ["a.md", "b.md"]

        with pytest.raises(IngestTooLarge):
            self._run(task_self)

        upload_reader.load_data.assert_not_called()
        assert embeds == []
        assert _failed(published)["reason"] == "too_many_files"

    def test_too_many_tokens_fails_before_embedding(self, task_self, upload_reader, embeds, published, caps):
        caps(tokens=5)
        upload_reader.load_data.return_value = _docs(1, text="word " * 50)

        with pytest.raises(IngestTooLarge):
            self._run(task_self)

        assert embeds == []
        assert _failed(published)["reason"] == "too_many_tokens"


@pytest.mark.unit
class TestConnectorIngestCaps:
    def _run(self, task_self):
        worker.ingest_connector(
            task_self, "job", "bob", "google_drive", session_token="tok", file_ids=["f"],
        )

    def test_too_many_files_fails_before_parsing(
        self, task_self, _mock_connector_pipeline, embeds, published, caps, monkeypatch,
    ):
        caps(files=1)
        reader = MagicMock(name="reader")
        reader.input_files = ["a.md", "b.md"]
        monkeypatch.setattr(worker, "SimpleDirectoryReader", lambda *a, **k: reader)

        with pytest.raises(IngestTooLarge):
            self._run(task_self)

        reader.load_data.assert_not_called()
        assert embeds == []
        assert _failed(published)["reason"] == "too_many_files"

    def test_too_many_tokens_fails_before_embedding(
        self, task_self, _mock_connector_pipeline, embeds, published, caps, monkeypatch,
    ):
        caps(tokens=5)
        reader = MagicMock(name="reader")
        reader.input_files = ["a.md"]
        reader.load_data.return_value = _docs(1, text="word " * 50)
        reader.directory_structure = {}
        monkeypatch.setattr(worker, "SimpleDirectoryReader", lambda *a, **k: reader)

        with pytest.raises(IngestTooLarge):
            self._run(task_self)

        assert embeds == []
        assert _failed(published)["reason"] == "too_many_tokens"


@pytest.mark.unit
class TestCappedIngestIsNotRetried:
    def test_every_whole_source_ingest_task_fails_it_at_once(self):
        from docsgpt.api.user import tasks

        for task in (
            tasks.ingest, tasks.ingest_remote, tasks.ingest_connector_task, tasks.reingest_source_task,
            tasks.sync_connector_source,
        ):
            assert IngestTooLarge in task.dont_autoretry_for, task.name
