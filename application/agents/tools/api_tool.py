import json

import requests
from application.agents.tools.base import Tool


class APITool(Tool):
    """
    API Tool
    A flexible tool for performing various API actions (e.g., sending messages, retrieving data) via custom user-specified APIs
    """

    def __init__(self, config):
        self.config = config
        self.url = config.get("url", "")
        self.method = config.get("method", "GET")
        self.headers = config.get("headers", {"Content-Type": "application/json"})
        self.query_params = config.get("query_params", {})

    def execute_action(self, action_name, **kwargs):
        return self._make_api_call(
            self.url, self.method, self.headers, self.query_params, kwargs
        )

    def _make_api_call(self, url, method, headers, query_params, body):
        sanitized_headers = {}
        for key, value in headers.items():
            if isinstance(value, str):
                sanitized_value = value.encode('latin-1', errors='ignore').decode('latin-1')
                sanitized_headers[key] = sanitized_value
            else:
                sanitized_headers[key] = value

        if query_params:
            url = f"{url}?{requests.compat.urlencode(query_params)}"
        if isinstance(body, dict):
            body = json.dumps(body)
        response = None
        try:
            print(f"Making API call: {method} {url} with body: {body}")
            if body == "{}":
                body = None

            proxy_id = self.config.get("proxy_id", None)
            request_kwargs = {
                'method': method,
                'url': url,
                'headers': sanitized_headers,
                'data': body
            }
            try:
                if proxy_id:
                    from application.agents.tools.proxy_handler import apply_proxy_to_request
                    response = apply_proxy_to_request(
                        requests.request,
                        proxy_id=proxy_id,
                        **request_kwargs
                    )
                else:
                    response = requests.request(**request_kwargs)
            except ImportError:
                response = requests.request(**request_kwargs)
            response.raise_for_status()
            content_type = response.headers.get(
                "Content-Type", "application/json"
            ).lower()
            if "application/json" in content_type:
                try:
                    data = response.json()
                except json.JSONDecodeError as e:
                    print(f"Error decoding JSON: {e}.  Raw response: {response.text}")
                    return {
                        "status_code": response.status_code,
                        "message": f"API call returned invalid JSON.  Error: {e}",
                        "data": response.text,
                    }
            elif "text/" in content_type or "application/xml" in content_type:
                data = response.text
            elif not response.content:
                data = None
            else:
                print(f"Unsupported content type: {content_type}")
                data = response.content

            return {
                "status_code": response.status_code,
                "data": data,
                "message": "API call successful.",
            }
        except requests.exceptions.RequestException as e:
            return {
                "status_code": response.status_code if response else None,
                "message": f"API call failed: {str(e)}",
            }

    def get_actions_metadata(self):
        return []

    def get_config_requirements(self):
        return {}
