"""Tests for the readable tool names Activity shows."""

from __future__ import annotations

from sqlalchemy import text

from docsgpt.activity import labels


def _tool(conn, name, custom=None, display=None):
    conn.execute(
        text(
            "INSERT INTO user_tools (user_id, name, custom_name, display_name) "
            "VALUES ('u1', :n, :c, :d)"
        ),
        {"n": name, "c": custom, "d": display},
    )


class TestCatalogName:
    def test_reads_the_tool_class(self):
        assert labels.catalog_name("code_executor") == "Code Executor"

    def test_keeps_acronyms_when_it_falls_back(self):
        assert labels._fallback("mcp_tool") == "MCP tool"
        assert labels._fallback("artifact_pdf") == "Artifact PDF"

    def test_never_imports_a_path(self):
        assert labels.catalog_name("../secrets") == "../secrets"
        assert labels.catalog_name("os.path") == "Os.path"


class TestToolLabels:
    def test_uses_the_users_own_name_for_a_single_tool(self, pg_conn):
        _tool(pg_conn, "code_executor", custom="Report sandbox")
        assert labels.tool_labels(pg_conn, "u1", ["code_executor"]) == {"code_executor": "Report sandbox"}

    def test_uses_the_catalog_name_when_the_user_has_several(self, pg_conn):
        _tool(pg_conn, "api_tool", custom="Billing API")
        _tool(pg_conn, "api_tool", custom="CRM API")
        assert labels.tool_labels(pg_conn, "u1", ["api_tool"])["api_tool"] == labels.catalog_name("api_tool")

    def test_without_a_tool_row_uses_the_catalog(self, pg_conn):
        assert labels.tool_labels(pg_conn, "u1", ["code_executor"]) == {"code_executor": "Code Executor"}
