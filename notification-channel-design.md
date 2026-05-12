# Internal Push Notification Channel — Design

## The ask

Add a backend → frontend push channel for DocsGPT. Beyond the agent's streaming response (request/response), there's nothing today.

The user note: "for use case with telegram and ntfy clearly not needed, I just want to see if there is broader benefit, for eg source uploads or some other things on docsgpt that may take time to process".

## Today

- No SSE / WebSocket / push layer exists.
- Agent answers stream via `fetch().body.getReader()` (`frontend/src/conversation/conversationHandlers.ts`) — request/response streaming, not persistent push. The connection closes when the answer ends.
- `frontend/src/components/Notification.tsx` is a static visual component, no backend wiring.
- Long operations rely on **frontend polling** (5s, 2s, or 1s intervals) with hard frontend caps (often 60s) that silently abandon work the worker is still doing.

## Where push pays off (14 use cases identified)

| Use case | Today | Pain |
|---|---|---|
| Source ingestion (upload) | 5s polling; modal must stay mounted; reload = lost progress | 4-min embed jumps in 5s chunks; navigation kills toast |
| Connector ingest (Drive/Dropbox/Reddit/GitHub) | Frontend gives up after 60s | Worker keeps churning; user sees "still loading" forever then nothing |
| Re-ingest after `manage_source_files` | Same 60s frontend cap | Directory tree only updates if poll lands on `SUCCESS` |
| Background source syncs (nightly) | Zero user surface today | Notion/Drive sync fails silently for days |
| Webhook agent runs | Zero user visibility | Webhook agent runs for 2 minutes, sends Telegram, no UI signal it ran |
| Tool approval flow | Only visible if staring at conversation | Webhook-triggered agents that pause for approval = invisible |
| Attachment processing | 2s polling burns Redis/network | Slow when tab throttles |
| MCP OAuth | Worker publishes status to Redis with TTL; frontend still polls every 1s | Closest existing "almost-push"; wasted requests |
| Long agent runs (research, workflow) | In-band stream only | Network drop mid-stream = lost answer; no resume |
| Multi-tab consistency | None | Tab A creates agent → Tab B doesn't know |
| Errors from background work | Only via polling, 60s cap | User never sees errors past cap |
| System update available | Only on next page load | Stale until refresh |
| Reminder fired (when feature lands) | N/A | In-app surface beyond Telegram/ntfy |
| Other UX paper-cuts | Many | Sharing notifications, post-upload doc list refresh dropping a round-trip, etc. |

## Approaches considered

| Approach | Effort | Verdict |
|---|---|---|
| **A. SSE on `/api/events`** *(recommended)* | 3-5 days v1 | Reuses existing fetch-streaming idiom (`conversationHandlers.ts`); Redis pub/sub for fan-out; Redis Streams (`XADD MAXLEN ~ 1000`) for 24h replay; single Flask process |
| **B. WebSockets** | 7-10 days | Overkill — bidirectional buys nothing v1 needs |
| **C. Long polling** | – | Already what we have; what we're replacing |
| **D. Web Push API** | 5-7 days | Complementary, not replacement. Different problem (closed tabs); needs PWA manifest first; v3 |
| **E. Hosted realtime (Pusher/Ably)** | 2 days | Wrong fit for OSS — vendor dependency on critical path |
| **F. Hybrid SSE + Web Push** | – | Right long-term shape; ship A first, add D when PWA manifest lands |

## Recommended: SSE with fetch streaming

Key decisions:

| Decision | Why |
|---|---|
| SSE over WebSockets | One-way is sufficient v1; SSE has built-in `Last-Event-ID` resume; no nginx WS upgrade config needed |
| Fetch streaming, not `EventSource` | Already the codebase idiom; avoids EventSource's "no headers" auth limitation (no SSE-ticket dance needed) |
| Redis Streams + pub/sub | `XADD MAXLEN ~ 1000` for 24h replay backlog; `PUBLISH` for live fan-out; multi-instance fan-out free |
| Stays in same Flask process | No sidecar; existing `WSGIMiddleware(workers=32)` thread pool handles up to 32 concurrent SSE per gunicorn worker |
| Polling stays as fallback in v1 | Push is additive; gated on `pushChannelHealthy` selector. Remove polling endpoints only after a release of clean co-existence |

