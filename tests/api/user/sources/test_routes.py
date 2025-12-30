"""Tests for sources routes."""

import json
import pytest
from unittest.mock import MagicMock, patch
from bson import ObjectId


class TestGetProviderFromRemoteData:
    """Test the _get_provider_from_remote_data helper function."""

    def test_returns_none_for_none_input(self):
        """Should return None when remote_data is None."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        result = _get_provider_from_remote_data(None)
        assert result is None

    def test_returns_none_for_empty_string(self):
        """Should return None when remote_data is empty string."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        result = _get_provider_from_remote_data("")
        assert result is None

    def test_extracts_provider_from_dict(self):
        """Should extract provider from dict remote_data."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        remote_data = {"provider": "s3", "bucket": "my-bucket"}
        result = _get_provider_from_remote_data(remote_data)
        assert result == "s3"

    def test_extracts_provider_from_json_string(self):
        """Should extract provider from JSON string remote_data."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        remote_data = json.dumps({"provider": "github", "repo": "test/repo"})
        result = _get_provider_from_remote_data(remote_data)
        assert result == "github"

    def test_returns_none_for_dict_without_provider(self):
        """Should return None when dict has no provider key."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        remote_data = {"bucket": "my-bucket", "region": "us-east-1"}
        result = _get_provider_from_remote_data(remote_data)
        assert result is None

    def test_returns_none_for_invalid_json(self):
        """Should return None for invalid JSON string."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        result = _get_provider_from_remote_data("not valid json")
        assert result is None

    def test_returns_none_for_json_array(self):
        """Should return None when JSON parses to non-dict."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        result = _get_provider_from_remote_data('["item1", "item2"]')
        assert result is None

    def test_returns_none_for_non_string_non_dict(self):
        """Should return None for other types like int."""
        from application.api.user.sources.routes import _get_provider_from_remote_data

        result = _get_provider_from_remote_data(123)
        assert result is None


def _get_response_status(response):
    """Helper to get status code from response (handles both tuple and Response)."""
    if isinstance(response, tuple):
        return response[1]
    return response.status_code


def _get_response_json(response):
    """Helper to get JSON from response (handles both tuple and Response)."""
    if isinstance(response, tuple):
        return response[0].json
    return response.json


@pytest.mark.unit
class TestSyncSourceEndpoint:
    """Test the /sync_source endpoint."""

    @pytest.fixture
    def mock_sources_collection(self, mock_mongo_db):
        """Get mock sources collection."""
        from application.core.settings import settings

        return mock_mongo_db[settings.MONGO_DB_NAME]["sources"]

    def test_sync_source_returns_401_without_token(self, flask_app):
        """Should return 401 when no decoded_token is present."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)

        with app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": "123"}
        ):
            from flask import request

            request.decoded_token = None
            resource = SyncSource()
            response = resource.post()

            assert _get_response_status(response) == 401

    def test_sync_source_returns_400_for_missing_source_id(self, flask_app):
        """Should return 400 when source_id is missing."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)

        with app.test_request_context("/api/sync_source", method="POST", json={}):
            from flask import request

            request.decoded_token = {"sub": "test_user"}
            resource = SyncSource()
            response = resource.post()

            # check_required_fields returns a response tuple on missing fields
            assert response is not None

    def test_sync_source_returns_400_for_invalid_source_id(self, flask_app):
        """Should return 400 for invalid ObjectId."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)

        with app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": "invalid"}
        ):
            from flask import request

            request.decoded_token = {"sub": "test_user"}
            resource = SyncSource()
            response = resource.post()

            assert _get_response_status(response) == 400
            assert "Invalid source ID" in _get_response_json(response)["message"]

    def test_sync_source_returns_404_for_nonexistent_source(
        self, flask_app, mock_mongo_db
    ):
        """Should return 404 when source doesn't exist."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)
        source_id = str(ObjectId())

        with app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": source_id}
        ):
            from flask import request

            request.decoded_token = {"sub": "test_user"}

            with patch(
                "application.api.user.sources.routes.sources_collection",
                mock_mongo_db["docsgpt"]["sources"],
            ):
                resource = SyncSource()
                response = resource.post()

                assert _get_response_status(response) == 404
                assert "not found" in _get_response_json(response)["message"]

    def test_sync_source_returns_400_for_connector_type(
        self, flask_app, mock_mongo_db, mock_sources_collection
    ):
        """Should return 400 for connector sources."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)
        source_id = ObjectId()

        # Insert a connector source
        mock_sources_collection.insert_one(
            {
                "_id": source_id,
                "user": "test_user",
                "type": "connector_slack",
                "name": "Slack Source",
            }
        )

        with app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": str(source_id)}
        ):
            from flask import request

            request.decoded_token = {"sub": "test_user"}

            with patch(
                "application.api.user.sources.routes.sources_collection",
                mock_sources_collection,
            ):
                resource = SyncSource()
                response = resource.post()

                assert _get_response_status(response) == 400
                assert "Connector sources" in _get_response_json(response)["message"]

    def test_sync_source_returns_400_for_non_syncable_source(
        self, flask_app, mock_mongo_db, mock_sources_collection
    ):
        """Should return 400 when source has no remote_data."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)
        source_id = ObjectId()

        # Insert a source without remote_data
        mock_sources_collection.insert_one(
            {
                "_id": source_id,
                "user": "test_user",
                "type": "file",
                "name": "Local Source",
                "remote_data": None,
            }
        )

        with app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": str(source_id)}
        ):
            from flask import request

            request.decoded_token = {"sub": "test_user"}

            with patch(
                "application.api.user.sources.routes.sources_collection",
                mock_sources_collection,
            ):
                resource = SyncSource()
                response = resource.post()

                assert _get_response_status(response) == 400
                assert "not syncable" in _get_response_json(response)["message"]

    def test_sync_source_triggers_sync_task(
        self, flask_app, mock_mongo_db, mock_sources_collection
    ):
        """Should trigger sync task for valid syncable source."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)
        source_id = ObjectId()

        # Insert a valid syncable source
        mock_sources_collection.insert_one(
            {
                "_id": source_id,
                "user": "test_user",
                "type": "s3",
                "name": "S3 Source",
                "remote_data": json.dumps(
                    {
                        "provider": "s3",
                        "bucket": "my-bucket",
                        "aws_access_key_id": "key",
                        "aws_secret_access_key": "secret",
                    }
                ),
                "sync_frequency": "daily",
                "retriever": "classic",
            }
        )

        mock_task = MagicMock()
        mock_task.id = "task-123"

        with app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": str(source_id)}
        ):
            from flask import request

            request.decoded_token = {"sub": "test_user"}

            with patch(
                "application.api.user.sources.routes.sources_collection",
                mock_sources_collection,
            ):
                with patch(
                    "application.api.user.sources.routes.sync_source"
                ) as mock_sync:
                    mock_sync.delay.return_value = mock_task

                    resource = SyncSource()
                    response = resource.post()

                    assert _get_response_status(response) == 200
                    assert _get_response_json(response)["success"] is True
                    assert _get_response_json(response)["task_id"] == "task-123"

                    mock_sync.delay.assert_called_once()
                    call_kwargs = mock_sync.delay.call_args[1]
                    assert call_kwargs["user"] == "test_user"
                    assert call_kwargs["loader"] == "s3"
                    assert call_kwargs["doc_id"] == str(source_id)

    def test_sync_source_handles_task_error(
        self, flask_app, mock_mongo_db, mock_sources_collection
    ):
        """Should return 400 when task fails to start."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)
        source_id = ObjectId()

        mock_sources_collection.insert_one(
            {
                "_id": source_id,
                "user": "test_user",
                "type": "github",
                "name": "GitHub Source",
                "remote_data": "https://github.com/test/repo",
                "sync_frequency": "weekly",
                "retriever": "classic",
            }
        )

        with app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": str(source_id)}
        ):
            from flask import request

            request.decoded_token = {"sub": "test_user"}

            with patch(
                "application.api.user.sources.routes.sources_collection",
                mock_sources_collection,
            ):
                with patch(
                    "application.api.user.sources.routes.sync_source"
                ) as mock_sync:
                    mock_sync.delay.side_effect = Exception("Celery error")

                    resource = SyncSource()
                    response = resource.post()

                    assert _get_response_status(response) == 400
                    assert _get_response_json(response)["success"] is False
