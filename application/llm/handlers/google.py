import base64
import binascii
import uuid
from typing import Any, Dict, Generator, Optional, Union

from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


def _encode_thought_signature(sig: Optional[Union[bytes, str]]) -> Optional[str]:
    # Gemini's Python SDK returns thought_signature as raw bytes, but the
    # field is typed Optional[str] downstream and gets json.dumps'd into
    # SSE events. Encode once at ingress so callers only ever see a str.
    if isinstance(sig, bytes):
        return base64.b64encode(sig).decode("ascii")
    return sig


def _decode_thought_signature(
    sig: Optional[Union[bytes, str]],
) -> Optional[Union[bytes, str]]:
    # Reverse of _encode_thought_signature — Gemini's SDK expects bytes
    # back when we replay a tool call. ``validate=True`` keeps ASCII
    # strings that happen to be loosely decodable from being silently
    # turned into bytes; non-base64 inputs pass through unchanged.
    if isinstance(sig, str):
        try:
            return base64.b64decode(sig.encode("ascii"), validate=True)
        except (binascii.Error, ValueError):
            return sig
    return sig


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
                    thought_sig = _encode_thought_signature(part.thought_signature) if has_sig else None
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
                thought_sig = _encode_thought_signature(response.thought_signature) if has_sig else None
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
        """Iterate through Google streaming response."""
        for chunk in response:
            yield chunk
