"""Mock OpenAI-compatible LLM server for benchmarking.

Fixed 5-second generation (100 tokens × 50 ms/token). No auth. Emits SSE
chunks in OpenAI's chat.completions streaming format, or a single response
when stream=false. Run on 127.0.0.1:8090 — point DocsGPT at it via
OPENAI_BASE_URL=http://127.0.0.1:8090/v1.

Flags:
    --tool-calls   First response returns a tool call instead of text.
                   Subsequent responses (after a tool_result) return text.
                   Useful for triggering the tool-execution loop.
"""

import argparse
import json
import logging
import time
import uuid

from flask import Flask, Response, request, jsonify

TOKEN_COUNT = 100
TOKEN_DELAY_S = 0.05  # 100 * 0.05 = 5.0 s
TOOL_CALL_MODE = False

logger = logging.getLogger("mock_llm")
logging.basicConfig(level=logging.INFO, format="%(asctime)s mock: %(message)s")

FILLER_TOKENS = [
    "Lorem", " ipsum", " dolor", " sit", " amet", ",", " consectetur",
    " adipiscing", " elit", ".", " Sed", " do", " eiusmod", " tempor",
    " incididunt", " ut", " labore", " et", " dolore", " magna", " aliqua",
    ".", " Ut", " enim", " ad", " minim", " veniam", ",", " quis", " nostrud",
    " exercitation", " ullamco", " laboris", " nisi", " ut", " aliquip",
    " ex", " ea", " commodo", " consequat", ".", " Duis", " aute", " irure",
    " dolor", " in", " reprehenderit", " in", " voluptate", " velit",
    " esse", " cillum", " dolore", " eu", " fugiat", " nulla", " pariatur",
    ".", " Excepteur", " sint", " occaecat", " cupidatat", " non", " proident",
    ",", " sunt", " in", " culpa", " qui", " officia", " deserunt",
    " mollit", " anim", " id", " est", " laborum", ".", " Curabitur",
    " pretium", " tincidunt", " lacus", ".", " Nulla", " gravida", " orci",
    " a", " odio", ".", " Nullam", " varius", ",", " turpis", " et",
    " commodo", " pharetra", ",", " est", " eros", " bibendum", " elit",
    ".",
]

app = Flask(__name__)


def _token_stream_id() -> str:
    return f"chatcmpl-mock-{uuid.uuid4().hex[:12]}"


def _sse_chunk(completion_id: str, model: str, delta: dict, finish_reason=None) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n"


def _gen_tool_call_stream(model: str, req_id: str):
    """Emit two tool_calls (search) in streaming format.

    Two calls ensure the handler executes the first (which can return a
    huge result), then hits _check_context_limit before the second.
    """
    completion_id = _token_stream_id()
    call_id_1 = f"call_{uuid.uuid4().hex[:12]}"
    call_id_2 = f"call_{uuid.uuid4().hex[:12]}"

    yield _sse_chunk(completion_id, model, {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "index": 0,
                "id": call_id_1,
                "type": "function",
                "function": {"name": "search", "arguments": ""},
            },
            {
                "index": 1,
                "id": call_id_2,
                "type": "function",
                "function": {"name": "search", "arguments": ""},
            },
        ],
    })
    args_json = json.dumps({"query": "Python programming basics"})
    for ch in args_json:
        time.sleep(TOKEN_DELAY_S)
        yield _sse_chunk(completion_id, model, {
            "tool_calls": [
                {"index": 0, "function": {"arguments": ch}},
                {"index": 1, "function": {"arguments": ch}},
            ],
        })
    yield _sse_chunk(completion_id, model, {}, finish_reason="tool_calls")
    yield "data: [DONE]\n\n"
    logger.info("[%s] tool_call stream done (ids=%s, %s)", req_id, call_id_1, call_id_2)


def _has_tool_result(messages: list) -> bool:
    return any(m.get("role") == "tool" for m in messages)


def _gen_text_stream(model: str, req_id: str):
    completion_id = _token_stream_id()
    yield _sse_chunk(completion_id, model, {"role": "assistant", "content": ""})
    for tok in FILLER_TOKENS[:TOKEN_COUNT]:
        time.sleep(TOKEN_DELAY_S)
        yield _sse_chunk(completion_id, model, {"content": tok})
    yield _sse_chunk(completion_id, model, {}, finish_reason="stop")
    yield "data: [DONE]\n\n"
    logger.info("[%s] stream done", req_id)


@app.post("/v1/chat/completions")
def chat_completions():
    body = request.get_json(force=True)
    model = body.get("model", "mock")
    stream = bool(body.get("stream", False))
    messages = body.get("messages", [])
    tools = body.get("tools")
    req_id = uuid.uuid4().hex[:8]
    logger.info(
        "[%s] /chat/completions stream=%s model=%s tools=%s msgs=%d",
        req_id, stream, model, bool(tools), len(messages),
    )

    use_tool_call = (
        TOOL_CALL_MODE
        and tools
        and not _has_tool_result(messages)
    )

    if stream:
        gen = (
            _gen_tool_call_stream(model, req_id) if use_tool_call
            else _gen_text_stream(model, req_id)
        )
        return Response(
            gen,
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    time.sleep(TOKEN_COUNT * TOKEN_DELAY_S)
    logger.info("[%s] non-stream done", req_id)
    text = "".join(FILLER_TOKENS[:TOKEN_COUNT])
    completion_id = _token_stream_id()
    return jsonify({
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": TOKEN_COUNT,
            "total_tokens": 10 + TOKEN_COUNT,
        },
    })


@app.get("/v1/models")
def list_models():
    return jsonify({
        "object": "list",
        "data": [{"id": "mock", "object": "model", "owned_by": "mock"}],
    })


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tool-calls", action="store_true",
        help="First response returns a tool_call; subsequent responses return text.",
    )
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    TOOL_CALL_MODE = args.tool_calls
    if TOOL_CALL_MODE:
        logger.info("Tool-call mode enabled")
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)
