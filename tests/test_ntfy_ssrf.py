"""
PoC test for CWE-918: SSRF via NtfyTool server_url parameter.

The NtfyTool._send_message() method accepts server_url as a parameter
filled by the LLM (influenced by user prompts). Without SSRF validation,
an attacker can craft prompts causing the LLM to target internal services.

This test verifies that:
1. Internal/private IPs are blocked (169.254.169.254, 10.x, 192.168.x, etc.)
2. Blocked hostnames are rejected (localhost, metadata.google.internal)
3. Disallowed schemes are rejected (file://, ftp://)
4. Valid public URLs still work
"""

import pytest
from unittest.mock import patch, MagicMock

from application.agents.tools.ntfy import NtfyTool
from application.core.url_validation import SSRFError


@pytest.fixture
def ntfy_tool():
    return NtfyTool(config={"token": "test-token"})


class TestNtfySsrfProtection:
    """Verify NtfyTool rejects SSRF payloads in server_url."""

    def test_blocks_aws_metadata_ip(self, ntfy_tool):
        """SSRF via AWS metadata endpoint should be blocked."""
        with pytest.raises((SSRFError, ValueError)):
            ntfy_tool._send_message(
                server_url="http://169.254.169.254/latest/meta-data",
                message="test",
                topic="test-topic",
            )

    def test_blocks_private_ip_class_a(self, ntfy_tool):
        """SSRF via private 10.x.x.x network should be blocked."""
        with pytest.raises((SSRFError, ValueError)):
            ntfy_tool._send_message(
                server_url="http://10.0.0.1",
                message="test",
                topic="test-topic",
            )

    def test_blocks_private_ip_class_c(self, ntfy_tool):
        """SSRF via private 192.168.x.x network should be blocked."""
        with pytest.raises((SSRFError, ValueError)):
            ntfy_tool._send_message(
                server_url="http://192.168.1.1",
                message="test",
                topic="test-topic",
            )

    def test_blocks_loopback(self, ntfy_tool):
        """SSRF via localhost/loopback should be blocked."""
        with pytest.raises((SSRFError, ValueError)):
            ntfy_tool._send_message(
                server_url="http://127.0.0.1",
                message="test",
                topic="test-topic",
            )

    def test_blocks_localhost_hostname(self, ntfy_tool):
        """SSRF via 'localhost' hostname should be blocked."""
        with pytest.raises((SSRFError, ValueError)):
            ntfy_tool._send_message(
                server_url="http://localhost",
                message="test",
                topic="test-topic",
            )

    def test_blocks_metadata_google_internal(self, ntfy_tool):
        """SSRF via GCP metadata hostname should be blocked."""
        with pytest.raises((SSRFError, ValueError)):
            ntfy_tool._send_message(
                server_url="http://metadata.google.internal",
                message="test",
                topic="test-topic",
            )

    def test_blocks_file_scheme(self, ntfy_tool):
        """file:// scheme should be blocked."""
        with pytest.raises((SSRFError, ValueError)):
            ntfy_tool._send_message(
                server_url="file:///etc/passwd",
                message="test",
                topic="test-topic",
            )

    def test_blocks_hostname_resolving_to_private_ip(self, ntfy_tool):
        """Hostname that resolves to a private IP should be blocked."""
        with patch("application.core.url_validation.resolve_hostname") as mock_resolve:
            mock_resolve.return_value = "192.168.1.100"
            with pytest.raises((SSRFError, ValueError)):
                ntfy_tool._send_message(
                    server_url="http://evil-internal.example.com",
                    message="test",
                    topic="test-topic",
                )

    def test_allows_valid_public_url(self, ntfy_tool):
        """A valid public ntfy server URL should be allowed."""
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            with patch(
                "application.core.url_validation.resolve_hostname"
            ) as mock_resolve:
                mock_resolve.return_value = "93.184.216.34"  # Public IP
                result = ntfy_tool._send_message(
                    server_url="https://ntfy.sh",
                    message="hello",
                    topic="my-topic",
                )
                assert result["status_code"] == 200
                assert result["message"] == "Message sent"
                # Verify the request was made to the correct URL
                mock_post.assert_called_once()
                call_url = mock_post.call_args[0][0]
                assert call_url == "https://ntfy.sh/my-topic"

    def test_execute_action_blocks_ssrf(self, ntfy_tool):
        """SSRF should be blocked through the execute_action entry point too."""
        with pytest.raises((SSRFError, ValueError)):
            ntfy_tool.execute_action(
                "ntfy_send_message",
                server_url="http://169.254.169.254",
                message="test",
                topic="test-topic",
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
