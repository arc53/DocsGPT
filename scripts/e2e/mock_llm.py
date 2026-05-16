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

Run standalone (does NOT import anything from ``application/``). Python 3.11+.
Flask is the only non-stdlib dependency and is already in
``application/requirements.txt``.

Usage::

    python scripts/e2e/mock_llm.py

Defaults to ``127.0.0.1:7899`` to match the ``OPENAI_BASE_URL`` referenced in
``e2e-plan.md`` Appendix A.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
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


def _resolve_chat_response(
    payload: dict[str, Any], digest: str
) -> tuple[str, list[dict[str, Any]] | None, str, dict[str, int]]:
    """Return ``(content, tool_calls, finish_reason, usage)`` for ``payload``.

    Looks up a fixture by digest first; falls back to the generic response if
    no fixture is present, and logs the miss so the dev can convert it.
    """

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

    if tool_calls:
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
