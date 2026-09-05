"""Token counting utilities for compression."""

import logging
from typing import Any, Dict, List

from application.utils import num_tokens_from_string
from application.core.settings import settings
from application.api.answer.services.compression.types import (
    is_compression_summary_row,
    latest_usable_compression_point,
)

logger = logging.getLogger(__name__)


class TokenCounter:
    """Centralized token counting for conversations and messages."""

    # Per-image token estimate. Provider tokenizers vary widely
    # (Gemini ~258, GPT-4o 85-1500, Claude ~1500) and the actual cost
    # depends on resolution/detail we can't see here. Errs slightly high
    # so the threshold check stays conservative.
    _IMAGE_PART_TOKEN_ESTIMATE = 1500

    @staticmethod
    def count_message_tokens(messages: List[Dict]) -> int:
        """
        Calculate total tokens in a list of messages.

        Args:
            messages: List of message dicts with 'content' field

        Returns:
            Total token count
        """
        total_tokens = 0
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                total_tokens += num_tokens_from_string(content)
            elif isinstance(content, list):
                # Handle structured content (tool calls, image parts, etc.)
                for item in content:
                    if isinstance(item, dict):
                        total_tokens += TokenCounter._count_content_part(item)
        return total_tokens

    @staticmethod
    def _count_content_part(item: Dict) -> int:
        # Image/file attachments are billed by the provider per image,
        # not proportional to the inline bytes/base64 string.
        # ``str(item)`` on a 1MB image inflates the count by ~10000x,
        # which trips spurious compression and overflows downstream
        # input limits.
        item_type = item.get("type")

        if "files" in item:
            files = item.get("files")
            count = len(files) if isinstance(files, list) and files else 1
            return TokenCounter._IMAGE_PART_TOKEN_ESTIMATE * count

        if "image_url" in item or item_type in {
            "image",
            "image_url",
            "input_image",
            "file",
        }:
            return TokenCounter._IMAGE_PART_TOKEN_ESTIMATE

        return num_tokens_from_string(str(item))

    @staticmethod
    def count_query_tokens(
        queries: List[Dict[str, Any]], include_tool_calls: bool = True
    ) -> int:
        """
        Count tokens across multiple query objects.

        Args:
            queries: List of query objects from conversation
            include_tool_calls: Whether to count tool call tokens

        Returns:
            Total token count
        """
        total_tokens = 0

        for query in queries:
            # Count prompt and response tokens
            if "prompt" in query:
                total_tokens += num_tokens_from_string(query["prompt"])
            if "response" in query:
                total_tokens += num_tokens_from_string(query["response"])
            if "thought" in query:
                total_tokens += num_tokens_from_string(query.get("thought", ""))

            # Count tool call tokens
            if include_tool_calls and "tool_calls" in query:
                for tool_call in query["tool_calls"]:
                    tool_call_string = (
                        f"Tool: {tool_call.get('tool_name')} | "
                        f"Action: {tool_call.get('action_name')} | "
                        f"Args: {tool_call.get('arguments')} | "
                        f"Response: {tool_call.get('result')}"
                    )
                    total_tokens += num_tokens_from_string(tool_call_string)

        return total_tokens

    @staticmethod
    def count_conversation_tokens(
        conversation: Dict[str, Any], include_system_prompt: bool = False
    ) -> int:
        """
        Calculate total tokens in a conversation.

        Args:
            conversation: Conversation document
            include_system_prompt: Whether to include system prompt in count

        Returns:
            Total token count
        """
        try:
            queries = conversation.get("queries", [])
            total_tokens = TokenCounter.count_query_tokens(queries)

            # Add system prompt tokens if requested
            if include_system_prompt:
                # Rough estimate for system prompt
                total_tokens += settings.RESERVED_TOKENS.get("system_prompt", 500)

            return total_tokens

        except Exception as e:
            logger.error(f"Error calculating conversation tokens: {str(e)}")
            return 0

    @staticmethod
    def count_effective_conversation_tokens(conversation: Dict[str, Any]) -> int:
        """Tokens the next turn will actually replay.

        The latest summary plus the queries after its compression point, or
        everything when the conversation was never compressed.
        ``count_conversation_tokens`` counts the raw history regardless, which
        is what made every turn after a compression trigger it again.
        """
        try:
            queries = conversation.get("queries", []) or []
            metadata = conversation.get("compression_metadata") or {}
            points = metadata.get("compression_points") or []
            if not (metadata.get("is_compressed") and points):
                return TokenCounter.count_query_tokens(queries)
            latest = latest_usable_compression_point(points)
            if latest is None:
                # Only unusable (empty) points: the raw history is what the
                # next turn will replay.
                return TokenCounter.count_query_tokens(queries)
            try:
                last_index = int(latest.get("query_index", -1))
            except (TypeError, ValueError):
                last_index = -1
            recent = [
                q
                for q in queries[last_index + 1 :]
                if not is_compression_summary_row(q)
            ]
            summary_tokens = TokenCounter.count_message_tokens(
                [{"content": latest.get("compressed_summary") or ""}]
            )
            return summary_tokens + TokenCounter.count_query_tokens(recent)
        except Exception as e:
            logger.error(f"Error calculating effective conversation tokens: {str(e)}")
            return 0
