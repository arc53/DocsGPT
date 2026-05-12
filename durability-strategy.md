# Durability Strategy for DocsGPT

## The ask

Make DocsGPT executions more durable broadly. Identify what would benefit beyond the planned scheduled-reminder feature, and lay out the option space with enough detail to pick a direction.

> Code-level integration details, day-1/30/180 operational reality, production-user signal, exit costs, and brutally honest gotchas per option live in `durability-options-deep-dive.md`. This doc is the strategic summary and recommendation.

## DocsGPT's two product promises

DocsGPT delivers two distinct-but-connected experiences. Both are agentic; the difference is shape, not category.

1. **Linear agentic loop** — source + tools + custom prompt. The "ask my knowledge base" path with tool calls woven in. Onyx-shaped.
2. **Agentic workflows** — multi-step graphs with branching and conditions. Dify-shaped. We already have `workflow_agent` with the bones of this.

The durability strategy must serve both. The good news: most of the work (Celery hardening, WAL placeholders, heartbeat + reconciliation, SSE replay) is shared across both modes. The divergence is at the runtime layer, where workflow executions need per-node persistence and snapshot-based pause/resume that linear chat doesn't.

## TL;DR

Three-tier sequencing, validated by **Onyx** and **Dify** — two mature production OSS in DocsGPT's exact space. Neither uses Temporal/DBOS/Hatchet/Restate/Inngest. Both built on Celery + Postgres rows + Redis with carefully designed application-layer state machines.

| Tier | Effort | What ships | When |
|---|---|---|---|
| **Tier 1 — Onyx baseline** | Done | `acks_late`, WAL placeholder for assistant messages with meaningful "regenerate" text, heartbeat + reconciliation beat task, idempotency keys at HTTP boundaries, three-phase tool-call audit, transactional `token_usage` | Landed |
| **Tier 2 — SSE snapshot+tail replay** | 1-2 weeks | Celery worker → Redis pub/sub topic by `message_id` → SSE handler subscribes (race-free via `on_subscribe`) → on reconnect, snapshot from DB then tail. Buys reconnect-after-disconnect, multi-tab live mirroring, pod-restart visibility | Next |
| **Tier 3 — Extend `workflow_agent` (Path C)** | Per-feature, careful | Per-node persistence + snapshot serialization + pause primitive, only what the product actually needs | When product calls for it (HITL approval, paused workflows, replay) |

**Not adopting DBOS / Temporal / Hatchet / Restate / Inngest.** Two production projects in our exact space chose to build on Celery + Postgres + Redis instead. The likely reason: a vendor's primitives don't match DocsGPT's specificity (existing `BaseAgent`, `ToolExecutor`, `ContinuationService`, `workflow_agent` shapes), and the abstraction overhead outweighs the win once you've already built the substrate. Path C wins because we already have the workflow bones — the work is targeted enrichment, not new construction.

## Audit Status After Tier 1

The original audit covered 13 execution paths. Tier 1 has now landed the shared durability foundation: Celery late ACK/requeue settings, pre-LLM message reservation, `task_dedup` / `webhook_dedup`, `tool_call_attempts`, `ingest_chunk_progress`, `pending_tool_state.status`, token-usage request correlation, idempotency leases, stream heartbeats, and the reconciliation beat task.

| Path | Current status after Tier 1 |
|---|---|
| Streaming agent run (`stream_processor.py`) | Pre-reserves a message row before the LLM call, heartbeats while streaming, finalizes to `complete` / `failed`, and reconciles stuck rows. Tier 2 still needed for replaying live chunks after disconnect. |
| Source ingestion (`worker.py`) | Durable task settings, deterministic `source_id` from idempotency key, chunk progress, per-attempt scoping, and heartbeat-backed stall visibility are in place. |
| Webhook agent runs (`webhooks.py`) | Incoming idempotency and durable Celery task handling are in place; failures now raise into Celery retry paths instead of being treated as success. |
| Token usage (`usage.py`) | Stream-scoped `request_id` and `source` attribution are in place so multi-call runs can be counted once and side-channel usage can be separated. |
| Tool calls (`tool_executor.py`) | Three-phase audit exists: `proposed → executed → confirmed or failed`. This provides observability and manual recovery hooks; it does not promise automatic rollback of external side effects. |
| Conversation init (`conversation_service.py`) | First-turn conversation/message reservation now happens before streaming begins. |
| Pending tool state janitor | Resume now marks state as `resuming` and deletes only after completion; stale resumes revert through cleanup. |

