"""Token counting utilities for compression."""

import logging
from typing import Any, Dict, List

from docsgpt.utils import num_tokens_from_string
from docsgpt.core.settings import settings
from docsgpt.api.answer.services.compression.types import (
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

    # Characters of a Responses reasoning item's ``encrypted_content`` per
    # reasoning token it stands for. The provider decrypts a replayed item and
    # bills the reasoning in full as input: measured on Azure gpt-6-astra, two
    # turns' items (13,520 encrypted characters, 1,534 reasoning tokens) added
    # 1,538 input tokens to the next turn, ~8.8 characters a token. Rounded
    # down so the estimate errs high.
    _REASONING_CHARS_PER_TOKEN = 8

    @staticmethod
    def count_reasoning_items(items: Any) -> int:
        """Tokens the provider bills for replayed Responses reasoning items.

        Args:
            items: Reasoning items as stored (``encrypted_content`` and an
                optional ``summary``); repeats of one id count once.

        Returns:
            The estimate, 0 for anything that is not a list of items.
        """
        if not isinstance(items, list):
            return 0
        seen: set = set()
        total = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if item_id:
                if item_id in seen:
                    continue
                seen.add(item_id)
            encrypted = item.get("encrypted_content")
            if isinstance(encrypted, str):
                total += len(encrypted) // TokenCounter._REASONING_CHARS_PER_TOKEN
            for part in item.get("summary") or ():
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    total += num_tokens_from_string(part["text"])
        return total

    @staticmethod
    def replayed_reasoning_tokens(query: Dict[str, Any]) -> int:
        """Tokens of the reasoning a history turn carries when replayed on the Responses API.

        Each replayed tool call brings the reasoning items of the response
        that made it, and the answer brings its own (``agents/base.py``
        ``_build_messages``). None of it is in the turn's text, so a count of
        the text alone sees a fraction of what is sent: in production a
        conversation measured 185k tokens locally and was billed 347k.

        Args:
            query: A history entry with its ``metadata.responses_state``.

        Returns:
            The estimate; 0 when the entry has no Responses state.
        """
        metadata = query.get("metadata") if isinstance(query, dict) else None
        state = metadata.get("responses_state") if isinstance(metadata, dict) else None
        if not isinstance(state, dict):
            return 0
        items: List[Any] = []
        per_call = state.get("reasoning_for_calls")
        if isinstance(per_call, dict):
            for tool_call in query.get("tool_calls") or ():
                if isinstance(tool_call, dict):
                    call_items = per_call.get(str(tool_call.get("call_id")))
                    if isinstance(call_items, list):
                        items.extend(call_items)
        if isinstance(state.get("reasoning_items"), list):
            items.extend(state["reasoning_items"])
        return TokenCounter.count_reasoning_items(items)

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
            # Images a tool returned ride beside its text (``tool_images``).
            images = message.get("images")
            if isinstance(images, list):
                total_tokens += TokenCounter._IMAGE_PART_TOKEN_ESTIMATE * len(images)
            # Replayed reasoning is sent (and billed) with the message.
            total_tokens += TokenCounter.count_reasoning_items(message.get("responses_reasoning_items"))
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
        queries: List[Dict[str, Any]],
        include_tool_calls: bool = True,
        include_reasoning: bool = False,
    ) -> int:
        """
        Count tokens across multiple query objects.

        Args:
            queries: List of query objects from conversation
            include_tool_calls: Whether to count tool call tokens
            include_reasoning: Also count the Responses reasoning each turn
                replays (``replayed_reasoning_tokens``); for a model on the
                Responses API, where it is sent.

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
            if include_reasoning:
                total_tokens += TokenCounter.replayed_reasoning_tokens(query)

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
    def count_effective_conversation_tokens(
        conversation: Dict[str, Any], include_reasoning: bool = False
    ) -> int:
        """Tokens the next turn will actually replay.

        The latest summary plus the queries after its compression point, or
        everything when the conversation was never compressed.
        ``count_conversation_tokens`` counts the raw history regardless, which
        is what made every turn after a compression trigger it again.
        ``include_reasoning`` adds the Responses reasoning the turns replay.
        """
        try:
            queries = conversation.get("queries", []) or []
            metadata = conversation.get("compression_metadata") or {}
            points = metadata.get("compression_points") or []
            if not (metadata.get("is_compressed") and points):
                return TokenCounter.count_query_tokens(
                    queries, include_reasoning=include_reasoning
                )
            latest = latest_usable_compression_point(points)
            if latest is None:
                # Only unusable (empty) points: the raw history is what the
                # next turn will replay.
                return TokenCounter.count_query_tokens(
                    queries, include_reasoning=include_reasoning
                )
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
            return summary_tokens + TokenCounter.count_query_tokens(
                recent, include_reasoning=include_reasoning
            )
        except Exception as e:
            logger.error(f"Error calculating effective conversation tokens: {str(e)}")
            return 0
