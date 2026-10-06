"""Tests for error paths in read_webpage tool."""

from unittest.mock import patch

import requests


class TestReadWebpageErrors:
    def test_request_exception_returns_error_string(self):
        from docsgpt.agents.tools.read_webpage import ReadWebpageTool

        tool = ReadWebpageTool(config={})
        with patch(
            "docsgpt.agents.tools.read_webpage.pinned_fetch_bytes",
            side_effect=requests.exceptions.RequestException("bad url"),
        ):
            got = tool.execute_action(
                "read_webpage", url="https://example.com/",
            )
        assert "Error fetching URL" in got

    def test_generic_exception_returns_error_string(self):
        from unittest.mock import MagicMock

        from docsgpt.agents.tools.read_webpage import ReadWebpageTool

        tool = ReadWebpageTool(config={})
        response = MagicMock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/html"}
        response.raise_for_status.return_value = None
        with patch(
            "docsgpt.agents.tools.read_webpage.html_to_markdown_text",
            side_effect=RuntimeError("boom"),
        ) as convert, patch(
            "docsgpt.agents.tools.read_webpage.pinned_fetch_bytes",
            return_value=(b"<h1>hi</h1>", response),
        ):
            got = tool.execute_action(
                "read_webpage", url="https://example.com/",
            )
        convert.assert_called_once_with("<h1>hi</h1>")
        assert got == "Error fetching URL https://example.com/: boom"


class TestBaseAgentMinorBranches:
    """Cover 2 missing lines in agents/base.py (116, 160)."""

    def test_base_agent_with_llm_provided(self):
        from docsgpt.agents.classic_agent import ClassicAgent
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        mock_handler = MagicMock()
        # Instantiating with llm+llm_handler skips the creator call paths
        agent = ClassicAgent(
            endpoint="ep", llm_name="openai", model_id="gpt-4",
            api_key="k", llm=mock_llm, llm_handler=mock_handler,
        )
        assert agent.llm is mock_llm
        assert agent.llm_handler is mock_handler


class TestWorkflowNodesMinor:
    """Cover line 44 in workflow_nodes.py (likely default params branch)."""

    def test_bulk_create_empty_list_returns_empty(self, pg_conn):
        from docsgpt.storage.db.repositories.workflow_nodes import (
            WorkflowNodesRepository,
        )
        got = WorkflowNodesRepository(pg_conn).bulk_create(
            "00000000-0000-0000-0000-000000000001",
            1,
            [],
        )
        assert got == []
