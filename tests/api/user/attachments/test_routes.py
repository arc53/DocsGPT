import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask, request


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
