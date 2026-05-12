# Durability Options — Deep Dive

Companion to `durability-strategy.md`. Goes deeper per option: file-by-file integration with DocsGPT, gotchas, day-1/30/180 operational reality, production-user signal vs marketing, and code samples. Use the strategy doc for the recommendation; use this doc when evaluating an option seriously.

---

## Approach A — Status-quo-plus

The landed Tier 1 baseline. Tighten Celery, formalize idempotency, write-ahead the user's question, add three-phase tool-call audit, and run a reconciliation worker. Pure refactor, no new infrastructure, no new dependencies.

### The landed change set

Core files touched, three Alembic migrations, new durability tables, and follow-up lease / ingest-attempt refinements. Headlines:

**`application/celeryconfig.py`** — durability defaults at module scope:

```python
task_acks_late = True                        # don't ACK until task body returns
task_reject_on_worker_lost = True            # SIGKILL'd worker → re-queue
worker_prefetch_multiplier = 1               # avoid grab-4-then-crash redelivery
broker_transport_options = {"visibility_timeout": 7 * 3600}  # 7h, longer than longest task
result_expires = 86400 * 7                   # debug-grade retention
task_track_started = True                    # distinguish queued from executing
```

**`application/api/user/tasks.py`** — every long-running task gets retry policy + idempotency:

```python
DURABLE_TASK = dict(
    bind=True, acks_late=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
    retry_backoff=True,
)

@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="ingest")
def ingest(self, idempotency_key=None, **kwargs): ...
```

**`application/api/answer/services/conversation_service.py`** — split `save_conversation` into `save_user_question` (called *before* LLM) and `finalize_message` (called after). Add `status` column on `conversation_messages` (`pending|streaming|complete|failed`).

**`application/agents/tool_executor.py:267`** — three-phase pattern:

```python
def execute(self, tools_dict, call, llm_class):
    call_id = call.id
    self._record_attempt(call_id, status="proposed", ...)  # WAL
    try:
        result = tool.execute_action(...)
    except Exception as e:
        self._update_attempt(call_id, status="failed", error=str(e))
        raise
    self._update_attempt(call_id, status="executed", result=result)
    # finalize_message later flips to 'confirmed' after the assistant message commits
    return result
```

**`application/api/user/agents/webhooks.py:81`** — accept `Idempotency-Key` header; new `webhook_dedup` table. Same idempotency pattern at every external boundary.

**`application/usage.py`** — `token_usage` insert moves into the same transaction as `finalize_message`. Today it's a separate insert that silently swallows DB errors (`usage.py:118`).

**`application/api/answer/services/stream_processor.py:1027`** — stop the eager `cont_service.delete_state(...)`. Mark `status='resuming'` instead, delete only on completion. Reconciliation worker has a 10-minute grace before it touches `resuming` rows.

**`application/worker.py:agent_webhook_worker`** — currently returns `{"status": "error"}` instead of raising → Celery treats as success → no retry. Fix: raise on error.

**`application/worker.py:ingest_worker`** — derive `source_id` deterministically from idempotency_key (`uuid5(NS, key)`) instead of generating fresh inside the task. Without this fix, Celery `acks_late` retry creates a duplicate source.

### New tables (Migration `0004_durability_foundation.py`)

```sql
CREATE TABLE task_dedup (
    idempotency_key TEXT PRIMARY KEY,
    task_name TEXT NOT NULL,
    task_id TEXT NOT NULL,
    result_json JSONB,
    status TEXT NOT NULL,  -- pending|completed|failed
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE webhook_dedup (
    idempotency_key TEXT PRIMARY KEY,
    agent_id UUID NOT NULL,
    task_id TEXT NOT NULL,
    response_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE tool_call_attempts (
    call_id TEXT PRIMARY KEY,
    message_id UUID,  -- nullable until finalize
    tool_id UUID,
    tool_name TEXT NOT NULL,
    action_name TEXT NOT NULL,
    arguments JSONB NOT NULL,
    result JSONB,
    error TEXT,
    status TEXT NOT NULL CHECK (status IN ('proposed','executed','confirmed','failed')),
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE ingest_chunk_progress (
    source_id UUID PRIMARY KEY,
    total_chunks INT NOT NULL,
    embedded_chunks INT NOT NULL DEFAULT 0,
    last_index INT NOT NULL DEFAULT -1,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

ALTER TABLE conversation_messages
    ADD COLUMN status TEXT NOT NULL DEFAULT 'complete'
        CHECK (status IN ('pending','streaming','complete','failed')),
    ADD COLUMN request_id TEXT;
```

### A `@durable_step` helper? — verdict: no

The pattern repeats but the shapes don't actually match: `tool_call_attempts` has a 3-state machine, `ingest_chunk_progress` is a counter, `task_dedup` is a key-value cache. A decorator would either be too narrow or so generic it's just `try/except + INSERT`. Inline 6-line WAL is grep-able; the decorator hides the table name and complicates "why is this row stuck?" debugging. **Approach A is explicitly the "no new abstractions" path** — building a knockoff of `@DBOS.step()` that gets thrown out in 6 months is wasted work.

### Reconciliation worker

Runs every 30s via celery-redbeat. Five sweeps, using `FOR UPDATE SKIP LOCKED` where rows need to be claimed:

- **Q1**: `conversation_messages.status IN ('pending','streaming') AND timestamp < now() - 5min` — message stuck mid-stream. Action: bump retry count; after 3 attempts mark `failed`, emit alert. Skip rows whose conversation has `pending_tool_state.status='resuming' AND resumed_at > now() - 10min` (active resume).
- **Q2**: `tool_call_attempts.status='proposed' AND attempted_at < now() - 5min` — side effect MAY or MAY NOT have happened (crashed between WAL write and call). Mark `failed`, emit alert. Cannot retry safely without knowing.
- **Q3**: `tool_call_attempts.status='executed' AND updated_at < now() - 15min` — side effect likely happened, but the assistant message never confirmed it. Mark `failed`, emit alert, and require operator/manual cleanup where the external system needs it.
- **Q4**: `ingest_chunk_progress.last_updated < now() - 30min AND embedded_chunks < total_chunks` — ingest heartbeat stalled. Emit alert and bump `last_updated` so the same row does not alert every tick.
- **Q5**: `task_dedup.status='pending' AND lease_expires_at` is expired after the retry budget — idempotency lease was abandoned. Mark `failed`, clear the lease, emit alert.

Threshold rationale: 5 min for proposed (long calls are abnormal); 15 min for executed (avoid touching live work — pending_tool_state TTL is 30 min).

### Day-to-day operations (real SQL)

**"User reports their question disappeared":**
```sql
SELECT id, conversation_id, status, prompt, timestamp,
       message_metadata->>'error' AS error
FROM conversation_messages
WHERE user_id = :u AND timestamp > now() - interval '1 hour'
ORDER BY timestamp DESC LIMIT 20;
```
Three outcomes: `complete` (rendering bug), `failed` (read the error), no row (request never reached the route).

**"Webhook agent run is stuck":**
```sql
SELECT idempotency_key, agent_id, task_id, created_at
FROM webhook_dedup WHERE agent_id = :id ORDER BY created_at DESC LIMIT 10;
```
Then `celery inspect query_task <task_id>`; if hung, `celery control revoke <task_id> --terminate`.

**"Cancel an in-flight ingest eating the queue":**
```sql
SELECT source_id, total_chunks, embedded_chunks, last_index, last_updated
FROM ingest_chunk_progress
WHERE last_updated > now() - interval '1 hour'
  AND embedded_chunks < total_chunks;
```
`celery control revoke`. On retry the per-chunk checkpoint resumes from `embedded_chunks + 1`. No re-embedding spend.

