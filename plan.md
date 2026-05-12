# Delivery Plan: Notification Channel + Durability Tier 2

> Companion to `notification-channel-design.md` and `durability-strategy.md`.
> This file sequences the work; design rationale lives in the source docs.

## TL;DR — sequencing

| Phase | Ships | Effort | Depends on |
|---|---|---|---|
| **1. Shared SSE transport + Notifications v1** | Source-ingest live updates over SSE; reusable Topic + fetch-SSE primitives | 3–5 days | Tier 1 (landed) |
| **2. Durability Tier 2 — chat snapshot+tail replay** | Reconnect-after-disconnect on agent stream; multi-tab live mirroring | 1–2 weeks | Phase 1 transport |
| **3. Notifications v2** — broader event types | tool.approval, attachment.*, mcp.oauth, source.ingest.* (connector path), source.sync.*, in-app center | 1 week | Phase 1 |
| **4. Notifications v3** — polish, polling removal | Multi-tab dedup, conversation-scoped topic for live agent runs, polling-endpoint retirement | when warranted | Phases 1–3 stable |

**Why this order.** Phases 1 and 2 share transport (fetch-SSE, `Topic`, `Last-Event-ID` reconnect, JWT-on-fetch, keepalive, X-Accel-Buffering, polling-fallback gating). Building the user-firehose first forces a general abstraction; Tier 2 then reuses it for free and narrows to its message_id-specific parts (`message_events`, snapshot reconstruction, Celery move). The lower-stakes notifications channel debugs the transport before the correctness-critical chat path rides it.

**What stays separate across phases.** Notifications use Redis Streams (`XADD MAXLEN ~ 1000`, ~24h ephemeral). Tier 2 uses Postgres `message_events` (durable, multi-day chat replay). Same transport, different durability layers. Don't route message replay through the user notification firehose.

---

## Phase 1 — Shared SSE transport + Notifications v1

**Goal.** Source ingestion (`Upload.tsx` flow) shows sub-second progress over SSE. Polling stays intact, gated as fallback. The SSE primitives built here are what Phase 2 reuses.

### 1A. Backend transport substrate

- New `application/streaming/broadcast_channel.py`
  - `Topic.publish(payload)`, `Topic.subscribe(on_subscribe=...)` — Redis pub/sub, race-free via `on_subscribe` callback
  - Single backend (Redis pub/sub) — do not ABC for multiple backends until needed
- New `application/events/publisher.py`
  - `publish_user_event(user_id, event_type, payload, scope=...)`
  - Both `XADD user:{user_id}:stream MAXLEN ~ 1000 * type ... payload ...` (durable backlog) and `PUBLISH user:{user_id} <json>` (live fan-out)
  - ULID `id` field, ISO timestamp, topic + scope envelope per `notification-channel-design.md` event-envelope spec
- New `application/api/events/routes.py`
  - `GET /api/events` SSE endpoint, JWT bearer auth via existing `request.decoded_token` (`app.py:165-181`)
  - On connect: read `Last-Event-ID` header; `XRANGE user:{user_id}:stream (last_id +` for replay; then transition to `Topic.subscribe`
  - Headers: `Content-Type: text/event-stream`, `Cache-Control: no-store`, `X-Accel-Buffering: no`
  - 15s keepalive comment frames (under Cloudflare 100s idle close, accommodating iOS Safari ~60s)

### 1B. Source-ingest publisher wiring

Add `publish_user_event(...)` calls as siblings to existing `update_state(...)` (do not remove `update_state` — it still feeds `/api/task_status` and is the polling-fallback source of truth):

| File | Existing line | Event type |
|---|---|---|
| `application/worker.py:536` | `update_state(...)` queued | `source.ingest.queued` |
| `application/worker.py:587` | `update_state(...)` progress | `source.ingest.progress` |
| `application/parser/embedding_pipeline.py:92-113` | per-batch progress | `source.ingest.embedded` |
| `application/worker.py` ingest end | success/failure | `source.ingest.completed` / `source.ingest.failed` |

### 1C. Frontend transport substrate

- New `frontend/src/events/eventStreamClient.ts`
  - Fetch-based SSE consumer; mirror parser shape from `frontend/src/conversation/conversationHandlers.ts:147-189`
  - JWT in `Authorization` header, `Last-Event-ID` on reconnect
  - Reconnect with exponential backoff; emit `pushChannelHealthy` state transitions
- New `frontend/src/events/useEventStream.ts` — React hook
- New `frontend/src/events/EventStreamProvider.tsx` — mount under `<AuthWrapper>` in `App.tsx`
- New `frontend/src/events/dispatchEvent.ts` — switch on `event.type` → dispatch to relevant slice
- New `frontend/src/notifications/notificationsSlice.ts` — minimal slice; just enough to drive toasts in v1

