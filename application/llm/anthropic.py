import base64
import json
import logging
from typing import Any, Dict, Generator, List, Optional, Tuple

from anthropic import Anthropic

from application.core.settings import settings
from application.llm.base import BaseLLM
from application.storage.storage_creator import StorageCreator

logger = logging.getLogger(__name__)

# The Messages API requires ``max_tokens``. The retired Text Completions
# path defaulted to 300, which truncates almost any real answer; 4096 is
# comfortably above a typical chat answer while staying under the SDK's
# non-streaming timeout guard. Callers override via ``max_tokens``.
DEFAULT_MAX_TOKENS = 4096

# Request params forwarded verbatim to ``messages.create``. The agent layer
# merges caller-supplied OpenAI sampling params (``llm_params``) into the
# gen kwargs for every provider, so an allowlist is what keeps an
# OpenAI-only key (``frequency_penalty``, ``response_format``,
# ``reasoning_effort``, ...) from 400-ing an Anthropic request.
_PASSTHROUGH_PARAMS = (
    "temperature",
    "top_p",
    "top_k",
    "stop_sequences",
    "tool_choice",
    "thinking",
    "metadata",
)

# ``tool_choice`` values in OpenAI's vocabulary mapped to Anthropic's. OpenAI
# sends a bare string; Anthropic requires an object and 400s on the string.
# ``any``/``auto``/``none`` are also accepted spelled Anthropic-style, for a
# caller that speaks the provider's own dialect.
_TOOL_CHOICE_ALIASES = {
    "auto": {"type": "auto"},
    "none": {"type": "none"},
    "required": {"type": "any"},
    "any": {"type": "any"},
}

# ``tool_choice`` object types the Messages API accepts as-is (so a caller's
# ``disable_parallel_tool_use`` survives).
_ANTHROPIC_TOOL_CHOICE_TYPES = frozenset({"auto", "any", "tool", "none"})

# ``thinking.type`` values that turn extended thinking *on*. See
# ``_build_request`` for why these are incompatible with tool use here.
_THINKING_ENABLED_TYPES = frozenset({"enabled", "adaptive"})

# Content-block types the Messages API accepts inside a message. Anything
# else (e.g. an OpenAI ``image_url`` part replayed from history) is dropped
# rather than forwarded, so a mixed-provider conversation degrades to text
# instead of erroring upstream.
_PASSTHROUGH_BLOCK_TYPES = frozenset(
    {"text", "image", "document", "tool_use", "tool_result", "thinking"}
)

# Anthropic rejects an empty ``messages`` array and requires the first turn
# to be ``user``. Degenerate histories (empty, or leading with an assistant
# turn) get this placeholder rather than raising.
_PLACEHOLDER_USER_TEXT = "(no user message provided)"

# Anthropic's stop reasons in the OpenAI vocabulary the rest of the codebase
# speaks (``_last_finish_reason`` is read by the /v1 chat-completions
# response builder and the empty-answer classifier).
_STOP_REASON_MAP = {
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "end_turn": "stop",
    "stop_sequence": "stop",
    "pause_turn": "stop",
    "refusal": "stop",
}

# ``image/jpg`` is accepted by our upload path but is not a media type the
# Messages API recognises — it 400s. Normalise on the way out.
_MEDIA_TYPE_ALIASES = {"image/jpg": "image/jpeg"}


