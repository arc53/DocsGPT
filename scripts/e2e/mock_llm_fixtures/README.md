# Mock LLM fixtures

This directory holds **canned OpenAI Chat Completions responses** keyed by a
SHA-256 fingerprint of the request. The stub server at
`scripts/e2e/mock_llm.py` looks up `<hash>.json` here for every
`POST /v1/chat/completions` request; if no fixture matches, the server returns
a generic deterministic fallback and logs the missing hash to stderr so you
can promote it into a fixture later.

Embeddings do not use fixtures — they are generated on the fly from a
hash-seeded RNG. Only chat completions are fixtured.

## Filename format

```
<sha256-hex>.json
```

The hash is a lowercase hex SHA-256 digest (64 characters, no prefix, no
extension beyond `.json`). Example:

```
3f5a7b9c...d12ef0.json
```

## How the hash is computed

The fingerprint covers only the fields that should control which canned answer
is returned:

```python
canonical = {
    "model":       payload.get("model"),
    "messages":    [minimal({role, content, name?, tool_call_id?, tool_calls?}) ...],
    "tool_choice": payload.get("tool_choice"),
}
blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
```

Notes:

- `temperature`, `top_p`, `seed`, `max_tokens`, `stream`, and any other
  sampling/transport knobs **do not influence the hash**. Streaming and
  non-streaming variants of the same request resolve to the same fixture.
- Message `content` is kept verbatim — if the app passes a list of content
  parts (vision / multi-modal), the list is hashed as-is.
- `tool_calls` on assistant messages and `tool_call_id` / `name` on tool
  messages are included because they change what the model is *replying to*.

The canonical source of the hashing logic is `_compute_request_digest` in
`scripts/e2e/mock_llm.py`. If you change that function, regenerate all
fixtures.

## Computing a fixture hash from the command line

The easiest path: run the e2e suite once with your new flow, grep stderr for
`[mock-llm] unknown fixture hash <hash>` along with the request dump on the
following line, and save the canned answer under `<hash>.json`. The up.sh log
tail preserves both lines.

If you need to compute a hash by hand from a request payload:

```python
# scripts/e2e/compute_hash.py (not committed; run ad hoc)
import hashlib, json, sys

payload = json.load(sys.stdin)
canonical = {
    "model": payload.get("model"),
    "messages": [
        {k: v for k, v in msg.items() if k in {"role", "content", "name", "tool_call_id", "tool_calls"}}
        for msg in payload.get("messages", [])
    ],
    "tool_choice": payload.get("tool_choice"),
}
blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
print(hashlib.sha256(blob.encode("utf-8")).hexdigest())
```

```bash
cat request.json | python scripts/e2e/compute_hash.py
```

## Fixture JSON schema

```json
{
  "request_digest": "<hash>",
  "description": "Human description of when this is used",
  "response": {
    "content": "The canned assistant text, may include markdown.",
    "tool_calls": null,
    "finish_reason": "stop",
    "usage": {"prompt_tokens": 12, "completion_tokens": 34}
  }
}
```

### Field reference

| Field | Type | Required | Notes |
|---|---|---|---|
| `request_digest` | string | no (documentation only) | Must match the filename. The loader does not re-verify this, it's here for human review. |
| `description` | string | no | Short note on what flow this covers — makes grepping fixtures easier. |
| `response.content` | string | yes (if no `tool_calls`) | The assistant's reply body. Plain text or markdown. Empty string is legal when `tool_calls` is set. |
| `response.tool_calls` | array \| null | no | OpenAI tool-call shape: `[{"id": "call_x", "type": "function", "function": {"name": "...", "arguments": "{...}"}}]`. Arguments must be a JSON **string**, not an object. |
| `response.finish_reason` | string | no (defaults to `"stop"`) | Use `"tool_calls"` when returning tool calls, `"length"` to simulate truncation. |
| `response.usage.prompt_tokens` | number | no | Used verbatim in the non-streaming envelope. Default: estimated from request messages. |
| `response.usage.completion_tokens` | number | no | Default: estimated from `content`. |

`response.usage.total_tokens` is always recomputed as the sum — do not set it.

### Streaming behavior

The stub handles streaming vs non-streaming transparently for both content
and tool-call fixtures:

- **Content fixtures** are split into ~5 SSE deltas by character length. Only
  the last delta carries `finish_reason`.
- **Tool-call fixtures** are emitted as a single delta containing the full
  `tool_calls` array, followed by a final empty delta carrying `finish_reason`.

No fixture change is needed to toggle between streaming and non-streaming;
the app's `stream=true` flag alone controls it.

## Tool-call example

```json
{
  "request_digest": "abc123...",
  "description": "Agent calls the weather tool for 'weather in London?'",
  "response": {
    "content": "",
    "tool_calls": [
      {
        "id": "call_e2e_weather_1",
        "type": "function",
        "function": {
          "name": "get_weather",
          "arguments": "{\"city\":\"London\"}"
        }
      }
    ],
    "finish_reason": "tool_calls"
  }
}
```

## Workflow for adding a fixture

1. Run the failing e2e spec. Watch `scripts/e2e/up.sh`'s log tail (or
   `/tmp/docsgpt-e2e/mock_llm.log` depending on how orchestration pipes it).
2. Find the `[mock-llm] unknown fixture hash <hash>` warning and the request
   dump on the following line.
3. Create `mock_llm_fixtures/<hash>.json` with the schema above.
4. Re-run the spec — the warning should disappear and the spec should pass.
5. Commit the fixture. Fixtures are checked into the repo so every developer
   and every CI run gets the same canned answers.

## Determinism guarantees

- Same request → same hash → same fixture → same response, always.
- No `time.time()`, no random seeds, no environment dependence in the hash.
- Embeddings are hash-seeded but never all-zero (the stub nudges the first
  component away from 0 if the seeded draw is near zero), so the vector store
  ingest path never rejects them.
