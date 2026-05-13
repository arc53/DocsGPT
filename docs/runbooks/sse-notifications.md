# SSE Notifications Runbook

> Operations guide for "user says they didn't get a notification" — and
> the related "the bell never lights up" / "my upload toast hangs" /
> "the chat answer doesn't reconnect" symptoms.

The user-facing notifications channel is the SSE pipe at
`/api/events` plus per-message reconnects at
`/api/messages/<id>/events`. This document maps a user complaint to
the diagnostic that surfaces the cause.

---

## TL;DR — first 60 seconds

Run these three commands in parallel before anything else:

```bash
# 1) Is Redis up and serving the pipe? Should print PONG instantly.
redis-cli -n 2 PING

# 2) Anyone subscribed to the channel right now? Numbers per channel.
redis-cli -n 2 PUBSUB NUMSUB user:<user_id>

# 3) Is the user's backlog populated? Returns the count of journaled events.
redis-cli -n 2 XLEN user:<user_id>:stream
```

- `PING` failing → Redis is the problem. Skip to "Redis-down".
- `NUMSUB user:<user_id>` returns 0 → no client connected. Skip to "Client never connects".
- `XLEN user:<user_id>:stream` returns 0 or low → publisher isn't writing. Skip to "Publisher silent".
- All three look healthy → the events are flowing on the wire; the issue is downstream of the slice (UI rendering, toast suppression, etc.). Skip to "Events flowing but UI silent".

---

## Architecture cheat-sheet

```
Worker (publish_user_event)             Frontend tab
        │                                    ▲
        ▼                                    │  GET /api/events SSE
  Redis Streams: XADD                  Flask route
  user:<id>:stream  ──────────────►   replay_backlog (snapshot)
        │                                    +
        ▼                              Topic.subscribe (live tail)
  Redis pub/sub: PUBLISH                     │
  user:<id>  ────────────────────────────────┘
```

**Source of truth:**
- Persistent journal: Redis Stream `user:<user_id>:stream`, capped at
  `EVENTS_STREAM_MAXLEN` (default 1000) entries via `MAXLEN ~`. ~24h
  at typical event rates.
- Live fan-out: Redis pub/sub channel `user:<user_id>`. No durability;
  subscribers must be attached at publish time.

The chat-stream pipe is separate, parallel infrastructure:
- Journal: Postgres `message_events` table.
- Live fan-out: Redis pub/sub `channel:<message_id>`.

Same patterns, different durability layer. This doc covers both;
they share most diagnostic commands.

---

## Symptom → diagnostic map

### A. "I uploaded a source and the toast never appeared"

User flow: chat → upload → expect toast.

| Step                                              | Command                                                       | Expect                                          |
| ------------------------------------------------- | ------------------------------------------------------------- | ----------------------------------------------- |
| Worker received the task                          | `tail -f celery.log` filtered by user                         | `ingest_worker` start log line                  |
| Worker published the queued event                 | `redis-cli -n 2 XREVRANGE user:<id>:stream + - COUNT 5`       | A `source.ingest.queued` entry within seconds   |
| Frontend got it                                   | DevTools → Network → `/api/events` → EventStream tab          | `data: {"type":"source.ingest.queued",...}`     |
| Slice updated                                     | Redux DevTools → state.upload.tasks                           | Task with matching `sourceId`, `status:'training'` |

If the worker's queued log line is there but the XADD didn't land →
look for a `publish_user_event payload not JSON-serializable` warning
in the worker log (the publisher swallows `TypeError`).

If the XADD landed but the frontend never received it → check
`PUBSUB NUMSUB user:<id>` while the user is on the page. If 0, the
SSE connection isn't subscribed; skip to "Client never connects".

If the frontend received it but the toast didn't render → the
`uploadSlice` extraReducer requires `task.sourceId` to match the
event's `scope.id`. Check the upload route returned `source_id` in
its POST response (the upload, connector, and reingest paths all
include it). Idempotent / cached responses must also include
`source_id` (`_claim_task_or_get_cached`).

### B. "The bell badge never goes up"

There is no bell — the global notifications surface is per-event
toasts, not an aggregated counter. If the user is on an old build,
`Cmd-Shift-R` to bypass cache. The surfaces they're looking for are
`UploadToast` for source uploads and `ToolApprovalToast` for
tool-approval events.

