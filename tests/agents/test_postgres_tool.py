"""Tests for application/agents/tools/postgres.py"""

from unittest.mock import MagicMock, patch

import pytest

from application.agents.tools.postgres import PostgresTool


@pytest.fixture
def tool():
    return PostgresTool(config={"token": "postgresql://user:pass@localhost/testdb"})


@pytest.mark.unit
class TestPostgresExecuteAction:
    def test_unknown_action_raises(self, tool):
        with pytest.raises(ValueError, match="Unknown action"):
            tool.execute_action("invalid")

    @patch("application.agents.tools.postgres.psycopg2.connect")
    def test_select_query(self, mock_connect, tool):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("id",), ("name",)]
        mock_cur.fetchall.return_value = [(1, "Alice"), (2, "Bob")]
        mock_conn.cursor.return_value = mock_cur
        mock_connect.return_value = mock_conn

        result = tool.execute_action(
            "postgres_execute_sql", sql_query="SELECT id, name FROM users"
        )

        assert result["status_code"] == 200
        assert result["response_data"]["column_names"] == ["id", "name"]
        assert len(result["response_data"]["data"]) == 2
        assert result["response_data"]["data"][0] == {"id": 1, "name": "Alice"}
        mock_conn.close.assert_called_once()

    def test_insert_query_rejected(self, tool):
        """INSERT queries are now blocked by read-only validation."""
        result = tool.execute_action(
            "postgres_execute_sql",
            sql_query="INSERT INTO users (name) VALUES ('Alice')",
        )

        assert result["status_code"] == 403
        assert "not allowed" in result["message"].lower() or "not allowed" in result.get("error", "").lower()

    @patch("application.agents.tools.postgres.psycopg2.connect")
    def test_db_error(self, mock_connect, tool):
        import psycopg2

        mock_connect.side_effect = psycopg2.Error("connection refused")

        result = tool.execute_action(
            "postgres_execute_sql", sql_query="SELECT 1"
        )

        assert result["status_code"] == 500
        assert "Database error" in result["error"]

    @patch("application.agents.tools.postgres.psycopg2.connect")
    def test_get_schema(self, mock_connect, tool):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("users", "id", "integer", "nextval(...)", "NO"),
            ("users", "name", "varchar", None, "YES"),
            ("posts", "id", "integer", "nextval(...)", "NO"),
        ]
        mock_conn.cursor.return_value = mock_cur
        mock_connect.return_value = mock_conn

        result = tool.execute_action("postgres_get_schema", db_name="testdb")

        assert result["status_code"] == 200
        assert "users" in result["schema"]
        assert "posts" in result["schema"]
        assert len(result["schema"]["users"]) == 2
        assert result["schema"]["users"][0]["column_name"] == "id"
        mock_conn.close.assert_called_once()

    @patch("application.agents.tools.postgres.psycopg2.connect")
    def test_get_schema_db_error(self, mock_connect, tool):
        import psycopg2

        mock_connect.side_effect = psycopg2.Error("auth failed")

        result = tool.execute_action("postgres_get_schema", db_name="testdb")

        assert result["status_code"] == 500
        assert "Database error" in result["error"]

    def test_non_select_rejected_without_connection(self, tool):
        """Non-SELECT queries should be rejected before any DB connection is made."""
        result = tool.execute_action(
            "postgres_execute_sql", sql_query="DROP TABLE users"
        )

        assert result["status_code"] == 403

    @patch("application.agents.tools.postgres.psycopg2.connect")
    def test_select_with_no_description(self, mock_connect, tool):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = None
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cur
        mock_connect.return_value = mock_conn

        result = tool.execute_action(
            "postgres_execute_sql", sql_query="SELECT 1 WHERE false"
        )

        assert result["status_code"] == 200
        assert result["response_data"]["column_names"] == []


@pytest.mark.unit
class TestPostgresMetadata:
    def test_actions_metadata(self, tool):
        meta = tool.get_actions_metadata()
        assert len(meta) == 2
        names = {a["name"] for a in meta}
        assert "postgres_execute_sql" in names
        assert "postgres_get_schema" in names

    def test_config_requirements(self, tool):
        reqs = tool.get_config_requirements()
        assert "token" in reqs
        assert reqs["token"]["secret"] is True