### 1D. Slice integration (source ingest only in v1)

- `uploadSlice` consumes `source.ingest.*` events and updates progress without polling round-trips
- `Upload.tsx:341-441` `trackTraining`: keep polling code, gate behind `!pushChannelHealthy || timeSinceLastEvent > 30s`

### 1E. Tests + observability

- Unit: publisher round-trips XADD + PUBLISH; envelope shape; ULID monotonic
- Integration: subscribe → publish → receive; reconnect with `Last-Event-ID` replays missed events
- E2E: upload a real source, assert toast progress driven by SSE (poll fallback disabled in test env)
- Logging: per-publish `event.published topic=... type=...`; per-connect `event.connect user=... gap_replayed=N`
- Metrics: `events_published_total{type}`, `events_connections_active`

### 1F. Done criteria for Phase 1

- 600-chunk upload shows sub-second progress
- Closing the upload modal does not stall progress
- Page reload mid-ingest restores progress within 1s via `Last-Event-ID` replay
- Disabling Redis pub/sub falls back to polling without user-visible regression

---

## Phase 2 — Durability Tier 2 (chat snapshot+tail replay)

**Goal.** Reconnect-after-disconnect on the agent stream. Multi-tab live mirroring. Pod-restart visibility. Reuses Phase 1 transport; adds Postgres-backed snapshot.

### 2A. Schema

- New migration `application/alembic/versions/0007_message_events.py`
  - `message_events(message_id FK conversation_messages.id, sequence_no INT, event_type TEXT, payload JSONB, created_at TIMESTAMPTZ)`
  - PK `(message_id, sequence_no)`; index on `message_id`

### 2B. Backend

- New `application/streaming/event_replay.py`
  - `build_message_event_stream(message_id, last_event_id=None)`: yields snapshot from `message_events` rows, then tails `Topic` for `channel:{message_id}`
  - Buffer-and-dedupe between snapshot tail and live tail (no missed/duplicated events at the boundary)
- New `application/api/answer/tasks/agent_stream_task.py`
  - Celery task running `agent.gen()` (today inline in `complete_stream`)
  - Each yielded event: insert `message_events` row + `Topic.publish` to `channel:{message_id}`
  - Reuses Tier 1 stop-fence Redis key for cancellation
- Update `application/api/answer/routes/base.py:complete_stream`
  - Subscribe-first (`Topic.subscribe` with `on_subscribe`), then dispatch the new Celery task
  - Stream snapshot+tail to client via existing fetch-SSE response shape
  - Reuses Tier 1's `conversation_messages.status` reservation (already landed)

### 2C. Frontend

- Update `frontend/src/conversation/conversationHandlers.ts`
  - On stream-disconnect mid-answer: reconnect with `Last-Event-ID` instead of dropping the in-flight message
  - Reuse `eventStreamClient.ts` parser primitives from Phase 1 (factor out shared parser if not done in 1C)
- Surface "reconnecting…" state distinctly from "regenerate" (the Tier 1 placeholder text remains the final-fallback UX)

### 2D. Tests

- Unit: `event_replay` snapshot+tail boundary correctness with synthetic `message_events`
- Integration: kill the Celery worker mid-stream; reconnect resumes from last persisted event
- E2E: multi-tab — open same conversation in two tabs, both mirror live; reload one tab, it catches up

### 2E. Done criteria for Phase 2

- Wi-Fi blip mid-answer: client reconnects, resumes streaming from where it stopped, no duplicated tokens
- Worker pod restart mid-stream: client reconnects after task re-runs OR sees Tier 1 placeholder if abandoned (per `acks_late` semantics)
- Two browser tabs on the same conversation render the same answer in lockstep

---

## Phase 3 — Notifications v2 (broader event types)

**Goal.** The 14 use cases in `notification-channel-design.md` beyond source ingestion. In-app notifications center.

### 3A. Publisher wiring

`agent_webhook_worker` is intentionally **excluded** — webhook agents are
background side-effect runners (Telegram/ntfy/etc. via API calls) and
their lifecycle isn't a user-surfaced event. Keep the polling-status
endpoint for operators who care.

| File | Event types |
|---|---|
| `application/worker.py:1171,1174,1206,1231` (`attachment_worker`) | `attachment.processing.progress`, `attachment.completed` |
| `application/worker.py:1139-1153` (`sync_worker`) | `source.sync.completed`, `source.sync.failed` |
| `application/worker.py:1505-1586` (`mcp_oauth`) | `mcp.oauth.*` (keep `setex` for fallback) |
| `ingest_connector_task` (Drive/Dropbox/Confluence/SharePoint) | `source.ingest.*` (Phase 1B left this branch out) |
| Tool-approval pause flow | `tool.approval.required` |

