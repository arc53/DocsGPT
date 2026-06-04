"""Translate between standard chat completions format and DocsGPT internals.

This module handles:
- Request translation (chat completions -> DocsGPT internal format)
- Response translation (DocsGPT response -> chat completions format)
- Streaming event translation (DocsGPT SSE -> standard SSE chunks)
"""

import json
import re
import time
from typing import Any, Dict, List, Optional

# Some upstream models/proxies echo their reasoning into ``content`` as
# stringified ``{'type': 'thought', 'thought': '...'}`` event reprs (instead of
# using the separate reasoning channel) — most visibly when ``response_format``
# is set. OpenAI's API never puts reasoning in ``content``, so for the
# OpenAI-compatible endpoint we strip these and reroute them to
# ``reasoning_content`` to keep ``content`` clean and compatible.
# The thought value is a Python string repr: single-quoted, or double-quoted when
# the token contains an apostrophe (e.g. "'ll"). Match the full quoted value
# (honoring escapes) so tokens containing ``}`` or newlines don't truncate the
# match and leave stray ``'}`` tails in the content.
_LEAKED_THOUGHT_RE = re.compile(
    r"""\{'type': 'thought', 'thought': ('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")\}""",
    re.DOTALL,
)


def _strip_repr_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1]
    return value


def _split_leaked_reasoning(content: Optional[str]) -> tuple:
    """Return ``(clean_content, leaked_reasoning)``.

    ``clean_content`` has any stringified thought-event reprs removed;
    ``leaked_reasoning`` is the concatenated reasoning text that was extracted.
    A no-op (returns the input unchanged) when no leak markers are present.
    """
    if not content or "'type': 'thought'" not in content:
        return content, ""
    extracted: List[str] = []
    cleaned = _LEAKED_THOUGHT_RE.sub(
        lambda m: (extracted.append(_strip_repr_quotes(m.group(1))) or ""), content
    )
    return cleaned, "".join(extracted)


def _get_client_tool_name(tc: Dict) -> str:
    """Return the original tool name for client-facing responses.

    For client-side tools the ``tool_name`` field carries the name the
    client originally registered.  Fall back to ``action_name`` (which
    is now the clean LLM-visible name) or ``name``.
    """
    return tc.get("tool_name", tc.get("action_name", tc.get("name", "")))


# ---------------------------------------------------------------------------
# Request translation
# ---------------------------------------------------------------------------


def is_continuation(messages: List[Dict]) -> bool:
    """Check if messages represent a tool-call continuation.

    A continuation is detected when the last message(s) have ``role: "tool"``
    immediately after an assistant message with ``tool_calls``.
    """
    if not messages:
        return False
    # Walk backwards: if we see tool messages before hitting a non-tool, non-assistant message
    # and there's an assistant message with tool_calls, it's a continuation.
    i = len(messages) - 1
    while i >= 0 and messages[i].get("role") == "tool":
        i -= 1
    if i < 0:
        return False
    return (
        messages[i].get("role") == "assistant"
        and bool(messages[i].get("tool_calls"))
    )


def extract_tool_results(messages: List[Dict]) -> List[Dict]:
    """Extract tool results from trailing tool messages for continuation.

    Returns a list of ``tool_actions`` dicts with ``call_id`` and ``result``.
    """
    results = []
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            break
        call_id = msg.get("tool_call_id", "")
        content = msg.get("content", "")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                pass
        results.append({"call_id": call_id, "result": content})
    results.reverse()
    return results


def extract_conversation_id(messages: List[Dict]) -> Optional[str]:
    """Try to extract conversation_id from the assistant message before tool results.

    The conversation_id may be stored in a custom field on the assistant message
    from a previous response cycle.
    """
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            # Check docsgpt extension
            return msg.get("docsgpt", {}).get("conversation_id")
    return None


def extract_system_prompt(messages: List[Dict]) -> Optional[str]:
    """Extract the first system message content from the messages array.

    Returns None if no system message is present.
    """
    for msg in messages:
        if msg.get("role") == "system":
            return msg.get("content", "")
    return None