## Backend design

```
application/events/__init__.py
application/events/publisher.py       # publish_user_event(user, event) → XADD + PUBLISH
application/api/events/__init__.py
application/api/events/routes.py      # /api/events SSE endpoint
```

Topic naming:

- `user:{user_id}` — primary delivery topic. Every event with a user owner publishes here.
- `conversation:{conversation_id}` — narrow topic for token-level streaming (future, not v1).
- `broadcast:system` — version updates, maintenance.
- `agent:{agent_id}` — per-agent (for shared agents). Future.

Event envelope:

```json
{
  "id": "01J...",
  "type": "source.ingest.progress",
  "ts": "2026-04-28T10:11:12.345Z",
  "user_id": "abc123",
  "topic": "user:abc123",
  "scope": { "kind": "source", "id": "<source_id>" },
  "payload": { "task_id": "...", "current": 234, "total": 600, "stage": "embedding" }
}
```

Each publish does both:

1. `XADD user:{user_id}:stream MAXLEN ~ 1000 * type ... payload ...` — durable backlog (~24h via MAXLEN).
2. `PUBLISH user:{user_id} <json>` — live fan-out to currently-subscribed SSE generators.

On reconnect, client sends `Last-Event-ID`; backend reads `XRANGE user:{user_id}:stream (last_id +`, replays missed events, then transitions to live pub/sub.

### Publisher integration in workers

Each `update_state(...)` call in `worker.py` becomes a sibling `publish_user_event(...)`:

- `ingest_worker` (`worker.py:536, 587`) — `source.ingest.progress` with `current/total`, `source.ingest.completed` with `source_id`, `token_count`.
- `embed_and_store_documents` (`embedding_pipeline.py:92-113`) — `source.ingest.embedded` per batch.
- `attachment_worker` (`worker.py:1171, 1174, 1206, 1231`) — `attachment.processing.progress`, `attachment.completed`.
- `agent_webhook_worker` (`worker.py:1262, 1287, 1299`) — `agent.run.started/completed/failed`.
- `sync_worker` (per-source, `worker.py:1139-1153`) — `source.sync.completed/failed`.
- `mcp_oauth` (`worker.py:1505-1586`) — keep existing `setex` (frontend may still poll) AND publish `mcp.oauth.*` events; frontend swaps when ready.

`update_state(...)` calls are kept — they populate `celery.AsyncResult` for `/api/task_status` and protect us from a Redis pub/sub outage. Push is **additive** in v1.

## Frontend design

```
frontend/src/events/eventStreamClient.ts    # fetch-based SSE consumer (mirrors handleFetchAnswerSteaming)
frontend/src/events/useEventStream.ts       # React hook
frontend/src/events/EventStreamProvider.tsx # mounted under <AuthWrapper> in App.tsx
frontend/src/events/dispatchEvent.ts        # switch on type → dispatch to slices
frontend/src/notifications/notificationsSlice.ts  # in-app notifications surface
```

Multi-tab dedup (v1.5): `BroadcastChannel('docsgpt:events')` per tab — first tab to receive an `event.id` broadcasts on the channel, others dedupe before dispatching.

Polling removal sequencing: existing polling loops become fallbacks gated on a `pushChannelHealthy` selector:

- `Upload.tsx:341-441` `trackTraining` — only poll if `!pushChannelHealthy || timeSinceLastEvent > 30s`.
- `MessageInput.tsx:820-876` attachment poll — same gating.
- `FileTree.tsx:316-357` reingest poll — same.
- `MCPServerModal.tsx:240-333` OAuth poll — same.

This keeps the path to "polling-only" deployments open for users who run without Redis pub/sub.

## Auth

Bearer JWT via fetch (matches every other route — `request.decoded_token` populated by `app.py:165-181`). Avoids EventSource's no-headers limitation. JWT expiry → 401 → frontend auto-reconnects with fresh token.

## Operational concerns

