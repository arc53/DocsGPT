from typing import Any, Dict, Generator

from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


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
        return LLMResponse(
            content=getattr(message, "content", ""),
            tool_calls=tool_calls,
            finish_reason=getattr(response, "finish_reason", ""),
            raw_response=response,
        )

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        """Create OpenAI-style tool message."""
        return {
            "role": "tool",
            "content": [
                {
                    "function_response": {
                        "name": tool_call.name,
                        "response": {"result": result},
                        "call_id": tool_call.id,
                    }
                }
            ],
        }

    def _iterate_stream(self, response: Any) -> Generator:
        """Iterate through OpenAI streaming response."""
        for chunk in response:
            yield chunk