def convert_history(messages: List[Dict]) -> List[Dict]:
    """Convert chat completions messages array to DocsGPT history format.

    DocsGPT history is a list of ``{prompt, response}`` dicts.
    Excludes the last user message (that becomes the ``question``).
    """
    history = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "system":
            i += 1
            continue
        if msg.get("role") == "user":
            # Look ahead for assistant response
            if i + 1 < len(messages) and messages[i + 1].get("role") == "assistant":
                content = messages[i + 1].get("content") or ""
                history.append({
                    "prompt": msg.get("content", ""),
                    "response": content,
                })
                i += 2
                continue
            # Last user message without response — skip (it's the question)
            i += 1
            continue
        i += 1
    return history


def extract_response_schema(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract a JSON schema for structured output from a chat-completions request.

    Supports two request shapes:
    - OpenAI ``response_format``:
      ``{"type": "json_schema", "json_schema": {"name": ..., "schema": {...}}}``
      (a bare schema under ``json_schema`` is also tolerated).
    - ``response_schema`` convenience field: a raw JSON Schema object, or a
      ``{"schema": {...}}`` wrapper.

    Returns a raw JSON Schema object, or None. ``response_format``
    ``{"type": "json_object"}`` carries no schema to enforce and yields None
    (the model is still steered by the system prompt).
    """
    response_schema = data.get("response_schema")
    if isinstance(response_schema, dict) and response_schema:
        inner = response_schema.get("schema")
        return inner if isinstance(inner, dict) else response_schema

    response_format = data.get("response_format")
    if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
        json_schema = response_format.get("json_schema")
        if isinstance(json_schema, dict):
            schema = json_schema.get("schema")
            if isinstance(schema, dict):
                return schema
            if "type" in json_schema:
                return json_schema
    return None


def translate_request(
    data: Dict[str, Any], api_key: str
) -> Dict[str, Any]:
    """Translate a chat completions request to DocsGPT internal format.

    Args:
        data: The incoming request body.
        api_key: Agent API key from the Authorization header.

    Returns:
        Dict suitable for passing to ``StreamProcessor``.
    """
    messages = data.get("messages", [])
    response_schema = extract_response_schema(data)
    _rf = data.get("response_format")
    _rf = _rf if isinstance(_rf, dict) else {}
    # OpenAI Structured Outputs default to strict; honor an explicit strict:false.
    json_schema_strict = bool((_rf.get("json_schema") or {}).get("strict", True))
    json_object_mode = _rf.get("type") == "json_object"

    # Check for continuation (tool results after assistant tool_calls)
    if is_continuation(messages):
        tool_actions = extract_tool_results(messages)
        conversation_id = extract_conversation_id(messages)
        if not conversation_id:
            conversation_id = data.get("conversation_id")
        result = {
            "conversation_id": conversation_id,
            "tool_actions": tool_actions,
            "api_key": api_key,
        }
        # A continuation only exists if turn 1 was saved, so default to True —
        # otherwise the final turn and its WAL row are never persisted. An
        # explicit override is honoured if the client resends it.
        result["save_conversation"] = bool(
            data.get("docsgpt", {}).get("save_conversation", True)
        )
        # Carry tools forward for next iteration
        if data.get("tools"):
            result["client_tools"] = data["tools"]
        if response_schema is not None:
            result["json_schema"] = response_schema
            result["json_schema_strict"] = json_schema_strict
        if json_object_mode:
            result["json_object"] = True
        return result

    # Normal request — extract question from last user message
    question = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            question = msg.get("content", "")
            break

    history = convert_history(messages)
    system_prompt_override = extract_system_prompt(messages)

    docsgpt = data.get("docsgpt", {})

    result = {
        "question": question,
        "api_key": api_key,
        "history": json.dumps(history),
        # Conversations are NOT persisted by default on the v1 endpoint.
        # Callers opt in via ``docsgpt.save_conversation: true``.
        "save_conversation": bool(docsgpt.get("save_conversation", False)),
    }

    if system_prompt_override is not None:
        result["system_prompt_override"] = system_prompt_override

    # Client tools
    if data.get("tools"):
        result["client_tools"] = data["tools"]

    # DocsGPT extensions
    if docsgpt.get("attachments"):
        result["attachments"] = docsgpt["attachments"]

    if response_schema is not None:
        result["json_schema"] = response_schema
        result["json_schema_strict"] = json_schema_strict
    if json_object_mode:
        result["json_object"] = True

    return result


# ---------------------------------------------------------------------------
# Response translation (non-streaming)
# ---------------------------------------------------------------------------


def translate_response(
    conversation_id: str,
    answer: str,
    sources: Optional[List[Dict]],
    tool_calls: Optional[List[Dict]],
    thought: str,
    model_name: str,
    pending_tool_calls: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """Translate DocsGPT response to chat completions format.

    Args:
        conversation_id: The DocsGPT conversation ID.
        answer: The assistant's text response.
        sources: RAG retrieval sources.
        tool_calls: Completed tool call results.
        thought: Reasoning/thinking tokens.
        model_name: Model/agent identifier.
        pending_tool_calls: Pending client-side tool calls (if paused).

    Returns:
        Dict in the standard chat completions response format.
    """
    created = int(time.time())
    completion_id = f"chatcmpl-{conversation_id}" if conversation_id else f"chatcmpl-{created}"

    # Build message
    message: Dict[str, Any] = {"role": "assistant"}

    if pending_tool_calls:
        # Tool calls pending — return them for client execution
        message["content"] = None
        message["tool_calls"] = [
            {
                "id": tc.get("call_id", ""),
                "type": "function",
                "function": {
                    "name": _get_client_tool_name(tc),
                    "arguments": (
                        json.dumps(tc["arguments"])
                        if isinstance(tc.get("arguments"), dict)
                        else tc.get("arguments", "{}")
                    ),
                },
            }
            for tc in pending_tool_calls
        ]
        finish_reason = "tool_calls"
    else:
        clean_answer, leaked_reasoning = _split_leaked_reasoning(answer)
        message["content"] = clean_answer
        combined_reasoning = (thought or "") + leaked_reasoning
        if combined_reasoning:
            message["reasoning_content"] = combined_reasoning
        finish_reason = "stop"

    result: Dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }

    # DocsGPT extensions
    docsgpt: Dict[str, Any] = {}
    if conversation_id:
        docsgpt["conversation_id"] = conversation_id
    if sources:
        docsgpt["sources"] = sources
    if tool_calls:
        docsgpt["tool_calls"] = tool_calls
    if docsgpt:
        result["docsgpt"] = docsgpt

    return result


# ---------------------------------------------------------------------------
# Streaming event translation
# ---------------------------------------------------------------------------


def _make_chunk(
    completion_id: str,
    model_name: str,
    delta: Dict[str, Any],
    finish_reason: Optional[str] = None,
) -> str:
    """Build a single SSE chunk in the standard streaming format."""
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def _make_docsgpt_chunk(data: Dict[str, Any], completion_id: str, model_name: str) -> str:
    """Build a DocsGPT extension chunk that is ALSO a valid ``chat.completion.chunk``.

    Strict OpenAI clients (e.g. the Vercel AI SDK used by opencode) validate every
    SSE ``data:`` frame as a chat.completion.chunk, so the DocsGPT extension is
    attached to an otherwise-empty (no-op) chunk rather than sent as a bare
    ``{"docsgpt": ...}`` object — which has no ``choices`` and fails validation.
    OpenAI clients ignore the extra top-level ``docsgpt`` field.
    """
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
        "docsgpt": data,
    }
    return f"data: {json.dumps(chunk)}\n\n"


def translate_stream_event(
    event_data: Dict[str, Any],
    completion_id: str,
    model_name: str,
) -> List[str]:
    """Translate a DocsGPT SSE event dict to standard streaming chunks.

    May return 0, 1, or 2 chunks per input event. For example, a completed
    tool call produces both a docsgpt extension chunk and nothing on the
    standard side (since server-side tool calls aren't surfaced in standard
    format).

    Args:
        event_data: Parsed DocsGPT event dict.
        completion_id: The completion ID for this response.
        model_name: Model/agent identifier.

    Returns:
        List of SSE-formatted strings to send to the client.
    """
    event_type = event_data.get("type")
    chunks: List[str] = []

    if event_type == "answer":
        clean, leaked = _split_leaked_reasoning(event_data.get("answer", ""))
        if leaked:
            chunks.append(
                _make_chunk(completion_id, model_name, {"reasoning_content": leaked})
            )
        if clean:
            chunks.append(
                _make_chunk(completion_id, model_name, {"content": clean})
            )

    elif event_type == "thought":
        chunks.append(
            _make_chunk(
                completion_id, model_name,
                {"reasoning_content": event_data.get("thought", "")},
            )
        )

    elif event_type == "source":
        chunks.append(
            _make_docsgpt_chunk(
                {"type": "source", "sources": event_data.get("source", [])},
                completion_id, model_name,
            )
        )

    elif event_type == "tool_call":
        tc_data = event_data.get("data", {})
        status = tc_data.get("status")

        if status == "requires_client_execution":
            # Standard: stream as tool_calls delta
            args = tc_data.get("arguments", {})
            args_str = json.dumps(args) if isinstance(args, dict) else str(args)
            chunks.append(
                _make_chunk(completion_id, model_name, {
                    "tool_calls": [{
                        "index": 0,
                        "id": tc_data.get("call_id", ""),
                        "type": "function",
                        "function": {
                            "name": _get_client_tool_name(tc_data),
                            "arguments": args_str,
                        },
                    }],
                })
            )
        elif status == "awaiting_approval":
            # Extension: approval needed
            chunks.append(_make_docsgpt_chunk({"type": "tool_call", "data": tc_data}, completion_id, model_name))
        elif status in ("completed", "pending", "error", "denied", "skipped"):
            # Extension: tool call progress
            chunks.append(_make_docsgpt_chunk({"type": "tool_call", "data": tc_data}, completion_id, model_name))

    elif event_type == "tool_calls_pending":
        # Standard: finish_reason = tool_calls
        chunks.append(
            _make_chunk(completion_id, model_name, {}, finish_reason="tool_calls")
        )
        # Also emit as docsgpt extension
        chunks.append(
            _make_docsgpt_chunk(
                {
                    "type": "tool_calls_pending",
                    "pending_tool_calls": event_data.get("data", {}).get("pending_tool_calls", []),
                },
                completion_id, model_name,
            )
        )

    elif event_type == "end":
        chunks.append(
            _make_chunk(completion_id, model_name, {}, finish_reason="stop")
        )
        chunks.append("data: [DONE]\n\n")

    elif event_type == "id":
        # Skip the "None" placeholder conversation_id emitted when the call is
        # not persisted (save_conversation=false) — nothing useful to surface.
        conv_id = event_data.get("id", "")
        if conv_id and conv_id != "None":
            chunks.append(
                _make_docsgpt_chunk(
                    {"type": "id", "conversation_id": conv_id},
                    completion_id, model_name,
                )
            )

    elif event_type == "error":
        # Emit as standard error (non-standard but widely supported)
        error_data = {
            "error": {
                "message": event_data.get("error", "An error occurred"),
                "type": "server_error",
            }
        }
        chunks.append(f"data: {json.dumps(error_data)}\n\n")

    elif event_type == "structured_answer":
        clean, leaked = _split_leaked_reasoning(event_data.get("answer", ""))
        if leaked:
            chunks.append(
                _make_chunk(completion_id, model_name, {"reasoning_content": leaked})
            )
        if clean:
            chunks.append(
                _make_chunk(completion_id, model_name, {"content": clean})
            )

    # Skip: tool_calls (redundant), research_plan, research_progress

    return chunks
