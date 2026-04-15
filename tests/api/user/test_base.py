import datetime
import io
from unittest.mock import Mock, patch

import pytest
from werkzeug.datastructures import FileStorage


@pytest.mark.unit
class TestTimeRangeGenerators:
    pass

    def test_generate_minute_range(self):
        from application.api.user.base import generate_minute_range

        start = datetime.datetime(2024, 1, 1, 10, 0, 0)
        end = datetime.datetime(2024, 1, 1, 10, 5, 0)

        result = generate_minute_range(start, end)

        assert len(result) == 6
        assert "2024-01-01 10:00:00" in result
        assert "2024-01-01 10:05:00" in result
        assert all(val == 0 for val in result.values())

    def test_generate_hourly_range(self):
        from application.api.user.base import generate_hourly_range

        start = datetime.datetime(2024, 1, 1, 10, 0, 0)
        end = datetime.datetime(2024, 1, 1, 15, 0, 0)

        result = generate_hourly_range(start, end)

        assert len(result) == 6
        assert "2024-01-01 10:00" in result
        assert "2024-01-01 15:00" in result
        assert all(val == 0 for val in result.values())

    def test_generate_date_range(self):
        from application.api.user.base import generate_date_range

        start = datetime.date(2024, 1, 1)
        end = datetime.date(2024, 1, 5)

        result = generate_date_range(start, end)

        assert len(result) == 5
        assert "2024-01-01" in result
        assert "2024-01-05" in result
        assert all(val == 0 for val in result.values())

    def test_single_minute_range(self):
        from application.api.user.base import generate_minute_range

        time = datetime.datetime(2024, 1, 1, 10, 30, 0)
        result = generate_minute_range(time, time)

        assert len(result) == 1
        assert "2024-01-01 10:30:00" in result


@pytest.mark.unit
class TestEnsureUserDoc:
    pass

@pytest.mark.unit
class TestResolveToolDetails:
    pass

    def test_empty_tool_ids_list(self, mock_mongo_db):
        from application.api.user.base import resolve_tool_details

        result = resolve_tool_details([])

        assert result == []


@pytest.mark.unit
class TestGetVectorStore:
    pass

    @patch("application.api.user.base.VectorCreator.create_vectorstore")
    def test_creates_vector_store(self, mock_create):
        from application.api.user.base import get_vector_store

        mock_store = Mock()
        mock_create.return_value = mock_store
        source_id = "test_source_123"

        result = get_vector_store(source_id)

        assert result == mock_store
        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        assert kwargs.get("source_id") == source_id


@pytest.mark.unit
class TestHandleImageUpload:
    pass

    def test_returns_existing_url_when_no_file(self, flask_app):
        from application.api.user.base import handle_image_upload

        with flask_app.test_request_context():
            mock_request = Mock()
            mock_request.files = {}
            mock_storage = Mock()
            existing_url = "existing/path/image.jpg"

            url, error = handle_image_upload(
                mock_request, existing_url, "user123", mock_storage
            )

            assert url == existing_url
            assert error is None

    def test_uploads_new_image(self, flask_app):
        from application.api.user.base import handle_image_upload

        with flask_app.test_request_context():
            mock_file = FileStorage(
                stream=io.BytesIO(b"fake image data"), filename="test_image.png"
            )
            mock_request = Mock()
            mock_request.files = {"image": mock_file}
            mock_storage = Mock()
            mock_storage.save_file.return_value = {"success": True}

            url, error = handle_image_upload(
                mock_request, "old_url", "user123", mock_storage
            )

            assert error is None
            assert url is not None
            assert "test_image.png" in url
            assert "user123" in url
            mock_storage.save_file.assert_called_once()

    def test_ignores_empty_filename(self, flask_app):
        from application.api.user.base import handle_image_upload

        with flask_app.test_request_context():
            mock_file = Mock()
            mock_file.filename = ""
            mock_request = Mock()
            mock_request.files = {"image": mock_file}
            mock_storage = Mock()
            existing_url = "existing.jpg"

            url, error = handle_image_upload(
                mock_request, existing_url, "user123", mock_storage
            )

            assert url == existing_url
            assert error is None
            mock_storage.save_file.assert_not_called()

    def test_handles_upload_error(self, flask_app):
        from application.api.user.base import handle_image_upload

        with flask_app.app_context():
            mock_file = FileStorage(stream=io.BytesIO(b"data"), filename="test.png")
            mock_request = Mock()
            mock_request.files = {"image": mock_file}
            mock_storage = Mock()
            mock_storage.save_file.side_effect = Exception("Storage error")

            url, error = handle_image_upload(
                mock_request, "old.jpg", "user123", mock_storage
            )

            assert url is None
            assert error is not None
            assert error.status_code == 400


@pytest.mark.unit
class TestRequireAgentDecorator:
    pass

    def test_returns_400_for_missing_token(self, flask_app):
        from application.api.user.base import require_agent

        with flask_app.app_context():

            @require_agent
            def test_func(webhook_token=None, agent=None, agent_id_str=None):
                return {"success": True}

            result = test_func()

            assert result.status_code == 400
            assert result.json["success"] is False
            assert "missing" in result.json["message"].lower()

