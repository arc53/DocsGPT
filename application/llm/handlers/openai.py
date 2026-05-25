from typing import Any, Dict, Generator

from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall
from application.llm.openai import OpenAILLM


class OpenAILLMHandler(LLMHandler):
    """Handler for OpenAI API."""

    def parse_response(self, response: Any) -> LLMResponse:
        """Parse OpenAI response into standardized format."""
        if isinstance(response, str):
            return LLMResponse(
                content=response,
                tool_calls=[],
                finish_reason="stop",
                raw_response=response,
            )

        message = getattr(response, "message", None) or getattr(response, "delta", None)

        tool_calls = []
        if hasattr(message, "tool_calls"):
            tool_calls = [
                ToolCall(
                    id=getattr(tc, "id", ""),
                    name=getattr(tc.function, "name", ""),
                    arguments=getattr(tc.function, "arguments", ""),
                    index=getattr(tc, "index", None),
                )
                for tc in message.tool_calls or []
            ]
        # Reasoning lives on the message object for non-streaming and
        # on the delta for streaming. DeepSeek thinking mode requires
        # this to be echoed back on the next turn.
        reasoning_content = OpenAILLM._extract_reasoning_text(message)
        return LLMResponse(
            content=getattr(message, "content", ""),
            tool_calls=tool_calls,
            finish_reason=getattr(response, "finish_reason", ""),
            raw_response=response,
            reasoning_content=reasoning_content,
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
        """Iterate through OpenAI streaming response."""
        for chunk in response:
            yield chunk
