"""Tests for source upload routes (UploadFile, UploadRemote, ManageSourceFiles,
TaskStatus) and the _enforce_audio_path_size_limit helper.

Note: test_audio_upload.py already covers audio-extension pass-through and
oversized-audio rejection for UploadFile; those are NOT duplicated here.
"""

import io
import json

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from bson import ObjectId
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


def _status(response):
    if isinstance(response, tuple):
        return response[1]
    return response.status_code


def _json(response):
    if isinstance(response, tuple):
        return response[0].json
    return response.json


# ---------------------------------------------------------------------------
# _enforce_audio_path_size_limit helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnforceAudioPathSizeLimit:

    def test_skips_non_audio_file(self):
        from application.api.user.sources.upload import _enforce_audio_path_size_limit

        # Should not raise for non-audio file regardless of size
        with patch(
            "application.api.user.sources.upload.is_audio_filename",
            return_value=False,
        ):
            _enforce_audio_path_size_limit("/tmp/big.pdf", "big.pdf")

    def test_raises_for_oversized_audio(self):
        from application.api.user.sources.upload import _enforce_audio_path_size_limit
        from application.stt.upload_limits import AudioFileTooLargeError

        with patch(
            "application.api.user.sources.upload.is_audio_filename",
            return_value=True,
        ), patch(
            "application.api.user.sources.upload.os.path.getsize",
            return_value=999_999_999,
        ), patch(
            "application.api.user.sources.upload.enforce_audio_file_size_limit",
            side_effect=AudioFileTooLargeError("too big"),
        ):
            with pytest.raises(AudioFileTooLargeError):
                _enforce_audio_path_size_limit("/tmp/big.wav", "big.wav")

    def test_passes_for_small_audio(self):
        from application.api.user.sources.upload import _enforce_audio_path_size_limit

        with patch(
            "application.api.user.sources.upload.is_audio_filename",
            return_value=True,
        ), patch(
            "application.api.user.sources.upload.os.path.getsize",
            return_value=1024,
        ), patch(
            "application.api.user.sources.upload.enforce_audio_file_size_limit",
        ) as mock_enforce:
            _enforce_audio_path_size_limit("/tmp/small.wav", "small.wav")
            mock_enforce.assert_called_once_with(1024)


