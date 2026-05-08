"""Tests for application/agents/tools/cryptoprice.py"""

from unittest.mock import MagicMock, patch

import pytest

from application.agents.tools.cryptoprice import CryptoPriceTool


@pytest.fixture
def tool():
    return CryptoPriceTool(config={})


@pytest.mark.unit
class TestCryptoPriceExecuteAction:
    def test_unknown_action_raises(self, tool):
        with pytest.raises(ValueError, match="Unknown action"):
            tool.execute_action("invalid_action")

    @patch("application.agents.tools.cryptoprice.requests.get")
    def test_successful_price_fetch(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"USD": 65000}
        mock_get.return_value = mock_resp

        result = tool.execute_action("cryptoprice_get", symbol="BTC", currency="USD")

        assert result["status_code"] == 200
        assert result["price"] == 65000
        assert "successfully" in result["message"]

    @patch("application.agents.tools.cryptoprice.requests.get")
    def test_currency_not_found(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"EUR": 60000}
        mock_get.return_value = mock_resp

        result = tool.execute_action("cryptoprice_get", symbol="BTC", currency="USD")

        assert result["status_code"] == 200
        assert "Couldn't find" in result["message"]
        assert "price" not in result

    @patch("application.agents.tools.cryptoprice.requests.get")
    def test_api_failure(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp

        result = tool.execute_action("cryptoprice_get", symbol="BTC", currency="USD")

        assert result["status_code"] == 500
        assert "Failed" in result["message"]

    @patch("application.agents.tools.cryptoprice.requests.get")
    def test_symbol_case_insensitive(self, mock_get, tool):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"USD": 100}
        mock_get.return_value = mock_resp

        tool.execute_action("cryptoprice_get", symbol="btc", currency="usd")

        called_url = mock_get.call_args[0][0]
        assert "fsym=BTC" in called_url
        assert "tsyms=USD" in called_url


@pytest.mark.unit
class TestCryptoPriceMetadata:
    def test_actions_metadata(self, tool):
        meta = tool.get_actions_metadata()
        assert len(meta) == 1
        assert meta[0]["name"] == "cryptoprice_get"
        params = meta[0]["parameters"]
        assert "symbol" in params["properties"]
        assert "currency" in params["properties"]
        assert "symbol" in params["required"]
        assert "currency" in params["required"]

    def test_config_requirements(self, tool):
        assert tool.get_config_requirements() == {}
