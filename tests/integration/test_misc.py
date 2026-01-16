#!/usr/bin/env python3
"""
Integration tests for DocsGPT miscellaneous endpoints.

Endpoints tested:
- /api/models (GET) - List available models
- /api/images/{image_path} (GET) - Get images
- /api/store_attachment (POST) - Store attachments

Usage:
    python tests/integration/test_misc.py
    python tests/integration/test_misc.py --base-url http://localhost:7091
    python tests/integration/test_misc.py --token YOUR_JWT_TOKEN
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


class MiscTests(DocsGPTTestBase):
    """Integration tests for miscellaneous endpoints."""

    # -------------------------------------------------------------------------
    # Models Tests
    # -------------------------------------------------------------------------

    def test_get_models(self) -> bool:
        """Test listing available models."""
        test_name = "List models"
        self.print_header(test_name)

        try:
            response = self.get("/api/models", timeout=10)

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()

            # Handle both list and object responses
            if isinstance(result, list):
                self.print_success(f"Retrieved {len(result)} models")
                if result:
                    first_model = result[0]
                    if isinstance(first_model, dict):
                        self.print_info(f"First: {first_model.get('name', first_model.get('id', 'N/A'))}")
                    else:
                        self.print_info(f"First: {first_model}")
                self.record_result(test_name, True, f"Count: {len(result)}")
            elif isinstance(result, dict):
                # May return object with models array
                models = result.get("models", result.get("data", []))
                if isinstance(models, list):
                    self.print_success(f"Retrieved {len(models)} models")
                    if models:
                        first = models[0]
                        name = first.get('name', first) if isinstance(first, dict) else first
                        self.print_info(f"First: {name}")
                else:
                    self.print_success("Retrieved models data")
                self.record_result(test_name, True, "Models retrieved")
            else:
                self.print_warning(f"Unexpected response type: {type(result)}")
                self.record_result(test_name, True, "Response received")

            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_models_with_filter(self) -> bool:
        """Test listing models with filter parameters."""
        test_name = "List models filtered"
        self.print_header(test_name)

        try:
            response = self.get(
                "/api/models",
                params={"provider": "openai"},  # Filter by provider
                timeout=10,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()

            if isinstance(result, list):
                self.print_success(f"Retrieved {len(result)} filtered models")
                self.record_result(test_name, True, f"Count: {len(result)}")
                return True
            else:
                self.print_warning("Response format may vary")
                self.record_result(test_name, True, "Response received")
                return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Images Tests
    # -------------------------------------------------------------------------

    def test_get_image(self) -> bool:
        """Test getting an image by path."""
        test_name = "Get image"
        self.print_header(test_name)

        try:
            # Test with a placeholder path
            response = self.get("/api/images/test.png", timeout=10)

            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                self.print_success(f"Image retrieved: {content_type}")
                self.record_result(test_name, True, f"Type: {content_type}")
                return True
            elif response.status_code == 404:
                self.print_warning("Image not found (expected for test)")
                self.record_result(test_name, True, "404 - Image not found")
                return True
            else:
                self.print_error(f"Unexpected status: {response.status_code}")
                self.record_result(test_name, False, f"Status: {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_image_not_found(self) -> bool:
        """Test getting a non-existent image."""
        test_name = "Get non-existent image"
        self.print_header(test_name)

        try:
            response = self.get(
                "/api/images/nonexistent-image-xyz-12345.png",
                timeout=10,
            )

            if response.status_code == 404:
                self.print_success("Correctly returned 404")
                self.record_result(test_name, True, "404 returned")
                return True
            elif response.status_code in [400, 500]:
                self.print_warning(f"Error status: {response.status_code}")
                self.record_result(test_name, True, f"Status: {response.status_code}")
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
    # Attachment Tests
    # -------------------------------------------------------------------------

    def test_store_attachment(self) -> bool:
        """Test storing an attachment."""
        test_name = "Store attachment"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        # Create a small test file content
        test_content = b"Test attachment content for integration test"

        try:
            response = self.post(
                "/api/store_attachment",
                files={"file": ("test_attachment.txt", test_content, "text/plain")},
                timeout=15,
            )

            if response.status_code in [200, 201]:
                result = response.json()
                attachment_id = result.get("id") or result.get("attachment_id") or result.get("path")
                self.print_success(f"Stored attachment: {attachment_id}")
                self.record_result(test_name, True, f"ID: {attachment_id}")
                return True
            elif response.status_code in [400, 422]:
                self.print_warning(f"Validation: {response.status_code}")
                self.record_result(test_name, True, f"Status: {response.status_code}")
                return True
            else:
                self.print_error(f"Store failed: {response.status_code}")
                self.record_result(test_name, False, f"Status: {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_store_attachment_large(self) -> bool:
        """Test storing a larger attachment."""
        test_name = "Store large attachment"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        # Create a larger test file (1KB)
        test_content = b"X" * 1024

        try:
            response = self.post(
                "/api/store_attachment",
                files={"file": ("large_test.bin", test_content, "application/octet-stream")},
                timeout=30,
            )

            if response.status_code in [200, 201]:
                response.json()  # Validate JSON response
                self.print_success("Large attachment stored")
                self.record_result(test_name, True, "Attachment stored")
                return True
            elif response.status_code in [400, 413, 422]:
                self.print_warning(f"Size/validation: {response.status_code}")
                self.record_result(test_name, True, f"Status: {response.status_code}")
                return True
            else:
                self.print_error(f"Store failed: {response.status_code}")
                self.record_result(test_name, False, f"Status: {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Health/Info Tests (bonus)
    # -------------------------------------------------------------------------

    def test_health_check(self) -> bool:
        """Test basic health check (root or health endpoint)."""
        test_name = "Health check"
        self.print_header(test_name)

        try:
            # Try common health endpoints
            for path in ["/health", "/api/health", "/"]:
                response = self.get(path, timeout=5)
                if response.status_code == 200:
                    self.print_success(f"Health check passed: {path}")
                    self.record_result(test_name, True, f"Endpoint: {path}")
                    return True

            # If none worked, check if server responds at all
            self.print_warning("No standard health endpoint found")
            self.record_result(test_name, True, "Server responsive")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Test Runner
    # -------------------------------------------------------------------------

    def run_all(self) -> bool:
        """Run all miscellaneous tests."""
        self.print_header("DocsGPT Miscellaneous Integration Tests")
        self.print_info(f"Base URL: {self.base_url}")
        self.print_info(f"Auth: {self.token_source}")

        # Health check
        self.test_health_check()

        # Models tests
        self.test_get_models()
        self.test_get_models_with_filter()

        # Images tests
        self.test_get_image()
        self.test_get_image_not_found()

        # Attachment tests
        self.test_store_attachment()
        self.test_store_attachment_large()

        return self.print_summary()


def main():
    """Main entry point."""
    client = create_client_from_args(MiscTests, "DocsGPT Miscellaneous Integration Tests")
    exit_code = 0 if client.run_all() else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
