#!/usr/bin/env python3
r"""
Integration tests for the /v1/ chat completions API — client tool-call flow.

Tests the full lifecycle:
1. Send request with client tools → LLM triggers a tool call
2. Verify response returns clean tool names (no internal _ct\d+ suffix)
3. Send continuation with tool results + top-level conversation_id
4. Verify the continuation completes successfully

Usage:
    python tests/integration/test_v1_tool_calls.py
    python tests/integration/test_v1_tool_calls.py --base-url http://localhost:7091
"""

import json as json_module
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

_THIS_DIR = Path(__file__).parent
_TESTS_DIR = _THIS_DIR.parent
_ROOT_DIR = _TESTS_DIR.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from tests.integration.base import DocsGPTTestBase, create_client_from_args

# Internal suffix pattern that should NOT appear in client responses
_CT_SUFFIX_RE = re.compile(r"_ct\d+$")


class V1ToolCallTests(DocsGPTTestBase):
    """Integration tests for /v1/ client tool-call flows."""

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def get_or_create_agent_key(self) -> Optional[str]:
        """Get or create a test agent and return its API key."""
        if hasattr(self, "_agent_key") and self._agent_key:
            return self._agent_key

        payload = {
            "name": f"V1 ToolCall Test {int(time.time())}",
            "description": "Integration test agent for tool-call flow",
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
        except Exception as e:
            self.print_error(f"Failed to create agent: {e}")

        return None

    def _v1_headers(self, api_key: str) -> dict:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # A simple client tool definition in OpenAI format
    _CLIENT_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "create",
                "description": "Create a new todo item",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "The title of the new todo item",
                        }
                    },
                    "required": ["title"],
                },
            },
        }
    ]

    def _send_streaming_request(
        self,
        api_key: str,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        conversation_id: Optional[str] = None,
    ) -> Tuple[List[Dict], str, Optional[Dict]]:
        """Send a streaming request and collect all events.

        Returns:
            (all_chunks, full_content, tool_call_info)
            tool_call_info is a dict with 'name', 'arguments', 'call_id'
            if the response paused for a client tool call, else None.
        """
        body: Dict[str, Any] = {
            "messages": messages,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
        if conversation_id:
            body["conversation_id"] = conversation_id

        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=body,
            headers=self._v1_headers(api_key),
            stream=True,
            timeout=120,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Expected 200, got {response.status_code}: {response.text[:300]}"
            )

        chunks: List[Dict] = []
        content_pieces: List[str] = []
        tool_call_info: Optional[Dict] = None
        conversation_id_from_response: Optional[str] = None

        for line in response.iter_lines():
            if not line:
                continue
            line_str = line.decode("utf-8")
            if not line_str.startswith("data: "):
                continue

            data_str = line_str[6:]
            if data_str.strip() == "[DONE]":
                break

            try:
                chunk = json_module.loads(data_str)
                chunks.append(chunk)

                # Standard chunks
                if "choices" in chunk:
                    delta = chunk["choices"][0].get("delta", {})
                    if "content" in delta:
                        content_pieces.append(delta["content"])

                    # Tool call delta
                    if "tool_calls" in delta:
                        tc = delta["tool_calls"][0]
                        tool_call_info = {
                            "call_id": tc.get("id", ""),
                            "name": tc["function"]["name"],
                            "arguments": tc["function"].get("arguments", "{}"),
                        }

                # Extension chunks
                if "docsgpt" in chunk:
                    ext = chunk["docsgpt"]
                    if ext.get("type") == "id":
                        conversation_id_from_response = ext.get("conversation_id")

            except json_module.JSONDecodeError:
                pass

        full_content = "".join(content_pieces)

        # Attach conversation_id to tool_call_info for convenience
        if tool_call_info and conversation_id_from_response:
            tool_call_info["conversation_id"] = conversation_id_from_response

        return chunks, full_content, tool_call_info

    def _send_non_streaming_request(
        self,
        api_key: str,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict:
        """Send a non-streaming request and return parsed JSON."""
        body: Dict[str, Any] = {
            "messages": messages,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
        if conversation_id:
            body["conversation_id"] = conversation_id

        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=body,
            headers=self._v1_headers(api_key),
            timeout=120,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Expected 200, got {response.status_code}: {response.text[:300]}"
            )

        return response.json()

    # -------------------------------------------------------------------------
    # Tests
    # -------------------------------------------------------------------------

    def test_streaming_tool_call_clean_name(self) -> bool:
        """Streaming: tool names returned to client must not have _ct suffixes."""
        test_name = "v1 streaming tool call - clean name"
        self.print_header(f"Testing {test_name}")

        api_key = self.get_or_create_agent_key()
        if not api_key:
            if not self.require_auth(test_name):
                return True
            self.record_result(test_name, True, "Skipped (no agent)")
            return True

        try:
            messages = [
                {"role": "user", "content": "Use the create tool to add a todo item titled 'Test integration'. Call the tool now."},
            ]
            chunks, content, tool_call_info = self._send_streaming_request(
                api_key, messages, tools=self._CLIENT_TOOLS
            )

            if not tool_call_info:
                # LLM didn't trigger the tool — could happen, not a failure of our code
                self.print_warning("LLM did not trigger a tool call (may need prompt tuning)")
                self.print_info(f"Got text response instead: {content[:100]}")
                self.record_result(test_name, True, "Skipped (LLM didn't call tool)")
                return True

            tool_name = tool_call_info["name"]
            self.print_info(f"Tool call name: {tool_name}")

            has_suffix = bool(_CT_SUFFIX_RE.search(tool_name))
            if has_suffix:
                self.print_error(f"Tool name has internal suffix: {tool_name}")
                self.record_result(test_name, False, f"Suffix leak: {tool_name}")
                return False

            self.print_success(f"Tool name is clean: {tool_name}")
            self.record_result(test_name, True, f"Clean name: {tool_name}")
            return True

        except Exception as e:
            self.print_error(f"Error: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_non_streaming_tool_call_clean_name(self) -> bool:
        """Non-streaming: tool names returned to client must not have _ct suffixes."""
        test_name = "v1 non-streaming tool call - clean name"
        self.print_header(f"Testing {test_name}")

        api_key = self.get_or_create_agent_key()
        if not api_key:
            if not self.require_auth(test_name):
                return True
            self.record_result(test_name, True, "Skipped (no agent)")
            return True

        try:
            messages = [
                {"role": "user", "content": "Use the create tool to add a todo item titled 'Test non-stream'. Call the tool now."},
            ]
            data = self._send_non_streaming_request(
                api_key, messages, tools=self._CLIENT_TOOLS
            )

            message = data["choices"][0]["message"]
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                content = message.get("content", "")
                self.print_warning("LLM did not trigger a tool call")
                self.print_info(f"Got text response: {content[:100]}")
                self.record_result(test_name, True, "Skipped (LLM didn't call tool)")
                return True

            tool_name = tool_calls[0]["function"]["name"]
            self.print_info(f"Tool call name: {tool_name}")

            has_suffix = bool(_CT_SUFFIX_RE.search(tool_name))
            if has_suffix:
                self.print_error(f"Tool name has internal suffix: {tool_name}")
                self.record_result(test_name, False, f"Suffix leak: {tool_name}")
                return False

            self.print_success(f"Tool name is clean: {tool_name}")
            self.record_result(test_name, True, f"Clean name: {tool_name}")
            return True

        except Exception as e:
            self.print_error(f"Error: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_streaming_tool_continuation_with_top_level_conversation_id(self) -> bool:
        """Full tool-call round-trip: trigger → get conversation_id → continue with top-level id."""
        test_name = "v1 streaming tool continuation - top-level conversation_id"
        self.print_header(f"Testing {test_name}")

        api_key = self.get_or_create_agent_key()
        if not api_key:
            if not self.require_auth(test_name):
                return True
            self.record_result(test_name, True, "Skipped (no agent)")
            return True

        try:
            # Step 1: trigger a tool call
            messages = [
                {"role": "user", "content": "Use the create tool to add a todo item titled 'Round trip test'. Call the tool now."},
            ]
            chunks, content, tool_call_info = self._send_streaming_request(
                api_key, messages, tools=self._CLIENT_TOOLS
            )

            if not tool_call_info:
                self.print_warning("LLM did not trigger a tool call")
                self.record_result(test_name, True, "Skipped (LLM didn't call tool)")
                return True

            conversation_id = tool_call_info.get("conversation_id")
            if not conversation_id:
                self.print_error("No conversation_id returned in stream")
                self.record_result(test_name, False, "Missing conversation_id")
                return False

            self.print_info(f"Got conversation_id: {conversation_id[:12]}...")
            self.print_info(f"Tool call: {tool_call_info['name']}({tool_call_info['arguments']})")

            # Step 2: send continuation with tool result + top-level conversation_id
            # (standard OpenAI format — no docsgpt field in assistant message)
            continuation_messages = [
                *messages,
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tool_call_info["call_id"],
                            "type": "function",
                            "function": {
                                "name": tool_call_info["name"],
                                "arguments": tool_call_info["arguments"],
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": tool_call_info["call_id"],
                    "content": json_module.dumps({"id": 99, "title": "Round trip test", "status": "created"}),
                },
            ]

            chunks2, content2, tool_call_info2 = self._send_streaming_request(
                api_key,
                continuation_messages,
                tools=self._CLIENT_TOOLS,
                conversation_id=conversation_id,
            )

            checks = [
                (len(chunks2) > 0, f"continuation returned {len(chunks2)} chunks"),
                (bool(content2) or tool_call_info2 is not None, "got content or another tool call"),
            ]

            all_passed = True
            for check, label in checks:
                if check:
                    self.print_success(f"  {label}")
                else:
                    self.print_error(f"  {label}")
                    all_passed = False

            if content2:
                self.print_info(f"Continuation response: {content2[:150]}")

            self.record_result(
                test_name,
                all_passed,
                "Full round-trip works" if all_passed else "Continuation failed",
            )
            return all_passed

        except Exception as e:
            self.print_error(f"Error: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_non_streaming_tool_continuation_with_top_level_conversation_id(self) -> bool:
        """Non-streaming full round-trip with top-level conversation_id."""
        test_name = "v1 non-streaming tool continuation - top-level conversation_id"
        self.print_header(f"Testing {test_name}")

        api_key = self.get_or_create_agent_key()
        if not api_key:
            if not self.require_auth(test_name):
                return True
            self.record_result(test_name, True, "Skipped (no agent)")
            return True

        try:
            # Step 1: trigger a tool call
            messages = [
                {"role": "user", "content": "Use the create tool to add a todo item titled 'Non-stream round trip'. Call the tool now."},
            ]
            data = self._send_non_streaming_request(
                api_key, messages, tools=self._CLIENT_TOOLS
            )

            message = data["choices"][0]["message"]
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                self.print_warning("LLM did not trigger a tool call")
                self.record_result(test_name, True, "Skipped (LLM didn't call tool)")
                return True

            conversation_id = data.get("docsgpt", {}).get("conversation_id")
            if not conversation_id:
                self.print_error("No conversation_id in response")
                self.record_result(test_name, False, "Missing conversation_id")
                return False

            tc = tool_calls[0]
            self.print_info(f"Got tool call: {tc['function']['name']}")
            self.print_info(f"conversation_id: {conversation_id[:12]}...")

            # Step 2: send continuation (standard format, top-level conversation_id)
            continuation_messages = [
                *messages,
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tc],
                },
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json_module.dumps({"id": 100, "title": "Non-stream round trip", "status": "created"}),
                },
            ]

            data2 = self._send_non_streaming_request(
                api_key,
                continuation_messages,
                tools=self._CLIENT_TOOLS,
                conversation_id=conversation_id,
            )

            message2 = data2["choices"][0]["message"]
            has_response = bool(message2.get("content")) or bool(message2.get("tool_calls"))

            if has_response:
                self.print_success("Continuation returned a response")
                content2 = message2.get("content", "")
                if content2:
                    self.print_info(f"Response: {content2[:150]}")
            else:
                self.print_error("Continuation returned empty response")

            self.record_result(
                test_name,
                has_response,
                "Round-trip works" if has_response else "Empty continuation response",
            )
            return has_response

        except Exception as e:
            self.print_error(f"Error: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Cleanup & Run All
    # -------------------------------------------------------------------------

    def cleanup(self):
        if hasattr(self, "_agent_id") and self._agent_id and self.is_authenticated:
            try:
                self.post(f"/api/delete_agent?id={self._agent_id}", json={})
                self.print_info(f"Cleaned up test agent {self._agent_id[:8]}...")
            except Exception:
                pass

    def run_all(self) -> bool:
        self.print_header("V1 Tool-Call Flow Integration Tests")
        self.print_info(f"Base URL: {self.base_url}")
        self.print_info(f"Authentication: {'Yes' if self.is_authenticated else 'No'}")

        try:
            # Streaming tests
            self.test_streaming_tool_call_clean_name()
            time.sleep(1)

            self.test_non_streaming_tool_call_clean_name()
            time.sleep(1)

            # Full round-trip tests
            self.test_streaming_tool_continuation_with_top_level_conversation_id()
            time.sleep(1)

            self.test_non_streaming_tool_continuation_with_top_level_conversation_id()
            time.sleep(1)

        finally:
            self.cleanup()

        return self.print_summary()


def main():
    client = create_client_from_args(V1ToolCallTests, "DocsGPT V1 Tool-Call Integration Tests")
    success = client.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
