#!/usr/bin/env python3
"""
Integration tests for DocsGPT analytics endpoints.

Endpoints tested:
- /api/get_feedback_analytics (POST) - Feedback analytics
- /api/get_message_analytics (POST) - Message analytics
- /api/get_token_analytics (POST) - Token usage analytics
- /api/get_user_logs (POST) - User activity logs

Usage:
    python tests/integration/test_analytics.py
    python tests/integration/test_analytics.py --base-url http://localhost:7091
    python tests/integration/test_analytics.py --token YOUR_JWT_TOKEN
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


class AnalyticsTests(DocsGPTTestBase):
    """Integration tests for analytics endpoints."""

    # -------------------------------------------------------------------------
    # Feedback Analytics Tests
    # -------------------------------------------------------------------------

    def test_get_feedback_analytics(self) -> bool:
        """Test getting feedback analytics."""
        test_name = "Get feedback analytics"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/get_feedback_analytics",
                json={"date_range": "last_30_days"},
                timeout=15,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()
            self.print_success("Retrieved feedback analytics")
            self.print_info(f"Data points: {len(result) if isinstance(result, list) else 'object'}")
            self.record_result(test_name, True, "Analytics retrieved")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_feedback_analytics_with_filters(self) -> bool:
        """Test feedback analytics with filters."""
        test_name = "Feedback analytics filtered"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/get_feedback_analytics",
                json={
                    "date_range": "last_7_days",
                    "agent_id": None,
                },
                timeout=15,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            self.print_success("Retrieved filtered feedback analytics")
            self.record_result(test_name, True, "Filtered analytics retrieved")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Message Analytics Tests
    # -------------------------------------------------------------------------

    def test_get_message_analytics(self) -> bool:
        """Test getting message analytics."""
        test_name = "Get message analytics"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/get_message_analytics",
                json={"date_range": "last_30_days"},
                timeout=15,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()
            self.print_success("Retrieved message analytics")
            self.print_info(f"Data: {type(result).__name__}")
            self.record_result(test_name, True, "Analytics retrieved")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_message_analytics_with_agent(self) -> bool:
        """Test message analytics for specific agent."""
        test_name = "Message analytics by agent"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/get_message_analytics",
                json={
                    "date_range": "last_7_days",
                    "agent_id": None,
                },
                timeout=15,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            self.print_success("Retrieved agent message analytics")
            self.record_result(test_name, True, "Agent analytics retrieved")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Token Analytics Tests
    # -------------------------------------------------------------------------

    def test_get_token_analytics(self) -> bool:
        """Test getting token usage analytics."""
        test_name = "Get token analytics"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/get_token_analytics",
                json={"date_range": "last_30_days"},
                timeout=15,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()
            self.print_success("Retrieved token analytics")
            self.print_info(f"Data: {type(result).__name__}")
            self.record_result(test_name, True, "Analytics retrieved")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_token_analytics_breakdown(self) -> bool:
        """Test token analytics with breakdown."""
        test_name = "Token analytics breakdown"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/get_token_analytics",
                json={
                    "date_range": "last_7_days",
                    "breakdown": "daily",
                },
                timeout=15,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            self.print_success("Retrieved token analytics breakdown")
            self.record_result(test_name, True, "Breakdown retrieved")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # User Logs Tests
    # -------------------------------------------------------------------------

    def test_get_user_logs(self) -> bool:
        """Test getting user activity logs."""
        test_name = "Get user logs"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/get_user_logs",
                json={"date_range": "last_30_days"},
                timeout=15,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            result = response.json()
            self.print_success("Retrieved user logs")
            self.print_info(f"Logs: {len(result) if isinstance(result, list) else 'object'}")
            self.record_result(test_name, True, "Logs retrieved")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    def test_get_user_logs_paginated(self) -> bool:
        """Test user logs with pagination."""
        test_name = "User logs paginated"
        self.print_header(test_name)

        if not self.require_auth(test_name):
            return True

        try:
            response = self.post(
                "/api/get_user_logs",
                json={
                    "date_range": "last_7_days",
                    "page": 1,
                    "per_page": 10,
                },
                timeout=15,
            )

            if not self.assert_status(response, 200, test_name):
                return False

            self.print_success("Retrieved paginated user logs")
            self.record_result(test_name, True, "Paginated logs retrieved")
            return True

        except Exception as e:
            self.print_error(f"Exception: {e}")
            self.record_result(test_name, False, str(e))
            return False

    # -------------------------------------------------------------------------
    # Test Runner
    # -------------------------------------------------------------------------

    def run_all(self) -> bool:
        """Run all analytics tests."""
        self.print_header("DocsGPT Analytics Integration Tests")
        self.print_info(f"Base URL: {self.base_url}")
        self.print_info(f"Auth: {self.token_source}")

        # Feedback analytics
        self.test_get_feedback_analytics()
        self.test_get_feedback_analytics_with_filters()

        # Message analytics
        self.test_get_message_analytics()
        self.test_get_message_analytics_with_agent()

        # Token analytics
        self.test_get_token_analytics()
        self.test_get_token_analytics_breakdown()

        # User logs
        self.test_get_user_logs()
        self.test_get_user_logs_paginated()

        return self.print_summary()


def main():
    """Main entry point."""
    client = create_client_from_args(AnalyticsTests, "DocsGPT Analytics Integration Tests")
    exit_code = 0 if client.run_all() else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
