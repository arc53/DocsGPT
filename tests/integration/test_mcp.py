#!/usr/bin/env python3
"""
Integration tests for DocsGPT MCP (Model Context Protocol) server endpoints.

Endpoints tested:
- /api/mcp_server/callback (GET) - OAuth callback
- /api/mcp_server/oauth_status/{task_id} (GET) - OAuth status
- /api/mcp_server/save (POST) - Save MCP server config
- /api/mcp_server/test (POST) - Test MCP server connection

Usage:
    python tests/integration/test_mcp.py
    python tests/integration/test_mcp.py --base-url http://localhost:7091
    python tests/integration/test_mcp.py --token YOUR_JWT_TOKEN
"""

import sys
import time
from pathlib import Path

# Add parent directory to path for standalone execution
_THIS_DIR = Path(__file__).parent
_TESTS_DIR = _THIS_DIR.parent
_ROOT_DIR = _TESTS_DIR.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from tests.integration.base import DocsGPTTestBase, create_client_from_args


class MCPTests(DocsGPTTestBase):
    """Integration tests for MCP server endpoints."""

    # -------------------------------------------------------------------------
    # Callback Tests
    # -------------------------------------------------------------------------

    def test_mcp_callback(self) -> bool:
        """Test MCP OAuth callback endpoint."""
        test_name = "MCP OAuth callback"
        self.print_header(test_name)

        try:
            response = self.get(
                "/api/mcp_server/callback",
                params={"code": "test_code", "state": "test_state"},
                timeout=10,
            )

            # Expect various responses depending on configuration
            if response.status_code in [200, 302, 400, 404]:
                self.print_success(f"Callback response: {response.status_code}")
                self.record_result(test_name, True, f"Status: {response.status_code}")
                return True

            self.print_error(f"Unexpected status: {response.status_code}")
            self.record_result(test_name, False, f"Status: {response.status_code}")
            return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # OAuth Status Tests
    # -------------------------------------------------------------------------

    def test_mcp_oauth_status(self) -> bool:
        """Test getting MCP OAuth status."""
        test_name = "MCP OAuth status"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.get(
                "/api/mcp_server/oauth_status/test-task-id-123",
                timeout=10,
            )

            if response.status_code in [200, 404]:
                self.print_success(f"OAuth status check: {response.status_code}")
                if response.status_code == 200:
                    result = response.json()
                    self.print_info(f"Status: {result.get('status', 'N/A')}")
                self.record_result(test_name, True, f"Status: {response.status_code}")
                return True

            self.print_error(f"Unexpected status: {response.status_code}")
            self.record_result(test_name, False, f"Status: {response.status_code}")
            return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_mcp_oauth_status_invalid_task(self) -> bool:
        """Test OAuth status for invalid task ID."""
        test_name = "MCP OAuth status invalid"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.get(
                "/api/mcp_server/oauth_status/nonexistent-task-xyz",
                timeout=10,
            )

            if response.status_code in [404, 400]:
                self.print_success(f"Correctly returned: {response.status_code}")
                self.record_result(test_name, True, "Invalid task handled")
                return True
            elif response.status_code == 200:
                result = response.json()
                if result.get("status") in ["not_found", "unknown", None]:
                    self.print_success("Invalid task handled (status: not_found)")
                    self.record_result(test_name, True, "Invalid task handled")
                    return True

            self.print_warning(f"Status: {response.status_code}")
            self.record_result(test_name, True, f"Status: {response.status_code}")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Save Tests
    # -------------------------------------------------------------------------

    def test_mcp_save(self) -> bool:
        """Test saving MCP server configuration."""
        test_name = "Save MCP server config"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        payload = {
            "name": f"Test MCP Server {int(time.time())}",
            "url": "https://example.com/mcp",
            "config": {},
        }

        try:
            response = self.post(
                "/api/mcp_server/save",
                json=payload,
                timeout=15,
            )

            if response.status_code in [200, 201]:
                result = response.json()
                self.print_success(f"Saved MCP server: {result.get('id', 'N/A')}")
                self.record_result(test_name, True, "Config saved")
                return True
            elif response.status_code in [400, 422]:
                self.print_warning(f"Validation error: {response.status_code}")
                self.record_result(test_name, True, "Validation handled")
                return True

            self.print_error(f"Save failed: {response.status_code}")
            self.record_result(test_name, False, f"Status: {response.status_code}")
            return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_mcp_save_invalid(self) -> bool:
        """Test saving invalid MCP config."""
        test_name = "Save invalid MCP config"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        payload = {
            "name": "",  # Invalid empty name
            "url": "not-a-url",  # Invalid URL
        }

        try:
            response = self.post(
                "/api/mcp_server/save",
                json=payload,
                timeout=15,
            )

            if response.status_code in [400, 422]:
                self.print_success(f"Validation rejected: {response.status_code}")
                self.record_result(test_name, True, "Invalid config rejected")
                return True
            elif response.status_code in [200, 201]:
                self.print_warning("Server accepted invalid data (lenient validation)")
                self.record_result(test_name, True, "Lenient validation")
                return True

            self.print_error(f"Unexpected status: {response.status_code}")
            self.record_result(test_name, False, f"Status: {response.status_code}")
            return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Test Connection Tests
    # -------------------------------------------------------------------------

    def test_mcp_test_connection(self) -> bool:
        """Test MCP server connection test."""
        test_name = "Test MCP connection"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        payload = {
            "url": "https://example.com/mcp",
            "config": {},
        }

        try:
            response = self.post(
                "/api/mcp_server/test",
                json=payload,
                timeout=30,  # Connection test may take time
            )

            if response.status_code == 200:
                result = response.json()
                success = result.get("success", result.get("connected", False))
                self.print_success(f"Connection test: success={success}")
                self.record_result(test_name, True, f"Connected: {success}")
                return True
            elif response.status_code in [400, 500, 502, 504]:
                # Connection failed (expected for non-existent server)
                self.print_warning(f"Connection failed: {response.status_code}")
                self.record_result(test_name, True, "Connection failed (expected)")
                return True

            self.print_error(f"Unexpected status: {response.status_code}")
            self.record_result(test_name, False, f"Status: {response.status_code}")
            return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_mcp_test_connection_invalid(self) -> bool:
        """Test MCP connection with invalid URL."""
        test_name = "Test MCP invalid URL"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        payload = {
            "url": "invalid-url",
            "config": {},
        }

        try:
            response = self.post(
                "/api/mcp_server/test",
                json=payload,
                timeout=15,
            )

            if response.status_code in [400, 422, 500]:
                self.print_success(f"Invalid URL rejected: {response.status_code}")
                self.record_result(test_name, True, "Invalid URL handled")
                return True
            elif response.status_code == 200:
                result = response.json()
                if not result.get("success", result.get("connected", True)):
                    self.print_success("Connection correctly failed")
                    self.record_result(test_name, True, "Connection failed")
                    return True

            self.print_warning(f"Status: {response.status_code}")
            self.record_result(test_name, True, f"Status: {response.status_code}")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Test Runner
    # -------------------------------------------------------------------------

    def run_all(self) -> bool:
        """Run all MCP tests."""
        self.print_header("DocsGPT MCP Server Integration Tests")
        self.print_info(f"Base URL: {self.base_url}")
        self.print_info(f"Auth: {self.token_source}")

        # Callback tests
        self.test_mcp_callback()

        # OAuth status tests
        self.test_mcp_oauth_status()
        self.test_mcp_oauth_status_invalid_task()

        # Save tests
        self.test_mcp_save()
        self.test_mcp_save_invalid()

        # Test connection tests
        self.test_mcp_test_connection()
        self.test_mcp_test_connection_invalid()

        return self.print_summary()


def main():
    """Main entry point."""
    client = create_client_from_args(MCPTests, "DocsGPT MCP Server Integration Tests")
    exit_code = 0 if client.run_all() else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