**"Postgres failed over":** Celery tasks mid-`_record_attempt` get `OperationalError`. `acks_late` keeps them on the queue; `autoretry_for=(Exception,)` retries them after 60s. HTTP requests in flight return 503; client retries with same `Idempotency-Key` and dedup table prevents double-execution. Manual: drain stale connection pool with 5 health-check hits.

**"Deploy mid-stream":** Old workers drain. `task_reject_on_worker_lost=True` re-queues unfinished tasks. New workers pick up; `task_dedup` short-circuits if old worker finished. SSE clients see disconnect; `complete_stream`'s `GeneratorExit` branch fires `finalize_message` with the partial response — question + partial answer preserved.

### Hard parts and gotchas (the brutally honest list)

1. **Three-phase tool calls when phase 3 fails after side effect succeeds.** Worker executes Telegram → message sent → status='executed' → `finalize_message` crashes → reconciler 15 min later sees executed-not-confirmed → marked `failed`, alert emitted. **The Telegram message was sent, the user may have no matching record in DocsGPT.** This inconsistency A cannot fully prevent. Mitigations: 15-min window catches it quickly; alert means we *know* about it, unlike today; operators can reconcile external state manually when needed.

2. **`pending_tool_state` 30-min TTL.** Today the user who returns to approve a tool call at minute 31 finds the state gone ("session expired"). A doesn't fundamentally fix this — extending TTL to 4h is the v1 answer; long-horizon human-in-loop is exactly the canonical DBOS use case.

3. **`acks_late` + poisoned message → infinite retries.** A task body that triggers SIGKILL re-queues forever. Celery's `max_retries=3` doesn't count worker-loss as an attempt. Use `task_dedup` as a poor-man's circuit breaker: on each replay, check `attempt_count >= 5` and early-return without invoking the body.

4. **Idempotency key when input has a server-generated UUID.** `ingest_worker` historically generated `id = uuid.uuid4()` *inside* the task. Without changes, Celery retry creates a *second* source with a different UUID. Fix: derive `source_id = uuid5(NAMESPACE, idempotency_key)`.

5. **JSONB schema migrations.** A migration that renames a key inside `agent_config` breaks every in-flight `pending_tool_state` row. Strategy: never rewrite in-flight JSONB. New columns added with default empty-blob; old keys are READ-tolerant for one release cycle (`COALESCE(agent_config->>'new_key', agent_config->>'old_key')`); cleanup in the next release.

6. **Two workers grab the same row.** `FOR UPDATE SKIP LOCKED` saves us *if* both workers are inside an open txn at lock time. The race that breaks it: worker A reads (no FOR UPDATE), starts long operation, doesn't yet write; reconciler also reads, escalates; both write. Bounded by the 5-min threshold and `WHERE status='proposed'` clause on the worker's update (no-op if reconciler beat it).

### What A explicitly does NOT solve

- **Multi-step workflows where step N depends on step N-2.** A doesn't add cross-step primitives; you'd store everything in `pending_tool_state.messages` and replay from the top.
- **Long-horizon human-in-loop pauses (>30 min).** Discussed above. Real answer is `DBOS.recv()`.
- **Workflow-to-workflow signals.** The reminder feature gets its own table. For 5 features each needing this, you re-implement DBOS step-channels in 5 different shapes.
- **Replay debugging.** A doesn't give you "rerun yesterday's conversation with mocked LLM."
- **Throughput ceiling.** Works to ~10K concurrent durable runs; at ~50K, `task_dedup` PK lookups become a hot row.

The honest line: **A buys you per-step durability for currently-running tasks, not multi-actor coordination across time.** The reminder feature crosses this line; everything else in the strategy doc lives below it.

### Realistic timeline (one engineer, three weeks)

| Week | Ships | Highest risk |
|---|---|---|
| 1 | Celery durability defaults, migration 0004, `with_idempotency` decorator, all 10 task entry points, webhook + upload `Idempotency-Key`, `agent_webhook_worker` raise-on-error, unit tests | `worker_prefetch_multiplier=1` regression on short-task throughput; ship behind feature flag |
| 2 | `save_user_question` + `finalize_message` split, `complete_stream` restructure, `usage.py` transactional, `reconciliation_worker`, integration tests for kill-mid-stream | `complete_stream` rewrite touches highest-traffic path; roll out behind `ENABLE_PRE_PERSIST=true` env flag |
| 3 | Three-phase pattern in `tool_executor`, `pending_tool_state` resuming flow, `ingest_worker` chunk checkpoint, runbook, chaos test | `tool_executor.execute` signature change ripples to research/agentic agents |

Honest: a *very* careful engineer ships in 3 weeks. A typical engineer slips to 4. Anyone in 1 week is cutting tests.

### Migration to DBOS later — what survives

| Artifact | Fate under DBOS | Notes |
|---|---|---|
| `task_dedup` table | Replace | DBOS has built-in `idempotency_key` on `start_workflow` |
| `tool_call_attempts` | **Keep** | Per-tool audit log is independently valuable; refit so writes go inside `@DBOS.step()` |
| `webhook_dedup` | Replace | Same reason as `task_dedup` |
| `ingest_chunk_progress` | Replace mostly | Becomes per-chunk `@DBOS.step()` calls |
| `conversation_messages.status` | **Keep** | Domain state, not workflow state |
| `pending_tool_state.status` + `resumed_at` | Replace | Whole table goes away; `DBOS.recv()` replaces the pause/resume pattern |
| `with_idempotency` decorator | Replace | Direct map to DBOS's `idempotency_key` parameter |
| `reconciliation_worker` | Mostly retire | DBOS has `recover_pending_workflows()`; keep the `tool_call_attempts` portion |
| `complete_stream` pre-persist split | **Keep, refit** | Becomes the first/last `@DBOS.step()` |
| Celery `acks_late` config | **Keep for tasks staying on Celery** | Ingestion + sync + attachments + MCP OAuth stay on Celery |
| `Idempotency-Key` HTTP plumbing | **Keep** | DBOS reads the same key parameter; rewire from decorator to `start_workflow` |

**Worst-case wasted work: 2-3 engineer-days out of a 3-week sprint (~15%).** The other 85% is structurally good even after DBOS.

---

## Approach B — In-house PG workflow engine

Build a small `@workflow_step` framework + `durable_runs/durable_steps` tables ourselves. DBOS-shaped but homegrown.

### Schema (full)

```sql
CREATE TABLE durable_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','running','paused','completed','failed','cancelled')),
    input JSONB NOT NULL,
    output JSONB,
    error JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    resume_after TIMESTAMPTZ,
    user_id TEXT NOT NULL,
    heartbeat_at TIMESTAMPTZ,
    worker_id TEXT
);

CREATE INDEX idx_durable_runs_status_resume ON durable_runs (status, resume_after)
    WHERE status IN ('pending','paused');

CREATE TABLE durable_steps (
    run_id UUID NOT NULL REFERENCES durable_runs(id) ON DELETE CASCADE,
    step_idx INT NOT NULL,
    name TEXT NOT NULL,
    input_hash TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending','running','completed','failed')),
    output JSONB,
    error TEXT,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    PRIMARY KEY (run_id, step_idx)
);

CREATE TABLE durable_streams (
    run_id UUID NOT NULL REFERENCES durable_runs(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    offset_no BIGINT NOT NULL,
    value JSONB NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, key, offset_no)
);
```

### Decorator + runtime

