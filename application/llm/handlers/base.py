import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional, Union

from application.logging import build_stack_data

logger = logging.getLogger(__name__)


# Cap the agent tool-call loop. Without this an LLM that keeps
# requesting more tool calls (preview models, sparse tool results,
# under-specified prompts) can chain searches indefinitely and the
# stream never finalises. 25 mirrors Dify's default.
MAX_TOOL_ITERATIONS = 25
_FINALIZE_INSTRUCTION = (
    f"You have made {MAX_TOOL_ITERATIONS} tool calls. Provide a final "
    "response to the user based on what you have, without making any "
    "additional tool calls."
)


def _bound_tool_response_for_llm(tool_response: Any) -> Any:
    """Cap a single tool result before it enters the LLM message array.

    One uncapped web page / API response has produced multi-hundred-KB tool
    results that get re-sent in every subsequent round of the tool loop —
    blowing conversations past every model's context window (observed in
    prod up to a 14M-token estimated prompt). The durability journal and
    the persisted conversation keep the FULL result (bounded separately at
    persistence); only the copy handed to the model is truncated here.
    """
    from application.core.settings import settings
    from application.utils import num_tokens_from_string

    max_tokens = int(getattr(settings, "TOOL_RESULT_MAX_TOKENS", 20000) or 0)
    if max_tokens <= 0:
        return tool_response
    text = tool_response if isinstance(tool_response, str) else str(tool_response)
    tokens = num_tokens_from_string(text)
    if tokens <= max_tokens:
        return tool_response
    chars_per_token = len(text) / tokens if tokens > 0 else 4
    target_chars = int(max_tokens * chars_per_token * 0.95)
    keep = int(target_chars * 0.4)
    marker = (
        f"\n\n[... tool result truncated: {tokens:,} tokens exceeded the "
        f"{max_tokens:,}-token per-result limit ...]\n\n"
    )
    if keep <= 0:
        # ``text[-0:]`` would return the WHOLE string, not nothing.
        return marker.strip()
    logger.warning(
        "Tool result truncated from %s to ~%s tokens before LLM handoff",
        tokens,
        max_tokens,
    )
    return text[:keep] + marker + text[-keep:]


