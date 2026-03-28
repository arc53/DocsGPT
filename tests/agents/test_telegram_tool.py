"""Tests for application/agents/tools/telegram.py"""

from unittest.mock import MagicMock, patch

import pytest

from application.agents.tools.telegram import TelegramTool


@pytest.fixture
def tool():
    return TelegramTool(config={"token": "bot123:ABC"})


@pytest.mark.unit
class TestTelegramExecuteAction:
    def test_unknown_action_raises(self, tool):
        with pytest.raises(ValueError, match="Unknown action"):
            tool.execute_action("invalid")

    @patch("application.agents.tools.telegram.requests.post")
    def test_send_message(self, mock_post, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = tool.execute_action(
            "telegram_send_message", text="Hello", chat_id="12345"
        )

        assert result["status_code"] == 200
        assert result["message"] == "Message sent"
        call_args = mock_post.call_args
        assert "bot123:ABC/sendMessage" in call_args[0][0]
        assert call_args[1]["data"]["text"] == "Hello"
        assert call_args[1]["data"]["chat_id"] == "12345"

    @patch("application.agents.tools.telegram.requests.post")
    def test_send_image(self, mock_post, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = tool.execute_action(
            "telegram_send_image", image_url="https://img.com/cat.jpg", chat_id="12345"
        )

        assert result["status_code"] == 200
        assert result["message"] == "Image sent"
        call_args = mock_post.call_args
        assert "bot123:ABC/sendPhoto" in call_args[0][0]
        assert call_args[1]["data"]["photo"] == "https://img.com/cat.jpg"

    @patch("application.agents.tools.telegram.requests.post")
    def test_api_error_status(self, mock_post, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_post.return_value = mock_resp

        result = tool.execute_action(
            "telegram_send_message", text="Hi", chat_id="999"
        )

        assert result["status_code"] == 403


@pytest.mark.unit
class TestTelegramMetadata:
    def test_actions_metadata(self, tool):
        meta = tool.get_actions_metadata()
        assert len(meta) == 2
        names = {a["name"] for a in meta}
        assert "telegram_send_message" in names
        assert "telegram_send_image" in names

    def test_config_requirements(self, tool):
        reqs = tool.get_config_requirements()
        assert "token" in reqs
        assert reqs["token"]["secret"] is True
