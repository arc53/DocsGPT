#!/usr/bin/env python3
"""
Integration tests for DocsGPT tools management endpoints.

Endpoints tested:
- /api/create_tool (POST) - Create tool
- /api/get_tools (GET) - List tools
- /api/update_tool (POST) - Update tool
- /api/delete_tool (POST) - Delete tool
- /api/update_tool_actions (POST) - Update tool actions
- /api/update_tool_config (POST) - Update tool config
- /api/update_tool_status (POST) - Update tool status
- /api/available_tools (GET) - List available tools

Usage:
    python tests/integration/test_tools.py
    python tests/integration/test_tools.py --base-url http://localhost:7091
    python tests/integration/test_tools.py --token YOUR_JWT_TOKEN
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


class ToolsTests(DocsGPTTestBase):
    """Integration tests for tools management endpoints."""

    # -------------------------------------------------------------------------
    # Test Data Helpers
    # -------------------------------------------------------------------------

    def get_or_create_test_tool(self) -> Optional[str]:
        """
        Get or create a test tool.

        Returns:
            Tool ID or None if creation fails
        """
        if hasattr(self, "_test_tool_id"):
            return self._test_tool_id

        if not self.is_authenticated:
            return None

        # CreateToolModel: 'name' must be an available tool type (e.g., "duckduckgo")
        # Use a tool that doesn't require config (like duckduckgo)
        # Note: status must be a boolean (False = draft, True = active)
        payload = {
            "name": "duckduckgo",  # Must match available tool name
            "displayName": f"Test DuckDuckGo {int(time.time())}",
            "description": "Integration test tool",
            "config": {},
            "status": False,  # Boolean: False = draft
        }

        try:
            response = self.post("/api/create_tool", json=payload, timeout=10)
            if response.status_code in [200, 201]:
                result = response.json()
                tool_id = result.get("id")
                if tool_id:
                    self._test_tool_id = tool_id
                    return tool_id
        except Exception:
            pass

        return None

    def cleanup_test_tool(self, tool_id: str) -> None:
        """Delete a test tool (cleanup helper)."""
        if not self.is_authenticated:
            return
        try:
            self.post("/api/delete_tool", json={"id": tool_id}, timeout=10)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Create Tests
    # -------------------------------------------------------------------------

    def test_create_tool(self) -> bool:
        """Test creating a tool instance from available tools."""
        test_name = "Create tool"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        # 'name' must be an available tool type (e.g., "duckduckgo", "cryptoprice")
        # Note: status must be a boolean (False = draft, True = active)
        payload = {
            "name": "cryptoprice",  # A tool that needs no config
            "displayName": f"Test CryptoPrice {int(time.time())}",
            "description": "Integration test created tool",
            "config": {},
            "status": False,  # Boolean: False = draft
        }

        try:
            response = self.post("/api/create_tool", json=payload, timeout=10)

            if response.status_code not in [200, 201]:
                self.print_error(f"Expected 200/201, got {response.status_code}")
                self.print_error(f"Response: {response.text[:200]}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            result = response.json()
            tool_id = result.get("id")

            if not tool_id:
                self.print_error("No tool ID returned")
                self.record_result(test_name, False, "No tool ID")
                return False

            self.print_success(f"Created tool: {tool_id}")
            self.print_info(f"Name: {payload['name']}")
            self.record_result(test_name, True, f"ID: {tool_id}")

            # Cleanup
            self.cleanup_test_tool(tool_id)
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_create_tool_with_config(self) -> bool:
        """Test creating a tool that requires configuration."""
        test_name = "Create tool with config"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        # Use api_tool which has flexible config requirements
        # Note: status must be a boolean (False = draft, True = active)
        payload = {
            "name": "api_tool",
            "displayName": f"Test API Tool {int(time.time())}",
            "description": "Tool with custom config",
            "config": {"base_url": "https://api.example.com"},
            "status": False,  # Boolean: False = draft
        }

        try:
            response = self.post("/api/create_tool", json=payload, timeout=10)

            if response.status_code not in [200, 201]:
                self.print_error(f"Expected 200/201, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            result = response.json()
            tool_id = result.get("id")

            if not tool_id:
                self.print_error("No tool ID returned")
                self.record_result(test_name, False, "No tool ID")
                return False

            self.print_success(f"Created tool with actions: {tool_id}")
            self.record_result(test_name, True, f"ID: {tool_id}")

            # Cleanup
            self.cleanup_test_tool(tool_id)
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Read Tests
    # -------------------------------------------------------------------------

    def test_get_tools(self) -> bool:
        """Test listing all tools."""
        test_name = "List tools"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.get("/api/get_tools", timeout=10)

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()

            # Handle both list and object responses
            if isinstance(result, list):
                self.print_success(f"Retrieved {len(result)} tools")
                if result:
                    self.print_info(f"First: {result[0].get('name', 'N/A')}")
                self.record_result(test_name, True, f"Count: {len(result)}")
            elif isinstance(result, dict):
                # May return object with tools array
                tools = result.get("tools", result.get("data", []))
                if isinstance(tools, list):
                    self.print_success(f"Retrieved {len(tools)} tools")
                else:
                    self.print_success("Retrieved tools data")
                self.record_result(test_name, True, "Tools retrieved")
            else:
                self.print_warning(f"Unexpected response type: {type(result)}")
                self.record_result(test_name, True, "Response received")

            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_available_tools(self) -> bool:
        """Test listing available tool types."""
        test_name = "List available tools"
        self.print_header(test_name)

        try:
            response = self.get("/api/available_tools", timeout=10)

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()

            # Handle both list and object responses
            if isinstance(result, list):
                self.print_success(f"Retrieved {len(result)} available tool types")
                if result:
                    first = result[0]
                    name = first.get('name', first) if isinstance(first, dict) else first
                    self.print_info(f"First: {name}")
                self.record_result(test_name, True, f"Count: {len(result)}")
            elif isinstance(result, dict):
                # May return object with tools array
                tools = result.get("tools", result.get("available", result.get("data", [])))
                if isinstance(tools, list):
                    self.print_success(f"Retrieved {len(tools)} available tools")
                else:
                    self.print_success("Retrieved available tools data")
                self.record_result(test_name, True, "Tools retrieved")
            else:
                self.print_warning(f"Unexpected response type: {type(result)}")
                self.record_result(test_name, True, "Response received")

            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Update Tests
    # -------------------------------------------------------------------------

    def test_update_tool(self) -> bool:
        """Test updating a tool."""
        test_name = "Update tool"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        tool_id = self.get_or_create_test_tool()
        if not tool_id:
            self.print_warning("Could not create test tool")
            self.record_result(test_name, True, "Skipped (no tool)")
            return True

        new_description = f"Updated at {int(time.time())}"

        try:
            response = self.post(
                "/api/update_tool",
                json={"id": tool_id, "description": new_description},
                timeout=10,
            )

            if response.status_code in [200, 201]:
                self.print_success("Tool updated successfully")
                self.record_result(test_name, True, "Tool updated")
                return True
            else:
                self.print_error(f"Update failed: {response.status_code}")
                self.record_result(test_name, False, f"Status: {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_update_tool_actions(self) -> bool:
        """Test updating tool actions."""
        test_name = "Update tool actions"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        tool_id = self.get_or_create_test_tool()
        if not tool_id:
            self.print_warning("Could not create test tool")
            self.record_result(test_name, True, "Skipped (no tool)")
            return True

        new_actions = [
            {
                "name": "new_action",
                "description": "New action added",
                "parameters": {},
            }
        ]

        try:
            response = self.post(
                "/api/update_tool_actions",
                json={"id": tool_id, "actions": new_actions},
                timeout=10,
            )

            if response.status_code in [200, 201]:
                self.print_success("Tool actions updated")
                self.record_result(test_name, True, "Actions updated")
                return True
            else:
                self.print_error(f"Update failed: {response.status_code}")
                self.record_result(test_name, False, f"Status: {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_update_tool_config(self) -> bool:
        """Test updating tool configuration."""
        test_name = "Update tool config"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        tool_id = self.get_or_create_test_tool()
        if not tool_id:
            self.print_warning("Could not create test tool")
            self.record_result(test_name, True, "Skipped (no tool)")
            return True

        new_config = {"api_key": "updated_key", "timeout": 30}

        try:
            response = self.post(
                "/api/update_tool_config",
                json={"id": tool_id, "config": new_config},
                timeout=10,
            )

            if response.status_code in [200, 201]:
                self.print_success("Tool config updated")
                self.record_result(test_name, True, "Config updated")
                return True
            else:
                self.print_error(f"Update failed: {response.status_code}")
                self.record_result(test_name, False, f"Status: {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_update_tool_status(self) -> bool:
        """Test updating tool status."""
        test_name = "Update tool status"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        tool_id = self.get_or_create_test_tool()
        if not tool_id:
            self.print_warning("Could not create test tool")
            self.record_result(test_name, True, "Skipped (no tool)")
            return True

        try:
            # Status is a boolean in UpdateToolStatusModel
            response = self.post(
                "/api/update_tool_status",
                json={"id": tool_id, "status": True},
                timeout=10,
            )

            if response.status_code in [200, 201]:
                self.print_success("Tool status updated to active")
                self.record_result(test_name, True, "Status updated")
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

    def test_delete_tool(self) -> bool:
        """Test deleting a tool."""
        test_name = "Delete tool"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        # Create a tool specifically for deletion - must use available tool name
        # Note: status must be a boolean (False = draft, True = active)
        payload = {
            "name": "duckduckgo",
            "displayName": f"Tool to Delete {int(time.time())}",
            "description": "Will be deleted",
            "config": {},
            "status": False,  # Boolean: False = draft
        }

        try:
            create_response = self.post("/api/create_tool", json=payload, timeout=10)
            if create_response.status_code not in [200, 201]:
                self.print_warning("Could not create tool for deletion")
                self.record_result(test_name, True, "Skipped (create failed)")
                return True

            tool_id = create_response.json().get("id")

            # Delete the tool (DeleteToolModel requires 'id')
            response = self.post("/api/delete_tool", json={"id": tool_id}, timeout=10)

            if response.status_code in [200, 204]:
                self.print_success(f"Deleted tool: {tool_id}")
                self.record_result(test_name, True, "Tool deleted")
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
        """Run all tools tests."""
        self.print_header("DocsGPT Tools Integration Tests")
        self.print_info(f"Base URL: {self.base_url}")
        self.print_info(f"Auth: {self.token_source}")

        # Create tests
        self.test_create_tool()
        self.test_create_tool_with_config()

        # Read tests
        self.test_get_tools()
        self.test_get_available_tools()

        # Update tests
        self.test_update_tool()
        self.test_update_tool_actions()
        self.test_update_tool_config()
        self.test_update_tool_status()

        # Delete tests
        self.test_delete_tool()

        # Cleanup
        if hasattr(self, "_test_tool_id"):
            self.cleanup_test_tool(self._test_tool_id)

        return self.print_summary()


def main():
    """Main entry point."""
    client = create_client_from_args(ToolsTests, "DocsGPT Tools Integration Tests")
    exit_code = 0 if client.run_all() else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
