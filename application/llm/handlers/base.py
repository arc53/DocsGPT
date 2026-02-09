import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional, Union

from application.logging import build_stack_data

logger = logging.getLogger(__name__)


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

    @property
    def requires_tool_call(self) -> bool:
        """Check if the response requires tool calls."""
        return bool(self.tool_calls) and self.finish_reason == "tool_calls"


class LLMHandler(ABC):
    """Abstract base class for LLM handlers."""

    def __init__(self):
        self.llm_calls = []
        self.tool_calls = []

    @abstractmethod
    def parse_response(self, response: Any) -> LLMResponse:
        """Parse raw LLM response into standardized format."""
        pass

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
                        parts_text.append(str(item))
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
                # If this assistant turn contains tool calls, collect them; otherwise commit a response.
                if isinstance(content, list):
                    for item in content:
                        if "function_call" in item:
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
                        elif "function_response" in item:
                            fr = item["function_response"]
                            call_id = fr.get("call_id") or str(uuid.uuid4())
                            current_tool_calls[call_id] = {
                                "tool_name": "unknown_tool",
                                "action_name": fr.get("name"),
                                "arguments": None,
                                "result": fr.get("response", {}).get("result"),
                                "status": "completed",
                                "call_id": call_id,
                            }
                    # No direct assistant text here; continue to next message
                    continue

                response_text = self._extract_text_from_content(content)
                _commit_query(response_text)

            elif role == "tool":
                # Attach tool outputs to the latest pending tool call if possible
                tool_text = self._extract_text_from_content(content)
                # Attempt to parse function_response style
                call_id = None
                if isinstance(content, list):
                    for item in content:
                        if "function_response" in item and item["function_response"].get("call_id"):
                            call_id = item["function_response"]["call_id"]
                            break
                if call_id and call_id in current_tool_calls:
                    current_tool_calls[call_id]["result"] = tool_text
                    current_tool_calls[call_id]["status"] = "completed"
                elif queries:
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

            # Use orchestrator to perform compression
            result = orchestrator.compress_mid_execution(
                conversation_id=agent.conversation_id,
                user_id=agent.initial_user_id,
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
            provider = get_provider_from_model_id(compression_model)
            api_key = get_api_key_for_provider(provider)
            compression_llm = LLMCreator.create_llm(
                provider,
                api_key,
                getattr(agent, "user_api_key", None),
                getattr(agent, "decoded_token", None),
                model_id=compression_model,
            )

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

            metadata = compression_service.compress_conversation(
                conversation,
                compress_up_to_index=compress_up_to,
            )

            # If compression doesn't reduce tokens, fall back to minimal pruning
            if (
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
        self, agent, tool_calls: List[ToolCall], tools_dict: Dict, messages: List[Dict]
    ) -> Generator:
        """
        Execute tool calls and update conversation history.

        Args:
            agent: The agent instance
            tool_calls: List of tool calls to execute
            tools_dict: Available tools dictionary
            messages: Current conversation history

        Returns:
            Updated messages list
        """
        updated_messages = messages.copy()

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
            try:
                self.tool_calls.append(call)
                tool_executor_gen = agent._execute_tool_action(tools_dict, call)
                while True:
                    try:
                        yield next(tool_executor_gen)
                    except StopIteration as e:
                        tool_response, call_id = e.value
                        break
                    
                function_call_content = {
                    "function_call": {
                        "name": call.name,
                        "args": call.arguments,
                        "call_id": call_id,
                    }
                }
                # Include thought_signature for Google Gemini 3 models
                # It should be at the same level as function_call, not inside it
                if call.thought_signature:
                    function_call_content["thought_signature"] = call.thought_signature
                updated_messages.append(
                    {
                        "role": "assistant",
                        "content": [function_call_content],
                    }
                )


                updated_messages.append(self.create_tool_message(call, tool_response))
            except Exception as e:
                logger.error(f"Error executing tool: {str(e)}", exc_info=True)
                error_call = ToolCall(
                    id=call.id, name=call.name, arguments=call.arguments
                )
                error_response = f"Error executing tool: {str(e)}"
                error_message = self.create_tool_message(error_call, error_response)
                updated_messages.append(error_message)

                call_parts = call.name.split("_")
                if len(call_parts) >= 2:
                    tool_id = call_parts[-1]  # Last part is tool ID (e.g., "1")
                    action_name = "_".join(call_parts[:-1])
                    tool_name = tools_dict.get(tool_id, {}).get("name", "unknown_tool")
                    full_action_name = f"{action_name}_{tool_id}"
                else:
                    tool_name = "unknown_tool"
                    action_name = call.name
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
        return updated_messages

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
        parsed = self.parse_response(response)
        self.llm_calls.append(build_stack_data(agent.llm))

        while parsed.requires_tool_call:
            tool_handler_gen = self.handle_tool_calls(
                agent, parsed.tool_calls, tools_dict, messages
            )
            while True:
                try:
                    yield next(tool_handler_gen)
                except StopIteration as e:
                    messages = e.value
                    break
            response = agent.llm.gen(
                model=agent.model_id, messages=messages, tools=agent.tools
            )
            parsed = self.parse_response(response)
            self.llm_calls.append(build_stack_data(agent.llm))
        return parsed.content

    def handle_streaming(
        self, agent, response: Any, tools_dict: Dict, messages: List[Dict]
    ) -> Generator:
        """
        Handle streaming response flow.

        Args:
            agent: The agent instance
            response: Current LLM response
            tools_dict: Available tools dictionary
            messages: Conversation history

        Yields:
            Streaming response chunks
        """
        buffer = ""
        tool_calls = {}

        for chunk in self._iterate_stream(response):
            if isinstance(chunk, dict) and chunk.get("type") == "thought":
                yield chunk
                continue
            if isinstance(chunk, str):
                yield chunk
                continue
            parsed = self.parse_response(chunk)

            if parsed.tool_calls:
                for call in parsed.tool_calls:
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
                            else:
                                existing.arguments += call.arguments
                        # Preserve thought_signature for Google Gemini 3 models
                        if call.thought_signature:
                            existing.thought_signature = call.thought_signature
            if parsed.finish_reason == "tool_calls":
                tool_handler_gen = self.handle_tool_calls(
                    agent, list(tool_calls.values()), tools_dict, messages
                )
                while True:
                    try:
                        yield next(tool_handler_gen)
                    except StopIteration as e:
                        messages = e.value
                        break
                tool_calls = {}

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

                response = agent.llm.gen_stream(
                    model=agent.model_id, messages=messages, tools=agent.tools if not agent.context_limit_reached else None
                )
                self.llm_calls.append(build_stack_data(agent.llm))

                yield from self.handle_streaming(agent, response, tools_dict, messages)
                return
            if parsed.content:
                buffer += parsed.content
                yield buffer
                buffer = ""
            if parsed.finish_reason == "stop":
                return
