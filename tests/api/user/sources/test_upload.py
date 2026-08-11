"""Tests for application/api/user/sources/upload.py."""

import io
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.sources.upload.db_session", _yield
    ), patch(
        "application.api.user.sources.upload.db_readonly", _yield
    ):
        yield


def _seed_source(pg_conn, user="u", name="src", **kw):
    from application.storage.db.repositories.sources import SourcesRepository
    return SourcesRepository(pg_conn).create(name, user_id=user, **kw)


class TestEnforceAudioPathSizeLimit:
    def test_noop_for_non_audio(self, tmp_path):
        from application.api.user.sources.upload import (
            _enforce_audio_path_size_limit,
        )
        p = tmp_path / "doc.txt"
        p.write_bytes(b"x" * 1024)
        _enforce_audio_path_size_limit(str(p), "doc.txt")

    def test_raises_for_large_audio(self, tmp_path):
        from application.api.user.sources.upload import (
            _enforce_audio_path_size_limit,
        )
        from application.stt.upload_limits import AudioFileTooLargeError

        p = tmp_path / "audio.mp3"
        p.write_bytes(b"x" * 100)
        with patch(
            "application.api.user.sources.upload.enforce_audio_file_size_limit",
            side_effect=AudioFileTooLargeError("too large"),
        ):
            with pytest.raises(AudioFileTooLargeError):
                _enforce_audio_path_size_limit(str(p), "audio.mp3")