@dataclass
class ToolCall:
    """Represents a tool/function call from the LLM."""

    id: str
    name: str
    arguments: Union[str, Dict]
    index: Optional[int] = None
    thought_signature: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "ToolCall":
        """Create ToolCall from dictionary."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            arguments=data.get("arguments", {}),
            index=data.get("index"),
        )


@dataclass
class LLMResponse:
    """Represents a response from the LLM."""

    content: str
    tool_calls: List[ToolCall]
    finish_reason: str
    raw_response: Any
    reasoning_content: str = ""

    @property
    def requires_tool_call(self) -> bool:
        """Check if the response requires tool calls."""
        return bool(self.tool_calls) and self.finish_reason == "tool_calls"


class LLMHandler(ABC):
    """Abstract base class for LLM handlers."""

    def __init__(self):
        self.llm_calls = []
        self.tool_calls = []
        # Cache of provider-name -> handler used by ``_parse_for_response``
        # to parse chunks from a model that a cross-provider fallback
        # swapped in underneath this handler.
        self._parser_by_provider = {}

    @abstractmethod
    def parse_response(self, response: Any) -> LLMResponse:
        """Parse raw LLM response into standardized format."""
        pass

    def _parse_for_response(self, agent, response: Any) -> "LLMResponse":
        """Parse ``response`` with the handler matching the model that
        actually produced it.

        ``BaseLLM`` runs model fallback *below* the agent (see
        ``BaseLLM._stream_with_fallback``): a Google-primary agent that is
        rate-limited can fail over to an OpenAI-compatible backup inside the
        same ``gen_stream`` call. This handler was built for the primary
        provider, so its ``parse_response`` cannot read the backup's chunk
        shape and silently drops tool calls — the agent then stops after the
        first text instead of running the tool loop.

        ``parse_response`` is the only provider-specific step that matters
        here: both providers' ``_iterate_stream`` and ``create_tool_message``
        are identical, so only this call is routed. The orchestration state
        (buffers, ``tool_calls``, ``llm_calls``) stays on ``self``.
        """
        provider = getattr(getattr(agent, "llm", None), "_responding_provider", None)
        if not isinstance(provider, str):
            return self.parse_response(response)
        return self._handler_for_provider(provider).parse_response(response)

    def _handler_for_provider(self, provider: str) -> "LLMHandler":
        """Resolve (and cache) the handler for ``provider``. Reuses ``self``
        when it already matches that provider, so the common no-fallback path
        is unchanged."""
        cached = self._parser_by_provider.get(provider)
        if cached is not None:
            return cached
        from application.llm.handlers.handler_creator import LLMHandlerCreator

        handler = LLMHandlerCreator.create_handler(provider)
        if type(handler) is type(self):
            handler = self
        self._parser_by_provider[provider] = handler
        return handler

    @abstractmethod
    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        """Create a tool result message for the conversation history."""
        pass

    @abstractmethod
    def _iterate_stream(self, response: Any) -> Generator:
        """Iterate through streaming response chunks."""
        pass

    def process_message_flow(
        self,
        agent,
        initial_response,
        tools_dict: Dict,
        messages: List[Dict],
        attachments: Optional[List] = None,
        stream: bool = False,
    ) -> Union[str, Generator]:
        """
        Main orchestration method for processing LLM message flow.

        Args:
            agent: The agent instance
            initial_response: Initial LLM response
            tools_dict: Dictionary of available tools
            messages: Conversation history
            attachments: Optional attachments
            stream: Whether to use streaming

        Returns:
            Final response or generator for streaming
        """
        messages = self.prepare_messages(agent, messages, attachments)

        if stream:
            return self.handle_streaming(agent, initial_response, tools_dict, messages)
        else:
            return self.handle_non_streaming(
                agent, initial_response, tools_dict, messages
            )

    def prepare_messages(
        self, agent, messages: List[Dict], attachments: Optional[List] = None
    ) -> List[Dict]:
        """
        Prepare messages with attachments and provider-specific formatting.


        Args:
            agent: The agent instance
            messages: Original messages
            attachments: List of attachments

        Returns:
            Prepared messages list
        """
        if not attachments:
            return messages
        logger.info(f"Preparing messages with {len(attachments)} attachments")
        supported_types = agent.llm.get_supported_attachment_types()

        # Check if provider supports images but not PDF (synthetic PDF support)
        supports_images = any(t.startswith("image/") for t in supported_types)
        supports_pdf = "application/pdf" in supported_types

        # Process attachments, converting PDFs to images if needed
        processed_attachments = []
        for attachment in attachments:
            mime_type = attachment.get("mime_type")

            # Synthetic PDF support: convert PDF to images if LLM supports images but not PDF
            if mime_type == "application/pdf" and supports_images and not supports_pdf:
                logger.info(
                    f"Converting PDF to images for synthetic PDF support: {attachment.get('path', 'unknown')}"
                )
                try:
                    converted_images = self._convert_pdf_to_images(attachment)
                    processed_attachments.extend(converted_images)
                    logger.info(
                        f"Converted PDF to {len(converted_images)} images"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to convert PDF to images, falling back to text: {e}"
                    )
                    # Fall back to treating as unsupported (text extraction)
                    processed_attachments.append(attachment)
            else:
                processed_attachments.append(attachment)

        supported_attachments = [
            a for a in processed_attachments if a.get("mime_type") in supported_types
        ]
        unsupported_attachments = [
            a for a in processed_attachments if a.get("mime_type") not in supported_types
        ]

        # Process supported attachments with the LLM's custom method

        if supported_attachments:
            logger.info(
                f"Processing {len(supported_attachments)} supported attachments"
            )
            messages = agent.llm.prepare_messages_with_attachments(
                messages, supported_attachments
            )
        # Process unsupported attachments with default method

        if unsupported_attachments:
            logger.info(
                f"Processing {len(unsupported_attachments)} unsupported attachments"
            )
            messages = self._append_unsupported_attachments(
                messages, unsupported_attachments
            )
        return messages

    def _convert_pdf_to_images(self, attachment: Dict) -> List[Dict]:
        """
        Convert a PDF attachment to a list of image attachments.

        This enables synthetic PDF support for LLMs that support images but not PDFs.

        Args:
            attachment: PDF attachment dictionary with 'path' and optional 'content'

        Returns:
            List of image attachment dictionaries with 'data', 'mime_type', and 'page'
        """
        from application.utils import convert_pdf_to_images
        from application.storage.storage_creator import StorageCreator

        file_path = attachment.get("path")
        if not file_path:
            raise ValueError("No file path provided in PDF attachment")

        storage = StorageCreator.get_storage()

        # Convert PDF to images
        images_data = convert_pdf_to_images(
            file_path=file_path,
            storage=storage,
            max_pages=20,
            dpi=150,
        )

        return images_data

    def _append_unsupported_attachments(
        self, messages: List[Dict], attachments: List[Dict]
    ) -> List[Dict]:
        """
        Default method to append unsupported attachment content to system prompt.

        Args:
            messages: Current messages
            attachments: List of unsupported attachments

        Returns:
            Updated messages list
        """
        prepared_messages = messages.copy()
        attachment_texts = []

        for attachment in attachments:
            logger.info(f"Adding attachment {attachment.get('id')} to context")
            if "content" in attachment:
                attachment_texts.append(
                    f"Attached file content:\n\n{attachment['content']}"
                )
        if attachment_texts:
            combined_text = "\n\n".join(attachment_texts)

            system_msg = next(
                (msg for msg in prepared_messages if msg.get("role") == "system"),
                {"role": "system", "content": ""},
            )

            if system_msg not in prepared_messages:
                prepared_messages.insert(0, system_msg)
            system_msg["content"] += f"\n\n{combined_text}"
        return prepared_messages

    def _prune_messages_minimal(self, messages: List[Dict]) -> Optional[List[Dict]]:
        """
        Build a minimal context: system prompt + latest user message only.
        Drops all tool/function messages to shrink context aggressively.
        """
        system_message = next((m for m in messages if m.get("role") == "system"), None)
        if not system_message:
            logger.warning("Cannot prune messages minimally: missing system message.")
            return None
        last_non_system = None
        for m in reversed(messages):
            if m.get("role") == "user":
                last_non_system = m
                break
            if not last_non_system and m.get("role") not in ("system", None):
                last_non_system = m
        if not last_non_system:
            logger.warning("Cannot prune messages minimally: missing user/assistant messages.")
            return None
        logger.info("Pruning context to system + latest user/assistant message to proceed.")
        return [system_message, last_non_system]

    def _extract_text_from_content(self, content: Any) -> str:
        """
        Convert message content (str or list of parts) to plain text for compression.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts_text = []
            for item in content:
                if isinstance(item, dict):
                    if "text" in item and item["text"] is not None:
                        parts_text.append(str(item["text"]))
                    elif "function_call" in item or "function_response" in item:
                        # Keep serialized function calls/responses so the compressor sees actions
                        parts_text.append(str(item))
                    elif "files" in item:
                        # Image attachments arrive with raw bytes / base64
                        # inline (see GoogleLLM.prepare_messages_with_attachments).
                        # ``str(item)`` would dump the whole byte/base64
                        # blob into the compression prompt and bust the
                        # compression LLM's input limit.
                        files = item.get("files") or []
                        descriptors = []
                        if isinstance(files, list):
                            for f in files:
                                if isinstance(f, dict):
                                    descriptors.append(
                                        f.get("mime_type") or "file"
                                    )
                                elif isinstance(f, str):
                                    descriptors.append(f)
                        if not descriptors:
                            descriptors = ["file"]
                        parts_text.append(
                            f"[attachment: {', '.join(descriptors)}]"
                        )
            return "\n".join(parts_text)
        return ""

    def _build_conversation_from_messages(self, messages: List[Dict]) -> Optional[Dict]:
        """
        Build a conversation-like dict from current messages so we can compress
        even when the conversation isn't persisted yet. Includes tool calls/results.
        """
        queries = []
        current_prompt = None
        current_tool_calls = {}

        def _commit_query(response_text: str):
            nonlocal current_prompt, current_tool_calls
            if current_prompt is None and not response_text:
                return
            tool_calls_list = list(current_tool_calls.values())
            queries.append(
                {
                    "prompt": current_prompt or "",
                    "response": response_text,
                    "tool_calls": tool_calls_list,
                }
            )
            current_prompt = None
            current_tool_calls = {}

        for message in messages:
            role = message.get("role")
            content = message.get("content")

            if role == "user":
                current_prompt = self._extract_text_from_content(content)

            elif role in {"assistant", "model"}:
                # Standard format: tool_calls array on assistant message
                msg_tool_calls = message.get("tool_calls")
                if msg_tool_calls:
                    for tc in msg_tool_calls:
                        call_id = tc.get("id") or str(uuid.uuid4())
                        func = tc.get("function", {})
                        args = func.get("arguments")
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except (json.JSONDecodeError, TypeError):
                                pass
                        current_tool_calls[call_id] = {
                            "tool_name": "unknown_tool",
                            "action_name": func.get("name"),
                            "arguments": args,
                            "result": None,
                            "status": "called",
                            "call_id": call_id,
                        }
                    continue

                # Legacy format: function_call/function_response in content list
                if isinstance(content, list):
                    has_fc = False
                    for item in content:
                        if "function_call" in item:
                            has_fc = True
                            fc = item["function_call"]
                            call_id = fc.get("call_id") or str(uuid.uuid4())
                            current_tool_calls[call_id] = {
                                "tool_name": "unknown_tool",
                                "action_name": fc.get("name"),
                                "arguments": fc.get("args"),
                                "result": None,
                                "status": "called",
                                "call_id": call_id,
                            }
                    if has_fc:
                        continue

                response_text = self._extract_text_from_content(content)
                _commit_query(response_text)

            elif role == "tool":
                # Standard format: tool_call_id on tool message
                call_id = message.get("tool_call_id")
                tool_text = self._extract_text_from_content(content)

                if call_id and call_id in current_tool_calls:
                    current_tool_calls[call_id]["result"] = tool_text
                    current_tool_calls[call_id]["status"] = "completed"
                # Legacy: function_response in content list
                elif isinstance(content, list):
                    for item in content:
                        if "function_response" in item:
                            legacy_id = item["function_response"].get("call_id")
                            if legacy_id and legacy_id in current_tool_calls:
                                current_tool_calls[legacy_id]["result"] = tool_text
                                current_tool_calls[legacy_id]["status"] = "completed"
                                break
                elif call_id is None and queries:
                    queries[-1].setdefault("tool_calls", []).append(
                        {
                            "tool_name": "unknown_tool",
                            "action_name": "unknown_action",
                            "arguments": {},
                            "result": tool_text,
                            "status": "completed",
                        }
                    )

        # If there's an unfinished prompt with tool_calls but no response yet, commit it
        if current_prompt is not None or current_tool_calls:
            _commit_query(response_text="")

        if not queries:
            return None

        return {
            "queries": queries,
            "compression_metadata": {
                "is_compressed": False,
                "compression_points": [],
            },
        }

    def _rebuild_messages_after_compression(
        self,
        messages: List[Dict],
        compressed_summary: Optional[str],
        recent_queries: List[Dict],
        include_current_execution: bool = False,
        include_tool_calls: bool = False,
    ) -> Optional[List[Dict]]:
        """
        Rebuild the message list after compression so tool execution can continue.

        Delegates to MessageBuilder for the actual reconstruction.
        """
        from application.api.answer.services.compression.message_builder import (
            MessageBuilder,
        )

        return MessageBuilder.rebuild_messages_after_compression(
            messages=messages,
            compressed_summary=compressed_summary,
            recent_queries=recent_queries,
            include_current_execution=include_current_execution,
            include_tool_calls=include_tool_calls,
        )

    def _perform_mid_execution_compression(
        self, agent, messages: List[Dict]
    ) -> tuple[bool, Optional[List[Dict]]]:
        """
        Perform compression during tool execution and rebuild messages.

        Uses the new orchestrator for simplified compression.

        Args:
            agent: The agent instance
            messages: Current conversation messages

        Returns:
            (success: bool, rebuilt_messages: Optional[List[Dict]])
        """
        try:
            from application.api.answer.services.compression import (
                CompressionOrchestrator,
            )
            from application.api.answer.services.conversation_service import (
                ConversationService,
            )

            conversation_service = ConversationService()
            orchestrator = CompressionOrchestrator(conversation_service)

            # Get conversation from database (may be None for new sessions)
            conversation = conversation_service.get_conversation(
                agent.conversation_id, agent.initial_user_id
            )

            if conversation:
                # Merge current in-flight messages (including tool calls)
                conversation_from_msgs = self._build_conversation_from_messages(messages)
                if conversation_from_msgs:
                    conversation = conversation_from_msgs
            else:
                logger.warning(
                    "Could not load conversation for compression; attempting in-memory compression"
                )
                return self._perform_in_memory_compression(agent, messages)

            # Use orchestrator to perform compression. ``model_user_id``
            # keeps BYOM registry resolution scoped to the model owner
            # (shared-agent dispatch) while ``user_id`` stays the caller
            # for the conversation access check.
            result = orchestrator.compress_mid_execution(
                conversation_id=agent.conversation_id,
                user_id=agent.initial_user_id,
                model_user_id=getattr(agent, "model_user_id", None),
                model_id=agent.model_id,
                decoded_token=getattr(agent, "decoded_token", {}),
                current_conversation=conversation,
            )

            if not result.success:
                logger.warning(f"Mid-execution compression failed: {result.error}")
                # Try minimal pruning as fallback
                pruned = self._prune_messages_minimal(messages)
                if pruned:
                    agent.context_limit_reached = False
                    agent.current_token_count = 0
                    return True, pruned
                return False, None

            if not result.compression_performed:
                logger.warning("Compression not performed")
                return False, None

            # Check if compression actually reduced tokens
            if result.metadata:
                if result.metadata.compressed_token_count >= result.metadata.original_token_count:
                    logger.warning(
                        "Compression did not reduce token count; falling back to minimal pruning"
                    )
                    pruned = self._prune_messages_minimal(messages)
                    if pruned:
                        agent.context_limit_reached = False
                        agent.current_token_count = 0
                        return True, pruned
                    return False, None

                logger.info(
                    f"Mid-execution compression successful - ratio: {result.metadata.compression_ratio:.1f}x, "
                    f"saved {result.metadata.original_token_count - result.metadata.compressed_token_count} tokens"
                )

            # Also store the compression summary as a visible message
            if result.metadata:
                conversation_service.append_compression_message(
                    agent.conversation_id, result.metadata.to_dict()
                )

            # Update agent's compressed summary for downstream persistence
            agent.compressed_summary = result.compressed_summary
            agent.compression_metadata = result.metadata.to_dict() if result.metadata else None
            agent.compression_saved = False

            # Reset the context limit flag so tools can continue
            agent.context_limit_reached = False
            agent.current_token_count = 0

            # Rebuild messages
            rebuilt_messages = self._rebuild_messages_after_compression(
                messages,
                result.compressed_summary,
                result.recent_queries,
                include_current_execution=False,
                include_tool_calls=False,
            )

            if rebuilt_messages is None:
                return False, None

            return True, rebuilt_messages

        except Exception as e:
            logger.error(
                f"Error performing mid-execution compression: {str(e)}", exc_info=True
            )
            return False, None

    def _perform_in_memory_compression(
        self, agent, messages: List[Dict]
    ) -> tuple[bool, Optional[List[Dict]]]:
        """
        Fallback compression path when the conversation is not yet persisted.

        Uses CompressionService directly without DB persistence.
        """
        try:
            from application.api.answer.services.compression.service import (
                CompressionService,
            )
            from application.core.model_utils import (
                get_api_key_for_provider,
                get_provider_from_model_id,
            )
            from application.core.settings import settings
            from application.llm.llm_creator import LLMCreator

            conversation = self._build_conversation_from_messages(messages)
            if not conversation:
                logger.warning(
                    "Cannot perform in-memory compression: no user/assistant turns found"
                )
                return False, None

            compression_model = (
                settings.COMPRESSION_MODEL_OVERRIDE
                if settings.COMPRESSION_MODEL_OVERRIDE
                else agent.model_id
            )
            agent_decoded = getattr(agent, "decoded_token", None)
            caller_sub = (
                agent_decoded.get("sub")
                if isinstance(agent_decoded, dict)
                else None
            )
            # Use model-owner scope (mirrors orchestrator path) so
            # shared-agent owner-BYOM resolves under the owner's layer.
            compression_user_id = (
                getattr(agent, "model_user_id", None) or caller_sub
            )
            provider = get_provider_from_model_id(
                compression_model, user_id=compression_user_id
            )
            api_key = get_api_key_for_provider(provider)
            compression_llm = LLMCreator.create_llm(
                provider,
                api_key,
                getattr(agent, "user_api_key", None),
                getattr(agent, "decoded_token", None),
                model_id=compression_model,
                agent_id=getattr(agent, "agent_id", None),
                model_user_id=compression_user_id,
            )
            # Side-channel LLM tag — see ``orchestrator.py`` for rationale.
            compression_llm._token_usage_source = "compression"
            compression_llm._request_id = getattr(agent, "_request_id", None) \
                or getattr(getattr(agent, "llm", None), "_request_id", None)

            # Create service without DB persistence capability
            compression_service = CompressionService(
                llm=compression_llm,
                model_id=compression_model,
                conversation_service=None,  # No DB updates for in-memory
            )

            queries_count = len(conversation.get("queries", []))
            compress_up_to = queries_count - 1

            if compress_up_to < 0 or queries_count == 0:
                logger.warning("Not enough queries to compress in-memory context")
                return False, None

            try:
                metadata = compression_service.compress_conversation(
                    conversation,
                    compress_up_to_index=compress_up_to,
                )
            except ValueError:
                # compress_conversation raises when the summary is not
                # smaller than the original (negative-savings guard). For
                # the in-memory path that is not fatal — fall back to
                # minimal pruning and keep the tool loop running.
                metadata = None

            # If compression doesn't reduce tokens, fall back to minimal pruning
            if metadata is None or (
                metadata.compressed_token_count
                >= metadata.original_token_count
            ):
                logger.warning(
                    "In-memory compression did not reduce token count; falling back to minimal pruning"
                )
                pruned = self._prune_messages_minimal(messages)
                if pruned:
                    agent.context_limit_reached = False
                    agent.current_token_count = 0
                    return True, pruned
                return False, None

            # Attach metadata to synthetic conversation
            conversation["compression_metadata"] = {
                "is_compressed": True,
                "compression_points": [metadata.to_dict()],
            }

            compressed_summary, recent_queries = (
                compression_service.get_compressed_context(conversation)
            )

            agent.compressed_summary = compressed_summary
            agent.compression_metadata = metadata.to_dict()
            agent.compression_saved = False
            agent.context_limit_reached = False
            agent.current_token_count = 0

            rebuilt_messages = self._rebuild_messages_after_compression(
                messages,
                compressed_summary,
                recent_queries,
                include_current_execution=False,
                include_tool_calls=False,
            )
            if rebuilt_messages is None:
                return False, None

            logger.info(
                f"In-memory compression successful - ratio: {metadata.compression_ratio:.1f}x, "
                f"saved {metadata.original_token_count - metadata.compressed_token_count} tokens"
            )
            return True, rebuilt_messages

        except Exception as e:
            logger.error(
                f"Error performing in-memory compression: {str(e)}", exc_info=True
            )
            return False, None

    def handle_tool_calls(
        self,
        agent,
        tool_calls: List[ToolCall],
        tools_dict: Dict,
        messages: List[Dict],
        reasoning_content: str = "",
    ) -> Generator:
        """
        Execute tool calls and update conversation history.

        When a tool requires approval or client-side execution, it is
        collected as a pending action instead of being executed.  The
        generator returns ``(updated_messages, pending_actions)`` where
        *pending_actions* is ``None`` when every tool was executed
        normally, or a list of dicts describing actions the client must
        resolve before the LLM loop can continue.

        Args:
            agent: The agent instance
            tool_calls: List of tool calls to execute
            tools_dict: Available tools dictionary
            messages: Current conversation history
            reasoning_content: Reasoning text emitted by the model
                before these tool calls. Attached to the recorded
                assistant message so providers that require reasoning
                to round-trip (DeepSeek thinking mode) accept the
                follow-up request.

        Returns:
            Tuple of (updated_messages, pending_actions).
            pending_actions is None if all tools executed, otherwise a list.
        """
        updated_messages = messages.copy()
        pending_actions: List[Dict] = []

        # One assistant message carries the WHOLE parallel batch, followed by
        # one tool message per call — the layout every provider expects, and
        # the one the resume (``BaseAgent._resume_*``) and history-replay
        # (``BaseAgent._build_messages``) paths already emit.
        #
        # Emitting a separate assistant message per call breaks chained
        # Responses requests: ``_trim_for_previous_response`` re-sends only
        # what follows the LAST assistant message, so every output except the
        # final one was dropped and the provider rejected the request with
        # "No tool output found for function call <first unpaired call>".
        batch_assistant: Optional[Dict[str, Any]] = None

        def _declare_call(tool_call_obj: Dict[str, Any]) -> None:
            """Add ``tool_call_obj`` to the batch's assistant message,
            creating (and appending) that message on first use."""
            nonlocal batch_assistant
            if batch_assistant is None:
                batch_assistant = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [],
                }
                # Reasoning rides once on the batch message; DeepSeek thinking
                # mode rejects an active-turn assistant message without it.
                if reasoning_content:
                    batch_assistant["reasoning_content"] = reasoning_content
                updated_messages.append(batch_assistant)
            batch_assistant["tool_calls"].append(tool_call_obj)

        for i, call in enumerate(tool_calls):
            # Check context limit before executing tool call
            if hasattr(agent, '_check_context_limit') and agent._check_context_limit(updated_messages):
                # Context limit reached - attempt mid-execution compression
                compression_attempted = False
                compression_successful = False

                try:
                    from application.core.settings import settings
                    compression_enabled = settings.ENABLE_CONVERSATION_COMPRESSION
                except Exception:
                    compression_enabled = False

                if compression_enabled:
                    compression_attempted = True
                    try:
                        logger.info(
                            f"Context limit reached with {len(tool_calls) - i} remaining tool calls. "
                            f"Attempting mid-execution compression..."
                        )

                        # Trigger mid-execution compression (DB-backed if available, otherwise in-memory)
                        compression_successful, rebuilt_messages = self._perform_mid_execution_compression(
                            agent, updated_messages
                        )

                        if compression_successful and rebuilt_messages is not None:
                            # Update the messages list with rebuilt compressed version
                            updated_messages = rebuilt_messages
                            # The rebuilt list no longer contains the batch
                            # message we were appending to, so mutating it
                            # would be a silent no-op. Start a fresh one for
                            # the remaining calls; each assistant message
                            # still owns exactly the results that follow it.
                            batch_assistant = None

                            # Yield compression success message
                            yield {
                                "type": "info",
                                "data": {
                                    "message": "Context window limit reached. Compressed conversation history to continue processing."
                                }
                            }

                            logger.info(
                                f"Mid-execution compression successful. Continuing with {len(tool_calls) - i} remaining tool calls."
                            )
                            # Proceed to execute the current tool call with the reduced context
                        else:
                            logger.warning("Mid-execution compression attempted but failed. Skipping remaining tools.")
                    except Exception as e:
                        logger.error(f"Error during mid-execution compression: {str(e)}", exc_info=True)
                        compression_attempted = True
                        compression_successful = False

                # If compression wasn't attempted or failed, skip remaining tools
                if not compression_successful:
                    if i == 0:
                        # Special case: limit reached before executing any tools
                        # This can happen when previous tool responses pushed context over limit
                        if compression_attempted:
                            logger.warning(
                                f"Context limit reached before executing any tools. "
                                f"Compression attempted but failed. "
                                f"Skipping all {len(tool_calls)} pending tool call(s). "
                                f"This typically occurs when previous tool responses contained large amounts of data."
                            )
                        else:
                            logger.warning(
                                f"Context limit reached before executing any tools. "
                                f"Skipping all {len(tool_calls)} pending tool call(s). "
                                f"This typically occurs when previous tool responses contained large amounts of data. "
                                f"Consider enabling compression or using a model with larger context window."
                            )
                    else:
                        # Normal case: executed some tools, now stopping
                        tool_word = "tool call" if i == 1 else "tool calls"
                        remaining = len(tool_calls) - i
                        remaining_word = "tool call" if remaining == 1 else "tool calls"
                        if compression_attempted:
                            logger.warning(
                                f"Context limit reached after executing {i} {tool_word}. "
                                f"Compression attempted but failed. "
                                f"Skipping remaining {remaining} {remaining_word}."
                            )
                        else:
                            logger.warning(
                                f"Context limit reached after executing {i} {tool_word}. "
                                f"Skipping remaining {remaining} {remaining_word}. "
                                f"Consider enabling compression or using a model with larger context window."
                            )

                    # Mark remaining tools as skipped
                    for remaining_call in tool_calls[i:]:
                        skip_message = {
                            "type": "tool_call",
                            "data": {
                                "tool_name": "system",
                                "call_id": remaining_call.id,
                                "action_name": remaining_call.name,
                                "arguments": {},
                                "result": "Skipped: Context limit reached. Too many tool calls in conversation.",
                                "status": "skipped"
                            }
                        }
                        yield skip_message

                    # Set flag on agent
                    agent.context_limit_reached = True
                    break

            # ---- Pause check: approval / client-side execution ----
            llm_class = agent.llm.__class__.__name__
            pause_info = agent.tool_executor.check_pause(
                tools_dict, call, llm_class
            )
            if pause_info:
                # Headless (scheduled / webhook): synthesize a denial tool message
                # so the LLM finishes gracefully instead of stalling on a pause
                # nobody will resolve, then journal so the reconciler sees it.
                if pause_info.get("pause_type") == "headless_denied":
                    deny_reason = pause_info.get(
                        "deny_reason", "Tool blocked in headless mode."
                    )
                    args_str = (
                        json.dumps(call.arguments)
                        if isinstance(call.arguments, dict)
                        else (call.arguments or "{}")
                    )
                    tool_call_obj = {
                        "id": pause_info["call_id"],
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": args_str,
                        },
                    }
                    if getattr(call, "thought_signature", None):
                        tool_call_obj["thought_signature"] = call.thought_signature
                    _declare_call(tool_call_obj)
                    denial_call = ToolCall(
                        id=pause_info["call_id"],
                        name=call.name,
                        arguments=call.arguments,
                    )
                    updated_messages.append(
                        self.create_tool_message(
                            denial_call,
                            f"Tool denied (headless): {deny_reason}",
                        )
                    )
                    if hasattr(agent.tool_executor, "headless_denials"):
                        agent.tool_executor.headless_denials.append(pause_info)
                    from application.agents.tool_executor import (
                        _mark_failed,
                        _record_proposed,
                    )

                    if _record_proposed(
                        pause_info["call_id"],
                        pause_info["tool_name"],
                        pause_info["action_name"],
                        pause_info.get("arguments") or {},
                        tool_id=pause_info.get("tool_id"),
                        message_id=agent.tool_executor.message_id,
                        user_id=agent.tool_executor.user,
                        agent_id=agent.tool_executor.agent_id,
                    ):
                        _mark_failed(
                            pause_info["call_id"],
                            f"headless: {deny_reason}",
                            message_id=agent.tool_executor.message_id,
                            user_id=agent.tool_executor.user,
                        )
                    yield {
                        "type": "tool_call",
                        "data": {
                            "tool_name": pause_info["tool_name"],
                            "call_id": pause_info["call_id"],
                            "action_name": pause_info.get(
                                "llm_name", pause_info["name"]
                            ),
                            "arguments": pause_info["arguments"],
                            "status": "denied",
                            "error": deny_reason,
                            "error_type": pause_info.get(
                                "error_type", "tool_not_allowed"
                            ),
                        },
                    }
                    continue
                # Yield pause event so the client knows this tool is waiting
                pause_data = {
                    "tool_name": pause_info["tool_name"],
                    "call_id": pause_info["call_id"],
                    "action_name": pause_info.get("llm_name", pause_info["name"]),
                    "arguments": pause_info["arguments"],
                    "status": pause_info["pause_type"],
                }
                # Surface device_id for remote_device pauses so the approval UI
                # can wire the sticky "don't ask again" button.
                if pause_info.get("device_id"):
                    pause_data["device_id"] = pause_info["device_id"]
                yield {"type": "tool_call", "data": pause_data}
                pending_actions.append(pause_info)
                # Do NOT add messages for pending tools here.
                # They will be added on resume to keep call/result pairs together.
                continue

            # One assistant(tool_calls) message per call: track whether the
            # success path already appended it so the except below doesn't
            # add a second one when create_tool_message fails post-append.
            assistant_appended = False
            try:
                self.tool_calls.append(call)
                tool_executor_gen = agent._execute_tool_action(tools_dict, call)
                while True:
                    try:
                        yield next(tool_executor_gen)
                    except StopIteration as e:
                        tool_response, call_id = e.value
                        break
                # The journal / persisted conversation received the full
                # result inside the executor; the model gets a bounded copy.
                tool_response = _bound_tool_response_for_llm(tool_response)

                # Standard internal format: assistant message with tool_calls array
                args_str = (
                    json.dumps(call.arguments)
                    if isinstance(call.arguments, dict)
                    else call.arguments
                )
                tool_call_obj = {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": args_str,
                    },
                }
                # Preserve thought_signature for Google Gemini 3 models
                if call.thought_signature:
                    tool_call_obj["thought_signature"] = call.thought_signature

                _declare_call(tool_call_obj)
                assistant_appended = True

                # The tool result's tool_call_id must match the id put on the
                # assistant tool_call above (``call_id`` — a synthesized UUID
                # when the provider omitted an id), not the raw ``call.id`` which
                # may be empty. A mismatch orphans the tool message and 400s the
                # next completion ("'tool' must be a response to a preceding
                # message with 'tool_calls'").
                resolved_call = ToolCall(
                    id=call_id, name=call.name, arguments=call.arguments
                )
                updated_messages.append(
                    self.create_tool_message(resolved_call, tool_response)
                )
            except Exception as e:
                logger.error(f"Error executing tool: {str(e)}", exc_info=True)
                # The error tool message's tool_call_id must match the
                # tool_call id declared on the batch assistant message. When
                # the success path already declared this call that id is the
                # executor-returned ``call_id``; otherwise the except declares
                # it below from ``call.id``.
                error_id = call_id if assistant_appended else call.id
                error_call = ToolCall(
                    id=error_id, name=call.name, arguments=call.arguments
                )
                error_response = f"Error executing tool: {str(e)}"
                # Mirror the success path: every tool message must answer a
                # call declared on the batch assistant message, or the next
                # provider completion 400s. Skip re-declaring when the success
                # path already did it for this call — a create_tool_message
                # failure after that point would otherwise declare the call
                # twice and 400 the same way an orphan tool message does.
                if not assistant_appended:
                    args_str = (
                        json.dumps(call.arguments)
                        if isinstance(call.arguments, dict)
                        else call.arguments
                    )
                    tool_call_obj = {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": args_str,
                        },
                    }
                    if call.thought_signature:
                        tool_call_obj["thought_signature"] = call.thought_signature
                    _declare_call(tool_call_obj)

                error_message = self.create_tool_message(error_call, error_response)
                updated_messages.append(error_message)

                mapping = agent.tool_executor._name_to_tool
                if call.name in mapping:
                    resolved_tool_id, _ = mapping[call.name]
                    tool_name = tools_dict.get(resolved_tool_id, {}).get(
                        "name", "unknown_tool"
                    )
                else:
                    tool_name = "unknown_tool"
                full_action_name = call.name
                yield {
                    "type": "tool_call",
                    "data": {
                        "tool_name": tool_name,
                        "call_id": call.id,
                        "action_name": full_action_name,
                        "arguments": call.arguments,
                        "error": error_response,
                        "status": "error",
                    },
                }
        return updated_messages, pending_actions if pending_actions else None

    def handle_non_streaming(
        self, agent, response: Any, tools_dict: Dict, messages: List[Dict]
    ) -> Generator:
        """
        Handle non-streaming response flow.

        Args:
            agent: The agent instance
            response: Current LLM response
            tools_dict: Available tools dictionary
            messages: Conversation history

        Returns:
            Final response after processing all tool calls
        """
        parsed = self._parse_for_response(agent, response)
        self.llm_calls.append(build_stack_data(agent.llm))

        iteration = 0
        while parsed.requires_tool_call:
            iteration += 1
            reasoning_for_round = parsed.reasoning_content or ""
            tool_handler_gen = self.handle_tool_calls(
                agent,
                parsed.tool_calls,
                tools_dict,
                messages,
                reasoning_content=reasoning_for_round,
            )
            while True:
                try:
                    yield next(tool_handler_gen)
                except StopIteration as e:
                    messages, pending_actions = e.value
                    break

            # If tools need approval or client execution, pause the loop
            if pending_actions:
                agent._pending_continuation = {
                    "messages": messages,
                    "pending_tool_calls": pending_actions,
                    "tools_dict": tools_dict,
                    "reasoning_content": reasoning_for_round,
                }
                yield {
                    "type": "tool_calls_pending",
                    "data": {"pending_tool_calls": pending_actions},
                }
                return ""

            # Cap reached: force one final tool-less call so the stream
            # always ends with content rather than cutting off.
            if iteration >= MAX_TOOL_ITERATIONS:
                logger.warning(
                    "agent tool loop hit cap (%d); forcing finalize",
                    MAX_TOOL_ITERATIONS,
                )
                messages.append(
                    {"role": "system", "content": _FINALIZE_INSTRUCTION},
                )
                response = agent.llm.gen(
                    model=getattr(agent.llm, "model_id", None) or agent.model_id,
                    messages=messages,
                    tools=None,
                )
                parsed = self._parse_for_response(agent, response)
                self.llm_calls.append(build_stack_data(agent.llm))
                break

            # ``agent.model_id`` is the registry id (a UUID for BYOM
            # records). Use the LLM's own model_id, which LLMCreator
            # already resolved to the upstream model name. Built-ins:
            # the two are equal; BYOM: the upstream name like
            # "mistral-large-latest" instead of the UUID.
            response = agent.llm.gen(
                model=getattr(agent.llm, "model_id", None) or agent.model_id,
                messages=messages,
                tools=agent.tools,
            )
            parsed = self._parse_for_response(agent, response)
            self.llm_calls.append(build_stack_data(agent.llm))
        return parsed.content

    def handle_streaming(
        self,
        agent,
        response: Any,
        tools_dict: Dict,
        messages: List[Dict],
        _iteration: int = 0,
        _answer_recovered: bool = False,
    ) -> Generator:
        """
        Handle streaming response flow.

        Args:
            agent: The agent instance
            response: Current LLM response
            tools_dict: Available tools dictionary
            messages: Conversation history
            _answer_recovered: Set by the recovery branch to bound the
                empty-answer rescue to one attempt per stream — a recovery
                that itself ends reasoning-only must not recurse.

        Yields:
            Streaming response chunks
        """
        buffer = ""
        tool_calls = {}
        reasoning_buffer = ""
        finish_reason = None
        # Tracks whether any visible content reached the caller this
        # round. Distinct from ``buffer``/``finish_reason``: providers
        # emit content as bare strings (yielded straight through) and
        # also as ``parsed.content`` on choice objects; either counts.
        answered = False

        # Consume the provider stream to exhaustion before acting on its
        # finish reason. Acting mid-iteration (as this loop used to) left
        # every tool round's generator abandoned until request teardown,
        # where all their usage-decorator ``finally`` blocks fired at once
        # and mis-billed each round with the shared ``_last_usage`` of the
        # final round (duplicate token_usage rows). Exhausting the stream
        # also delivers the terminal usage-only chunk (Chat Completions
        # ``stream_options.include_usage``), which arrives *after* the
        # finish_reason chunk — so provider-exact counts land before the
        # decorator persists this round's row.
        stream_iter = self._iterate_stream(response)
        while True:
            try:
                chunk = next(stream_iter)
            except StopIteration:
                break
            except Exception:
                # A failure in the trailing frames (usage chunk, [DONE])
                # after the round already finished must not fail — or
                # fallback-restream — an answer the user has fully
                # received. GeneratorExit/KeyboardInterrupt are
                # BaseException and still propagate.
                #
                # The handler-local ``finish_reason`` only ever sees
                # tool-call finishes (providers don't surface a parseable
                # "stop" chunk — content arrives as bare strings), so the
                # final answer round is covered by the LLM-level
                # ``_stream_reached_finish`` flag instead — checked on the
                # primary AND its fallback (whichever actually served the
                # stream).
                llm = getattr(agent, "llm", None)
                provider_finished = bool(
                    getattr(llm, "_stream_reached_finish", False)
                    or getattr(
                        getattr(llm, "_fallback_llm", None),
                        "_stream_reached_finish",
                        False,
                    )
                )
                if finish_reason is not None or provider_finished:
                    logger.warning(
                        "Provider stream failed after finish "
                        "(finish_reason=%s, provider_finished=%s); "
                        "ignoring trailing-frame failure",
                        finish_reason,
                        provider_finished,
                        exc_info=True,
                    )
                    break
                raise
            if isinstance(chunk, dict) and chunk.get("type") == "thought":
                reasoning_buffer += chunk.get("thought") or ""
                yield chunk
                continue
            if isinstance(chunk, str):
                answered = True
                yield chunk
                continue
            parsed = self._parse_for_response(agent, chunk)
            if parsed.reasoning_content:
                reasoning_buffer += parsed.reasoning_content

            if parsed.tool_calls:
                for call in parsed.tool_calls:
                    if call.index is None:
                        # Providers like Google emit each parallel call as
                        # a COMPLETE, index-less ToolCall per chunk. They
                        # must never be merged into one another (dict
                        # arguments would even raise on ``+=``).
                        tool_calls[("complete", len(tool_calls))] = call
                        continue
                    if call.index not in tool_calls:
                        tool_calls[call.index] = call
                    else:
                        existing = tool_calls[call.index]
                        if call.id:
                            existing.id = call.id
                        if call.name:
                            existing.name = call.name
                        if call.arguments:
                            if existing.arguments is None:
                                existing.arguments = call.arguments
                            elif isinstance(existing.arguments, str) and isinstance(
                                call.arguments, str
                            ):
                                existing.arguments += call.arguments
                            else:
                                # Complete (non-delta) payloads: latest wins.
                                existing.arguments = call.arguments
                        # Preserve thought_signature for Google Gemini 3 models
                        if call.thought_signature:
                            existing.thought_signature = call.thought_signature
            if parsed.finish_reason == "tool_calls":
                finish_reason = "tool_calls"
                continue
            if parsed.content:
                buffer += parsed.content
                answered = True
                yield buffer
                buffer = ""
            if parsed.finish_reason == "stop" and finish_reason is None:
                finish_reason = "stop"

        if finish_reason != "tool_calls":
            # Silent-loss recovery: the stream ended cleanly (finish=stop
            # or plain exhaustion) but never yielded a visible answer,
            # and the model actually did work (thoughts non-empty).
            structured_output = (
                getattr(agent, "json_schema", None)
                or getattr(agent, "json_object", False)
            )
            if (
                not answered
                and reasoning_buffer
                and not _answer_recovered
                and not structured_output
            ):
                logger.warning(
                    "Stream ended reasoning-only (%d chars of thought, "
                    "0 answer bytes); re-sending once.",
                    len(reasoning_buffer),
                )
                enforce = getattr(agent, "_enforce_context_window", None)
                if callable(enforce):
                    messages = enforce(messages)
                # Mirror the finalize-round contract at the bottom of
                # this method: when the cap or context limit already
                # forced ``tools=None`` (with an accompanying "no more
                # tools" system message), the recovery must not reopen
                # tools, or the model could run one extra tool call past
                # the cap. ``_iteration >= MAX_TOOL_ITERATIONS`` catches
                # the finalize round.
                recovery_tools = (
                    None
                    if _iteration >= MAX_TOOL_ITERATIONS
                    or getattr(agent, "context_limit_reached", False)
                    else agent.tools
                )
                recovery_kwargs = {
                    "model": getattr(agent.llm, "model_id", None) or agent.model_id,
                    "messages": messages,
                    "tools": recovery_tools,
                }
                # Forward the sampling params the primary got
                # (temperature, max_tokens, top_p, …). ``response_format``
                # / ``response_schema`` are intentionally NOT forwarded
                # — the structured_output gate above bails before we get
                # here. ``previous_response_id`` is Responses-chain state
                # and belongs to the failed turn, not a fresh recovery.
                llm_params = getattr(agent, "llm_params", None)
                if llm_params:
                    recovery_kwargs.update(llm_params)
                recovery_response = agent.llm.gen_stream(**recovery_kwargs)
                self.llm_calls.append(build_stack_data(agent.llm))
                yield from self.handle_streaming(
                    agent,
                    recovery_response,
                    tools_dict,
                    messages,
                    _iteration=_iteration,
                    _answer_recovered=True,
                )
            return

        tool_handler_gen = self.handle_tool_calls(
            agent,
            list(tool_calls.values()),
            tools_dict,
            messages,
            reasoning_content=reasoning_buffer,
        )
        while True:
            try:
                yield next(tool_handler_gen)
            except StopIteration as e:
                messages, pending_actions = e.value
                break
        pause_reasoning = reasoning_buffer

        # If tools need approval or client execution, pause the loop
        if pending_actions:
            agent._pending_continuation = {
                "messages": messages,
                "pending_tool_calls": pending_actions,
                "tools_dict": tools_dict,
                "reasoning_content": pause_reasoning,
            }
            yield {
                "type": "tool_calls_pending",
                "data": {"pending_tool_calls": pending_actions},
            }
            return

        next_iteration = _iteration + 1
        cap_reached = next_iteration >= MAX_TOOL_ITERATIONS

        # Check if context limit was reached during tool execution
        if hasattr(agent, 'context_limit_reached') and agent.context_limit_reached:
            # Add system message warning about context limit
            messages.append({
                "role": "system",
                "content": (
                    "WARNING: Context window limit has been reached. "
                    "Please provide a final response to the user without making additional tool calls. "
                    "Summarize the work completed so far."
                )
            })
            logger.info("Context limit reached - instructing agent to wrap up")
        elif cap_reached:
            logger.warning(
                "agent tool loop hit cap (%d); forcing finalize",
                MAX_TOOL_ITERATIONS,
            )
            messages.append(
                {"role": "system", "content": _FINALIZE_INSTRUCTION},
            )

        # Hard pre-send gate: tool results appended this round may have
        # pushed the payload past the model's window — shrink or refuse
        # BEFORE the usage decorators run (a rejected dispatch would still
        # bill its full estimated prompt).
        enforce = getattr(agent, "_enforce_context_window", None)
        if callable(enforce):
            messages = enforce(messages)

        # See note above on agent.model_id vs llm.model_id.
        response = agent.llm.gen_stream(
            model=getattr(agent.llm, "model_id", None) or agent.model_id,
            messages=messages,
            tools=(
                None
                if cap_reached
                or getattr(agent, "context_limit_reached", False)
                else agent.tools
            ),
        )
        self.llm_calls.append(build_stack_data(agent.llm))

        yield from self.handle_streaming(
            agent, response, tools_dict, messages,
            _iteration=next_iteration,
            # Carry the recovery guard through tool-loop recursion so a
            # re-send that emitted tool_calls and then reasons-only-stops
            # doesn't trigger a second re-send — the bound is per outer
            # stream, not per tool round.
            _answer_recovered=_answer_recovered,
        )
