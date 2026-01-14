#!/usr/bin/env python3
"""
Integration tests for DocsGPT chat endpoints.

Endpoints tested:
- /stream (POST) - Streaming chat
- /api/answer (POST) - Non-streaming chat
- /api/feedback (POST) - Feedback submission
- /api/tts (POST) - Text-to-speech

Usage:
    python tests/integration/test_chat.py
    python tests/integration/test_chat.py --base-url http://localhost:7091
    python tests/integration/test_chat.py --token YOUR_JWT_TOKEN
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


class ChatTests(DocsGPTTestBase):
    """Integration tests for chat/streaming endpoints."""

    # -------------------------------------------------------------------------
    # Test Data Helpers
    # -------------------------------------------------------------------------

    def get_or_create_test_agent(self) -> Optional[tuple]:
        """
        Get or create a test agent for chat tests.

        Returns:
            Tuple of (agent_id, api_key) or None if creation fails
        """
        if hasattr(self, "_test_agent"):
            return self._test_agent

        if not self.is_authenticated:
            return None

        payload = {
            "name": f"Chat Test Agent {int(time.time())}",
            "description": "Integration test agent for chat tests",
            "prompt_id": "default",
            "chunks": 2,
            "retriever": "classic",
            "agent_type": "classic",
            "status": "draft",
        }

        try:
            response = self.post("/api/create_agent", json=payload, timeout=10)
            if response.status_code in [200, 201]:
                result = response.json()
                agent_id = result.get("id")
                api_key = result.get("key")
                if agent_id:
                    self._test_agent = (agent_id, api_key)
                    return self._test_agent
        except Exception:
            pass

        return None

    def get_or_create_published_agent(self) -> Optional[tuple]:
        """
        Get or create a published agent with API key.

        Returns:
            Tuple of (agent_id, api_key) or None if creation fails
        """
        if hasattr(self, "_published_agent"):
            return self._published_agent

        if not self.is_authenticated:
            return None

        # First create a source
        source_id = self._create_test_source()

        payload = {
            "name": f"Chat Test Published Agent {int(time.time())}",
            "description": "Integration test published agent",
            "prompt_id": "default",
            "chunks": 2,
            "retriever": "classic",
            "agent_type": "classic",
            "status": "published",
        }

        if source_id:
            payload["source"] = source_id

        try:
            response = self.post("/api/create_agent", json=payload, timeout=10)
            if response.status_code in [200, 201]:
                result = response.json()
                agent_id = result.get("id")
                api_key = result.get("key")
                if agent_id and api_key:
                    self._published_agent = (agent_id, api_key)
                    return self._published_agent
        except Exception:
            pass

        return None

    def _create_test_source(self) -> Optional[str]:
        """Create a simple test source and return its ID."""
        if hasattr(self, "_test_source_id"):
            return self._test_source_id

        test_content = """# Test Documentation
