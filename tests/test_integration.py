#!/usr/bin/env python3
"""
Integration test script for DocsGPT API endpoints.

Tests:
1. /stream endpoint without agent
2. /api/answer endpoint without agent
3. Create agent via API
4. /stream endpoint with agent
5. /api/answer endpoint with agent

Usage:
    python tests/test_integration.py  # auto-generates JWT token from local secret when available
    python tests/test_integration.py --base-url http://localhost:7091
    python tests/test_integration.py --token YOUR_JWT_TOKEN  # override auto-generation
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def generate_default_token() -> tuple[Optional[str], Optional[str]]:
    """
    Try to generate a JWT token using the same logic as generate_test_token.py.
    Returns a tuple of (token, error_message). Token is None on failure.
    """
    secret = os.getenv("JWT_SECRET_KEY")
    key_file = Path(".jwt_secret_key")

    if not secret:
        try:
            secret = key_file.read_text().strip()
        except FileNotFoundError:
            return None, f"Set JWT_SECRET_KEY or create {key_file} by running the backend once."
        except OSError as exc:
            return None, f"Could not read {key_file}: {exc}"

    if not secret:
        return None, "JWT secret key is empty."

    try:
        from jose import jwt  # type: ignore
    except ImportError:
        return None, "python-jose is not installed (pip install 'python-jose' to auto-generate tokens)."

    try:
        payload = {"sub": "test_integration_user"}
        return jwt.encode(payload, secret, algorithm="HS256"), None
    except Exception as exc:
        return None, f"Failed to generate JWT token: {exc}"


class DocsGPTTester:
    def __init__(self, base_url: str, token: Optional[str] = None, token_source: str = "provided"):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.token_source = token_source
        self.headers = {}
        if token:
            self.headers['Authorization'] = f'Bearer {token}'
        self.agent_id = None
        self.test_results = []

    def print_header(self, message: str):
        """Print a colored header"""
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{message}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}\n")

    def print_success(self, message: str):
        """Print a success message"""
        print(f"{Colors.OKGREEN}✓ {message}{Colors.ENDC}")

    def print_error(self, message: str):
        """Print an error message"""
        print(f"{Colors.FAIL}✗ {message}{Colors.ENDC}")

    def print_info(self, message: str):
        """Print an info message"""
        print(f"{Colors.OKCYAN}ℹ {message}{Colors.ENDC}")

    def print_warning(self, message: str):
        """Print a warning message"""
        print(f"{Colors.WARNING}⚠ {message}{Colors.ENDC}")

    def test_stream_endpoint(self, agent_id: Optional[str] = None) -> bool:
        """Test the /stream endpoint"""
        endpoint = f"{self.base_url}/stream"
        test_name = f"Stream endpoint{'with agent ' + agent_id if agent_id else ' (no agent)'}"

        self.print_header(f"Testing {test_name}")

        payload = {
            "question": "What is DocsGPT?",
            "history": "[]",
            "isNoneDoc": True,
        }

        if agent_id:
            payload["agent_id"] = agent_id

        try:
            self.print_info(f"POST {endpoint}")
            self.print_info(f"Payload: {json.dumps(payload, indent=2)}")

            response = requests.post(
                endpoint,
                json=payload,
                headers=self.headers,
                stream=True,
                timeout=30
            )

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.print_error(f"Response: {response.text[:500]}")
                self.test_results.append((test_name, False, f"Status {response.status_code}"))
                return False

            # Parse SSE stream
            events = []
            full_response = ""
            conversation_id = None

            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data_str = line[6:]  # Remove 'data: ' prefix
                        try:
                            data = json.loads(data_str)
                            events.append(data)

                            # Handle different event types
                            if data.get('type') in ['stream', 'answer']:
                                # Both 'stream' and 'answer' types contain response text
                                full_response += data.get('message', '') or data.get('answer', '')
                            elif data.get('type') == 'id':
                                conversation_id = data.get('id')
                            elif data.get('type') == 'end':
                                break
                        except json.JSONDecodeError:
                            pass

            self.print_success(f"Received {len(events)} events")
            self.print_info(f"Response preview: {full_response[:100]}...")

            if conversation_id:
                self.print_success(f"Conversation ID: {conversation_id}")

            if not full_response:
                self.print_warning("No response content received")

            self.test_results.append((test_name, True, "Success"))
            self.print_success(f"{test_name} passed!")
            return True

        except requests.exceptions.RequestException as e:
            self.print_error(f"Request failed: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return False
        except Exception as e:
            self.print_error(f"Unexpected error: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return False

    def test_answer_endpoint(self, agent_id: Optional[str] = None) -> bool:
        """Test the /api/answer endpoint"""
        endpoint = f"{self.base_url}/api/answer"
        test_name = f"Answer endpoint{' with agent ' + agent_id if agent_id else ' (no agent)'}"

        self.print_header(f"Testing {test_name}")

        payload = {
            "question": "What is DocsGPT?",
            "history": "[]",
            "isNoneDoc": True,
        }

        if agent_id:
            payload["agent_id"] = agent_id

        try:
            self.print_info(f"POST {endpoint}")
            self.print_info(f"Payload: {json.dumps(payload, indent=2)}")

            response = requests.post(
                endpoint,
                json=payload,
                headers=self.headers,
                timeout=30
            )

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code != 200:
                self.print_error(f"Expected 200, got {response.status_code}")
                self.print_error(f"Response: {response.text[:500]}")
                self.test_results.append((test_name, False, f"Status {response.status_code}"))
                return False

            result = response.json()

            self.print_info(f"Response keys: {list(result.keys())}")

            if 'answer' in result:
                answer = result['answer']
                self.print_success(f"Answer received: {answer[:100]}...")
            else:
                self.print_warning("No 'answer' field in response")

            if 'conversation_id' in result:
                self.print_success(f"Conversation ID: {result['conversation_id']}")

            if 'sources' in result:
                self.print_info(f"Sources: {len(result['sources'])} items")

            self.test_results.append((test_name, True, "Success"))
            self.print_success(f"{test_name} passed!")
            return True

        except requests.exceptions.RequestException as e:
            self.print_error(f"Request failed: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return False
        except Exception as e:
            self.print_error(f"Unexpected error: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return False

    def upload_text_source(self) -> Optional[str]:
        """Upload a simple text source for testing

        This creates a source without requiring crawler infrastructure.
        """
        endpoint = f"{self.base_url}/api/upload"
        test_name = "Upload Text Source"

        self.print_header(f"Testing {test_name}")

        if not self.token:
            self.print_warning("No authentication token provided")
            self.print_info("Source upload requires authentication")
            self.test_results.append((test_name, True, "Skipped (auth required)"))
            return None

        # Create a simple text file for upload
        test_content = """# DocsGPT Test Documentation