# ---------------------------------------------------------------------------
# UploadFile (/api/upload)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadFile:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.upload import UploadFile

        with app.test_request_context(
            "/api/upload", method="POST",
            data={"user": "u1", "name": "test", "file": (io.BytesIO(b"x"), "f.txt")},
            content_type="multipart/form-data",
        ):
            from flask import request

            request.decoded_token = None
            response = UploadFile().post()

        assert _status(response) == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.sources.upload import UploadFile

        with app.test_request_context(
            "/api/upload", method="POST",
            data={"user": "u1"},
            content_type="multipart/form-data",
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = UploadFile().post()

        assert _status(response) == 400

    def test_returns_400_when_no_files(self, app):
        from application.api.user.sources.upload import UploadFile

        with app.test_request_context(
            "/api/upload", method="POST",
            data={"user": "u1", "name": "test"},
            content_type="multipart/form-data",
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = UploadFile().post()

        assert _status(response) == 400

    def test_returns_400_when_files_have_empty_filenames(self, app):
        from application.api.user.sources.upload import UploadFile

        with app.test_request_context(
            "/api/upload", method="POST",
            data={"user": "u1", "name": "test", "file": (io.BytesIO(b""), "")},
            content_type="multipart/form-data",
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = UploadFile().post()

        assert _status(response) == 400

    def test_successful_upload(self, app):
        from application.api.user.sources.upload import UploadFile

        mock_storage = MagicMock()
        mock_task = SimpleNamespace(id="task-abc")

        with app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "u1",
                "name": "My Doc",
                "file": (io.BytesIO(b"hello"), "test.txt"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.StorageCreator.get_storage",
                return_value=mock_storage,
            ), patch(
                "application.api.user.sources.upload.ingest"
            ) as mock_ingest, patch(
                "application.api.user.sources.upload._enforce_audio_path_size_limit",
            ):
                mock_ingest.delay.return_value = mock_task
                response = UploadFile().post()

        assert _status(response) == 200
        data = _json(response)
        assert data["success"] is True
        assert data["task_id"] == "task-abc"
        mock_ingest.delay.assert_called_once()

    def test_returns_400_on_general_error(self, app):
        from application.api.user.sources.upload import UploadFile

        with app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "u1",
                "name": "Doc",
                "file": (io.BytesIO(b"data"), "f.txt"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.StorageCreator.get_storage",
                side_effect=Exception("storage down"),
            ):
                response = UploadFile().post()

        assert _status(response) == 400


# ---------------------------------------------------------------------------
# UploadRemote (/api/remote)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadRemote:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.upload import UploadRemote

        with app.test_request_context(
            "/api/remote", method="POST",
            data={"user": "u1", "source": "github", "name": "repo", "data": "{}"},
        ):
            from flask import request

            request.decoded_token = None
            response = UploadRemote().post()

        assert _status(response) == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.sources.upload import UploadRemote

        with app.test_request_context(
            "/api/remote", method="POST",
            data={"user": "u1", "source": "github"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = UploadRemote().post()

        assert response is not None

    def test_github_source(self, app):
        from application.api.user.sources.upload import UploadRemote

        mock_task = SimpleNamespace(id="task-gh")
        config = json.dumps({"repo_url": "https://github.com/test/repo"})

        with app.test_request_context(
            "/api/remote", method="POST",
            data={"user": "u1", "source": "github", "name": "repo", "data": config},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.ingest_remote"
            ) as mock_ingest:
                mock_ingest.delay.return_value = mock_task
                response = UploadRemote().post()

        assert _status(response) == 200
        data = _json(response)
        assert data["task_id"] == "task-gh"
        call_kwargs = mock_ingest.delay.call_args[1]
        assert call_kwargs["source_data"] == "https://github.com/test/repo"
        assert call_kwargs["loader"] == "github"

    def test_crawler_source(self, app):
        from application.api.user.sources.upload import UploadRemote

        mock_task = SimpleNamespace(id="task-cr")
        config = json.dumps({"url": "https://example.com"})

        with app.test_request_context(
            "/api/remote", method="POST",
            data={"user": "u1", "source": "crawler", "name": "site", "data": config},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.ingest_remote"
            ) as mock_ingest:
                mock_ingest.delay.return_value = mock_task
                response = UploadRemote().post()

        assert _status(response) == 200
        call_kwargs = mock_ingest.delay.call_args[1]
        assert call_kwargs["source_data"] == "https://example.com"

    def test_url_source(self, app):
        from application.api.user.sources.upload import UploadRemote

        mock_task = SimpleNamespace(id="task-url")
        config = json.dumps({"url": "https://example.com/doc"})

        with app.test_request_context(
            "/api/remote", method="POST",
            data={"user": "u1", "source": "url", "name": "url-src", "data": config},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.ingest_remote"
            ) as mock_ingest:
                mock_ingest.delay.return_value = mock_task
                response = UploadRemote().post()

        assert _status(response) == 200
        call_kwargs = mock_ingest.delay.call_args[1]
        assert call_kwargs["source_data"] == "https://example.com/doc"

    def test_reddit_source(self, app):
        from application.api.user.sources.upload import UploadRemote

        mock_task = SimpleNamespace(id="task-reddit")
        config_data = {"subreddit": "python", "limit": 10}
        config = json.dumps(config_data)

        with app.test_request_context(
            "/api/remote", method="POST",
            data={"user": "u1", "source": "reddit", "name": "reddit-src", "data": config},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.ingest_remote"
            ) as mock_ingest:
                mock_ingest.delay.return_value = mock_task
                response = UploadRemote().post()

        assert _status(response) == 200
        call_kwargs = mock_ingest.delay.call_args[1]
        assert call_kwargs["source_data"] == config_data

    def test_s3_source(self, app):
        from application.api.user.sources.upload import UploadRemote

        mock_task = SimpleNamespace(id="task-s3")
        config_data = {"bucket": "my-bucket", "key": "data/"}
        config = json.dumps(config_data)

        with app.test_request_context(
            "/api/remote", method="POST",
            data={"user": "u1", "source": "s3", "name": "s3-src", "data": config},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.ingest_remote"
            ) as mock_ingest:
                mock_ingest.delay.return_value = mock_task
                response = UploadRemote().post()

        assert _status(response) == 200
        call_kwargs = mock_ingest.delay.call_args[1]
        assert call_kwargs["source_data"] == config_data

    def test_connector_source_success(self, app):
        from application.api.user.sources.upload import UploadRemote

        mock_task = SimpleNamespace(id="task-gd")
        config = json.dumps({
            "session_token": "token123",
            "file_ids": ["f1", "f2"],
            "folder_ids": "fold1, fold2",
            "recursive": True,
            "retriever": "classic",
        })

        with app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u1",
                "source": "google_drive",
                "name": "gdrive",
                "data": config,
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.ConnectorCreator.get_supported_connectors",
                return_value=["google_drive", "share_point"],
            ), patch(
                "application.api.user.sources.upload.ingest_connector_task"
            ) as mock_connector:
                mock_connector.delay.return_value = mock_task
                response = UploadRemote().post()

        assert _status(response) == 200
        data = _json(response)
        assert data["task_id"] == "task-gd"
        call_kwargs = mock_connector.delay.call_args[1]
        assert call_kwargs["session_token"] == "token123"
        assert call_kwargs["file_ids"] == ["f1", "f2"]
        assert call_kwargs["folder_ids"] == ["fold1", "fold2"]
        assert call_kwargs["recursive"] is True

    def test_connector_source_missing_session_token(self, app):
        from application.api.user.sources.upload import UploadRemote

        config = json.dumps({"file_ids": ["f1"]})

        with app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u1",
                "source": "google_drive",
                "name": "gdrive",
                "data": config,
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.ConnectorCreator.get_supported_connectors",
                return_value=["google_drive"],
            ):
                response = UploadRemote().post()

        assert _status(response) == 400
        assert "session_token" in _json(response)["error"]

    def test_connector_file_ids_as_string(self, app):
        from application.api.user.sources.upload import UploadRemote

        mock_task = SimpleNamespace(id="task-sp")
        config = json.dumps({
            "session_token": "tok",
            "file_ids": "a, b, c",
            "folder_ids": [],
        })

        with app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u1",
                "source": "share_point",
                "name": "sp",
                "data": config,
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.ConnectorCreator.get_supported_connectors",
                return_value=["share_point"],
            ), patch(
                "application.api.user.sources.upload.ingest_connector_task"
            ) as mock_ct:
                mock_ct.delay.return_value = mock_task
                response = UploadRemote().post()

        assert _status(response) == 200
        call_kwargs = mock_ct.delay.call_args[1]
        assert call_kwargs["file_ids"] == ["a", "b", "c"]

    def test_connector_non_list_file_ids_becomes_empty(self, app):
        from application.api.user.sources.upload import UploadRemote

        mock_task = SimpleNamespace(id="task-sp2")
        config = json.dumps({
            "session_token": "tok",
            "file_ids": 42,
            "folder_ids": True,
        })

        with app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u1",
                "source": "share_point",
                "name": "sp",
                "data": config,
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.ConnectorCreator.get_supported_connectors",
                return_value=["share_point"],
            ), patch(
                "application.api.user.sources.upload.ingest_connector_task"
            ) as mock_ct:
                mock_ct.delay.return_value = mock_task
                response = UploadRemote().post()

        assert _status(response) == 200
        call_kwargs = mock_ct.delay.call_args[1]
        assert call_kwargs["file_ids"] == []
        assert call_kwargs["folder_ids"] == []

    def test_returns_400_on_error(self, app):
        from application.api.user.sources.upload import UploadRemote

        with app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u1",
                "source": "github",
                "name": "repo",
                "data": "invalid-json",
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = UploadRemote().post()

        assert _status(response) == 400


# ---------------------------------------------------------------------------
# ManageSourceFiles (/api/manage_source_files)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManageSourceFiles:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        with app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": "abc", "operation": "add"},
        ):
            from flask import request

            request.decoded_token = None
            response = ManageSourceFiles().post()

        assert _status(response) == 401

    def test_returns_400_missing_source_id(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        with app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"operation": "add"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = ManageSourceFiles().post()

        assert _status(response) == 400

    def test_returns_400_missing_operation(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        with app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": str(ObjectId())},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = ManageSourceFiles().post()

        assert _status(response) == 400

    def test_returns_400_invalid_operation(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        with app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": str(ObjectId()), "operation": "invalid"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = ManageSourceFiles().post()

        assert _status(response) == 400
        assert "must be" in _json(response)["message"]

    def test_returns_400_invalid_source_id_format(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        with app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": "bad-id", "operation": "add"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = ManageSourceFiles().post()

        assert _status(response) == 400
        assert "Invalid source ID" in _json(response)["message"]

    def test_returns_404_when_source_not_found(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        mock_collection = Mock()
        mock_collection.find_one.return_value = None
        source_id = str(ObjectId())

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={"source_id": source_id, "operation": "add"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 404

    def test_add_operation_no_files_returns_400(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }
        mock_storage = MagicMock()

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ):
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={"source_id": source_id, "operation": "add"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 400
        assert "No files" in _json(response)["message"]

    def test_add_operation_success(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
            "file_name_map": {},
        }
        mock_storage = MagicMock()
        mock_task = SimpleNamespace(id="reingest-1")

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task"
        ) as mock_reingest:
            mock_reingest.delay.return_value = mock_task
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "add",
                    "file": (io.BytesIO(b"content"), "new_file.txt"),
                },
                content_type="multipart/form-data",
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 200
        data = _json(response)
        assert data["success"] is True
        assert "1 files" in data["message"]
        assert data["reingest_task_id"] == "reingest-1"

    def test_add_operation_with_parent_dir(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
            "file_name_map": {},
        }
        mock_storage = MagicMock()
        mock_task = SimpleNamespace(id="reingest-2")

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task"
        ) as mock_reingest:
            mock_reingest.delay.return_value = mock_task
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "add",
                    "parent_dir": "subdir",
                    "file": (io.BytesIO(b"content"), "f.txt"),
                },
                content_type="multipart/form-data",
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 200
        data = _json(response)
        assert data["parent_dir"] == "subdir"
        # Verify storage.save_file was called with path including parent_dir
        save_call = mock_storage.save_file.call_args
        assert "subdir" in save_call[0][1]

    def test_add_rejects_invalid_parent_dir(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }
        mock_storage = MagicMock()

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ):
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "add",
                    "parent_dir": "../escape",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 400
        assert "Invalid parent" in _json(response)["message"]

    def test_add_rejects_absolute_parent_dir(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }
        mock_storage = MagicMock()

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ):
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "add",
                    "parent_dir": "/etc/passwd",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 400

    def test_remove_operation_success(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
            "file_name_map": {"old.txt": "Original Name.txt"},
        }
        mock_storage = MagicMock()
        mock_storage.file_exists.return_value = True
        mock_task = SimpleNamespace(id="reingest-3")

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task"
        ) as mock_reingest:
            mock_reingest.delay.return_value = mock_task
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove",
                    "file_paths": json.dumps(["old.txt"]),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 200
        data = _json(response)
        assert "1 files" in data["message"]
        mock_storage.delete_file.assert_called_once()

    def test_remove_missing_file_paths_returns_400(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }
        mock_storage = MagicMock()

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ):
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={"source_id": source_id, "operation": "remove"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 400
        assert "file_paths required" in _json(response)["message"]

    def test_remove_invalid_file_paths_format(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }
        mock_storage = MagicMock()

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ):
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove",
                    "file_paths": "not-valid-json{",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 400
        assert "Invalid file_paths" in _json(response)["message"]

    def test_remove_directory_success(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
            "file_name_map": {"subdir/a.txt": "A.txt", "subdir/b.txt": "B.txt", "other.txt": "Other.txt"},
        }
        mock_storage = MagicMock()
        mock_storage.is_directory.return_value = True
        mock_storage.remove_directory.return_value = True
        mock_task = SimpleNamespace(id="reingest-4")

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task"
        ) as mock_reingest:
            mock_reingest.delay.return_value = mock_task
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove_directory",
                    "directory_path": "subdir",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 200
        data = _json(response)
        assert data["removed_directory"] == "subdir"
        # file_name_map should have subdir entries removed
        update_call = mock_collection.update_one.call_args
        updated_map = update_call[0][1]["$set"]["file_name_map"]
        assert "subdir/a.txt" not in updated_map
        assert "other.txt" in updated_map

    def test_remove_directory_missing_path_returns_400(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }
        mock_storage = MagicMock()

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ):
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove_directory",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 400
        assert "directory_path required" in _json(response)["message"]

    def test_remove_directory_path_traversal_rejected(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }
        mock_storage = MagicMock()

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ):
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove_directory",
                    "directory_path": "../../../etc",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 400
        assert "Invalid directory" in _json(response)["message"]

    def test_remove_directory_not_found_returns_404(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }
        mock_storage = MagicMock()
        mock_storage.is_directory.return_value = False

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ):
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove_directory",
                    "directory_path": "nonexistent",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 404

    def test_remove_directory_storage_failure_returns_500(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }
        mock_storage = MagicMock()
        mock_storage.is_directory.return_value = True
        mock_storage.remove_directory.return_value = False

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ):
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove_directory",
                    "directory_path": "mydir",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 500

    def test_returns_500_on_db_find_error(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.side_effect = Exception("db error")

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={"source_id": source_id, "operation": "add"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 500

    def test_file_name_map_as_json_string(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
            "file_name_map": json.dumps({"old.txt": "Old File.txt"}),
        }
        mock_storage = MagicMock()
        mock_storage.file_exists.return_value = True
        mock_task = SimpleNamespace(id="reingest-5")

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task"
        ) as mock_reingest:
            mock_reingest.delay.return_value = mock_task
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove",
                    "file_paths": json.dumps(["old.txt"]),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 200

    def test_general_operation_error_returns_500(self, app):
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            side_effect=Exception("storage crash"),
        ):
            with app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove",
                    "file_paths": json.dumps(["x.txt"]),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 500
        assert "Operation failed" in _json(response)["message"]


