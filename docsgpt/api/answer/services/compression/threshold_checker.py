"""Compression threshold checking logic."""

import logging
from typing import Any, Dict

from docsgpt.core.model_utils import cap_context_window, get_model_capabilities, get_token_limit
from docsgpt.core.settings import settings
from docsgpt.api.answer.services.compression.token_counter import TokenCounter

logger = logging.getLogger(__name__)


def uses_responses_api(model_id: str, user_id: str | None) -> bool:
    """Whether ``model_id`` speaks the Responses API, where history replays its reasoning."""
    try:
        capabilities = get_model_capabilities(model_id, user_id=user_id) or {}
    except Exception:
        return False
    return capabilities.get("api_flavor") == "responses"


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
        user_id: str | None = None,
        context_window_limit: int | None = None,
    ) -> bool:
        """
        Determine if compression is needed.

        Args:
            conversation: Full conversation document
            model_id: Target model for this request
            current_query_tokens: Estimated tokens for current query
            user_id: Owner — needed so per-user BYOM custom-model UUIDs
                resolve when looking up the context window.
            context_window_limit: The agent's context limit; the threshold
                is a share of it when it is below the model's window.

        Returns:
            True if tokens >= threshold% of context window
        """
        try:
            # What the next turn will replay: summary + queries after the
            # last compression point, or the raw history when never compressed.
            # On the Responses API every replayed tool call also carries its
            # reasoning, billed in full; left out, the check read 70% of the
            # window while the provider was sent 133%.
            total_tokens = TokenCounter.count_effective_conversation_tokens(
                conversation, include_reasoning=uses_responses_api(model_id, user_id)
            )
            total_tokens += current_query_tokens

            # Get context window limit for model, lowered to the agent's limit
            context_limit = cap_context_window(
                get_token_limit(model_id, user_id=user_id), context_window_limit
            )

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

    def history_over_limit(
        self,
        conversation: Dict[str, Any],
        model_id: str,
        history_token_limit: int | None,
        user_id: str | None = None,
    ) -> bool:
        """Whether the messages replayed word for word have reached the agent's history limit.

        The summary is left out: it is bounded by the compression prompt, and
        counted in it a long summary would compress again on every turn.

        Args:
            conversation: Full conversation document.
            model_id: Target model for this request.
            history_token_limit: The agent's ``config.history_token_limit``;
                None never trips.
            user_id: Owner, so a per-user BYOM model's API flavor resolves.

        Returns:
            True if the recent messages are at or above the limit.
        """
        if not history_token_limit:
            return False
        try:
            recent_tokens = TokenCounter.count_recent_conversation_tokens(
                conversation, include_reasoning=uses_responses_api(model_id, user_id)
            )
        except Exception as e:
            logger.error(f"Error checking history limit: {str(e)}", exc_info=True)
            return False
        if recent_tokens >= history_token_limit:
            logger.info(
                f"HISTORY LIMIT REACHED: {recent_tokens} recent tokens / {history_token_limit} limit"
            )
            return True
        return False

    def check_message_tokens(
        self, messages: list, model_id: str, user_id: str | None = None
    ) -> bool:
        """
        Check if message list exceeds threshold.

        Args:
            messages: List of message dicts
            model_id: Target model
            user_id: Owner — needed so per-user BYOM custom-model UUIDs
                resolve when looking up the context window.

        Returns:
            True if at or above threshold
        """
        try:
            current_tokens = TokenCounter.count_message_tokens(messages)
            context_limit = get_token_limit(model_id, user_id=user_id)
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