class AnthropicLLM(BaseLLM):
    provider_name = "anthropic"

    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):

        super().__init__(*args, **kwargs)
        self.api_key = api_key or settings.ANTHROPIC_API_KEY or settings.API_KEY
        self.user_api_key = user_api_key

        # Use custom base_url if provided
        if base_url:
            self.anthropic = Anthropic(api_key=self.api_key, base_url=base_url)
        else:
            self.anthropic = Anthropic(api_key=self.api_key)

        self.storage = StorageCreator.get_storage()
        self._last_usage: Optional[Dict[str, Any]] = None
        self._last_usage_claimed = False
        self._last_finish_reason: Optional[str] = None
        self._stream_reached_finish = False

    # ------------------------------------------------------------------
    # Message / tool translation
    # ------------------------------------------------------------------

    @staticmethod
    def _system_text(content: Any) -> str:
        """Flatten a system message's content to plain text.

        Args:
            content: Either a string or a list of content-block dicts.

        Returns:
            The concatenated text, or an empty string when there is none.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                item["text"]
                for item in content
                if isinstance(item, dict) and item.get("text")
            )
        return ""

    @classmethod
    def _content_blocks(cls, content: Any) -> List[Dict[str, Any]]:
        """Normalise a message's ``content`` to Anthropic content blocks.

        Args:
            content: A string, a list of content-block dicts, or ``None``.

        Returns:
            A list of Anthropic-shaped content blocks; empty when the message
            carries nothing the Messages API can represent.
        """
        if content is None:
            return []
        if isinstance(content, str):
            return [{"type": "text", "text": content}] if content else []
        if not isinstance(content, list):
            text = str(content)
            return [{"type": "text", "text": text}] if text else []

        blocks: List[Dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "text":
                if item.get("text"):
                    blocks.append({"type": "text", "text": item["text"]})
            elif item_type in _PASSTHROUGH_BLOCK_TYPES:
                blocks.append(item)
            else:
                logger.debug(
                    "AnthropicLLM: dropping unsupported content block %r", item_type
                )
        return blocks

    @staticmethod
    def _tool_use_blocks(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert internal ``tool_calls`` entries to Anthropic ``tool_use``.

        Args:
            tool_calls: OpenAI-shaped tool calls as produced by
                ``LLMHandler.handle_tool_calls``.

        Returns:
            A list of ``tool_use`` content blocks.
        """
        blocks = []
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            arguments = function.get("arguments", "{}")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments or "{}")
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "AnthropicLLM: unparseable tool arguments for %r; sending {}",
                        function.get("name"),
                    )
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            blocks.append(
                {
                    "type": "tool_use",
                    "id": call.get("id") or "",
                    "name": function.get("name") or "",
                    "input": arguments,
                }
            )
        return blocks

    @classmethod
    def _clean_messages_anthropic(
        cls, messages: Optional[List[Dict[str, Any]]]
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Convert the internal OpenAI-shaped history to the Messages API.

        System turns are lifted into the top-level ``system`` parameter,
        assistant ``tool_calls`` become ``tool_use`` blocks, ``role: tool``
        turns become ``tool_result`` blocks on a user turn, and consecutive
        same-role turns are merged so the result alternates and leads with a
        user turn (which also puts a parallel batch's tool results into the
        single user message Anthropic requires).

        Args:
            messages: The internal conversation history.

        Returns:
            ``(anthropic_messages, system_prompt)``; *system_prompt* is
            ``None`` when the history carried no system turn.
        """
        system_parts: List[str] = []
        mapped: List[Dict[str, Any]] = []

        for message in messages or []:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")

            if role == "system":
                text = cls._system_text(content)
                if text:
                    system_parts.append(text)
                continue

            if role == "tool":
                tool_content = content
                if not isinstance(tool_content, str):
                    tool_content = json.dumps(tool_content, default=str)
                mapped.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.get("tool_call_id") or "",
                                "content": tool_content,
                            }
                        ],
                    }
                )
                continue

            blocks = cls._content_blocks(content)
            if role == "assistant":
                blocks.extend(cls._tool_use_blocks(message.get("tool_calls") or []))
            if not blocks:
                # An empty content array is a 400; drop the turn instead.
                continue
            mapped.append(
                {
                    "role": "assistant" if role == "assistant" else "user",
                    "content": blocks,
                }
            )

        # Anthropic requires a leading user turn.
        if not mapped or mapped[0]["role"] != "user":
            mapped.insert(
                0,
                {
                    "role": "user",
                    "content": [{"type": "text", "text": _PLACEHOLDER_USER_TEXT}],
                },
            )

        merged: List[Dict[str, Any]] = []
        for message in mapped:
            if merged and merged[-1]["role"] == message["role"]:
                merged[-1]["content"].extend(message["content"])
            else:
                merged.append(message)

        system_prompt = "\n\n".join(system_parts) if system_parts else None
        return merged, system_prompt

    @staticmethod
    def _clean_tools_anthropic(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert OpenAI function schemas to Anthropic tool definitions.

        Args:
            tools: Tool definitions in the ``{"type": "function",
                "function": {...}}`` shape ``ToolExecutor`` emits.

        Returns:
            A list of ``{"name", "description", "input_schema"}`` dicts.
        """
        cleaned = []
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function") or tool
            name = function.get("name")
            if not name:
                continue
            parameters = function.get("parameters") or {"type": "object", "properties": {}}
            cleaned.append(
                {
                    "name": name,
                    "description": function.get("description", "") or "",
                    "input_schema": parameters,
                }
            )
        return cleaned

    @staticmethod
    def _clean_tool_choice(tool_choice: Any) -> Optional[Dict[str, Any]]:
        """Translate an OpenAI ``tool_choice`` into Anthropic's object shape.

        OpenAI sends ``"auto"``/``"none"``/``"required"`` or
        ``{"type": "function", "function": {"name": ...}}``; Anthropic wants
        ``{"type": "auto"|"any"|"tool"|"none"}`` (with ``name`` for ``tool``)
        and rejects both OpenAI shapes with a 400.

        Args:
            tool_choice: The caller-supplied value, in either vocabulary.

        Returns:
            An Anthropic-shaped ``tool_choice``, or ``None`` when the value is
            unrecognised — dropped (degrading to the API default of ``auto``)
            rather than forwarded into a 400 that fails the whole request.
        """
        if isinstance(tool_choice, str):
            return _TOOL_CHOICE_ALIASES.get(tool_choice.lower())
        if not isinstance(tool_choice, dict):
            return None

        choice_type = tool_choice.get("type")
        if choice_type == "function":
            name = (tool_choice.get("function") or {}).get("name")
            return {"type": "tool", "name": name} if name else None
        if choice_type in _ANTHROPIC_TOOL_CHOICE_TYPES:
            return tool_choice
        return None

    @staticmethod
    def _stop_sequences(stop: Any) -> Optional[List[str]]:
        """Normalise an OpenAI ``stop`` value to Anthropic ``stop_sequences``.

        Args:
            stop: A string, or a sequence of strings.

        Returns:
            The non-empty stop strings, or ``None`` when there are none.
        """
        if isinstance(stop, str):
            stop = [stop]
        if not isinstance(stop, (list, tuple)):
            return None
        sequences = [item for item in stop if isinstance(item, str) and item]
        return sequences or None

    # ------------------------------------------------------------------
    # Usage
    # ------------------------------------------------------------------

    def _record_usage(self, usage: Any, *, output_only: bool = False) -> None:
        """Capture provider-reported usage for the current call.

        Anthropic reports cache reads and writes in bins *separate* from
        ``input_tokens``, whereas ``_prefer_provider_usage`` expects
        ``prompt_tokens`` to be the billing-parity total. The three input
        bins are therefore summed into ``prompt_tokens`` and also reported
        individually under ``prompt_tokens_details`` so nothing is dropped.

        Args:
            usage: An SDK usage object (or ``None``).
            output_only: True for the ``message_delta`` event, which carries
                the final ``output_tokens`` but no input counts.
        """
        if usage is None:
            return
        try:
            output = int(getattr(usage, "output_tokens", 0) or 0)
            # On a message_delta the input bins are absent; the counts kept at
            # message_start are reused below instead.
            if not output_only:
                base_input = int(getattr(usage, "input_tokens", 0) or 0)
                created = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
                cached = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        except (TypeError, ValueError):
            return

        previous = self._last_usage if isinstance(self._last_usage, dict) else {}
        if output_only:
            # Keep the input counts captured at ``message_start``.
            prompt = int(previous.get("prompt_tokens", 0) or 0)
            details = previous.get("prompt_tokens_details")
        else:
            prompt = base_input + created + cached
            details = {}
            if cached:
                details["cached_tokens"] = cached
            if created:
                details["cache_creation_tokens"] = created
            details = details or None

        if not prompt and not output:
            # A zeroed usage object must not clobber the tiktoken estimate.
            return

        result: Dict[str, Any] = {
            "prompt_tokens": prompt,
            "completion_tokens": output,
            "total_tokens": prompt + output,
        }
        if details:
            result["prompt_tokens_details"] = details
        self._last_usage = result
        self._last_usage_claimed = False

    def _set_finish_reason(self, stop_reason: Optional[str]) -> None:
        """Record the terminal reason in the codebase's OpenAI vocabulary."""
        if not stop_reason:
            return
        self._last_finish_reason = _STOP_REASON_MAP.get(stop_reason, "stop")

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    def _build_request(
        self,
        model: str,
        messages: Optional[List[Dict[str, Any]]],
        tools: Optional[List[Dict[str, Any]]],
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Assemble the ``messages.create`` payload.

        Args:
            model: Upstream model name.
            messages: Internal conversation history.
            tools: OpenAI-shaped tool definitions, or ``None``.
            kwargs: Caller kwargs; the params in ``_PASSTHROUGH_PARAMS`` are
                forwarded verbatim, and the OpenAI aliases ``max_tokens`` /
                ``max_completion_tokens``, ``stop`` and ``tool_choice`` are
                translated. Everything else is dropped.

        Returns:
            The keyword arguments for ``client.messages.create``.
        """
        cleaned_messages, system_prompt = self._clean_messages_anthropic(messages)
        # OpenAI clients send either spelling (``max_completion_tokens`` is the
        # newer one, and the /v1 translator drops the alias when both arrive);
        # ignoring it silently capped every such request at DEFAULT_MAX_TOKENS.
        max_tokens = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens")
        params: Dict[str, Any] = {
            "model": model,
            "messages": cleaned_messages,
            "max_tokens": int(max_tokens or DEFAULT_MAX_TOKENS),
        }
        if system_prompt:
            # A ``cache_control`` breakpoint would go here — on the last
            # system block once ``system`` becomes a list of text blocks.
            params["system"] = system_prompt

        # Defense-in-depth: honour the registry's capability flag, mirroring
        # the OpenAI provider.
        if tools and not self._supports_tools():
            tools = None
        if tools:
            cleaned_tools = self._clean_tools_anthropic(tools)
            if cleaned_tools:
                params["tools"] = cleaned_tools

        for key in _PASSTHROUGH_PARAMS:
            if kwargs.get(key) is not None:
                params[key] = kwargs[key]

        # OpenAI's ``stop`` is Anthropic's ``stop_sequences``. A caller that
        # already speaks Anthropic wins.
        if "stop_sequences" not in params:
            sequences = self._stop_sequences(kwargs.get("stop"))
            if sequences:
                params["stop_sequences"] = sequences

        if "tools" not in params:
            params.pop("tool_choice", None)
        elif "tool_choice" in params:
            choice = self._clean_tool_choice(params["tool_choice"])
            if choice is None:
                logger.debug(
                    "AnthropicLLM: dropping unrecognised tool_choice %r",
                    params["tool_choice"],
                )
                params.pop("tool_choice")
            else:
                params["tool_choice"] = choice

        # Extended thinking and tool use cannot be combined here. Anthropic
        # requires the complete, unmodified (signed) thinking block to be
        # replayed on the assistant turn that carries ``tool_use``, and this
        # adapter cannot produce one: ``_raw_gen_stream`` keeps only the
        # thinking *text* (``signature_delta`` is not captured), and the
        # internal assistant-message shape carries reasoning as a plain string
        # with nowhere to put the signature. Sending ``thinking`` anyway works
        # for the first request and then 400s on the tool-result round, killing
        # the conversation. Round-tripping the block would require threading a
        # signature through LLMHandler/BaseAgent.
        if params.get("tools") and isinstance(params.get("thinking"), dict):
            if params["thinking"].get("type") in _THINKING_ENABLED_TYPES:
                logger.warning(
                    "AnthropicLLM: dropping `thinking` for a tool-enabled "
                    "request; thinking blocks cannot be round-tripped."
                )
                params.pop("thinking")
        return params

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _raw_gen(
        self,
        baseself,
        model,
        messages,
        stream=False,
        tools=None,
        **kwargs,
    ):
        """Non-streaming completion via the Messages API.

        Returns:
            The raw ``Message`` when tools were offered (the handler parses
            its ``tool_use`` blocks), otherwise the concatenated text.
        """
        params = self._build_request(model, messages, tools, kwargs)
        self._last_usage = None
        self._last_finish_reason = None
        logger.debug(
            "Prepared Anthropic request with %d messages and %d tools",
            len(params["messages"]),
            len(params.get("tools") or []),
        )
        response = self.anthropic.messages.create(**params)
        self._record_usage(getattr(response, "usage", None))
        self._set_finish_reason(getattr(response, "stop_reason", None))

        if params.get("tools"):
            return response
        return "".join(
            block.text
            for block in getattr(response, "content", None) or []
            if getattr(block, "type", None) == "text" and getattr(block, "text", None)
        )

    def _raw_gen_stream(
        self,
        baseself,
        model,
        messages,
        stream=True,
        tools=None,
        **kwargs,
    ) -> Generator[Any, None, None]:
        """Streaming completion via the Messages API.

        Yields:
            ``str`` for text deltas, ``{"type": "thought", ...}`` for
            extended-thinking deltas, and ``{"type": "tool_use", ...}`` once
            per completed tool call. Tool-call JSON is buffered here and
            emitted whole, so the handler yields index-less (complete)
            ``ToolCall``s that ``handle_streaming`` keeps intact.
        """
        params = self._build_request(model, messages, tools, kwargs)
        params["stream"] = True
        self._last_usage = None
        self._last_finish_reason = None
        self._stream_reached_finish = False
        logger.debug(
            "Prepared Anthropic streaming request with %d messages and %d tools",
            len(params["messages"]),
            len(params.get("tools") or []),
        )
        response = self.anthropic.messages.create(**params)

        # Partial ``tool_use`` blocks, keyed by content-block index.
        tool_blocks: Dict[Any, Dict[str, str]] = {}
        try:
            for event in response:
                event_type = getattr(event, "type", None)

                if event_type == "message_start":
                    self._record_usage(
                        getattr(getattr(event, "message", None), "usage", None)
                    )

                elif event_type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if getattr(block, "type", None) == "tool_use":
                        tool_blocks[getattr(event, "index", None)] = {
                            "id": getattr(block, "id", "") or "",
                            "name": getattr(block, "name", "") or "",
                            "json": "",
                        }

                elif event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        text = getattr(delta, "text", None)
                        if text:
                            yield text
                    elif delta_type == "thinking_delta":
                        thinking = getattr(delta, "thinking", None)
                        if thinking:
                            yield {"type": "thought", "thought": thinking}
                    elif delta_type == "input_json_delta":
                        pending = tool_blocks.get(getattr(event, "index", None))
                        if pending is not None:
                            pending["json"] += getattr(delta, "partial_json", "") or ""

                elif event_type == "content_block_stop":
                    pending = tool_blocks.pop(getattr(event, "index", None), None)
                    if pending is not None:
                        yield {
                            "type": "tool_use",
                            "id": pending["id"],
                            "name": pending["name"],
                            # A tool with no arguments produces no
                            # input_json_delta at all; "" would blow up the
                            # executor's json.loads.
                            "arguments": pending["json"] or "{}",
                        }

                elif event_type == "message_delta":
                    self._record_usage(getattr(event, "usage", None), output_only=True)
                    stop_reason = getattr(
                        getattr(event, "delta", None), "stop_reason", None
                    )
                    if stop_reason:
                        # The answer is complete; only trailing frames remain.
                        # ``_stream_with_fallback`` reads this to refuse
                        # restreaming an answer the user already received.
                        self._stream_reached_finish = True
                        self._set_finish_reason(stop_reason)
        finally:
            if hasattr(response, "close"):
                response.close()

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def _supports_tools(self) -> bool:
        """Whether this model may be offered tools.

        Returns:
            The registry capability flag when one is attached (BYOM users can
            disable tools), otherwise True — every current Claude model
            supports tool use.
        """
        if self.capabilities is not None:
            return bool(self.capabilities.supports_tools)
        return True

    def get_supported_attachment_types(self) -> List[str]:
        """
        Return a list of MIME types supported by Anthropic Claude for file uploads.
        Claude accepts images and PDFs natively (PDFs as ``document`` blocks),
        so no PDF-to-image conversion is needed.

        Returns:
            list: List of supported MIME types
        """
        return [
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/webp",
            "image/gif",
            "application/pdf",
        ]

    def prepare_messages_with_attachments(self, messages, attachments=None):
        """
        Process attachments for Anthropic Claude API.
        Formats images as ``image`` blocks and PDFs as ``document`` blocks.

        Args:
            messages (list): List of message dictionaries.
            attachments (list): List of attachment dictionaries with content and metadata.

        Returns:
            list: Messages formatted with image/document content for Claude API.
        """
        if not attachments:
            return messages

        prepared_messages = messages.copy()

        # Find the last user message to attach images to
        user_message_index = None
        for i in range(len(prepared_messages) - 1, -1, -1):
            if prepared_messages[i].get("role") == "user":
                user_message_index = i
                break

        if user_message_index is None:
            user_message = {"role": "user", "content": []}
            prepared_messages.append(user_message)
            user_message_index = len(prepared_messages) - 1

        # Convert content to list format if it's a string
        if isinstance(prepared_messages[user_message_index].get("content"), str):
            text_content = prepared_messages[user_message_index]["content"]
            prepared_messages[user_message_index]["content"] = [
                {"type": "text", "text": text_content}
            ]
        elif not isinstance(prepared_messages[user_message_index].get("content"), list):
            prepared_messages[user_message_index]["content"] = []

        for attachment in attachments:
            mime_type = attachment.get("mime_type")
            is_image = bool(mime_type and mime_type.startswith("image/"))
            is_pdf = mime_type == "application/pdf"
            if not (is_image or is_pdf):
                continue

            try:
                # Pre-converted attachments (e.g. PDF-to-image) already
                # carry base64 in ``data``.
                if "data" in attachment:
                    encoded = attachment["data"]
                else:
                    encoded = self._get_base64_image(attachment)

                prepared_messages[user_message_index]["content"].append(
                    {
                        "type": "document" if is_pdf else "image",
                        "source": {
                            "type": "base64",
                            "media_type": _MEDIA_TYPE_ALIASES.get(
                                mime_type, mime_type
                            ),
                            "data": encoded,
                        },
                    }
                )

            except Exception as e:
                logger.error(f"Error processing attachment: {e}", exc_info=True)
                if "content" in attachment:
                    prepared_messages[user_message_index]["content"].append(
                        {
                            "type": "text",
                            "text": f"[File could not be processed: {attachment.get('path', 'unknown')}]",
                        }
                    )

        return prepared_messages

    def _get_base64_image(self, attachment):
        """
        Convert an image file to base64 encoding.

        Args:
            attachment (dict): Attachment dictionary with path and metadata.

        Returns:
            str: Base64-encoded image data.
        """
        file_path = attachment.get("path")
        if not file_path:
            raise ValueError("No file path provided in attachment")
        try:
            with self.storage.get_file(file_path) as image_file:
                return base64.b64encode(image_file.read()).decode("utf-8")
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {file_path}")