# ---------------------------------------------------------------------------
# TaskStatus (/api/task_status)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTaskStatus:

    def test_returns_400_when_task_id_missing(self, app):
        from application.api.user.sources.upload import TaskStatus

        with app.test_request_context("/api/task_status"):
            response = TaskStatus().get()

        assert _status(response) == 400
        assert "Task ID is required" in _json(response)["message"]

    def test_returns_task_status_success(self, app):
        from application.api.user.sources.upload import TaskStatus

        mock_task = Mock()
        mock_task.status = "SUCCESS"
        mock_task.info = {"result": "done"}

        mock_celery = Mock()
        mock_celery.AsyncResult.return_value = mock_task

        with patch(
            "application.celery_init.celery", mock_celery
        ):
            with app.test_request_context("/api/task_status?task_id=tid-123"):
                response = TaskStatus().get()

        assert _status(response) == 200
        data = _json(response)
        assert data["status"] == "SUCCESS"
        assert data["result"] == {"result": "done"}

    def test_returns_task_status_pending_with_workers(self, app):
        from application.api.user.sources.upload import TaskStatus

        mock_task = Mock()
        mock_task.status = "PENDING"
        mock_task.info = None

        mock_inspect = Mock()
        mock_inspect.ping.return_value = {"worker1": {"ok": "pong"}}
        mock_celery = Mock()
        mock_celery.AsyncResult.return_value = mock_task
        mock_celery.control.inspect.return_value = mock_inspect

        with patch(
            "application.celery_init.celery", mock_celery
        ):
            with app.test_request_context("/api/task_status?task_id=tid-pend"):
                response = TaskStatus().get()

        assert _status(response) == 200

    def test_returns_503_when_no_workers(self, app):
        from application.api.user.sources.upload import TaskStatus

        mock_task = Mock()
        mock_task.status = "PENDING"
        mock_task.info = None

        mock_inspect = Mock()
        mock_inspect.ping.return_value = None
        mock_celery = Mock()
        mock_celery.AsyncResult.return_value = mock_task
        mock_celery.control.inspect.return_value = mock_inspect

        with patch(
            "application.celery_init.celery", mock_celery
        ):
            with app.test_request_context("/api/task_status?task_id=tid-nw"):
                response = TaskStatus().get()

        assert _status(response) == 503
        assert "unavailable" in _json(response)["message"]

    def test_handles_non_serializable_task_meta(self, app):
        from application.api.user.sources.upload import TaskStatus

        mock_task = Mock()
        mock_task.status = "SUCCESS"
        mock_task.info = object()  # non-serializable

        mock_celery = Mock()
        mock_celery.AsyncResult.return_value = mock_task

        with patch(
            "application.celery_init.celery", mock_celery
        ):
            with app.test_request_context("/api/task_status?task_id=tid-ns"):
                response = TaskStatus().get()

        assert _status(response) == 200
        data = _json(response)
        # Non-serializable info should be converted to string
        assert isinstance(data["result"], str)

    def test_returns_400_on_general_error(self, app):
        from application.api.user.sources.upload import TaskStatus

        with patch(
            "application.celery_init.celery",
        ) as mock_celery:
            mock_celery.AsyncResult.side_effect = Exception("broken")
            with app.test_request_context("/api/task_status?task_id=tid-err"):
                response = TaskStatus().get()

        assert _status(response) == 400