Remaining gaps:

| Path | Remaining risk | User impact |
|---|---|---|
| Periodic syncs (`worker.py`) | Sync scheduling is still coarse and lacks a robust per-connector cursor / user-visible failure surface. | Long deploys or connector failures can leave sources stale without clear user feedback. |
| Workflow agent (`workflow_agent.py`) | `workflow_runs` still needs per-node persistence and snapshot/resume primitives. | A multi-step workflow crash can still lose mid-run progress. |
| MCP OAuth (`worker.py:1505`) | State still relies on Redis TTL. | Redis restart mid-handshake can still lose the flow. |
| Research agent | Citations and partial research state are still mostly in-memory. | Crash mid-research can require a full restart and repeat spend. |
| MongoDB → PG dual-write / legacy paths | Any remaining legacy shim that swallows PG write failures needs retirement or explicit alerts. | Split-brain data can still occur where legacy dual-write paths remain active. |

DocsGPT is no longer at "zero formal durability primitives." The current problem is narrower: Tier 1 made currently-running tasks observable and recoverable enough for retries/manual escalation, while Tier 2 and Tier 3 still need to address live stream replay and workflow-runtime state.

## Industry validation: Onyx and Dify

Two mature production OSS in DocsGPT's exact space. Both Python backends, both Postgres-only, both Celery-heavy.

- **Onyx** — RAG + connectors, "linear" shape (matches DocsGPT promise 1)
- **Dify** — visual LLM app builder, "workflow" shape (matches DocsGPT promise 2)

### What they share (the validated baseline)

| Pattern | Detail |
|---|---|
| Backend stack | Celery + Postgres-only + Redis. **No Mongo, no DBOS/Temporal/Hatchet/Restate/Inngest** |
| Per-message WAL | Assistant message row created with placeholder before LLM call |
| Stop-fence | Redis key polled at ~50ms |
| Schedule polling | `SELECT FOR UPDATE SKIP LOCKED` (Onyx migrated *away* from Redis fences toward this) |
| Simple chat streaming | In-process generator for low-latency conversational paths |
| Idempotency at HTTP boundary | None — handled at the data layer via stable IDs |

### Where they diverge

| Area | Onyx | Dify |
|---|---|---|
| Workflow engine | None — chat is "send + receive", ingest is a long Celery task | `GraphEngine` (extracted to PyPI as `graphon`, ~10k LOC) — queue-based, serializable runtime state, command channel for OOB control |
| HITL tool/human approval | None | First-class `HumanInputNode` with web/email delivery, expiration, parallel join |
| SSE resume after disconnect | "Regenerate on disconnect" — explicit choice | Snapshot+tail: reconstructs prior events from DB, then tails Redis pub/sub |
| Streaming transport (workflow mode) | n/a | Celery worker → Redis pub/sub by `workflow_run_id` → SSE handler subscribes via `on_subscribe` callback (race-free) |
| `acks_late` | **Yes (default)** | **No (early ACK)** |
| Stuck-task janitor | Heartbeat counter + reconciliation beat task (`validate_active_indexing_attempts`) | None — only `queue_monitor_task` alerts; `WorkflowRun.status=RUNNING` rows orphan on crash |
| Crash UX | Placeholder text: "Response was terminated prior to completion, try regenerating." | Empty `answer=""` |
| Per-connector ingest checkpoint | `CheckpointedConnector` ABC + 50-attempt poison-loop guard | Per-segment DB row + Redis pause flag |
| Multi-tenancy | PG schema-per-tenant | Row-level `tenant_id` |
| Vector store | Single (Vespa → OpenSearch) | 32 backends behind ABC |
| Plugin system | First-party | Out-of-process Go `plugin_daemon` |
| Worker pool | All `pool=threads` (avoiding billiard SIGSEGV) | Default `pool=gevent` |

