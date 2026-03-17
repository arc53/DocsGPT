import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask, request
from application.parser.file.constants import SUPPORTED_SOURCE_EXTENSIONS


def test_upload_route_passes_audio_extensions_to_ingest(flask_app, mock_mongo_db):
    from application.api.user.sources.upload import UploadFile

    app = Flask(__name__)
    mock_storage = MagicMock()
    mock_task = SimpleNamespace(id="task-123")

    with app.test_request_context(
        "/api/upload",
        method="POST",
        data={
            "user": "test_user",
            "name": "Meeting Notes",
            "file": (io.BytesIO(b"audio-bytes"), "meeting.wav"),
        },
        content_type="multipart/form-data",
    ):
        request.decoded_token = {"sub": "test_user"}

        with patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.sources.upload.ingest.delay",
            return_value=mock_task,
        ) as mock_delay:
            resource = UploadFile()
            response = resource.post()

            assert response.status_code == 200
            assert response.json["success"] is True

            formats = mock_delay.call_args.args[1]
            assert formats == list(SUPPORTED_SOURCE_EXTENSIONS)


@patch("application.stt.upload_limits.settings")
def test_upload_route_rejects_oversized_audio(
    mock_limit_settings, flask_app, mock_mongo_db
):
    from application.api.user.sources.upload import UploadFile

    app = Flask(__name__)
    mock_limit_settings.STT_MAX_FILE_SIZE_MB = 1

    with app.test_request_context(
        "/api/upload",
        method="POST",
        data={
            "user": "test_user",
            "name": "Meeting Notes",
            "file": (io.BytesIO(b"x" * (2 * 1024 * 1024)), "meeting.wav"),
        },
        content_type="multipart/form-data",
    ):
        request.decoded_token = {"sub": "test_user"}

        with patch("application.api.user.sources.upload.StorageCreator.get_storage"):
            resource = UploadFile()
            response = resource.post()

            assert response.status_code == 413
            assert "exceeds" in response.json["message"]