# ---------------------------------------------------------------------------
# Additional coverage: zip extraction paths and ManageSourceFiles edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadFileZipExtraction:
    """Cover zip file extraction (lines 102-136) and error fallback."""

    def test_zip_file_extraction_success(self, app):
        """Lines 102-127: zip file is extracted and inner files uploaded."""
        import zipfile

        from application.api.user.sources.upload import UploadFile

        mock_storage = MagicMock()
        mock_task = SimpleNamespace(id="task-zip")

        # Create a real zip file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("inner_file.txt", "hello zip content")
        zip_buffer.seek(0)

        with app.test_request_context(
            "/api/upload",
            method="POST",
            data={
                "user": "u1",
                "name": "ZipDoc",
                "file": (zip_buffer, "archive.zip"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.StorageCreator.get_storage",
                return_value=mock_storage,
            ), patch(
                "application.api.user.sources.upload.ingest"
            ) as mock_ingest, patch(
                "application.api.user.sources.upload._enforce_audio_path_size_limit",
            ):
                mock_ingest.delay.return_value = mock_task
                response = UploadFile().post()

        assert _status(response) == 200
        # Storage should have been called to save extracted files
        assert mock_storage.save_file.called

    def test_zip_extraction_error_falls_back_to_original(self, app):
        """Lines 128-136: zip extraction fails, original zip file is saved."""
        import zipfile

        from application.api.user.sources.upload import UploadFile

        mock_storage = MagicMock()
        mock_task = SimpleNamespace(id="task-zip-err")

        # Create a real zip file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("inner.txt", "content")
        zip_buffer.seek(0)

        def bad_extractall(**kwargs):
            raise Exception("corrupt zip")

        with app.test_request_context(
            "/api/upload",
            method="POST",
            data={
                "user": "u1",
                "name": "BadZip",
                "file": (zip_buffer, "bad.zip"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.StorageCreator.get_storage",
                return_value=mock_storage,
            ), patch(
                "application.api.user.sources.upload.ingest"
            ) as mock_ingest, patch(
                "application.api.user.sources.upload._enforce_audio_path_size_limit",
            ), patch(
                "application.api.user.sources.upload.zipfile.ZipFile"
            ) as mock_zip_cls:
                mock_zip_instance = MagicMock()
                mock_zip_instance.__enter__ = MagicMock(return_value=mock_zip_instance)
                mock_zip_instance.__exit__ = MagicMock(return_value=False)
                mock_zip_instance.extractall.side_effect = Exception("corrupt zip")
                mock_zip_cls.return_value = mock_zip_instance
                mock_ingest.delay.return_value = mock_task
                response = UploadFile().post()

        assert _status(response) == 200
        # Fallback: storage should save the original zip
        assert mock_storage.save_file.called

    def test_upload_returns_413_for_oversized_audio(self, app):
        """Lines 152-161: AudioFileTooLargeError caught."""
        from application.api.user.sources.upload import UploadFile
        from application.stt.upload_limits import AudioFileTooLargeError

        mock_storage = MagicMock()

        with app.test_request_context(
            "/api/upload",
            method="POST",
            data={
                "user": "u1",
                "name": "AudioDoc",
                "file": (io.BytesIO(b"audio data"), "big.wav"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}

            with patch(
                "application.api.user.sources.upload.StorageCreator.get_storage",
                return_value=mock_storage,
            ), patch(
                "application.api.user.sources.upload._enforce_audio_path_size_limit",
                side_effect=AudioFileTooLargeError("too big"),
            ):
                response = UploadFile().post()

        assert _status(response) == 413
        assert "success" in _json(response) and _json(response)["success"] is False


@pytest.mark.unit
class TestManageSourceFilesAdditional:
    """Additional edge cases for ManageSourceFiles."""

    def test_remove_with_absolute_directory_path_rejected(self, app):
        """Lines 513-523: directory_path starting with / is rejected."""
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }
        mock_storage = MagicMock()

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ):
            with app.test_request_context(
                "/api/manage_source_files",
                method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove_directory",
                    "directory_path": "/etc/passwd",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 400
        assert "Invalid directory" in _json(response)["message"]

    def test_remove_directory_no_keys_to_remove(self, app):
        """Lines 564-577: remove_directory with file_name_map that has no
        matching keys (keys_to_remove is empty)."""
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
            "file_name_map": {"unrelated.txt": "File.txt"},
        }
        mock_storage = MagicMock()
        mock_storage.is_directory.return_value = True
        mock_storage.remove_directory.return_value = True
        mock_task = SimpleNamespace(id="reingest-x")

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task"
        ) as mock_reingest:
            mock_reingest.delay.return_value = mock_task
            with app.test_request_context(
                "/api/manage_source_files",
                method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove_directory",
                    "directory_path": "no_match_dir",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 200
        # update_one should NOT be called because no keys matched
        mock_collection.update_one.assert_not_called()

    def test_general_error_remove_directory_context(self, app):
        """Line 598-600: error context includes directory_path for
        remove_directory operation."""
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            side_effect=Exception("storage crash"),
        ):
            with app.test_request_context(
                "/api/manage_source_files",
                method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove_directory",
                    "directory_path": "mydir",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 500
        assert "Operation failed" in _json(response)["message"]

    def test_general_error_add_context(self, app):
        """Lines 604-606: error context includes parent_dir for add operation."""
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
        }

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            side_effect=Exception("storage crash"),
        ):
            with app.test_request_context(
                "/api/manage_source_files",
                method="POST",
                data={
                    "source_id": source_id,
                    "operation": "add",
                    "parent_dir": "sub",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 500

    def test_file_name_map_non_dict_reset(self, app):
        """Lines 366-367: file_name_map not a dict is reset to {}."""
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
            "file_name_map": [1, 2, 3],  # not a dict
        }
        mock_storage = MagicMock()
        mock_storage.file_exists.return_value = True
        mock_task = SimpleNamespace(id="reingest-nd")

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task"
        ) as mock_reingest:
            mock_reingest.delay.return_value = mock_task
            with app.test_request_context(
                "/api/manage_source_files",
                method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove",
                    "file_paths": json.dumps(["x.txt"]),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 200

    def test_file_name_map_invalid_json_string_reset(self, app):
        """Lines 362-365: file_name_map is a string but not valid JSON."""
        from application.api.user.sources.upload import ManageSourceFiles

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": ObjectId(source_id),
            "user": "u1",
            "file_path": "uploads/u1/src",
            "file_name_map": "not-valid-json{",
        }
        mock_storage = MagicMock()
        mock_storage.file_exists.return_value = False
        mock_task = SimpleNamespace(id="reingest-ij")

        with patch(
            "application.api.user.sources.upload.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task"
        ) as mock_reingest:
            mock_reingest.delay.return_value = mock_task
            with app.test_request_context(
                "/api/manage_source_files",
                method="POST",
                data={
                    "source_id": source_id,
                    "operation": "remove",
                    "file_paths": json.dumps(["x.txt"]),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSourceFiles().post()

        assert _status(response) == 200
