"""Mock OpenAI-compatible LLM server for benchmarking.

Fixed 5-second generation (100 tokens × 50 ms/token). No auth. Emits SSE
chunks in OpenAI's chat.completions streaming format, or a single response
when stream=false. Run on 127.0.0.1:8090 — point DocsGPT at it via
OPENAI_BASE_URL=http://127.0.0.1:8090/v1.
"""

import asyncio
import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

TOKEN_COUNT = 100
TOKEN_DELAY_S = 0.05  # 100 * 0.05 = 5.0 s

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

app = FastAPI()


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


async def _stream_response(model: str, req_id: str):
    completion_id = _token_stream_id()
    yield _sse_chunk(completion_id, model, {"role": "assistant", "content": ""})
    for i, tok in enumerate(FILLER_TOKENS[:TOKEN_COUNT]):
        await asyncio.sleep(TOKEN_DELAY_S)
        yield _sse_chunk(completion_id, model, {"content": tok})
    yield _sse_chunk(completion_id, model, {}, finish_reason="stop")
    yield "data: [DONE]\n\n"
    logger.info("[%s] stream done", req_id)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "mock")
    stream = bool(body.get("stream", False))
    req_id = uuid.uuid4().hex[:8]
    logger.info("[%s] /chat/completions stream=%s model=%s max_tokens=%s", req_id, stream, model, body.get("max_tokens"))

    if stream:
        return StreamingResponse(
            _stream_response(model, req_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    await asyncio.sleep(TOKEN_COUNT * TOKEN_DELAY_S)
    logger.info("[%s] non-stream done", req_id)
    text = "".join(FILLER_TOKENS[:TOKEN_COUNT])
    completion_id = _token_stream_id()
    return JSONResponse(
        {
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
        }
    )


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": "mock", "object": "model", "owned_by": "mock"}],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8090, log_level="info")
