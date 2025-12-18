import json
import logging
import re
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from application.agents.tools.api_body_serializer import (
    ContentType,
    RequestBodySerializer,
)
from application.agents.tools.base import Tool

logger = logging.getLogger(__name__)


class APITool(Tool):
    """
    API Tool
    A flexible tool for performing various API actions (e.g., sending messages, retrieving data) via custom user-specified APIs.
    """

    def __init__(self, config):
        self.config = config
        self.url = config.get("url", "")
        self.method = config.get("method", "GET")
        self.headers = config.get("headers", {})
        self.query_params = config.get("query_params", {})
        self.body_content_type = config.get("body_content_type", ContentType.JSON)
        self.body_encoding_rules = config.get("body_encoding_rules", {})

    def execute_action(self, action_name, **kwargs):
        """Execute an API action with the given arguments."""
        return self._make_api_call(
            self.url,
            self.method,
            self.headers,
            self.query_params,
            kwargs,
            self.body_content_type,
            self.body_encoding_rules,
        )

    def _make_api_call(
        self,
        url: str,
        method: str,
        headers: Dict[str, str],
        query_params: Dict[str, Any],
        body: Dict[str, Any],
        content_type: str = ContentType.JSON,
        encoding_rules: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Make an API call with proper body serialization and error handling.

        Args:
            url: API endpoint URL
            method: HTTP method (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS)
            headers: Request headers dict
            query_params: URL query parameters
            body: Request body as dict
            content_type: Content-Type for serialization
            encoding_rules: OpenAPI encoding rules

        Returns:
            Dict with status_code, data, and message
        """
        request_url = url
        request_headers = headers.copy() if headers else {}
        response = None

        try:
            path_params_used = set()
            if query_params:
                for match in re.finditer(r"\{([^}]+)\}", request_url):
                    param_name = match.group(1)
                    if param_name in query_params:
                        request_url = request_url.replace(
                            f"{{{param_name}}}", str(query_params[param_name])
                        )
                        path_params_used.add(param_name)
            remaining_params = {
                k: v for k, v in query_params.items() if k not in path_params_used
            }
            if remaining_params:
                query_string = urlencode(remaining_params)
                separator = "&" if "?" in request_url else "?"
                request_url = f"{request_url}{separator}{query_string}"
            # Serialize body based on content type

            if body and body != {}:
                try:
                    serialized_body, body_headers = RequestBodySerializer.serialize(
                        body, content_type, encoding_rules
                    )
                    request_headers.update(body_headers)
                except ValueError as e:
                    logger.error(f"Body serialization failed: {str(e)}")
                    return {
                        "status_code": None,
                        "message": f"Body serialization error: {str(e)}",
                        "data": None,
                    }
            else:
                serialized_body = None
            if "Content-Type" not in request_headers and method not in [
                "GET",
                "HEAD",
                "DELETE",
            ]:
                request_headers["Content-Type"] = ContentType.JSON
            logger.debug(
                f"API Call: {method} {request_url} | Content-Type: {request_headers.get('Content-Type', 'N/A')}"
            )

            if method.upper() == "GET":
                response = requests.get(
                    request_url, headers=request_headers, timeout=30
                )
            elif method.upper() == "POST":
                response = requests.post(
                    request_url,
                    data=serialized_body,
                    headers=request_headers,
                    timeout=30,
                )
            elif method.upper() == "PUT":
                response = requests.put(
                    request_url,
                    data=serialized_body,
                    headers=request_headers,
                    timeout=30,
                )
            elif method.upper() == "DELETE":
                response = requests.delete(
                    request_url, headers=request_headers, timeout=30
                )
            elif method.upper() == "PATCH":
                response = requests.patch(
                    request_url,
                    data=serialized_body,
                    headers=request_headers,
                    timeout=30,
                )
            elif method.upper() == "HEAD":
                response = requests.head(
                    request_url, headers=request_headers, timeout=30
                )
            elif method.upper() == "OPTIONS":
                response = requests.options(
                    request_url, headers=request_headers, timeout=30
                )
            else:
                return {
                    "status_code": None,
                    "message": f"Unsupported HTTP method: {method}",
                    "data": None,
                }
            response.raise_for_status()

            data = self._parse_response(response)

            return {
                "status_code": response.status_code,
                "data": data,
                "message": "API call successful.",
            }
        except requests.exceptions.Timeout:
            logger.error(f"Request timeout for {request_url}")
            return {
                "status_code": None,
                "message": "Request timeout (30s exceeded)",
                "data": None,
            }
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            return {
                "status_code": None,
                "message": f"Connection error: {str(e)}",
                "data": None,
            }
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {response.status_code}: {str(e)}")
            try:
                error_data = response.json()
            except (json.JSONDecodeError, ValueError):
                error_data = response.text
            return {
                "status_code": response.status_code,
                "message": f"HTTP Error {response.status_code}",
                "data": error_data,
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {str(e)}")
            return {
                "status_code": response.status_code if response else None,
                "message": f"API call failed: {str(e)}",
                "data": None,
            }
        except Exception as e:
            logger.error(f"Unexpected error in API call: {str(e)}", exc_info=True)
            return {
                "status_code": None,
                "message": f"Unexpected error: {str(e)}",
                "data": None,
            }

    def _parse_response(self, response: requests.Response) -> Any:
        """
        Parse response based on Content-Type header.

        Supports: JSON, XML, plain text, binary data.
        """
        content_type = response.headers.get("Content-Type", "").lower()

        if not response.content:
            return None
        # JSON response

        if "application/json" in content_type:
            try:
                return response.json()
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON response: {str(e)}")
                return response.text
        # XML response

        elif "application/xml" in content_type or "text/xml" in content_type:
            return response.text
        # Plain text response

        elif "text/plain" in content_type or "text/html" in content_type:
            return response.text
        # Binary/unknown response

        else:
            # Try to decode as text first, fall back to base64

            try:
                return response.text
            except (UnicodeDecodeError, AttributeError):
                import base64

                return base64.b64encode(response.content).decode("utf-8")

    def get_actions_metadata(self):
        """Return metadata for available actions (none for API Tool - actions are user-defined)."""
        return []

    def get_config_requirements(self):
        """Return configuration requirements for the tool."""
        return {}