### Best of both for DocsGPT

DocsGPT's two-promise positioning means we want the union:
- **Onyx baseline**: `acks_late`, heartbeat + reconciliation, "regenerate" placeholder text — Dify lacks all three and pays for it
- **Dify streaming + workflow durability**: snapshot+tail SSE replay, per-node persistence, pause primitive — Onyx lacks all three

The composition is natural: Onyx's primitives sit at the per-Celery-task level; Dify's snapshot sits at the per-workflow-run level. They don't conflict.

## Three-tier sequencing

### Tier 1 — Onyx baseline (landed)

Pure refactor on existing Celery + Postgres. No new infra. Fixes the broad silent-data-loss class of bugs. Landed across migrations `0004_durability_foundation.py`, `0005_ingest_attempt_id.py`, and `0006_idempotency_lease.py`.

**Configuration:**
- `application/celeryconfig.py`: add `task_acks_late=True`, `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1`, `broker_transport_options={"visibility_timeout": 7*3600}`, `result_expires=86400*7`, `task_track_started=True`

**New tables / columns:**
- `task_dedup` (idempotency keys for Celery tasks, attempt counts, lease owner/expiry)
- `webhook_dedup` (incoming webhook idempotency)
- `tool_call_attempts` (three-phase tool audit: `proposed → executed → confirmed or failed`)
- `ingest_chunk_progress` (per-source chunk checkpoint with per-attempt scoping)
- New columns on `conversation_messages`: `status` (`pending|streaming|complete|failed`), `request_id`
- New columns on `pending_tool_state`: `status`, `resumed_at`
- New columns on `token_usage`: `source`, `request_id`

**Code changes:**
- `application/api/answer/services/conversation_service.py`: split into `save_user_question(question) → message_id` (called *before* LLM with placeholder text "Response was terminated prior to completion, try regenerating.") and `finalize_message(message_id, response, ...)` (called after — transactional with `token_usage`)
- `application/api/user/tasks.py`: every long-running task gets `acks_late=True`, `autoretry_for=(Exception,)`, `retry_kwargs={"max_retries": 3, "countdown": 60}`, `retry_backoff=True`, plus an `idempotency_key` parameter checked against `task_dedup`
- `application/agents/tool_executor.py:267`: refactor `execute` into three phases (record `proposed` → execute → update to `executed` → `finalize_message` flips to `confirmed`)
- `application/api/user/agents/webhooks.py:81`: accept `Idempotency-Key` header
- `application/api/user/sources/upload.py`: derive `source_id = uuid5(NAMESPACE, idempotency_key)` instead of fresh `uuid4()` inside task (prevents duplicate sources on retry)
- `application/api/answer/services/stream_processor.py:1027`: stop eager `delete_state(...)`. Mark `status='resuming'` instead, delete only on completion
- `application/worker.py:agent_webhook_worker`: raise on error instead of returning `{"status": "error"}` (today Celery treats it as success)
- New `reconciliation_worker` Celery beat task (every 30s): scans for messages stuck in `pending|streaming` for >5 min, tool_call_attempts stuck in `proposed` >5 min or `executed` >15 min, stalled ingest heartbeats, and exhausted idempotency leases; marks terminal failures and emits operator alerts

Full file-by-file design + gotchas + week-by-week timeline in `durability-options-deep-dive.md` Approach A.

### Tier 2 — SSE snapshot+tail replay (1-2 weeks)

The Dify pattern, ported to DocsGPT's existing Flask + Celery setup. Buys reconnect-after-disconnect for both linear chat AND workflow runs (when Tier 3 lands). ~500 LOC of glue.

