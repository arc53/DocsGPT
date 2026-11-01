"""Tests for the pending-state check on the MCP OAuth callback.

The callback used to accept any nonempty ``state`` and report success, so a
forged or stray redirect looked like a completed authorization. The check
below pins the intended behaviour: only a state this server actually issued
for a live sign-in is accepted.
"""

from unittest.mock import MagicMock

import pytest

# ``mcp_tool`` imports the user API package, which imports the MCP routes,
# which import ``mcp_tool`` back. Importing the API package first completes
# that cycle, so this file can be run on its own.
from docsgpt.api.user.tasks import mcp_oauth_task as _mcp_oauth_task  # noqa: F401


@pytest.mark.unit
class TestCallbackStateValidation:
    """The callback must only accept a state that has a sign-in in flight."""

    def _manager(self, redis_client=MagicMock()):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        return MCPOAuthManager(redis_client)

    def test_a_callback_for_a_pending_state_is_accepted(self):
        redis_client = MagicMock()
        redis_client.exists.return_value = 1
        manager = self._manager(redis_client)

        assert manager.handle_oauth_callback(state="live", code="auth_code") is True
        redis_client.setex.assert_any_call("mcp_oauth:code:live", 300, "auth_code")

    def test_a_callback_for_an_unknown_state_is_refused(self):
        redis_client = MagicMock()
        redis_client.exists.return_value = 0
        manager = self._manager(redis_client)

        assert manager.handle_oauth_callback(state="forged", code="auth_code") is False

    def test_a_refused_callback_stores_no_authorization_code(self):
        redis_client = MagicMock()
        redis_client.exists.return_value = 0
        manager = self._manager(redis_client)

        manager.handle_oauth_callback(state="forged", code="auth_code")

        stored = [call for call in redis_client.setex.call_args_list]
        assert not [call for call in stored if "code:forged" in str(call)]

    def test_the_pending_check_asks_for_the_state_auth_url_key(self):
        redis_client = MagicMock()
        redis_client.exists.return_value = 1
        manager = self._manager(redis_client)

        manager.handle_oauth_callback(state="live", code="auth_code")

        redis_client.exists.assert_called_with("mcp_oauth:auth_url:live")

    def test_a_replayed_callback_is_refused_once_the_sign_in_has_ended(self):
        # The worker removes ``auth_url:<state>`` when it consumes the code,
        # so a second callback for the same state finds no live sign-in.
        redis_client = MagicMock()
        redis_client.exists.return_value = 0
        manager = self._manager(redis_client)

        assert manager.handle_oauth_callback(state="spent", code="auth_code") is False

    def test_a_refused_callback_reports_an_error_rather_than_success(self):
        # The API redirects to the callback-status page, so the browser must
        # be told the authorization failed.
        redis_client = MagicMock()
        redis_client.exists.return_value = 0
        manager = self._manager(redis_client)

        result = manager.handle_oauth_callback(state="forged", code="auth_code")

        assert result is False

    def test_the_check_uses_the_prefix_the_manager_was_given(self):
        redis_client = MagicMock()
        redis_client.exists.return_value = 1
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        manager = MCPOAuthManager(redis_client, redis_prefix="custom:")

        manager.handle_oauth_callback(state="live", code="auth_code")

        redis_client.exists.assert_called_with("custom:auth_url:live")

    def test_a_callback_without_redis_is_refused(self):
        manager = self._manager(None)

        assert manager.handle_oauth_callback(state="live", code="auth_code") is False

    def test_a_callback_without_a_state_is_refused(self):
        redis_client = MagicMock()
        manager = self._manager(redis_client)

        assert manager.handle_oauth_callback(state="", code="auth_code") is False

    def test_a_failing_redis_refuses_the_callback(self):
        # If the pending state cannot be checked, the callback is refused
        # rather than accepted on an unverified assumption.
        redis_client = MagicMock()
        redis_client.exists.side_effect = Exception("redis is down")
        manager = self._manager(redis_client)

        assert manager.handle_oauth_callback(state="live", code="auth_code") is False

    def test_an_error_callback_for_a_pending_state_is_still_refused(self):
        # An error callback tells the waiting sign-in that the user declined.
        redis_client = MagicMock()
        redis_client.exists.return_value = 1
        manager = self._manager(redis_client)

        result = manager.handle_oauth_callback(
            state="live", code="", error="access_denied"
        )

        assert result is False
        redis_client.setex.assert_any_call(
            "mcp_oauth:error:live", 300, "access_denied"
        )
