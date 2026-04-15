"""Tests for sources routes.

All Mongo-coupled tests (patching ``sources_collection``, using ``mock_mongo_db``,
``ObjectId``) have been removed as part of the MongoDB->Postgres cutover. The
integration suite at ``tests/integration/test_sources.py`` now covers the
route-level behaviour that used to live here.

Only pure helper-function tests that don't touch any datastore remain below.
"""

import json
import uuid
import pytest
from unittest.mock import MagicMock, patch


def _make_oid():
    """Return a fresh 24-hex string suitable as a MongoDB-like _id."""
    return uuid.uuid4().hex[:24]


class _InMemoryCollection:
    """Minimal dict-backed collection for sources-routes tests."""

    def __init__(self):
        self._docs = []

    def _matches(self, doc, query):
        for k, v in query.items():
            if str(doc.get(k)) != str(v):
                return False
        return True

    def insert_one(self, doc):
        new_doc = dict(doc)
        if "_id" not in new_doc:
            new_doc["_id"] = _make_oid()
        self._docs.append(new_doc)
        result = MagicMock()
        result.inserted_id = new_doc["_id"]
        return result

    def find_one(self, query):
        import copy
        for doc in self._docs:
            if self._matches(doc, query):
                return copy.deepcopy(doc)
        return None

    def find(self, query=None):
        import copy
        if query is None:
            query = {}
        return [copy.deepcopy(d) for d in self._docs if self._matches(d, query)]

    def delete_one(self, query):
        for i, doc in enumerate(self._docs):
            if self._matches(doc, query):
                self._docs.pop(i)
                result = MagicMock()
                result.deleted_count = 1
                return result
        result = MagicMock()
        result.deleted_count = 0
        return result

    def update_one(self, query, update, upsert=False):
        result = MagicMock()
        result.modified_count = 0
        for doc in self._docs:
            if self._matches(doc, query):
                if "$set" in update:
                    doc.update(update["$set"])
                result.modified_count = 1
                return result
        if upsert:
            new_doc = dict(query)
            if "$set" in update:
                new_doc.update(update["$set"])
            self._docs.append(new_doc)
        return result


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


@pytest.mark.unit
class TestSyncSourceEndpoint:
    """Test the /sync_source endpoint."""

    @pytest.fixture
    def sources_col(self):
        """Provide an in-memory sources collection."""
        return _InMemoryCollection()

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
        self, flask_app, sources_col
    ):
        """Should return 404 when source doesn't exist."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)
        source_id = _make_oid()

        with app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": source_id}
        ):
            from flask import request

            request.decoded_token = {"sub": "test_user"}

            with patch(
                "application.api.user.sources.routes.sources_collection",
                sources_col,
            ):
                resource = SyncSource()
                response = resource.post()

                assert _get_response_status(response) == 404
                assert "not found" in _get_response_json(response)["message"]

    def test_sync_source_returns_400_for_connector_type(
        self, flask_app, sources_col
    ):
        """Should return 400 for connector sources."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)
        source_id = _make_oid()

        # Insert a connector source
        sources_col.insert_one(
            {
                "_id": source_id,
                "user": "test_user",
                "type": "connector_slack",
                "name": "Slack Source",
            }
        )

        with app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": source_id}
        ):
            from flask import request

            request.decoded_token = {"sub": "test_user"}

            with patch(
                "application.api.user.sources.routes.sources_collection",
                sources_col,
            ):
                resource = SyncSource()
                response = resource.post()

                assert _get_response_status(response) == 400
                assert "Connector sources" in _get_response_json(response)["message"]

    def test_sync_source_returns_400_for_non_syncable_source(
        self, flask_app, sources_col
    ):
        """Should return 400 when source has no remote_data."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)
        source_id = _make_oid()

        # Insert a source without remote_data
        sources_col.insert_one(
            {
                "_id": source_id,
                "user": "test_user",
                "type": "file",
                "name": "Local Source",
                "remote_data": None,
            }
        )

        with app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": source_id}
        ):
            from flask import request

            request.decoded_token = {"sub": "test_user"}

            with patch(
                "application.api.user.sources.routes.sources_collection",
                sources_col,
            ):
                resource = SyncSource()
                response = resource.post()

                assert _get_response_status(response) == 400
                assert "not syncable" in _get_response_json(response)["message"]

    def test_sync_source_triggers_sync_task(
        self, flask_app, sources_col
    ):
        """Should trigger sync task for valid syncable source."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)
        source_id = _make_oid()

        # Insert a valid syncable source
        sources_col.insert_one(
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
            "/api/sync_source", method="POST", json={"source_id": source_id}
        ):
            from flask import request

            request.decoded_token = {"sub": "test_user"}

            with patch(
                "application.api.user.sources.routes.sources_collection",
                sources_col,
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
                    assert call_kwargs["doc_id"] == source_id

    def test_sync_source_handles_task_error(
        self, flask_app, sources_col
    ):
        """Should return 400 when task fails to start."""
        from flask import Flask
        from application.api.user.sources.routes import SyncSource

        app = Flask(__name__)
        source_id = _make_oid()

        sources_col.insert_one(
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
            "/api/sync_source", method="POST", json={"source_id": source_id}
        ):
            from flask import request

            request.decoded_token = {"sub": "test_user"}

            with patch(
                "application.api.user.sources.routes.sources_collection",
                sources_col,
            ):
                with patch(
                    "application.api.user.sources.routes.sync_source"
                ) as mock_sync:
                    mock_sync.delay.side_effect = Exception("Celery error")

                    resource = SyncSource()
                    response = resource.post()

                    assert _get_response_status(response) == 400
                    assert _get_response_json(response)["success"] is False