### C. "My chat answer froze mid-stream and never recovered"

User flow: ask question → answer streaming → network blip → answer
stops; should reconnect.

```bash
# Was the original message reserved in PG?
psql -c "SELECT id, status, prompt FROM conversation_messages \
  WHERE user_id = '<user>' ORDER BY timestamp DESC LIMIT 5;"

# Did the journal capture events past the user's last-seen seq?
psql -c "SELECT sequence_no, event_type FROM message_events \
  WHERE message_id = '<id>' ORDER BY sequence_no;"

# Is the live tail still producing? (subscribe and watch)
redis-cli -n 2 SUBSCRIBE channel:<message_id>
```

The frontend should reconnect via `GET /api/messages/<id>/events`
when the original POST stream closes without a typed `end` or
`error` event. If it's not reconnecting, `console.warn('Stream
reconnect failed', ...)` will be in the browser console — the
reconnect HTTP errored. Common cases:

- The user's JWT rotated mid-stream → 401 on the GET. Frontend
  doesn't auto-refresh; the user reloads.
- The user is on a different host than the API and CORS is rejecting
  the GET → check `application/asgi.py` allow-headers.

### D. "The dev install never delivers any notifications at all"

Default `AUTH_TYPE` unset means `decoded_token = {"sub": "local"}`
for every request. The SSE client connects without the
`Authorization` header in this case, and `user:local:stream` is
the shared channel everything goes to. If the user has multiple dev
machines pointing at the same Redis, they will see each other's
events. Confirm with:

```bash
redis-cli -n 2 KEYS 'user:local:*'
```

If multiple deployments share the Redis, document that as a known
multi-user-on-local-channel limitation. Set `AUTH_TYPE=simple_jwt`
to scope per-user.

### E. "The notifications channel was working, then suddenly stopped after the user reloaded the page"

Likely path: `backlog.truncated` event fired, the slice cleared
`lastEventId` to null, the closure was carrying the same stale id and
re-tripped the same truncation on every reconnect. **Verify the user
is on a current build — `eventStreamClient.ts` must re-read
`lastEventId = opts.getLastEventId();` without a truthy guard so the
null clear propagates into the next reconnect.**

### F. "I keep getting 429 on /api/events"

The per-user concurrent-connection cap (`SSE_MAX_CONCURRENT_PER_USER`,
default 8) refused the connection. User has too many tabs open or a
runaway reconnect loop. `redis-cli -n 2 GET user:<id>:sse_count`
shows the live counter; the TTL is 1h from the last connection
attempt (rolling — every INCR re-seeds it), so the key only ages
out after the user stops reconnecting for a full hour.

If the count is wedged high without explanation, the
counter-DECR-in-finally path didn't run (worker SIGKILL, OOM). Wait
for the TTL or `redis-cli -n 2 DEL user:<id>:sse_count` to reset.

### G. "Replay snapshot stops at 200 events"

The route caps each replay at `EVENTS_REPLAY_MAX_PER_REQUEST`
(default 200). The cap is intentionally **silent** — the route does NOT
emit a `backlog.truncated` notice for cap-hit. The 200 entries each
carry their own `id:` header, so the frontend's slice cursor
advances to the most-recent delivered id. Next reconnect sends
`last_event_id=<max_replayed>` and the snapshot resumes from there.
A user that was 1000 entries behind catches up over ~5 reconnects.

If the user reports getting HTTP 429 on `/api/events` despite being
well under `SSE_MAX_CONCURRENT_PER_USER`, they hit the windowed
replay budget (`EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW`, default
30 / `EVENTS_REPLAY_BUDGET_WINDOW_SECONDS` 60s). The route refuses
the connection so the slice cursor stays pinned at whatever value
it had; the frontend backs off and the next reconnect (after the
window rolls) gets the proper snapshot. Serving the live tail
without a snapshot used to be the behavior here, but that let the
client advance `lastEventId` past entries it never received,
permanently stranding the un-replayed window — so the route now
429s instead. `redis-cli -n 2 GET user:<id>:replay_count` shows the
current counter; TTL is the window size.

