"""Compression threshold checking logic."""

import logging
from typing import Any, Dict

from application.core.model_utils import get_token_limit
from application.core.settings import settings
from application.api.answer.services.compression.token_counter import TokenCounter

logger = logging.getLogger(__name__)


class CompressionThresholdChecker:
    """Determines if compression is needed based on token thresholds."""

    def __init__(self, threshold_percentage: float = None):
        """
        Initialize threshold checker.

        Args:
            threshold_percentage: Percentage of context to use as threshold
                                 (defaults to settings.COMPRESSION_THRESHOLD_PERCENTAGE)
        """
        self.threshold_percentage = (
            threshold_percentage or settings.COMPRESSION_THRESHOLD_PERCENTAGE
        )

    def should_compress(
        self,
        conversation: Dict[str, Any],
        model_id: str,
        current_query_tokens: int = 500,
    ) -> bool:
        """
        Determine if compression is needed.

        Args:
            conversation: Full conversation document
            model_id: Target model for this request
            current_query_tokens: Estimated tokens for current query

        Returns:
            True if tokens >= threshold% of context window
        """
        try:
            # Calculate total tokens in conversation
            total_tokens = TokenCounter.count_conversation_tokens(conversation)
            total_tokens += current_query_tokens

            # Get context window limit for model
            context_limit = get_token_limit(model_id)

            # Calculate threshold
            threshold = int(context_limit * self.threshold_percentage)

            compression_needed = total_tokens >= threshold
            percentage_used = (total_tokens / context_limit) * 100

            if compression_needed:
                logger.warning(
                    f"COMPRESSION TRIGGERED: {total_tokens} tokens / {context_limit} limit "
                    f"({percentage_used:.1f}% used, threshold: {self.threshold_percentage * 100:.0f}%)"
                )
            else:
                logger.info(
                    f"Compression check: {total_tokens}/{context_limit} tokens "
                    f"({percentage_used:.1f}% used, threshold: {self.threshold_percentage * 100:.0f}%) - No compression needed"
                )

            return compression_needed

        except Exception as e:
            logger.error(f"Error checking compression need: {str(e)}", exc_info=True)
            return False

    def check_message_tokens(self, messages: list, model_id: str) -> bool:
        """
        Check if message list exceeds threshold.

        Args:
            messages: List of message dicts
            model_id: Target model

        Returns:
            True if at or above threshold
        """
        try:
            current_tokens = TokenCounter.count_message_tokens(messages)
            context_limit = get_token_limit(model_id)
            threshold = int(context_limit * self.threshold_percentage)

            if current_tokens >= threshold:
                logger.warning(
                    f"Message context limit approaching: {current_tokens}/{context_limit} tokens "
                    f"({(current_tokens/context_limit)*100:.1f}%)"
                )
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking message tokens: {str(e)}", exc_info=True)
            return False
