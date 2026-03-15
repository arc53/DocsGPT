"""Message reconstruction utilities for compression."""

import logging
import uuid
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MessageBuilder:
    """Builds message arrays from compressed context."""

    @staticmethod
    def build_from_compressed_context(
        system_prompt: str,
        compressed_summary: Optional[str],
        recent_queries: List[Dict],
        include_tool_calls: bool = False,
        context_type: str = "pre_request",
    ) -> List[Dict]:
        """
        Build messages from compressed context.

        Args:
            system_prompt: Original system prompt
            compressed_summary: Compressed summary (if any)
            recent_queries: Recent uncompressed queries
            include_tool_calls: Whether to include tool calls from history
            context_type: Type of context ('pre_request' or 'mid_execution')

        Returns:
            List of message dicts ready for LLM
        """
        # Append compression summary to system prompt if present
        if compressed_summary:
            system_prompt = MessageBuilder._append_compression_context(
                system_prompt, compressed_summary, context_type
            )

        messages = [{"role": "system", "content": system_prompt}]

        # Add recent history
        for query in recent_queries:
            if "prompt" in query and "response" in query:
                messages.append({"role": "user", "content": query["prompt"]})
                messages.append({"role": "assistant", "content": query["response"]})

            # Add tool calls from history if present
            if include_tool_calls and "tool_calls" in query:
                for tool_call in query["tool_calls"]:
                    call_id = tool_call.get("call_id") or str(uuid.uuid4())

                    function_call_dict = {
                        "function_call": {
                            "name": tool_call.get("action_name"),
                            "args": tool_call.get("arguments"),
                            "call_id": call_id,
                        }
                    }
                    function_response_dict = {
                        "function_response": {
                            "name": tool_call.get("action_name"),
                            "response": {"result": tool_call.get("result")},
                            "call_id": call_id,
                        }
                    }

                    messages.append(
                        {"role": "assistant", "content": [function_call_dict]}
                    )
                    messages.append(
                        {"role": "tool", "content": [function_response_dict]}
                    )

        # If no recent queries (everything was compressed), add a continuation user message
        if len(recent_queries) == 0 and compressed_summary:
            messages.append({
                "role": "user",
                "content": "Please continue with the remaining tasks based on the context above."
            })
            logger.info("Added continuation user message to maintain proper turn-taking after full compression")

        return messages

    @staticmethod
    def _append_compression_context(
        system_prompt: str, compressed_summary: str, context_type: str = "pre_request"
    ) -> str:
        """
        Append compression context to system prompt.

        Args:
            system_prompt: Original system prompt
            compressed_summary: Summary to append
            context_type: Type of compression context

        Returns:
            Updated system prompt
        """
        # Remove existing compression context if present
        if "This session is being continued" in system_prompt or "Context window limit reached" in system_prompt:
            parts = system_prompt.split("\n\n---\n\n")
            system_prompt = parts[0]

        # Build appropriate context message based on type
        if context_type == "mid_execution":
            context_message = (
                "\n\n---\n\n"
                "Context window limit reached during execution. "
                "Previous conversation has been compressed to fit within limits. "
                "The conversation is summarized below:\n\n"
                f"{compressed_summary}"
            )
        else:  # pre_request
            context_message = (
                "\n\n---\n\n"
                "This session is being continued from a previous conversation that "
                "has been compressed to fit within context limits. "
                "The conversation is summarized below:\n\n"
                f"{compressed_summary}"
            )

        return system_prompt + context_message

    @staticmethod
    def rebuild_messages_after_compression(
        messages: List[Dict],
        compressed_summary: Optional[str],
        recent_queries: List[Dict],
        include_current_execution: bool = False,
        include_tool_calls: bool = False,
    ) -> Optional[List[Dict]]:
        """
        Rebuild the message list after compression so tool execution can continue.

        Args:
            messages: Original message list
            compressed_summary: Compressed summary
            recent_queries: Recent uncompressed queries
            include_current_execution: Whether to preserve current execution messages
            include_tool_calls: Whether to include tool calls from history

        Returns:
            Rebuilt message list or None if failed
        """
        # Find the system message
        system_message = next(
            (msg for msg in messages if msg.get("role") == "system"), None
        )
        if not system_message:
            logger.warning("No system message found in messages list")
            return None

        # Update system message with compressed summary
        if compressed_summary:
            content = system_message.get("content", "")
            system_message["content"] = MessageBuilder._append_compression_context(
                content, compressed_summary, "mid_execution"
            )
            logger.info(
                "Appended compression summary to system prompt (truncated): %s",
                (
                    compressed_summary[:500] + "..."
                    if len(compressed_summary) > 500
                    else compressed_summary
                ),
            )

        rebuilt_messages = [system_message]

        # Add recent history from compressed context
        for query in recent_queries:
            if "prompt" in query and "response" in query:
                rebuilt_messages.append({"role": "user", "content": query["prompt"]})
                rebuilt_messages.append(
                    {"role": "assistant", "content": query["response"]}
                )

            # Add tool calls from history if present
            if include_tool_calls and "tool_calls" in query:
                for tool_call in query["tool_calls"]:
                    call_id = tool_call.get("call_id") or str(uuid.uuid4())

                    function_call_dict = {
                        "function_call": {
                            "name": tool_call.get("action_name"),
                            "args": tool_call.get("arguments"),
                            "call_id": call_id,
                        }
                    }
                    function_response_dict = {
                        "function_response": {
                            "name": tool_call.get("action_name"),
                            "response": {"result": tool_call.get("result")},
                            "call_id": call_id,
                        }
                    }

                    rebuilt_messages.append(
                        {"role": "assistant", "content": [function_call_dict]}
                    )
                    rebuilt_messages.append(
                        {"role": "tool", "content": [function_response_dict]}
                    )

        # If no recent queries (everything was compressed), add a continuation user message
        if len(recent_queries) == 0 and compressed_summary:
            rebuilt_messages.append({
                "role": "user",
                "content": "Please continue with the remaining tasks based on the context above."
            })
            logger.info("Added continuation user message to maintain proper turn-taking after full compression")

        if include_current_execution:
            # Preserve any messages that were added during the current execution cycle
            recent_msg_count = 1  # system message
            for query in recent_queries:
                if "prompt" in query and "response" in query:
                    recent_msg_count += 2
                if "tool_calls" in query:
                    recent_msg_count += len(query["tool_calls"]) * 2

            if len(messages) > recent_msg_count:
                current_execution_messages = messages[recent_msg_count:]
                rebuilt_messages.extend(current_execution_messages)
                logger.info(
                    f"Preserved {len(current_execution_messages)} messages from current execution cycle"
                )

        logger.info(
            f"Messages rebuilt: {len(messages)} → {len(rebuilt_messages)} messages. "
            f"Ready to continue tool execution."
        )
        return rebuilt_messages