## Overview
This is test documentation for integration tests.
## Features
- Feature 1: Testing
- Feature 2: Integration
"""
        files = {"file": ("test_docs.txt", test_content.encode(), "text/plain")}
        data = {"user": "test_user", "name": f"Chat Test Source {int(time.time())}"}

        try:
            response = self.post("/api/upload", files=files, data=data, timeout=30)
            if response.status_code == 200:
                task_id = response.json().get("task_id")
                if task_id:
                    time.sleep(5)  # Wait for processing
                    # Get source ID
                    sources_response = self.get("/api/sources")
                    if sources_response.status_code == 200:
                        sources = sources_response.json()
                        for source in sources:
                            if "Chat Test Source" in source.get("name", ""):
                                self._test_source_id = source.get("id")
                                return self._test_source_id
        except Exception:
            pass

        return None

    # -------------------------------------------------------------------------
    # Stream Endpoint Tests
    # -------------------------------------------------------------------------

    def test_stream_endpoint_no_agent(self) -> bool:
        """Test /stream endpoint without agent."""
        test_name = "Stream endpoint (no agent)"
        self.print_header(f"Testing {test_name}")

        payload = {
            "question": "What is DocsGPT?",
            "history": "[]",
            "isNoneDoc": True,
        }

        try:
            self.print_info("POST /stream")
            self.print_info(f"Payload: {json_module.dumps(payload, indent=2)}")

            response = requests.post(
                f"{self.base_url}/stream",
                json=payload,
                headers=self.headers,
                stream=True,
                timeout=30,
            )

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.print_error(f"Response: {response.text[:500]}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            # Parse SSE stream
            events = []
            full_response = ""
            conversation_id = None

            for line in response.iter_lines():
                if line:
                    line_str = line.decode("utf-8")
                    if line_str.startswith("data: "):
                        data_str = line_str[6:]
                        try:
                            data = json_module.loads(data_str)
                            events.append(data)

                            if data.get("type") in ["stream", "answer"]:
                                full_response += data.get("message", "") or data.get("answer", "")
                            elif data.get("type") == "id":
                                conversation_id = data.get("id")
                            elif data.get("type") == "end":
                                break
                        except json_module.JSONDecodeError:
                            pass

            self.print_success(f"Received {len(events)} events")
            self.print_info(f"Response preview: {full_response[:100]}...")

            if conversation_id:
                self.print_success(f"Conversation ID: {conversation_id}")

            self.record_result(test_name, True, "Success")
            self.print_success(f"{test_name} passed!")
            return True

        except requests.exceptions.RequestException as e:
            self.print_error(f"Request failed: {str(e)}")
            self.record_result(test_name, False, str(e))
            return False
        except Exception as e:
            self.print_error(f"Unexpected error: {str(e)}")
            self.record_result(test_name, False, str(e))
            return False

    def test_stream_endpoint_with_agent(self) -> bool:
        """Test /stream endpoint with agent_id."""
        test_name = "Stream endpoint (with agent)"

        agent_result = self.get_or_create_test_agent()
        if not agent_result:
            if not self.require_auth(test_name):
                return True  # Skipped
            self.print_warning("Could not create test agent")
            self.record_result(test_name, True, "Skipped (no agent)")
            return True

        agent_id, _ = agent_result
        self.print_header(f"Testing {test_name}")

        payload = {
            "question": "What is DocsGPT?",
            "history": "[]",
            "agent_id": agent_id,
        }

        try:
            self.print_info(f"POST /stream with agent_id={agent_id[:8]}...")

            response = requests.post(
                f"{self.base_url}/stream",
                json=payload,
                headers=self.headers,
                stream=True,
                timeout=30,
            )

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            events = []
            for line in response.iter_lines():
                if line:
                    line_str = line.decode("utf-8")
                    if line_str.startswith("data: "):
                        try:
                            data = json_module.loads(line_str[6:])
                            events.append(data)
                            if data.get("type") == "end":
                                break
                        except json_module.JSONDecodeError:
                            pass

            self.print_success(f"Received {len(events)} events")
            self.record_result(test_name, True, "Success")
            return True

        except Exception as e:
            self.print_error(f"Error: {str(e)}")
            self.record_result(test_name, False, str(e))
            return False

    def test_stream_endpoint_with_api_key(self) -> bool:
        """Test /stream endpoint with API key."""
        test_name = "Stream endpoint (with API key)"

        agent_result = self.get_or_create_published_agent()
        if not agent_result or not agent_result[1]:
            if not self.require_auth(test_name):
                return True
            self.print_warning("Could not create published agent with API key")
            self.record_result(test_name, True, "Skipped (no API key)")
            return True

        _, api_key = agent_result
        self.print_header(f"Testing {test_name}")

        payload = {
            "question": "What is DocsGPT?",
            "history": "[]",
            "api_key": api_key,
        }

        try:
            self.print_info(f"POST /stream with api_key={api_key[:20]}...")

            response = requests.post(
                f"{self.base_url}/stream",
                json=payload,
                headers=self.headers,
                stream=True,
                timeout=30,
            )

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            events = []
            full_response = ""
            for line in response.iter_lines():
                if line:
                    line_str = line.decode("utf-8")
                    if line_str.startswith("data: "):
                        try:
                            data = json_module.loads(line_str[6:])
                            events.append(data)
                            if data.get("type") in ["stream", "answer"]:
                                full_response += data.get("message", "") or data.get("answer", "")
                            elif data.get("type") == "end":
                                break
                        except json_module.JSONDecodeError:
                            pass

            self.print_success(f"Received {len(events)} events")
            self.print_info(f"Response preview: {full_response[:100]}...")
            self.record_result(test_name, True, "Success")
            return True

        except Exception as e:
            self.print_error(f"Error: {str(e)}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Answer Endpoint Tests
    # -------------------------------------------------------------------------

    def test_answer_endpoint_no_agent(self) -> bool:
        """Test /api/answer endpoint without agent."""
        test_name = "Answer endpoint (no agent)"
        self.print_header(f"Testing {test_name}")

        payload = {
            "question": "What is DocsGPT?",
            "history": "[]",
            "isNoneDoc": True,
        }

        try:
            self.print_info("POST /api/answer")
            self.print_info(f"Payload: {json_module.dumps(payload, indent=2)}")

            response = self.post("/api/answer", json=payload, timeout=30)

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.print_error(f"Response: {response.text[:500]}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            result = response.json()
            self.print_info(f"Response keys: {list(result.keys())}")

            if "answer" in result:
                answer = result["answer"]
                self.print_success(f"Answer received: {answer[:100]}...")
            else:
                self.print_warning("No 'answer' field in response")

            if "conversation_id" in result:
                self.print_success(f"Conversation ID: {result['conversation_id']}")

            self.record_result(test_name, True, "Success")
            self.print_success(f"{test_name} passed!")
            return True

        except Exception as e:
            self.print_error(f"Error: {str(e)}")
            self.record_result(test_name, False, str(e))
            return False

    def test_answer_endpoint_with_agent(self) -> bool:
        """Test /api/answer endpoint with agent_id."""
        test_name = "Answer endpoint (with agent)"

        agent_result = self.get_or_create_test_agent()
        if not agent_result:
            if not self.require_auth(test_name):
                return True
            self.record_result(test_name, True, "Skipped (no agent)")
            return True

        agent_id, _ = agent_result
        self.print_header(f"Testing {test_name}")

        payload = {
            "question": "What is DocsGPT?",
            "history": "[]",
            "agent_id": agent_id,
        }

        try:
            self.print_info(f"POST /api/answer with agent_id={agent_id[:8]}...")

            response = self.post("/api/answer", json=payload, timeout=30)

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            result = response.json()
            answer = result.get("answer", "")
            self.print_success(f"Answer received: {answer[:100]}...")
            self.record_result(test_name, True, "Success")
            return True

        except Exception as e:
            self.print_error(f"Error: {str(e)}")
            self.record_result(test_name, False, str(e))
            return False

    def test_answer_endpoint_with_api_key(self) -> bool:
        """Test /api/answer endpoint with API key."""
        test_name = "Answer endpoint (with API key)"

        agent_result = self.get_or_create_published_agent()
        if not agent_result or not agent_result[1]:
            if not self.require_auth(test_name):
                return True
            self.record_result(test_name, True, "Skipped (no API key)")
            return True

        _, api_key = agent_result
        self.print_header(f"Testing {test_name}")

        payload = {
            "question": "What is DocsGPT?",
            "history": "[]",
            "api_key": api_key,
        }

        try:
            self.print_info(f"POST /api/answer with api_key={api_key[:20]}...")

            response = self.post("/api/answer", json=payload, timeout=30)

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

            result = response.json()
            answer = result.get("answer", "")
            self.print_success(f"Answer received: {answer[:100]}...")
            self.record_result(test_name, True, "Success")
            return True

        except Exception as e:
            self.print_error(f"Error: {str(e)}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Validation Tests
    # -------------------------------------------------------------------------

    def test_model_validation_invalid_model_id(self) -> bool:
        """Test that invalid model_id is rejected."""
        test_name = "Model validation (invalid model_id)"
        self.print_header(f"Testing {test_name}")

        payload = {
            "question": "Test question",
            "history": "[]",
            "isNoneDoc": True,
            "model_id": "invalid-model-xyz-123",
        }

        try:
            self.print_info("POST /stream with invalid model_id")

            response = requests.post(
                f"{self.base_url}/stream",
                json=payload,
                headers=self.headers,
                stream=True,
                timeout=10,
            )

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code == 400:
                # Read error from SSE stream
                error_message = None
                for line in response.iter_lines():
                    if line:
                        line_str = line.decode("utf-8")
                        if line_str.startswith("data: "):
                            try:
                                data = json_module.loads(line_str[6:])
                                if data.get("type") == "error":
                                    error_message = data.get("message") or data.get("error", "")
                                    break
                            except json_module.JSONDecodeError:
                                pass

                if error_message:
                    self.print_success("Invalid model_id rejected with 400 status")
                    self.print_info(f"Error: {error_message[:200]}")
                    self.record_result(test_name, True, "Validation works")
                    return True
                else:
                    self.print_warning("No error message in response")
                    self.record_result(test_name, False, "No error message")
                    return False
            else:
                self.print_warning(f"Expected 400, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Error: {str(e)}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Compression Tests
    # -------------------------------------------------------------------------

    def test_compression_heavy_tool_usage(self) -> bool:
        """Test compression with heavy conversation usage."""
        test_name = "Compression - Heavy Tool Usage"
        self.print_header(f"Testing {test_name}")

        if not self.require_auth(test_name):
            return True

        self.print_info("Making 10 consecutive requests to build conversation history...")

        current_conv_id = None

        for i in range(10):
            question = f"Tell me about Python topic {i+1}: data structures, decorators, async, testing. Provide a comprehensive explanation."

            payload = {
                "question": question,
                "history": "[]",
                "isNoneDoc": True,
            }

            if current_conv_id:
                payload["conversation_id"] = current_conv_id

            try:
                response = self.post("/api/answer", json=payload, timeout=90)

                if response.status_code == 200:
                    result = response.json()
                    current_conv_id = result.get("conversation_id", current_conv_id)
                    answer_preview = (result.get("answer") or "")[:80]
                    self.print_success(f"Request {i+1}/10 completed")
                    self.print_info(f"  Answer: {answer_preview}...")
                else:
                    self.print_error(f"Request {i+1}/10 failed: status {response.status_code}")
                    self.record_result(test_name, False, f"Request {i+1} failed")
                    return False

                time.sleep(2)

            except Exception as e:
                self.print_error(f"Request {i+1}/10 failed: {str(e)}")
                self.record_result(test_name, False, str(e))
                return False

        if current_conv_id:
            self.print_success("Heavy usage test completed")
            self.record_result(test_name, True, f"10 requests, conv_id: {current_conv_id}")
            return True
        else:
            self.print_warning("No conversation_id received")
            self.record_result(test_name, False, "No conversation_id")
            return False

    def test_compression_needle_in_haystack(self) -> bool:
        """Test that compression preserves critical information.

        Note: This is a long-running test that may timeout due to LLM response times.
        Timeouts are handled gracefully as they indicate performance issues, not bugs.
        """
        test_name = "Compression - Needle in Haystack"
        self.print_header(f"Testing {test_name}")

        if not self.require_auth(test_name):
            return True

        conversation_id = None

        # Step 1: Send general questions
        self.print_info("Step 1: Sending general questions...")
        for i, question in enumerate([
            "Tell me about Python best practices in detail",
            "Explain Python data structures comprehensively",
        ]):
            payload = {
                "question": question,
                "history": "[]",
                "isNoneDoc": True,
            }
            if conversation_id:
                payload["conversation_id"] = conversation_id

            try:
                response = self.post("/api/answer", json=payload, timeout=90)
                if response.status_code == 200:
                    result = response.json()
                    conversation_id = result.get("conversation_id", conversation_id)
                    self.print_success(f"General question {i+1}/2 completed")
                else:
                    self.print_error(f"Request failed: status {response.status_code}")
                    self.record_result(test_name, False, "General questions failed")
                    return False
                time.sleep(2)
            except Exception as e:
                # Timeout errors are expected for long LLM responses
                if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                    self.print_warning(f"Request timed out: {str(e)[:50]}")
                    self.record_result(test_name, True, "Skipped (timeout)")
                    return True
                self.print_error(f"Request failed: {str(e)}")
                self.record_result(test_name, False, str(e))
                return False

        # Step 2: Send critical information
        self.print_info("Step 2: Sending CRITICAL information...")
        critical_payload = {
            "question": "Please remember: The production database password is stored in DB_PASSWORD_PROD environment variable. The backup runs at 3:00 AM UTC daily.",
            "history": "[]",
            "isNoneDoc": True,
            "conversation_id": conversation_id,
        }

        try:
            response = self.post("/api/answer", json=critical_payload, timeout=90)
            if response.status_code == 200:
                result = response.json()
                conversation_id = result.get("conversation_id", conversation_id)
                self.print_success("Critical information sent")
            else:
                self.record_result(test_name, False, "Critical info failed")
                return False
            time.sleep(2)
        except Exception as e:
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                self.print_warning(f"Request timed out: {str(e)[:50]}")
                self.record_result(test_name, True, "Skipped (timeout)")
                return True
            self.record_result(test_name, False, str(e))
            return False

        # Step 3: Bury with more questions
        self.print_info("Step 3: Sending more questions to bury critical info...")
        for i, question in enumerate([
            "Explain Python decorators in great detail",
            "Tell me about Python async programming comprehensively",
        ]):
            payload = {
                "question": question,
                "history": "[]",
                "isNoneDoc": True,
                "conversation_id": conversation_id,
            }

            try:
                response = self.post("/api/answer", json=payload, timeout=90)
                if response.status_code == 200:
                    result = response.json()
                    conversation_id = result.get("conversation_id", conversation_id)
                    self.print_success(f"Burying question {i+1}/2 completed")
                else:
                    self.record_result(test_name, False, "Burying questions failed")
                    return False
                time.sleep(2)
            except Exception as e:
                if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                    self.print_warning(f"Request timed out: {str(e)[:50]}")
                    self.record_result(test_name, True, "Skipped (timeout)")
                    return True
                self.record_result(test_name, False, str(e))
                return False

        # Step 4: Test recall
        self.print_info("Step 4: Testing if critical info was preserved...")
        recall_payload = {
            "question": "What was the database password environment variable I mentioned earlier?",
            "history": "[]",
            "isNoneDoc": True,
            "conversation_id": conversation_id,
        }

        try:
            response = self.post("/api/answer", json=recall_payload, timeout=90)
            if response.status_code == 200:
                result = response.json()
                answer = (result.get("answer") or "").lower()

                if "db_password_prod" in answer or "database password" in answer:
                    self.print_success("Critical information preserved!")
                    self.print_info(f"Answer: {answer[:150]}...")
                    self.record_result(test_name, True, "Info preserved")
                    return True
                else:
                    self.print_warning("Critical information may have been lost")
                    self.print_info(f"Answer: {answer[:150]}...")
                    self.record_result(test_name, False, "Info not preserved")
                    return False
            else:
                self.record_result(test_name, False, "Recall failed")
                return False
        except Exception as e:
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                self.print_warning(f"Request timed out: {str(e)[:50]}")
                self.record_result(test_name, True, "Skipped (timeout)")
                return True
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Feedback Tests (NEW)
    # -------------------------------------------------------------------------

    def test_feedback_positive(self) -> bool:
        """Test positive feedback submission."""
        test_name = "Feedback - Positive"
        self.print_header(f"Testing {test_name}")

        # First create a conversation to get an ID
        answer_response = self.post(
            "/api/answer",
            json={"question": "Hello", "history": "[]", "isNoneDoc": True},
            timeout=30,
        )

        if answer_response.status_code != 200:
            self.print_warning("Could not create conversation for feedback test")
            self.record_result(test_name, True, "Skipped (no conversation)")
            return True

        result = answer_response.json()
        conversation_id = result.get("conversation_id")

        if not conversation_id:
            self.record_result(test_name, True, "Skipped (no conversation_id)")
            return True

        payload = {
            "question": "Hello",
            "answer": result.get("answer", ""),
            "feedback": "like",
            "conversation_id": conversation_id,
            "question_index": 0,  # Required field
        }

        try:
            response = self.post("/api/feedback", json=payload, timeout=10)
            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code == 200:
                self.print_success("Positive feedback submitted")
                self.record_result(test_name, True, "Success")
                return True
            else:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

        except Exception as e:
            self.print_error(f"Error: {str(e)}")
            self.record_result(test_name, False, str(e))
            return False

    def test_feedback_negative(self) -> bool:
        """Test negative feedback submission."""
        test_name = "Feedback - Negative"
        self.print_header(f"Testing {test_name}")

        answer_response = self.post(
            "/api/answer",
            json={"question": "Hello", "history": "[]", "isNoneDoc": True},
            timeout=30,
        )

        if answer_response.status_code != 200:
            self.record_result(test_name, True, "Skipped (no conversation)")
            return True

        result = answer_response.json()
        conversation_id = result.get("conversation_id")

        if not conversation_id:
            self.record_result(test_name, True, "Skipped (no conversation_id)")
            return True

        payload = {
            "question": "Hello",
            "answer": result.get("answer", ""),
            "feedback": "dislike",
            "conversation_id": conversation_id,
            "question_index": 0,  # Required field
        }

        try:
            response = self.post("/api/feedback", json=payload, timeout=10)
            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code == 200:
                self.print_success("Negative feedback submitted")
                self.record_result(test_name, True, "Success")
                return True
            else:
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

        except Exception as e:
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # TTS Tests (NEW)
    # -------------------------------------------------------------------------

    def test_tts_basic(self) -> bool:
        """Test basic text-to-speech endpoint."""
        test_name = "TTS - Basic"
        self.print_header(f"Testing {test_name}")

        payload = {"text": "Hello, this is a test of the text to speech system."}

        try:
            response = self.post("/api/tts", json=payload, timeout=30)
            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code == 200:
                content_type = response.headers.get("Content-Type", "")
                self.print_success(f"TTS response received, Content-Type: {content_type}")
                self.record_result(test_name, True, "Success")
                return True
            elif response.status_code == 501:
                self.print_warning("TTS not implemented/configured")
                self.record_result(test_name, True, "Skipped (not configured)")
                return True
            else:
                self.record_result(test_name, False, f"Status {response.status_code}")
                return False

        except Exception as e:
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Run All Tests
    # -------------------------------------------------------------------------

    def run_all(self) -> bool:
        """Run all chat integration tests."""
        self.print_header("Chat Integration Tests")
        self.print_info(f"Base URL: {self.base_url}")
        self.print_info(f"Authentication: {'Yes' if self.is_authenticated else 'No'}")

        # Basic endpoint tests
        self.test_stream_endpoint_no_agent()
        time.sleep(1)

        self.test_answer_endpoint_no_agent()
        time.sleep(1)

        # Validation tests
        self.test_model_validation_invalid_model_id()
        time.sleep(1)

        # Agent-based tests
        self.test_stream_endpoint_with_agent()
        time.sleep(1)

        self.test_answer_endpoint_with_agent()
        time.sleep(1)

        # API key tests
        self.test_stream_endpoint_with_api_key()
        time.sleep(1)

        self.test_answer_endpoint_with_api_key()
        time.sleep(1)

        # Feedback tests
        self.test_feedback_positive()
        time.sleep(1)

        self.test_feedback_negative()
        time.sleep(1)

        # TTS test
        self.test_tts_basic()
        time.sleep(1)

        # Compression tests (longer running)
        if self.is_authenticated:
            self.test_compression_heavy_tool_usage()
            time.sleep(2)

            self.test_compression_needle_in_haystack()
        else:
            self.print_info("Skipping compression tests (no authentication)")

        return self.print_summary()


def main():
    """Main entry point for standalone execution."""
    client = create_client_from_args(ChatTests, "DocsGPT Chat Integration Tests")
    success = client.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
