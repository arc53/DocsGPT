"""Core compression service with simplified responsibilities."""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from application.api.answer.services.compression.prompt_builder import (
    CompressionPromptBuilder,
)
from application.api.answer.services.compression.token_counter import TokenCounter
from application.api.answer.services.compression.types import (
    CompressionMetadata,
)
from application.core.settings import settings

logger = logging.getLogger(__name__)


class CompressionService:
    """
    Service for compressing conversation history.

    Handles DB updates.
    """

    def __init__(
        self,
        llm,
        model_id: str,
        conversation_service=None,
        prompt_builder: Optional[CompressionPromptBuilder] = None,
    ):
        """
        Initialize compression service.

        Args:
            llm: LLM instance to use for compression
            model_id: Model ID for compression
            conversation_service: Service for DB operations (optional, for DB updates)
            prompt_builder: Custom prompt builder (optional)
        """
        self.llm = llm
        self.model_id = model_id
        self.conversation_service = conversation_service
        self.prompt_builder = prompt_builder or CompressionPromptBuilder(
            version=settings.COMPRESSION_PROMPT_VERSION
        )

    def compress_conversation(
        self,
        conversation: Dict[str, Any],
        compress_up_to_index: int,
    ) -> CompressionMetadata:
        """
        Compress conversation history up to specified index.

        Args:
            conversation: Full conversation document
            compress_up_to_index: Last query index to include in compression

        Returns:
            CompressionMetadata with compression details

        Raises:
            ValueError: If compress_up_to_index is invalid
        """
        try:
            queries = conversation.get("queries", [])

            if compress_up_to_index < 0 or compress_up_to_index >= len(queries):
                raise ValueError(
                    f"Invalid compress_up_to_index: {compress_up_to_index} "
                    f"(conversation has {len(queries)} queries)"
                )

            # Get queries to compress
            queries_to_compress = queries[: compress_up_to_index + 1]

            # Check if there are existing compressions
            existing_compressions = conversation.get("compression_metadata", {}).get(
                "compression_points", []
            )

            if existing_compressions:
                logger.info(
                    f"Found {len(existing_compressions)} previous compression(s) - "
                    f"will incorporate into new summary"
                )

            # Calculate original token count
            original_tokens = TokenCounter.count_query_tokens(queries_to_compress)

            # Log tool call stats
            self._log_tool_call_stats(queries_to_compress)

            # Build compression prompt
            messages = self.prompt_builder.build_prompt(
                queries_to_compress, existing_compressions
            )

            # Call LLM to generate compression
            logger.info(
                f"Starting compression: {len(queries_to_compress)} queries "
                f"(messages 0-{compress_up_to_index}, {original_tokens} tokens) "
                f"using model {self.model_id}"
            )

            response = self.llm.gen(
                model=self.model_id, messages=messages, max_tokens=4000
            )

            # Extract summary from response
            compressed_summary = self._extract_summary(response)

            # Calculate compressed token count
            compressed_tokens = TokenCounter.count_message_tokens(
                [{"content": compressed_summary}]
            )

            # Calculate compression ratio
            compression_ratio = (
                original_tokens / compressed_tokens if compressed_tokens > 0 else 0
            )

            logger.info(
                f"Compression complete: {original_tokens} → {compressed_tokens} tokens "
                f"({compression_ratio:.1f}x compression)"
            )

            # Build compression metadata
            compression_metadata = CompressionMetadata(
                timestamp=datetime.now(timezone.utc),
                query_index=compress_up_to_index,
                compressed_summary=compressed_summary,
                original_token_count=original_tokens,
                compressed_token_count=compressed_tokens,
                compression_ratio=compression_ratio,
                model_used=self.model_id,
                compression_prompt_version=self.prompt_builder.version,
            )

            return compression_metadata

        except Exception as e:
            logger.error(f"Error compressing conversation: {str(e)}", exc_info=True)
            raise

    def compress_and_save(
        self,
        conversation_id: str,
        conversation: Dict[str, Any],
        compress_up_to_index: int,
    ) -> CompressionMetadata:
        """
        Compress conversation and save to database.

        Args:
            conversation_id: Conversation ID
            conversation: Full conversation document
            compress_up_to_index: Last query index to include

        Returns:
            CompressionMetadata

        Raises:
            ValueError: If conversation_service not provided or invalid index
        """
        if not self.conversation_service:
            raise ValueError(
                "conversation_service required for compress_and_save operation"
            )

        # Perform compression
        metadata = self.compress_conversation(conversation, compress_up_to_index)

        # Save to database
        self.conversation_service.update_compression_metadata(
            conversation_id, metadata.to_dict()
        )

        logger.info(f"Compression metadata saved to database for {conversation_id}")

        return metadata

    def get_compressed_context(
        self, conversation: Dict[str, Any]
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        """
        Get compressed summary + recent uncompressed messages.

        Args:
            conversation: Full conversation document

        Returns:
            (compressed_summary, recent_messages)
        """
        try:
            compression_metadata = conversation.get("compression_metadata", {})

            if not compression_metadata.get("is_compressed"):
                logger.debug("No compression metadata found - using full history")
                queries = conversation.get("queries", [])
                if queries is None:
                    logger.error("Conversation queries is None - returning empty list")
                    return None, []
                return None, queries

            compression_points = compression_metadata.get("compression_points", [])

            if not compression_points:
                logger.debug("No compression points found - using full history")
                queries = conversation.get("queries", [])
                if queries is None:
                    logger.error("Conversation queries is None - returning empty list")
                    return None, []
                return None, queries

            # Get the most recent compression point
            latest_compression = compression_points[-1]
            compressed_summary = latest_compression.get("compressed_summary")
            last_compressed_index = latest_compression.get("query_index")
            compressed_tokens = latest_compression.get("compressed_token_count", 0)
            original_tokens = latest_compression.get("original_token_count", 0)

            # Get only messages after compression point
            queries = conversation.get("queries", [])
            total_queries = len(queries)
            recent_queries = queries[last_compressed_index + 1 :]

            logger.info(
                f"Using compressed context: summary ({compressed_tokens} tokens, "
                f"compressed from {original_tokens}) + {len(recent_queries)} recent messages "
                f"(messages {last_compressed_index + 1}-{total_queries - 1})"
            )

            return compressed_summary, recent_queries

        except Exception as e:
            logger.error(
                f"Error getting compressed context: {str(e)}", exc_info=True
            )
            queries = conversation.get("queries", [])
            if queries is None:
                return None, []
            return None, queries

    def _extract_summary(self, llm_response: str) -> str:
        """
        Extract clean summary from LLM response.

        Args:
            llm_response: Raw LLM response

        Returns:
            Cleaned summary text
        """
        try:
            # Try to extract content within <summary> tags
            summary_match = re.search(
                r"<summary>(.*?)</summary>", llm_response, re.DOTALL
            )

            if summary_match:
                summary = summary_match.group(1).strip()
            else:
                # If no summary tags, remove analysis tags and use the rest
                summary = re.sub(
                    r"<analysis>.*?</analysis>", "", llm_response, flags=re.DOTALL
                ).strip()

            return summary

        except Exception as e:
            logger.warning(f"Error extracting summary: {str(e)}, using full response")
            return llm_response

    def _log_tool_call_stats(self, queries: List[Dict[str, Any]]) -> None:
        """Log statistics about tool calls in queries."""
        total_tool_calls = 0
        total_tool_result_chars = 0
        tool_call_breakdown = {}

        for q in queries:
            for tc in q.get("tool_calls", []):
                total_tool_calls += 1
                tool_name = tc.get("tool_name", "unknown")
                action_name = tc.get("action_name", "unknown")
                key = f"{tool_name}.{action_name}"
                tool_call_breakdown[key] = tool_call_breakdown.get(key, 0) + 1

                # Track total tool result size
                result = tc.get("result", "")
                if result:
                    total_tool_result_chars += len(str(result))

        if total_tool_calls > 0:
            tool_breakdown_str = ", ".join(
                f"{tool}({count})"
                for tool, count in sorted(tool_call_breakdown.items())
            )
            tool_result_kb = total_tool_result_chars / 1024
            logger.info(
                f"Tool call breakdown: {tool_breakdown_str} "
                f"(total result size: {tool_result_kb:.1f} KB, {total_tool_result_chars:,} chars)"
            )
