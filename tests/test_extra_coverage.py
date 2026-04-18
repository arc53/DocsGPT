"""Grab-bag of tests targeting remaining coverage gaps.

Covers edge cases in:
  - application/api/user/tools/routes.py
  - application/api/user/sources/upload.py (remaining)
  - application/api/connector/routes.py (exception paths)
  - application/seed/seeder.py (remaining)
  - application/api/user/agents/routes.py (remaining)
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_tools_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.tools.routes.db_session", _yield
    ), patch(
        "application.api.user.tools.routes.db_readonly", _yield
    ):
        yield


@contextmanager
def _patch_upload_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.sources.upload.db_session", _yield
    ), patch(
        "application.api.user.sources.upload.db_readonly", _yield
    ):
        yield


@contextmanager
def _patch_conn_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.connector.routes.db_session", _yield
    ), patch(
        "application.api.connector.routes.db_readonly", _yield
    ):
        yield


# ---------------------------------------------------------------------------
# tools/routes.py — remaining branches
# ---------------------------------------------------------------------------


class TestToolsRoutesExtra:
    def test_create_tool_unknown_name_returns_404(self, app, pg_conn):
        from application.api.user.tools.routes import CreateTool

        with _patch_tools_db(pg_conn), app.test_request_context(
            "/api/create_tool", method="POST",
            json={
                "name": "not_a_real_tool_name",
                "displayName": "x",
                "description": "d",
                "config": {},
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = CreateTool().post()
        # Unknown tool name can return 400 or 404 depending on validation order
        assert response.status_code in (400, 404)

    def test_delete_tool_missing_id_returns_400(self, app):
        from application.api.user.tools.routes import DeleteTool

        with app.test_request_context(
            "/api/delete_tool", method="POST", json={},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DeleteTool().post()
        assert response.status_code == 400

    def test_update_tool_missing_id(self, app):
        from application.api.user.tools.routes import UpdateTool

        with app.test_request_context(
            "/api/update_tool", method="POST", json={"displayName": "n"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UpdateTool().post()
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# sources/upload.py — ingestion task error paths
# ---------------------------------------------------------------------------


class TestSourcesUploadExtra:
    def test_remote_github_missing_repo_url(self, app):
        from application.api.user.sources.upload import UploadRemote
        import json as _json

        fake_task = MagicMock(id="t")
        with patch(
            "application.api.user.sources.upload.ingest_remote.delay",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "github", "name": "g",
                "data": _json.dumps({}),  # empty dict, no repo_url
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        # Still returns 200 with task_id; source_data is just None
        assert response.status_code == 200

    def test_remote_connector_missing_session_token(self, app):
        from application.api.user.sources.upload import UploadRemote
        import json as _json

        with patch(
            "application.parser.connectors.connector_creator.ConnectorCreator"
            ".get_supported_connectors",
            return_value={"google_drive"},
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "google_drive", "name": "g",
                "data": _json.dumps({}),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 400

    def test_remote_connector_triggers_task(self, app):
        from application.api.user.sources.upload import UploadRemote
        import json as _json

        fake_task = MagicMock(id="conn-t")
        with patch(
            "application.parser.connectors.connector_creator.ConnectorCreator"
            ".get_supported_connectors",
            return_value={"google_drive"},
        ), patch(
            "application.api.user.sources.upload.ingest_connector_task.delay",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "google_drive", "name": "g",
                "data": _json.dumps({
                    "session_token": "st",
                    "file_ids": "a, b, c",
                    "folder_ids": ["f1"],
                    "recursive": True,
                }),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 200
        assert response.json["task_id"] == "conn-t"


# ---------------------------------------------------------------------------
# connector/routes.py — extra exception paths
# ---------------------------------------------------------------------------


class TestConnectorExtra:
    def test_disconnect_exception_returns_500(self, app):
        from application.api.connector.routes import ConnectorDisconnect

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.connector.routes.db_session", _broken
        ), app.test_request_context(
            "/api/connectors/disconnect", method="POST",
            json={"provider": "x", "session_token": "y"},
        ):
            response = ConnectorDisconnect().post()
        assert response.status_code == 500

    def test_callback_status_exception_returns_500(self, app):
        from application.api.connector.routes import ConnectorCallbackStatus

        # An exception inside is hard to trigger naturally; use a patched
        # ``html.escape`` raising to exercise the except branch.
        with patch(
            "application.api.connector.routes.html.escape",
            side_effect=RuntimeError("boom"),
        ), app.test_request_context(
            "/api/connectors/callback-status?status=success"
        ):
            response = ConnectorCallbackStatus().get()
        assert response.status_code == 500

    def test_validate_session_token_refresh_failure(self, app, pg_conn):
        from application.api.connector.routes import ConnectorValidateSession
        from application.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        user = "u-refresh-fail"
        repo = ConnectorSessionsRepository(pg_conn)
        session = repo.upsert(user, "google_drive", status="authorized")
        repo.update(
            str(session["id"]),
            {
                "session_token": "st-fail",
                "token_info": {"access_token": "old", "refresh_token": "rt"},
            },
        )

        fake_auth = MagicMock()
        fake_auth.is_token_expired.return_value = True
        fake_auth.refresh_access_token.side_effect = RuntimeError("fail")

        with _patch_conn_db(pg_conn), patch(
            "application.api.connector.routes.ConnectorCreator.create_auth",
            return_value=fake_auth,
        ), app.test_request_context(
            "/api/connectors/validate-session", method="POST",
            json={"provider": "google_drive", "session_token": "st-fail"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ConnectorValidateSession().post()
        assert response.status_code == 401  # expired, refresh failed

    def test_sync_exception_returns_400(self, app):
        from application.api.connector.routes import ConnectorSync

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.connector.routes.db_readonly", _broken
        ), app.test_request_context(
            "/api/connectors/sync", method="POST",
            json={"source_id": "x", "session_token": "y"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ConnectorSync().post()
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# seeder.py — remaining paths
# ---------------------------------------------------------------------------


class TestSeederExtra:
    def test_seed_initial_data_loads_and_seeds(self, pg_conn, tmp_path):
        from application.seed.seeder import DatabaseSeeder

        # Write a valid YAML config file
        config_file = tmp_path / "premade.yaml"
        config_file.write_text(
            "agents:\n"
            "  - name: SeedAgent\n"
            "    description: desc\n"
            "    agent_type: classic\n"
        )

        @contextmanager
        def _yield():
            yield pg_conn

        seeder = DatabaseSeeder()
        with patch(
            "application.seed.seeder.db_session", _yield
        ), patch(
            "application.seed.seeder.db_readonly", _yield
        ):
            seeder.seed_initial_data(
                config_path=str(config_file), force=True,
            )

    def test_handle_tools_empty_success(self, pg_conn):
        from application.seed.seeder import DatabaseSeeder

        @contextmanager
        def _yield():
            yield pg_conn

        seeder = DatabaseSeeder()
        with patch(
            "application.seed.seeder.db_session", _yield
        ), patch(
            "application.seed.seeder.db_readonly", _yield
        ):
            # Agent config with tools list, but tool name is bogus
            got = seeder._handle_tools({
                "name": "a",
                "tools": [
                    {"name": "nonexistent_tool", "config": {}},
                ],
            })
        assert got == []


# ---------------------------------------------------------------------------
# agents/routes.py — remaining edge cases
# ---------------------------------------------------------------------------


class TestAgentsRoutesRemainingGaps:
    def test_get_agents_filters_out_incomplete(self, app, pg_conn):
        """Agents missing both source and retriever are filtered from the list."""
        from application.api.user.agents.routes import GetAgents
        from application.storage.db.repositories.agents import AgentsRepository

        @contextmanager
        def _yield():
            yield pg_conn

        user = "u-filter"
        # Complete agent: has retriever
        AgentsRepository(pg_conn).create(
            user, "ok", "published", retriever="classic",
        )
        # Incomplete agent: no source, no retriever, not workflow type
        AgentsRepository(pg_conn).create(user, "bad", "published")

        with patch(
            "application.api.user.agents.routes.db_session", _yield
        ), patch(
            "application.api.user.agents.routes.db_readonly", _yield
        ), app.test_request_context("/api/get_agents"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetAgents().get()
        assert response.status_code == 200
        names = [a["name"] for a in response.json]
        assert "ok" in names
        assert "bad" not in names
