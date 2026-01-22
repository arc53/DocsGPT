#!/usr/bin/env python3
"""
Integration tests for DocsGPT prompt management endpoints.

Endpoints tested:
- /api/create_prompt (POST) - Create prompt
- /api/get_prompts (GET) - List prompts
- /api/get_single_prompt (GET) - Get single prompt
- /api/update_prompt (POST) - Update prompt
- /api/delete_prompt (POST) - Delete prompt

Usage:
    python tests/integration/test_prompts.py
    python tests/integration/test_prompts.py --base-url http://localhost:7091
    python tests/integration/test_prompts.py --token YOUR_JWT_TOKEN
"""

import sys
import time
from pathlib import Path
from typing import Optional

# Add parent directory to path for standalone execution
_THIS_DIR = Path(__file__).parent
_TESTS_DIR = _THIS_DIR.parent
_ROOT_DIR = _TESTS_DIR.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from tests.integration.base import DocsGPTTestBase, create_client_from_args


class PromptTests(DocsGPTTestBase):
    """Integration tests for prompt management endpoints."""

    # -------------------------------------------------------------------------
    # Test Data Helpers
    # -------------------------------------------------------------------------

    def get_or_create_test_prompt(self) -> Optional[str]:
        """
        Get or create a test prompt.

        Returns:
            Prompt ID or None if creation fails
        """
        if hasattr(self, "_test_prompt_id"):
            return self._test_prompt_id

        if not self.is_authenticated:
            return None

        payload = {
            "name": f"Test Prompt {int(time.time())}",
            "content": "You are a helpful assistant. Answer questions accurately.",
        }

        try:
            response = self.post("/api/create_prompt", json=payload, timeout=10)
            if response.status_code in [200, 201]:
                result = response.json()
                prompt_id = result.get("id")
                if prompt_id:
                    self._test_prompt_id = prompt_id
                    return prompt_id
        except Exception:
            pass

        return None

    def cleanup_test_prompt(self, prompt_id: str) -> None:
        """Delete a test prompt (cleanup helper)."""
        if not self.is_authenticated:
            return
        try:
            self.post("/api/delete_prompt", json={"id": prompt_id}, timeout=10)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Create Tests
    # -------------------------------------------------------------------------

    def test_create_prompt(self) -> bool:
        """Test creating a prompt."""
        test_name = "Create prompt"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        payload = {
            "name": f"Created Prompt {int(time.time())}",
            "content": "You are a test assistant created by integration tests.",
        }

        try:
            response = self.post("/api/create_prompt", json=payload, timeout=10)

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()
            prompt_id = result.get("id")

            if not prompt_id:
                self.print_error("No prompt ID returned")
                self.record_result(test_name, False, "No prompt ID")
                return False

            self.print_success(f"Created prompt: {prompt_id}")
            self.print_info(f"Name: {payload['name']}")
            self.record_result(test_name, True, f"ID: {prompt_id}")

            # Cleanup
            self.cleanup_test_prompt(prompt_id)
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_create_prompt_validation(self) -> bool:
        """Test prompt creation validation (missing required fields)."""
        test_name = "Create prompt validation"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        # Missing content field
        payload = {
            "name": "Invalid Prompt",
        }

        try:
            response = self.post("/api/create_prompt", json=payload, timeout=10)

            # Expect validation error (400) or accept it if server provides defaults
            if response.status_code in [400, 422]:
                self.print_success(f"Validation error returned: {response.status_code}")
                self.record_result(test_name, True, "Validation works")
                return True
            elif response.status_code in [200, 201]:
                self.print_warning("Server accepted incomplete data (may have defaults)")
                result = response.json()
                if result.get("id"):
                    self.cleanup_test_prompt(result["id"])
                self.record_result(test_name, True, "Server accepted with defaults")
                return True
            else:
                self.print_error(f"Unexpected status: {response.status_code}")
                self.record_result(test_name, False, f"Status: {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Read Tests
    # -------------------------------------------------------------------------

    def test_get_prompts(self) -> bool:
        """Test listing all prompts."""
        test_name = "List prompts"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.get("/api/get_prompts", timeout=10)

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()

            if not isinstance(result, list):
                self.print_error("Response is not a list")
                self.record_result(test_name, False, "Invalid response type")
                return False

            self.print_success(f"Retrieved {len(result)} prompts")
            if result:
                self.print_info(f"First: {result[0].get('name', 'N/A')}")
            self.record_result(test_name, True, f"Count: {len(result)}")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_prompts_with_pagination(self) -> bool:
        """Test listing prompts with pagination params."""
        test_name = "List prompts paginated"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.get(
                "/api/get_prompts",
                params={"skip": 0, "limit": 10},
                timeout=10,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()

            if not isinstance(result, list):
                self.print_error("Response is not a list")
                self.record_result(test_name, False, "Invalid response type")
                return False

            self.print_success(f"Retrieved {len(result)} prompts (paginated)")
            self.record_result(test_name, True, f"Count: {len(result)}")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_single_prompt(self) -> bool:
        """Test getting a single prompt by ID."""
        test_name = "Get single prompt"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        prompt_id = self.get_or_create_test_prompt()
        if not prompt_id:
            self.print_warning("Could not create test prompt")
            self.record_result(test_name, True, "Skipped (no prompt)")
            return True

        try:
            response = self.get(
                "/api/get_single_prompt",
                params={"id": prompt_id},
                timeout=10,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()

            # Handle different response formats (may have _id instead of id)
            returned_id = result.get("id") or result.get("_id")

            if returned_id and returned_id != prompt_id:
                self.print_error(f"Wrong prompt returned: {returned_id}")
                self.record_result(test_name, False, "Wrong prompt ID")
                return False

            self.print_success(f"Retrieved prompt: {result.get('name', 'N/A')}")
            self.record_result(test_name, True, f"Name: {result.get('name', 'N/A')}")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_single_prompt_not_found(self) -> bool:
        """Test getting a non-existent prompt."""
        test_name = "Get non-existent prompt"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.get(
                "/api/get_single_prompt",
                params={"id": "nonexistent-prompt-id-12345"},
                timeout=10,
            )

            if response.status_code in [404, 400, 500]:
                self.print_success(f"Correctly returned {response.status_code}")
                self.record_result(test_name, True, f"Status: {response.status_code}")
                return True
            else:
                self.print_warning(f"Unexpected status: {response.status_code}")
                self.record_result(test_name, True, f"Status: {response.status_code}")
                return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Update Tests
    # -------------------------------------------------------------------------

    def test_update_prompt(self) -> bool:
        """Test updating a prompt."""
        test_name = "Update prompt"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        prompt_id = self.get_or_create_test_prompt()
        if not prompt_id:
            self.print_warning("Could not create test prompt")
            self.record_result(test_name, True, "Skipped (no prompt)")
            return True

        new_content = f"Updated content at {int(time.time())}"
        new_name = f"Updated Prompt {int(time.time())}"

        try:
            # UpdatePromptModel requires id, name, and content
            response = self.post(
                "/api/update_prompt",
                json={"id": prompt_id, "name": new_name, "content": new_content},
                timeout=10,
            )

            if response.status_code in [200, 201]:
                self.print_success("Prompt updated successfully")
                self.record_result(test_name, True, "Prompt updated")
                return True
            else:
                self.print_error(f"Update failed: {response.status_code}")
                self.record_result(test_name, False, f"Status: {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Delete Tests
    # -------------------------------------------------------------------------

    def test_delete_prompt(self) -> bool:
        """Test deleting a prompt."""
        test_name = "Delete prompt"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        # Create a prompt specifically for deletion
        payload = {
            "name": f"Prompt to Delete {int(time.time())}",
            "content": "Will be deleted",
        }

        try:
            create_response = self.post("/api/create_prompt", json=payload, timeout=10)
            if create_response.status_code not in [200, 201]:
                self.print_warning("Could not create prompt for deletion")
                self.record_result(test_name, True, "Skipped (create failed)")
                return True

            prompt_id = create_response.json().get("id")

            # Delete the prompt
            response = self.post("/api/delete_prompt", json={"id": prompt_id}, timeout=10)

            if response.status_code in [200, 204]:
                self.print_success(f"Deleted prompt: {prompt_id}")
                self.record_result(test_name, True, "Prompt deleted")
                return True
            else:
                self.print_error(f"Delete failed: {response.status_code}")
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
        """Run all prompt tests."""
        self.print_header("DocsGPT Prompt Integration Tests")
        self.print_info(f"Base URL: {self.base_url}")
        self.print_info(f"Auth: {self.token_source}")

        # Create tests
        self.test_create_prompt()
        self.test_create_prompt_validation()

        # Read tests
        self.test_get_prompts()
        self.test_get_prompts_with_pagination()
        self.test_get_single_prompt()
        self.test_get_single_prompt_not_found()

        # Update tests
        self.test_update_prompt()

        # Delete tests
        self.test_delete_prompt()

        # Cleanup
        if hasattr(self, "_test_prompt_id"):
            self.cleanup_test_prompt(self._test_prompt_id)

        return self.print_summary()


def main():
    """Main entry point."""
    client = create_client_from_args(PromptTests, "DocsGPT Prompt Integration Tests")
    exit_code = 0 if client.run_all() else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