### 3B. Polling-loop migration to push-with-fallback

Same `pushChannelHealthy` gate pattern as Phase 1:

- `frontend/src/components/FileTree.tsx` reingest poll — landed. Per-source freshness via `notifications.recentEvents`-keyed-by-`scope.id`; falls back to polling when push is unhealthy or no events for this source within 30s. Refreshes the directory structure on terminal SSE without a network round-trip.
- `frontend/src/components/MessageInput.tsx` attachment poll — **deferred to follow-up**. Requires storing the server's `attachment_id` in the slice on upload-response (currently only stored after SUCCESS) so the existing `attachment.*` events from Phase 3A can match by `scope.id`. Adds an `attachment.*` `extraReducer` to `uploadSlice.attachments` for per-attachment `lastEventAt`.
- `frontend/src/modals/MCPServerModal.tsx` OAuth poll — **deferred to follow-up**. The OAuth flow is short-lived (60s max), so polling-only is acceptable for v1. Phase 4 work, alongside the broader retirement of polling code paths.

### 3C. In-app notifications center

- Expand `notificationsSlice.ts` from Phase 1 to a real history surface
- Notifications dropdown component; bell + badge in header
- Persistence: notifications drain from Redis Streams backlog on connect; no separate DB table v2

---

## Phase 4 — Notifications v3 (polish + retirement)

**Goal.** Remove polling endpoints once push has co-existed cleanly for a release cycle.

- `BroadcastChannel('docsgpt:events')` multi-tab dedup
- `conversation:{conversation_id}` narrow topic for in-progress agent runs (extends Phase 2 reuse)
- Per-user rate limits on Stream replay
- Runbook: "user says they didn't get a notification"
- Retire polling code paths in `Upload.tsx`, `MessageInput.tsx`, `FileTree.tsx`, `MCPServerModal.tsx` after one release with no incidents

---

## Cross-cutting non-negotiables

- **Polling stays as fallback through Phases 1–3.** Push is additive. Removal only in Phase 4 after a clean release window.
- **Two products on one pipe.** Shared: transport, reconnect, auth, Topic, frontend parser. Separate: backlog durability (Redis Streams vs Postgres `message_events`), topic naming (`user:{id}` vs `channel:{message_id}`), correctness contract.
- **Don't ABC `Topic` for multiple backends.** Redis pub/sub is the only backend until a second one is forced by deployment reality.
- **No EventSource.** Fetch-streaming everywhere; matches existing idiom and avoids the no-headers auth limitation.
- **Tier 1 invariants preserved.** `conversation_messages.status` lifecycle, stop-fences, reconciliation beat task remain authoritative; Phase 2 plugs into them, doesn't replace them.

---

## Critical files (cumulative, for grep navigation)

### New (Phase 1)
- `application/streaming/broadcast_channel.py`
- `application/events/publisher.py`
- `application/api/events/routes.py`
- `frontend/src/events/eventStreamClient.ts`
- `frontend/src/events/useEventStream.ts`
- `frontend/src/events/EventStreamProvider.tsx`
- `frontend/src/events/dispatchEvent.ts`
- `frontend/src/notifications/notificationsSlice.ts`

### New (Phase 2)
- `application/alembic/versions/0007_message_events.py`
- `application/streaming/event_replay.py`
- `application/api/answer/tasks/agent_stream_task.py`

### Updated
- `application/worker.py` — publisher calls (Phase 1 ingest; Phase 3 attachment/agent/sync/mcp)
- `application/parser/embedding_pipeline.py` — embedded-batch publisher (Phase 1)
- `application/api/answer/routes/base.py` — subscribe-first dispatch in `complete_stream` (Phase 2)
- `frontend/src/conversation/conversationHandlers.ts` — `Last-Event-ID` reconnect on chat (Phase 2)
- `frontend/src/upload/Upload.tsx` — `trackTraining` push-with-fallback gating (Phase 1)
- `frontend/src/components/MessageInput.tsx`, `FileTree.tsx`, modals/MCPServerModal.tsx (Phase 3)
- `App.tsx` — mount `EventStreamProvider` under `AuthWrapper` (Phase 1)

---

## Sources

- Strategic context: `durability-strategy.md`, `durability-options-deep-dive.md`
- Channel design: `notification-channel-design.md`
- Industry validation for snapshot+tail: Dify (`langgenius/dify`), Onyx (`onyx-dot-app/onyx`)