class TestUploadFile:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.upload import UploadFile

        with app.test_request_context("/api/upload", method="POST"):
            from flask import request
            request.decoded_token = None
            response = UploadFile().post()
        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.sources.upload import UploadFile

        with app.test_request_context(
            "/api/upload", method="POST",
            data={"user": "u"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadFile().post()
        assert response.status_code == 400

    def test_returns_400_empty_filenames(self, app):
        from application.api.user.sources.upload import UploadFile

        with app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "u", "name": "job",
                "file": (io.BytesIO(b""), ""),  # empty filename
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadFile().post()
        assert response.status_code == 400

    def test_uploads_single_file_successfully(self, app):
        from application.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        fake_task = MagicMock(id="task-1")

        with patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.upload.ingest.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "my_job",
                "file": (io.BytesIO(b"content"), "doc.txt"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 200
        assert response.json["success"] is True
        assert response.json["task_id"] == "task-1"

    def test_storage_error_returns_400(self, app):
        from application.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        fake_storage.save_file.side_effect = RuntimeError("boom")

        with patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "j",
                "file": (io.BytesIO(b"content"), "doc.txt"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 400

    def test_uploads_zip_extracts_files(self, app):
        from application.api.user.sources.upload import UploadFile
        import zipfile

        # Build an in-memory zip containing 2 files
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("a.txt", "content a")
            zf.writestr("sub/b.txt", "content b")
        zip_buffer.seek(0)

        fake_storage = MagicMock()
        fake_task = MagicMock(id="task-zip")

        with patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.upload.ingest.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "job",
                "file": (zip_buffer, "docs.zip"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 200
        # save_file called at least twice (for 2 files in zip)
        assert fake_storage.save_file.call_count >= 2

    def test_office_format_zip_saved_as_is(self, app):
        from application.api.user.sources.upload import UploadFile
        import zipfile

        # .docx is technically a zip but should be saved as-is
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", "<x/>")
        buf.seek(0)

        fake_storage = MagicMock()

        with patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.upload.ingest.apply_async",
            return_value=MagicMock(id="t"),
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "job",
                "file": (buf, "letter.docx"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 200
        # Saved once (as the .docx directly, not extracted)
        assert fake_storage.save_file.call_count == 1

    def test_audio_too_large_returns_413(self, app):
        from application.api.user.sources.upload import UploadFile
        from application.stt.upload_limits import AudioFileTooLargeError

        fake_storage = MagicMock()

        with patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.upload._enforce_audio_path_size_limit",
            side_effect=AudioFileTooLargeError("too large"),
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "j",
                "file": (io.BytesIO(b"audio-content"), "song.mp3"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 413


class TestUploadRemote:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.upload import UploadRemote

        with app.test_request_context(
            "/api/remote", method="POST",
            data={"user": "u", "source": "github"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = None
            response = UploadRemote().post()
        assert response.status_code == 401

    def test_returns_missing_fields(self, app):
        from application.api.user.sources.upload import UploadRemote

        with app.test_request_context(
            "/api/remote", method="POST",
            data={"user": "u"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        # check_required_fields returns a response; status is 400
        # The response is returned directly by missing_fields branch
        assert response.status_code == 400

    def test_uploads_github_remote_success(self, app):
        from application.api.user.sources.upload import UploadRemote

        fake_task = MagicMock(id="remote-task-1")
        with patch(
            "application.api.user.sources.upload.ingest_remote.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "github", "name": "gh",
                "data": json.dumps({"repo_url": "https://github.com/x/y"}),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 200
        assert response.json["task_id"] == "remote-task-1"

    def test_uploads_url_source(self, app):
        from application.api.user.sources.upload import UploadRemote

        fake_task = MagicMock(id="url-task")
        with patch(
            "application.api.user.sources.upload.ingest_remote.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "crawler", "name": "crawl",
                "data": json.dumps({"url": "https://example.com"}),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 200

    def test_uploads_reddit_source(self, app):
        from application.api.user.sources.upload import UploadRemote

        fake_task = MagicMock(id="reddit-task")
        with patch(
            "application.api.user.sources.upload.ingest_remote.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "reddit", "name": "r",
                "data": json.dumps({"subreddit": "python"}),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 200

    def test_upload_exception_returns_400(self, app):
        from application.api.user.sources.upload import UploadRemote

        with patch(
            "application.api.user.sources.upload.ingest_remote.apply_async",
            side_effect=RuntimeError("boom"),
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "github", "name": "x",
                "data": json.dumps({"repo_url": "https://github.com/x/y"}),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 400


class TestManageSourceFiles:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        with app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": "x", "operation": "add"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = None
            response = ManageSourceFiles().post()
        assert response.status_code == 401

    def test_returns_400_missing_required(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        with app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": "x"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_returns_400_invalid_operation(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        with app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": "x", "operation": "weird"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_returns_404_source_not_found(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        with _patch_db(pg_conn), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": "00000000-0000-0000-0000-000000000000",
                "operation": "add",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ManageSourceFiles().post()
        assert response.status_code == 404

    def test_rejects_bad_parent_dir(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "u-bad-parent"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "add",
                "parent_dir": "/abs-path",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_add_no_files_returns_400(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "u-add-nofile"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": str(src["id"]), "operation": "add"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_add_files_success(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "u-add-ok"
        src = _seed_source(pg_conn, user=user, file_path="/data/src")

        fake_storage = MagicMock()
        fake_task = MagicMock(id="reingest-1")
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "add",
                "file": (io.BytesIO(b"content"), "new.txt"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 200
        assert response.json["success"] is True
        assert "new.txt" in response.json["added_files"]

    def test_remove_missing_file_paths_returns_400(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "u-rm-nolist"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": str(src["id"]), "operation": "remove"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_remove_invalid_json_file_paths(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "u-rm-bad"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove",
                "file_paths": "not-json",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_remove_rejects_path_traversal(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "u-rm-trav"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove",
                "file_paths": json.dumps(["../escape.txt"]),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_remove_files_success(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "u-rm-ok"
        src = _seed_source(
            pg_conn, user=user,
            file_path="/data/src",
            file_name_map={"a.txt": "Original A.txt"},
        )

        fake_storage = MagicMock()
        fake_storage.file_exists.return_value = True
        fake_task = MagicMock(id="reingest-rm")
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove",
                "file_paths": json.dumps(["a.txt"]),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 200
        assert "a.txt" in response.json["removed_files"]

    def test_remove_directory_missing_path(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "u-rmdir-missing"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove_directory",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_remove_directory_rejects_bad_path(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "u-rmdir-bad"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove_directory",
                "directory_path": "../escape",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_remove_directory_404_when_not_directory(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "u-rmdir-notdir"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        fake_storage = MagicMock()
        fake_storage.is_directory.return_value = False

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove_directory",
                "directory_path": "subdir",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 404

    def test_remove_directory_success(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "u-rmdir-ok"
        src = _seed_source(
            pg_conn, user=user, file_path="/data",
            file_name_map={"sub/a.txt": "A"},
        )

        fake_storage = MagicMock()
        fake_storage.is_directory.return_value = True
        fake_storage.remove_directory.return_value = True
        fake_task = MagicMock(id="reingest-dir")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove_directory",
                "directory_path": "sub",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 200
        assert response.json["removed_directory"] == "sub"

    def test_remove_directory_storage_failure_returns_500(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "u-rmdir-fail"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        fake_storage = MagicMock()
        fake_storage.is_directory.return_value = True
        fake_storage.remove_directory.return_value = False

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove_directory",
                "directory_path": "sub",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 500


class TestTaskStatus:
    def test_returns_400_missing_task_id(self, app):
        from application.api.user.sources.upload import TaskStatus

        with app.test_request_context("/api/task_status"):
            response = TaskStatus().get()
        assert response.status_code == 400

    def test_returns_task_status(self, app):
        from application.api.user.sources.upload import TaskStatus

        fake_task = MagicMock()
        fake_task.status = "SUCCESS"
        fake_task.info = {"result": "ok"}

        fake_celery = MagicMock()
        fake_celery.AsyncResult.return_value = fake_task

        with patch(
            "application.celery_init.celery", fake_celery
        ), app.test_request_context("/api/task_status?task_id=t-123"):
            response = TaskStatus().get()
        assert response.status_code == 200
        assert response.json["status"] == "SUCCESS"

    def test_pending_without_workers_returns_503(self, app):
        from application.api.user.sources.upload import TaskStatus

        fake_task = MagicMock()
        fake_task.status = "PENDING"
        fake_task.info = None

        fake_inspect = MagicMock()
        fake_inspect.ping.return_value = None  # no workers

        fake_celery = MagicMock()
        fake_celery.AsyncResult.return_value = fake_task
        fake_celery.control.inspect.return_value = fake_inspect

        with patch(
            "application.celery_init.celery", fake_celery
        ), app.test_request_context("/api/task_status?task_id=t-999"):
            response = TaskStatus().get()
        assert response.status_code == 503

    def test_exception_returns_400(self, app):
        from application.api.user.sources.upload import TaskStatus

        fake_celery = MagicMock()
        fake_celery.AsyncResult.side_effect = RuntimeError("boom")

        with patch(
            "application.celery_init.celery", fake_celery
        ), app.test_request_context("/api/task_status?task_id=t-err"):
            response = TaskStatus().get()
        assert response.status_code == 400

    def test_non_serializable_info_gets_stringified(self, app):
        from application.api.user.sources.upload import TaskStatus

        class WeirdObj:
            def __str__(self):
                return "weird-str"

        fake_task = MagicMock()
        fake_task.status = "SUCCESS"
        fake_task.info = WeirdObj()

        fake_celery = MagicMock()
        fake_celery.AsyncResult.return_value = fake_task

        with patch(
            "application.celery_init.celery", fake_celery
        ), app.test_request_context("/api/task_status?task_id=t-weird"):
            response = TaskStatus().get()
        assert response.status_code == 200
        assert response.json["result"] == "weird-str"
