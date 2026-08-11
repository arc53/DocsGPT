"""Tests for application/agents/tools/ntfy.py"""

from unittest.mock import MagicMock, patch

import pytest

from application.agents.tools.ntfy import NtfyTool


@pytest.fixture
def tool():
    return NtfyTool(config={"token": "test_token"})


@pytest.fixture
def tool_no_token():
    return NtfyTool(config={})


@pytest.mark.unit
class TestNtfyExecuteAction:
    def test_unknown_action_raises(self, tool):
        with pytest.raises(ValueError, match="Unknown action"):
            tool.execute_action("bad_action")

    @patch("application.agents.tools.ntfy.pinned_request")
    def test_send_message_basic(self, mock_pinned_request, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_pinned_request.return_value = mock_resp

        result = tool.execute_action(
            "ntfy_send_message",
            server_url="https://ntfy.sh",
            message="Hello",
            topic="test",
        )

        assert result["status_code"] == 200
        assert result["message"] == "Message sent"
        mock_pinned_request.assert_called_once()
        args, kwargs = mock_pinned_request.call_args
        assert args[0] == "POST"
        assert args[1] == "https://ntfy.sh/test"
        assert kwargs["data"] == b"Hello"

    @patch("application.agents.tools.ntfy.pinned_request")
    def test_send_with_title_and_priority(self, mock_pinned_request, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_pinned_request.return_value = mock_resp

        tool.execute_action(
            "ntfy_send_message",
            server_url="https://ntfy.sh",
            message="Alert",
            topic="urgent",
            title="Warning",
            priority=5,
        )

        headers = mock_pinned_request.call_args[1]["headers"]
        assert headers["X-Title"] == "Warning"
        assert headers["X-Priority"] == "5"

    @patch("application.agents.tools.ntfy.pinned_request")
    def test_auth_header_with_token(self, mock_pinned_request, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_pinned_request.return_value = mock_resp

        tool.execute_action(
            "ntfy_send_message",
            server_url="https://ntfy.sh",
            message="Hi",
            topic="t",
        )

        headers = mock_pinned_request.call_args[1]["headers"]
        assert headers["Authorization"] == "Basic test_token"

    @patch("application.agents.tools.ntfy.pinned_request")
    def test_no_auth_without_token(self, mock_pinned_request, tool_no_token):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_pinned_request.return_value = mock_resp

        tool_no_token.execute_action(
            "ntfy_send_message",
            server_url="https://ntfy.sh",
            message="Hi",
            topic="t",
        )

        headers = mock_pinned_request.call_args[1]["headers"]
        assert "Authorization" not in headers

    def test_invalid_priority_raises(self, tool):
        with pytest.raises(ValueError, match="between 1 and 5"):
            tool.execute_action(
                "ntfy_send_message",
                server_url="https://ntfy.sh",
                message="Hi",
                topic="t",
                priority=10,
            )

    def test_non_numeric_priority_raises(self, tool):
        with pytest.raises(ValueError, match="convertible to an integer"):
            tool.execute_action(
                "ntfy_send_message",
                server_url="https://ntfy.sh",
                message="Hi",
                topic="t",
                priority="abc",
            )

    @patch("application.agents.tools.ntfy.pinned_request")
    def test_trailing_slash_stripped(self, mock_pinned_request, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_pinned_request.return_value = mock_resp

        tool.execute_action(
            "ntfy_send_message",
            server_url="https://ntfy.sh/",
            message="Hi",
            topic="test",
        )

        assert mock_pinned_request.call_args[0][1] == "https://ntfy.sh/test"


@pytest.mark.unit
class TestNtfyMetadata:
    def test_actions_metadata(self, tool):
        meta = tool.get_actions_metadata()
        assert len(meta) == 1
        assert meta[0]["name"] == "ntfy_send_message"
        assert "server_url" in meta[0]["parameters"]["properties"]
        assert "message" in meta[0]["parameters"]["properties"]
        assert "topic" in meta[0]["parameters"]["properties"]

    def test_config_requirements(self, tool):
        reqs = tool.get_config_requirements()
        assert "token" in reqs
        assert reqs["token"]["secret"] is True
