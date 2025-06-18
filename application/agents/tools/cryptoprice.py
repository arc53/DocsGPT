import requests
from application.agents.tools.base import Tool


class CryptoPriceTool(Tool):
    """
    CryptoPrice
    A tool for retrieving cryptocurrency prices using the CryptoCompare public API
    """

    def __init__(self, config):
        self.config = config

    def execute_action(self, action_name, **kwargs):
        actions = {"cryptoprice_get": self._get_price}

        if action_name in actions:
            return actions[action_name](**kwargs)
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def _get_price(self, symbol, currency):
        """
        Fetches the current price of a given cryptocurrency symbol in the specified currency.
        Example:
            symbol = "BTC"
            currency = "USD"
            returns price in USD.
        """
        url = f"https://min-api.cryptocompare.com/data/price?fsym={symbol.upper()}&tsyms={currency.upper()}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if currency.upper() in data:
                return {
                    "status_code": response.status_code,
                    "price": data[currency.upper()],
                    "message": f"Price of {symbol.upper()} in {currency.upper()} retrieved successfully.",
                }
            else:
                return {
                    "status_code": response.status_code,
                    "message": f"Couldn't find price for {symbol.upper()} in {currency.upper()}.",
                }
        else:
            return {
                "status_code": response.status_code,
                "message": "Failed to retrieve price.",
            }

    def get_actions_metadata(self):
        return [
            {
                "name": "cryptoprice_get",
                "description": "Retrieve the price of a specified cryptocurrency in a given currency",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "The cryptocurrency symbol (e.g. BTC)",
                        },
                        "currency": {
                            "type": "string",
                            "description": "The currency in which you want the price (e.g. USD)",
                        },
                    },
                    "required": ["symbol", "currency"],
                    "additionalProperties": False,
                },
            }
        ]

    def get_config_requirements(self):
        # No specific configuration needed for this tool as it just queries a public endpoint
        return {}
