from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestCompressionThresholdChecker:

    def _make_checker(self, pct=0.7):
        from application.api.answer.services.compression.threshold_checker import (
            CompressionThresholdChecker,
        )

        return CompressionThresholdChecker(threshold_percentage=pct)

    @patch(
        "application.api.answer.services.compression.threshold_checker.get_token_limit",
        return_value=8000,
    )
    @patch(
        "application.api.answer.services.compression.threshold_checker.TokenCounter.count_message_tokens",
        return_value=6000,
    )
    def test_check_message_tokens_above_threshold(self, mock_count, mock_limit):
        checker = self._make_checker(0.7)
        assert checker.check_message_tokens([{"role": "user"}], "gpt-4") is True

    @patch(
        "application.api.answer.services.compression.threshold_checker.get_token_limit",
        return_value=8000,
    )
    @patch(
        "application.api.answer.services.compression.threshold_checker.TokenCounter.count_message_tokens",
        return_value=1000,
    )
    def test_check_message_tokens_below_threshold(self, mock_count, mock_limit):
        checker = self._make_checker(0.7)
        assert checker.check_message_tokens([{"role": "user"}], "gpt-4") is False

    @patch(
        "application.api.answer.services.compression.threshold_checker.TokenCounter.count_message_tokens",
        side_effect=Exception("Token error"),
    )
    def test_check_message_tokens_exception_returns_false(self, mock_count):
        checker = self._make_checker(0.7)
        assert checker.check_message_tokens([], "gpt-4") is False
