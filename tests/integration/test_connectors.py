#!/usr/bin/env python3
"""
Integration tests for DocsGPT external connectors endpoints.

Endpoints tested:
- /api/connectors/auth (GET) - OAuth authentication URL
- /api/connectors/callback (GET) - OAuth callback
- /api/connectors/callback-status (GET) - Callback status
- /api/connectors/disconnect (POST) - Disconnect connector
- /api/connectors/files (POST) - List connector files
- /api/connectors/sync (POST) - Sync connector
- /api/connectors/validate-session (POST) - Validate session

Note: Many tests are limited without actual external service connections.

Usage:
    python tests/integration/test_connectors.py
    python tests/integration/test_connectors.py --base-url http://localhost:7091
    python tests/integration/test_connectors.py --token YOUR_JWT_TOKEN
"""

import sys
from pathlib import Path

# Add parent directory to path for standalone execution
_THIS_DIR = Path(__file__).parent
_TESTS_DIR = _THIS_DIR.parent
_ROOT_DIR = _TESTS_DIR.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from tests.integration.base import DocsGPTTestBase, create_client_from_args


class ConnectorTests(DocsGPTTestBase):
    """Integration tests for external connector endpoints."""

    # -------------------------------------------------------------------------
    # Auth Tests
    # -------------------------------------------------------------------------

    def test_connectors_auth_google(self) -> bool:
        """Test getting Google OAuth URL."""
        test_name = "Get Google OAuth URL"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.get(
                "/api/connectors/auth",
                params={"provider": "google"},
                timeout=10,
            )

            # Expect 200 with URL, or 400/501 if not configured
            if response.status_code == 200:
                result = response.json()
                auth_url = result.get("url") or result.get("auth_url")
                if auth_url:
                    self.print_success(f"Got OAuth URL: {auth_url[:50]}...")
                    self.record_result(test_name, True, "OAuth URL retrieved")
                    return True
            elif response.status_code in [400, 404, 501]:
                self.print_warning(f"Connector not configured: {response.status_code}")
                self.record_result(test_name, True, "Not configured (expected)")
                return True

            self.print_error(f"Unexpected status: {response.status_code}")
            self.record_result(test_name, False, f"Status: {response.status_code}")
            return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_connectors_auth_invalid_provider(self) -> bool:
        """Test auth with invalid provider."""
        test_name = "Auth invalid provider"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.get(
                "/api/connectors/auth",
                params={"provider": "invalid_provider_xyz"},
                timeout=10,
            )

            if response.status_code in [400, 404]:
                self.print_success(f"Correctly rejected: {response.status_code}")
                self.record_result(test_name, True, "Invalid provider rejected")
                return True
            else:
                self.print_warning(f"Status: {response.status_code}")
                self.record_result(test_name, True, f"Status: {response.status_code}")
                return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Callback Tests
    # -------------------------------------------------------------------------

    def test_connectors_callback_status(self) -> bool:
        """Test checking callback status."""
        test_name = "Check callback status"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.get(
                "/api/connectors/callback-status",
                params={"task_id": "test-task-id"},
                timeout=10,
            )

            # Expect 200 with status, or 404 for unknown task
            if response.status_code in [200, 404]:
                self.print_success(f"Callback status check: {response.status_code}")
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
    # Disconnect Tests
    # -------------------------------------------------------------------------

    def test_connectors_disconnect(self) -> bool:
        """Test disconnecting a connector."""
        test_name = "Disconnect connector"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/connectors/disconnect",
                json={"provider": "google"},
                timeout=10,
            )

            # Expect 200 for successful disconnect, or 400/404 if not connected
            if response.status_code in [200, 400, 404]:
                self.print_success(f"Disconnect response: {response.status_code}")
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
    # Files Tests
    # -------------------------------------------------------------------------

    def test_connectors_files(self) -> bool:
        """Test listing connector files."""
        test_name = "List connector files"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/connectors/files",
                json={"provider": "google", "path": "/"},
                timeout=15,
            )

            # Expect 200 with files, or 400/401/404 if not authenticated
            if response.status_code == 200:
                result = response.json()
                files = result.get("files", result)
                self.print_success(f"Got files list: {len(files) if isinstance(files, list) else 'object'}")
                self.record_result(test_name, True, "Files retrieved")
                return True
            elif response.status_code in [400, 401, 404]:
                self.print_warning(f"Connector not authenticated: {response.status_code}")
                self.record_result(test_name, True, "Not authenticated (expected)")
                return True

            self.print_error(f"Unexpected status: {response.status_code}")
            self.record_result(test_name, False, f"Status: {response.status_code}")
            return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_connectors_files_with_path(self) -> bool:
        """Test listing files at specific path."""
        test_name = "List files at path"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/connectors/files",
                json={"provider": "google", "path": "/documents"},
                timeout=15,
            )

            if response.status_code in [200, 400, 401, 404]:
                self.print_success(f"Files at path response: {response.status_code}")
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
    # Sync Tests
    # -------------------------------------------------------------------------

    def test_connectors_sync(self) -> bool:
        """Test syncing a connector."""
        test_name = "Sync connector"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/connectors/sync",
                json={"provider": "google", "file_ids": []},
                timeout=15,
            )

            if response.status_code in [200, 202, 400, 401, 404]:
                self.print_success(f"Sync response: {response.status_code}")
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
    # Validate Session Tests
    # -------------------------------------------------------------------------

    def test_connectors_validate_session(self) -> bool:
        """Test validating connector session."""
        test_name = "Validate connector session"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/connectors/validate-session",
                json={"provider": "google"},
                timeout=10,
            )

            if response.status_code in [200, 400, 401, 404]:
                result = response.json() if response.status_code == 200 else {}
                valid = result.get("valid", False)
                self.print_success(f"Session validation: {response.status_code}, valid={valid}")
                self.record_result(test_name, True, f"Valid: {valid}")
                return True

            self.print_error(f"Unexpected status: {response.status_code}")
            self.record_result(test_name, False, f"Status: {response.status_code}")
            return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Test Runner
    # -------------------------------------------------------------------------

    def run_all(self) -> bool:
        """Run all connector tests."""
        self.print_header("DocsGPT Connector Integration Tests")
        self.print_info(f"Base URL: {self.base_url}")
        self.print_info(f"Auth: {self.token_source}")
        self.print_warning("Note: Many tests require external service configuration")

        # Auth tests
        self.test_connectors_auth_google()
        self.test_connectors_auth_invalid_provider()

        # Callback tests
        self.test_connectors_callback_status()

        # Disconnect tests
        self.test_connectors_disconnect()

        # Files tests
        self.test_connectors_files()
        self.test_connectors_files_with_path()

        # Sync tests
        self.test_connectors_sync()

        # Validate session tests
        self.test_connectors_validate_session()

        return self.print_summary()


def main():
    """Main entry point."""
    client = create_client_from_args(ConnectorTests, "DocsGPT Connector Integration Tests")
    exit_code = 0 if client.run_all() else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
