"""An ingest hands the folder its upload asked for to ``/api/upload_index``, which files the new source."""

from __future__ import annotations

import pytest

from docsgpt import worker
from docsgpt.storage.db.repositories.sources import SourcesRepository
from tests.worker.test_ingest_worker import _patch_ingest_pipeline

FOLDER = "7b0f5e0c-1f5a-4c43-9d55-0d1c6c1a2b3c"


def _ingest(task_self, **kwargs):
    worker.ingest_worker(
        task_self, directory="inputs", formats=[".txt"], job_name="job1",
        file_path="inputs/eve/job1/a.txt", filename="a.txt", user="eve", **kwargs,
    )


@pytest.mark.unit
class TestUploadFolderTravels:
    def test_an_upload_names_its_folder(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        captured: list[dict] = []
        _patch_ingest_pipeline(monkeypatch, captured)
        _ingest(task_self, folder_id=FOLDER)
        assert captured[0]["folder_id"] == FOLDER

    def test_no_folder_keeps_the_form_shape(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        captured: list[dict] = []
        _patch_ingest_pipeline(monkeypatch, captured)
        _ingest(task_self)
        assert "folder_id" not in captured[0]

    def test_a_remote_upload_names_its_folder(self, pg_conn, patch_worker_db, tmp_path, task_self, remote_pipeline):
        worker.remote_worker(
            task_self, {"url": "https://docs.x.io/"}, "Docs", "bob", "url",
            directory=str(tmp_path / "temp"), operation_mode="upload", folder_id=FOLDER,
        )
        assert remote_pipeline.uploads[0]["folder_id"] == FOLDER

    def test_a_remote_sync_files_nothing(self, pg_conn, patch_worker_db, tmp_path, task_self, remote_pipeline):
        source = SourcesRepository(pg_conn).create("Docs", user_id="bob", type="url")
        worker.remote_worker(
            task_self, {"url": "https://docs.x.io/"}, "Docs", "bob", "url",
            directory=str(tmp_path / "temp"), operation_mode="sync", doc_id=str(source["id"]), folder_id=FOLDER,
        )
        assert "folder_id" not in remote_pipeline.uploads[0]

    def test_a_connector_upload_names_its_folder(
        self, pg_conn, patch_worker_db, task_self, monkeypatch, _mock_connector_pipeline,
    ):
        uploads: list[dict] = []
        monkeypatch.setattr(worker, "upload_index", lambda full_path, file_data: uploads.append(file_data))
        worker.ingest_connector(
            task_self, "gdrive-folder", "dave", "google_drive",
            session_token="tok", file_ids=["f1"], operation_mode="upload", folder_id=FOLDER,
        )
        assert uploads[0]["folder_id"] == FOLDER
