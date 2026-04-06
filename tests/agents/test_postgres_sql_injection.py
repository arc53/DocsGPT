"""
PoC / regression tests for CWE-89: SQL Injection via LLM-generated queries in PostgresTool.

The PostgresTool._execute_sql method passes LLM-generated SQL directly to
psycopg2's cur.execute() with no validation. An attacker can craft prompts
that cause the LLM to generate destructive queries (DROP, DELETE, UPDATE, etc.)
which are then committed via conn.commit().

These tests verify that the fix properly rejects non-SELECT queries.
"""

from unittest.mock import MagicMock, patch

import pytest

from application.agents.tools.postgres import PostgresTool


@pytest.fixture
def tool():
    return PostgresTool(config={"token": "postgresql://user:pass@localhost/testdb"})


class TestSQLInjectionPrevention:
    """Destructive or data-mutating queries must be blocked."""

    def test_drop_table_rejected(self, tool):
        """DROP TABLE should be blocked without hitting the database."""
        result = tool.execute_action(
            "postgres_execute_sql", sql_query="DROP TABLE users"
        )
        assert result["status_code"] == 403

    def test_delete_rejected(self, tool):
        result = tool.execute_action(
            "postgres_execute_sql", sql_query="DELETE FROM users WHERE id = 1"
        )
        assert result["status_code"] == 403

    def test_update_rejected(self, tool):
        result = tool.execute_action(
            "postgres_execute_sql", sql_query="UPDATE users SET name = 'hacked'"
        )
        assert result["status_code"] == 403

    def test_insert_rejected(self, tool):
        result = tool.execute_action(
            "postgres_execute_sql",
            sql_query="INSERT INTO users (name) VALUES ('evil')",
        )
        assert result["status_code"] == 403

    def test_truncate_rejected(self, tool):
        result = tool.execute_action(
            "postgres_execute_sql", sql_query="TRUNCATE TABLE users"
        )
        assert result["status_code"] == 403

    def test_alter_rejected(self, tool):
        result = tool.execute_action(
            "postgres_execute_sql", sql_query="ALTER TABLE users ADD COLUMN evil text"
        )
        assert result["status_code"] == 403

    def test_create_rejected(self, tool):
        result = tool.execute_action(
            "postgres_execute_sql", sql_query="CREATE TABLE evil (id int)"
        )
        assert result["status_code"] == 403

    def test_case_insensitive_rejection(self, tool):
        """Case variations should not bypass the filter."""
        result = tool.execute_action(
            "postgres_execute_sql", sql_query="dRoP tAbLe users"
        )
        assert result["status_code"] == 403

    def test_leading_whitespace_rejection(self, tool):
        """Leading whitespace should not bypass the filter."""
        result = tool.execute_action(
            "postgres_execute_sql", sql_query="   \n\t  DROP TABLE users"
        )
        assert result["status_code"] == 403

    def test_comment_prefix_rejection(self, tool):
        """SQL comments before destructive statements should be blocked."""
        result = tool.execute_action(
            "postgres_execute_sql", sql_query="/* comment */ DROP TABLE users"
        )
        assert result["status_code"] == 403

    def test_stacked_statements_rejected(self, tool):
        """Semicolons indicating stacked statements should be blocked."""
        result = tool.execute_action(
            "postgres_execute_sql",
            sql_query="SELECT 1; DROP TABLE users;",
        )
        assert result["status_code"] == 403

    @patch("application.agents.tools.postgres.psycopg2.connect")
    def test_select_still_works(self, mock_connect, tool):
        """Valid SELECT queries should still execute normally."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("id",)]
        mock_cur.fetchall.return_value = [(1,)]
        mock_conn.cursor.return_value = mock_cur
        mock_connect.return_value = mock_conn

        result = tool.execute_action(
            "postgres_execute_sql", sql_query="SELECT id FROM users"
        )
        assert result["status_code"] == 200

    @patch("application.agents.tools.postgres.psycopg2.connect")
    def test_with_select_still_works(self, mock_connect, tool):
        """CTE (WITH ... SELECT) queries should still work."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("id",)]
        mock_cur.fetchall.return_value = [(1,)]
        mock_conn.cursor.return_value = mock_cur
        mock_connect.return_value = mock_conn

        result = tool.execute_action(
            "postgres_execute_sql",
            sql_query="WITH active AS (SELECT * FROM users WHERE active) SELECT * FROM active",
        )
        assert result["status_code"] == 200

    @patch("application.agents.tools.postgres.psycopg2.connect")
    def test_explain_still_works(self, mock_connect, tool):
        """EXPLAIN queries should still work."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("QUERY PLAN",)]
        mock_cur.fetchall.return_value = [("Seq Scan on users...",)]
        mock_conn.cursor.return_value = mock_cur
        mock_connect.return_value = mock_conn

        result = tool.execute_action(
            "postgres_execute_sql",
            sql_query="EXPLAIN SELECT * FROM users",
        )
        assert result["status_code"] == 200

    @patch("application.agents.tools.postgres.psycopg2.connect")
    def test_no_commit_on_select(self, mock_connect, tool):
        """SELECT queries should NOT trigger conn.commit()."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("id",)]
        mock_cur.fetchall.return_value = [(1,)]
        mock_conn.cursor.return_value = mock_cur
        mock_connect.return_value = mock_conn

        tool.execute_action(
            "postgres_execute_sql", sql_query="SELECT id FROM users"
        )
        mock_conn.commit.assert_not_called()

    def test_grant_rejected(self, tool):
        result = tool.execute_action(
            "postgres_execute_sql", sql_query="GRANT ALL ON users TO evil_user"
        )
        assert result["status_code"] == 403

    def test_copy_rejected(self, tool):
        result = tool.execute_action(
            "postgres_execute_sql",
            sql_query="COPY users TO '/tmp/dump.csv'",
        )
        assert result["status_code"] == 403

    def test_with_insert_rejected(self, tool):
        """CTE with INSERT (writable CTE) should be blocked."""
        result = tool.execute_action(
            "postgres_execute_sql",
            sql_query="WITH ins AS (INSERT INTO users (name) VALUES ('evil') RETURNING id) SELECT * FROM ins",
        )
        assert result["status_code"] == 403