**The pattern:**
1. Frontend POST `/send-chat-message` → backend creates `conversation_messages` row with `message_id` (Tier 1 already does this)
2. Backend builds Redis pub/sub topic `channel:{message_id}`
3. **Subscribes first**, then via `on_subscribe` callback dispatches the Celery task — race-free
4. Celery worker runs `agent.gen()`, publishes events to the topic per yield
5. SSE handler tails subscription, yields to client
6. Client reconnects? Backend reads `conversation_messages` row + new `message_events` rows from DB, yields snapshot, then tails the live pub/sub
7. Buffer state ensures no event missed between snapshot and tail

**New components:**
- `application/streaming/broadcast_channel.py` — small Redis pub/sub abstraction (`Topic.publish`, `Topic.subscribe`, `on_subscribe` callback). Single backend (Redis pub/sub); don't ABC for multiple backends until needed
- `application/streaming/event_replay.py` — `build_message_event_stream(message_id, last_event_id=None)` reads DB then tails pub/sub
- New table `message_events(message_id FK, sequence_no, event_type, payload, created_at)` with `(message_id, sequence_no)` PK
- Update `application/api/answer/routes/base.py:complete_stream` to subscribe-first then dispatch Celery, instead of in-process generator
- Move `agent.gen()` execution into a new Celery task that publishes events to the topic

**Frontend:**
- `frontend/src/conversation/conversationHandlers.ts`: support `Last-Event-ID` header on reconnect; keep existing fetch-streaming idiom

**Reuse from Tier 1:**
- Stop-fence via Redis key
- `conversation_messages.status` for snapshot reconstruction logic

**Relationship to `notification-channel-design.md`:**

Tier 2 should share the low-level transport pieces with the internal notification channel — fetch-based SSE parsing, auth/reconnect/keepalive handling, Redis topic publish/subscribe helpers, and connection-health reporting. Keep the domains separate above that transport layer: Tier 2 is a `message_id`-scoped, ordered, correctness-critical stream backed by Postgres `message_events`; notifications are `user_id`-scoped background UX events backed by the user event backlog. Do not route token/message replay through the user notification firehose.

### Tier 3 — Extend existing `workflow_agent` (Path C, when product calls for it)

DocsGPT already has `workflow_agent.py` with multi-step graphs and branching. This tier is enrichment of what exists, not new construction. Add only what the product actually needs, in this order:

| Item | What | Trigger to add |
|---|---|---|
| `workflow_runs` (extend existing) + `workflow_node_executions` table | Per-run + per-node journal: `inputs/outputs/status/error/elapsed_time/predecessor_node_id` | Workflow runs need debuggability or replay (probably the first ask) |
| Snapshot serialization | `RuntimeState.dumps()` to FileStore as JSON; tiny `workflow_pauses(workflow_run_id, state_object_key)` DB pointer row | Workflows need to pause for HITL or survive crash mid-run |
| `resume_workflow_run` Celery task | Load snapshot, rehydrate state, continue from saved point | Pairs with snapshot; useless without it |
| Pause primitive | Engine yields `PauseRequestedEvent` → snapshot serialized → DB row created → external `POST /workflow_runs/{id}/resume` enqueues resume task | Product wants HITL tool approval / human input flows |
| Per-node SSE events into Tier 2 topic | Workflow nodes publish progress events to the same `message_id` topic chat uses | UI live progress for workflow runs (free reuse of Tier 2) |

**Don't build (yet):**
- 32 vector backends — Dify pays this maintenance cost; pick 3-5
- Plugin daemon (out-of-process Go service) — premature abstraction
- PyPI extraction of the runtime — Dify did this with `graphon`; coordination cost is real
- Tier-based queues (`PROFESSIONAL_QUEUE` / `TEAM_QUEUE`) — only when monetization needs it
- CFS time-slicing layer — only when multi-tenant fairness matters
- Multiple BroadcastChannel backends — Redis pub/sub is fine until proven otherwise
- Custom node types beyond what the product uses
- Multiple delivery surfaces for HITL (web + email + console) — start with web, add email later
- ABC-everything — direct implementations until a second case appears

**Why extend-our-own beats DBOS adoption:**