| Concern | Approach |
|---|---|
| Reverse proxy / Cloudflare | `X-Accel-Buffering: no`, `Cache-Control: no-store`, 15s keepalive comments (under CF 100s idle close) |
| Multi-instance scaling | Redis pub/sub natively fans out; each gunicorn replica subscribes for its own connected users — no sticky sessions needed |
| Resource ceiling | Each connection = 1 thread (in WSGI middleware pool) + 1 Redis pub/sub subscription + ~10KB heap. The 32-thread pool caps concurrent SSE per gunicorn worker; bump `_WSGI_THREADPOOL` (`application/asgi.py:14`) if needed |
| Backpressure | Slow client falls behind → drop connection → client reconnects with `Last-Event-ID` and replays from Streams |
| Mobile / iOS Safari | Aggressive ~60s idle close → keepalive ≤30s |
| Observability | Per-event log line `event.published topic=user:abc type=...`; per-connection log `event.connect user=abc gap_replayed=N`; Prometheus counters `events_published_total{type}`, `events_connections_active` |

## v1 / v2 / v3 scope

**v1 (~3-5 days):** Source ingestion only.

- 4 event types: `source.ingest.{queued,progress,completed,failed}`.
- `application/events/publisher.py` (XADD + PUBLISH wrapper).
- `application/api/events/routes.py` (one endpoint, fetch-stream-style SSE).
- Wire 4 publisher calls into `ingest_worker` + `embedding_pipeline` + `attachment_worker`.
- Frontend: `eventStreamClient.ts`, `useEventStream.ts`, mounted in `AuthWrapper`.
- `uploadSlice` updates dispatched from events.
- Keep all existing polling code intact, gated on `!pushChannelHealthy`.
- Tests: unit (publisher), integration (publish→subscribe round-trip), e2e (upload + assert toast updates from SSE).

Success criteria: a 600-chunk upload shows updates at sub-second granularity; closing the upload modal doesn't stall progress; reload mid-ingest restores progress within 1s.

**v2:**

- Add `agent.run.*` and `tool.approval.required` events. Build the in-app notifications center (slice + dropdown component).
- Migrate `MessageInput` attachment poll, `FileTree` reingest poll, `MCPServerModal` OAuth poll to push-with-poll-fallback.
- `system.update_available` cross the version-check finish line.

**v3:**

- `source.sync.*` for background syncs (the silent paper-cut).
- `BroadcastChannel` multi-tab dedup.
- `conversation:{id}` topic for in-progress agent runs (resume-after-disconnect for the long answer stream).
- Web Push API integration (option D) for closed-tab delivery, conditional on PWA manifest landing.
- Hardening: per-user rate limits on Stream replay, Prometheus metrics, runbook for "user says they didn't get a notification."

## What NOT to ship in v1

- WebSockets — no bidirectional need.
- Hosted realtime services — wrong fit for OSS.
- Web Push / service worker — different problem (closed tabs); needs PWA manifest first; user-permission-gated; defer.
- A separate sidecar process — adds deployment complexity for zero gain when the same Flask process can host SSE.
- Removing the polling endpoints — push is additive; polling is the fallback. Remove only after a release of co-existence with no incidents.
- Cross-user fanout — sharing-as-agent and team features can come later.
- Per-event ack protocol — Redis Streams `MAXLEN ~ 1000` plus `Last-Event-ID` cursor is enough.
- Topic subscriptions per page — v1 subscribes to one topic per user, full firehose. Frontend filters/dispatches client-side.

## Critical files

- `application/cache.py` — `get_redis_instance()`; the publisher wraps this
- `application/api/answer/routes/base.py` — for the existing SSE/streaming pattern to mirror
- `application/api/answer/routes/stream.py` — already uses `X-Accel-Buffering: no` for SSE; the legacy `/stream` route does not — pattern partially established
- `application/asgi.py:14` — `WSGIMiddleware(workers=32)` thread pool that bounds concurrent SSE per worker
- `application/worker.py` — where publisher calls get added per task
- `frontend/src/conversation/conversationHandlers.ts:147-189` — existing fetch-streaming SSE parser to reuse for the new channel
- `frontend/src/upload/Upload.tsx:341-441` — `trackTraining` polling loop to gate behind `pushChannelHealthy`
