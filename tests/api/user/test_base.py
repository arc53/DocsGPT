import datetime
import io
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest
from werkzeug.datastructures import FileStorage


@contextmanager
def _patch_base_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.base.db_session", _yield
    ), patch(
        "application.api.user.base.db_readonly", _yield
    ):
        yield


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


# ---------------------------------------------------------------------------
# Real PG tests: ensure_user_doc, resolve_tool_details, require_agent
# ---------------------------------------------------------------------------


class TestEnsureUserDocPgConn:
    def test_creates_new_user_doc(self, pg_conn):
        from application.api.user.base import ensure_user_doc

        with _patch_base_db(pg_conn):
            doc = ensure_user_doc("brand-new-user")
        assert doc["user_id"] == "brand-new-user"
        prefs = doc["agent_preferences"]
        assert prefs.get("pinned") == []
        assert prefs.get("shared_with_me") == []

    def test_preserves_existing_prefs(self, pg_conn):
        from application.api.user.base import ensure_user_doc
        from application.storage.db.repositories.users import UsersRepository

        user = "existing-user"
        UsersRepository(pg_conn).upsert(user)
        UsersRepository(pg_conn).add_pinned(user, "agent-abc")

        with _patch_base_db(pg_conn):
            doc = ensure_user_doc(user)
        assert "agent-abc" in doc["agent_preferences"]["pinned"]
        assert doc["agent_preferences"]["shared_with_me"] == []


class TestResolveToolDetailsPgConn:
    def test_empty_list_returns_empty(self, pg_conn):
        from application.api.user.base import resolve_tool_details
        with _patch_base_db(pg_conn):
            assert resolve_tool_details([]) == []

    def test_none_entries_filtered_out(self, pg_conn):
        from application.api.user.base import resolve_tool_details
        with _patch_base_db(pg_conn):
            assert resolve_tool_details([None, ""]) == []

    def test_resolves_known_uuid_ids(self, pg_conn):
        from application.api.user.base import resolve_tool_details
        from application.storage.db.repositories.user_tools import (
            UserToolsRepository,
        )

        tool = UserToolsRepository(pg_conn).create(
            "u", "my_tool", display_name="My Tool",
            custom_name="Custom",
            description="x",
        )
        with _patch_base_db(pg_conn):
            got = resolve_tool_details([str(tool["id"])])
        assert len(got) == 1
        assert got[0]["name"] == "my_tool"
        assert got[0]["display_name"] == "Custom"

    def test_unknown_ids_skipped(self, pg_conn):
        from application.api.user.base import resolve_tool_details
        with _patch_base_db(pg_conn):
            got = resolve_tool_details(
                ["00000000-0000-0000-0000-000000000000"]
            )
        assert got == []

    def test_legacy_ids_lookup(self, pg_conn):
        from application.api.user.base import resolve_tool_details
        from application.storage.db.repositories.user_tools import (
            UserToolsRepository,
        )

        tool = UserToolsRepository(pg_conn).create(
            "u", "legacy_tool",
            display_name="Legacy",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        _ = tool
        with _patch_base_db(pg_conn):
            got = resolve_tool_details(["507f1f77bcf86cd799439011"])
        assert len(got) == 1
        assert got[0]["name"] == "legacy_tool"


class TestRequireAgentPgConn:
    def test_returns_404_invalid_token(self, pg_conn, flask_app):
        from application.api.user.base import require_agent

        @require_agent
        def fn(webhook_token=None, agent=None, agent_id_str=None):
            return {"ok": True}

        with _patch_base_db(pg_conn), flask_app.app_context():
            result = fn(webhook_token="bogus")
        assert result.status_code == 404

    def test_injects_agent_when_valid(self, pg_conn, flask_app):
        from application.api.user.base import require_agent
        from application.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create(
            "owner", "wh-agent", "published",
            incoming_webhook_token="webhook-123",
        )

        @require_agent
        def fn(webhook_token=None, agent=None, agent_id_str=None):
            return {"got": agent_id_str}

        with _patch_base_db(pg_conn), flask_app.app_context():
            result = fn(webhook_token="webhook-123")
        assert result["got"] == str(agent["id"])