`backlog.truncated` is emitted ONLY when the client's
`Last-Event-ID` has slid off the MAXLEN'd window — i.e. the journal
is genuinely gone past the cursor and the frontend should clear the
slice cursor and refetch state. Treating cap-hit or
budget-exhaustion the same way would lock the user into re-receiving
the oldest 200 entries on every reconnect (the cursor would clear,
the snapshot would re-serve from the start, the cap would re-trip).

### H. "User says push notifications stopped after a deploy"

- Pull `event.published topic=user:<id> type=...` from the worker
  logs to confirm the publisher is still firing.
- Pull `event.connect user=<id>` from the API logs to confirm the
  client is reconnecting.
- Check the gunicorn worker count and `WSGIMiddleware(workers=32)` —
  if the deploy reduced worker count, the per-user cap is still 8
  but total concurrent SSE connections are bounded by `gunicorn
  workers × 32`. A capacity miss looks like users randomly getting
  429'd.

---

## Common failure modes

### Redis-down

Symptoms: `/api/events` returns 200 but emits only `: connected`
then the body closes. `XLEN` and `PUBLISH` both fail. The publisher's
`record_event` swallows the failure and returns False; the live tail
publish also drops on the floor. Frontend retries forever with
exponential backoff.

Resolution: bring Redis back. The journal is gone (was in-memory
only — Streams persist within a single Redis instance, no replication
configured). New events flow as soon as Redis comes back.

### `AUTH_TYPE` misconfigured = sub:"local" cross-stream

Symptoms: every user shares `user:local:stream`. Any user sees
everyone else's notifications.

Resolution: set `AUTH_TYPE=simple_jwt` (or `session_jwt`) in `.env`.
The events route logs a one-time WARNING per process when
`sub == "local"` is observed. A repeat WARNING after a restart
confirms the misconfiguration.

### MAXLEN trimmed past Last-Event-ID

Symptoms: client reconnects with `last_event_id=X`, snapshot returns
the entire MAXLEN'd backlog (because X is older than the oldest
retained entry). Old events appear duplicated.

Detection: the route's `_oldest_retained_id` check emits
`backlog.truncated` when this case fires. Frontend's
`dispatchSSEEvent` clears `lastEventId` so the next reconnect starts
fresh.

If the WARNING isn't firing but symptoms match: the user's client
may have a corrupt cached `lastEventId`. `localStorage` doesn't
store this state; check Redux state via DevTools.

### Stale event-stream client

Symptoms: events visible in `XRANGE` but the frontend slice doesn't
update.

```bash
# Is the client subscribed?
redis-cli -n 2 PUBSUB NUMSUB user:<id>

# When did its connection start?
grep "event.connect user=<id>" /var/log/docsgpt.log | tail -3
```

If `NUMSUB` is 0 and no recent `event.connect`, the user's tab is
closed or the connection died and never reconnected. Push them to
reload.

### Publisher silent

Symptoms: worker is processing the task (Celery says SUCCESS), but
no XADD and no PUBLISH. User sees no events.

```bash
# Was the publisher import error suppressed?
grep "publish_user_event" /var/log/celery.log | grep -i "warn\|error" | tail -20

# Is push disabled?
grep "ENABLE_SSE_PUSH" /var/log/docsgpt.log | tail -5
```

`ENABLE_SSE_PUSH=False` in `.env` would silence the publisher
globally. Useful for incident response if a runaway publisher is
DoS'ing Redis; toggle off, fix root cause, toggle on.

---

## Useful one-liners

```bash
# Watch a user's live event stream in real time (all events, all types)
redis-cli -n 2 PSUBSCRIBE 'user:*' | grep "user:<id>"

# Last 10 events the user would see on reconnect
redis-cli -n 2 XREVRANGE user:<id>:stream + - COUNT 10

# Live count of subscribed clients per user
redis-cli -n 2 PUBSUB NUMSUB $(redis-cli -n 2 PUBSUB CHANNELS 'user:*')

# Trim a runaway stream (CAREFUL — destroys backlog for all current
# subscribers; OK after explaining to the user)
redis-cli -n 2 XTRIM user:<id>:stream MAXLEN 0

# Clear a wedged concurrent-connection counter
redis-cli -n 2 DEL user:<id>:sse_count

# Force-flip every client to re-snapshot (drop the stream key entirely
# — destroys the backlog; clients reconnect with their last id and
# get a backlog.truncated)
redis-cli -n 2 DEL user:<id>:stream
```

