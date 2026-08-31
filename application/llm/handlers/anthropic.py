from typing import Any, Dict, Generator

from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall

# Anthropic's stop reasons in the OpenAI vocabulary ``LLMHandler`` speaks.
_STOP_REASON_MAP = {
    "tool_use": "tool_calls",
    "max_tokens": "length",
}


class AnthropicLLMHandler(LLMHandler):
    """Handler for the Anthropic Messages API.

    Parses both shapes ``AnthropicLLM`` produces: the non-streaming
    ``Message`` object, and the normalised chunks its stream generator
    yields (``{"type": "tool_use"|"thought", ...}``).
    """

    def parse_response(self, response: Any) -> LLMResponse:
        """Parse an Anthropic response into the standardized format."""
        if isinstance(response, str):
            return LLMResponse(
                content=response,
                tool_calls=[],
                finish_reason="stop",
                raw_response=response,
            )

        if isinstance(response, dict):
            return self._parse_stream_chunk(response)

        content_parts = []
        reasoning_parts = []
        tool_calls = []
        for block in getattr(response, "content", None) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                content_parts.append(getattr(block, "text", "") or "")
            elif block_type == "thinking":
                reasoning_parts.append(getattr(block, "thinking", "") or "")
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=getattr(block, "id", "") or "",
                        name=getattr(block, "name", "") or "",
                        arguments=getattr(block, "input", None) or {},
                    )
                )

        stop_reason = getattr(response, "stop_reason", None)
        finish_reason = _STOP_REASON_MAP.get(stop_reason, "stop")
        if tool_calls:
            finish_reason = "tool_calls"
        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            raw_response=response,
            reasoning_content="".join(reasoning_parts),
        )

    @staticmethod
    def _parse_stream_chunk(chunk: Dict[str, Any]) -> LLMResponse:
        """Parse a normalised streaming chunk from ``AnthropicLLM``.

        Tool-call JSON is buffered provider-side and emitted whole, so the
        resulting ``ToolCall`` carries no ``index`` — the signal
        ``handle_streaming`` uses to keep a call intact instead of
        concatenating it into a partial one.
        """
        if chunk.get("type") == "tool_use":
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id=chunk.get("id", ""),
                        name=chunk.get("name", ""),
                        arguments=chunk.get("arguments", "{}"),
                    )
                ],
                finish_reason="tool_calls",
                raw_response=chunk,
            )
        return LLMResponse(
            content="",
            tool_calls=[],
            finish_reason="",
            raw_response=chunk,
            reasoning_content=(
                chunk.get("thought", "") if chunk.get("type") == "thought" else ""
            ),
        )

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        """Create a tool result message in the standard internal format."""
        import json as _json

        from application.storage.db.serialization import PGNativeJSONEncoder

        # PostgresTool results commonly include PG-native types
        # (datetime / UUID / Decimal / bytea) when SELECT touches
        # timestamptz / numeric / uuid / bytea columns. The shared
        # encoder handles all five — bytes get base64 (lossless) instead
        # of the ``str(b'...')`` repr that ``default=str`` would emit.
        content = (
            _json.dumps(result, cls=PGNativeJSONEncoder)
            if not isinstance(result, str)
            else result
        )
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": content,
        }

    def _iterate_stream(self, response: Any) -> Generator:
        """Iterate through the Anthropic streaming response."""
        for chunk in response:
            yield chunk
