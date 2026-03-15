"""Token counting utilities for compression."""

import logging
from typing import Any, Dict, List

from application.utils import num_tokens_from_string
from application.core.settings import settings

logger = logging.getLogger(__name__)


class TokenCounter:
    """Centralized token counting for conversations and messages."""

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
                # Handle structured content (tool calls, etc.)
                for item in content:
                    if isinstance(item, dict):
                        total_tokens += num_tokens_from_string(str(item))
        return total_tokens

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
