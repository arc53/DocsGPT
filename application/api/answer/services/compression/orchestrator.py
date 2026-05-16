"""High-level compression orchestration."""

import logging
from typing import Any, Dict, Optional

from application.api.answer.services.compression.service import CompressionService
from application.api.answer.services.compression.threshold_checker import (
    CompressionThresholdChecker,
)
from application.api.answer.services.compression.types import CompressionResult
from application.api.answer.services.conversation_service import ConversationService
from application.core.model_utils import (
    get_api_key_for_provider,
    get_provider_from_model_id,
)
from application.core.settings import settings
from application.llm.llm_creator import LLMCreator

logger = logging.getLogger(__name__)


class CompressionOrchestrator:
    """
    Facade for compression operations.

    Coordinates between all compression components and provides
    a simple interface for callers.
    """

    def __init__(
        self,
        conversation_service: ConversationService,
        threshold_checker: Optional[CompressionThresholdChecker] = None,
    ):
        """
        Initialize orchestrator.

        Args:
            conversation_service: Service for DB operations
            threshold_checker: Custom threshold checker (optional)
        """
        self.conversation_service = conversation_service
        self.threshold_checker = threshold_checker or CompressionThresholdChecker()

    def compress_if_needed(
        self,
        conversation_id: str,
        user_id: str,
        model_id: str,
        decoded_token: Dict[str, Any],
        current_query_tokens: int = 500,
        model_user_id: Optional[str] = None,
    ) -> CompressionResult:
        """
        Check if compression is needed and perform it if so.

        This is the main entry point for compression operations.

        Args:
            conversation_id: Conversation ID
            user_id: Caller's user id — used for conversation access checks
            model_id: Model being used for conversation
            decoded_token: User's decoded JWT token
            current_query_tokens: Estimated tokens for current query
            model_user_id: BYOM-resolution scope (model owner); defaults
                to ``user_id`` for built-in / caller-owned models.

        Returns:
            CompressionResult with summary and recent queries
        """
        try:
            # Conversation row is owned by the caller, not the model owner.
            conversation = self.conversation_service.get_conversation(
                conversation_id, user_id
            )

            if not conversation:
                logger.warning(
                    f"Conversation {conversation_id} not found for user {user_id}"
                )
                return CompressionResult.failure("Conversation not found")

            # Use model-owner scope so per-user BYOM context windows
            # (e.g. 8k) compute the threshold against the right limit.
            registry_user_id = model_user_id or user_id
            if not self.threshold_checker.should_compress(
                conversation,
                model_id,
                current_query_tokens,
                user_id=registry_user_id,
            ):
                # No compression needed, return full history
                queries = conversation.get("queries", [])
                return CompressionResult.success_no_compression(queries)

            # Perform compression
            return self._perform_compression(
                conversation_id,
                conversation,
                model_id,
                decoded_token,
                user_id=user_id,
                model_user_id=model_user_id,
            )

        except Exception as e:
            logger.error(
                f"Error in compress_if_needed: {str(e)}", exc_info=True
            )
            return CompressionResult.failure(str(e))

    def _perform_compression(
        self,
        conversation_id: str,
        conversation: Dict[str, Any],
        model_id: str,
        decoded_token: Dict[str, Any],
        user_id: Optional[str] = None,
        model_user_id: Optional[str] = None,
    ) -> CompressionResult:
        """
        Perform the actual compression operation.

        Args:
            conversation_id: Conversation ID
            conversation: Conversation document
            model_id: Model ID for conversation
            decoded_token: User token
            user_id: Caller's id (for conversation reload after compression)
            model_user_id: BYOM-resolution scope (model owner)

        Returns:
            CompressionResult
        """
        try:
            # Determine which model to use for compression
            compression_model = (
                settings.COMPRESSION_MODEL_OVERRIDE
                if settings.COMPRESSION_MODEL_OVERRIDE
                else model_id
            )

            # Use model-owner scope so provider/api_key resolves to the
            # owner's BYOM record (shared-agent dispatch).
            caller_user_id = user_id
            if caller_user_id is None and isinstance(decoded_token, dict):
                caller_user_id = decoded_token.get("sub")
            registry_user_id = model_user_id or caller_user_id
            provider = get_provider_from_model_id(
                compression_model, user_id=registry_user_id
            )
            api_key = get_api_key_for_provider(provider)

            compression_llm = LLMCreator.create_llm(
                provider,
                api_key=api_key,
                user_api_key=None,
                decoded_token=decoded_token,
                model_id=compression_model,
                agent_id=conversation.get("agent_id"),
                model_user_id=registry_user_id,
            )
            # Side-channel LLM tag — distinguishes compression rows
            # from primary stream rows for cost-attribution dashboards.
            compression_llm._token_usage_source = "compression"

            # Create compression service with DB update capability
            compression_service = CompressionService(
                llm=compression_llm,
                model_id=compression_model,
                conversation_service=self.conversation_service,
            )

            # Compress all queries up to the latest
            queries_count = len(conversation.get("queries", []))
            compress_up_to = queries_count - 1

            if compress_up_to < 0:
                logger.warning("No queries to compress")
                return CompressionResult.success_no_compression([])

            logger.info(
                f"Initiating compression for conversation {conversation_id}: "
                f"compressing all {queries_count} queries (0-{compress_up_to})"
            )

            # Perform compression and save to DB
            metadata = compression_service.compress_and_save(
                conversation_id, conversation, compress_up_to
            )

            logger.info(
                f"Compression successful - ratio: {metadata.compression_ratio:.1f}x, "
                f"saved {metadata.original_token_count - metadata.compressed_token_count} tokens"
            )

            # Reload under caller (conversation is owned by caller).
            reload_user_id = caller_user_id
            if reload_user_id is None and isinstance(decoded_token, dict):
                reload_user_id = decoded_token.get("sub")
            conversation = self.conversation_service.get_conversation(
                conversation_id, user_id=reload_user_id
            )

            # Get compressed context
            compressed_summary, recent_queries = (
                compression_service.get_compressed_context(conversation)
            )

            return CompressionResult.success_with_compression(
                compressed_summary, recent_queries, metadata
            )

        except Exception as e:
            logger.error(f"Error performing compression: {str(e)}", exc_info=True)
            return CompressionResult.failure(str(e))

    def compress_mid_execution(
        self,
        conversation_id: str,
        user_id: str,
        model_id: str,
        decoded_token: Dict[str, Any],
        current_conversation: Optional[Dict[str, Any]] = None,
        model_user_id: Optional[str] = None,
    ) -> CompressionResult:
        """
        Perform compression during tool execution.

        Args:
            conversation_id: Conversation ID
            user_id: Caller's user id — used for conversation access checks
            model_id: Model ID
            decoded_token: User token
            current_conversation: Pre-loaded conversation (optional)
            model_user_id: BYOM-resolution scope (model owner). For
                shared-agent dispatch this is the agent owner; defaults
                to ``user_id`` so built-in / caller-owned models are
                unaffected.

        Returns:
            CompressionResult
        """
        try:
            # Load conversation if not provided
            if current_conversation:
                conversation = current_conversation
            else:
                conversation = self.conversation_service.get_conversation(
                    conversation_id, user_id
                )

            if not conversation:
                logger.warning(
                    f"Could not load conversation {conversation_id} for mid-execution compression"
                )
                return CompressionResult.failure("Conversation not found")

            # Perform compression
            return self._perform_compression(
                conversation_id,
                conversation,
                model_id,
                decoded_token,
                user_id=user_id,
                model_user_id=model_user_id,
            )

        except Exception as e:
            logger.error(
                f"Error in mid-execution compression: {str(e)}", exc_info=True
            )
            return CompressionResult.failure(str(e))
