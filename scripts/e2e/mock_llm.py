"""OpenAI-compatible stub server for the DocsGPT e2e test suite.

Speaks the minimum subset of the OpenAI HTTP API that DocsGPT's ``openai``
Python client needs:

* ``POST /v1/chat/completions`` (streaming + non-streaming, tool calls via fixture)
* ``POST /v1/embeddings`` (deterministic hash-seeded vectors)
* ``GET /healthz`` (liveness probe for ``scripts/e2e/up.sh``)

The server is **deterministic**: the same request always returns the same
response. Requests are fingerprinted by SHA-256 of a canonical JSON encoding
of ``(model, messages, tool_choice)``. If a fixture file matching that hash
exists under ``mock_llm_fixtures/<hash>.json`` it wins; otherwise a generic
"I don't know" fallback is returned and the hash + request is logged to stderr
so a developer can promote it into a fixture later.

**In-band reply directive.** A spec that needs to pin the assistant's exact
words cannot use a hash fixture, because DocsGPT's system prompt embeds
``Today's date is <YYYY-MM-DD>`` — the digest of the same question changes
every midnight, so a committed ``<hash>.json`` rots within a day. Instead, a
spec may embed ``[[MOCK_LLM_EMIT:<base64url>]]`` anywhere in the question; the
stub decodes it and returns exactly that text as the assistant's content.
The payload is base64 so a spec can drive the model into emitting secrets,
PII, or banned terms without those literals appearing in the request itself
(which would otherwise be scanned by an input-stage guardrail, and persisted
verbatim as the conversation's prompt). See
``tests/e2e/specs/tier-b/guardrails*.spec.ts``.

Run standalone (does NOT import anything from ``application/``). Python 3.11+.
Flask is the only non-stdlib dependency and is already in
``application/requirements.txt``.

Usage::

    python scripts/e2e/mock_llm.py

Defaults to ``127.0.0.1:7899`` to match the ``OPENAI_BASE_URL`` referenced in
``e2e-plan.md`` Appendix A.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, stream_with_context

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOST = os.environ.get("MOCK_LLM_HOST", "127.0.0.1")
PORT = int(os.environ.get("MOCK_LLM_PORT", "7899"))
FIXTURES_DIR = Path(__file__).parent / "mock_llm_fixtures"
EMBEDDING_DIM = 768
GENERIC_FALLBACK_TEXT = (
    "I don't have enough information to answer that from the provided sources."
)
STREAM_CHUNK_COUNT = 5

# In-band directive: ``[[MOCK_LLM_EMIT:<base64url payload>]]`` anywhere in the
# request messages pins the assistant's reply to the decoded payload. See the
# module docstring for why hash fixtures cannot serve this purpose.
EMIT_DIRECTIVE = re.compile(r"\[\[MOCK_LLM_EMIT:([A-Za-z0-9_=\-]+)\]\]")

# In-band directive: ``[[MOCK_LLM_TOOLCALL:<action>:<mode>]]`` makes the stub
# answer with a tool call instead of content, and controls how the call's
# ``arguments`` are split across SSE frames. Modes:
#   ``once``   — one frame carrying the complete arguments (a well-behaved
#                provider).
#   ``repeat`` — TWO frames for the same ``index``, each carrying the COMPLETE
#                arguments. Some OpenAI-compatible gateways restate a short
#                argument payload on the finish frame rather than sending a
#                delta. The merge recognises the restatement and takes the
#                latest, rather than appending into invalid JSON
#                (``{}`` + ``{}`` -> ``{}{}``).
#   ``delta``  — arguments split into genuine partial deltas, which is what the
#                merge's ``+=`` exists to reassemble. The control case.
#   ``truncated`` — a single frame carrying a PREFIX of the arguments, i.e. a
#                provider that stopped mid-payload. Unlike ``repeat`` this is
#                genuinely unrecoverable: nothing downstream can invent the
#                missing bytes, so the turn runs to the iteration cap.
# An optional 4th field is a base64url JSON object to send as the arguments;
# it defaults to ``{}`` (a zero-parameter action such as ``note_view``).
TOOLCALL_DIRECTIVE = re.compile(
    r"\[\[MOCK_LLM_TOOLCALL:([A-Za-z0-9_\-]+):(once|repeat|delta|truncated)"
    r"(?::([A-Za-z0-9_=\-]+))?\]\]"
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# CORS — permissive; stub trusts its port
# ---------------------------------------------------------------------------


@app.after_request
def _add_cors_headers(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response


@app.route("/v1/chat/completions", methods=["OPTIONS"])
@app.route("/v1/embeddings", methods=["OPTIONS"])
def _cors_preflight() -> Response:
    return Response(status=204)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Return a minimal, stable representation of the messages array.

    We keep only fields that are semantically meaningful for fingerprinting a
    request. Extra keys from the OpenAI client (e.g. ``name``, ``tool_call_id``)
    are preserved because they *do* change the intended response.
    """

    if not messages:
        return []
    out: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        # Content may be a string OR a list of content-part dicts (vision / tool).
        # Serialize both forms deterministically.
        entry: dict[str, Any] = {
            "role": msg.get("role"),
            "content": msg.get("content"),
        }
        for key in ("name", "tool_call_id", "tool_calls"):
            if key in msg:
                entry[key] = msg[key]
        out.append(entry)
    return out


