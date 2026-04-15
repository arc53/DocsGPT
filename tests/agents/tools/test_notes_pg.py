"""Tests for application/agents/tools/notes.py using pg_conn."""

from contextlib import contextmanager
from unittest.mock import patch



@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.storage.db.session.db_readonly", _yield
    ), patch(
        "application.storage.db.session.db_session", _yield
    ):
        yield


def _make_tool(tool_id="default_test", user_id="u"):
    from application.agents.tools.notes import NotesTool
    tool = NotesTool.__new__(NotesTool)
    tool.tool_id = tool_id
    tool.user_id = user_id
    tool._last_artifact_id = None
    return tool


class TestNotesToolPgEnabled:
    def test_returns_false_no_tool_id(self):
        tool = _make_tool(tool_id=None)
        assert tool._pg_enabled() is False

    def test_returns_false_default_prefix(self):
        tool = _make_tool(tool_id="default_test")
        assert tool._pg_enabled() is False

    def test_returns_false_non_uuid(self):
        tool = _make_tool(tool_id="not-a-uuid")
        assert tool._pg_enabled() is False

    def test_returns_true_for_uuid(self):
        import uuid as _uuid
        tool = _make_tool(tool_id=str(_uuid.uuid4()))
        assert tool._pg_enabled() is True


class TestNotesToolExecuteGuards:
    def test_no_user_id_returns_error(self):
        tool = _make_tool()
        tool.user_id = None
        assert "valid user_id" in tool.execute_action("view")

    def test_not_pg_enabled_returns_error(self):
        tool = _make_tool(tool_id="default_abc")
        msg = tool.execute_action("view")
        assert "not configured" in msg

    def test_unknown_action(self, pg_conn):
        # Real tool_id requires a user_tools row
        from application.storage.db.repositories.user_tools import (
            UserToolsRepository,
        )
        UserToolsRepository(pg_conn).create("u", "notes_tool")
        # Use a uuid that has notes_tool rows
        tool_row = UserToolsRepository(pg_conn).list_for_user("u")[0]
        tool = _make_tool(tool_id=str(tool_row["id"]))
        with _patch_db(pg_conn):
            got = tool.execute_action("bogus_action")
        assert "Unknown action" in got


class TestNotesActionsMetadata:
    def test_returns_list(self):
        tool = _make_tool()
        got = tool.get_actions_metadata()
        assert isinstance(got, list)
        names = {a["name"] for a in got}
        assert names >= {"view", "overwrite", "str_replace", "insert", "delete"}


