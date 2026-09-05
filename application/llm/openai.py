import base64
import hashlib
import io
import json
import logging
import os.path
from typing import Any, Callable

from openai import BadRequestError, OpenAI

from application.core.settings import settings
from application.llm.base import BaseLLM, optional_int
from application.storage.storage_creator import StorageCreator

# Placeholder sent to OpenAI-compatible backends that require no credentials.
NO_API_KEY = "sk-no-key"

# Request keys that only make sense alongside ``tools``; all dropped together
# when an endpoint turns out not to serve tool calling.
_TOOL_REQUEST_KEYS = ("tools", "tool_choice", "parallel_tool_calls")

# Knobs that shape *how* tools are called. A 400 naming one of these is a bad
# argument, so they are dropped on their own before tools are given up.
_TOOL_CHOICE_KEYS = ("tool_choice", "parallel_tool_calls")

# Substrings an OpenAI-compatible server puts in a 400 when it understands the
# request but cannot serve tool calling: vLLM without --enable-auto-tool-choice
# / --tool-call-parser, llama.cpp, TGI, Ollama and friends. Matched case
# insensitively, and only for requests that actually carried tools — so a false
# positive degrades to a tool-less answer rather than a failed chat.
_TOOLS_UNSUPPORTED_MARKERS = (
    "enable-auto-tool-choice",
    "tool-call-parser",
    # Deliberately no bare "tool_choice"/"tool choice": a 400 about a malformed
    # tool_choice *argument* names the parameter without meaning the endpoint
    # lacks tool support. Only unambiguous phrasings belong here.
    "unsupported parameter: 'tool_choice'",
    "unknown field: tool_choice",
    "tools are not supported",
    "tools is not supported",
    "does not support tools",
    "doesn't support tools",
    "tool calling",
    "tool call is not supported",
    "function calling",
    "functions are not supported",
    "does not support function",
    "unsupported parameter: 'tools'",
    "unknown field: tools",
)


def _provider_message(error: Exception) -> str:
    """The server's own message text, without the SDK's whole-body repr.

    ``openai._base_client`` interpolates the entire decoded JSON body into the
    exception message, so matching ``str(error)`` would let a *parameter name*
    ("param": "tool_choice") read as "this endpoint cannot serve tools".

    Args:
        error: The exception raised by the provider SDK.

    Returns:
        The server's message when the body carries one, else ``str(error)``.
    """
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        inner = body.get("error")
        if isinstance(inner, dict) and inner.get("message"):
            return str(inner["message"])
        if body.get("message"):
            return str(body["message"])
    return str(error)


def _is_tools_unsupported_error(error: Exception) -> bool:
    """Whether a 400 says the endpoint cannot serve tool calling.

    Args:
        error: The exception raised by the provider SDK.

    Returns:
        True when the server's message matches a tool-calling marker.
    """
    haystack = _provider_message(error).lower()
    return any(marker in haystack for marker in _TOOLS_UNSUPPORTED_MARKERS)


def _truncate_base64_for_logging(messages):
    """
    Create a copy of messages with base64 data truncated for readable logging.

    Args:
        messages: List of message dicts

    Returns:
        Copy of messages with truncated base64 content
    """
    import copy

    def truncate_content(content):
        if isinstance(content, str):
            # Check if it looks like a data URL with base64
            if content.startswith("data:") and ";base64," in content:
                prefix_end = content.index(";base64,") + len(";base64,")
                prefix = content[:prefix_end]
                return f"{prefix}[BASE64_DATA_TRUNCATED, length={len(content) - prefix_end}]"
            return content
        elif isinstance(content, list):
            return [truncate_item(item) for item in content]
        elif isinstance(content, dict):
            return {k: truncate_content(v) for k, v in content.items()}
        return content

    def truncate_item(item):
        if isinstance(item, dict):
            result = {}
            for k, v in item.items():
                if k == "url" and isinstance(v, str) and ";base64," in v:
                    prefix_end = v.index(";base64,") + len(";base64,")
                    prefix = v[:prefix_end]
                    result[k] = f"{prefix}[BASE64_DATA_TRUNCATED, length={len(v) - prefix_end}]"
                elif k == "data" and isinstance(v, str) and len(v) > 100:
                    result[k] = f"[BASE64_DATA_TRUNCATED, length={len(v)}]"
                else:
                    result[k] = truncate_content(v)
            return result
        return truncate_content(item)

    truncated = []
    for msg in messages:
        msg_copy = copy.copy(msg)
        if "content" in msg_copy:
            msg_copy["content"] = truncate_content(msg_copy["content"])
        truncated.append(msg_copy)

    return truncated


class _RespFunction:
    """Minimal stand-in for an OpenAI tool-call ``function`` object."""

    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _RespToolCall:
    """Chat-Completions-shaped tool call synthesized from a Responses
    ``function_call`` item, so the existing OpenAI handler and the streaming
    tool-call accumulator consume it unchanged."""

    def __init__(self, id, index, name, arguments):
        self.id = id
        self.index = index
        self.type = "function"
        self.function = _RespFunction(name, arguments)


class _RespDelta:
    """Stand-in for a streaming chat ``choice.delta``."""

    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _RespMessage:
    """Stand-in for a non-streaming chat ``choice.message``."""

    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _RespChoice:
    """Stand-in for ``response.choices[0]`` (non-streaming) or a streaming
    chunk's choice. ``parse_response`` reads ``.message`` or ``.delta`` plus
    ``.finish_reason``."""

    def __init__(self, finish_reason, delta=None, message=None):
        self.delta = delta
        self.message = message
        self.finish_reason = finish_reason


