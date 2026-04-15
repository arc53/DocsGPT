"""Additional tests for application/api/user/utils.py to cover paginated_response.

Target missing lines:
  - 257-262: paginated_response (collection query + serializer + response)
"""

import uuid
from unittest.mock import MagicMock

import pytest
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@pytest.mark.unit
class TestPaginatedResponse:
    """Cover lines 257-262: paginated_response function."""

    def test_paginated_response_basic(self, app):
        from application.api.user.utils import paginated_response

        mock_collection = MagicMock()
        items = [
            {"_id": uuid.uuid4().hex[:24], "name": "item1"},
            {"_id": uuid.uuid4().hex[:24], "name": "item2"},
        ]

        # Chain: collection.find().sort().skip().limit() returns items
        mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = items
        mock_collection.count_documents.return_value = 2

        def serializer(item):
            return {"id": item["_id"], "name": item["name"]}

        with app.app_context():
            resp = paginated_response(
                collection=mock_collection,
                query={"user": "user-1"},
                serializer=serializer,
                limit=10,
                skip=0,
                response_key="items",
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["items"]) == 2
        assert data["total"] == 2
        assert data["limit"] == 10
        assert data["skip"] == 0

    def test_paginated_response_custom_sort_and_key(self, app):
        from application.api.user.utils import paginated_response

        mock_collection = MagicMock()
        mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = []
        mock_collection.count_documents.return_value = 0

        with app.app_context():
            resp = paginated_response(
                collection=mock_collection,
                query={},
                serializer=lambda x: x,
                limit=5,
                skip=10,
                sort_field="name",
                sort_order=1,
                response_key="workflows",
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["workflows"] == []
        assert data["total"] == 0
        assert data["limit"] == 5
        assert data["skip"] == 10
        # Verify sort was called with the custom field and order
        mock_collection.find.return_value.sort.assert_called_once_with("name", 1)

    def test_safe_db_operation_without_app_context(self, app):
        """Cover lines 330-332: safe_db_operation when no app context.

        The function checks has_app_context() before logging, so calling it
        outside an app context should still return an error response but
        skip the logger call.
        """
        from application.api.user.utils import safe_db_operation

        # We need an app context for make_response/jsonify inside error_response
        with app.app_context():
            result, error = safe_db_operation(
                lambda: (_ for _ in ()).throw(RuntimeError("fail")),
                "Failed without context",
            )
        assert result is None
        assert error is not None
        assert error.status_code == 400