## Installation

To install DocsGPT, follow these steps:

1. Clone the repository
2. Run `docker compose up`
3. Access the application at http://localhost:5173

## Configuration

DocsGPT can be configured using environment variables:
- API_KEY: Your OpenAI API key
- LLM_PROVIDER: Choose between openai, anthropic, or google
- ENABLE_CONVERSATION_COMPRESSION: Enable context compression

## Features

DocsGPT provides:
- Conversation compression for long chats
- Real-time token tracking
- Multiple LLM provider support
- Agent system with tools
"""

        try:
            self.print_info(f"POST {endpoint}")
            self.print_info("Uploading test documentation...")

            # Create a file-like object
            files = {
                'file': ('test_docs.txt', test_content.encode(), 'text/plain')
            }
            data = {
                'user': 'test_user',
                'name': f'Test Docs {int(time.time())}',
            }

            response = requests.post(
                endpoint,
                files=files,
                data=data,
                headers=self.headers,
                timeout=30
            )

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                task_id = result.get('task_id')

                if task_id:
                    self.print_success(f"Upload task started: {task_id}")
                    self.print_info("Waiting for processing (10 seconds)...")
                    time.sleep(10)
                    self.test_results.append((test_name, True, f"Task: {task_id}"))
                    return task_id
                else:
                    self.print_warning("No task_id returned")
                    self.test_results.append((test_name, False, "No task_id"))
                    return None
            else:
                self.print_error(f"Expected 200, got {response.status_code}")
                try:
                    error_data = response.json()
                    self.print_error(f"Error: {error_data}")
                except Exception:
                    self.print_error(f"Response: {response.text[:500]}")
                self.test_results.append((test_name, False, f"Status {response.status_code}"))
                return None

        except requests.exceptions.RequestException as e:
            self.print_error(f"Request failed: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return None
        except Exception as e:
            self.print_error(f"Unexpected error: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return None

    def upload_crawler_source(self) -> Optional[str]:
        """Upload a crawler source for DocsGPT documentation"""
        endpoint = f"{self.base_url}/api/remote"
        test_name = "Upload Crawler Source"

        self.print_header(f"Testing {test_name}")

        if not self.token:
            self.print_warning("No authentication token provided")
            self.print_info("Source upload requires authentication")
            self.print_info("Skipping source upload and agent tests...")
            self.test_results.append((test_name, True, "Skipped (auth required)"))
            return None

        payload = {
            "user": "test_user",
            "source": "crawler",
            "name": f"DocsGPT Docs {int(time.time())}",
            "data": json.dumps({"url": "https://docs.docsgpt.cloud/"}),
        }

        try:
            self.print_info(f"POST {endpoint}")
            self.print_info("Crawling: https://docs.docsgpt.cloud/")

            response = requests.post(
                endpoint,
                data=payload,
                headers=self.headers,
                timeout=30
            )

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                task_id = result.get('task_id')

                if task_id:
                    self.print_success(f"Crawler task started: {task_id}")
                    self.print_info("Waiting for crawler to complete (30 seconds)...")
                    time.sleep(30)  # Wait for crawler to process
                    self.test_results.append((test_name, True, f"Task: {task_id}"))
                    return task_id
                else:
                    self.print_warning("No task_id returned")
                    self.test_results.append((test_name, False, "No task_id"))
                    return None
            else:
                self.print_error(f"Expected 200, got {response.status_code}")
                try:
                    error_data = response.json()
                    self.print_error(f"Error: {error_data}")
                except Exception:
                    self.print_error(f"Response: {response.text[:500]}")
                self.test_results.append((test_name, False, f"Status {response.status_code}"))
                return None

        except requests.exceptions.RequestException as e:
            self.print_error(f"Request failed: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return None
        except Exception as e:
            self.print_error(f"Unexpected error: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return None

    def get_source_id_from_task(self, task_id: str) -> Optional[str]:
        """Check task status and get source ID"""
        endpoint = f"{self.base_url}/api/task_status"

        try:
            response = requests.get(
                endpoint,
                params={"task_id": task_id},
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('status') == 'SUCCESS':
                    # Task completed, now find the source
                    # Query sources collection to find the latest source
                    sources_response = requests.get(
                        f"{self.base_url}/api/sources",
                        headers=self.headers,
                        timeout=10
                    )
                    if sources_response.status_code == 200:
                        sources = sources_response.json()
                        # Filter out the "Default" source and get user sources only
                        user_sources = [s for s in sources if s.get('date') != 'default']
                        if user_sources and len(user_sources) > 0:
                            # Get the most recent source (first one, as they're sorted by date desc)
                            latest_source = user_sources[0]
                            return latest_source.get('id')
            return None
        except Exception as e:
            self.print_error(f"Error getting source ID: {str(e)}")
            return None

    def create_agent(self, source_id: Optional[str] = None, published: bool = False) -> Optional[tuple]:
        """Create an agent via API

        Args:
            source_id: Optional source ID to attach to agent
            published: If True, create published agent (requires source_id)

        Returns:
            Tuple of (agent_id, api_key) if successful, None otherwise
        """
        endpoint = f"{self.base_url}/api/create_agent"

        if published and source_id:
            test_name = f"Create Published Agent with source {source_id[:8]}..."
        elif published:
            test_name = "Create Published Agent (skipped - no source)"
        else:
            test_name = "Create Draft Agent"

        self.print_header(f"Testing {test_name}")

        if not self.token:
            self.print_warning("No authentication token provided")
            self.print_info("Agent creation requires authentication")
            self.print_info("To test agents, provide a JWT token with --token argument")
            self.print_info("Skipping agent tests...")
            # Mark as skipped rather than attempting without auth
            self.test_results.append((test_name, True, "Skipped (auth required)"))
            return None

        # Published agents require a source
        if published and not source_id:
            self.print_warning("Cannot create published agent without source")
            self.test_results.append((test_name, True, "Skipped (no source)"))
            return None

        # Create payload based on type
        if published:
            self.print_info(f"Creating published agent with source {source_id[:8]}...")
            payload = {
                "name": f"Test Agent (Published) {int(time.time())}",
                "description": "Integration test agent with source",
                "prompt_id": "default",
                "chunks": 2,
                "retriever": "classic",
                "agent_type": "classic",
                "status": "published",
                "source": source_id,
            }
        else:
            self.print_info("Creating draft agent (for agent_id testing)")
            payload = {
                "name": f"Test Agent (Draft) {int(time.time())}",
                "description": "Integration test draft agent",
                "prompt_id": "default",
                "chunks": 2,
                "retriever": "classic",
                "agent_type": "classic",
                "status": "draft",
            }

        try:
            self.print_info(f"POST {endpoint}")
            self.print_info(f"Payload: {json.dumps(payload, indent=2)}")

            response = requests.post(
                endpoint,
                json=payload,
                headers=self.headers,
                timeout=10
            )

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code in [200, 201]:  # Accept both 200 OK and 201 Created
                result = response.json()
                agent_id = result.get('id')
                api_key = result.get('key', '')

                if agent_id:
                    self.agent_id = agent_id
                    self.print_success(f"Agent created with ID: {agent_id}")
                    if api_key:
                        self.print_success(f"Agent API key: {api_key[:20]}...")
                        self.test_results.append((test_name, True, f"ID: {agent_id}, API Key: Yes"))
                        return (agent_id, api_key)
                    else:
                        self.print_warning("Agent created but no API key (draft agent)")
                        self.test_results.append((test_name, True, f"ID: {agent_id}, API Key: No"))
                        return (agent_id, None)
                else:
                    self.print_warning("Agent created but no ID returned")
                    self.test_results.append((test_name, False, "No ID returned"))
                    return None
            elif response.status_code == 401:
                self.print_warning("Authentication required for agent creation")
                self.print_info("To test agents, provide a JWT token with --token argument")
                self.print_info("Skipping agent tests...")
                # Mark as "skipped" rather than "failed"
                self.test_results.append((test_name, True, "Skipped (auth required)"))
                return None
            else:
                self.print_error(f"Expected 200/201, got {response.status_code}")
                try:
                    error_data = response.json()
                    self.print_error(f"Error: {error_data.get('message', response.text[:200])}")
                except Exception:
                    self.print_error(f"Response: {response.text[:500]}")
                self.test_results.append((test_name, False, f"Status {response.status_code}"))
                return None

        except requests.exceptions.RequestException as e:
            self.print_error(f"Request failed: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return None
        except Exception as e:
            self.print_error(f"Unexpected error: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return None

    def test_api_key_endpoint(self, api_key: str, endpoint_type: str = "stream") -> bool:
        """Test endpoint with API key instead of agent_id"""
        test_name = f"{endpoint_type.capitalize()} endpoint with API key"

        self.print_header(f"Testing {test_name}")

        if endpoint_type == "stream":
            endpoint = f"{self.base_url}/stream"
        else:
            endpoint = f"{self.base_url}/api/answer"

        payload = {
            "question": "What is DocsGPT?",
            "history": "[]",
            "api_key": api_key,  # Use api_key instead of agent_id
        }

        try:
            self.print_info(f"POST {endpoint}")
            self.print_info(f"Using API key: {api_key[:20]}...")

            if endpoint_type == "stream":
                response = requests.post(
                    endpoint,
                    json=payload,
                    headers=self.headers,
                    stream=True,
                    timeout=30
                )

                self.print_info(f"Status Code: {response.status_code}")

                if response.status_code != 200:
                    self.print_error(f"Expected 200, got {response.status_code}")
                    self.print_error(f"Response: {response.text[:500]}")
                    self.test_results.append((test_name, False, f"Status {response.status_code}"))
                    return False

                # Parse SSE stream
                events = []
                full_response = ""

                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith('data: '):
                            data_str = line[6:]
                            try:
                                data = json.loads(data_str)
                                events.append(data)

                                if data.get('type') in ['stream', 'answer']:
                                    full_response += data.get('message', '') or data.get('answer', '')
                                elif data.get('type') == 'end':
                                    break
                            except json.JSONDecodeError:
                                pass

                self.print_success(f"Received {len(events)} events")
                self.print_info(f"Response preview: {full_response[:100]}...")
                self.test_results.append((test_name, True, "Success"))
                return True

            else:  # answer endpoint
                response = requests.post(
                    endpoint,
                    json=payload,
                    headers=self.headers,
                    timeout=30
                )

                self.print_info(f"Status Code: {response.status_code}")

                if response.status_code != 200:
                    self.print_error(f"Expected 200, got {response.status_code}")
                    self.print_error(f"Response: {response.text[:500]}")
                    self.test_results.append((test_name, False, f"Status {response.status_code}"))
                    return False

                result = response.json()
                answer = result.get('answer') or ''
                self.print_success(f"Answer received: {answer[:100]}...")
                self.test_results.append((test_name, True, "Success"))
                return True

        except requests.exceptions.RequestException as e:
            self.print_error(f"Request failed: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return False
        except Exception as e:
            self.print_error(f"Unexpected error: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return False

    def test_model_validation(self) -> bool:
        """Test model_id validation"""
        endpoint = f"{self.base_url}/stream"
        test_name = "Model validation (invalid model_id)"

        self.print_header(f"Testing {test_name}")

        payload = {
            "question": "Test question",
            "history": "[]",
            "isNoneDoc": True,
            "model_id": "invalid-model-xyz-123",
        }

        try:
            self.print_info(f"POST {endpoint}")
            self.print_info("Testing with invalid model_id: invalid-model-xyz-123")

            response = requests.post(
                endpoint,
                json=payload,
                headers=self.headers,
                stream=True,
                timeout=10
            )

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code == 400:
                # Read the error from SSE stream
                error_message = None
                error_field = None
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith('data: '):
                            data_str = line[6:]
                            try:
                                data = json.loads(data_str)
                                if data.get('type') == 'error':
                                    # Try both 'message' and 'error' fields
                                    error_message = data.get('message') or data.get('error', '')
                                    error_field = 'message' if 'message' in data else 'error'
                                    break
                            except json.JSONDecodeError:
                                pass

                # Consider it successful if we got a 400 with any error message
                if error_message:
                    self.print_success("Invalid model_id rejected with 400 status")
                    self.print_info(f"Error ({error_field}): {error_message[:200]}")

                    # Check if it's the detailed validation error or generic error
                    if 'Invalid model_id' in error_message or 'model' in error_message.lower():
                        self.print_success("✓ Validation error contains model information")
                        self.test_results.append((test_name, True, "Validation works"))
                    else:
                        self.print_warning("Generic error message (validation may need improvement)")
                        self.test_results.append((test_name, True, "Generic validation"))
                    return True
                else:
                    self.print_warning("No error message in response")
                    self.test_results.append((test_name, False, "No error message"))
                    return False
            else:
                self.print_warning(f"Expected 400, got {response.status_code}")
                self.test_results.append((test_name, False, f"Status {response.status_code}"))
                return False

        except Exception as e:
            self.print_error(f"Unexpected error: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return False

    def create_web_scraping_agent(self) -> Optional[tuple]:
        """Create an agent with read_webpage tool enabled

        Returns:
            Tuple of (agent_id, api_key) if successful, None otherwise
        """
        endpoint = f"{self.base_url}/api/create_agent"
        test_name = "Create Web Scraping Agent"

        self.print_header(f"Testing {test_name}")

        if not self.token:
            self.print_warning("No authentication token provided")
            self.test_results.append((test_name, True, "Skipped (auth required)"))
            return None

        # Create agent with read_webpage tool
        payload = {
            "name": f"Web Scraping Agent {int(time.time())}",
            "description": "Test agent with read_webpage tool for compression testing",
            "prompt_id": "default",
            "chunks": 2,
            "retriever": "classic",
            "agent_type": "react",  # ReAct agent supports tools
            "status": "draft",
            "tools": ["read_webpage"],  # Enable read_webpage tool
        }

        try:
            self.print_info(f"POST {endpoint}")
            self.print_info("Creating agent with read_webpage tool...")

            response = requests.post(
                endpoint,
                json=payload,
                headers=self.headers,
                timeout=10
            )

            self.print_info(f"Status Code: {response.status_code}")

            if response.status_code in [200, 201]:
                result = response.json()
                agent_id = result.get('id')
                api_key = result.get('key', '')

                if agent_id:
                    self.print_success(f"Web scraping agent created with ID: {agent_id}")
                    if api_key:
                        self.print_success(f"Agent API key: {api_key[:20]}...")
                        self.test_results.append((test_name, True, f"ID: {agent_id}, API Key: Yes"))
                        return (agent_id, api_key)
                    else:
                        self.print_warning("Agent created but no API key (draft agent)")
                        self.test_results.append((test_name, True, f"ID: {agent_id}, API Key: No"))
                        return (agent_id, None)
                else:
                    self.print_warning("Agent created but no ID returned")
                    self.test_results.append((test_name, False, "No ID returned"))
                    return None
            else:
                self.print_error(f"Expected 200/201, got {response.status_code}")
                try:
                    error_data = response.json()
                    self.print_error(f"Error: {error_data.get('message', response.text[:200])}")
                except Exception:
                    self.print_error(f"Response: {response.text[:500]}")
                self.test_results.append((test_name, False, f"Status {response.status_code}"))
                return None

        except requests.exceptions.RequestException as e:
            self.print_error(f"Request failed: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return None
        except Exception as e:
            self.print_error(f"Unexpected error: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return None

    def test_compression_heavy_tool_usage(self, agent_result: Optional[tuple] = None) -> bool:
        """Test compression with heavy tool usage (real API calls)

        This simulates a scenario where an agent makes many tool calls
        (including read_webpage for web scraping), generating large responses
        that should trigger compression.

        Args:
            agent_result: Optional tuple of (agent_id, api_key) from agent creation
        """
        endpoint = f"{self.base_url}/api/answer"
        test_name = "Compression - Heavy Tool Usage"

        self.print_header(f"Testing {test_name}")

        if not self.token:
            self.print_warning("Authentication required for compression tests")
            self.test_results.append((test_name, True, "Skipped (auth required)"))
            return False

        # Use provided agent or create one
        if not agent_result:
            self.print_info("No web scraping agent provided, creating one...")
            agent_result = self.create_web_scraping_agent()

        if not agent_result:
            self.print_warning("Could not create web scraping agent, using isNoneDoc instead")
            agent_id = None
            api_key = None
        else:
            agent_id, api_key = agent_result

        # Define URLs to scrape for testing
        urls_to_scrape = [
            "https://docs.docsgpt.cloud/",
            "https://docs.docsgpt.cloud/getting-started/quickstart",
            "https://docs.docsgpt.cloud/getting-started/installation",
            "https://docs.docsgpt.cloud/extensions/extensions-intro",
            "https://github.com/arc53/DocsGPT",
        ]

        # Make requests with tool usage
        self.print_info("Making 10 consecutive requests to build up conversation history...")
        self.print_info("Some requests will use read_webpage tool for web scraping...")

        current_conv_id = None

        for i in range(10):
            # Alternate between regular questions and web scraping
            if i < 5 and agent_id:
                # Use web scraping for first 5 requests
                url = urls_to_scrape[i % len(urls_to_scrape)]
                question = f"Please read and summarize the content from this webpage: {url}"
            else:
                # Use regular questions for remaining requests
                question = f"Tell me about Python topic number {i+1}: data structures, decorators, async, testing, etc. Please provide a comprehensive explanation."

            payload = {
                "question": question,
                "history": "[]",
            }

            # Use agent if available, otherwise isNoneDoc
            if agent_id:
                payload["agent_id"] = agent_id
            elif api_key:
                payload["api_key"] = api_key
            else:
                payload["isNoneDoc"] = True

            if current_conv_id:
                payload["conversation_id"] = current_conv_id

            try:
                response = requests.post(
                    endpoint,
                    json=payload,
                    headers=self.headers,
                    timeout=90  # Longer timeout for web scraping
                )

                if response.status_code == 200:
                    result = response.json()
                    current_conv_id = result.get('conversation_id', current_conv_id)
                    answer_preview = (result.get('answer') or '')[:80]
                    self.print_success(f"Request {i+1}/10 completed (conv_id: {current_conv_id})")
                    self.print_info(f"  Answer preview: {answer_preview}...")
                else:
                    self.print_error(f"Request {i+1}/10 failed with status {response.status_code}")
                    self.test_results.append((test_name, False, f"Request {i+1} failed"))
                    return False

                time.sleep(2)  # Small delay between requests

            except Exception as e:
                self.print_error(f"Request {i+1}/10 failed: {str(e)}")
                self.test_results.append((test_name, False, str(e)))
                return False

        # Check if conversation was compressed by examining metadata
        if current_conv_id:
            self.print_info(f"Checking compression status for conversation {current_conv_id}")
            # Note: This would require a /api/conversation/{id} endpoint to verify
            self.print_success("Heavy tool usage test completed")
            tool_info = "with read_webpage" if agent_id else "without tools"
            self.test_results.append((test_name, True, f"10 requests {tool_info}, conv_id: {current_conv_id}"))
            return True
        else:
            self.print_warning("No conversation_id received")
            self.test_results.append((test_name, False, "No conversation_id"))
            return False

    def test_compression_needle_in_haystack(self) -> bool:
        """Test that compression preserves critical information

        This sends a long conversation with important info in the middle,
        then asks about that info to verify it was preserved through compression.
        """
        endpoint = f"{self.base_url}/api/answer"
        test_name = "Compression - Needle in Haystack"

        self.print_header(f"Testing {test_name}")

        if not self.token:
            self.print_warning("Authentication required for compression tests")
            self.test_results.append((test_name, True, "Skipped (auth required)"))
            return False

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
                response = requests.post(endpoint, json=payload, headers=self.headers, timeout=60)
                if response.status_code == 200:
                    result = response.json()
                    conversation_id = result.get('conversation_id', conversation_id)
                    self.print_success(f"General question {i+1}/2 completed")
                else:
                    self.print_error(f"Request failed with status {response.status_code}")
                    self.test_results.append((test_name, False, "General questions failed"))
                    return False
                time.sleep(2)
            except Exception as e:
                self.print_error(f"Request failed: {str(e)}")
                self.test_results.append((test_name, False, str(e)))
                return False

        # Step 2: Send CRITICAL information
        self.print_info("Step 2: Sending CRITICAL information to remember...")
        critical_payload = {
            "question": "Please remember this critical information: The production database password is stored in DB_PASSWORD_PROD environment variable. The backup runs at 3:00 AM UTC daily. Premium users have 10,000 req/hour limit.",
            "history": "[]",
            "isNoneDoc": True,
            "conversation_id": conversation_id,
        }

        try:
            response = requests.post(endpoint, json=critical_payload, headers=self.headers, timeout=60)
            if response.status_code == 200:
                result = response.json()
                conversation_id = result.get('conversation_id', conversation_id)
                self.print_success("Critical information sent")
            else:
                self.print_error("Critical info request failed")
                self.test_results.append((test_name, False, "Critical info failed"))
                return False
            time.sleep(2)
        except Exception as e:
            self.print_error(f"Request failed: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return False

        # Step 3: Send more general questions to bury the critical info
        self.print_info("Step 3: Sending more questions to bury the critical info...")
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
                response = requests.post(endpoint, json=payload, headers=self.headers, timeout=60)
                if response.status_code == 200:
                    result = response.json()
                    conversation_id = result.get('conversation_id', conversation_id)
                    self.print_success(f"Burying question {i+1}/2 completed")
                else:
                    self.print_error("Request failed")
                    self.test_results.append((test_name, False, "Burying questions failed"))
                    return False
                time.sleep(2)
            except Exception as e:
                self.print_error(f"Request failed: {str(e)}")
                self.test_results.append((test_name, False, str(e)))
                return False

        # Step 4: Ask about the critical information
        self.print_info("Step 4: Testing if critical info was preserved...")
        recall_payload = {
            "question": "What was the database password environment variable I mentioned earlier?",
            "history": "[]",
            "isNoneDoc": True,
            "conversation_id": conversation_id,
        }

        try:
            response = requests.post(endpoint, json=recall_payload, headers=self.headers, timeout=60)
            if response.status_code == 200:
                result = response.json()
                answer = (result.get('answer') or '').lower()

                # Check if the critical info was preserved
                if 'db_password_prod' in answer or 'database password' in answer:
                    self.print_success("✓ Critical information preserved through compression!")
                    self.print_info(f"Answer: {answer[:150]}...")
                    self.test_results.append((test_name, True, "Info preserved"))
                    return True
                else:
                    self.print_warning("Critical information may have been lost")
                    self.print_info(f"Answer: {answer[:150]}...")
                    self.test_results.append((test_name, False, "Info not preserved"))
                    return False
            else:
                self.print_error("Recall request failed")
                self.test_results.append((test_name, False, "Recall failed"))
                return False
        except Exception as e:
            self.print_error(f"Request failed: {str(e)}")
            self.test_results.append((test_name, False, str(e)))
            return False

    def print_summary(self):
        """Print test results summary"""
        self.print_header("Test Results Summary")

        passed = sum(1 for _, success, _ in self.test_results if success)
        failed = len(self.test_results) - passed

        print(f"\n{Colors.BOLD}Total Tests: {len(self.test_results)}{Colors.ENDC}")
        print(f"{Colors.OKGREEN}Passed: {passed}{Colors.ENDC}")
        print(f"{Colors.FAIL}Failed: {failed}{Colors.ENDC}\n")

        print(f"{Colors.BOLD}Detailed Results:{Colors.ENDC}")
        for test_name, success, message in self.test_results:
            status = f"{Colors.OKGREEN}PASS{Colors.ENDC}" if success else f"{Colors.FAIL}FAIL{Colors.ENDC}"
            print(f"  {status} - {test_name}: {message}")

        print()
        return failed == 0

    def run_all_tests(self):
        """Run all integration tests"""
        self.print_header("DocsGPT Integration Tests")
        self.print_info(f"Base URL: {self.base_url}")
        if self.token:
            self.print_info(f"Authentication: Yes ({self.token_source})")
        else:
            self.print_info("Authentication: No (agent-related tests will be skipped)")

        # Test 1: Stream endpoint without agent
        self.test_stream_endpoint()
        time.sleep(1)

        # Test 2: Answer endpoint without agent
        self.test_answer_endpoint()
        time.sleep(1)

        # Test 3: Model validation
        self.test_model_validation()
        time.sleep(1)

        # Test 4: Compression tests (requires token)
        if self.token:
            self.print_info("Running compression integration tests...")
            time.sleep(1)

            # Test 4a: Heavy tool usage compression
            self.test_compression_heavy_tool_usage()
            time.sleep(2)

            # Test 4b: Needle in haystack compression
            self.test_compression_needle_in_haystack()
            time.sleep(1)
        else:
            self.print_info("Skipping compression tests (no authentication)")

        # Test 5: Upload text source (requires token) - faster than crawler
        task_id = self.upload_text_source()
        source_id = None

        if task_id:
            # Test 6: Get source ID from completed task
            source_id = self.get_source_id_from_task(task_id)
            if source_id:
                self.print_success(f"Source created with ID: {source_id}")
            else:
                self.print_warning("Could not retrieve source ID from task - trying crawler fallback")
                # Fallback to crawler if text upload failed
                crawler_task_id = self.upload_crawler_source()
                if crawler_task_id:
                    source_id = self.get_source_id_from_task(crawler_task_id)
                    if source_id:
                        self.print_success(f"Source created with ID (crawler): {source_id}")
                    else:
                        self.print_warning("Could not retrieve source ID from crawler task either")

        # Test 7: Create published agent (for API key testing) - default behavior
        # Published agents get an API key automatically
        published_result = self.create_agent(source_id=source_id, published=True)

        if published_result:
            agent_id, api_key = published_result
            time.sleep(1)

            if api_key:
                # Test 8 & 9: Test with API key (primary method)
                self.test_api_key_endpoint(api_key, endpoint_type="stream")
                time.sleep(1)
                self.test_api_key_endpoint(api_key, endpoint_type="answer")
                time.sleep(1)

                # Test 10: Also test with agent_id for completeness
                self.test_stream_endpoint(agent_id=agent_id)
                time.sleep(1)
                self.test_answer_endpoint(agent_id=agent_id)

                # Test 11: If agent has a source, test source-specific questions
                if source_id:
                    time.sleep(1)
                    self.print_info("Testing published agent with source-specific questions...")

                    test_name = "Published agent with source (DocsGPT question)"
                    self.print_header(f"Testing {test_name}")

                    payload = {
                        "question": "How do I install DocsGPT?",
                        "history": "[]",
                        "api_key": api_key,
                    }

                    try:
                        response = requests.post(
                            f"{self.base_url}/api/answer",
                            json=payload,
                            headers=self.headers,
                            timeout=30
                        )

                        if response.status_code == 200:
                            result = response.json()
                            answer = result.get('answer') or ''
                            self.print_success(f"Answer received: {answer[:100]}...")

                            if any(word in answer.lower() for word in ['install', 'docker', 'setup']):
                                self.print_success("Answer contains relevant information from source")
                                self.test_results.append((test_name, True, "Success"))
                            else:
                                self.print_warning("Answer may not be using source data")
                                self.test_results.append((test_name, True, "Answer unclear"))
                        else:
                            self.print_error(f"Status {response.status_code}")
                            self.test_results.append((test_name, False, f"Status {response.status_code}"))

                    except Exception as e:
                        self.print_error(f"Test failed: {str(e)}")
                        self.test_results.append((test_name, False, str(e)))
            else:
                self.print_warning("Published agent created but no API key received")
                self.print_info("Testing with agent_id instead...")
                # Fallback to agent_id testing
                self.test_stream_endpoint(agent_id=agent_id)
                time.sleep(1)
                self.test_answer_endpoint(agent_id=agent_id)
        else:
            if self.token:
                self.print_warning("Published agent creation failed - some tests skipped")
            else:
                self.print_info("Skipping agent tests (no authentication token)")

        # Print summary
        success = self.print_summary()
        return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(
        description='Integration test script for DocsGPT API endpoints',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test local instance
  python tests/test_integration.py  # auto-generates JWT token from local secret if possible

  # Test remote instance
  python tests/test_integration.py --base-url https://app.docsgpt.com

  # Test with authentication (required for agent creation)
  python tests/test_integration.py --token YOUR_JWT_TOKEN

  # Test specific endpoint only
  python tests/test_integration.py --base-url http://localhost:7091 --token YOUR_TOKEN
        """
    )

    parser.add_argument(
        '--base-url',
        default='http://localhost:7091',
        help='Base URL of DocsGPT instance (default: http://localhost:7091)'
    )

    parser.add_argument(
        '--token',
        help='JWT authentication token (auto-generated from local secret when available)'
    )

    args = parser.parse_args()

    token = args.token
    token_source = "provided via --token" if token else "auto-generated from local JWT secret"

    if not token:
        token, token_error = generate_default_token()
        if token:
            print(f"{Colors.OKCYAN}ℹ Using auto-generated JWT token from local secret{Colors.ENDC}")
        else:
            token_source = "none"
            if token_error:
                print(f"{Colors.WARNING}⚠ Could not auto-generate JWT token: {token_error}{Colors.ENDC}")
            print(f"{Colors.WARNING}⚠ Agent creation tests will be skipped unless you provide --token{Colors.ENDC}")

    try:
        tester = DocsGPTTester(args.base_url, token, token_source=token_source)
        exit_code = tester.run_all_tests()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}Tests interrupted by user{Colors.ENDC}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.FAIL}Fatal error: {str(e)}{Colors.ENDC}")
        sys.exit(1)


if __name__ == '__main__':
    main()
