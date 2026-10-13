"""Tests for docsgpt/agents/tools/ntfy.py"""

from unittest.mock import MagicMock, patch

import pytest

from docsgpt.agents.tools.ntfy import NtfyTool


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

    @patch("docsgpt.agents.tools.ntfy.pinned_request")
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

    @patch("docsgpt.agents.tools.ntfy.pinned_request")
    def test_failed_send_reports_the_servers_reason(self, mock_pinned_request, tool):
        from docsgpt.agents.tool_executor import result_status

        mock_pinned_request.return_value = MagicMock(
            status_code=403,
            json=MagicMock(return_value={"code": 40301, "http": 403, "error": "forbidden"}),
        )
        result = tool.execute_action(
            "ntfy_send_message", server_url="https://ntfy.sh", message="Hi", topic="t",
        )

        assert result["status"] == "error"
        assert "forbidden" in result["error"]
        assert result_status(result) == "error"

    def test_unsafe_url_is_an_error(self, tool):
        result = tool.execute_action(
            "ntfy_send_message", server_url="http://127.0.0.1", message="Hi", topic="t",
        )
        assert result["status"] == "error"

    @patch("docsgpt.agents.tools.ntfy.pinned_request")
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

    @patch("docsgpt.agents.tools.ntfy.pinned_request")
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

    @patch("docsgpt.agents.tools.ntfy.pinned_request")
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

    @patch("docsgpt.agents.tools.ntfy.pinned_request")
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


def _sent(mock_pinned_request):
    """``(url, headers)`` of the one request the tool made."""
    mock_pinned_request.assert_called_once()
    args, kwargs = mock_pinned_request.call_args
    return args[1], kwargs["headers"]


@pytest.mark.unit
class TestTokenStaysWithItsServer:
    """The access token goes only to the server its owner set up, never to one the model names."""

    @patch("docsgpt.agents.tools.ntfy.pinned_request")
    def test_model_chosen_server_does_not_get_the_token(self, mock_pinned_request, tool):
        result = tool.execute_action(
            "ntfy_send_message", server_url="https://attacker.example", message="hi", topic="t",
        )

        mock_pinned_request.assert_not_called()
        assert result["status"] == "error"
        assert "attacker.example" in result["error"]

    @pytest.mark.parametrize(
        "server_url",
        [
            "https://ntfy.sh.attacker.example",
            "https://attacker.example/ntfy.sh",
            "https://ntfy.sh@attacker.example",
            "https://ntfy.sh\\@attacker.example",
            "https://attacker.example?h=ntfy.sh",
            "http://ntfy.sh",
            "https://ntfy.sh:8443",
            "https://user:pw@ntfy.sh",
            "ntfy.sh",
        ],
    )
    @patch("docsgpt.agents.tools.ntfy.pinned_request")
    def test_lookalikes_of_the_default_server_do_not_get_the_token(self, mock_pinned_request, tool, server_url):
        result = tool.execute_action("ntfy_send_message", server_url=server_url, message="hi", topic="t")

        mock_pinned_request.assert_not_called()
        assert result["status"] == "error"

    @pytest.mark.parametrize("server_url", ["https://ntfy.sh", "https://NTFY.SH/", "https://ntfy.sh:443"])
    @patch("docsgpt.agents.tools.ntfy.pinned_request")
    def test_the_default_server_still_gets_the_token(self, mock_pinned_request, tool, server_url):
        mock_pinned_request.return_value = MagicMock(status_code=200)

        tool.execute_action("ntfy_send_message", server_url=server_url, message="hi", topic="t")

        assert _sent(mock_pinned_request)[1]["Authorization"] == "Basic test_token"

    @patch("docsgpt.agents.tools.ntfy.pinned_request")
    def test_configured_server_gets_the_token(self, mock_pinned_request):
        mock_pinned_request.return_value = MagicMock(status_code=200)
        tool = NtfyTool(config={"token": "test_token", "server_url": "https://ntfy.example.com/alerts/"})

        tool.execute_action("ntfy_send_message", server_url="https://ntfy.sh", message="hi", topic="t")

        url, headers = _sent(mock_pinned_request)
        assert url == "https://ntfy.example.com/alerts/t"
        assert headers["Authorization"] == "Basic test_token"

    @patch("docsgpt.agents.tools.ntfy.pinned_request")
    def test_configured_server_wins_over_the_models_choice(self, mock_pinned_request):
        mock_pinned_request.return_value = MagicMock(status_code=200)
        tool = NtfyTool(config={"token": "test_token", "server_url": "https://ntfy.example.com"})

        tool.execute_action("ntfy_send_message", server_url="https://attacker.example", message="hi", topic="t")

        assert _sent(mock_pinned_request)[0] == "https://ntfy.example.com/t"

    @patch("docsgpt.agents.tools.ntfy.pinned_request")
    def test_configured_server_needs_no_model_value(self, mock_pinned_request):
        mock_pinned_request.return_value = MagicMock(status_code=200)
        tool = NtfyTool(config={"token": "test_token", "server_url": "https://ntfy.example.com"})

        tool.execute_action("ntfy_send_message", message="hi", topic="t")

        assert _sent(mock_pinned_request)[0] == "https://ntfy.example.com/t"

    @patch("docsgpt.agents.tools.ntfy.pinned_request")
    def test_without_a_token_the_model_may_still_pick_the_server(self, mock_pinned_request, tool_no_token):
        mock_pinned_request.return_value = MagicMock(status_code=200)

        tool_no_token.execute_action(
            "ntfy_send_message", server_url="https://ntfy.example.org", message="hi", topic="t",
        )

        url, headers = _sent(mock_pinned_request)
        assert url == "https://ntfy.example.org/t"
        assert "Authorization" not in headers

    @patch("docsgpt.agents.tools.ntfy.pinned_request")
    def test_blank_configured_server_counts_as_unset(self, mock_pinned_request):
        tool = NtfyTool(config={"token": "test_token", "server_url": "  "})

        result = tool.execute_action(
            "ntfy_send_message", server_url="https://attacker.example", message="hi", topic="t",
        )

        mock_pinned_request.assert_not_called()
        assert result["status"] == "error"

    def test_server_url_is_a_plain_optional_setting(self, tool):
        spec = tool.get_config_requirements()["server_url"]

        assert spec["secret"] is False
        assert spec["required"] is False

    def test_the_model_can_still_name_a_server(self, tool):
        assert "server_url" in tool.get_actions_metadata()[0]["parameters"]["properties"]
