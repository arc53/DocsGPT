import io
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, request


class _FakeAgentsRepo:
    """Post-PG migration replacement for the old Mongo `agents_collection`
    mock. Tests set `_FakeAgentsRepo._row` to control what `find_by_key`
    returns."""

    _row = None

    def __init__(self, *a, **kw):
        pass

    def find_by_key(self, key):
        return self._row


@contextmanager
def _fake_readonly():
    yield None


def _patch_agents_repo(row):
    _FakeAgentsRepo._row = row
    return (
        patch(
            "application.api.user.attachments.routes.AgentsRepository",
            _FakeAgentsRepo,
        ),
        patch(
            "application.api.user.attachments.routes.db_readonly",
            _fake_readonly,
        ),
    )


def _get_response_status(response):
    if isinstance(response, tuple):
        return response[1]
    return response.status_code


def _get_response_json(response):
    if isinstance(response, tuple):
        return response[0].json
    return response.json


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        _ = ttl
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class TestStoreAttachmentEndpoint:
    @patch("application.api.user.tasks.store_attachment.delay")
    def test_store_attachment_preserves_upload_indexes_for_partial_failures(
        self, mock_store_attachment, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import StoreAttachment

        app = Flask(__name__)
        mock_storage = MagicMock()
        mock_store_attachment.side_effect = [
            SimpleNamespace(id="task-alpha"),
            SimpleNamespace(id="task-gamma"),
        ]

        def save_file(file, path):
            _ = path
            if file.filename == "beta.txt":
                raise ValueError("Failed to save file")
            return {"storage_type": "local"}

        mock_storage.save_file.side_effect = save_file

        with patch("application.api.user.base.storage", mock_storage):
            with app.test_request_context(
                "/api/store_attachment",
                method="POST",
                data={
                    "file": [
                        (io.BytesIO(b"alpha"), "alpha.txt"),
                        (io.BytesIO(b"beta"), "beta.txt"),
                        (io.BytesIO(b"gamma"), "gamma.txt"),
                    ]
                },
                content_type="multipart/form-data",
            ):
                request.decoded_token = {"sub": "test_user"}

                resource = StoreAttachment()
                response = resource.post()
                payload = _get_response_json(response)

                assert _get_response_status(response) == 200
                assert [task["upload_index"] for task in payload["tasks"]] == [0, 2]
                assert payload["errors"][0]["upload_index"] == 1
                assert payload["errors"][0]["error"] == "Failed to process file"

    @patch("application.api.user.tasks.store_attachment.delay")
    @patch("application.stt.upload_limits.settings")
    def test_store_attachment_rejects_oversized_audio_files(
        self, mock_limit_settings, mock_store_attachment, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import StoreAttachment

        app = Flask(__name__)
        mock_limit_settings.STT_MAX_FILE_SIZE_MB = 1

        with app.test_request_context(
            "/api/store_attachment",
            method="POST",
            data={
                "file": (
                    io.BytesIO(b"x" * (2 * 1024 * 1024)),
                    "meeting.wav",
                )
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = StoreAttachment()
            response = resource.post()

            assert _get_response_status(response) == 413
            assert "exceeds" in _get_response_json(response)["message"]
            mock_store_attachment.assert_not_called()


class TestSpeechToTextEndpoint:
    def test_stt_returns_400_when_file_is_missing(self, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import SpeechToText

        app = Flask(__name__)

        with app.test_request_context("/api/stt", method="POST", data={}):
            request.decoded_token = {"sub": "test_user"}

            resource = SpeechToText()
            response = resource.post()

            assert _get_response_status(response) == 400
            assert _get_response_json(response)["message"] == "Missing file"

    def test_stt_returns_401_when_authentication_is_missing(
        self, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import SpeechToText

        app = Flask(__name__)

        with app.test_request_context(
            "/api/stt",
            method="POST",
            data={"file": (io.BytesIO(b"audio-bytes"), "clip.wav")},
            content_type="multipart/form-data",
        ):
            request.decoded_token = None

            resource = SpeechToText()
            response = resource.post()

            assert _get_response_status(response) == 401
            assert _get_response_json(response)["message"] == "Authentication required"

    @patch("application.api.user.attachments.routes.STTCreator.create_stt")
    def test_stt_transcribes_audio_for_authenticated_user(
        self, mock_create_stt, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import SpeechToText

        app = Flask(__name__)
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "text": "hello from audio",
            "language": "en",
            "duration_s": 1.2,
            "segments": [],
            "provider": "openai",
        }
        mock_create_stt.return_value = mock_stt

        with app.test_request_context(
            "/api/stt",
            method="POST",
            data={
                "file": (io.BytesIO(b"audio-bytes"), "clip.wav"),
                "language": "en",
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = SpeechToText()
            response = resource.post()

            assert _get_response_status(response) == 200
            assert _get_response_json(response) == {
                "success": True,
                "text": "hello from audio",
                "language": "en",
                "duration_s": 1.2,
                "segments": [],
                "provider": "openai",
            }
            mock_create_stt.assert_called_once()
            mock_stt.transcribe.assert_called_once()

    def test_stt_rejects_unsupported_extension(self, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import SpeechToText

        app = Flask(__name__)

        with app.test_request_context(
            "/api/stt",
            method="POST",
            data={"file": (io.BytesIO(b"audio-bytes"), "clip.exe")},
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = SpeechToText()
            response = resource.post()

            assert _get_response_status(response) == 400
            assert "Unsupported audio format" in _get_response_json(response)["message"]


class TestLiveSpeechToTextEndpoint:
    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_start_creates_session(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import LiveSpeechToTextStart

        app = Flask(__name__)
        mock_get_redis.return_value = FakeRedis()

        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={"language": "ru"},
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = LiveSpeechToTextStart()
            response = resource.post()
            payload = _get_response_json(response)

            assert _get_response_status(response) == 200
            assert payload["success"] is True
            assert payload["language"] == "ru"
            assert payload["session_id"]
            assert payload["transcript_text"] == ""

    @patch("application.api.user.attachments.routes.STTCreator.create_stt")
    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_reconciles_transcript_progressively(
        self, mock_get_redis, mock_create_stt, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import (
            LiveSpeechToTextChunk,
            LiveSpeechToTextFinish,
            LiveSpeechToTextStart,
        )

        app = Flask(__name__)
        fake_redis = FakeRedis()
        mock_get_redis.return_value = fake_redis

        start_resource = LiveSpeechToTextStart()
        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={"language": "ru"},
        ):
            request.decoded_token = {"sub": "test_user"}
            start_response = start_resource.post()
            session_id = _get_response_json(start_response)["session_id"]

        mock_stt = MagicMock()
        mock_stt.transcribe.side_effect = [
            {
                "text": "hello this is a longer test phrase for transcript stabilization today now",
                "language": "ru",
                "duration_s": 1.0,
                "segments": [],
                "provider": "openai",
            },
            {
                "text": "hello this is a longer test phrase for transcript stabilization today now again later",
                "language": "ru",
                "duration_s": 1.0,
                "segments": [],
                "provider": "openai",
            },
        ]
        mock_create_stt.return_value = mock_stt

        chunk_resource = LiveSpeechToTextChunk()
        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": session_id,
                "chunk_index": "0",
                "file": (io.BytesIO(b"chunk-0"), "chunk-0.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}
            chunk_response = chunk_resource.post()
            chunk_payload = _get_response_json(chunk_response)

            assert _get_response_status(chunk_response) == 200
            assert (
                chunk_payload["transcript_text"]
                == "hello this is a longer test phrase for transcript stabilization today now"
            )
            assert chunk_payload["committed_text"] == ""
            assert (
                chunk_payload["mutable_text"]
                == "hello this is a longer test phrase for transcript stabilization today now"
            )
            assert chunk_payload["finalized_text"] == ""
            assert (
                chunk_payload["pending_text"]
                == "hello this is a longer test phrase for transcript stabilization today now"
            )

        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": session_id,
                "chunk_index": "1",
                "is_silence": "true",
                "file": (io.BytesIO(b"chunk-1"), "chunk-1.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}
            chunk_response = chunk_resource.post()
            chunk_payload = _get_response_json(chunk_response)

            assert _get_response_status(chunk_response) == 200
            assert (
                chunk_payload["transcript_text"]
                == "hello this is a longer test phrase for transcript stabilization today now again later"
            )
            assert (
                chunk_payload["committed_text"]
                == "hello this is a longer test phrase for transcript stabilization today now"
            )
            assert chunk_payload["mutable_text"] == "again later"
            assert chunk_payload["finalized_text"] == chunk_payload["committed_text"]
            assert chunk_payload["pending_text"] == "again later"
            assert chunk_payload["is_silence"] is True

        finish_resource = LiveSpeechToTextFinish()
        with app.test_request_context(
            "/api/stt/live/finish",
            method="POST",
            json={"session_id": session_id},
        ):
            request.decoded_token = {"sub": "test_user"}
            finish_response = finish_resource.post()
            finish_payload = _get_response_json(finish_response)

            assert _get_response_status(finish_response) == 200
            assert (
                finish_payload["text"]
                == "hello this is a longer test phrase for transcript stabilization today now again later"
            )

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_rejects_missing_session(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import LiveSpeechToTextChunk

        app = Flask(__name__)
        mock_get_redis.return_value = FakeRedis()

        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": "missing-session",
                "chunk_index": "0",
                "file": (io.BytesIO(b"chunk-0"), "chunk-0.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = LiveSpeechToTextChunk()
            response = resource.post()

            assert _get_response_status(response) == 404
            assert _get_response_json(response)["message"] == "Live transcription session not found"

    @patch("application.api.user.attachments.routes.STTCreator.create_stt")
    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_hides_internal_value_errors(
        self, mock_get_redis, mock_create_stt, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import (
            LiveSpeechToTextChunk,
            LiveSpeechToTextStart,
        )

        app = Flask(__name__)
        fake_redis = FakeRedis()
        mock_get_redis.return_value = fake_redis

        start_resource = LiveSpeechToTextStart()
        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={"language": "ru"},
        ):
            request.decoded_token = {"sub": "test_user"}
            start_response = start_resource.post()
            session_id = _get_response_json(start_response)["session_id"]

        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "text": "hello there",
            "language": "ru",
            "duration_s": 1.0,
            "segments": [],
            "provider": "openai",
        }
        mock_create_stt.return_value = mock_stt

        chunk_resource = LiveSpeechToTextChunk()
        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": session_id,
                "chunk_index": "-1",
                "file": (io.BytesIO(b"chunk-neg"), "chunk-neg.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}
            response = chunk_resource.post()

            assert _get_response_status(response) == 409
            assert (
                _get_response_json(response)["message"]
                == "Invalid live transcription chunk"
            )


@pytest.mark.unit
class TestResolveAuthenticatedUser:
    """Tests for _resolve_authenticated_user helper."""

    def test_returns_user_from_decoded_token(self, flask_app):
        from application.api.user.attachments.routes import _resolve_authenticated_user

        app = Flask(__name__)
        with app.test_request_context("/api/store_attachment", method="POST"):
            request.decoded_token = {"sub": "jwt_user"}
            result = _resolve_authenticated_user()
            assert result is not None
            assert "jwt_user" in result

    def test_returns_user_from_valid_api_key_form(self, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import _resolve_authenticated_user

        app = Flask(__name__)
        p1, p2 = _patch_agents_repo({"key": "valid_key", "user_id": "apikey_user"})

        with p1, p2:
            with app.test_request_context(
                "/api/store_attachment",
                method="POST",
                data={"api_key": "valid_key"},
            ):
                request.decoded_token = None
                result = _resolve_authenticated_user()
                assert result is not None
                assert "apikey_user" in result

    def test_returns_401_for_invalid_api_key(self, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import _resolve_authenticated_user

        app = Flask(__name__)
        p1, p2 = _patch_agents_repo(None)

        with p1, p2:
            with app.test_request_context(
                "/api/store_attachment",
                method="POST",
                data={"api_key": "bad_key"},
            ):
                request.decoded_token = None
                result = _resolve_authenticated_user()
                assert hasattr(result, "status_code")
                assert result.status_code == 401

    def test_returns_none_no_auth(self, flask_app):
        from application.api.user.attachments.routes import _resolve_authenticated_user

        app = Flask(__name__)
        with app.test_request_context("/api/store_attachment", method="POST"):
            request.decoded_token = None
            result = _resolve_authenticated_user()
            assert result is None


@pytest.mark.unit
class TestGetUploadedFileSize:
    """Tests for _get_uploaded_file_size helper."""

    def test_returns_file_size(self):
        from application.api.user.attachments.routes import _get_uploaded_file_size

        file = MagicMock()
        file.stream.tell.side_effect = [0, 1024]
        result = _get_uploaded_file_size(file)
        assert result == 1024

    def test_returns_zero_on_exception(self):
        from application.api.user.attachments.routes import _get_uploaded_file_size

        file = MagicMock()
        file.stream.tell.side_effect = Exception("stream error")
        result = _get_uploaded_file_size(file)
        assert result == 0


@pytest.mark.unit
class TestIsSupportedAudioMimetype:
    """Tests for _is_supported_audio_mimetype helper."""

    def test_empty_mimetype_returns_true(self):
        from application.api.user.attachments.routes import _is_supported_audio_mimetype

        assert _is_supported_audio_mimetype("") is True

    def test_none_mimetype_returns_true(self):
        from application.api.user.attachments.routes import _is_supported_audio_mimetype

        assert _is_supported_audio_mimetype(None) is True

    def test_audio_mimetype_returns_true(self):
        from application.api.user.attachments.routes import _is_supported_audio_mimetype

        assert _is_supported_audio_mimetype("audio/wav") is True
        assert _is_supported_audio_mimetype("audio/mp3") is True

    def test_unsupported_mimetype_returns_false(self):
        from application.api.user.attachments.routes import _is_supported_audio_mimetype

        assert _is_supported_audio_mimetype("text/plain") is False

    def test_mimetype_with_params(self):
        from application.api.user.attachments.routes import _is_supported_audio_mimetype

        assert _is_supported_audio_mimetype("audio/wav; codecs=1") is True


@pytest.mark.unit
class TestEnforceUploadedAudioSizeLimit:
    """Tests for _enforce_uploaded_audio_size_limit."""

    def test_non_audio_file_is_ignored(self):
        from application.api.user.attachments.routes import (
            _enforce_uploaded_audio_size_limit,
        )

        file = MagicMock()
        # Should not raise for non-audio files
        _enforce_uploaded_audio_size_limit(file, "readme.txt")

    @patch("application.api.user.attachments.routes.enforce_audio_file_size_limit")
    @patch("application.api.user.attachments.routes._get_uploaded_file_size")
    def test_audio_file_calls_enforce(self, mock_size, mock_enforce):
        from application.api.user.attachments.routes import (
            _enforce_uploaded_audio_size_limit,
        )

        mock_size.return_value = 5000
        file = MagicMock()
        _enforce_uploaded_audio_size_limit(file, "clip.wav")
        mock_enforce.assert_called_once_with(5000)


@pytest.mark.unit
class TestStoreAttachmentAdditional:
    """Additional tests for StoreAttachment endpoint."""

    def test_store_attachment_returns_401_for_invalid_api_key(
        self, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import StoreAttachment

        app = Flask(__name__)
        p1, p2 = _patch_agents_repo(None)

        with p1, p2:
            with app.test_request_context(
                "/api/store_attachment",
                method="POST",
                data={
                    "api_key": "bad_key",
                    "file": (io.BytesIO(b"data"), "test.txt"),
                },
                content_type="multipart/form-data",
            ):
                request.decoded_token = None

                resource = StoreAttachment()
                response = resource.post()
                assert _get_response_status(response) == 401

    def test_store_attachment_missing_file(self, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import StoreAttachment

        app = Flask(__name__)
        with app.test_request_context(
            "/api/store_attachment",
            method="POST",
            data={},
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = StoreAttachment()
            response = resource.post()
            assert _get_response_status(response) == 400

    def test_store_attachment_no_auth_returns_401(self, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import StoreAttachment

        app = Flask(__name__)
        with app.test_request_context(
            "/api/store_attachment",
            method="POST",
            data={"file": (io.BytesIO(b"data"), "test.txt")},
            content_type="multipart/form-data",
        ):
            request.decoded_token = None

            resource = StoreAttachment()
            response = resource.post()
            assert _get_response_status(response) == 401

    @patch("application.api.user.tasks.store_attachment.delay")
    def test_store_attachment_single_file_response(
        self, mock_store_attachment, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import StoreAttachment

        app = Flask(__name__)
        mock_storage = MagicMock()
        mock_storage.save_file.return_value = {"storage_type": "local"}
        mock_store_attachment.return_value = SimpleNamespace(id="task-single")

        with patch("application.api.user.base.storage", mock_storage):
            with app.test_request_context(
                "/api/store_attachment",
                method="POST",
                data={"file": (io.BytesIO(b"data"), "single.txt")},
                content_type="multipart/form-data",
            ):
                request.decoded_token = {"sub": "test_user"}

                resource = StoreAttachment()
                response = resource.post()
                payload = _get_response_json(response)

                assert _get_response_status(response) == 200
                assert payload["task_id"] == "task-single"

    @patch("application.api.user.tasks.store_attachment.delay")
    def test_store_attachment_all_files_fail_returns_400(
        self, mock_store_attachment, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import StoreAttachment

        app = Flask(__name__)
        mock_storage = MagicMock()
        mock_storage.save_file.side_effect = ValueError("save error")

        with patch("application.api.user.base.storage", mock_storage):
            with app.test_request_context(
                "/api/store_attachment",
                method="POST",
                data={"file": (io.BytesIO(b"data"), "fail.txt")},
                content_type="multipart/form-data",
            ):
                request.decoded_token = {"sub": "test_user"}

                resource = StoreAttachment()
                response = resource.post()
                assert _get_response_status(response) == 400

    @patch("application.api.user.tasks.store_attachment.delay")
    def test_store_attachment_outer_exception(
        self, mock_store_attachment, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import StoreAttachment

        app = Flask(__name__)

        with patch(
            "application.api.user.base.storage",
            side_effect=Exception("unexpected"),
        ):
            with app.test_request_context(
                "/api/store_attachment",
                method="POST",
                data={"file": (io.BytesIO(b"data"), "test.txt")},
                content_type="multipart/form-data",
            ):
                request.decoded_token = {"sub": "test_user"}

                resource = StoreAttachment()
                response = resource.post()
                assert _get_response_status(response) == 400

    def test_store_attachment_empty_filename_files(self, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import StoreAttachment

        app = Flask(__name__)
        with app.test_request_context(
            "/api/store_attachment",
            method="POST",
            data={"file": (io.BytesIO(b""), "")},
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = StoreAttachment()
            response = resource.post()
            assert _get_response_status(response) == 400

    @patch("application.api.user.tasks.store_attachment.delay")
    def test_store_attachment_via_api_key_auth(
        self, mock_store_attachment, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import StoreAttachment

        app = Flask(__name__)
        mock_storage = MagicMock()
        mock_storage.save_file.return_value = {"storage_type": "local"}
        mock_store_attachment.return_value = SimpleNamespace(id="task-api")
        p1, p2 = _patch_agents_repo(
            {"key": "valid_key", "user_id": "apikey_user"}
        )

        with patch("application.api.user.base.storage", mock_storage), p1, p2:
            with app.test_request_context(
                "/api/store_attachment",
                method="POST",
                data={
                    "api_key": "valid_key",
                    "file": (io.BytesIO(b"data"), "doc.txt"),
                },
                content_type="multipart/form-data",
            ):
                request.decoded_token = None

                resource = StoreAttachment()
                response = resource.post()
                payload = _get_response_json(response)

                assert _get_response_status(response) == 200
                assert payload["task_id"] == "task-api"


@pytest.mark.unit
class TestSpeechToTextAdditional:
    """Additional tests for SpeechToText endpoint."""

    @patch(
        "application.api.user.attachments.routes._is_supported_audio_mimetype",
        return_value=False,
    )
    def test_stt_rejects_unsupported_mimetype(
        self, mock_mimetype_check, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import SpeechToText

        app = Flask(__name__)
        with app.test_request_context(
            "/api/stt",
            method="POST",
            data={"file": (io.BytesIO(b"audio-bytes"), "clip.wav")},
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = SpeechToText()
            response = resource.post()
            assert _get_response_status(response) == 400
            assert "MIME" in _get_response_json(response)["message"]

    @patch("application.stt.upload_limits.settings")
    def test_stt_rejects_oversized_audio(
        self, mock_limit_settings, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import SpeechToText

        app = Flask(__name__)
        mock_limit_settings.STT_MAX_FILE_SIZE_MB = 1

        with app.test_request_context(
            "/api/stt",
            method="POST",
            data={
                "file": (io.BytesIO(b"x" * (2 * 1024 * 1024)), "clip.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = SpeechToText()
            response = resource.post()
            assert _get_response_status(response) == 413
            assert "exceeds" in _get_response_json(response)["message"]

    @patch("application.api.user.attachments.routes.STTCreator.create_stt")
    def test_stt_transcription_error_returns_400(
        self, mock_create_stt, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import SpeechToText

        app = Flask(__name__)
        mock_stt = MagicMock()
        mock_stt.transcribe.side_effect = Exception("transcription failed")
        mock_create_stt.return_value = mock_stt

        with app.test_request_context(
            "/api/stt",
            method="POST",
            data={"file": (io.BytesIO(b"audio-bytes"), "clip.wav")},
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = SpeechToText()
            response = resource.post()
            assert _get_response_status(response) == 400
            assert (
                _get_response_json(response)["message"]
                == "Failed to transcribe audio"
            )

    @patch("application.api.user.attachments.routes.STTCreator.create_stt")
    def test_stt_uses_language_form_param(
        self, mock_create_stt, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import SpeechToText

        app = Flask(__name__)
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "text": "hola",
            "language": "es",
        }
        mock_create_stt.return_value = mock_stt

        with app.test_request_context(
            "/api/stt",
            method="POST",
            data={
                "file": (io.BytesIO(b"audio-bytes"), "clip.wav"),
                "language": "es",
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = SpeechToText()
            response = resource.post()
            assert _get_response_status(response) == 200
            call_kwargs = mock_stt.transcribe.call_args
            assert call_kwargs.kwargs.get("language") == "es" or call_kwargs[1].get("language") == "es"


@pytest.mark.unit
class TestLiveSpeechToTextAdditional:
    """Additional tests for live STT endpoints."""

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_start_returns_401_no_auth(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import LiveSpeechToTextStart

        app = Flask(__name__)
        mock_get_redis.return_value = FakeRedis()

        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={},
        ):
            request.decoded_token = None

            resource = LiveSpeechToTextStart()
            response = resource.post()
            assert _get_response_status(response) == 401

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_start_returns_503_when_redis_unavailable(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import LiveSpeechToTextStart

        app = Flask(__name__)
        mock_get_redis.return_value = None

        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={},
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = LiveSpeechToTextStart()
            response = resource.post()
            assert _get_response_status(response) == 503

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_returns_401_no_auth(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import LiveSpeechToTextChunk

        app = Flask(__name__)
        mock_get_redis.return_value = FakeRedis()

        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": "some-session",
                "chunk_index": "0",
                "file": (io.BytesIO(b"chunk"), "chunk.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = None

            resource = LiveSpeechToTextChunk()
            response = resource.post()
            assert _get_response_status(response) == 401

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_returns_503_no_redis(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import LiveSpeechToTextChunk

        app = Flask(__name__)
        mock_get_redis.return_value = None

        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": "some-session",
                "chunk_index": "0",
                "file": (io.BytesIO(b"chunk"), "chunk.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = LiveSpeechToTextChunk()
            response = resource.post()
            assert _get_response_status(response) == 503

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_missing_session_id(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import LiveSpeechToTextChunk

        app = Flask(__name__)
        mock_get_redis.return_value = FakeRedis()

        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": "",
                "chunk_index": "0",
                "file": (io.BytesIO(b"chunk"), "chunk.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = LiveSpeechToTextChunk()
            response = resource.post()
            assert _get_response_status(response) == 400
            assert "session_id" in _get_response_json(response)["message"]

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_forbidden_different_user(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import (
            LiveSpeechToTextChunk,
            LiveSpeechToTextStart,
        )

        app = Flask(__name__)
        fake_redis = FakeRedis()
        mock_get_redis.return_value = fake_redis

        start_resource = LiveSpeechToTextStart()
        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={},
        ):
            request.decoded_token = {"sub": "owner_user"}
            start_response = start_resource.post()
            session_id = _get_response_json(start_response)["session_id"]

        chunk_resource = LiveSpeechToTextChunk()
        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": session_id,
                "chunk_index": "0",
                "file": (io.BytesIO(b"chunk"), "chunk.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "other_user"}

            response = chunk_resource.post()
            assert _get_response_status(response) == 403

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_missing_chunk_index(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import (
            LiveSpeechToTextChunk,
            LiveSpeechToTextStart,
        )

        app = Flask(__name__)
        fake_redis = FakeRedis()
        mock_get_redis.return_value = fake_redis

        start_resource = LiveSpeechToTextStart()
        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={},
        ):
            request.decoded_token = {"sub": "test_user"}
            start_response = start_resource.post()
            session_id = _get_response_json(start_response)["session_id"]

        chunk_resource = LiveSpeechToTextChunk()
        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": session_id,
                "chunk_index": "",
                "file": (io.BytesIO(b"chunk"), "chunk.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            response = chunk_resource.post()
            assert _get_response_status(response) == 400
            assert "chunk_index" in _get_response_json(response)["message"]

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_invalid_chunk_index(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import (
            LiveSpeechToTextChunk,
            LiveSpeechToTextStart,
        )

        app = Flask(__name__)
        fake_redis = FakeRedis()
        mock_get_redis.return_value = fake_redis

        start_resource = LiveSpeechToTextStart()
        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={},
        ):
            request.decoded_token = {"sub": "test_user"}
            start_response = start_resource.post()
            session_id = _get_response_json(start_response)["session_id"]

        chunk_resource = LiveSpeechToTextChunk()
        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": session_id,
                "chunk_index": "abc",
                "file": (io.BytesIO(b"chunk"), "chunk.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            response = chunk_resource.post()
            assert _get_response_status(response) == 400
            assert "Invalid chunk_index" in _get_response_json(response)["message"]

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_missing_file(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import (
            LiveSpeechToTextChunk,
            LiveSpeechToTextStart,
        )

        app = Flask(__name__)
        fake_redis = FakeRedis()
        mock_get_redis.return_value = fake_redis

        start_resource = LiveSpeechToTextStart()
        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={},
        ):
            request.decoded_token = {"sub": "test_user"}
            start_response = start_resource.post()
            session_id = _get_response_json(start_response)["session_id"]

        chunk_resource = LiveSpeechToTextChunk()
        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": session_id,
                "chunk_index": "0",
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            response = chunk_resource.post()
            assert _get_response_status(response) == 400
            assert "Missing file" in _get_response_json(response)["message"]

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_unsupported_extension(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import (
            LiveSpeechToTextChunk,
            LiveSpeechToTextStart,
        )

        app = Flask(__name__)
        fake_redis = FakeRedis()
        mock_get_redis.return_value = fake_redis

        start_resource = LiveSpeechToTextStart()
        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={},
        ):
            request.decoded_token = {"sub": "test_user"}
            start_response = start_resource.post()
            session_id = _get_response_json(start_response)["session_id"]

        chunk_resource = LiveSpeechToTextChunk()
        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": session_id,
                "chunk_index": "0",
                "file": (io.BytesIO(b"chunk"), "chunk.exe"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            response = chunk_resource.post()
            assert _get_response_status(response) == 400
            assert "Unsupported audio format" in _get_response_json(response)["message"]

    @patch("application.api.user.attachments.routes.STTCreator.create_stt")
    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_transcription_error(
        self, mock_get_redis, mock_create_stt, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import (
            LiveSpeechToTextChunk,
            LiveSpeechToTextStart,
        )

        app = Flask(__name__)
        fake_redis = FakeRedis()
        mock_get_redis.return_value = fake_redis

        start_resource = LiveSpeechToTextStart()
        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={},
        ):
            request.decoded_token = {"sub": "test_user"}
            start_response = start_resource.post()
            session_id = _get_response_json(start_response)["session_id"]

        mock_stt = MagicMock()
        mock_stt.transcribe.side_effect = Exception("transcription error")
        mock_create_stt.return_value = mock_stt

        chunk_resource = LiveSpeechToTextChunk()
        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": session_id,
                "chunk_index": "0",
                "file": (io.BytesIO(b"chunk"), "chunk.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            response = chunk_resource.post()
            assert _get_response_status(response) == 400
            assert (
                _get_response_json(response)["message"]
                == "Failed to transcribe audio"
            )

    @patch("application.api.user.attachments.routes.settings")
    @patch("application.api.user.attachments.routes.STTCreator.create_stt")
    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_chunk_detects_language(
        self, mock_get_redis, mock_create_stt, mock_settings, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import (
            LiveSpeechToTextChunk,
            LiveSpeechToTextStart,
        )

        mock_settings.STT_LANGUAGE = None
        mock_settings.STT_PROVIDER = "openai"
        mock_settings.STT_ENABLE_TIMESTAMPS = False
        mock_settings.STT_ENABLE_DIARIZATION = False
        mock_settings.UPLOAD_FOLDER = "uploads"

        app = Flask(__name__)
        fake_redis = FakeRedis()
        mock_get_redis.return_value = fake_redis

        start_resource = LiveSpeechToTextStart()
        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={},
        ):
            request.decoded_token = {"sub": "test_user"}
            start_response = start_resource.post()
            session_id = _get_response_json(start_response)["session_id"]

        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = {
            "text": "hola mundo esto es una prueba larga para pasar las validaciones de texto",
            "language": "es",
        }
        mock_create_stt.return_value = mock_stt

        chunk_resource = LiveSpeechToTextChunk()
        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": session_id,
                "chunk_index": "0",
                "file": (io.BytesIO(b"chunk"), "chunk.wav"),
            },
            content_type="multipart/form-data",
        ):
            request.decoded_token = {"sub": "test_user"}

            response = chunk_resource.post()
            payload = _get_response_json(response)
            assert _get_response_status(response) == 200
            assert payload["language"] == "es"

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_finish_returns_401_no_auth(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import LiveSpeechToTextFinish

        app = Flask(__name__)
        mock_get_redis.return_value = FakeRedis()

        with app.test_request_context(
            "/api/stt/live/finish",
            method="POST",
            json={"session_id": "some-id"},
        ):
            request.decoded_token = None

            resource = LiveSpeechToTextFinish()
            response = resource.post()
            assert _get_response_status(response) == 401

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_finish_returns_503_no_redis(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import LiveSpeechToTextFinish

        app = Flask(__name__)
        mock_get_redis.return_value = None

        with app.test_request_context(
            "/api/stt/live/finish",
            method="POST",
            json={"session_id": "some-id"},
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = LiveSpeechToTextFinish()
            response = resource.post()
            assert _get_response_status(response) == 503

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_finish_missing_session_id(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import LiveSpeechToTextFinish

        app = Flask(__name__)
        mock_get_redis.return_value = FakeRedis()

        with app.test_request_context(
            "/api/stt/live/finish",
            method="POST",
            json={},
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = LiveSpeechToTextFinish()
            response = resource.post()
            assert _get_response_status(response) == 400
            assert "session_id" in _get_response_json(response)["message"]

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_finish_session_not_found(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import LiveSpeechToTextFinish

        app = Flask(__name__)
        mock_get_redis.return_value = FakeRedis()

        with app.test_request_context(
            "/api/stt/live/finish",
            method="POST",
            json={"session_id": "nonexistent"},
        ):
            request.decoded_token = {"sub": "test_user"}

            resource = LiveSpeechToTextFinish()
            response = resource.post()
            assert _get_response_status(response) == 404

    @patch("application.api.user.attachments.routes.get_redis_instance")
    def test_live_stt_finish_forbidden_different_user(
        self, mock_get_redis, flask_app, mock_mongo_db
    ):
        from application.api.user.attachments.routes import (
            LiveSpeechToTextFinish,
            LiveSpeechToTextStart,
        )

        app = Flask(__name__)
        fake_redis = FakeRedis()
        mock_get_redis.return_value = fake_redis

        start_resource = LiveSpeechToTextStart()
        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={},
        ):
            request.decoded_token = {"sub": "owner_user"}
            start_response = start_resource.post()
            session_id = _get_response_json(start_response)["session_id"]

        finish_resource = LiveSpeechToTextFinish()
        with app.test_request_context(
            "/api/stt/live/finish",
            method="POST",
            json={"session_id": session_id},
        ):
            request.decoded_token = {"sub": "other_user"}

            response = finish_resource.post()
            assert _get_response_status(response) == 403


@pytest.mark.unit
class TestServeImage:
    """Tests for ServeImage endpoint."""

    def test_serve_image_success(self, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import ServeImage

        app = Flask(__name__)
        mock_storage = MagicMock()
        mock_file_obj = io.BytesIO(b"\x89PNG\r\n")
        mock_storage.get_file.return_value = mock_file_obj

        with patch("application.api.user.base.storage", mock_storage):
            with app.test_request_context(
                "/api/images/test/image.png",
                method="GET",
            ):
                resource = ServeImage()
                response = resource.get("test/image.png")
                assert _get_response_status(response) == 200
                assert response.headers.get("Content-Type") == "image/png"

    def test_serve_image_jpg_content_type(self, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import ServeImage

        app = Flask(__name__)
        mock_storage = MagicMock()
        mock_file_obj = io.BytesIO(b"\xff\xd8\xff\xe0")
        mock_storage.get_file.return_value = mock_file_obj

        with patch("application.api.user.base.storage", mock_storage):
            with app.test_request_context(
                "/api/images/test/photo.jpg",
                method="GET",
            ):
                resource = ServeImage()
                response = resource.get("test/photo.jpg")
                assert _get_response_status(response) == 200
                assert response.headers.get("Content-Type") == "image/jpeg"

    def test_serve_image_not_found(self, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import ServeImage

        app = Flask(__name__)
        mock_storage = MagicMock()
        mock_storage.get_file.side_effect = FileNotFoundError("not found")

        with patch("application.api.user.base.storage", mock_storage):
            with app.test_request_context(
                "/api/images/missing/image.png",
                method="GET",
            ):
                resource = ServeImage()
                response = resource.get("missing/image.png")
                assert _get_response_status(response) == 404

    def test_serve_image_generic_error(self, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import ServeImage

        app = Flask(__name__)
        mock_storage = MagicMock()
        mock_storage.get_file.side_effect = Exception("storage error")

        with patch("application.api.user.base.storage", mock_storage):
            with app.test_request_context(
                "/api/images/broken/image.png",
                method="GET",
            ):
                resource = ServeImage()
                response = resource.get("broken/image.png")
                assert _get_response_status(response) == 500


@pytest.mark.unit
class TestTextToSpeech:
    """Tests for TextToSpeech endpoint."""

    @patch("application.api.user.attachments.routes.TTSCreator.create_tts")
    def test_tts_success(self, mock_create_tts, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import TextToSpeech

        app = Flask(__name__)
        mock_tts = MagicMock()
        mock_tts.text_to_speech.return_value = ("base64audio==", "en")
        mock_create_tts.return_value = mock_tts

        with app.test_request_context(
            "/api/tts",
            method="POST",
            json={"text": "Hello world"},
        ):
            resource = TextToSpeech()
            response = resource.post()
            payload = _get_response_json(response)
            assert _get_response_status(response) == 200
            assert payload["success"] is True
            assert payload["audio_base64"] == "base64audio=="
            assert payload["lang"] == "en"

    @patch("application.api.user.attachments.routes.TTSCreator.create_tts")
    def test_tts_error_returns_400(self, mock_create_tts, flask_app, mock_mongo_db):
        from application.api.user.attachments.routes import TextToSpeech

        app = Flask(__name__)
        mock_tts = MagicMock()
        mock_tts.text_to_speech.side_effect = Exception("tts error")
        mock_create_tts.return_value = mock_tts

        with app.test_request_context(
            "/api/tts",
            method="POST",
            json={"text": "Hello world"},
        ):
            resource = TextToSpeech()
            response = resource.post()
            assert _get_response_status(response) == 400
            assert _get_response_json(response)["success"] is False


# =====================================================================
# Coverage gap tests  (lines 136, 256, 330, 337, 443, 457, 560, 590)
# =====================================================================


@pytest.mark.unit
class TestAttachmentRoutesGaps:
    """Cover remaining uncovered lines in attachments/routes.py."""

    def test_parse_bool_form_value_true(self):
        """Cover helper function."""
        from application.api.user.attachments.routes import _parse_bool_form_value

        assert _parse_bool_form_value("true") is True
        assert _parse_bool_form_value("1") is True
        assert _parse_bool_form_value("yes") is True
        assert _parse_bool_form_value("on") is True
        assert _parse_bool_form_value("false") is False
        assert _parse_bool_form_value(None) is False

    def test_stt_auth_status_code_passthrough(self):
        """Cover line 256: auth_user with status_code is returned directly."""
        from application.api.user.attachments.routes import SpeechToText

        app = Flask(__name__)
        with app.test_request_context(
            "/api/stt",
            method="POST",
            content_type="multipart/form-data",
        ):
            from flask import request as flask_request

            flask_request.decoded_token = None

            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user"
            ) as mock_auth:
                error_resp = MagicMock()
                error_resp.status_code = 401
                mock_auth.return_value = error_resp
                resource = SpeechToText()
                response = resource.post()
                assert response.status_code == 401

    def test_live_start_no_auth(self):
        """Cover line 330: live/start returns 401 when no auth."""
        from application.api.user.attachments.routes import LiveSpeechToTextStart

        app = Flask(__name__)
        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={},
        ):
            from flask import request as flask_request

            flask_request.decoded_token = None

            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value=None,
            ):
                resource = LiveSpeechToTextStart()
                response = resource.post()
                assert _get_response_status(response) == 401

    def test_live_start_redis_unavailable(self):
        """Cover line 337: redis_client with status_code returned."""
        from application.api.user.attachments.routes import LiveSpeechToTextStart

        app = Flask(__name__)
        with app.test_request_context(
            "/api/stt/live/start",
            method="POST",
            json={},
        ):
            from flask import request as flask_request

            flask_request.decoded_token = {"sub": "user1"}

            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value="user1",
            ):
                with patch(
                    "application.api.user.attachments.routes._require_live_stt_redis"
                ) as mock_redis:
                    error_resp = MagicMock()
                    error_resp.status_code = 503
                    mock_redis.return_value = error_resp
                    resource = LiveSpeechToTextStart()
                    response = resource.post()
                    assert response.status_code == 503

    def test_live_chunk_missing_file(self):
        """Cover line 443: missing file in chunk returns 400."""
        from application.api.user.attachments.routes import LiveSpeechToTextChunk

        app = Flask(__name__)
        fake_redis = FakeRedis()

        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": "sess123",
                "chunk_index": "0",
            },
            content_type="multipart/form-data",
        ):
            from flask import request as flask_request

            flask_request.decoded_token = {"sub": "user1"}

            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value="user1",
            ):
                with patch(
                    "application.api.user.attachments.routes._require_live_stt_redis",
                    return_value=fake_redis,
                ):
                    with patch(
                        "application.api.user.attachments.routes.load_live_stt_session",
                        return_value={"session_id": "sess123", "user": "user1"},
                    ):
                        with patch(
                            "application.api.user.attachments.routes.safe_filename",
                            side_effect=lambda x: x,
                        ):
                            resource = LiveSpeechToTextChunk()
                            response = resource.post()
                            assert _get_response_status(response) == 400

    def test_live_chunk_unsupported_mimetype(self):
        """Cover line 457: unsupported MIME type returns 400."""
        from application.api.user.attachments.routes import LiveSpeechToTextChunk

        app = Flask(__name__)
        fake_redis = FakeRedis()
        fake_file = MagicMock()
        fake_file.filename = "chunk.wav"
        fake_file.mimetype = "application/pdf"

        with app.test_request_context(
            "/api/stt/live/chunk",
            method="POST",
            data={
                "session_id": "sess123",
                "chunk_index": "0",
            },
            content_type="multipart/form-data",
        ):
            from flask import request as flask_request

            flask_request.decoded_token = {"sub": "user1"}
            flask_request.files = MagicMock()
            flask_request.files.get.return_value = fake_file

            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value="user1",
            ):
                with patch(
                    "application.api.user.attachments.routes._require_live_stt_redis",
                    return_value=fake_redis,
                ):
                    with patch(
                        "application.api.user.attachments.routes.load_live_stt_session",
                        return_value={"session_id": "sess123", "user": "user1"},
                    ):
                        with patch(
                            "application.api.user.attachments.routes.safe_filename",
                            side_effect=lambda x: x,
                        ):
                            resource = LiveSpeechToTextChunk()
                            response = resource.post()
                            # Should fail on MIME type check
                            status = _get_response_status(response)
                            assert status == 400

    def test_live_finish_no_auth(self):
        """Cover line 560: finish returns 401 when no auth."""
        from application.api.user.attachments.routes import LiveSpeechToTextFinish

        app = Flask(__name__)
        with app.test_request_context(
            "/api/stt/live/finish",
            method="POST",
            json={"session_id": "sess123"},
        ):
            from flask import request as flask_request

            flask_request.decoded_token = None
            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value=None,
            ):
                resource = LiveSpeechToTextFinish()
                response = resource.post()
                assert _get_response_status(response) == 401

    def test_live_finish_forbidden(self):
        """Cover line 590: finish returns 403 when user mismatch."""
        from application.api.user.attachments.routes import LiveSpeechToTextFinish

        app = Flask(__name__)
        fake_redis = FakeRedis()

        with app.test_request_context(
            "/api/stt/live/finish",
            method="POST",
            json={"session_id": "sess123"},
        ):
            from flask import request as flask_request

            flask_request.decoded_token = {"sub": "user1"}
            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value="user1",
            ):
                with patch(
                    "application.api.user.attachments.routes._require_live_stt_redis",
                    return_value=fake_redis,
                ):
                    with patch(
                        "application.api.user.attachments.routes.load_live_stt_session",
                        return_value={
                            "session_id": "sess123",
                            "user": "different_user",
                        },
                    ):
                        with patch(
                            "application.api.user.attachments.routes.safe_filename",
                            side_effect=lambda x: x,
                        ):
                            resource = LiveSpeechToTextFinish()
                            response = resource.post()
                            assert _get_response_status(response) == 403


# ---------------------------------------------------------------------------
# Coverage — additional uncovered lines: 136, 256, 330, 443, 457, 560, 590
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAttachmentsCoverageLines:

    def test_store_attachment_single_file_fallback(self):
        """Cover line 136: single file fallback when getlist returns empty."""
        from application.api.user.attachments.routes import StoreAttachment

        app = Flask(__name__)

        with app.test_request_context(
            "/api/attachments/store",
            method="POST",
            content_type="multipart/form-data",
        ):
            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value="user1",
            ):
                resource = StoreAttachment()
                response = resource.post()
                status = _get_response_status(response)
                assert status == 400

    def test_speech_to_text_auth_required(self):
        """Cover line 256: STT requires authentication."""
        from application.api.user.attachments.routes import SpeechToText

        app = Flask(__name__)

        with app.test_request_context(
            "/api/attachments/stt",
            method="POST",
        ):
            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value=None,
            ):
                resource = SpeechToText()
                response = resource.post()
                status = _get_response_status(response)
                assert status == 401

    def test_live_stt_start_auth_required(self):
        """Cover line 330: live STT start requires auth."""
        from application.api.user.attachments.routes import LiveSpeechToTextStart

        app = Flask(__name__)

        with app.test_request_context(
            "/api/attachments/stt/live/start",
            method="POST",
        ):
            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value=None,
            ):
                resource = LiveSpeechToTextStart()
                response = resource.post()
                status = _get_response_status(response)
                assert status == 401

    def test_live_stt_chunk_missing_file(self):
        """Cover line 443: missing file in chunk upload."""
        from application.api.user.attachments.routes import LiveSpeechToTextChunk

        app = Flask(__name__)
        fake_redis = FakeRedis()

        with app.test_request_context(
            "/api/attachments/stt/live/chunk",
            method="POST",
            content_type="multipart/form-data",
            data={"session_id": "sess1", "chunk_index": "0"},
        ):
            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value="user1",
            ):
                with patch(
                    "application.api.user.attachments.routes._require_live_stt_redis",
                    return_value=fake_redis,
                ):
                    with patch(
                        "application.api.user.attachments.routes.load_live_stt_session",
                        return_value={"session_id": "sess1", "user": "user1"},
                    ):
                        with patch(
                            "application.api.user.attachments.routes.safe_filename",
                            side_effect=lambda x: x,
                        ):
                            resource = LiveSpeechToTextChunk()
                            response = resource.post()
                            status = _get_response_status(response)
                            assert status == 400

    def test_live_stt_chunk_unsupported_mime(self):
        """Cover line 457: unsupported audio MIME type."""
        from application.api.user.attachments.routes import LiveSpeechToTextChunk

        app = Flask(__name__)
        fake_redis = FakeRedis()

        fake_file = MagicMock()
        fake_file.filename = "test.wav"
        fake_file.mimetype = "video/mp4"
        fake_file.read.return_value = b"data"

        with app.test_request_context(
            "/api/attachments/stt/live/chunk",
            method="POST",
            content_type="multipart/form-data",
            data={"session_id": "sess1", "chunk_index": "0"},
        ):
            from flask import request

            request.files = {"file": fake_file}
            request.form = {"session_id": "sess1", "chunk_index": "0"}

            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value="user1",
            ):
                with patch(
                    "application.api.user.attachments.routes._require_live_stt_redis",
                    return_value=fake_redis,
                ):
                    with patch(
                        "application.api.user.attachments.routes.load_live_stt_session",
                        return_value={"session_id": "sess1", "user": "user1"},
                    ):
                        with patch(
                            "application.api.user.attachments.routes.safe_filename",
                            side_effect=lambda x: x,
                        ):
                            with patch(
                                "application.api.user.attachments.routes._is_supported_audio_mimetype",
                                return_value=False,
                            ):
                                resource = LiveSpeechToTextChunk()
                                response = resource.post()
                                status = _get_response_status(response)
                                assert status == 400

    def test_live_stt_finish_auth_required(self):
        """Cover line 560: live STT finish requires auth."""
        from application.api.user.attachments.routes import LiveSpeechToTextFinish

        app = Flask(__name__)

        with app.test_request_context(
            "/api/attachments/stt/live/finish",
            method="POST",
        ):
            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value=None,
            ):
                resource = LiveSpeechToTextFinish()
                response = resource.post()
                status = _get_response_status(response)
                assert status == 401

    def test_live_stt_finish_forbidden(self):
        """Cover line 590: finish session with wrong user returns 403."""
        from application.api.user.attachments.routes import LiveSpeechToTextFinish

        app = Flask(__name__)
        fake_redis = FakeRedis()

        with app.test_request_context(
            "/api/attachments/stt/live/finish",
            method="POST",
            json={"session_id": "sess1"},
        ):
            with patch(
                "application.api.user.attachments.routes._resolve_authenticated_user",
                return_value="user1",
            ):
                with patch(
                    "application.api.user.attachments.routes._require_live_stt_redis",
                    return_value=fake_redis,
                ):
                    with patch(
                        "application.api.user.attachments.routes.load_live_stt_session",
                        return_value={
                            "session_id": "sess1",
                            "user": "different_user",
                        },
                    ):
                        with patch(
                            "application.api.user.attachments.routes.safe_filename",
                            side_effect=lambda x: x,
                        ):
                            resource = LiveSpeechToTextFinish()
                            response = resource.post()
                            status = _get_response_status(response)
                            assert status == 403


# ---------------------------------------------------------------------------
# Additional coverage for attachments/routes.py
# Lines: 60 (return None), 70-71 (get_uploaded_file_size exception),
# 91 (AudioFileTooLargeError message), 99-102 (redis unavailable),
# 92 (generic error message), 76 (normalized mimetype)
# ---------------------------------------------------------------------------


class TestResolveAuthenticatedUserReturnsNone:
    """Cover line 60: _resolve_authenticated_user returns None."""

    @pytest.mark.unit
    def test_returns_none_when_no_auth(self):
        from application.api.user.attachments.routes import _resolve_authenticated_user

        app = Flask(__name__)
        with app.test_request_context(
            "/api/store_attachment",
            method="POST",
        ):
            with patch(
                "application.api.user.attachments.routes.safe_filename",
                side_effect=lambda x: x,
            ):
                # No decoded_token, no api_key
                from flask import request

                request.decoded_token = None
                result = _resolve_authenticated_user()
                assert result is None


class TestGetUploadedFileSizeException:
    """Cover lines 70-71: _get_uploaded_file_size returns 0 on error."""

    @pytest.mark.unit
    def test_returns_zero_on_exception(self):
        from application.api.user.attachments.routes import _get_uploaded_file_size

        broken_file = MagicMock()
        broken_file.stream.tell.side_effect = RuntimeError("broken")
        result = _get_uploaded_file_size(broken_file)
        assert result == 0


class TestGetStoreAttachmentUserError:
    """Cover lines 91-92: error message helper."""

    @pytest.mark.unit
    def test_audio_too_large_error(self):
        from application.api.user.attachments.routes import (
            _get_store_attachment_user_error,
        )
        from application.stt.upload_limits import AudioFileTooLargeError

        err = AudioFileTooLargeError("too big")
        msg = _get_store_attachment_user_error(err)
        assert isinstance(msg, str)
        assert len(msg) > 0

    @pytest.mark.unit
    def test_generic_error(self):
        from application.api.user.attachments.routes import (
            _get_store_attachment_user_error,
        )

        msg = _get_store_attachment_user_error(RuntimeError("oops"))
        assert msg == "Failed to process file"


class TestRequireLiveSttRedisUnavailable:
    """Cover lines 99-102: Redis unavailable returns 503."""

    @pytest.mark.unit
    def test_redis_unavailable(self):
        from application.api.user.attachments.routes import _require_live_stt_redis

        app = Flask(__name__)
        with app.app_context():
            with patch(
                "application.api.user.attachments.routes.get_redis_instance",
                return_value=None,
            ):
                result = _require_live_stt_redis()
                assert hasattr(result, "status_code")
                assert result.status_code == 503
