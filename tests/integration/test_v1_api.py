#!/usr/bin/env python3
"""
Integration tests for the /v1/ chat completions API (Phase 4).

Endpoints tested:
- /v1/chat/completions (POST) - Standard chat completions (streaming & non-streaming)
- /v1/models (GET) - List available agent models

Usage:
    python tests/integration/test_v1_api.py
    python tests/integration/test_v1_api.py --base-url http://localhost:7091
    python tests/integration/test_v1_api.py --token YOUR_JWT_TOKEN
"""

import json as json_module
import sys
import time
from pathlib import Path
from typing import Optional

import requests

# Add parent directory to path for standalone execution
_THIS_DIR = Path(__file__).parent
_TESTS_DIR = _THIS_DIR.parent
_ROOT_DIR = _TESTS_DIR.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from tests.integration.base import DocsGPTTestBase, create_client_from_args


class V1ApiTests(DocsGPTTestBase):
    """Integration tests for /v1/ chat completions API."""

    # -------------------------------------------------------------------------
    # Test Data Helpers
    # -------------------------------------------------------------------------

    def get_or_create_agent_key(self) -> Optional[str]:
        """Get or create a test agent and return its API key."""
        if hasattr(self, "_agent_key") and self._agent_key:
            return self._agent_key

        # Try both authenticated and unauthenticated creation.
        # Published agents need a source to get an API key.
        payload = {
            "name": f"V1 Test Agent {int(time.time())}",
            "description": "Integration test agent for v1 API tests",
            "prompt_id": "default",
            "chunks": 2,
            "retriever": "classic",
            "agent_type": "classic",
            "status": "published",
            "source": "default",
        }

        try:
            response = self.post("/api/create_agent", json=payload, timeout=10)
            if response.status_code in [200, 201]:
                result = response.json()
                api_key = result.get("key")
                self._agent_id = result.get("id")
                if api_key:
                    self._agent_key = api_key
                    self.print_info(f"Created test agent with key: {api_key[:8]}...")
                    return api_key
                else:
                    self.print_warning("Agent created but no API key returned")
            else:
                self.print_warning(f"Agent creation returned {response.status_code}: {response.text[:200]}")
        except Exception as e:
            self.print_error(f"Failed to create agent: {e}")

        return None

    def _v1_headers(self, api_key: str) -> dict:
        """Build headers for v1 API requests."""
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # -------------------------------------------------------------------------
    # /v1/chat/completions — Auth Tests
    # -------------------------------------------------------------------------

    def test_no_auth_returns_401(self) -> bool:
        """Test that /v1/chat/completions without auth returns 401."""
        test_name = "v1 chat completions - no auth"
        self.print_header(f"Testing {test_name}")

        try:
            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
                headers={"Content-Type": "application/json"},
                timeout=10,
            )

            if response.status_code == 401:
                self.print_success("Correctly returned 401 for missing auth")
                self.record_result(test_name, True, "401 as expected")
                return True
            else:
                self.print_error(f"Expected 401, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False
        except Exception as e:
            self.print_error(f"Request failed: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_invalid_key_returns_error(self) -> bool:
        """Test that invalid API key returns error."""
        test_name = "v1 chat completions - invalid key"
        self.print_header(f"Testing {test_name}")

        try:
            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
                headers=self._v1_headers("invalid-key-12345"),
                timeout=30,
            )

            # Should return 400 or 500 (agent not found)
            if response.status_code in [400, 401, 500]:
                self.print_success(f"Correctly returned {response.status_code} for invalid key")
                self.record_result(test_name, True, f"Error as expected ({response.status_code})")
                return True
            else:
                self.print_error(f"Unexpected status: {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False
        except Exception as e:
            self.print_error(f"Request failed: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_missing_messages_returns_400(self) -> bool:
        """Test that missing messages field returns 400."""
        test_name = "v1 chat completions - missing messages"
        self.print_header(f"Testing {test_name}")

        api_key = self.get_or_create_agent_key()
        if not api_key:
            if not self.require_auth(test_name):
                return True
            self.record_result(test_name, True, "Skipped (no agent)")
            return True

        try:
            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json={"stream": False},
                headers=self._v1_headers(api_key),
                timeout=10,
            )

            if response.status_code == 400:
                self.print_success("Correctly returned 400 for missing messages")
                self.record_result(test_name, True, "400 as expected")
                return True
            else:
                self.print_error(f"Expected 400, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False
        except Exception as e:
            self.print_error(f"Request failed: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # /v1/chat/completions — Non-streaming
    # -------------------------------------------------------------------------

    def test_non_streaming_basic(self) -> bool:
        """Test basic non-streaming chat completion."""
        test_name = "v1 chat completions - non-streaming"
        self.print_header(f"Testing {test_name}")

        api_key = self.get_or_create_agent_key()
        if not api_key:
            if not self.require_auth(test_name):
                return True
            self.record_result(test_name, True, "Skipped (no agent)")
            return True

        try:
            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Say hello in one word."}],
                    "stream": False,
                },
                headers=self._v1_headers(api_key),
                timeout=60,
            )

            self.print_info(f"Status: {response.status_code}")

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.print_error(f"Response: {response.text[:300]}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            data = response.json()

            # Verify standard format
            checks = [
                ("id" in data, "has id"),
                (data.get("object") == "chat.completion", "object is chat.completion"),
                ("choices" in data, "has choices"),
                (len(data["choices"]) > 0, "choices not empty"),
                (data["choices"][0].get("message", {}).get("role") == "assistant", "role is assistant"),
                (data["choices"][0].get("message", {}).get("content") is not None, "has content"),
                (data["choices"][0].get("finish_reason") == "stop", "finish_reason is stop"),
                ("usage" in data, "has usage"),
            ]

            all_passed = True
            for check, label in checks:
                if check:
                    self.print_success(f"  {label}")
                else:
                    self.print_error(f"  {label}")
                    all_passed = False

            content = data["choices"][0]["message"]["content"]
            self.print_info(f"Response: {content[:100]}")

            # Check docsgpt extension
            if "docsgpt" in data:
                self.print_success("  has docsgpt extension")
                if "conversation_id" in data["docsgpt"]:
                    self.print_success(f"  conversation_id: {data['docsgpt']['conversation_id'][:8]}...")

            self.record_result(test_name, all_passed, "All checks passed" if all_passed else "Some checks failed")
            return all_passed

        except Exception as e:
            self.print_error(f"Error: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # /v1/chat/completions — Streaming
    # -------------------------------------------------------------------------

    def test_streaming_basic(self) -> bool:
        """Test basic streaming chat completion."""
        test_name = "v1 chat completions - streaming"
        self.print_header(f"Testing {test_name}")

        api_key = self.get_or_create_agent_key()
        if not api_key:
            if not self.require_auth(test_name):
                return True
            self.record_result(test_name, True, "Skipped (no agent)")
            return True

        try:
            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Say hi briefly."}],
                    "stream": True,
                },
                headers=self._v1_headers(api_key),
                stream=True,
                timeout=60,
            )

            self.print_info(f"Status: {response.status_code}")

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            chunks = []
            content_pieces = []
            got_done = False
            got_stop = False
            got_id = False

            for line in response.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8")
                if not line_str.startswith("data: "):
                    continue

                data_str = line_str[6:]
                if data_str.strip() == "[DONE]":
                    got_done = True
                    break

                try:
                    chunk = json_module.loads(data_str)
                    chunks.append(chunk)

                    # Standard chunks
                    if "choices" in chunk:
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta:
                            content_pieces.append(delta["content"])
                        if chunk["choices"][0].get("finish_reason") == "stop":
                            got_stop = True

                    # Extension chunks
                    if "docsgpt" in chunk:
                        ext = chunk["docsgpt"]
                        if ext.get("type") == "id":
                            got_id = True

                except json_module.JSONDecodeError:
                    pass

            full_content = "".join(content_pieces)

            checks = [
                (len(chunks) > 0, f"received {len(chunks)} chunks"),
                (len(content_pieces) > 0, f"got content: {full_content[:50]}..."),
                (got_stop, "got finish_reason=stop"),
                (got_done, "got [DONE] sentinel"),
            ]

            all_passed = True
            for check, label in checks:
                if check:
                    self.print_success(f"  {label}")
                else:
                    self.print_error(f"  {label}")
                    all_passed = False

            if got_id:
                self.print_success("  got conversation_id via docsgpt extension")

            self.record_result(test_name, all_passed, "All checks passed" if all_passed else "Some checks failed")
            return all_passed

        except Exception as e:
            self.print_error(f"Error: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # /v1/chat/completions — Multi-turn conversation
    # -------------------------------------------------------------------------

    def test_multi_turn_conversation(self) -> bool:
        """Test multi-turn conversation with history in messages."""
        test_name = "v1 chat completions - multi-turn"
        self.print_header(f"Testing {test_name}")

        api_key = self.get_or_create_agent_key()
        if not api_key:
            if not self.require_auth(test_name):
                return True
            self.record_result(test_name, True, "Skipped (no agent)")
            return True

        try:
            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "user", "content": "My name is TestBot."},
                        {"role": "assistant", "content": "Hello TestBot!"},
                        {"role": "user", "content": "What is my name?"},
                    ],
                    "stream": False,
                },
                headers=self._v1_headers(api_key),
                timeout=60,
            )

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            self.print_info(f"Response: {content[:150]}")

            # The response should reference "TestBot" from the history
            has_content = bool(content)
            self.print_success(f"  Got response with {len(content)} chars")
            self.record_result(test_name, has_content, "Multi-turn works")
            return has_content

        except Exception as e:
            self.print_error(f"Error: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # /v1/models
    # -------------------------------------------------------------------------

    def test_list_models(self) -> bool:
        """Test GET /v1/models endpoint."""
        test_name = "v1 models - list"
        self.print_header(f"Testing {test_name}")

        api_key = self.get_or_create_agent_key()
        if not api_key:
            if not self.require_auth(test_name):
                return True
            self.record_result(test_name, True, "Skipped (no agent)")
            return True

        try:
            response = requests.get(
                f"{self.base_url}/v1/models",
                headers=self._v1_headers(api_key),
                timeout=10,
            )

            self.print_info(f"Status: {response.status_code}")

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            data = response.json()

            checks = [
                (data.get("object") == "list", "object is list"),
                ("data" in data, "has data array"),
                (len(data.get("data", [])) > 0, f"has {len(data.get('data', []))} model(s)"),
            ]

            all_passed = True
            for check, label in checks:
                if check:
                    self.print_success(f"  {label}")
                else:
                    self.print_error(f"  {label}")
                    all_passed = False

            if data.get("data"):
                model = data["data"][0]
                model_checks = [
                    ("id" in model, "model has id"),
                    (model.get("object") == "model", "model object is 'model'"),
                    (model.get("owned_by") == "docsgpt", "owned_by is docsgpt"),
                ]
                for check, label in model_checks:
                    if check:
                        self.print_success(f"  {label}")
                    else:
                        self.print_error(f"  {label}")
                        all_passed = False

            self.record_result(test_name, all_passed, "All checks passed" if all_passed else "Some checks failed")
            return all_passed

        except Exception as e:
            self.print_error(f"Error: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_models_no_auth(self) -> bool:
        """Test that /v1/models without auth returns 401."""
        test_name = "v1 models - no auth"
        self.print_header(f"Testing {test_name}")

        try:
            response = requests.get(
                f"{self.base_url}/v1/models",
                timeout=10,
            )

            if response.status_code == 401:
                self.print_success("Correctly returned 401")
                self.record_result(test_name, True, "401 as expected")
                return True
            else:
                self.print_error(f"Expected 401, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False
        except Exception as e:
            self.print_error(f"Error: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Backward Compatibility — old endpoints still work
    # -------------------------------------------------------------------------

    def test_old_stream_endpoint_still_works(self) -> bool:
        """Verify the old /stream endpoint still works after v1 changes."""
        test_name = "Backward compat - /stream"
        self.print_header(f"Testing {test_name}")

        payload = {
            "question": "Say hello briefly.",
            "history": "[]",
            "isNoneDoc": True,
        }

        try:
            response = requests.post(
                f"{self.base_url}/stream",
                json=payload,
                headers=self.headers,
                stream=True,
                timeout=60,
            )

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            events = []
            got_end = False
            got_answer = False

            for line in response.iter_lines():
                if line:
                    line_str = line.decode("utf-8")
                    if line_str.startswith("data: "):
                        try:
                            data = json_module.loads(line_str[6:])
                            events.append(data)
                            if data.get("type") == "answer":
                                got_answer = True
                            if data.get("type") == "end":
                                got_end = True
                                break
                        except json_module.JSONDecodeError:
                            pass

            checks = [
                (len(events) > 0, f"received {len(events)} events"),
                (got_answer, "got answer event"),
                (got_end, "got end event"),
            ]

            all_passed = True
            for check, label in checks:
                if check:
                    self.print_success(f"  {label}")
                else:
                    self.print_error(f"  {label}")
                    all_passed = False

            self.record_result(test_name, all_passed, "Old endpoint works" if all_passed else "Regression")
            return all_passed

        except Exception as e:
            self.print_error(f"Error: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_old_answer_endpoint_still_works(self) -> bool:
        """Verify the old /api/answer endpoint still works."""
        test_name = "Backward compat - /api/answer"
        self.print_header(f"Testing {test_name}")

        payload = {
            "question": "Say hi.",
            "history": "[]",
            "isNoneDoc": True,
        }

        try:
            response = requests.post(
                f"{self.base_url}/api/answer",
                json=payload,
                headers=self.headers,
                timeout=60,
            )

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            data = response.json()
            checks = [
                ("answer" in data, "has answer"),
                ("conversation_id" in data, "has conversation_id"),
            ]

            all_passed = True
            for check, label in checks:
                if check:
                    self.print_success(f"  {label}")
                else:
                    self.print_error(f"  {label}")
                    all_passed = False

            self.print_info(f"Answer: {data.get('answer', '')[:100]}")
            self.record_result(test_name, all_passed, "Old endpoint works" if all_passed else "Regression")
            return all_passed

        except Exception as e:
            self.print_error(f"Error: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    def cleanup(self):
        """Clean up test resources."""
        if hasattr(self, "_agent_id") and self._agent_id and self.is_authenticated:
            try:
                self.post(f"/api/delete_agent?id={self._agent_id}", json={})
                self.print_info(f"Cleaned up test agent {self._agent_id[:8]}...")
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Run All
    # -------------------------------------------------------------------------

    def run_all(self) -> bool:
        """Run all v1 API integration tests."""
        self.print_header("V1 Chat Completions API Integration Tests")
        self.print_info(f"Base URL: {self.base_url}")
        self.print_info(f"Authentication: {'Yes' if self.is_authenticated else 'No'}")

        try:
            # Auth tests (no agent needed)
            self.test_no_auth_returns_401()
            time.sleep(0.5)

            self.test_models_no_auth()
            time.sleep(0.5)

            self.test_invalid_key_returns_error()
            time.sleep(0.5)

            self.test_missing_messages_returns_400()
            time.sleep(0.5)

            # Non-streaming
            self.test_non_streaming_basic()
            time.sleep(1)

            # Streaming
            self.test_streaming_basic()
            time.sleep(1)

            # Multi-turn
            self.test_multi_turn_conversation()
            time.sleep(1)

            # Models
            self.test_list_models()
            time.sleep(0.5)

            # Backward compatibility
            self.test_old_stream_endpoint_still_works()
            time.sleep(1)

            self.test_old_answer_endpoint_still_works()
            time.sleep(1)

        finally:
            self.cleanup()

        return self.print_summary()


def main():
    """Main entry point."""
    client = create_client_from_args(V1ApiTests, "DocsGPT V1 API Integration Tests")
    success = client.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
