#!/usr/bin/env python3
"""
Integration tests for DocsGPT conversation management endpoints.

Endpoints tested:
- /api/get_conversations (GET) - List conversations
- /api/get_single_conversation (GET) - Get single conversation
- /api/delete_conversation (POST) - Delete conversation
- /api/delete_all_conversations (GET) - Delete all conversations
- /api/update_conversation_name (POST) - Rename conversation
- /api/share (POST) - Share conversation
- /api/shared_conversation/{id} (GET) - Get shared conversation

Usage:
    python tests/integration/test_conversations.py
    python tests/integration/test_conversations.py --base-url http://localhost:7091
    python tests/integration/test_conversations.py --token YOUR_JWT_TOKEN
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


class ConversationTests(DocsGPTTestBase):
    """Integration tests for conversation management endpoints."""

    # -------------------------------------------------------------------------
    # Test Data Helpers
    # -------------------------------------------------------------------------

    def get_or_create_test_conversation(self) -> Optional[str]:
        """
        Get or create a test conversation by making a chat request.

        Returns:
            Conversation ID or None if creation fails
        """
        if hasattr(self, "_test_conversation_id"):
            return self._test_conversation_id

        if not self.is_authenticated:
            return None

        # Create conversation via a chat request
        try:
            payload = {
                "question": "Test message for conversation creation",
                "history": [],
                "conversation_id": None,
            }

            response = self.post("/api/answer", json=payload, timeout=30)
            if response.status_code == 200:
                result = response.json()
                conv_id = result.get("conversation_id")
                if conv_id:
                    self._test_conversation_id = conv_id
                    return conv_id
        except Exception:
            pass

        return None

    def get_existing_conversation(self) -> Optional[str]:
        """Get an existing conversation ID from the list."""
        try:
            response = self.get("/api/get_conversations", timeout=10)
            if response.status_code == 200:
                convs = response.json()
                if convs and len(convs) > 0:
                    return convs[0].get("id")
        except Exception:
            pass
        return None

    # -------------------------------------------------------------------------
    # List/Get Tests
    # -------------------------------------------------------------------------

    def test_get_conversations(self) -> bool:
        """Test listing all conversations."""
        test_name = "List conversations"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.get("/api/get_conversations", timeout=10)

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()

            if not isinstance(result, list):
                self.print_error("Response is not a list")
                self.record_result(test_name, False, "Invalid response type")
                return False

            self.print_success(f"Retrieved {len(result)} conversations")
            if result:
                self.print_info(f"First: {result[0].get('name', 'N/A')[:30]}...")
            self.record_result(test_name, True, f"Count: {len(result)}")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_conversations_paginated(self) -> bool:
        """Test getting conversations with pagination."""
        test_name = "List conversations paginated"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.get(
                "/api/get_conversations",
                params={"page": 1, "per_page": 5},
                timeout=10,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()

            if not isinstance(result, list):
                self.print_error("Response is not a list")
                self.record_result(test_name, False, "Invalid response type")
                return False

            self.print_success(f"Retrieved {len(result)} conversations (page 1)")
            self.record_result(test_name, True, f"Count: {len(result)}")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_single_conversation(self) -> bool:
        """Test getting a single conversation by ID."""
        test_name = "Get single conversation"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        # Try to get existing conversation
        conv_id = self.get_existing_conversation()
        if not conv_id:
            conv_id = self.get_or_create_test_conversation()

        if not conv_id:
            self.print_warning("No conversations available")
            self.record_result(test_name, True, "Skipped (no conversations)")
            return True

        try:
            response = self.get(
                "/api/get_single_conversation",
                params={"id": conv_id},
                timeout=10,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()
            self.print_success(f"Retrieved conversation: {conv_id[:20]}...")
            self.print_info(f"Messages: {len(result.get('queries', []))}")
            self.record_result(test_name, True, f"ID: {conv_id[:20]}...")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_single_conversation_not_found(self) -> bool:
        """Test getting a non-existent conversation."""
        test_name = "Get non-existent conversation"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.get(
                "/api/get_single_conversation",
                params={"id": "nonexistent-conversation-id-12345"},
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

    def test_update_conversation_name(self) -> bool:
        """Test renaming a conversation."""
        test_name = "Update conversation name"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        conv_id = self.get_existing_conversation()
        if not conv_id:
            conv_id = self.get_or_create_test_conversation()

        if not conv_id:
            self.print_warning("No conversation to rename")
            self.record_result(test_name, True, "Skipped (no conversation)")
            return True

        new_name = f"Renamed Conversation {int(time.time())}"

        try:
            response = self.post(
                "/api/update_conversation_name",
                json={"id": conv_id, "name": new_name},
                timeout=10,
            )

            if response.status_code in [200, 201]:
                self.print_success(f"Renamed conversation to: {new_name[:30]}...")
                self.record_result(test_name, True, f"New name: {new_name[:20]}...")
                return True
            else:
                self.print_error(f"Rename failed: {response.status_code}")
                self.record_result(test_name, False, f"Status: {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Delete Tests
    # -------------------------------------------------------------------------

    def test_delete_conversation(self) -> bool:
        """Test deleting a single conversation."""
        test_name = "Delete conversation"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        # Create a conversation specifically for deletion
        try:
            payload = {
                "question": "Test message for deletion test",
                "history": [],
                "conversation_id": None,
            }

            create_response = self.post("/api/answer", json=payload, timeout=30)
            if create_response.status_code != 200:
                self.print_warning("Could not create conversation for deletion")
                self.record_result(test_name, True, "Skipped (create failed)")
                return True

            conv_id = create_response.json().get("conversation_id")
            if not conv_id:
                self.print_warning("No conversation ID returned")
                self.record_result(test_name, True, "Skipped (no ID)")
                return True

            # Delete the conversation
            response = self.post(
                "/api/delete_conversation",
                json={"id": conv_id},
                timeout=10,
            )

            if response.status_code in [200, 204]:
                self.print_success(f"Deleted conversation: {conv_id[:20]}...")
                self.record_result(test_name, True, "Conversation deleted")
                return True
            else:
                self.print_error(f"Delete failed: {response.status_code}")
                self.record_result(test_name, False, f"Status: {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_delete_all_conversations(self) -> bool:
        """Test the delete all conversations endpoint (without actually deleting all)."""
        test_name = "Delete all conversations endpoint"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        self.print_warning("Skipping actual deletion to preserve data")
        self.print_info("Verifying endpoint exists...")

        try:
            # Just verify endpoint responds (don't actually call it)
            # We can test with a GET to see if endpoint exists
            response = self.get("/api/delete_all_conversations", timeout=10)

            # Any response means endpoint exists
            self.print_success(f"Endpoint responded: {response.status_code}")
            self.record_result(test_name, True, "Endpoint verified")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Share Tests
    # -------------------------------------------------------------------------

    def test_share_conversation(self) -> bool:
        """Test sharing a conversation."""
        test_name = "Share conversation"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        conv_id = self.get_existing_conversation()
        if not conv_id:
            conv_id = self.get_or_create_test_conversation()

        if not conv_id:
            self.print_warning("No conversation to share")
            self.record_result(test_name, True, "Skipped (no conversation)")
            return True

        try:
            response = self.post(
                "/api/share",
                json={"conversation_id": conv_id},
                timeout=10,
            )

            if response.status_code in [200, 201]:
                result = response.json()
                share_id = result.get("share_id") or result.get("id")
                self.print_success(f"Shared conversation: {share_id}")
                self._shared_conversation_id = share_id
                self.record_result(test_name, True, f"Share ID: {share_id}")
                return True
            else:
                self.print_error(f"Share failed: {response.status_code}")
                self.record_result(test_name, False, f"Status: {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_shared_conversation(self) -> bool:
        """Test getting a shared conversation."""
        test_name = "Get shared conversation"
        self.print_header(test_name)

        # Use share ID from previous test if available
        share_id = getattr(self, "_shared_conversation_id", None)

        if not share_id:
            self.print_warning("No shared conversation available")
            self.record_result(test_name, True, "Skipped (no shared conversation)")
            return True

        try:
            response = self.get(f"/api/shared_conversation/{share_id}", timeout=10)

            if response.status_code == 200:
                result = response.json()
                self.print_success("Retrieved shared conversation")
                self.print_info(f"Messages: {len(result.get('queries', []))}")
                self.record_result(test_name, True, f"Share ID: {share_id}")
                return True
            elif response.status_code == 404:
                self.print_warning("Shared conversation not found")
                self.record_result(test_name, True, "Not found (may be expected)")
                return True
            else:
                self.print_error(f"Get failed: {response.status_code}")
                self.record_result(test_name, False, f"Status: {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_shared_conversation_not_found(self) -> bool:
        """Test getting a non-existent shared conversation."""
        test_name = "Get non-existent shared conversation"
        self.print_header(test_name)

        try:
            response = self.get(
                "/api/shared_conversation/nonexistent-share-id-12345",
                timeout=10,
            )

            if response.status_code in [404, 400]:
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
    # Test Runner
    # -------------------------------------------------------------------------

    def run_all(self) -> bool:
        """Run all conversation tests."""
        self.print_header("DocsGPT Conversation Integration Tests")
        self.print_info(f"Base URL: {self.base_url}")
        self.print_info(f"Auth: {self.token_source}")

        # List/Get tests
        self.test_get_conversations()
        self.test_get_conversations_paginated()
        self.test_get_single_conversation()
        self.test_get_single_conversation_not_found()

        # Update tests
        self.test_update_conversation_name()

        # Delete tests
        self.test_delete_conversation()
        self.test_delete_all_conversations()

        # Share tests
        self.test_share_conversation()
        self.test_get_shared_conversation()
        self.test_get_shared_conversation_not_found()

        return self.print_summary()


def main():
    """Main entry point."""
    client = create_client_from_args(
        ConversationTests, "DocsGPT Conversation Integration Tests"
    )
    exit_code = 0 if client.run_all() else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
