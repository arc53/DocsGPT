"""
Base classes and utilities for DocsGPT integration tests.

This module provides:
- Colors: ANSI color codes for terminal output
- DocsGPTTestBase: Base class with HTTP helpers and output utilities
- generate_jwt_token: JWT token generation for authentication
- create_client_from_args: Factory function to create client from CLI args
"""

import argparse
import json as json_module
import os
from pathlib import Path
from typing import Any, Iterator, Optional, Type, TypeVar

import requests

T = TypeVar("T", bound="DocsGPTTestBase")


class Colors:
    """ANSI color codes for terminal output."""

    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"


def generate_jwt_token() -> tuple[Optional[str], Optional[str]]:
    """
    Generate a JWT token using local secret or environment variable.

    Returns:
        Tuple of (token, error_message). Token is None on failure.
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
        from jose import jwt
    except ImportError:
        return None, "python-jose is not installed (pip install 'python-jose' to auto-generate tokens)."

    try:
        payload = {"sub": "test_integration_user"}
        return jwt.encode(payload, secret, algorithm="HS256"), None
    except Exception as exc:
        return None, f"Failed to generate JWT token: {exc}"


class DocsGPTTestBase:
    """
    Base class for DocsGPT integration tests.

    Provides HTTP helpers, SSE streaming, output formatting, and result tracking.

    Usage:
        client = DocsGPTTestBase("http://localhost:7091", token="...")
        response = client.post("/api/answer", json={"question": "test"})
    """

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        token_source: str = "provided",
    ):
        """
        Initialize test client.

        Args:
            base_url: Base URL of DocsGPT instance (e.g., "http://localhost:7091")
            token: Optional JWT authentication token
            token_source: Description of token source for logging
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.token_source = token_source
        self.headers: dict[str, str] = {}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.test_results: list[tuple[str, bool, str]] = []

    # -------------------------------------------------------------------------
    # HTTP Helper Methods
    # -------------------------------------------------------------------------

    def get(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        timeout: int = 30,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Make a GET request.

        Args:
            path: API path (e.g., "/api/sources")
            params: Optional query parameters
            timeout: Request timeout in seconds
            **kwargs: Additional arguments passed to requests.get

        Returns:
            Response object
        """
        url = f"{self.base_url}{path}"
        return requests.get(
            url,
            params=params,
            headers={**self.headers, **kwargs.pop("headers", {})},
            timeout=timeout,
            **kwargs,
        )

    def post(
        self,
        path: str,
        json: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, Any]] = None,
        timeout: int = 30,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Make a POST request.

        Args:
            path: API path (e.g., "/api/answer")
            json: Optional JSON body
            data: Optional form data
            files: Optional files for multipart upload
            timeout: Request timeout in seconds
            **kwargs: Additional arguments passed to requests.post

        Returns:
            Response object
        """
        url = f"{self.base_url}{path}"
        return requests.post(
            url,
            json=json,
            data=data,
            files=files,
            headers={**self.headers, **kwargs.pop("headers", {})},
            timeout=timeout,
            **kwargs,
        )

    def put(
        self,
        path: str,
        json: Optional[dict[str, Any]] = None,
        timeout: int = 30,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Make a PUT request.

        Args:
            path: API path (e.g., "/api/update_agent/123")
            json: Optional JSON body
            timeout: Request timeout in seconds
            **kwargs: Additional arguments passed to requests.put

        Returns:
            Response object
        """
        url = f"{self.base_url}{path}"
        return requests.put(
            url,
            json=json,
            headers={**self.headers, **kwargs.pop("headers", {})},
            timeout=timeout,
            **kwargs,
        )

    def delete(
        self,
        path: str,
        json: Optional[dict[str, Any]] = None,
        timeout: int = 30,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Make a DELETE request.

        Args:
            path: API path (e.g., "/api/delete_agent")
            json: Optional JSON body
            timeout: Request timeout in seconds
            **kwargs: Additional arguments passed to requests.delete

        Returns:
            Response object
        """
        url = f"{self.base_url}{path}"
        return requests.delete(
            url,
            json=json,
            headers={**self.headers, **kwargs.pop("headers", {})},
            timeout=timeout,
            **kwargs,
        )

    def post_stream(
        self,
        path: str,
        json: Optional[dict[str, Any]] = None,
        timeout: int = 60,
        **kwargs: Any,
    ) -> Iterator[dict[str, Any]]:
        """
        Make a streaming POST request and yield SSE events.

        Args:
            path: API path (e.g., "/stream")
            json: Optional JSON body
            timeout: Request timeout in seconds
            **kwargs: Additional arguments passed to requests.post

        Yields:
            Parsed JSON data from each SSE event

        Example:
            for event in client.post_stream("/stream", json={"question": "test"}):
                if event.get("type") == "answer":
                    print(event.get("message"))
        """
        url = f"{self.base_url}{path}"
        response = requests.post(
            url,
            json=json,
            headers={**self.headers, **kwargs.pop("headers", {})},
            stream=True,
            timeout=timeout,
            **kwargs,
        )

        # Store response for status code checking
        self._last_stream_response = response

        if response.status_code != 200:
            # Yield error event for non-200 responses
            yield {"type": "error", "status_code": response.status_code, "text": response.text[:500]}
            return

        for line in response.iter_lines():
            if line:
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    data_str = line_str[6:]  # Remove 'data: ' prefix
                    try:
                        data = json_module.loads(data_str)
                        yield data
                        if data.get("type") == "end":
                            break
                    except json_module.JSONDecodeError:
                        pass

    # -------------------------------------------------------------------------
    # Output Helper Methods
    # -------------------------------------------------------------------------

    def print_header(self, message: str) -> None:
        """Print a colored header."""
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{message}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}\n")

    def print_success(self, message: str) -> None:
        """Print a success message."""
        print(f"{Colors.OKGREEN}[PASS] {message}{Colors.ENDC}")

    def print_error(self, message: str) -> None:
        """Print an error message."""
        print(f"{Colors.FAIL}[FAIL] {message}{Colors.ENDC}")

    def print_info(self, message: str) -> None:
        """Print an info message."""
        print(f"{Colors.OKCYAN}[INFO] {message}{Colors.ENDC}")

    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        print(f"{Colors.WARNING}[WARN] {message}{Colors.ENDC}")

    # -------------------------------------------------------------------------
    # Result Tracking Methods
    # -------------------------------------------------------------------------

    def record_result(self, test_name: str, success: bool, message: str) -> None:
        """
        Record a test result.

        Args:
            test_name: Name of the test
            success: Whether the test passed
            message: Result message or error details
        """
        self.test_results.append((test_name, success, message))

    def print_summary(self) -> bool:
        """
        Print test results summary.

        Returns:
            True if all tests passed, False otherwise
        """
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

    # -------------------------------------------------------------------------
    # Assertion Helpers
    # -------------------------------------------------------------------------

    def assert_status(
        self,
        response: requests.Response,
        expected: int,
        test_name: str,
    ) -> bool:
        """
        Assert response status code and record result.

        Args:
            response: Response object to check
            expected: Expected status code
            test_name: Name of the test for recording

        Returns:
            True if status matches, False otherwise
        """
        if response.status_code == expected:
            return True
        else:
            self.print_error(f"Expected {expected}, got {response.status_code}")
            self.print_error(f"Response: {response.text[:500]}")
            self.record_result(test_name, False, f"Status {response.status_code}")
            return False

    def assert_json_key(
        self,
        data: dict[str, Any],
        key: str,
        test_name: str,
    ) -> bool:
        """
        Assert JSON response contains a key.

        Args:
            data: JSON response data
            key: Expected key
            test_name: Name of the test for recording

        Returns:
            True if key exists, False otherwise
        """
        if key in data:
            return True
        else:
            self.print_error(f"Missing key '{key}' in response")
            self.record_result(test_name, False, f"Missing key: {key}")
            return False

    # -------------------------------------------------------------------------
    # Convenience Properties
    # -------------------------------------------------------------------------

    @property
    def is_authenticated(self) -> bool:
        """Check if client has authentication token."""
        return self.token is not None

    def require_auth(self, test_name: str) -> bool:
        """
        Check authentication and record skip if not authenticated.

        Args:
            test_name: Name of the test

        Returns:
            True if authenticated, False otherwise (test skipped)
        """
        if not self.is_authenticated:
            self.print_warning("No authentication token provided")
            self.print_info("Skipping test (auth required)")
            self.record_result(test_name, True, "Skipped (auth required)")
            return False
        return True


# -----------------------------------------------------------------------------
# Factory Function
# -----------------------------------------------------------------------------


def create_client_from_args(
    client_class: Type[T],
    description: str = "DocsGPT Integration Tests",
) -> T:
    """
    Create a test client from command-line arguments.

    Parses --base-url and --token arguments, and handles JWT token generation.

    Args:
        client_class: The test class to instantiate (must inherit from DocsGPTTestBase)
        description: Description for the argument parser

    Returns:
        An instance of the provided client_class

    Example:
        class ChatTests(DocsGPTTestBase):
            def run_all(self):
                ...

        if __name__ == "__main__":
            client = create_client_from_args(ChatTests)
            sys.exit(0 if client.run_all() else 1)
    """
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--base-url",
        default=os.getenv("DOCSGPT_BASE_URL", "http://localhost:7091"),
        help="Base URL of DocsGPT instance (default: http://localhost:7091)",
    )

    parser.add_argument(
        "--token",
        default=os.getenv("JWT_TOKEN"),
        help="JWT authentication token (auto-generated from local secret when available)",
    )

    args = parser.parse_args()

    # Determine token and source
    token = args.token
    token_source = "provided via --token" if token else "none"

    if not token:
        token, token_error = generate_jwt_token()
        if token:
            token_source = "auto-generated from local secret"
            print(f"{Colors.OKCYAN}[INFO] Using auto-generated JWT token{Colors.ENDC}")
        elif token_error:
            print(f"{Colors.WARNING}[WARN] Could not auto-generate token: {token_error}{Colors.ENDC}")
            print(f"{Colors.WARNING}[WARN] Tests requiring auth will be skipped{Colors.ENDC}")

    return client_class(args.base_url, token=token, token_source=token_source)
