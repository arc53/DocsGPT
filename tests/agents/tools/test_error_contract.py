"""Executable form of the ``ToolExecutor.result_status`` error contract.

``result_status`` classifies a tool payload as a failure only when it
carries an in-band marker (``status: "error"``, a truthy ``error`` key, or
an integer ``status_code >= 400``); everything else is journaled as
``completed``. Issue #3288 was that contract breaking silently —
``APITool`` returned 3xx-redirect, timeout and connection-failure payloads
with no marker, so failed tool calls were persisted as successes.

Every HTTP-backed tool is registered in ``TOOLS`` below: for each, any
transport-level failure (timeout, connection error, SSRF rejection,
unfollowed redirect) must come back classified as ``error``. Registering a
new tool here instantly gives it the same net.
"""

from unittest.mock import Mock, patch

import pytest
import requests

from docsgpt.agents.tool_executor import result_status
from docsgpt.agents.tools.api_tool import APITool
from docsgpt.agents.tools.ntfy import NtfyTool
from docsgpt.agents.tools.tool_results import strip_userinfo
from docsgpt.security.safe_url import UnsafeUserUrlError

TOOLS = {
    "api_tool": {
        "patch": "docsgpt.agents.tools.api_tool.pinned_request",
        "invoke": lambda: APITool(
            config={
                "url": "https://user:pass@api.example.com/v1/orders",
                "method": "POST",
            }
        ).execute_action("any"),
    },
    "ntfy": {
        "patch": "docsgpt.agents.tools.ntfy.pinned_request",
        "invoke": lambda: NtfyTool(config={"token": "tok"}).execute_action(
            "ntfy_send_message",
            server_url="https://ntfy.example.com",
            message="hello",
            topic="alerts",
        ),
    },
}

FAILURE_EFFECTS = {
    "timeout": lambda: requests.exceptions.Timeout(),
    "connection_error": lambda: requests.exceptions.ConnectionError("refused"),
    "url_validation": lambda: UnsafeUserUrlError("blocked"),
}


def _redirect_response(status=307, location="/v1/orders/"):
    return Mock(
        status_code=status,
        headers={"Location": location} if location else {},
        content=b"",
        text="",
    )


@pytest.mark.unit
class TestErrorContract:

    @pytest.mark.parametrize("tool_name", TOOLS)
    @pytest.mark.parametrize("failure_name", FAILURE_EFFECTS)
    def test_transport_failure_is_classified_error(self, tool_name, failure_name):
        with patch(
            TOOLS[tool_name]["patch"], side_effect=FAILURE_EFFECTS[failure_name]()
        ):
            result = TOOLS[tool_name]["invoke"]()
        assert result_status(result) == "error"
        assert result["status"] == "error"

    @pytest.mark.parametrize("tool_name", TOOLS)
    def test_unfollowed_redirect_is_classified_error(self, tool_name):
        with patch(TOOLS[tool_name]["patch"], return_value=_redirect_response()):
            result = TOOLS[tool_name]["invoke"]()
        assert result_status(result) == "error"
        assert result["status"] == "error"

    def test_redirect_message_names_target_without_credentials(self):
        with patch(TOOLS["api_tool"]["patch"], return_value=_redirect_response()):
            result = TOOLS["api_tool"]["invoke"]()
        assert "user:pass" not in result["message"]
        assert "https://api.example.com/v1/orders/" in result["message"]

    def test_redirect_without_location_is_classified_error(self):
        with patch(
            TOOLS["api_tool"]["patch"], return_value=_redirect_response(location="")
        ):
            result = TOOLS["api_tool"]["invoke"]()
        assert result_status(result) == "error"
        assert "no target location" in result["message"]

    def test_304_not_modified_is_classified_error(self):
        with patch(
            TOOLS["api_tool"]["patch"],
            return_value=_redirect_response(status=304, location=""),
        ):
            result = TOOLS["api_tool"]["invoke"]()
        assert result_status(result) == "error"
        assert "304" in result["message"]

    @pytest.mark.parametrize("tool_name", TOOLS)
    def test_success_still_classified_completed(self, tool_name):
        if tool_name == "api_tool":
            response = Mock(
                status_code=200,
                headers={"Content-Type": "application/json"},
                content=b"{}",
                json=lambda: {},
            )
        else:
            response = Mock(status_code=200, headers={})
        with patch(TOOLS[tool_name]["patch"], return_value=response):
            result = TOOLS[tool_name]["invoke"]()
        assert result_status(result) == "completed"


@pytest.mark.unit
class TestStripUserinfo:

    def test_removes_userinfo(self):
        assert (
            strip_userinfo("https://user:pass@api.example.com/v1/orders?x=1")
            == "https://api.example.com/v1/orders?x=1"
        )

    def test_rebrackets_ipv6(self):
        assert (
            strip_userinfo("https://user:pass@[2001:db8::1]:8443/x")
            == "https://[2001:db8::1]:8443/x"
        )

    def test_no_userinfo_is_noop(self):
        assert strip_userinfo("https://api.example.com/x") == "https://api.example.com/x"
