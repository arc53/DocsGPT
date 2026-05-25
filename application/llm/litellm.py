"""LiteLLM provider for DocsGPT.

Provides access to 100+ LLM providers (OpenAI, Anthropic, Google, Azure,
Bedrock, Vertex, Cohere, etc.) through a single unified interface using
LiteLLM as an AI gateway.

Users configure ``LLM_PROVIDER=litellm`` and set ``LLM_NAME`` to any
LiteLLM-supported model string (e.g. ``anthropic/claude-3-haiku``,
``azure/gpt-4o``, ``bedrock/anthropic.claude-v2``).  Provider-specific
API keys are read from standard environment variables
(``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, etc.) — LiteLLM picks
them up automatically.
"""

import json
import logging

from application.core.settings import settings
from application.llm.base import BaseLLM

logger = logging.getLogger(__name__)


class LiteLLM(BaseLLM):
    """LiteLLM provider — unified gateway to 100+ LLM providers.

    Args:
        api_key: API key forwarded to ``litellm.completion``.  Defaults
            to ``settings.API_KEY``.  LiteLLM also reads provider-specific
            keys from environment variables automatically.
        user_api_key: Optional user-provided API key override.
        base_url: Optional custom base URL.
    """

    def __init__(
        self,
        api_key: str | None = None,
        user_api_key: str | None = None,
        base_url: str | None = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.api_key = api_key or settings.API_KEY
        self.user_api_key = user_api_key
        self.litellm_base_url = base_url

    def _clean_messages(self, messages: list[dict]) -> list[dict]:
        """Normalize messages into OpenAI chat-completion format.

        LiteLLM accepts OpenAI-format messages and translates them
        for each provider internally, so this method mirrors the
        cleaning logic used by the OpenAI provider.

        Args:
            messages: Raw message list from the pipeline.

        Returns:
            Cleaned list of message dicts.
        """
        cleaned: list[dict] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")

            if role == "model":
                role = "assistant"

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
                    cleaned_tcs.append(
                        {
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": func.get("name", ""),
                                "arguments": args,
                            },
                        }
                    )
                cleaned.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": cleaned_tcs,
                    }
                )
                continue

            tool_call_id = message.get("tool_call_id")
            if role == "tool" and tool_call_id is not None:
                cleaned.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": (
                            content
                            if isinstance(content, str)
                            else json.dumps(content)
                        ),
                    }
                )
                continue

            if role and content is not None:
                if isinstance(content, str):
                    cleaned.append({"role": role, "content": content})
                elif isinstance(content, list):
                    content_parts: list[dict] = []
                    for item in content:
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
                            cleaned.append(
                                {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [tool_call],
                                }
                            )
                        elif "function_response" in item:
                            cleaned.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": item["function_response"][
                                        "call_id"
                                    ],
                                    "content": json.dumps(
                                        item["function_response"]["response"][
                                            "result"
                                        ]
                                    ),
                                }
                            )
                        elif isinstance(item, dict):
                            if (
                                "type" in item
                                and item["type"] == "text"
                                and "text" in item
                            ):
                                content_parts.append(item)
                            elif (
                                "type" in item
                                and item["type"] == "image_url"
                                and "image_url" in item
                            ):
                                content_parts.append(item)
                            elif "text" in item and "type" not in item:
                                content_parts.append(
                                    {"type": "text", "text": item["text"]}
                                )
                    if content_parts:
                        cleaned.append({"role": role, "content": content_parts})
                else:
                    raise ValueError(f"Unexpected content type: {type(content)}")
        return cleaned

    @staticmethod
    def _extract_reasoning_text(delta) -> str:
        """Extract reasoning/thinking tokens from a stream delta chunk.

        Args:
            delta: A delta object from a streaming response chunk.

        Returns:
            Extracted reasoning text, or empty string.
        """
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
            if value and isinstance(value, str):
                return value
        return ""

    def _build_completion_params(
        self,
        model: str,
        messages: list[dict],
        stream: bool,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> dict:
        """Build the parameter dict for ``litellm.completion``.

        Args:
            model: LiteLLM model string.
            messages: Cleaned message list.
            stream: Whether to stream.
            tools: Optional tool definitions.
            **kwargs: Extra kwargs forwarded to LiteLLM.

        Returns:
            Dict of keyword arguments for ``litellm.completion``.
        """
        params: dict = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "drop_params": True,
            **kwargs,
        }

        if self.api_key:
            params["api_key"] = self.api_key
        if self.litellm_base_url:
            params["api_base"] = self.litellm_base_url
        if tools:
            params["tools"] = tools

        return params

    def _raw_gen(
        self,
        baseself,
        model: str,
        messages: list[dict],
        stream: bool = False,
        tools: list[dict] | None = None,
        **kwargs,
    ):
        """Generate a single completion via LiteLLM.

        Args:
            baseself: Reference passed by the decorator chain.
            model: LiteLLM model string (e.g. ``anthropic/claude-3-haiku``).
            messages: Chat messages.
            stream: Must be ``False`` for non-streaming.
            tools: Optional tool definitions.
            **kwargs: Extra arguments forwarded to ``litellm.completion``.

        Returns:
            Content string, or a Choice object when tools are used.
        """
        import litellm

        messages = self._clean_messages(messages)
        logger.info(
            "LiteLLM _raw_gen: model=%s, message_count=%d, tools=%s",
            model,
            len(messages),
            bool(tools),
        )

        params = self._build_completion_params(
            model, messages, stream=False, tools=tools, **kwargs
        )
        response = litellm.completion(**params)

        if tools:
            return response.choices[0]
        return response.choices[0].message.content

    def _raw_gen_stream(
        self,
        baseself,
        model: str,
        messages: list[dict],
        stream: bool = True,
        tools: list[dict] | None = None,
        **kwargs,
    ):
        """Generate a streaming completion via LiteLLM.

        Args:
            baseself: Reference passed by the decorator chain.
            model: LiteLLM model string.
            messages: Chat messages.
            stream: Must be ``True`` for streaming.
            tools: Optional tool definitions.
            **kwargs: Extra arguments forwarded to ``litellm.completion``.

        Yields:
            ``str`` for content tokens, ``dict`` for thinking/reasoning
            tokens, or a Choice object for tool-call chunks.
        """
        import litellm

        messages = self._clean_messages(messages)
        logger.info(
            "LiteLLM _raw_gen_stream: model=%s, message_count=%d, tools=%s",
            model,
            len(messages),
            bool(tools),
        )

        params = self._build_completion_params(
            model, messages, stream=True, tools=tools, **kwargs
        )
        response = litellm.completion(**params)

        try:
            for line in response:
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

                if has_tool_calls or finish_reason == "tool_calls":
                    yield choice
        finally:
            if hasattr(response, "close"):
                response.close()

    def _supports_tools(self) -> bool:
        """LiteLLM supports function calling for providers that support it."""
        return True

    def _supports_structured_output(self) -> bool:
        """LiteLLM supports structured output for providers that support it."""
        return True

    def prepare_structured_output_format(
        self, json_schema: dict | None
    ) -> dict | None:
        """Prepare structured output format using OpenAI's json_schema spec.

        LiteLLM translates OpenAI-format ``response_format`` to each
        provider's native format via ``drop_params=True``.

        Args:
            json_schema: JSON schema dict for the expected response.

        Returns:
            OpenAI-format ``response_format`` dict, or ``None``.
        """
        if not json_schema:
            return None
        try:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": json_schema.get("name", "response"),
                    "description": json_schema.get(
                        "description", "Structured response"
                    ),
                    "schema": json_schema,
                    "strict": True,
                },
            }
        except Exception as e:
            logger.error("Error preparing structured output format: %s", e)
            return None
