import datetime
import io
from unittest.mock import Mock, patch

import pytest
from bson import ObjectId
from werkzeug.datastructures import FileStorage


@pytest.mark.unit
class TestTimeRangeGenerators:

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

    def test_creates_new_user_with_defaults(self, mock_mongo_db):
        from application.api.user.base import ensure_user_doc

        user_id = "test_user_123"

        result = ensure_user_doc(user_id)

        assert result is not None
        assert result["user_id"] == user_id
        assert "agent_preferences" in result
        assert result["agent_preferences"]["pinned"] == []
        assert result["agent_preferences"]["shared_with_me"] == []

    def test_returns_existing_user(self, mock_mongo_db):
        from application.api.user.base import ensure_user_doc
        from application.core.settings import settings

        users_collection = mock_mongo_db[settings.MONGO_DB_NAME]["users"]
        user_id = "existing_user"

        existing_doc = {
            "user_id": user_id,
            "agent_preferences": {"pinned": ["agent1"], "shared_with_me": ["agent2"]},
        }
        users_collection.insert_one(existing_doc)

        result = ensure_user_doc(user_id)

        assert result["user_id"] == user_id
        assert result["agent_preferences"]["pinned"] == ["agent1"]
        assert result["agent_preferences"]["shared_with_me"] == ["agent2"]

    def test_adds_missing_preferences_fields(self, mock_mongo_db):
        from application.api.user.base import ensure_user_doc
        from application.core.settings import settings

        users_collection = mock_mongo_db[settings.MONGO_DB_NAME]["users"]
        user_id = "incomplete_user"

        users_collection.insert_one(
            {"user_id": user_id, "agent_preferences": {"pinned": ["agent1"]}}
        )

        result = ensure_user_doc(user_id)

        assert "shared_with_me" in result["agent_preferences"]
        assert result["agent_preferences"]["shared_with_me"] == []


@pytest.mark.unit
class TestResolveToolDetails:

    def test_resolves_tool_ids_to_details(self, mock_mongo_db):
        from application.api.user.base import resolve_tool_details
        from application.core.settings import settings

        user_tools = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]
        tool_id1 = ObjectId()
        tool_id2 = ObjectId()

        user_tools.insert_one(
            {"_id": tool_id1, "name": "calculator", "displayName": "Calculator Tool"}
        )
        user_tools.insert_one(
            {"_id": tool_id2, "name": "weather", "displayName": "Weather API"}
        )

        result = resolve_tool_details([str(tool_id1), str(tool_id2)])

        assert len(result) == 2
        assert result[0]["id"] == str(tool_id1)
        assert result[0]["name"] == "calculator"
        assert result[0]["display_name"] == "Calculator Tool"
        assert result[1]["name"] == "weather"

    def test_handles_missing_display_name(self, mock_mongo_db):
        from application.api.user.base import resolve_tool_details
        from application.core.settings import settings

        user_tools = mock_mongo_db[settings.MONGO_DB_NAME]["user_tools"]
        tool_id = ObjectId()

        user_tools.insert_one({"_id": tool_id, "name": "test_tool"})

        result = resolve_tool_details([str(tool_id)])

        assert result[0]["display_name"] == "test_tool"

    def test_empty_tool_ids_list(self, mock_mongo_db):
        from application.api.user.base import resolve_tool_details

        result = resolve_tool_details([])

        assert result == []


@pytest.mark.unit
class TestGetVectorStore:

    @patch("application.api.user.base.VectorCreator.create_vectorstore")
    def test_creates_vector_store(self, mock_create, mock_mongo_db):
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

    def test_validates_webhook_token(self, mock_mongo_db, flask_app):
        from application.api.user.base import require_agent
        from application.core.settings import settings

        with flask_app.app_context():
            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agent_id = ObjectId()
            webhook_token = "valid_webhook_token_123"

            agents_collection.insert_one(
                {"_id": agent_id, "incoming_webhook_token": webhook_token}
            )

            @require_agent
            def test_func(webhook_token=None, agent=None, agent_id_str=None):
                return {"agent_id": agent_id_str}

            result = test_func(webhook_token=webhook_token)

            assert result["agent_id"] == str(agent_id)

    def test_returns_400_for_missing_token(self, mock_mongo_db, flask_app):
        from application.api.user.base import require_agent

        with flask_app.app_context():

            @require_agent
            def test_func(webhook_token=None, agent=None, agent_id_str=None):
                return {"success": True}

            result = test_func()

            assert result.status_code == 400
            assert result.json["success"] is False
            assert "missing" in result.json["message"].lower()

    def test_returns_404_for_invalid_token(self, mock_mongo_db, flask_app):
        from application.api.user.base import require_agent

        with flask_app.app_context():

            @require_agent
            def test_func(webhook_token=None, agent=None, agent_id_str=None):
                return {"success": True}

            result = test_func(webhook_token="invalid_token_999")

            assert result.status_code == 404
            assert result.json["success"] is False
            assert "not found" in result.json["message"].lower()