- DocsGPT already has `workflow_agent` with graphs and branching — bones exist
- DBOS's deciding-factor primitive (`write_stream`/`read_stream`) was reconnect-after-disconnect; Tier 2 gets that without DBOS via Dify's pattern
- DBOS's HITL primitive (`recv()`) is replaceable with our own pause primitive on the existing engine
- Two production projects in our space looked at the workflow-engine-vendor option and built their own instead. Two independent data points
- Maintaining a small in-house extension to the runtime we already have is cheaper than carrying the DBOS dependency for years
- DBOS's pickle-by-default snapshot format has real exit cost; our own JSON format doesn't
- DocsGPT's specificity (existing agent classes, `ToolExecutor` patterns, encrypted credential decryption keyed by `user_id`) outgrows whatever subset DBOS provides; we'd be fighting the abstraction

## What NOT to do

- **DBOS / Temporal / Hatchet / Restate / Inngest** — neither Onyx nor Dify chose any of these. The vendor's specificity won't match ours. Restate is additionally disqualified by streaming gap (their `ctx.run` blocks don't support streaming)
- **Event-source the agent loop** — premature; defer until compliance/eval is a top product driver
- **32 vector backends** — Dify pays maintenance cost we don't need
- **Schema-per-tenant multi-tenancy** — Onyx pays for it; only adopt if we go enterprise-multitenant
- **Build then extract a runtime as a PyPI package** — Dify did this with `graphon`; ongoing release coordination cost
- **Custom `@durable_step` decorator** in Tier 1 — the WAL pattern is grep-able inline; a decorator hides the table name and complicates debugging. Build helpers only at the storage layer, not the control-flow layer

## Benefits beyond the reminder feature

The durability work unlocks value independent of any single feature:

1. **Crash-safe ingestion** — `reingest_source_worker` resumes from last embedded chunk; saves embedding API spend
2. **Replayable debugging** — "the agent did the wrong thing yesterday" becomes reproducible (Tier 3 with per-node journal makes this trivial; Tier 1 alone enables partial reproduction via `tool_call_attempts`)
3. **Tool side-effect auditability** — Telegram sends, API calls, and destructive tools leave structured rows operators can inspect instead of disappearing into logs
4. **Deploy without dropping in-flight work** — graceful drain; in-flight runs checkpoint and resume
5. **Cost attribution at any cardinality** — every LLM call in a journal makes per-conversation/per-user/per-feature cost queryable
6. **A/B testing & evals** — replay last week's real conversations against a candidate model or prompt
7. **Long-horizon agent flows** — research agent goes from "5 min then time out" to "hours, paused at multiple approvals"
8. **Tool-level observability** — `SELECT tool_name, AVG(latency_ms) FROM tool_call_attempts` instead of grepping JSONB
9. **Reconnect-after-disconnect** (Tier 2) — chat doesn't die on Wi-Fi blip; multi-tab works
10. **HITL** (Tier 3) — tool-approval, human-input flows enabled by pause primitive

## Reference: option families considered

Brief reference. Full per-option analysis (file-by-file diffs, day-1/30/180, gotchas, exit costs) in `durability-options-deep-dive.md`.

| Option | Verdict |
|---|---|
| **A. Status-quo-plus** | **Tier 1 (landed).** Pure refactor on existing Celery + Postgres |
| B. In-house PG workflow engine | **Tier 3 (recommended, minimal).** We already have `workflow_agent`; this tier extends it carefully |
| C. DBOS | Not recommended. Vendor specificity mismatch; we'd fight the abstraction |
| D1. Temporal | Not recommended. Operational weight wrong for OSS self-host; streaming requires Redis bridge |
| D2. Hatchet | Not recommended. Closest competitor; streaming-on-`durable_task` undocumented; we don't need a Celery replacement |
| D3. Inngest | Not recommended. HTTP-callback per step is sideways for a Flask monolith; pre-1.0 Python SDK |
| D4. Restate | Disqualified. Streaming explicitly unsupported in `ctx.run()` blocks |
| D5. Prefect 3 | Wrong shape (data pipelines, not agent runtime) |
| D6. Windmill | Wrong product category (script orchestrator with UI) |
| E. Event-source the agent loop | Defer. Highest long-term payoff, premature now |
| F. Hybrid A + C/D | Replaced by A + Dify-pattern (Tier 2) + minimal own runtime (Tier 3) |

## Critical files

### Tier 1 — Onyx baseline

- `application/celeryconfig.py` — flip Celery durability defaults
- `application/api/user/tasks.py` — `acks_late`, retries, idempotency_key parameter on every task; `process_agent_webhook` raises on error
- `application/api/answer/services/conversation_service.py` — split into `save_user_question` + `finalize_message`; transactional `token_usage`
- `application/api/answer/routes/base.py` — call `save_user_question` before `agent.gen()`; restructure `complete_stream`
- `application/agents/tool_executor.py` — refactor `execute` into three-phase save→execute→confirm audit
- `application/api/user/agents/webhooks.py:81` — `Idempotency-Key` header
- `application/api/answer/services/stream_processor.py:1027` — stop eager `delete_state`; mark `status='resuming'`
- `application/storage/db/repositories/conversations.py` — add `status` column transitions
- `application/usage.py` — single transaction with message insert
- New: `application/alembic/versions/0004_durability_foundation.py`
- New: `application/alembic/versions/0005_ingest_attempt_id.py`
- New: `application/alembic/versions/0006_idempotency_lease.py`

### Tier 2 — SSE snapshot+tail replay

- New: `application/streaming/broadcast_channel.py` — Redis pub/sub `Topic` abstraction with `on_subscribe` callback
- New: `application/streaming/event_replay.py` — `build_message_event_stream(message_id, last_event_id)`
- New: `application/api/answer/tasks/agent_stream_task.py` — Celery task running `agent.gen()` and publishing to topic
- Update: `application/api/answer/routes/base.py:complete_stream` — subscribe-first then dispatch
- Update: `frontend/src/conversation/conversationHandlers.ts` — support `Last-Event-ID` on reconnect
- New table: `message_events`

### Tier 3 — Extend `workflow_agent` (when triggered)

- Update: `application/agents/workflow_agent.py` — emit per-node events to Tier 2 topic; emit `PauseRequestedEvent` when nodes need HITL
- New tables: `workflow_node_executions`, `workflow_pauses`
- New: `application/agents/workflows/runtime_state.py` — serializable state (variable pool + ready queue + per-node state) with `dumps()` / `from_snapshot()`
- New: `application/agents/workflows/persistence_layer.py` — write `workflow_node_executions` rows on every `Node*Event`
- New Celery task: `resume_workflow_run(run_id)` — load snapshot, continue
- New endpoint: `POST /api/workflow_runs/{run_id}/resume` — for HITL form submission

## Sources

Industry validation:
- Onyx: https://github.com/onyx-dot-app/onyx — RAG product, similar shape to DocsGPT promise 1
- Dify: https://github.com/langgenius/dify, https://dify.ai/ — workflow product, similar shape to DocsGPT promise 2
- `graphon` (Dify's extracted runtime): https://pypi.org/project/graphon/

Engine docs (for reference; none recommended for adoption):
- DBOS: [streaming](https://docs.dbos.dev/python/tutorials/workflow-communication), [scheduled workflows](https://docs.dbos.dev/python/tutorials/scheduled-workflows), [pricing](https://www.dbos.dev/pricing)
- Temporal: [Pydantic AI streaming-limit doc](https://pydantic.dev/docs/ai/integrations/durable_execution/temporal/), [Redis SSE pattern](https://www.architectingbytes.com/posts/temporal-redis-sse)
- Hatchet: [streaming docs](https://docs.hatchet.run/home/streaming), [v1 SDK](https://docs.hatchet.run/home/v1-sdk-improvements)
- Inngest: [Realtime](https://www.inngest.com/docs/features/realtime), [Python SDK](https://github.com/inngest/inngest-py)
- Restate: [streaming-limit doc](https://docs.restate.dev/ai/sdk-integrations/integration-guide)

Survey context: [Zylos Research durable execution survey (Feb 2026)](https://zylos.ai/research/2026-02-17-durable-execution-ai-agents)
