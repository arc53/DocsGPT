import uuid
from typing import Any, Dict, Generator

from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


class GoogleLLMHandler(LLMHandler):
    """Handler for Google's GenAI API."""

    def parse_response(self, response: Any) -> LLMResponse:
        """Parse Google response into standardized format."""

        if isinstance(response, str):
            return LLMResponse(
                content=response,
                tool_calls=[],
                finish_reason="stop",
                raw_response=response,
            )
        if hasattr(response, "candidates"):
            parts = response.candidates[0].content.parts if response.candidates else []
            tool_calls = []
            for idx, part in enumerate(parts):
                if hasattr(part, "function_call") and part.function_call is not None:
                    has_sig = hasattr(part, "thought_signature") and part.thought_signature is not None
                    thought_sig = part.thought_signature if has_sig else None
                    tool_calls.append(
                        ToolCall(
                            id=str(uuid.uuid4()),
                            name=part.function_call.name,
                            arguments=part.function_call.args,
                            index=idx,
                            thought_signature=thought_sig,
                        )
                    )

            content = " ".join(
                part.text
                for part in parts
                if hasattr(part, "text") and part.text is not None
            )
            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason="tool_calls" if tool_calls else "stop",
                raw_response=response,
            )
        else:
            # This branch handles individual Part objects from streaming responses
            tool_calls = []
            if hasattr(response, "function_call") and response.function_call is not None:
                has_sig = hasattr(response, "thought_signature") and response.thought_signature is not None
                thought_sig = response.thought_signature if has_sig else None
                tool_calls.append(
                    ToolCall(
                        id=str(uuid.uuid4()),
                        name=response.function_call.name,
                        arguments=response.function_call.args,
                        thought_signature=thought_sig,
                    )
                )
            return LLMResponse(
                content=response.text if hasattr(response, "text") else "",
                tool_calls=tool_calls,
                finish_reason="tool_calls" if tool_calls else "stop",
                raw_response=response,
            )

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        """Create Google-style tool message."""

        return {
            "role": "model",
            "content": [
                {
                    "function_response": {
                        "name": tool_call.name,
                        "response": {"result": result},
                    }
                }
            ],
        }

    def _iterate_stream(self, response: Any) -> Generator:
        """Iterate through Google streaming response."""
        for chunk in response:
            yield chunk