class OpenAILLM(BaseLLM):
    provider_name = "openai"
    structured_output_kwarg = "response_format"

    # Flipped once this endpoint answered 400 on a request carrying tools.
    # Instance-scoped (the assignment shadows this class default), so an
    # agent loop pays for the discovery round trip at most once.
    _tools_rejected = False

    def __init__(
        self,
        api_key=None,
        user_api_key=None,
        base_url=None,
        http_client=None,
        *args,
        **kwargs,
    ):

        super().__init__(*args, **kwargs)
        # openai>=2.53 rejects a falsy api_key at construction. Keyless
        # OpenAI-compatible backends (Ollama, llama.cpp, vLLM) legitimately have
        # none, and pydantic-settings yields "" for a bare `API_KEY=` in .env.
        self.api_key = (
            api_key or settings.OPENAI_API_KEY or settings.API_KEY or NO_API_KEY
        )
        self.user_api_key = user_api_key

        # Priority: 1) Parameter base_url, 2) Settings OPENAI_BASE_URL, 3) Default
        effective_base_url = None
        if base_url and isinstance(base_url, str) and base_url.strip():
            effective_base_url = base_url
        elif (
            isinstance(settings.OPENAI_BASE_URL, str)
            and settings.OPENAI_BASE_URL.strip()
        ):
            effective_base_url = settings.OPENAI_BASE_URL
        else:
            effective_base_url = "https://api.openai.com/v1"
        self._effective_base_url = effective_base_url

        # http_client (set by LLMCreator for BYOM) is a DNS-rebinding-safe
        # httpx.Client; without it the SDK re-resolves DNS per request.
        if http_client is not None:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=effective_base_url,
                http_client=http_client,
            )
        else:
            self.client = OpenAI(
                api_key=self.api_key, base_url=effective_base_url
            )
        self.storage = StorageCreator.get_storage()
        # Per-instance state for the Responses API path. ``_reasoning_for_calls``
        # maps a function-call id to the reasoning items that preceded it, so
        # the model's chain-of-thought survives the in-turn tool round-trip.
        # ``_last_response_id`` is the most recent /v1/responses id, used to
        # chain turns when OPENAI_RESPONSES_STORE is enabled.
        self._reasoning_for_calls = {}
        self._last_response_id = None
        # call_ids the most recent response emitted; the chained-request
        # coverage guard checks the next turn answers all of them.
        self._last_response_call_ids = set()
        self._last_reasoning_items = []
        self._last_usage = None
        # One-shot guard consumed by ``_prefer_provider_usage``: fresh
        # provider usage flips it False, the first billing read flips it
        # True, so no two token_usage rows share one reported usage.
        self._last_usage_claimed = False
        # True once the current stream delivered a finish signal — only
        # trailing frames remain, so a failure there must not trigger a
        # fallback restream of the already-delivered answer.
        self._stream_reached_finish = False
        self._imported_response_id = None
        # Hash of the system head the current Responses chain already holds.
        # The server appends a re-sent system message after the stored
        # transcript instead of deduping it, so a chained round only carries
        # the head when it changed.
        self._chain_system_hash = None
        # The head hash a request in flight would establish; it becomes
        # ``_chain_system_hash`` only once the provider records the response,
        # so a failed request leaves the chain's head unchanged and a retry
        # re-sends the head.
        self._pending_system_hash = None
        # Opaque per-user prompt-cache routing key, set by the agent per call.
        self._prompt_cache_key = None
        # Files-API ids for inline ``file_data`` content parts already
        # uploaded, keyed by content hash. First-line cache for the
        # in-request tool loop; the Redis-backed cross-request cache
        # (see ``_inline_file_id_cache_*``) covers /v1 clients that
        # resend the same ``file_data`` on every turn.
        self._inline_file_ids = {}

    def responses_chain_key(self) -> str:
        """Return a credential- and endpoint-scoped Responses chain key.

        The digest is safe to persist in conversation metadata and prevents a
        ``previous_response_id`` from being reused after the user switches
        model, endpoint, or API credential.

        Returns:
            A stable hexadecimal digest for the current Responses target.
        """
        canonical_model_id = (
            getattr(self, "_canonical_model_id", None) or self.model_id or ""
        )
        material = "\0".join(
            (
                self.provider_name,
                canonical_model_id,
                self._effective_base_url,
                self.api_key or "",
                "store=true" if settings.OPENAI_RESPONSES_STORE else "store=false",
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def export_responses_state(self) -> dict:
        """Return serializable Responses continuity state for persistence."""
        return {
            "version": 1,
            "chain_key": self.responses_chain_key(),
            "response_id": (
                self._last_response_id if settings.OPENAI_RESPONSES_STORE else None
            ),
            # Without these the coverage guard in ``_build_responses_input``
            # is inert after a cross-process resume, and the trim's carry
            # loop re-sends every earlier round's outputs unfiltered.
            "call_ids": sorted(self._last_response_call_ids or ()),
            "reasoning_items": self._last_reasoning_items,
            "reasoning_for_calls": self._reasoning_for_calls,
            "system_hash": self._chain_system_hash,
        }

    def import_responses_state(self, state: dict | None) -> bool:
        """Restore encrypted/stored Responses state when its target matches."""
        if not isinstance(state, dict):
            return False
        if state.get("chain_key") != self.responses_chain_key():
            return False
        self._imported_response_id = state.get("response_id")
        # Tolerant of rows persisted before ``call_ids`` existed: an empty
        # set keeps the guard disabled rather than rejecting the state.
        self._last_response_call_ids = set(state.get("call_ids") or ())
        self._last_reasoning_items = list(state.get("reasoning_items") or [])
        self._reasoning_for_calls = dict(state.get("reasoning_for_calls") or {})
        self._chain_system_hash = state.get("system_hash")
        self._pending_system_hash = None
        return True

    def start_responses_turn(self) -> None:
        """Reset continuity accumulated during the preceding user turn."""
        self._reasoning_for_calls = {}
        self._last_reasoning_items = []
        self._last_response_id = None
        self._last_response_call_ids = set()
        self._imported_response_id = None
        self._chain_system_hash = None
        self._pending_system_hash = None
        self._last_finish_reason = None

    def _resolve_file_part(self, item):
        """Resolve a ``file`` content part into a Files-API reference.

        Clients (the /v1 passthrough in particular) may send OpenAI-style
        file parts carrying an inline ``file_data`` data-URI. Azure's
        Responses API rejects inline data with ``unsupported_file`` even for
        valid PDFs, and string-content-only chat deployments 4xx on any file
        part — so upload the bytes once and swap in the ``file_id`` the
        deployments do accept. A part with neither ``file_id`` nor decodable
        ``file_data``, or whose upload fails (e.g. the endpoint has no Files
        API), degrades to a text note instead of a certain provider 4xx.
        """
        file_obj = item.get("file") or {}
        if file_obj.get("file_id"):
            # Normalize: a client that sends both ``file_id`` and
            # ``file_data`` would otherwise leak the inline payload to
            # ``_responses_content_parts``, which copies every truthy key
            # into ``input_file`` — and Azure Responses then rejects on
            # the ``file_data`` regardless of the ``file_id``.
            return {"type": "file", "file": {"file_id": file_obj["file_id"]}}
        filename = file_obj.get("filename") or "upload.pdf"
        file_data = file_obj.get("file_data")
        if file_data:
            payload = file_data
            if payload.startswith("data:"):
                _, _, payload = payload.partition(",")
            # MIME-wrapped encoders (``base64.encodebytes``, some
            # JSON pretty-printers) insert whitespace/newlines that
            # ``validate=True`` rejects — strip so recoverable data
            # doesn't get thrown into the text-note degrade path.
            payload = "".join(payload.split())
        else:
            payload = None
        if payload:
            # Hash the canonical payload, not the raw string, so data-URI,
            # bare-base64, and MIME-wrapped encodings of the same bytes
            # share one cache entry.
            content_hash = hashlib.sha256(payload.encode()).hexdigest()
            cached = self._inline_file_ids.get(content_hash)
            if cached:
                return {"type": "file", "file": {"file_id": cached}}
            cached = self._inline_file_id_cache_get(content_hash)
            if cached:
                self._inline_file_ids[content_hash] = cached
                return {"type": "file", "file": {"file_id": cached}}
            try:
                raw = base64.b64decode(payload, validate=True)
                file_id = self.client.files.create(
                    file=(filename, io.BytesIO(raw)),
                    purpose="assistants",
                ).id
                self._inline_file_ids[content_hash] = file_id
                self._inline_file_id_cache_set(content_hash, file_id)
                return {"type": "file", "file": {"file_id": file_id}}
            except Exception as e:
                logging.warning(
                    "Could not resolve inline file_data part '%s' to a "
                    "file_id (%s); degrading to a text note",
                    filename,
                    e,
                )
        elif file_data:
            # A data URI missing the comma (or one with an empty payload)
            # would otherwise decode to zero bytes and upload an empty
            # artifact; degrade deliberately.
            logging.warning(
                "File content part '%s' has an empty file_data payload; "
                "degrading to a text note",
                filename,
            )
        else:
            logging.warning(
                "File content part '%s' has neither file_id nor file_data; "
                "degrading to a text note",
                filename,
            )
        return {
            "type": "text",
            "text": f"[File '{filename}' could not be processed]",
        }

    def _inline_file_id_cache_key(self, content_hash: str) -> str:
        """Redis key for the inline-file-data → file_id cache.

        Scoped by ``(provider_name, base_url, api_key)``: a Files-API
        ``file_id`` is only valid for the endpoint + credential it was
        uploaded to, so a shared key across providers would return
        ids the current call can't use.
        """
        creds = "\0".join(
            (
                self.provider_name or "",
                self._effective_base_url or "",
                self.api_key or "",
            )
        )
        creds_hash = hashlib.sha256(creds.encode("utf-8")).hexdigest()[:16]
        return f"openai_inline_file:{creds_hash}:{content_hash}"

    def _inline_file_id_cache_get(self, content_hash: str):
        """Look up a previously-uploaded file_id for this content.

        Returns None on cache miss or on any Redis error — the caller
        then uploads normally. Never raises.
        """
        try:
            from application.cache import get_redis_instance

            r = get_redis_instance()
            if r is None:
                return None
            value = r.get(self._inline_file_id_cache_key(content_hash))
            if value is None:
                return None
            return value.decode() if isinstance(value, (bytes, bytearray)) else value
        except Exception as e:
            logging.debug("inline_file_id cache read failed: %s", e)
            return None

    def _inline_file_id_cache_set(self, content_hash: str, file_id: str) -> None:
        """Persist a fresh (content_hash → file_id) mapping.

        24 h TTL: well inside Azure's 30-day retention for
        ``purpose="assistants"``, long enough to cover multi-turn
        conversations that resend the same ``file_data`` every turn.
        Silent on failure.
        """
        try:
            from application.cache import get_redis_instance

            r = get_redis_instance()
            if r is None:
                return
            r.setex(
                self._inline_file_id_cache_key(content_hash),
                86400,
                file_id,
            )
        except Exception as e:
            logging.debug("inline_file_id cache write failed: %s", e)

    def _clean_messages_openai(self, messages):
        cleaned_messages = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            # Reasoning round-trips for providers that demand it
            # (DeepSeek thinking mode). Other OpenAI-compatible APIs
            # ignore the extra field.
            reasoning_content = message.get("reasoning_content")

            if role == "model":
                role = "assistant"

            # Standard format: assistant message with tool_calls (passthrough)
            tool_calls = message.get("tool_calls")
            if tool_calls and role == "assistant":
                cleaned_tcs = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    args = func.get("arguments", "{}")
                    if isinstance(args, dict):
                        args = json.dumps(self._remove_null_values(args))
                    elif isinstance(args, str):
                        try:
                            parsed = json.loads(args)
                            args = json.dumps(self._remove_null_values(parsed))
                        except (json.JSONDecodeError, TypeError):
                            pass
                    cleaned_tcs.append({
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {"name": func.get("name", ""), "arguments": args},
                    })
                cleaned_assistant: dict = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": cleaned_tcs,
                }
                if reasoning_content:
                    cleaned_assistant["reasoning_content"] = reasoning_content
                if self._uses_responses_api() and message.get(
                    "responses_reasoning_items"
                ):
                    cleaned_assistant["responses_reasoning_items"] = message[
                        "responses_reasoning_items"
                    ]
                cleaned_messages.append(cleaned_assistant)
                continue

            # Standard format: tool message with tool_call_id (passthrough)
            tool_call_id = message.get("tool_call_id")
            if role == "tool" and tool_call_id is not None:
                cleaned_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": content if isinstance(content, str) else json.dumps(content),
                })
                continue

            if role and content is not None:
                if isinstance(content, str):
                    msg_obj: dict = {"role": role, "content": content}
                    if reasoning_content and role == "assistant":
                        msg_obj["reasoning_content"] = reasoning_content
                    if (
                        self._uses_responses_api()
                        and message.get("responses_reasoning_items")
                        and role == "assistant"
                    ):
                        msg_obj["responses_reasoning_items"] = message[
                            "responses_reasoning_items"
                        ]
                    cleaned_messages.append(msg_obj)
                elif isinstance(content, list):
                    content_parts = []
                    for item in content:
                        # Legacy format support: function_call / function_response
                        if "function_call" in item:
                            args = item["function_call"]["args"]
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            cleaned_args = self._remove_null_values(args)
                            tool_call = {
                                "id": item["function_call"]["call_id"],
                                "type": "function",
                                "function": {
                                    "name": item["function_call"]["name"],
                                    "arguments": json.dumps(cleaned_args),
                                },
                            }
                            cleaned_messages.append({
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [tool_call],
                            })
                        elif "function_response" in item:
                            cleaned_messages.append({
                                "role": "tool",
                                "tool_call_id": item["function_response"]["call_id"],
                                "content": json.dumps(
                                    item["function_response"]["response"]["result"]
                                ),
                            })
                        elif isinstance(item, dict):
                            if "type" in item and item["type"] == "text" and "text" in item:
                                content_parts.append(item)
                            elif "type" in item and item["type"] == "file" and "file" in item:
                                content_parts.append(self._resolve_file_part(item))
                            elif "type" in item and item["type"] == "image_url" and "image_url" in item:
                                content_parts.append(item)
                            elif "text" in item and "type" not in item:
                                content_parts.append({"type": "text", "text": item["text"]})
                    if content_parts:
                        list_msg: dict = {"role": role, "content": content_parts}
                        if reasoning_content and role == "assistant":
                            list_msg["reasoning_content"] = reasoning_content
                        cleaned_messages.append(list_msg)
                else:
                    raise ValueError(f"Unexpected content type: {type(content)}")
        return cleaned_messages

    @staticmethod
    def _normalize_reasoning_value(value):
        """Normalize reasoning payloads from OpenAI-compatible stream chunks."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(
                OpenAILLM._normalize_reasoning_value(item) for item in value
            )
        if isinstance(value, dict):
            for key in ("text", "content", "value", "reasoning_content", "reasoning"):
                normalized = OpenAILLM._normalize_reasoning_value(value.get(key))
                if normalized:
                    return normalized
            return ""

        for attr in ("text", "content", "value"):
            if hasattr(value, attr):
                normalized = OpenAILLM._normalize_reasoning_value(getattr(value, attr))
                if normalized:
                    return normalized
        return ""

    @classmethod
    def _extract_reasoning_text(cls, delta):
        """Extract reasoning/thinking tokens from OpenAI-compatible delta chunks."""
        if delta is None:
            return ""

        for key in (
            "reasoning_content",
            "reasoning",
            "thinking",
            "thinking_content",
        ):
            value = getattr(delta, key, None)
            if value is None and isinstance(delta, dict):
                value = delta.get(key)
            normalized = cls._normalize_reasoning_value(value)
            if normalized:
                return normalized
        return ""

    def _note_tools_rejected(self, model: str, error: Exception) -> None:
        """Record that this endpoint refuses tool calling, warning once."""
        if not self._tools_rejected:
            logging.warning(
                "Endpoint rejected tool calling (model=%s, base_url=%s): %s. "
                "Retrying this request without tools and skipping tools for "
                "the rest of this session — set supports_tools: false in the "
                "model catalog for %s to avoid the discovery round trip.",
                model,
                self._effective_base_url,
                error,
                model,
            )
        self._tools_rejected = True

    @staticmethod
    def _params_without_tools(params: dict) -> dict:
        """Copy of ``params`` with every tool-calling key removed."""
        return {
            key: value for key, value in params.items()
            if key not in _TOOL_REQUEST_KEYS
        }

    def _create_with_tool_fallback(
        self, create: Callable[..., Any], params: dict, model: str
    ) -> Any:
        """Send a request, retrying once without tools on a tools-unsupported 400.

        Args:
            create: The provider ``create`` callable for this endpoint.
            params: Request kwargs, possibly including ``tools``.
            model: Model id, used for the warning.

        Returns:
            The provider response — from the first call, or from the
            tool-less retry when the endpoint rejected tool calling.

        Raises:
            openai.BadRequestError: Any 400 unrelated to tool calling, any 400
                on a request that carried no tools, and any 400 raised by the
                retry itself.
        """
        try:
            return create(**params)
        except BadRequestError as error:
            if not params.get("tools"):
                raise
            if getattr(error, "param", None) in _TOOL_CHOICE_KEYS:
                # A rejected tool_choice is a bad argument, not a missing
                # capability -- the v1 translator forwards a client-supplied
                # value verbatim. Drop just that knob and keep the tools.
                logging.warning(
                    "Endpoint rejected %r (model=%s): %s. Retrying with tools intact.",
                    getattr(error, "param", None),
                    model,
                    error,
                )
                retry = {
                    key: value for key, value in params.items()
                    if key not in _TOOL_CHOICE_KEYS
                }
                return create(**retry)
            if not _is_tools_unsupported_error(error):
                raise
            response = create(**self._params_without_tools(params))
            # Latch only once the tool-less retry has actually worked: a retry
            # that also 400s proves nothing about tool support, and must not
            # disable tools for the rest of this answer.
            self._note_tools_rejected(model, error)
            return response

    def _raw_gen(
        self,
        baseself,
        model,
        messages,
        stream=False,
        tools=None,
        engine=settings.AZURE_DEPLOYMENT_NAME,
        response_format=None,
        **kwargs,
    ):
        messages = self._clean_messages_openai(messages)
        logging.debug(
            "Prepared OpenAI request with %d messages and %d tools",
            len(messages or []),
            len(tools or []),
        )

        # Convert max_tokens to max_completion_tokens for newer models
        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")

        # Defense-in-depth: drop tools / response_format if the
        # registry's capability flags deny them.
        if tools and not self._supports_tools():
            tools = None
        if response_format and not self._supports_structured_output():
            response_format = None
        if not tools:
            kwargs.pop("tool_choice", None)
            kwargs.pop("parallel_tool_calls", None)

        previous_response_id = kwargs.pop("previous_response_id", None)
        if self._uses_responses_api():
            return self._responses_gen(
                model,
                messages,
                tools=tools,
                response_format=response_format,
                previous_response_id=previous_response_id,
                **kwargs,
            )

        self._apply_reasoning_effort(kwargs)

        request_params = {
            "model": model,
            "messages": messages,
            "stream": stream,
            **kwargs,
        }

        if tools:
            request_params["tools"] = tools
        if response_format:
            request_params["response_format"] = response_format
        self._last_usage = None
        self._stream_reached_finish = False
        response = self._create_with_tool_fallback(
            self.client.chat.completions.create, request_params, model
        )
        logging.debug("OpenAI request completed")
        self._record_chat_usage(getattr(response, "usage", None))
        if tools:
            return response.choices[0]
        else:
            return response.choices[0].message.content

    def _raw_gen_stream(
        self,
        baseself,
        model,
        messages,
        stream=True,
        tools=None,
        engine=settings.AZURE_DEPLOYMENT_NAME,
        response_format=None,
        **kwargs,
    ):
        messages = self._clean_messages_openai(messages)
        logging.debug(
            "Prepared OpenAI streaming request with %d messages and %d tools",
            len(messages or []),
            len(tools or []),
        )

        # Convert max_tokens to max_completion_tokens for newer models
        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")

        # See _raw_gen for rationale — drop tools/response_format when the
        # registry-provided capabilities say the model doesn't support them.
        if tools and not self._supports_tools():
            tools = None
        if response_format and not self._supports_structured_output():
            response_format = None
        if not tools:
            kwargs.pop("tool_choice", None)
            kwargs.pop("parallel_tool_calls", None)

        previous_response_id = kwargs.pop("previous_response_id", None)
        if self._uses_responses_api():
            yield from self._responses_gen_stream(
                model,
                messages,
                tools=tools,
                response_format=response_format,
                previous_response_id=previous_response_id,
                **kwargs,
            )
            return

        self._apply_reasoning_effort(kwargs)

        request_params = {
            "model": model,
            "messages": messages,
            "stream": stream,
            **kwargs,
        }

        if tools:
            request_params["tools"] = tools
        if response_format:
            request_params["response_format"] = response_format
        # Ask for the terminal usage-only chunk (choices=[]) so token rows
        # get provider-exact counts; servers that ignore stream_options
        # leave the tiktoken-estimate fallback in place.
        stream_options = dict(request_params.get("stream_options") or {})
        stream_options.setdefault("include_usage", True)
        request_params["stream_options"] = stream_options
        self._last_usage = None
        self._stream_reached_finish = False
        self._last_finish_reason = None
        # The request is issued before the loop, so a tools-unsupported 400
        # lands here with nothing yielded yet — the retry inside
        # ``_create_with_tool_fallback`` can never duplicate delivered output.
        response = self._create_with_tool_fallback(
            self.client.chat.completions.create, request_params, model
        )

        try:
            for line in response:
                logging.debug(f"OpenAI stream line: {line}")
                self._record_chat_usage(getattr(line, "usage", None))
                if not getattr(line, "choices", None):
                    continue

                choice = line.choices[0]
                delta = getattr(choice, "delta", None)
                reasoning_text = self._extract_reasoning_text(delta)
                if reasoning_text:
                    yield {"type": "thought", "thought": reasoning_text}

                content = getattr(delta, "content", None)
                if isinstance(content, str) and content:
                    yield content
                    continue

                has_tool_calls = bool(getattr(delta, "tool_calls", None))
                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason:
                    # The answer is complete; only trailing frames (usage
                    # chunk, [DONE]) remain. ``_stream_with_fallback`` reads
                    # this to refuse restreaming a delivered answer when a
                    # trailing frame fails.
                    self._stream_reached_finish = True
                    # Capture the reason itself (not just the bool) so the save
                    # path can classify an empty answer: a ``stop`` with no
                    # content is a genuine dead-end, ``tool_calls`` is a tool
                    # request. Previously the chat path discarded this.
                    self._last_finish_reason = finish_reason

                # Yield non-content chunks only when needed for tool-call handling.
                if has_tool_calls or finish_reason == "tool_calls":
                    yield choice
        finally:
            if hasattr(response, "close"):
                response.close()

    # ---- Responses API (/v1/responses) ----

    def _uses_responses_api(self):
        """True when the model's registry capability opts it into the
        ``/v1/responses`` endpoint."""
        return (
            self.capabilities is not None
            and getattr(self.capabilities, "api_flavor", "chat_completions")
            == "responses"
        )

    @staticmethod
    def _responses_content_parts(role, content):
        """Translate a cleaned chat ``content`` value into Responses content
        parts. The Responses API enforces the content-part type by message
        role: assistant turns require ``output_text`` (``input_text`` is
        rejected with a 400), while user/system turns require ``input_text``.
        Images/files use ``input_image``/``input_file``.
        """
        text_type = "output_text" if role == "assistant" else "input_text"
        parts = []
        if content is None:
            return parts
        if isinstance(content, str):
            if content:
                parts.append({"type": text_type, "text": content})
            return parts
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                itype = item.get("type")
                if itype == "text":
                    parts.append({"type": text_type, "text": item.get("text", "")})
                elif itype == "image_url":
                    url = (item.get("image_url") or {}).get("url")
                    if url:
                        parts.append({
                            "type": "input_image",
                            "image_url": url,
                            "detail": "auto",
                        })
                elif itype == "file":
                    file_obj = item.get("file") or {}
                    file_part = {"type": "input_file"}
                    for key in ("file_id", "filename", "file_data"):
                        if file_obj.get(key):
                            file_part[key] = file_obj[key]
                    parts.append(file_part)
        return parts

    def _to_responses_input(self, messages, chained=False):
        """Translate cleaned Chat-Completions messages into a Responses
        ``input`` item list.

        Reasoning items captured during the in-turn tool loop are re-injected
        ahead of the function calls they belong to (deduped by id) so the
        model keeps its chain-of-thought across the round-trip.

        Pairing invariant: the Responses API 400s on a ``function_call``
        without a matching ``function_call_output`` ("No tool output found
        for function call …") and on an output without its call. History
        rebuilds (compression, pause/resume) can produce either orphan, so
        both directions are dropped here rather than sent to certain
        rejection — along with any reasoning items that would then precede
        a dropped call with no following item. A call is only "paired" when
        its output appears LATER in the list (an output *before* its call
        is malformed history; both sides are dropped).

        ``chained=True`` (store-mode ``previous_response_id`` requests)
        disables the guard entirely: ``_trim_for_previous_response``
        deliberately sends bare ``function_call_output`` items whose calls
        live server-side in the previous response — dropping those breaks
        every tool round.
        """
        input_items = []
        emitted_reasoning = set()
        # First position (message index) at which each call_id's output
        # appears — used to require call-before-output ordering.
        output_positions: dict = {}
        for position, m in enumerate(messages):
            if m.get("role") == "tool" and m.get("tool_call_id") is not None:
                output_positions.setdefault(m["tool_call_id"], position)
        emitted_call_ids = set()
        for position, message in enumerate(messages):
            role = message.get("role")
            message_reasoning = message.get("responses_reasoning_items") or []
            tool_calls = message.get("tool_calls")
            if tool_calls and role == "assistant":
                kept_calls = [
                    tc
                    for tc in tool_calls
                    if chained
                    or output_positions.get(tc.get("id", ""), -1) > position
                ]
                if len(kept_calls) < len(tool_calls):
                    kept_ids = {id(tc) for tc in kept_calls}
                    dropped = [
                        tc.get("id", "")
                        for tc in tool_calls
                        if id(tc) not in kept_ids
                    ]
                    logging.warning(
                        "Dropping %d function_call item(s) without a matching "
                        "later function_call_output (call_ids=%s) from "
                        "Responses input",
                        len(dropped),
                        dropped,
                    )
                if not kept_calls:
                    # Nothing left to emit for this message; its reasoning
                    # items must not be emitted either (a trailing reasoning
                    # item with no following item is itself rejected).
                    continue
                for item in message_reasoning:
                    item_id = item.get("id") if isinstance(item, dict) else None
                    if item_id and item_id in emitted_reasoning:
                        continue
                    if item_id:
                        emitted_reasoning.add(item_id)
                    input_items.append(item)
                for tc in kept_calls:
                    call_id = tc.get("id", "")
                    for item in self._reasoning_for_calls.get(call_id, []):
                        item_id = item.get("id")
                        if item_id and item_id in emitted_reasoning:
                            continue
                        if item_id:
                            emitted_reasoning.add(item_id)
                        input_items.append(item)
                    func = tc.get("function", {})
                    input_items.append({
                        "type": "function_call",
                        "call_id": call_id,
                        "name": func.get("name", ""),
                        "arguments": func.get("arguments", "") or "{}",
                    })
                    emitted_call_ids.add(call_id)
                continue
            for item in message_reasoning:
                item_id = item.get("id") if isinstance(item, dict) else None
                if item_id and item_id in emitted_reasoning:
                    continue
                if item_id:
                    emitted_reasoning.add(item_id)
                input_items.append(item)
            tool_call_id = message.get("tool_call_id")
            if role == "tool" and tool_call_id is not None:
                if not chained and tool_call_id not in emitted_call_ids:
                    logging.warning(
                        "Dropping orphaned function_call_output (call_id=%s) "
                        "with no preceding function_call from Responses input",
                        tool_call_id,
                    )
                    continue
                tool_content = message.get("content")
                input_items.append({
                    "type": "function_call_output",
                    "call_id": tool_call_id,
                    "output": (
                        tool_content
                        if isinstance(tool_content, str)
                        else json.dumps(tool_content)
                    ),
                })
                continue
            parts = self._responses_content_parts(role, message.get("content"))
            if parts:
                input_items.append({"role": role, "content": parts})
        return input_items

    @staticmethod
    def _trim_for_previous_response(messages):
        """When chaining via ``previous_response_id`` the server already holds
        the earlier turns, so only system context plus the tool results
        answering the chained response's calls need to be sent again.

        The cut is the last assistant message. Any ``tool`` message inside the
        trailing assistant/tool run *before* that cut is carried over too: a
        batch written as one assistant message per call — instead of one
        message carrying the whole batch — would otherwise lose every result
        but the last, and the provider then rejects the request with "No tool
        output found for function call <first unpaired call>". The assistant
        messages in that run are not carried: the server already holds those
        calls, and chained mode accepts bare ``function_call_output`` items.
        """
        last_assistant = -1
        for i, message in enumerate(messages):
            if message.get("role") == "assistant":
                last_assistant = i
        if last_assistant < 0:
            return messages
        carried = []
        i = last_assistant - 1
        while i >= 0:
            role = messages[i].get("role")
            if role == "tool":
                carried.append(messages[i])
            elif not (role == "assistant" and messages[i].get("tool_calls")):
                break
            i -= 1
        carried.reverse()
        head = [
            m
            for m in messages[: last_assistant + 1]
            if m.get("role") == "system"
        ]
        return head + carried + messages[last_assistant + 1:]

    @staticmethod
    def _system_fingerprint(messages):
        """Hash of the system messages' content; ``None`` when there are none."""
        parts = [
            m.get("content")
            for m in messages
            if isinstance(m, dict) and m.get("role") == "system"
        ]
        if not parts:
            return None
        encoded = json.dumps(parts, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _build_responses_input(self, messages, previous_response_id):
        """Build the Responses ``input`` list, honouring store-mode chaining.

        Returns ``(input_items, previous_response_id)``. The id comes back
        ``None`` when the chained payload would not carry an output for every
        call the chained response holds — rather than send a request the
        provider is certain to reject, the full history is sent unchained.

        A chained request answers exactly the calls of the response it chains
        to, so outputs are checked in BOTH directions against
        ``_last_response_call_ids``: missing ones abandon chaining, extra ones
        are dropped. The extras matter because the trim's carry loop cannot
        tell a split batch (whose stray results must be rescued) from a
        multi-round grouped history (whose earlier rounds the server already
        has) — both end in the same assistant/tool run. Without the filter,
        round N re-sends every prior round's outputs back to the last user
        turn and the payload grows with the tool loop.
        """
        chained = bool(previous_response_id and settings.OPENAI_RESPONSES_STORE)
        if not chained:
            # The full head goes out; it becomes the chain's head only once
            # the provider records the response.
            self._pending_system_hash = self._system_fingerprint(messages)
            return self._to_responses_input(messages, chained=False), None

        trimmed = self._trim_for_previous_response(messages)
        head_hash = self._system_fingerprint(trimmed)
        if head_hash and head_hash == self._chain_system_hash:
            # The server appends a re-sent system message after the stored
            # transcript instead of replacing it (measured on Azure: 11,239
            # vs 5,635 input tokens for the same chained turn), so an
            # unchanged head stays home. After a compression the head also
            # carries the summary, which made every tool round re-append it.
            trimmed = [m for m in trimmed if m.get("role") != "system"]
            self._pending_system_hash = self._chain_system_hash
        else:
            # A changed (or first) head is sent; only a recorded response
            # makes it the chain's head, so a failed request and its retry
            # still carry it.
            self._pending_system_hash = head_hash or self._chain_system_hash
        input_items = self._to_responses_input(trimmed, chained=True)
        expected = set(self._last_response_call_ids or ())
        if expected:
            kept, dropped = [], []
            for item in input_items:
                if (
                    item.get("type") == "function_call_output"
                    and item.get("call_id") not in expected
                ):
                    dropped.append(item.get("call_id"))
                else:
                    kept.append(item)
            if dropped:
                logging.debug(
                    "Dropping %d already-answered tool output(s) from the "
                    "chained Responses input (call_ids=%s)",
                    len(dropped),
                    sorted(dropped),
                )
                input_items = kept
            sent = {
                item.get("call_id")
                for item in input_items
                if item.get("type") == "function_call_output"
            }
            missing = expected - sent
            if missing:
                logging.warning(
                    "Chained Responses request would omit tool output(s) for "
                    "%s; sending the full unchained input instead of a "
                    "request the provider would reject",
                    sorted(missing),
                )
                self._pending_system_hash = self._system_fingerprint(messages)
                return self._to_responses_input(messages, chained=False), None
        return input_items, previous_response_id

    @staticmethod
    def _to_responses_tools(tools):
        """Flatten Chat-Completions tool defs into Responses tool defs.

        ``strict`` is left False so schemas that were valid on Chat
        Completions are not newly rejected by the stricter Responses default.
        """
        converted = []
        for tool in tools or []:
            if tool.get("type") == "function" and isinstance(
                tool.get("function"), dict
            ):
                fn = tool["function"]
                converted.append({
                    "type": "function",
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                    "strict": False,
                })
            else:
                converted.append(tool)
        return converted

    @staticmethod
    def _responses_text_format(response_format):
        """Map a Chat-Completions ``response_format`` to a Responses
        ``text.format`` object."""
        if not isinstance(response_format, dict):
            return None
        if response_format.get("type") == "json_schema":
            js = response_format.get("json_schema", {})
            fmt = {"type": "json_schema", "name": js.get("name", "response")}
            if "schema" in js:
                fmt["schema"] = js["schema"]
            if "strict" in js:
                fmt["strict"] = js["strict"]
            return fmt
        if response_format.get("type") == "json_object":
            return {"type": "json_object"}
        return None

    def _build_responses_params(
        self,
        model,
        input_items,
        tools,
        response_format,
        previous_response_id,
        stream,
        kwargs,
    ):
        """Assemble the kwargs for ``client.responses.create``. Only known,
        Responses-compatible keys are forwarded — unknown chat-only kwargs
        are dropped so the API does not reject the request."""
        params = {"model": model, "input": input_items, "stream": stream}

        max_out = kwargs.pop("max_completion_tokens", None)
        if max_out is None:
            max_out = kwargs.pop("max_tokens", None)
        if max_out is not None:
            params["max_output_tokens"] = max_out

        effort = (
            getattr(self.capabilities, "reasoning_effort", None)
            if self.capabilities is not None
            else None
        )
        if effort:
            summary = settings.OPENAI_REASONING_SUMMARY or "auto"
            params["reasoning"] = {"effort": effort, "summary": summary}

        if response_format:
            fmt = self._responses_text_format(response_format)
            if fmt:
                params["text"] = {"format": fmt}

        if tools:
            params["tools"] = self._to_responses_tools(tools)
            if kwargs.get("tool_choice") is not None:
                choice = kwargs["tool_choice"]
                if isinstance(choice, dict) and choice.get("type") == "function":
                    choice = {
                        "type": "function",
                        "name": (choice.get("function") or {}).get("name", ""),
                    }
                params["tool_choice"] = choice
            if kwargs.get("parallel_tool_calls") is not None:
                params["parallel_tool_calls"] = bool(kwargs["parallel_tool_calls"])

        store = bool(settings.OPENAI_RESPONSES_STORE)
        params["store"] = store
        if store and previous_response_id:
            params["previous_response_id"] = previous_response_id
        # Always request encrypted reasoning content so reasoning items can be
        # replayed by value across the in-turn tool loop — this keeps
        # carryover working whether or not the response is also retained
        # server-side (store=true).
        params["include"] = ["reasoning.encrypted_content"]
        # Backstop against a chain that outgrows the model's native window:
        # the provider drops the oldest input items instead of failing.
        if getattr(settings, "OPENAI_RESPONSES_TRUNCATION_AUTO", False):
            params["truncation"] = "auto"
        # Prompt-cache hints. The key pins a conversation to one cache shard;
        # retention asks for the extended tier where the deployment offers it.
        cache_key = getattr(self, "_prompt_cache_key", None)
        if cache_key and getattr(settings, "OPENAI_PROMPT_CACHE_KEY", False):
            params["prompt_cache_key"] = str(cache_key)
        retention = getattr(settings, "OPENAI_PROMPT_CACHE_RETENTION", None)
        if retention:
            params["prompt_cache_retention"] = retention
        return params

    @staticmethod
    def _reasoning_item_to_dict(item):
        """Serialize a Responses ``reasoning`` output item into the input
        shape needed to feed it back on the next call."""
        result = {"type": "reasoning", "id": getattr(item, "id", None)}
        encrypted = getattr(item, "encrypted_content", None)
        if encrypted is not None:
            result["encrypted_content"] = encrypted
        summary = getattr(item, "summary", None) or []
        serialized = []
        for part in summary:
            if isinstance(part, dict):
                serialized.append(part)
            else:
                serialized.append({
                    "type": getattr(part, "type", "summary_text"),
                    "text": getattr(part, "text", ""),
                })
        result["summary"] = serialized
        return result

    def _record_chat_usage(self, usage) -> None:
        """Capture provider-reported Chat Completions usage for this call.

        Counterpart to ``_record_responses_metadata`` for the chat path;
        provider totals are stored as-is (see ``_prefer_provider_usage``).
        """
        if usage is None:
            return
        try:
            prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion = int(getattr(usage, "completion_tokens", 0) or 0)
            total = int(getattr(usage, "total_tokens", 0) or 0)
        except (TypeError, ValueError):
            return
        if not prompt and not completion:
            # A zeroed usage object (some proxies) must not clobber estimates.
            return
        result = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total or prompt + completion,
        }
        input_details = getattr(usage, "prompt_tokens_details", None)
        output_details = getattr(usage, "completion_tokens_details", None)
        cached = optional_int(getattr(input_details, "cached_tokens", None))
        written = optional_int(getattr(input_details, "cache_write_tokens", None))
        reasoning = optional_int(
            getattr(output_details, "reasoning_tokens", None)
        )
        details = self._prompt_cache_details(cached, written)
        if details:
            result["prompt_tokens_details"] = details
        if reasoning:
            result["completion_tokens_details"] = {"reasoning_tokens": reasoning}
        self._last_usage = result
        self._last_usage_claimed = False

    @staticmethod
    def _prompt_cache_details(cached: int | None, written: int | None) -> dict:
        """Build the ``prompt_tokens_details`` breakdown from the two cache bins.

        A bin is included whenever the provider reported it, zero included:
        downstream, an absent bin persists as NULL ("we don't know") and a
        reported zero as 0 ("no cache hits"), and OpenAI reports
        ``cached_tokens: 0`` on every uncached request. Collapsing the two
        would file every ordinary request as unknown. ``cache_write_tokens``
        is reported by newer OpenAI-family deployments that charge for cache
        writes.
        """
        details = {}
        if cached is not None:
            details["cached_tokens"] = cached
        if written is not None:
            details["cache_write_tokens"] = written
        return details

    @staticmethod
    def _function_call_ids(response):
        """call_ids of every ``function_call`` item in a Responses output.

        Feeds the chained-request coverage guard in
        ``_build_responses_input``: these are the calls the server will expect
        a ``function_call_output`` for on the next chained turn.
        """
        output = getattr(response, "output", None)
        if not isinstance(output, list):
            return set()
        call_ids = set()
        for item in output:
            if isinstance(item, dict):
                itype, cid = item.get("type"), item.get("call_id")
            else:
                itype = getattr(item, "type", None)
                cid = getattr(item, "call_id", None)
            if itype == "function_call" and isinstance(cid, str) and cid:
                call_ids.add(cid)
        return call_ids

    def _record_responses_metadata(self, response):
        rid = getattr(response, "id", None)
        if rid:
            self._last_response_id = rid
        # The provider recorded this request, so the head it carried (or
        # kept) is now the chain's head — including "no head at all", when
        # an unchained request went out without a system message: a stale
        # hash would let a later chained request omit a head this
        # transcript never received.
        self._chain_system_hash = self._pending_system_hash
        self._pending_system_hash = None
        self._last_response_call_ids = self._function_call_ids(response)
        usage = getattr(response, "usage", None)
        if usage is not None:
            prompt = int(getattr(usage, "input_tokens", 0) or 0)
            completion = int(getattr(usage, "output_tokens", 0) or 0)
            input_details = getattr(usage, "input_tokens_details", None)
            output_details = getattr(usage, "output_tokens_details", None)
            result = {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": int(getattr(usage, "total_tokens", 0) or prompt + completion),
            }
            cached = optional_int(getattr(input_details, "cached_tokens", None))
            written = optional_int(
                getattr(input_details, "cache_write_tokens", None)
            )
            reasoning = optional_int(
                getattr(output_details, "reasoning_tokens", None)
            )
            details = self._prompt_cache_details(cached, written)
            if details:
                result["prompt_tokens_details"] = details
            if reasoning:
                result["completion_tokens_details"] = {"reasoning_tokens": reasoning}
            self._last_usage = result
            self._last_usage_claimed = False

    @staticmethod
    def _responses_status_error(response) -> str | None:
        """Return a terminal Responses error message, if one is present.

        Args:
            response: An OpenAI Response object from a non-streaming call or
                terminal streaming event.

        Returns:
            A human-readable error string for failed/incomplete responses, or
            ``None`` for successful and legacy status-less test objects.
        """
        if response is None:
            return None
        status = getattr(response, "status", None)
        error = getattr(response, "error", None)
        if status == "failed" or error is not None:
            message = getattr(error, "message", None) or str(error or "unknown error")
            return f"Responses API failed: {message}"
        details = getattr(response, "incomplete_details", None)
        if status == "incomplete" or details is not None:
            reason = getattr(details, "reason", None) or "unknown reason"
            return f"Responses API incomplete: {reason}"
        return None

    def _remember_reasoning(self, tool_calls, reasoning_items):
        """Key captured reasoning items by each function-call id for replay
        on the next in-turn request."""
        if not reasoning_items:
            return
        for tc in tool_calls:
            self._reasoning_for_calls[tc.id] = reasoning_items

    def _parse_responses_output(self, response):
        """Walk a non-streaming Responses ``output`` array into
        ``(content, tool_calls, reasoning_items)``."""
        content_parts = []
        tool_calls = []
        reasoning_items = []
        for item in getattr(response, "output", None) or []:
            itype = getattr(item, "type", None)
            if itype == "reasoning":
                reasoning_items.append(self._reasoning_item_to_dict(item))
            elif itype == "message":
                for part in getattr(item, "content", None) or []:
                    if getattr(part, "type", None) == "output_text":
                        content_parts.append(getattr(part, "text", "") or "")
                    elif getattr(part, "type", None) == "refusal":
                        content_parts.append(getattr(part, "refusal", "") or "")
            elif itype == "function_call":
                tool_calls.append(_RespToolCall(
                    id=getattr(item, "call_id", "") or getattr(item, "id", ""),
                    index=len(tool_calls),
                    name=getattr(item, "name", "") or "",
                    arguments=getattr(item, "arguments", "") or "",
                ))
        return "".join(content_parts), tool_calls, reasoning_items

    def _responses_gen(
        self,
        model,
        messages,
        tools=None,
        response_format=None,
        previous_response_id=None,
        **kwargs,
    ):
        previous_response_id = (
            self._last_response_id or previous_response_id or self._imported_response_id
        )
        # Built before the per-turn state is cleared: the coverage guard reads
        # the call_ids the chained response emitted.
        input_items, previous_response_id = self._build_responses_input(
            messages, previous_response_id
        )
        self._last_response_id = None
        self._last_response_call_ids = set()
        self._last_usage = None
        self._last_finish_reason = None
        params = self._build_responses_params(
            model,
            input_items,
            tools,
            response_format,
            previous_response_id,
            stream=False,
            kwargs=kwargs,
        )
        response = self._create_with_tool_fallback(
            self.client.responses.create, params, model
        )
        if response is None:
            raise RuntimeError("Responses API returned no response object")
        logging.debug(
            "OpenAI Responses request completed id=%s",
            getattr(response, "id", None),
        )
        content, tool_calls, reasoning_items = self._parse_responses_output(
            response
        )
        # Chain state (response id, head hash, reasoning items) is recorded
        # only for a response the provider actually completed — a failed one
        # must not become the id the next call chains onto, nor commit a head
        # the stored transcript never received.
        details = getattr(response, "incomplete_details", None)
        incomplete_reason = getattr(details, "reason", None)
        if getattr(response, "status", None) == "incomplete":
            if incomplete_reason != "max_output_tokens":
                raise RuntimeError(
                    self._responses_status_error(response)
                    or "Responses API incomplete: unknown reason"
                )
            # Cut off by the output cap: the input was accepted and stored.
            self._record_responses_metadata(response)
            self._last_reasoning_items = reasoning_items
            self._last_finish_reason = "length"
            if tools:
                return _RespChoice(
                    finish_reason="length",
                    message=_RespMessage(content=content or None, tool_calls=None),
                )
            return content or ""
        status_error = self._responses_status_error(response)
        if status_error:
            raise RuntimeError(status_error)
        self._record_responses_metadata(response)
        self._last_reasoning_items = reasoning_items
        if tools:
            self._remember_reasoning(tool_calls, reasoning_items)
            message = _RespMessage(
                content=content or None, tool_calls=tool_calls or None
            )
            return _RespChoice(
                finish_reason="tool_calls" if tool_calls else "stop",
                message=message,
            )
        self._last_finish_reason = "stop"
        return content or ""

    def _responses_gen_stream(
        self,
        model,
        messages,
        tools=None,
        response_format=None,
        previous_response_id=None,
        **kwargs,
    ):
        previous_response_id = (
            self._last_response_id or previous_response_id or self._imported_response_id
        )
        # Built before the per-turn state is cleared: the coverage guard reads
        # the call_ids the chained response emitted.
        input_items, previous_response_id = self._build_responses_input(
            messages, previous_response_id
        )
        self._last_response_id = None
        self._last_response_call_ids = set()
        self._last_usage = None
        self._last_finish_reason = None
        self._stream_reached_finish = False
        params = self._build_responses_params(
            model,
            input_items,
            tools,
            response_format,
            previous_response_id,
            stream=True,
            kwargs=kwargs,
        )
        # Issued before the event loop below, so the tool-less retry cannot
        # duplicate output already yielded.
        response = self._create_with_tool_fallback(
            self.client.responses.create, params, model
        )

        func_calls = {}
        reasoning_items = []
        refusal_delta_seen = False
        try:
            for event in response:
                etype = getattr(event, "type", "")
                if etype == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield delta
                elif etype == "response.refusal.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        refusal_delta_seen = True
                        yield delta
                elif etype == "response.refusal.done" and not refusal_delta_seen:
                    refusal = getattr(event, "refusal", "")
                    if refusal:
                        yield refusal
                elif etype == "response.reasoning_summary_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield {"type": "thought", "thought": delta}
                elif etype == "response.output_item.added":
                    item = getattr(event, "item", None)
                    if getattr(item, "type", None) == "function_call":
                        index = getattr(event, "output_index", len(func_calls))
                        func_calls[index] = {
                            "call_id": (
                                getattr(item, "call_id", "")
                                or getattr(item, "id", "")
                            ),
                            "name": getattr(item, "name", "") or "",
                            "arguments": "",
                        }
                elif etype == "response.function_call_arguments.delta":
                    index = getattr(event, "output_index", None)
                    if index in func_calls:
                        func_calls[index]["arguments"] += (
                            getattr(event, "delta", "") or ""
                        )
                elif etype == "response.function_call_arguments.done":
                    index = getattr(event, "output_index", None)
                    if index in func_calls:
                        done_args = getattr(event, "arguments", None)
                        if done_args is not None:
                            func_calls[index]["arguments"] = done_args
                elif etype == "response.output_item.done":
                    item = getattr(event, "item", None)
                    if getattr(item, "type", None) == "reasoning":
                        reasoning_items.append(
                            self._reasoning_item_to_dict(item)
                        )
                elif etype == "response.completed":
                    completed_response = getattr(event, "response", None)
                    if completed_response is None:
                        raise RuntimeError(
                            "Responses API returned no response object"
                        )
                    status_error = self._responses_status_error(completed_response)
                    if status_error:
                        raise RuntimeError(status_error)
                    self._stream_reached_finish = True
                    self._record_responses_metadata(completed_response)
                    self._last_reasoning_items = reasoning_items
                    self._last_finish_reason = "tool_calls" if func_calls else "stop"
                    if func_calls:
                        tool_calls = []
                        for position, index in enumerate(sorted(func_calls)):
                            entry = func_calls[index]
                            tool_calls.append(_RespToolCall(
                                id=entry["call_id"],
                                index=position,
                                name=entry["name"],
                                arguments=entry["arguments"],
                            ))
                        self._remember_reasoning(tool_calls, reasoning_items)
                        yield _RespChoice(
                            finish_reason="tool_calls",
                            delta=_RespDelta(tool_calls=tool_calls),
                        )
                elif etype == "response.incomplete":
                    incomplete_response = getattr(event, "response", None)
                    details = getattr(incomplete_response, "incomplete_details", None)
                    reason = getattr(details, "reason", None)
                    if reason == "max_output_tokens":
                        self._record_responses_metadata(incomplete_response)
                        self._last_reasoning_items = reasoning_items
                        self._last_finish_reason = "length"
                        yield _RespChoice(
                            finish_reason="length",
                            delta=_RespDelta(tool_calls=None),
                        )
                        return
                    status_error = self._responses_status_error(incomplete_response)
                    raise RuntimeError(
                        status_error or "Responses API incomplete: unknown reason"
                    )
                elif etype in ("response.failed", "error"):
                    resp = getattr(event, "response", None)
                    err = self._responses_status_error(resp)
                    if err is None:
                        err = (
                            getattr(event, "message", None)
                            or "Responses API stream error"
                        )
                    raise RuntimeError(err)
        finally:
            if hasattr(response, "close"):
                response.close()

    def _supports_tools(self):
        # A 400 already told us this endpoint can't serve tool calling
        # (vLLM without --enable-auto-tool-choice, and friends). Answer
        # False from then on so later turns skip tools outright instead of
        # paying for another rejected round trip.
        if self._tools_rejected:
            return False
        # When the LLM was constructed via LLMCreator with a registered
        # AvailableModel, ``self.capabilities`` is the per-model record.
        # BYOM users can disable tool support; respect that. Otherwise
        # OpenAI's API supports tools by default.
        if self.capabilities is not None:
            return bool(self.capabilities.supports_tools)
        return True

    def _supports_structured_output(self):
        if self.capabilities is not None:
            return bool(self.capabilities.supports_structured_output)
        return True

    def _apply_reasoning_effort(self, kwargs):
        """Inject the model's configured reasoning_effort into ``kwargs``.

        No-op when the caller already set one, when no registry capabilities
        are attached, or when the model has no configured effort. Read from
        per-model capabilities (not the caller) so a cross-provider fallback
        applies its own model's effort rather than inheriting the primary's.
        """
        if "reasoning_effort" in kwargs:
            return
        if self.capabilities is None:
            return
        effort = getattr(self.capabilities, "reasoning_effort", None)
        if effort:
            kwargs["reasoning_effort"] = effort

    def prepare_structured_output_format(self, json_schema, strict=True):
        # Recorded so a cross-provider fallback can re-prepare the raw schema.
        self._structured_output_source = (json_schema, strict) if json_schema else None
        if not json_schema:
            return None
        try:

            def add_additional_properties_false(schema_obj):
                if isinstance(schema_obj, dict):
                    schema_copy = schema_obj.copy()

                    if schema_copy.get("type") == "object":
                        schema_copy["additionalProperties"] = False
                        # Ensure 'required' includes all properties for OpenAI strict mode

                        if "properties" in schema_copy:
                            schema_copy["required"] = list(
                                schema_copy["properties"].keys()
                            )
                    for key, value in schema_copy.items():
                        if key == "properties" and isinstance(value, dict):
                            schema_copy[key] = {
                                prop_name: add_additional_properties_false(prop_schema)
                                for prop_name, prop_schema in value.items()
                            }
                        elif key == "items" and isinstance(value, dict):
                            schema_copy[key] = add_additional_properties_false(value)
                        elif key in ["anyOf", "oneOf", "allOf"] and isinstance(
                            value, list
                        ):
                            schema_copy[key] = [
                                add_additional_properties_false(sub_schema)
                                for sub_schema in value
                            ]
                    return schema_copy
                return schema_obj

            # Strict mode requires additionalProperties:false + all-required on every
            # object (OpenAI Structured Outputs). When strict is false (OpenAI's
            # lenient json_schema), pass the schema through unchanged.
            processed_schema = (
                add_additional_properties_false(json_schema) if strict else json_schema
            )

            result = {
                "type": "json_schema",
                "json_schema": {
                    "name": processed_schema.get("name", "response"),
                    "description": processed_schema.get(
                        "description", "Structured response"
                    ),
                    "schema": processed_schema,
                    "strict": strict,
                },
            }

            return result
        except Exception as e:
            logging.error(f"Error preparing structured output format: {e}")
            return None

    def get_supported_attachment_types(self):
        """
        Return a list of MIME types supported by OpenAI for file uploads.

        This reads from the model config to ensure consistency.
        If no model config found, falls back to images only (safest default).

        Returns:
            list: List of supported MIME types
        """
        # Per-model caps from the registry win when present — a BYOM
        # endpoint that doesn't accept images would otherwise still be
        # sent base64 image parts because the OpenAI default below
        # advertises the image alias unconditionally.
        if self.capabilities is not None:
            return list(self.capabilities.supported_attachment_types or [])
        from application.core.model_yaml import resolve_attachment_alias
        return resolve_attachment_alias("image")

    def prepare_messages_with_attachments(self, messages, attachments=None):
        """
        Process attachments using OpenAI's file API for more efficient handling.

        Args:
            messages (list): List of message dictionaries.
            attachments (list): List of attachment dictionaries with content and metadata.

        Returns:
            list: Messages formatted with file references for OpenAI API.
        """
        if not attachments:
            return messages
        prepared_messages = messages.copy()

        # Find the user message to attach file_id to the last one

        user_message_index = None
        for i in range(len(prepared_messages) - 1, -1, -1):
            if prepared_messages[i].get("role") == "user":
                user_message_index = i
                break
        if user_message_index is None:
            user_message = {"role": "user", "content": []}
            prepared_messages.append(user_message)
            user_message_index = len(prepared_messages) - 1
        if isinstance(prepared_messages[user_message_index].get("content"), str):
            text_content = prepared_messages[user_message_index]["content"]
            prepared_messages[user_message_index]["content"] = [
                {"type": "text", "text": text_content}
            ]
        elif not isinstance(prepared_messages[user_message_index].get("content"), list):
            prepared_messages[user_message_index]["content"] = []
        for attachment in attachments:
            mime_type = attachment.get("mime_type")
            logging.info(f"Processing attachment with mime_type: {mime_type}, has_data: {'data' in attachment}, has_path: {'path' in attachment}")

            if mime_type and mime_type.startswith("image/"):
                try:
                    # Check if this is a pre-converted image (from PDF-to-image conversion)
                    if "data" in attachment:
                        base64_image = attachment["data"]
                    else:
                        base64_image = self._get_base64_image(attachment)

                    prepared_messages[user_message_index]["content"].append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}"
                            },
                        }
                    )

                except Exception as e:
                    logging.error(
                        f"Error processing image attachment: {e}", exc_info=True
                    )
                    if "content" in attachment:
                        prepared_messages[user_message_index]["content"].append(
                            {
                                "type": "text",
                                "text": f"[Image could not be processed: {attachment.get('path', 'unknown')}]",
                            }
                        )
            # Handle PDFs using the file API

            elif mime_type == "application/pdf":
                logging.info(f"Attempting to upload PDF to OpenAI: {attachment.get('path', 'unknown')}")
                try:
                    file_id = self._upload_file_to_openai(attachment)
                    if not file_id:
                        # Never emit ``{"file_id": None}``: the part carries no
                        # document, providers 4xx or silently ignore it, and
                        # downstream cleaning degrades it to a note claiming the
                        # file "could not be processed" — while the parsed text
                        # sits unused on the attachment row.
                        raise ValueError(
                            "no file_id returned for PDF upload "
                            f"{attachment.get('path', 'unknown')!r}"
                        )
                    # ``file_id`` only. Sending ``filename`` alongside it is
                    # rejected: 400 "Unknown parameter: …file.filename".
                    prepared_messages[user_message_index]["content"].append(
                        {"type": "file", "file": {"file_id": file_id}}
                    )
                except Exception as e:
                    logging.error(f"Error uploading PDF to OpenAI: {e}", exc_info=True)
                    # Truthy, not membership — ``content`` is always a key on a
                    # PG-backed attachment and is "" when extraction produced
                    # nothing, which would otherwise send an empty "File
                    # content:" block and read as a successfully-read document.
                    if attachment.get("content"):
                        prepared_messages[user_message_index]["content"].append(
                            {
                                "type": "text",
                                "text": (
                                    "File content:\n\n"
                                    f"{self._fit_attachment_text(attachment['content'])}"
                                ),
                            }
                        )
                    else:
                        # Nothing to fall back on: say so, naming the user's own
                        # file so the answer can't invent a generic excuse.
                        filename = (
                            attachment.get("filename")
                            or os.path.basename(attachment.get("path") or "")
                            or "the attached file"
                        )
                        prepared_messages[user_message_index]["content"].append(
                            {
                                "type": "text",
                                "text": f"[File '{filename}' could not be processed]",
                            }
                        )
            else:
                logging.warning(f"Unsupported attachment type in OpenAI provider: {mime_type}")
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

    def _fit_attachment_text(self, content: str) -> str:
        """Bound inlined attachment text to a share of the model's window.

        ``_enforce_context_window`` runs in ``_llm_gen``, *before* attachments
        are merged into the messages here, so nothing downstream trims this.
        A 200-page PDF on an endpoint without a Files API would otherwise be
        appended whole and get the whole request rejected for length — a worse
        outcome than the degrade note it replaces.
        """
        from application.core.model_utils import get_token_limit
        from application.utils import num_tokens_from_string

        try:
            limit = get_token_limit(self.model_id) if self.model_id else 0
        except Exception:
            limit = 0
        # Half the window: the prompt, history and the answer share the rest.
        budget = int(limit * 0.5) if limit else 24000
        try:
            # Tokenize once: this is a full BPE pass over the whole extraction
            # (~12ms per 250k chars), on the hot path of every attachment turn.
            token_count = num_tokens_from_string(content)
            if token_count <= budget:
                return content
            chars_per_token = len(content) / max(token_count, 1)
            keep = max(int(budget * chars_per_token * 0.95), 0)
        except Exception:
            keep = budget * 4
        if keep <= 0 or keep >= len(content):
            return content
        return (
            f"{content[:keep]}\n\n[Content truncated: the file is larger than "
            "this model's context window.]"
        )

    def _endpoint_scope(self) -> str:
        """Short fingerprint of ``(provider, base_url, api_key)``.

        A Files-API ``file_id`` is only meaningful to the endpoint and
        credential it was uploaded to — the same reasoning the Redis inline
        cache already applies in ``_inline_file_id_cache_key``.
        """
        creds = "\0".join(
            (
                self.provider_name or "",
                self._effective_base_url or "",
                self.api_key or "",
            )
        )
        return hashlib.sha256(creds.encode("utf-8")).hexdigest()[:16]

    def _stamp_file_id(self, file_id: str) -> str:
        """Tag a file_id with the endpoint it belongs to before persisting."""
        return f"{self._endpoint_scope()}:{file_id}"

    def _scoped_file_id(self, stored):
        """Return a persisted file_id only if this endpoint can resolve it.

        ``attachments.openai_file_id`` is a single global column, so without a
        scope an id minted against one deployment would be replayed against
        another, which answers ``No such File object`` on every retry —
        permanently, since the row keeps the bad id. A miss re-uploads and
        overwrites, so this self-heals both cross-endpoint reuse and ids that
        aged out of provider retention. Legacy unscoped values are ignored.
        """
        if not stored or not isinstance(stored, str):
            return None
        scope, _, file_id = stored.partition(":")
        if not file_id or scope != self._endpoint_scope():
            return None
        return file_id

    def _upload_file_to_openai(self, attachment):
        """
        Upload a file to OpenAI and return the file_id.

        Args:
            attachment (dict): Attachment dictionary with path and metadata.
                Expected keys:
                - path: Path to the file
                - id: Optional MongoDB ID for caching

        Returns:
            str: OpenAI file_id for the uploaded file.
        """
        # Truthy check, not membership: attachment dicts are built from
        # ``SELECT *``, so ``openai_file_id`` is always a key and is NULL
        # until an upload caches one. Testing membership treated every fresh
        # attachment as a cache hit and returned None without uploading.
        cached = self._scoped_file_id(attachment.get("openai_file_id"))
        if cached:
            return cached
        file_path = attachment.get("path")

        if not self.storage.file_exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        try:
            def _upload(local_path, **_kwargs):
                with open(local_path, "rb") as uploaded_file:
                    return self.client.files.create(
                        file=uploaded_file,
                        purpose="assistants",
                    ).id

            file_id = self.storage.process_file(file_path, _upload)

            # Cache the OpenAI file id on the attachment row so we don't
            # re-upload the same blob on the next LLM call. Prefer the PG
            # UUID (``id``) when present; fall back to the legacy Mongo
            # ObjectId string (``_id``). Opened per-write — this runs
            # inside the hot LLM path, so we don't want a long-lived
            # session wrapping the generator.
            attachment_id = attachment.get("id") or attachment.get("_id")
            if attachment_id:
                user_id = None
                decoded = getattr(self, "decoded_token", None)
                if isinstance(decoded, dict):
                    user_id = decoded.get("sub")
                from application.storage.db.repositories.attachments import (
                    AttachmentsRepository,
                )
                from application.storage.db.session import db_session

                try:
                    with db_session() as conn:
                        AttachmentsRepository(conn).update_any(
                            str(attachment_id),
                            user_id,
                            {"openai_file_id": self._stamp_file_id(file_id)},
                        )
                except Exception as cache_err:
                    logging.warning(
                        f"Failed to cache openai_file_id on attachment {attachment_id}: {cache_err}"
                    )
            return file_id
        except Exception as e:
            logging.error(f"Error uploading file to OpenAI: {e}", exc_info=True)
            raise
