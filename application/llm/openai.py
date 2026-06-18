import base64
import json
import logging

from openai import OpenAI

from application.core.settings import settings
from application.llm.base import BaseLLM
from application.storage.storage_creator import StorageCreator


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
        self.api_key = api_key or settings.OPENAI_API_KEY or settings.API_KEY
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
                                content_parts.append(item)
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
        logging.info(f"Cleaned messages: {_truncate_base64_for_logging(messages)}")

        # Convert max_tokens to max_completion_tokens for newer models
        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")

        # Defense-in-depth: drop tools / response_format if the
        # registry's capability flags deny them.
        if tools and not self._supports_tools():
            tools = None
        if response_format and not self._supports_structured_output():
            response_format = None

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
        response = self.client.chat.completions.create(**request_params)
        logging.info(f"OpenAI response: {response}")
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
        logging.info(f"Cleaned messages: {_truncate_base64_for_logging(messages)}")

        # Convert max_tokens to max_completion_tokens for newer models
        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")

        # See _raw_gen for rationale — drop tools/response_format when the
        # registry-provided capabilities say the model doesn't support them.
        if tools and not self._supports_tools():
            tools = None
        if response_format and not self._supports_structured_output():
            response_format = None

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
        response = self.client.chat.completions.create(**request_params)

        try:
            for line in response:
                logging.debug(f"OpenAI stream line: {line}")
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

    def _to_responses_input(self, messages):
        """Translate cleaned Chat-Completions messages into a Responses
        ``input`` item list.

        Reasoning items captured during the in-turn tool loop are re-injected
        ahead of the function calls they belong to (deduped by id) so the
        model keeps its chain-of-thought across the round-trip.
        """
        input_items = []
        emitted_reasoning = set()
        for message in messages:
            role = message.get("role")
            tool_calls = message.get("tool_calls")
            if tool_calls and role == "assistant":
                for tc in tool_calls:
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
                continue
            tool_call_id = message.get("tool_call_id")
            if role == "tool" and tool_call_id is not None:
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
        the earlier turns, so only system context plus everything after the
        last completed assistant response needs to be sent again."""
        last_assistant = -1
        for i, message in enumerate(messages):
            if message.get("role") == "assistant" and not message.get(
                "tool_calls"
            ):
                last_assistant = i
        if last_assistant < 0:
            return messages
        head = [
            m
            for m in messages[: last_assistant + 1]
            if m.get("role") == "system"
        ]
        return head + messages[last_assistant + 1:]

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
            params["reasoning"] = {"effort": effort, "summary": "auto"}

        if response_format:
            fmt = self._responses_text_format(response_format)
            if fmt:
                params["text"] = {"format": fmt}

        if tools:
            params["tools"] = self._to_responses_tools(tools)

        store = bool(settings.OPENAI_RESPONSES_STORE)
        params["store"] = store
        if store and previous_response_id:
            params["previous_response_id"] = previous_response_id
        # Always request encrypted reasoning content so reasoning items can be
        # replayed by value across the in-turn tool loop — this keeps
        # carryover working whether or not the response is also retained
        # server-side (store=true).
        params["include"] = ["reasoning.encrypted_content"]
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

    def _record_responses_metadata(self, response):
        rid = getattr(response, "id", None)
        if rid:
            self._last_response_id = rid

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
        if previous_response_id and settings.OPENAI_RESPONSES_STORE:
            messages = self._trim_for_previous_response(messages)
        input_items = self._to_responses_input(messages)
        params = self._build_responses_params(
            model,
            input_items,
            tools,
            response_format,
            previous_response_id,
            stream=False,
            kwargs=kwargs,
        )
        response = self.client.responses.create(**params)
        logging.info(f"OpenAI responses output: {getattr(response, 'output', None)}")
        self._record_responses_metadata(response)
        content, tool_calls, reasoning_items = self._parse_responses_output(
            response
        )
        if tools:
            self._remember_reasoning(tool_calls, reasoning_items)
            message = _RespMessage(
                content=content or None, tool_calls=tool_calls or None
            )
            return _RespChoice(
                finish_reason="tool_calls" if tool_calls else "stop",
                message=message,
            )
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
        if previous_response_id and settings.OPENAI_RESPONSES_STORE:
            messages = self._trim_for_previous_response(messages)
        input_items = self._to_responses_input(messages)
        params = self._build_responses_params(
            model,
            input_items,
            tools,
            response_format,
            previous_response_id,
            stream=True,
            kwargs=kwargs,
        )
        response = self.client.responses.create(**params)

        func_calls = {}
        reasoning_items = []
        try:
            for event in response:
                etype = getattr(event, "type", "")
                if etype == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield delta
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
                    self._record_responses_metadata(
                        getattr(event, "response", None)
                    )
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
                elif etype in ("response.failed", "error"):
                    resp = getattr(event, "response", None)
                    err = (
                        getattr(resp, "error", None)
                        or getattr(event, "message", None)
                        or "Responses stream error"
                    )
                    raise RuntimeError(f"Responses API stream error: {err}")
        finally:
            if hasattr(response, "close"):
                response.close()

    def _supports_tools(self):
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
                    prepared_messages[user_message_index]["content"].append(
                        {"type": "file", "file": {"file_id": file_id}}
                    )
                except Exception as e:
                    logging.error(f"Error uploading PDF to OpenAI: {e}", exc_info=True)
                    if "content" in attachment:
                        prepared_messages[user_message_index]["content"].append(
                            {
                                "type": "text",
                                "text": f"File content:\n\n{attachment['content']}",
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
        if "openai_file_id" in attachment:
            return attachment["openai_file_id"]
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
                            {"openai_file_id": file_id},
                        )
                except Exception as cache_err:
                    logging.warning(
                        f"Failed to cache openai_file_id on attachment {attachment_id}: {cache_err}"
                    )
            return file_id
        except Exception as e:
            logging.error(f"Error uploading file to OpenAI: {e}", exc_info=True)
            raise