---

## Settings reference

Everything in `application/core/settings.py`:

| Setting                                       | Default | Purpose                                       |
| --------------------------------------------- | ------- | --------------------------------------------- |
| `ENABLE_SSE_PUSH`                             | `True`  | Master switch. False = publisher no-ops, route serves "push_disabled" comment. |
| `EVENTS_STREAM_MAXLEN`                        | `1000`  | Per-user backlog cap. Approximate via `XADD MAXLEN ~`. |
| `SSE_KEEPALIVE_SECONDS`                       | `15`    | Comment-frame cadence. Must sit under reverse-proxy idle close. |
| `SSE_MAX_CONCURRENT_PER_USER`                 | `8`     | Cap on simultaneous SSE connections per user. 0 = disabled. |
| `EVENTS_REPLAY_MAX_PER_REQUEST`               | `200`   | Hard cap on snapshot rows per request. |
| `EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW`    | `30`    | Per-user replays per window. 0 = disabled. |
| `EVENTS_REPLAY_BUDGET_WINDOW_SECONDS`         | `60`    | Window length. |
| `MESSAGE_EVENTS_RETENTION_DAYS`               | `14`    | Retention for the `message_events` journal; `cleanup_message_events` beat task deletes older rows. |

---

## Known limitations

### Each tab runs its own SSE connection

There is no cross-tab dedup. Every tab open to the app holds its
own SSE connection and dispatches every received event into its
own Redux store, so a user with N tabs open will see N copies of
each toast. With `SSE_MAX_CONCURRENT_PER_USER=8` (the default) a
heavy multi-tab user can also hit the connection cap and start
seeing 429s. Cross-tab dedup via a `BroadcastChannel` ring +
`navigator.locks`-based leader election is tracked as future work.

### `/c/<unknown-id>` normalises to `/c/new`

If a user navigates to a conversation id that isn't in their
loaded list, the conversation route rewrites the URL to `/c/new`.
`ToolApprovalToast`'s gate uses `useMatch('/c/:conversationId')`,
so for the brief window after the rewrite the toast may surface
for a conversation the user *thought* they were already viewing.
Pre-existing route behaviour; not a notifications regression.

### Terminal events un-dismiss running uploads

`frontend/src/upload/uploadSlice.ts` sets `dismissed: false` when
an upload reaches `completed` or `failed`. If the user dismissed a
running task and the terminal SSE arrives later, the toast pops
back. Intentional ("notify the user it's done"); revisit if the
re-surface UX is too aggressive for v2.

### Werkzeug doesn't auto-reload route files

The dev server (`flask run`) doesn't watch
`application/api/events/routes.py` for changes by default.
After editing the route, restart Flask manually — `--reload`
isn't on. (Production gunicorn reloads via deploy.)

### MCP OAuth completion can fall outside the user stream's MAXLEN window

`get_oauth_status` scans up to `EVENTS_STREAM_MAXLEN` (~1000) entries via `XREVRANGE`. If the user has a high-rate ingest running concurrent with the OAuth handshake, the `mcp.oauth.completed` envelope can be trimmed off the back before they click Save. Symptom: backend returns "OAuth failed or not completed" even though the popup completed successfully.

Mitigation today: bump `EVENTS_STREAM_MAXLEN` per-deployment if your users routinely flood the channel during OAuth flows. A dedicated short-TTL Redis key for OAuth task results is tracked as a follow-up.

### React StrictMode double-mounts SSE

In dev, React 18 StrictMode mounts → unmounts → remounts every
component, briefly opening two SSE connections per tab before the
first is aborted. With `SSE_MAX_CONCURRENT_PER_USER=8` and 4–5
tabs open concurrently you can transiently hit the cap and see
HTTP 429 on cold-load. The first connection's counter increment
fires before the AbortController-induced disconnect can decrement
it. Production (single mount, no StrictMode) is unaffected; raise
the cap in dev or accept transient 429s.
