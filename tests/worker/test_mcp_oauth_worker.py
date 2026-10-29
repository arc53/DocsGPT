"""Tests for the worker's MCP OAuth task.

A server that answers anonymous MCP requests with HTTP 200 gives the OAuth
flow no challenge to react to, so the discovery can finish without ever
holding a token. The worker has to report that as a failure rather than as a
completed sign-in, and it has to publish the terminal event either way.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Loaded first so ``patch("docsgpt.agents.tools.mcp_tool.MCPTool")`` can resolve
# the module attribute: the worker imports ``MCPTool`` inside the function,
# and importing ``mcp_tool`` first trips the ``docsgpt.api.user`` circular
# import.
import docsgpt.api.user  # noqa: F401
import docsgpt.agents.tools.mcp_tool  # noqa: F401


class _FakeRequest:
    def __init__(self, task_id: str = "task-1"):
        self.id = task_id


class _FakeTask:
    """The bits of the bound Celery task ``mcp_oauth`` reads."""

    def __init__(self, task_id: str = "task-1"):
        self.request = _FakeRequest(task_id)


def _mcp_tool_mock(signed_in: bool, tools=None):
    """A stand-in for ``MCPTool`` with the OAuth outcome fixed."""
    tool = MagicMock()
    tool._client = MagicMock()
    tool.auth_type = "oauth"
    tool.oauth_signed_in = MagicMock(return_value=signed_in)
    tool.get_actions_metadata = MagicMock(return_value=tools or [{"name": "hf_search"}])
    tool._execute_with_client = AsyncMock(return_value=[])
    return tool


def _capturing_tool(captured, signed_in: bool):
    """A ``MCPTool`` stand-in that records the config it was built with."""

    def _factory(config, user_id=None):
        captured["config"] = config
        captured["user_id"] = user_id
        return _mcp_tool_mock(signed_in=signed_in)

    return _factory


@pytest.fixture
def _worker():
    import docsgpt.worker as worker

    return worker


class TestWorkerOAuthWithoutAToken:
    """An anonymous discovery is a failure, not a completed sign-in."""

    def test_a_discovery_without_a_token_fails(self, _worker):
        tool = _mcp_tool_mock(signed_in=False)

        with patch("docsgpt.agents.tools.mcp_tool.MCPTool", return_value=tool), \
                patch("docsgpt.worker.publish_user_event"):
            result = _worker.mcp_oauth(_FakeTask(), {"auth_type": "oauth"}, "alice")

        assert result["success"] is False
        assert "without an access token" in result["error"]

    def test_the_failure_names_the_anonymous_discovery(self, _worker):
        tool = _mcp_tool_mock(signed_in=False)

        with patch("docsgpt.agents.tools.mcp_tool.MCPTool", return_value=tool), \
                patch("docsgpt.worker.publish_user_event"):
            result = _worker.mcp_oauth(_FakeTask(), {"auth_type": "oauth"}, "alice")

        assert "answered the tool discovery anonymously" in result["error"]


class TestWorkerOAuthWithAToken:
    """A signed-in discovery completes and reports the tools."""

    def test_a_signed_in_discovery_succeeds(self, _worker):
        tool = _mcp_tool_mock(signed_in=True)

        with patch("docsgpt.agents.tools.mcp_tool.MCPTool", return_value=tool), \
                patch("docsgpt.worker.publish_user_event"):
            result = _worker.mcp_oauth(_FakeTask(), {"auth_type": "oauth"}, "alice")

        assert result["success"] is True
        assert result["tools_count"] == 1

    def test_a_server_without_oauth_does_not_require_a_token(self, _worker):
        """A tool discovery on a server that needs no OAuth is not a failure."""
        tool = _mcp_tool_mock(signed_in=False)
        tool.auth_type = "none"

        with patch("docsgpt.agents.tools.mcp_tool.MCPTool", return_value=tool), \
                patch("docsgpt.worker.publish_user_event"):
            result = _worker.mcp_oauth(_FakeTask(), {"auth_type": "none"}, "alice")

        assert result["success"] is True


class TestWorkerOAuthEvents:
    """The worker publishes the phase events the frontend drives on."""

    def _published(self, _worker, tool):
        with patch("docsgpt.agents.tools.mcp_tool.MCPTool", return_value=tool), \
                patch("docsgpt.worker.publish_user_event") as publish:
            _worker.mcp_oauth(_FakeTask(), {"auth_type": "oauth"}, "alice")
        return [call.args[1] for call in publish.call_args_list]

    def test_a_successful_sign_in_publishes_in_progress_and_completed(self, _worker):
        events = self._published(_worker, _mcp_tool_mock(signed_in=True))

        assert "mcp.oauth.in_progress" in events
        assert "mcp.oauth.completed" in events

    def test_a_failed_sign_in_publishes_a_terminal_failure(self, _worker):
        events = self._published(_worker, _mcp_tool_mock(signed_in=False))

        assert "mcp.oauth.failed" in events
        assert "mcp.oauth.completed" not in events

    def test_the_events_carry_the_task_id(self, _worker):
        with patch("docsgpt.agents.tools.mcp_tool.MCPTool", return_value=_mcp_tool_mock(signed_in=True)), \
                patch("docsgpt.worker.publish_user_event") as publish:
            _worker.mcp_oauth(_FakeTask("task-42"), {"auth_type": "oauth"}, "alice")

        for call in publish.call_args_list:
            assert call.args[2]["task_id"] == "task-42"


class TestWorkerOAuthConfig:
    """The worker passes the task's config through to the tool."""

    def test_the_task_id_reaches_the_tool_config(self, _worker):
        captured = {}

        with patch(
            "docsgpt.agents.tools.mcp_tool.MCPTool",
            _capturing_tool(captured, signed_in=True),
        ), patch("docsgpt.worker.publish_user_event"):
            _worker.mcp_oauth(_FakeTask("task-7"), {"auth_type": "oauth"}, "alice")

        assert captured["config"]["oauth_task_id"] == "task-7"
        assert captured["user_id"] == "alice"

    def test_the_proactive_flag_survives_the_config(self, _worker):
        captured = {}

        with patch(
            "docsgpt.agents.tools.mcp_tool.MCPTool",
            _capturing_tool(captured, signed_in=True),
        ), patch("docsgpt.worker.publish_user_event"):
            _worker.mcp_oauth(
                _FakeTask("task-7"),
                {"auth_type": "oauth", "proactive_oauth": True},
                "alice",
            )

        assert captured["config"]["proactive_oauth"] is True

    def test_the_redirect_publish_callback_is_injected(self, _worker):
        captured = {}

        with patch(
            "docsgpt.agents.tools.mcp_tool.MCPTool",
            _capturing_tool(captured, signed_in=True),
        ), patch("docsgpt.worker.publish_user_event"):
            _worker.mcp_oauth(_FakeTask("task-7"), {"auth_type": "oauth"}, "alice")

        assert callable(captured["config"]["oauth_redirect_publish"])