```python
# application/durable/inhouse.py
def workflow(name: str):
    def decorator(fn):
        _registry[name] = fn
        return fn
    return decorator

def workflow_step(name: str):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            run_id = _current_run.get()
            step_idx = _next_step_idx(run_id)
            existing = _read_step(run_id, step_idx)
            if existing and existing["status"] == "completed":
                return existing["output"]  # replay short-circuit
            _record_step(run_id, step_idx, name, status="running")
            try:
                output = fn(*args, **kwargs)
            except Exception as e:
                _update_step(run_id, step_idx, status="failed", error=str(e))
                raise
            _update_step(run_id, step_idx, status="completed", output=output)
            return output
        return wrapper
    return decorator
```

Plus `sleep(seconds)` (write `resume_after = now() + seconds`, status=`paused`, return), `read_stream`/`write_stream` via LISTEN/NOTIFY, runner that drains `durable_runs WHERE status='pending' AND resume_after IS NULL OR resume_after <= now() FOR UPDATE SKIP LOCKED`, beat poller every 30s.

### Honest assessment of in-house

**Engineer-months to reach ~80% of DBOS quality:**

| Component | Effort |
|---|---|
| Schema + decorator + runner + beat poller + sleep + basic stream | 1 week (v0) |
| Workflow recovery on app restart (heartbeat scan + requeue) | 3 days |
| Idempotent step retry with exponential backoff | 2 days |
| Per-tool side-effect policy and audit semantics | 1 week (genuinely tricky) |
| Stream replay from a cursor (so SSE refresh works) | 3 days |
| LISTEN/NOTIFY scaling (batching for high-volume token streams) | 3-5 days |
| Workflow versioning across deploys | 2 weeks minimum |
| Inspect-runs UI (DBOS has Conductor; you'd build basic table view) | 1-2 weeks |
| Observability (OTel spans per step) | 3 days |
| Test suite exercising crash-mid-step semantics | 1 week |

**Realistic total: 2-3 engineer-months for a credible 80%-DBOS-quality v1**, then ongoing maintenance burden of ~10-20% of one engineer indefinitely.

**Long-tail bug surface (real things that will bite):**
- Concurrent execution of the same run by two workers if heartbeat-recovery races
- Replay failures on workflow code changes (Temporal solves with worker-versioning; you don't have that)
- Step-input serialization edge cases (JSONB doesn't roundtrip Python `datetime`, `Decimal`, custom classes losslessly)
- LISTEN/NOTIFY connection lifecycle (one PG connection per consumer; pool exhaustion at concurrency)
- Stream chunk loss if a writer dies between INSERT and NOTIFY (fixable: flush on commit hook)
- Replay determinism — `random()` and `datetime.now()` calls in workflow body break replay

**When in-house is actually right:**
1. Hard organizational constraint forbids new dependencies in critical-path code (real but narrow)
2. Exotic semantics that DBOS doesn't support (e.g., per-step multi-database transactions)
3. **You already have 80% of this** — DocsGPT's `pending_tool_state` + `continuation_service` *is* a partial in-house engine. Generalizing it to a `durable_steps` table is exactly the Status-Quo-Plus path

**The pragmatic line:** build only the subset that maps to existing concepts (`pending_tool_state` → `durable_steps` rename + `status` column). Don't build the full engine. The full engine is a 2-3 month detour to land at "we built our own DBOS, badly, that we now maintain forever."

---

## Approach C — DBOS in DocsGPT

The recommended engine pick. Library, no new infra, native streaming primitive, scheduled wake-up in 3 lines. This section is the integration design.

### Concrete integration with the agent loop

Today: `BaseAgent.gen()` is a Python generator yielding `Dict` events directly to `complete_stream`'s SSE.

In DBOS: **a workflow body cannot itself be a generator that yields to a caller.** Workflow runs to completion durably; events flow over `write_stream`. The rewrite:

```python
# application/agents/dbos_workflows.py (NEW)
from dbos import DBOS

EVENTS_STREAM = "events"

@DBOS.step(retries_allowed=True, max_attempts=3, interval_seconds=2.0, backoff_rate=2.0)
def llm_chunk_step(*, workflow_id: str, messages: list, model_id: str, ...) -> dict:
    # one LLM call returning {"text": "...", "tool_calls": [...]}
    ...

@DBOS.step()
def execute_tool_step(*, call_id: str, tool_name: str, action: str, args: dict) -> dict:
    # returns the tool result; audit row records proposed/executed/confirmed state
    ...

@DBOS.workflow()
def agent_workflow(*, request_data, decoded_token, question, conversation_id):
    # Build agent context (DB reads → step)
    setup = build_agent_step(request_data=request_data, decoded_token=decoded_token,
                             question=question, conversation_id=conversation_id)
    messages = setup["messages"]
    while True:
        chunk = llm_chunk_step(workflow_id=DBOS.workflow_id,
                               messages=messages, model_id=setup["model_id"], ...)
        DBOS.write_stream(EVENTS_STREAM, {"answer": chunk["text"]})
        if not chunk["tool_calls"]:
            break
        for tc in chunk["tool_calls"]:
            if requires_approval(tc):
                DBOS.write_stream(EVENTS_STREAM, {"pending_tool": tc})
                decision = DBOS.recv("approval", timeout_seconds=24*3600)
                if not decision or decision == "denied":
                    DBOS.write_stream(EVENTS_STREAM, {"tool_skipped": tc["call_id"]})
                    continue
            result = execute_tool_step(call_id=tc["call_id"], tool_name=tc["tool"],
                                       action=tc["action"], args=tc["args"])
            DBOS.write_stream(EVENTS_STREAM, {"tool_result": result})
            messages.append({"role": "tool", "tool_call_id": tc["call_id"],
                             "content": str(result)})
    DBOS.write_stream(EVENTS_STREAM, {"sources": setup.get("sources", [])})
    DBOS.close_stream(EVENTS_STREAM)
    return {"final": chunk["text"], "tool_calls": [...]}
```

The route handler:

```python
# application/api/answer/routes/base.py — REWRITTEN complete_stream
def complete_stream(request_data, decoded_token, question, conversation_id):
    handle = DBOS.start_workflow(
        agent_workflow,
        request_data=request_data, decoded_token=decoded_token,
        question=question, conversation_id=conversation_id,
        idempotency_key=request_data.get("request_id"),
    )
    def sse_generator():
        for event in DBOS.read_stream(handle.workflow_id, EVENTS_STREAM):
            yield f"data: {json.dumps(event)}\n\n"
        # workflow done — flush any final state
        result = handle.get_result()
        yield f"data: {json.dumps({'done': True, 'result': result})}\n\n"
    return Response(sse_generator(), mimetype="text/event-stream")
```

### Pause-on-tool-approval — the death of `pending_tool_state` + `ContinuationService`

Today: `pending_tool_state` (30-min TTL via PG row), `ContinuationService.save_state` persists the agent + messages + tool_calls + tools_dict; `StreamProcessor.resume_from_tool_actions` rebuilds the agent from saved state on user approval.

In DBOS: `DBOS.recv()` *is* the pause primitive. The workflow waits durably; another HTTP call from the user invokes `DBOS.send(workflow_id, "approval", decision)`. No external state to persist — the workflow's variables are the state.

```python
# Resume route (much smaller than today's StreamProcessor.resume_from_tool_actions)
@bp.post("/api/answer/resume/<workflow_id>")
def resume_workflow(workflow_id):
    decision = request.json.get("decision")  # "approved" | "denied"
    DBOS.send(workflow_id, "approval", decision)
    handle = DBOS.retrieve_workflow(workflow_id)
    return Response(
        (f"data: {json.dumps(e)}\n\n" for e in DBOS.read_stream(workflow_id, EVENTS_STREAM)),
        mimetype="text/event-stream",
    )
```

What survives, what dies:

| Today | After DBOS |
|---|---|
| `pending_tool_state` table | Gone. DBOS state machine replaces it. |
| `ContinuationService.save_state/load_state/delete_state` | Gone. `DBOS.recv()` is the API. |
| `StreamProcessor.resume_from_tool_actions` (~150 lines) | Becomes ~10 lines that call `DBOS.send` |
| 30-min TTL janitor | Gone. `recv` timeout is per-call. |
| The "session expired" UX | Gone — set timeout to 24h or longer per-feature |

**Migration cutover:** for in-flight `pending_tool_state` rows, run both code paths in parallel for one TTL window (30 min). New runs use DBOS; existing rows drain through the legacy path. Remove legacy after the window.

### Source ingestion as a DBOS workflow

Today: `ingest_worker` is one Celery task with `tempfile.TemporaryDirectory()` holding all chunks. Crash mid-embed = restart from scratch.

In DBOS:

```python
@DBOS.workflow()
def ingest_workflow(*, source_id, file_paths, ...):
    parsed = parse_files_step(source_id=source_id, file_paths=file_paths)
    chunks = chunk_documents_step(source_id=source_id, parsed=parsed)
    for batch_idx, batch in enumerate(_batches_of_50(chunks)):
        embed_chunk_batch_step(source_id=source_id, batch_idx=batch_idx, chunks=batch)
    register_source_step(source_id=source_id, total_chunks=len(chunks))
    return {"source_id": source_id, "chunks": len(chunks)}

@DBOS.step(retries_allowed=True, max_attempts=5)
def embed_chunk_batch_step(*, source_id, batch_idx, chunks): ...
```

Crash recovery: each step's output cached in `dbos.operation_outputs`. Worker restart → recovery scans pending workflows → resumes at first non-completed step. A 30-min embed that crashes at chunk 8000/10000 picks up at batch_idx=160, not from scratch.

### Streaming throughput — what's confirmed vs inferred

**Confirmed from docs:**
- Stream values land in `dbos.streams(workflow_uuid, key, value, offset, function_id)` ([source](https://docs.dbos.dev/explanations/system-tables))
- `read_stream` returns `Generator[Any, Any, None]`
- Exactly-once from workflow body, at-least-once from steps
- Stream auto-closes when workflow terminates (SUCCESS/ERROR/CANCELLED)

**Inferred / not officially documented:**
- **Persistence mechanism: almost certainly polling** (`SELECT ... WHERE offset > :last`), not LISTEN/NOTIFY (docs would be loud about NOTIFY; they're not). Expect 50-200ms baseline latency per token, dominated by polling interval. **Substantially higher than today's direct-yield SSE** where the only delay is OpenAI → Flask → browser.
- **Throughput: ~5K writes/sec/PG before contention.** The "40K workflows/sec" claim is workflow-level, not stream-level.
- **Consumer disconnect: workflow keeps running**, writing to PG. Reconnecting consumer can re-`read_stream` from the beginning (or saved cursor). Strictly better than today's `GeneratorExit` partial-save.
- **Multi-consumer: yes** — `read_stream` is a SQL query keyed by workflow + key. Two browser tabs both reading the same workflow's stream is supported by construction.
- **Reconnect with cursor: not exposed in 2.19.0 public API.** Each `read_stream` call starts from offset 0; you'd track seen `seq` IDs at the consumer and dedupe, or drop down to raw SQL.

**Implication for DocsGPT:** streaming will get slower per-token (~50-200ms added). For UX this is invisible. For PG growth: ~2KB per token × tokens-per-conversation × conversations-per-day. **Mitigation:** write tokens in chunks of 5-10 (one sentence at a time) instead of token-by-token; perceived UX barely changes; PG row count drops 5-10×.

### Hard parts — line-by-line audit of what becomes a step

`AgenticAgent._gen_inner` is short. Every line that has to move into a step:

```python
def _gen_inner(self, query, log_context):
    tools_dict = self.tool_executor.get_tools()       # DB read → STEP
    add_internal_search_tool(tools_dict, ...)         # mutation; safe in body
    self._prepare_tools(tools_dict)                   # in-memory → safe
    messages = self._build_messages(self.prompt, query)  # in-memory → safe
    llm_response = self._llm_gen(messages, log_context)  # LLM → STEP
    yield from self._handle_response(...)             # → STEP
    yield {"sources": self.retrieved_docs}            # → write_stream
```

Less obvious non-deterministic operations:
- `uuid.uuid4()` in `_build_messages` (`base.py:436`) — generates `call_id` for legacy tool calls. Move to step or pre-compute at workflow start.
- `_calculate_current_context_tokens` calls `TokenCounter` — DB read, wrap in step.
- `get_token_limit(...)` in `_llm_gen` — DB lookup. Step or read-once-at-workflow-start.

The "wrap the agent body in `@DBOS.workflow()`" sketch in the strategy doc under-estimates this. **Plan ~2 weeks just for the agent loop migration done correctly, with tests.**

### Other gotchas

- **Workflow versioning + patching.** DBOS hashes `application_version` (git SHA) per workflow. v2 deploys with v1 in flight → v1 stays PENDING until old executor recovers it or you `DBOS.fork_workflow` onto v2. **Don't break step signatures.** Adding new steps is fine; removing or renaming is dangerous. Treat step name + argument shape as a wire protocol.
- **Step input hashing.** Cache key is `(workflow_uuid, function_id)` — function_id is **position in the workflow body**. `Pydantic` models with `Field(default_factory=lambda: datetime.now())` → fresh value on replay → mismatch. Always serialize args via `model_dump_json` and avoid mutable default factories. Treat all step inputs as immutable.
- **Postgres failover with async replication = data loss.** [HN warning](https://news.ycombinator.com/item?id=42379974): "Failover with some data loss happened to me twice." Run PG with `synchronous_commit=on` and `synchronous_standby_names` configured, OR design steps to be idempotent (deterministic IDs, upserts not inserts). True for any durability layer; DBOS isn't unique.
- **The "stuck workflow" debugging story.** Walk `dbos.workflow_status` directly:
  ```sql
  SELECT workflow_uuid, status, name, created_at, updated_at, executor_id, error
  FROM dbos.workflow_status WHERE workflow_uuid = '...';
  
  SELECT function_id, function_name, output, error
  FROM dbos.operation_outputs WHERE workflow_uuid = '...' ORDER BY function_id;
  ```
  CLI: `dbos workflow list --status PENDING`. Free Conductor UI surfaces all of this. **Hard case:** workflow at `recv()` waiting for a notification that will never come. Looks identical to a healthy paused workflow. Only signal is the `recv` timeout. Add a custom log line at `recv` start ("waiting for approval, timeout in 24h") for searchable traces.
- **Two-database model.** Run DBOS state in a separate logical PG database (not just schema): `system_database_url` separate from app DB. DBOS does many writes per workflow; co-location causes autovacuum competition.
- **Sentry/Prometheus/OTel:** OTel native + automatic (workflow = span, step = child span). Sentry indirect via OTLP collector → Sentry's OTLP endpoint. Prometheus = roll your own SQL scraper or OTel metrics path.

### Test story

```python
# tests/conftest.py
@pytest.fixture(autouse=True)
def reset_dbos():
    DBOS.destroy()
    DBOS(config={
        "name": "docsgpt-test",
        "system_database_url": "sqlite:///./.test-dbos.sqlite",
    })
    DBOS.reset_system_database()
    DBOS.launch()
    yield
    DBOS.destroy()

# tests/test_agent_workflow.py
def test_agent_workflow_basic():
    with patch("application.agents.dbos_workflows.llm_chunk_step",
               return_value={"text": "hello", "tool_calls": []}):
        handle = DBOS.start_workflow(agent_workflow, ...)
        result = handle.get_result()
        assert result["final"] == "hello"

def test_recovery_skips_completed_steps():
    # DBOS.fork_workflow lets you replay from any step
    h2 = DBOS.fork_workflow(h1.workflow_id, start_step=2)
```

`unittest.mock.patch` works because steps are ordinary Python functions. SQLite test backend supported.

### Day-1 / Day-30 / Day-180 experience

**Day 1.** `pip install dbos`. In `application/dbos_init.py`:
```python
from dbos import DBOS, DBOSConfig
DBOS(config={
    "name": "docsgpt",
    "system_database_url": settings.DBOS_POSTGRES_URI,
    "enable_otlp": settings.DBOS_OTEL_ENABLED,
})
DBOS.launch()
```

First error: `relation "dbos.workflow_status" does not exist`. Fix: `DBOS.launch()` auto-creates if it has CREATE rights (production-locked DBs may need pre-provisioning). 

Second pitfall: **Flask vs FastAPI.** Docs assume FastAPI. Library works in Flask but you need `DBOS.launch()` exactly once before any worker process forks. With `gunicorn --preload` straightforward; without preload, each worker calls `DBOS.launch()` independently → connection thundering. Reference: existing `worker_process_init.connect` pattern in `celery_init.py:34`.

Third pitfall: **`@DBOS.workflow()` decorated functions must be importable at registry time.** Lazy imports inside route handlers won't work — DBOS scans the module to register the workflow. Put workflow definitions in top-level `application/dbos_workflows/__init__.py` imported during app boot.

**Day 30.** Deploying changes — v2 workflow with v1 in flight. v1 resumes on v2 executors *if signature-compatible*. Otherwise stay PENDING until `DBOS.fork_workflow(...)`. Discipline required: append-only changes to step signatures. Migration adding a step in the middle is dangerous (function_id positions shift). Watch `dbos.streams` and `dbos.operation_outputs` row growth. Set `workflow_retention_seconds=30 days`; run `dbos workflow gc` weekly.

**Day 180.** Likely surprises:
- **PG bloat from streams.** If you didn't move to chunked writes, `dbos.streams` is by far the largest table. Vacuum costs become noticeable.
- **The "ghost paused workflow" backlog.** Users start a chat, hit tool approval, never approve. With 24h `recv` timeout, you accumulate tens of thousands of `PENDING` rows. Retention sweep catches them; you'll see count grow before stabilizing.
- **Versioning fatigue.** Every step-signature change → bump workflow version, drain old, or live with breaking-change risk. Teams converge on bumping versions liberally — leaves long tail of dead workflow definitions.
- **Conductor temptation.** Free Conductor is genuinely useful. Team wants Pro tier ($99/mo) for retention beyond free tier window.
- **The "agent did the wrong thing yesterday" wins.** This is the durability payoff. Team stops apologizing for "we can't reproduce it."

### Production users — real vs marketing

- **[Dosu](https://dosu.dev/blog/migrate-celery-to-dbos-dosu)** — concrete case: 20K workflows/hour, RAG ingestion pipelines, Celery → DBOS migration. **Real and detailed.** They hit Celery's orchestration/observability bottleneck and migrated for code clarity + dashboard, not just durability. **No specific war stories surfaced** — yellow flag (every migration has war stories).
- **Supabase partnership** — ships a "DBOS on Supabase" template. Partnership marketing, not necessarily "Supabase is running DBOS in production."
- **Yutori (autonomous web agents), TMG.io, Ontologize** — named in DBOS marketing. Yutori most-quoted; case study link 404'd at time of research. Treat as "named user, public claim, depth unverified."
- **Pydantic AI integration** — ships, well-documented, but article notes streaming isn't a focus.
- **OpenAI Agents SDK + DBOS** — package exists. Same caveat: shipped library, no public production-scale users surfaced.

**Honest assessment:** named-customer signal is **thinner than the marketing implies**. Dosu is the one I'd bet is genuinely production-scale. Everything else is "company X has tried it and shipped a blog post." MIT license is the safety net.

GitHub repo health (April 2026): 1,301 stars, 5 open issues, v2.19.0 released April 22 (every ~2 weeks). Open issues are feature requests, not data-loss bugs.

### Performance & resource overhead

| Metric | Value | Source |
|---|---|---|
| Per-step overhead vs raw function call | ~1-5ms (one PG insert + one read) | Inferred — no public benchmark |
| Workflow throughput ceiling (single PG) | 40K workflows/sec quoted | DBOS marketing; no methodology published |
| Memory footprint of DBOS runtime | ~10-20MB baseline in process | Inferred from library size |
| Streaming throughput | Unbenchmarked publicly | Estimated ~5K writes/sec/PG |
| Disk usage growth | ~2KB per step + ~1KB per stream value | Approximated from schema row sizes |
| GC story | `workflow_retention_seconds` config; `dbos workflow gc` CLI | Configuration docs |

**Practical sizing for DocsGPT:** at 1K conversations/day, ~30K stream rows/day = ~30MB/day raw, ~5MB/day after compression. At 30-day retention, ~150MB stream table. Workflow status + step outputs add ~10MB/day. **Trivial PG load** — `db.t3.small` would handle this for years. Flip happens at ~100K conversations/day or research-agent flows with hundreds of steps.

### Exit story

If DocsGPT wants to stop using DBOS in 18 months:
- **Tables created:** `dbos.workflow_status`, `dbos.operation_outputs`, `dbos.notifications`, `dbos.workflow_events`, `dbos.streams`, `dbos.application_versions`, `dbos.workflow_schedules`. All readable with raw SQL.
- **Format:** workflow inputs/outputs serialized — by default JSON for primitives, **pickled for complex Python objects.** Pickle is not portable. For clean-exit portability, set `serialization_type=WorkflowSerializationFormat.PORTABLE` on every workflow.
- **In-flight migration:** drain to zero, then rip. Stop accepting new workflows; let existing complete or time out; once `SELECT COUNT(*) FROM dbos.workflow_status WHERE status='PENDING'` hits zero, drop schema.
- **"Emit checkpoints but don't orchestrate" mode:** doesn't exist.

The MIT license is the real exit story: even if DBOS Inc. disappears, library still works, data is in your PG, fork the repo. Cleanest exit posture in the durability-engine survey.

### Final honest take on DBOS

DBOS is the right adopt-an-engine pick for DocsGPT — but three things to flag:

1. **The streaming primitive is the deciding factor, but it's not free.** Per-token PG writes add latency and disk growth. Mitigate with chunked writes. Don't assume parity with today's direct-yield SSE.
2. **Determinism is contagious.** Every line of `_gen_inner`, `_build_messages`, `_llm_gen` needs an audit. Plan ~2 weeks just for the agent loop migration done correctly, with tests.
3. **Production-user signal is thinner than the marketing.** Dosu is real. The rest is named-but-unverified. **Ship behind a feature flag, run for 90 days, then commit.**

The reminder feature in DBOS truly is ~20 lines of new code (`ScheduledActionTool` + `reminder_workflow`), validating the engine choice for the immediate ask. Agent-loop and ingestion migrations are larger projects needing their own sequencing.

---

## Approach D — Alternative engines

### D1. Temporal — deep dive

**Day 1.** `pip install temporalio`. Dev: `temporal server start-dev` (single Go binary). Production: spin up Postgres + 4 Temporal Service components (Frontend, History, Matching, Worker) typically via Helm or `docker-compose-postgres.yml`.

First errors a developer hits:
- Workflow tries to call `requests.get(...)` → sandbox rejects as non-deterministic. Move to activity.
- Workflow uses `datetime.now()` → use `workflow.now()`.
- Workflow imports a module that does I/O at import time. Gate the import.

Time to "hello world": ~2 hours if you've used Temporal before, ~1-2 days if you haven't. Time to "first Flask integration": another ~1 day (Flask is sync, Temporal workers async — `asyncio.run()` wrapper or move to FastAPI).

**Day 30.** Deployments. Temporal's worker-versioning is its own subsystem — tag workers with build IDs and route workflow tasks to compatible workers. If you don't, you're patching workflows by hand with `workflow.patched("my-fix-v2")` branches that stay forever. Temporal docs: "if you made a version-incompatible change to your Workflow, and you want to roll back, it's not possible to patch it."

Operational pains:
- Workflow code is "trapped" — can't refactor freely because in-flight workflows replay against new code and break on determinism mismatches
- Activity timeouts have to be tuned per-activity; default is no timeout (wrong); overshooting causes phantom retries that bill OpenAI twice

**Day 180.** Replit's coding agent runs on Temporal at large scale. OpenAI Agents SDK has GA Temporal integration since 2026-03-23. Per Zylos research: Temporal's named users include OpenAI, Snap, Netflix, JPMorgan Chase. Themes from production users:
- "It's the database for our control plane" — audit log of every workflow execution is the moat
- Operational cost is real but predictable; once past initial learning curve, stops biting you new ways
- **Streaming is the sore thumb.** OpenAI integration README literally says: *"This integration does not presently support streaming."* You build a Redis pub/sub bridge and live with the duct tape forever

**Streaming on Temporal — the actual code.** [Architectingbytes](https://www.architectingbytes.com/posts/temporal-redis-sse) documents it. The pattern: activity runs the agent and `XADD`s tokens to a Redis Stream; Flask SSE generator `XREAD`s. Six failure modes (without trying hard):

1. Activity heartbeat timeout fires while LLM takes 90s → Temporal kills activity → retry policy gives up → user's stream stops mid-token
2. Redis restart between activity start and SSE connect → first batch lands but SSE connect arrives after restart → empty stream
3. Worker crashes after publishing tokens 1-50 but before 51-100 → if you allow retry, tokens 1-50 get re-emitted
4. SSE client disconnects → server has no signal → activity keeps writing to Redis → eventual `MAXLEN` eviction → reconnect after eviction loses missed tokens
5. Network split between Flask and Redis → `XREAD` hangs → SSE blocks → frontend EventSource times out
6. Schema evolution of agent event dicts → Redis JSON survives but legacy SSE clients break on unknown fields

**Verdict:** the duct tape works, but you're now operating two stateful systems (Temporal + Redis Streams) and reasoning about three failure horizons (workflow, activity, stream-consumer) for the *common case* path.

**Resource footprint:** 4 services + Postgres + Web UI + (optional) Elasticsearch. Server process ~112 MB minimum; realistic full-stack production deployment is 1-2 GB across components, 4-8 GB if running Elasticsearch.

**The honest "actually pick Temporal if..." case.** At least three of:
- Going multi-region in 12 months
- ≥10 engineers with at least one Temporal champion
- Workflows fan out to 10K+ activities each (deep-research-style)
- Need workflow visibility as a first-class product surface
- Already operate K8s seriously and adding 4 more pods is a non-event

For DocsGPT: zero of these. Pick DBOS.

### D2. Hatchet — deep dive

**Day 1.** `pip install hatchet-sdk` and `docker run ghcr.io/hatchet-dev/hatchet/hatchet-lite:latest` (with PG dependency). Two containers. Lite ships Engine + API server bundled. Time to "hello world": ~30 minutes. Time to first Flask integration: half a day (worker is a separate process via gRPC).

First error: gRPC connection refused — `SERVER_GRPC_BROADCAST_ADDRESS` is `localhost:7077` and worker can't reach it from inside Docker. Second: V1 SDK strictness — pass a dict where Pydantic expects a model.

**Day 30.** Workers connect via gRPC; scale workers independently. Hatchet UI on port 8888 — a real win for visibility. Pains:
- Engine + API are separate processes in non-Lite mode; in Lite they're one. Switching Lite→full deployment is a mechanical change but you have to do it intentionally before throughput grows.
- Postgres-only mode handles "hundreds of tasks per second"; beyond that you add RabbitMQ. Most DocsGPT users are nowhere near this.
- v0→v1 migration in March 2025 was a substantial rewrite (Pydantic-first, async-first, all camelCase fields gone, `aio_` prefix, `timedelta` instead of strings, `verbs` API). EOL of v0 was Sept 30, 2025.

**Day 180.** Named customers: Aevy ("week to 1h"), Distill ("100s of engineering hours"), Greptile ("50% reduction in failed runs"), Moonhub ("100→10K tasks"). All AI/data-heavy use cases; YC W24. HN community sentiment positive; multiple Show HN threads with engaged comments; founder active.

**The thing that hurts at 6 months:** the durable_task model and the streaming model are documented as separate features and **the docs don't explicitly confirm they compose.** Streaming docs use `@hatchet.task()`, not `@hatchet.durable_task()`. Durable best-practices doc says forbidden ops in a durable task are "direct database access, direct external API calls" — and `aio_put_stream` is part of the Hatchet context API, so it should be allowed, but **no example anywhere combines them** and there's no GH issue clearly resolving this. Mitigation: build a thin shim that runs the streaming part as a non-durable child task spawned by the durable parent.

**Streaming on Hatchet — the actual code:**
```python
@hatchet.task()
async def stream_task(input: EmptyModel, ctx: Context) -> None:
    for chunk in chunks:
        await ctx.aio_put_stream(chunk)

@app.get("/stream")
async def stream() -> StreamingResponse:
    ref = await stream_task.aio_run(wait_for_result=False)
    return StreamingResponse(
        hatchet.runs.subscribe_to_stream(ref.workflow_run_id),
        media_type="text/event-stream",
    )
```

Pattern fits DocsGPT cleanly. The catch is unconfirmed durability+streaming composition.

**Resource footprint Lite mode:** ~200-400 MB combined steady-state for low-throughput. Postgres can be the existing instance. Containers added for DocsGPT in Lite: 1.

**The honest "actually pick Hatchet if..." case.** At least two of:
- Want a real workflow UI as a first-class operational tool (dashboard is genuine differentiator over DBOS Conductor at the free tier)
- Want a clean Celery replacement for the *whole codebase*, not just greenfield (Hatchet is positioned exactly here; DBOS positioned as "library beside Celery")
- Throughput approaching 10K tasks/sec in your future (DBOS hits PG contention earlier)
- Like FastAPI-shaped Pydantic-first SDK aesthetic more than DBOS's decorators
- Rather operate one extra container with a UI than embed-as-library with no UI

**For DocsGPT:** strongest second choice and would be #1 if streaming-on-durable-tasks were explicitly documented end-to-end.

### D3. Inngest — deep dive

**Day 1.** `pip install inngest` and `npx inngest-cli@latest dev` (in-memory state). Hello-world: ~30 minutes. Flask integration: half-day via `inngest.flask.serve(app, client, [...functions])` adapter. Execution model is **HTTP-callback**: Inngest server POSTs back into your Flask app for each step.

First error: HTTP signing. Mismatch → 401 → function looks like it never ran.

**License correction from earlier docs:** Inngest server moved off SSPL to **Fair Source License (FSL)** with auto-conversion to Apache 2.0 after 3 years. Released Sept 2024. Meaningfully friendlier than SSPL was for self-hosters of OSS projects.

**Realtime support for Python landed September 26, 2025** in the experimental package. The publish side works in Python; the React subscribe hook (`useInngestSubscription`) is still TS-only.

**Day 30.** Strengths show: dashboard for in-flight functions is genuinely good, retries first-class, `step.run()` model decoder-friendly. Pains:
- HTTP-callback model means **every step is a network roundtrip** to the Inngest server and back. For a 50-step agent loop, 50 round-trips. For DocsGPT's 1000-token streams, not the right primitive — you'd publish via realtime channels, not steps.
- Pre-1.0 Python SDK (currently 0.5.18) means breaking changes still possible.

**Day 180.** Named users: SoundCloud, Resend, Outtake, Cubic, Day AI, Otto, Replit, TripAdvisor, Contentful, Gumroad, GitBook, Fey. Quote from Aomni founder: "Highly recommend for multi-step AI agents." Resend co-founder: "DX and visibility with Inngest is really incredible." HN counter-argument: HTTP-callback adds latency in low-throughput high-stakes paths.

**Streaming on Inngest — the swap.** Frontend rewrites from SSE to Inngest's WebSocket channel. `useInngestSubscription` hook is TS-only:
```typescript
const { data, latestData, status } = useInngestSubscription({
  refreshToken: () => fetch(`/api/stream-token?id=${streamId}`).then(r => r.text()),
  channel: `agent-stream:${streamId}`,
  topics: ["tokens"],
});
```

For a Python+Flask+React monolith, you swap your existing SSE for Inngest's WebSocket channel with no easy "use it from Python" path. Auth via short-lived subscription tokens minted server-side.

**The honest "actually pick Inngest if..." case.** At least two of:
- Frontend is React/TypeScript and you're happy to use `useInngestSubscription` instead of SSE
- Backend is mostly serverless or already FastAPI-shaped — the HTTP-callback model fits
- Want event-driven triggering as a first-class abstraction
- Comfortable on a pre-1.0 Python SDK with frontier-experimental Realtime

**For DocsGPT:** probably not. Flask monolith is the wrong shape for HTTP-callback per step.

### D4. Restate — deep dive

**Day 1.** `pip install restate-sdk`. Server is single Rust binary with embedded RocksDB; no external DB required for single-node. `docker run restatedev/restate:latest`. Time to hello-world: ~30 minutes. Flask integration: ~half day, but you think about it differently — Restate is HTTP-callback shaped (like Inngest), Flask exposes Restate handlers via `restate.app(services=[...])` and Restate pings them.

First error: handler signature mismatch. Restate's `ctx.run("step", lambda: ...)` is the durability primitive; if you call I/O outside `ctx.run`, you bypass durability and look like everything works until a retry blows up.

**Day 30.** Memory pressure. Docs recommend "3GB RocksDB cache for production." That's a non-trivial baseline for a self-hosted OSS project where users may run on 4GB VPSes. RocksDB is also opaque to most users — when something goes wrong, "look at the RocksDB metrics" is a tall ask.

**Day 180.** Named users (per restate.dev): "AI workflows, payments, crypto trades, account and credit-card stack of a tier-1 bank." Restate Cloud opened publicly in 2025. Python SDK is pre-1.0 (0.17.1) with 63 GitHub stars (vs Rust server's 3,778) — the Python ecosystem is significantly less mature than TS or Java for Restate.

**Streaming on Restate — what "no streaming" actually means.** Their docs say outright: *"Restate's `ctx.run()`-blocks do not support streaming responses. Therefore, you should turn off streaming for model responses or wait for the full response to arrive."* No documented Python SDK return type for streaming/generator handlers.

Three options if you accept "no streaming":

| Option | User experience | Engineering cost |
|---|---|---|
| **Wait for full response** | Spinner for 8-30s typical DocsGPT response, then full answer at once. Need keepalive pings. **Perceived responsiveness much worse.** | Low |
| **Batch every 100 tokens** | Each batch journaled step. For 1000-token answer, 10 steps. Each batch arrives ~50-200ms delayed. Time-to-first-batch ≈ 1-3s. **20-50× regression in perceived responsiveness vs today's 50-100ms time-to-first-token.** | High (refactor `agent.gen()` to batch yields) |
| **Stream outside Restate** (own pub/sub) | Agent runs in regular activity (no journaling); Redis Streams; Flask SSE consumes. **You've adopted Restate but disabled durability for the most important code path.** | Medium |

**Verdict:** Restate is disqualified for DocsGPT's primary chat path. Fine for the reminder feature alone (where wake-up doesn't need to stream) but adopting just for that is poor cost/value vs DBOS or A.

**Production stories:** anonymous tier-1 bank claim. 63 stars on Python SDK. **No publicly named Python production users I could find.** No HN postmortem-style adoption stories. Thin signal — Restate may be excellent for serverless workflows; for a Python-Flask monolith it's frontier territory.

**The honest "actually pick Restate if streaming were fixed..." case.** At least two of:
- Team is TS/Java-first and Python is secondary
- Want a single-binary stateful workflow engine with no external DB requirement
- Building serverless or edge-shaped systems
- Durable execution dominated by virtual objects with locked state (Restate's actor-like Virtual Objects model is genuinely interesting for some agent shapes)

**For DocsGPT:** even if streaming were fixed, the Python SDK maturity gap and BSL server license make this a "wait and see in 2 years" choice.

### D5/D6. Prefect 3 / Windmill

Both confirmed wrong-shape after deeper review:
- **Prefect 3** is data-pipeline oriented (DAGs, scheduled syncs). Pause/resume exists for human-in-loop. No native token streaming primitive. Same out-of-band-Redis story as Temporal.
- **Windmill** is a script orchestrator with auto-generated UI ("OSS Retool + simplified Temporal"). Not an embedded library or SDK to call from Flask. **AGPLv3** is incompatible with most distribution patterns for an MIT project.

---

## Approach E — Event-source the agent loop

The highest long-term payoff and the wrong call now. Walking through what it actually looks like sharpens *why* it's premature.

### Schema

```sql
CREATE TABLE agent_events (
    conversation_id UUID NOT NULL,
    sequence_no BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    event_version INTEGER NOT NULL DEFAULT 1,
    payload JSONB NOT NULL,
    causation_id UUID,
    correlation_id UUID NOT NULL,
    actor JSONB NOT NULL,  -- {"type": "user|llm|system|tool", "id": "..."}
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (conversation_id, sequence_no)
);

CREATE TABLE conversation_snapshots (
    conversation_id UUID PRIMARY KEY,
    up_to_sequence_no BIGINT NOT NULL,
    state JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Event types — the full list

`UserQueryReceived`, `LLMCallStarted`, `LLMTokenReceived` (per token, the bulk), `LLMCallCompleted`, `ToolCallRequested`, `ToolCallExecuted`, `ToolCallFailed`, `ToolCallCompensated`, `ToolCallApprovalRequested`, `ToolCallApprovalGranted`, `ToolCallApprovalDenied`, `AnswerCommitted`, `WakeUpScheduled`, `WakeUpFired`, `WakeUpCancelled`, `ConversationCompressed`, `TitleGenerated`, `FeedbackProvided`, `AttachmentReferenced`, `ContextLimitReached`, `TokenUsageRecorded`, `ErrorEncountered`, `ConversationStarted`, `ConversationDeleted`.

Projections (read models): `conversations`, `messages`, `tool_calls`, `token_usage` all derived via `fold(events)`.

### The killer feature — replay-debugging

```python
def replay_conversation(conversation_id, *, with_mocks=None, until_event_type=None):
    """Replay deterministically from the event log.
    
    state = replay_conversation("conv-failed-at-3pm")
    state2 = replay_conversation("conv-failed-at-3pm",
        with_mocks={"LLMCallStarted": lambda p: {**p, "system_prompt": "v2"}})
    """
    ...
```

You can run this against last week's 1000 conversations in a batch eval. **This is the killer feature for ES.**

### The migration — shadow → cut → deprecate

**Phase 1: Shadow emit.** Add `emit_event(...)` calls inside the existing agent loop alongside `save_conversation`. Don't read events yet. Pure addition; bounded risk.

**Phase 2: Cut over reads, one projection at a time.** Replace `MessagesRepository.list_for_conversation` with `project_messages(read_events(conv_id))`. Verify equivalence in feature-flagged shadow read; cut over.

**Phase 3: Deprecate existing tables.** Drop `conversation_messages`. Events are the source of truth.

### The hard problem — token-level events explode storage

A 1000-token answer = 1000 `LLMTokenReceived` events. At 1000 conversations/day × 1000 tokens = 1M events/day = 30M/month. JSONB at ~200 bytes each = 6 GB/month.

**Realistic mitigation:** don't event-source per token. Emit `LLMStreamStarted`, write tokens to a separate (non-event-sourced) `llm_stream_chunks` table, emit `LLMStreamCompleted` with the full text. **You lose pure event-sourcing purity but storage math works.**

### Why ES is hard (the brutally honest list)

1. **Schema versioning is a permanent tax.** Every event type ever emitted has to remain readable forever, or you write upcasters. The temptation to evolve the agent loop's events is constant; the cost of evolving them is high.
2. **Dual-write coordination during shadow phase.** Every state mutation has to also emit an event. Miss one place, projection is wrong, you discover at week 4. No compiler check.
3. **Projection rebuilds.** Bug in `project_messages` discovered months later means re-reading every event for every conversation. Hours at DocsGPT scale; maintenance window at later scale.
4. **Eventual consistency on reads.** Projections async; users hit cache misses; "I just sent that and it's not showing" complaints. Mitigation: read-your-writes via "read events table directly for the user's own conversations."
5. **Storage cost.** Token-level events are showstopper without batching. Once batched, you've conceded part of the purity.
6. **Cognitive load.** Every developer must understand "projections are async, source of truth is the event log." Onboarding cost real.

### Where ES is the right answer
- Audit & compliance (SOC 2, GDPR data-access requests, AI-Act explainability)
- Eval & regression testing (replay last week's real conversations against candidate prompt; trivial)
- Reproducibility ("the agent did X yesterday" → replay locally with mocked LLM)
- Multi-agent coordination (agents subscribe to each other's events)

### Where ES is the wrong answer
- Rapid iteration (frequent agent-shape changes mean frequent event-schema changes mean frequent upcaster work — the first 2 years of a product are exactly the wrong time)
- Simple CRUD-like state (most of DocsGPT today; forcing them into ES is over-engineering)
- Small teams (versioning + projections + snapshots + rebuilds dominate value at small headcount)
- Storage-cost-sensitive deployments (self-hosted single-VM with 50GB disk gets crushed by token-level events)

### Why DocsGPT isn't there yet, and what would change that

**Not yet because:**
- Agent shapes still evolving (research, workflow, classic, agentic — 4 implementations, all changing)
- Compliance asks aren't first-class product asks yet
- Team size small; maintenance burden would dominate value

**What would change that:**
- A serious enterprise customer asks for AI-Act explainability or SOC 2 audit trails
- Eval becomes a competitive moat ("DocsGPT lets you replay conversations against new prompts" as marketed feature)
- Multi-agent coordination becomes a product theme — agents sending events to each other
- Team size grows to 8+ with at least one ES-passionate champion

Until then: defer.

---

## Cross-cutting themes

### Deterministic-workflow constraint

| Engine | Workflow body must be deterministic? | Replay model |
|---|---|---|
| Temporal | Yes (sandbox enforces) | Replay event history on every recovery |
| Hatchet `durable_task` | Yes (between checkpoints) | Replay event log up to last checkpoint |
| Inngest | Yes (each `step.run` boundary) | Cached step outputs on retry |
| Restate | Yes (each `ctx.run` boundary) | Journal + replay |
| DBOS | Yes (workflow body) | Cached step outputs, replay from last completed step |
| In-house B | Yes (you'd enforce manually) | Same as DBOS |
| A. Status-quo-plus | No constraint on workflow shape | No replay; idempotent retry only |
| E. Event-source | No (events emitted from non-deterministic code) | Replay from event log |

### Process model

| Engine | Sidecar / external process? | Containers in self-host |
|---|---|---|
| Temporal | Yes (Service: 4 components + DB) | 4-6 |
| Hatchet (Lite) | Yes, single binary | 1 |
| Hatchet (full) | Yes (api + engine + queue) | 3 |
| Inngest | Yes, single binary | 1 |
| Restate | Yes, single binary | 1 |
| **DBOS** | **No, library-only** | **0** |
| In-house B | No | 0 |
| A. Status-quo-plus | No | 0 |
| E. Event-source | No | 0 |

### Python first-class status

| Engine | Python first-class? |
|---|---|
| Temporal | Yes — Python SDK mature, well-documented |
| Hatchet | Yes — v1 Pydantic-first, async-first |
| Inngest | Mostly — Python SDK pre-1.0, Realtime in beta as of Sept 2025 |
| Restate | No — TS and Java mature, Python laggard (63 stars vs 3,778 server) |
| DBOS | Yes — Python is flagship |

### License taxonomy & exit story

| Engine | License | Practical impact |
|---|---|---|
| DBOS Transact (library) | MIT | Frictionless |
| DBOS Conductor (UI) | Proprietary (free dev / paid prod) | Optional |
| Temporal Server + SDK | MIT | Frictionless |
| Hatchet Server + SDK | MIT | Frictionless |
| Inngest Server | FSL (auto Apache 2.0 after 3y) | Friendly — moved off SSPL Sept 2024 |
| Inngest SDK | Apache 2.0 | Frictionless |
| Restate Server | BSL 1.1 (converts after 4y) | Acceptable for non-competing use; review surface |
| Restate SDK | MIT | Frictionless |
| Prefect | Apache 2.0 | Frictionless |
| Windmill | AGPLv3 | Viral copyleft — incompatible for embedded |

**The "if the company dies" inheritance test.** For DBOS, Hatchet, Temporal: license is MIT, fork is viable, your data is in standard SQL tables. For Inngest: FSL is auto-Apache after 3 years. For Restate: BSL until conversion. **For OSS distribution, MIT-everything (DBOS, Hatchet, Temporal) is the cleanest inheritance story.**

### 5-year survival likelihood

| Engine | Probability | Why |
|---|---|---|
| Temporal | High | Multiple unicorns; ecosystem too big to fail |
| DBOS | Medium-high | $8.5M raised, growing, MIT library survives even if company doesn't |
| Hatchet | Medium-high | YC W24, real revenue, MIT-everything means survives company death |
| Inngest | Medium | Real customers; pre-1.0 Python a yellow flag; FSL friendly |
| Restate | Medium | Funded; Rust-server is a moat; Python SDK growth needs to materialize |
| Prefect | High (in its category) | Wrong category but well-established |
| Windmill | Medium-high (in its category) | Wrong category but well-established |

---

## Final synthesis

**Brutally opinionated:** Hatchet and Temporal are *good*, but they solve a "I want a workflow service in my stack" problem that DocsGPT doesn't have. Inngest and Restate are *fine* but neither's streaming story is friction-free. The in-house engine (B) is *defensible only as the partial-rebuild that A already represents*. Event sourcing (E) is the *highest-payoff long-term play and the wrong call now*. The non-recommended options aren't wrong-in-themselves; they're wrong-for-DocsGPT-now.

**If DBOS feels like fighting it after shipping the reminder feature**, the fallback ranking is:
1. Hatchet (if streaming-on-durable-tasks gets clarified end-to-end)
2. Temporal (if you grow into multi-region multi-tenant)
3. In-house-B-extended (if a hard organizational constraint emerges)

Inngest, Restate, Prefect, and Windmill remain the "no" pile for DocsGPT specifically.