def _compute_request_digest(payload: dict[str, Any]) -> str:
    """SHA-256 fingerprint of ``(model, messages, tool_choice)``.

    Kept narrow on purpose — temperature / top_p / seed / max_tokens should
    NOT influence which canned answer we return; those are knobs the app may
    flap on across runs.
    """

    canonical = {
        "model": payload.get("model"),
        "messages": _canonical_messages(payload.get("messages")),
        "tool_choice": payload.get("tool_choice"),
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load_fixture(digest: str) -> dict[str, Any] | None:
    """Return the parsed fixture dict for ``digest``, or ``None`` if missing/bad."""

    path = FIXTURES_DIR / f"{digest}.json"
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"[mock-llm] failed to load fixture {path}: {exc}\n")
        sys.stderr.flush()
        return None
    return data


def _estimate_tokens(text: str) -> int:
    """Rough 4-chars-per-token estimate (OpenAI's own ballpark)."""

    if not text:
        return 0
    return max(1, len(text) // 4)


def _messages_text(messages: list[dict[str, Any]] | None) -> str:
    """Concatenate message contents for prompt-token estimation."""

    if not messages:
        return ""
    parts: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        parts.append(text)
    return "\n".join(parts)


def _split_into_chunks(text: str, count: int) -> list[str]:
    """Split ``text`` into roughly ``count`` pieces by character length.

    Guarantees at least one chunk even for the empty string (so streaming
    clients still see a delta before ``[DONE]``).
    """

    if count <= 0:
        return [text]
    if not text:
        return [""]
    n = len(text)
    size = max(1, (n + count - 1) // count)
    chunks = [text[i : i + size] for i in range(0, n, size)]
    if not chunks:
        chunks = [""]
    return chunks


# ---------------------------------------------------------------------------
# Chat completions
# ---------------------------------------------------------------------------


def _directive_content(messages: list[dict[str, Any]] | None) -> str | None:
    """Decoded ``[[MOCK_LLM_EMIT:...]]`` payload from ``messages``, or None.

    The whole conversation is searched (not just the last turn) because
    DocsGPT wraps the user's question inside a composed turn and may replay
    history; the last directive seen wins so a follow-up turn can override an
    earlier one.
    """

    found: str | None = None
    for match in EMIT_DIRECTIVE.finditer(_messages_text(messages) or ""):
        raw = match.group(1)
        try:
            padded = raw + "=" * (-len(raw) % 4)
            found = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
            sys.stderr.write(f"[mock-llm] bad MOCK_LLM_EMIT payload {raw!r}: {exc}\n")
            sys.stderr.flush()
    return found


def _directive_toolcall(
    messages: list[dict[str, Any]] | None,
) -> tuple[str, str, str] | None:
    """Decoded ``[[MOCK_LLM_TOOLCALL:...]]`` directive, or None.

    Returns:
        ``(action_name, frame_mode, arguments_json)`` for the last directive
        found, or ``None`` when the conversation carries none.
    """

    found: tuple[str, str, str] | None = None
    for match in TOOLCALL_DIRECTIVE.finditer(_messages_text(messages) or ""):
        action, mode, raw_args = match.group(1), match.group(2), match.group(3)
        arguments = "{}"
        if raw_args:
            try:
                padded = raw_args + "=" * (-len(raw_args) % 4)
                arguments = base64.urlsafe_b64decode(padded.encode("ascii")).decode(
                    "utf-8"
                )
            except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
                sys.stderr.write(
                    f"[mock-llm] bad MOCK_LLM_TOOLCALL args {raw_args!r}: {exc}\n"
                )
                sys.stderr.flush()
        found = (action, mode, arguments)
    return found


def _toolcall_arg_frames(arguments: str, mode: str) -> list[str]:
    """Split ``arguments`` into the per-frame payloads for ``mode``."""

    if mode == "repeat":
        # The incident shape: the complete payload arrives twice for one index.
        return [arguments, arguments]
    if mode == "truncated":
        # A provider that stopped mid-payload. Strip the closing brace so the
        # accumulator can never parse, however it is merged.
        stripped = arguments.rstrip()
        if len(stripped) < 2:
            return ['{"']
        return [stripped[:-1]]
    if mode == "delta":
        if len(arguments) < 2:
            return [arguments]
        midpoint = len(arguments) // 2
        return [arguments[:midpoint], arguments[midpoint:]]
    return [arguments]


def _resolve_chat_response(
    payload: dict[str, Any], digest: str
) -> tuple[str, list[dict[str, Any]] | None, str, dict[str, int]]:
    """Return ``(content, tool_calls, finish_reason, usage)`` for ``payload``.

    An in-band ``[[MOCK_LLM_EMIT:...]]`` directive wins outright. Otherwise a
    fixture is looked up by digest; failing that the generic response is
    returned and the miss is logged so the dev can convert it.
    """

    # A real provider can only answer with a tool call when the request
    # actually offered tools. DocsGPT's finalize round deliberately sends
    # ``tools=None`` to force a text answer, so honouring that here is what
    # makes the loop terminate the way it does in production.
    toolcall = _directive_toolcall(payload.get("messages"))
    if toolcall is not None and payload.get("tools"):
        action, _mode, arguments = toolcall
        prompt_tokens = _estimate_tokens(_messages_text(payload.get("messages")))
        return (
            "",
            [
                {
                    "index": 0,
                    "id": f"call_e2e_{digest[:12]}",
                    "type": "function",
                    "function": {"name": action, "arguments": arguments},
                }
            ],
            "tool_calls",
            {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": 8,
                "total_tokens": prompt_tokens + 8,
            },
        )

    directive = _directive_content(payload.get("messages"))
    if directive is not None:
        prompt_tokens = _estimate_tokens(_messages_text(payload.get("messages")))
        completion_tokens = _estimate_tokens(directive)
        return (
            directive,
            None,
            "stop",
            {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )

    fixture = _load_fixture(digest)
    if fixture is None:
        sys.stderr.write(f"[mock-llm] unknown fixture hash {digest}\n")
        try:
            sys.stderr.write(
                "[mock-llm] request: "
                + json.dumps(payload, sort_keys=True, ensure_ascii=False)
                + "\n"
            )
        except (TypeError, ValueError):
            sys.stderr.write("[mock-llm] request: <unserializable>\n")
        sys.stderr.flush()
        content = GENERIC_FALLBACK_TEXT
        tool_calls: list[dict[str, Any]] | None = None
        finish_reason = "stop"
        prompt_tokens = _estimate_tokens(_messages_text(payload.get("messages")))
        completion_tokens = _estimate_tokens(content)
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        return content, tool_calls, finish_reason, usage

    response = fixture.get("response") or {}
    content = response.get("content") or ""
    tool_calls = response.get("tool_calls")
    finish_reason = response.get("finish_reason") or "stop"
    fixture_usage = response.get("usage") or {}
    prompt_tokens = int(
        fixture_usage.get(
            "prompt_tokens",
            _estimate_tokens(_messages_text(payload.get("messages"))),
        )
    )
    completion_tokens = int(
        fixture_usage.get("completion_tokens", _estimate_tokens(content))
    )
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    return content, tool_calls, finish_reason, usage


def _chat_completion_envelope(
    *,
    digest: str,
    model: str,
    content: str,
    tool_calls: list[dict[str, Any]] | None,
    finish_reason: str,
    usage: dict[str, int],
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": f"chatcmpl-e2e-{digest[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }


def _sse(payload: dict[str, Any]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _stream_chat_response(
    *,
    digest: str,
    model: str,
    content: str,
    tool_calls: list[dict[str, Any]] | None,
    finish_reason: str,
    chunk_delay_ms: int = 0,
    toolcall_arg_mode: str | None = None,
):
    """Generator yielding SSE frames that match the OpenAI streaming protocol.

    ``chunk_delay_ms`` (controlled by ``X-Mock-LLM-Stream-Chunk-Delay-Ms``
    header) sleeps that many milliseconds between successive SSE frames.
    Used by durability E2E tests to simulate slow streams that survive a
    mid-flight ``kill -9`` against the consumer.
    """

    created = int(time.time())
    completion_id = f"chatcmpl-e2e-{digest[:12]}"

    def _base_chunk(delta: dict[str, Any], final: bool = False) -> dict[str, Any]:
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason if final else None,
                }
            ],
        }

    def _maybe_sleep() -> None:
        if chunk_delay_ms > 0:
            time.sleep(chunk_delay_ms / 1000.0)

    # Opening role delta — matches OpenAI's real behavior.
    yield _sse(_base_chunk({"role": "assistant", "content": ""}))

    if tool_calls and toolcall_arg_mode:
        # Frame-split mode: the call's ``arguments`` are spread over several
        # deltas that all share one ``index``, which is what the client-side
        # merge in application/llm/handlers/base.py reassembles.
        call = tool_calls[0]
        frames = _toolcall_arg_frames(call["function"]["arguments"], toolcall_arg_mode)
        for position, piece in enumerate(frames):
            _maybe_sleep()
            if position == 0:
                delta = {
                    "tool_calls": [
                        {
                            "index": call.get("index", 0),
                            "id": call.get("id"),
                            "type": "function",
                            "function": {
                                "name": call["function"]["name"],
                                "arguments": piece,
                            },
                        }
                    ]
                }
            else:
                # Continuation frames carry neither id nor name — only the
                # index ties them to the call, exactly as OpenAI streams them.
                delta = {
                    "tool_calls": [
                        {
                            "index": call.get("index", 0),
                            "function": {"arguments": piece},
                        }
                    ]
                }
            yield _sse(_base_chunk(delta))
        yield _sse(_base_chunk({}, final=True))
    elif tool_calls:
        # Emit tool calls in one delta; content streaming is skipped when
        # tool_calls are present, matching what RAG code paths expect.
        _maybe_sleep()
        yield _sse(_base_chunk({"tool_calls": tool_calls}))
        yield _sse(_base_chunk({}, final=True))
    else:
        chunks = _split_into_chunks(content, STREAM_CHUNK_COUNT)
        last_index = len(chunks) - 1
        for i, piece in enumerate(chunks):
            _maybe_sleep()
            yield _sse(_base_chunk({"content": piece}, final=(i == last_index)))

    yield "data: [DONE]\n\n"


def _read_int_header(name: str, default: int = 0, ceiling: int = 600_000) -> int:
    """Parse an integer header with a sane upper bound (10 minutes)."""
    raw = request.headers.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value < 0:
        return default
    return min(value, ceiling)


def _read_int_env(name: str, default: int = 0, ceiling: int = 600_000) -> int:
    """Same as ``_read_int_header`` but for env vars — the durability E2E
    script sets ``MOCK_LLM_FORCE_*_DELAY_MS`` so it can drive slow streams
    through DocsGPT's OpenAI client without injecting per-request
    headers."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value < 0:
        return default
    return min(value, ceiling)


@app.post("/v1/chat/completions")
def chat_completions() -> Response:
    payload = request.get_json(silent=True) or {}
    model = payload.get("model") or "gpt-4o-mini"
    stream = bool(payload.get("stream"))

    digest = _compute_request_digest(payload)
    content, tool_calls, finish_reason, usage = _resolve_chat_response(payload, digest)

    # Durability E2E hooks: per-request OR per-process delays so tests can
    # simulate slow providers without touching fixtures or recompiling the
    # stub. Headers win over env so a single fixture run can opt in/out.
    upfront_delay_ms = _read_int_header("X-Mock-LLM-Total-Delay-Ms") or _read_int_env(
        "MOCK_LLM_FORCE_TOTAL_DELAY_MS"
    )
    chunk_delay_ms = _read_int_header(
        "X-Mock-LLM-Stream-Chunk-Delay-Ms"
    ) or _read_int_env("MOCK_LLM_FORCE_STREAM_CHUNK_DELAY_MS")
    if upfront_delay_ms > 0:
        time.sleep(upfront_delay_ms / 1000.0)

    if stream:
        generator = _stream_chat_response(
            digest=digest,
            model=model,
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            chunk_delay_ms=chunk_delay_ms,
            toolcall_arg_mode=(
                (_directive_toolcall(payload.get("messages")) or (None, None, None))[1]
                if payload.get("tools")
                else None
            ),
        )
        response = Response(
            stream_with_context(generator),
            mimetype="text/event-stream",
        )
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        # Flask strips Content-Length on streamed responses; make sure we don't
        # accidentally set one. Nothing to do here — just documenting.
        return response

    envelope = _chat_completion_envelope(
        digest=digest,
        model=model,
        content=content,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=usage,
    )
    return jsonify(envelope)


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def _deterministic_embedding(text: str) -> list[float]:
    """Hash-seeded 768-dim float vector in [-1, 1).

    Never all-zero: seeded RNG on a non-trivial hash of ``text`` plus a small
    non-zero offset so degenerate vector-store checks pass even if
    ``text`` itself is empty.
    """

    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16) & 0xFFFFFFFF
    rng = random.Random(seed)
    vec = [rng.uniform(-1.0, 1.0) for _ in range(EMBEDDING_DIM)]
    # Guarantee non-degeneracy: nudge the first component away from 0 if the
    # seeded draw happens to produce a very small value.
    if abs(vec[0]) < 1e-6:
        vec[0] = 0.1
    return vec


@app.post("/v1/embeddings")
@app.post("/v1/v1/embeddings")
def embeddings() -> Response:
    payload = request.get_json(silent=True) or {}
    model = payload.get("model") or "text-embedding-3-small"
    raw_input = payload.get("input", "")

    if isinstance(raw_input, str):
        inputs: list[str] = [raw_input]
    elif isinstance(raw_input, list):
        inputs = [str(item) if not isinstance(item, str) else item for item in raw_input]
    else:
        inputs = [str(raw_input)]

    data = [
        {
            "object": "embedding",
            "index": i,
            "embedding": _deterministic_embedding(text),
        }
        for i, text in enumerate(inputs)
    ]
    total_tokens = sum(_estimate_tokens(text) for text in inputs)
    return jsonify(
        {
            "object": "list",
            "data": data,
            "model": model,
            "usage": {
                "prompt_tokens": total_tokens,
                "total_tokens": total_tokens,
            },
        }
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/healthz")
def healthz() -> Response:
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    sys.stderr.write(
        f"[mock-llm] listening on http://{HOST}:{PORT} "
        f"(fixtures: {FIXTURES_DIR})\n"
    )
    sys.stderr.flush()
    # threaded=True so that concurrent streaming + embeddings requests from
    # the Flask backend + Celery worker don't serialize behind each other.
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
