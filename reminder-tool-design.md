# Scheduled Reminder / Agent Wake-Up Tool — Design

## The ask

Add a new agent tool that lets the LLM "schedule a future agent action" — a `sleep` / `wake-up` primitive for agents. Concrete user flow:

1. User: "Remind me to drink water in 1 hour via Telegram"
2. Agent calls `schedule_wakeup(delay="1h", instruction="...")`
3. Tool returns immediately, agent says "ok"
4. ~1 hour later~ — system wakes the agent back up with prior context + the saved instruction
5. Agent calls connected Telegram tool to deliver the reminder

This is durable, scheduled agent execution with context resumption — closer to "wake the agent later with prior context + a fresh instruction" than a plain push notification.

## What DocsGPT already has

The infra is largely in place. The new feature is mostly a tool wrapper + a wake-up worker that reuses existing patterns.

| Need | Already in repo |
|---|---|
| Background scheduler | Celery + Redis + `celery-redbeat` (`application/celeryconfig.py`) |
| "Wake an agent with no live session" | `agent_webhook_worker` + `run_agent_logic` (`application/worker.py:305,1250`) — manufactures `decoded_token = {"sub": owner}`, rebuilds the agent via `AgentCreator`, drains `agent.gen()` |
| Reconstitute agent from saved JSONB state | `ContinuationService` + `StreamProcessor.resume_from_tool_actions` (`application/api/answer/services/stream_processor.py:900`) — canonical resume path used today for tool-approval pauses |
| Per-user tool data pattern | `notes` / `todo_list` / `memory` tools — auto-discovered by `ToolManager.load_tools()`, scoped via injected `tool_id` (UUID from `user_tools`) and `user_id` |
| Schedule-row template | `pending_tool_state` table (`application/storage/db/models.py:366`) — same shape we'd want: per-user JSONB blob with TTL janitor |
| Encrypted per-user credentials | `ToolExecutor._get_or_load_tool` decrypts each user's tool credentials from `user_tools.config.encrypted_credentials` keyed by `user_id`, so once you know the `user_id` you can re-load all their connected tools at wake time |
| Outbound delivery channels | `telegram.py`, `ntfy.py` already exist as tools |

**Critical implication:** there is no SSE/WebSocket push to the frontend. The only way to reach a user with no open tab is via a connected outbound tool (Telegram/ntfy/etc.). This matches the use case exactly.

## Architectural options

| Option | How it fires | Pros | Cons |
|---|---|---|---|
| **A. Celery `apply_async(countdown=…)`** | Each reminder = its own queued task with ETA | Idiomatic Celery; cancel via `revoke()` | Reliability tied to Redis durability; harder to inspect |
| **B. Redis sorted-set + 30s poller** | `ZADD scheduled_reminders <epoch> <id>`; poller `ZRANGEBYSCORE` | Easy to dump/inspect; no per-task overhead | Up to 30s lateness; extra moving part |
| **C. Postgres table + 30s poller** *(recommended)* | PG row with `scheduled_for`; periodic Celery task with `FOR UPDATE SKIP LOCKED` | One source of truth; survives Redis flush; same pattern as existing `cleanup_pending_tool_state` | 30s lateness; tiny extra PG load |
| **D. Per-reminder RedBeat entry** | Ad-hoc beat schedule per reminder | Infra already there | RedBeat is for periodic, not one-shots — unidiomatic |

**Recommended: Option C.** Mirrors the `pending_tool_state` shape the team already understands. PG-as-truth means an operator can `SELECT * FROM scheduled_agent_actions WHERE status='pending'` to debug. The 30s window is invisible for "remind me in an hour" UX.

## Tool surface

Mirror Cloudflare Agents SDK's `this.schedule(...)` — the cleanest public API for this pattern:

```python
schedule_wakeup(when: "1h" | iso8601 | cron, instruction: str, idempotency_key?: str)
list_scheduled_wakeups()
cancel_scheduled_wakeup(id)
```

Display name in the tools UI: **"Scheduled Actions"** (broader than "reminders"). Follows the per-user tool pattern of `notes` / `todo_list`: enabled per-user from the tools UI, scoped via `(user_id, tool_id)`.

## Storage schema

New table `scheduled_agent_actions`, sibling to `pending_tool_state`:

| column | type | purpose |
|---|---|---|
| `id` | UUID PK | reminder id surfaced to the LLM |
| `user_id` | Text | owner |
| `tool_id` | UUID FK `user_tools` | scopes list/cancel ops |
| `conversation_id` | UUID FK `conversations` (nullable) | for context |
| `agent_id` | UUID FK `agents` (nullable) | optional |
| `instruction` | Text | natural-language note from "past agent" to "future agent" |
| `agent_config` | JSONB | snapshot like `pending_tool_state.agent_config` (model_id, llm_name, agent_type, prompt, etc.) |
| `status` | Text | `pending` / `firing` / `delivered` / `failed` / `cancelled` |
| `scheduled_for` | timestamptz | wall-clock fire time (also drives a reaper for lost tasks) |
| `created_at` | timestamptz | |
| `last_attempt_at` / `attempt_count` | for retries | |
| `idempotency_key` | Text (nullable, unique with user_id) | dedup |

Migration: `application/alembic/versions/0004_scheduled_agent_actions.py`.

## Wake-up worker behavior

1. Periodic Celery task `dispatch_scheduled_reminders` (registered in `setup_periodic_tasks`) ticks every 30s.
2. `SELECT … FROM scheduled_agent_actions WHERE status='pending' AND scheduled_for <= now() FOR UPDATE SKIP LOCKED LIMIT 100`.
3. For each row: mark `firing`, dispatch `wake_scheduled_reminder.delay(reminder_id)`.
4. Worker function `scheduled_reminder_worker` (sibling of `agent_webhook_worker` in `application/worker.py`):
   - Load reminder row, agent config, conversation
   - Reload user's currently-active tools (so a Telegram tool added *after* scheduling is still available — better UX than a frozen snapshot)
   - Build agent via `AgentCreator.create_agent(agent_type, ...)` exactly as `run_agent_logic` does
   - Inject synthetic query: `[Scheduled wake-up at <ts>] You previously asked yourself to: <instruction>. Carry out the task now using the available tools.`
   - Drain `agent.gen()`
   - Append the resumed turn to the original `conversation_id` via `ConversationService.save_conversation` (so the user sees it next time they open the conversation)
   - Mark `delivered`

## Auth on wake-up

No live `decoded_token` from a request. Synthesize: `decoded_token = {"sub": user_id}` (mirrors `run_agent_logic` line 341). The user's encrypted tool credentials are decrypted by `ToolExecutor._get_or_load_tool` from `user_tools.config.encrypted_credentials` using the per-user PBKDF2 key, which is keyed off the `user_id` we just synthesized. So as long as we know `user_id`, we can transparently load all the user's connected tools with their credentials — no separate auth-attach step needed.

## Failure modes & mitigations

| Failure | Mitigation |
|---|---|
| Celery loses the task | PG row is source of truth; janitor sweeps `pending` rows past `scheduled_for + grace` and re-enqueues |
| Worker dies mid-fire | `FOR UPDATE SKIP LOCKED` + `status='firing'` flip prevents replay; janitor moves stuck `firing` past 5-min grace back to `pending` for retry up to N attempts |
| Delivery tool removed between schedule and fire | LLM at fire time has no `telegram_send_message`; either falls back to another connected tool, or appends an in-conversation message ("tried to remind you about X but the Telegram tool is no longer connected") |
| LLM provider down at fire time | Standard Celery `autoretry_for=(SomeError,), retry_backoff=True, max_retries=3`; after max retries → `failed` with reason logged in `user_logs` |
| Token-budget abuse | `MAX_PENDING_REMINDERS_PER_USER=50`, `MAX_REMINDER_DELAY_SECONDS=30*24*3600` — anything longer is a job queue, not a reminder |

## Cost & rate limits

Each fire = a fresh full-context LLM call. For long conversations this is expensive. Mitigations:

- The existing compression layer trims context.
- The agent who *schedules* the reminder can be told in its system prompt to "summarize the relevant context inline in the `instruction` so the future agent doesn't need conversation history."
- Offer `use_full_context: bool = false` arg on `schedule_wakeup`. By default the wake-up runs as a fresh one-shot agent with only `instruction` as input (cheap mode); only when explicitly true does it run against full history (expensive mode).
- Optionally teach the model about the 5-minute prompt-cache TTL via the tool description — Anthropic's own `ScheduleWakeup` does this so the model picks delays that either stay sub-300s (cache stays warm) or commit to a longer wait that amortizes the miss.

## v1 vs v2 scope

**v1 (~1 sprint):**

- Migration `0004_scheduled_agent_actions.py` (table + indexes).
- `application/storage/db/repositories/scheduled_agent_actions.py` (insert / list_active / get / mark_status / cleanup).
- `application/agents/tools/scheduled_action.py` — Tool subclass with three actions: `schedule_wakeup`, `list_scheduled_wakeups`, `cancel_scheduled_wakeup`. Follows the `notes`/`todo_list` per-user pattern exactly.
- Refactor `application/worker.py:run_agent_logic` to accept optional `conversation_id` + `synthetic_query` so it's reusable.
- New worker function `scheduled_reminder_worker` in `application/worker.py`.
- New Celery task `wake_scheduled_reminder(reminder_id)` and periodic `dispatch_scheduled_reminders` in `application/api/user/tasks.py`.
- 2 settings in `application/core/settings.py`: `SCHEDULED_ACTION_MAX_PENDING_PER_USER`, `SCHEDULED_ACTION_MAX_DELAY_SECONDS`.

This v1 covers the user's exact flow ("Remind me to drink water in 1 hour via Telegram") cleanly: agent schedules, worker re-runs the agent against the same conversation 1 hour later, agent calls `telegram_send_message`. The reminder also lands in the conversation history so it's visible next time the user opens DocsGPT.

**v2 additions:**

- Optional `notify_user(text)` action on the scheduling tool itself (fallback when no outbound tool is connected).
- `update_reminder(id, …)` action.
- `recurrence: cron|rrule` arg on `schedule_wakeup` — at that point recurring reminders migrate to RedBeat entries (which is what RedBeat is actually built for); one-shots still use the PG poller.
- `/api/scheduled_actions` Flask blueprint (list/cancel/edit).
- Frontend "Scheduled actions" tab in user settings.
- Push channel integration (when the notification system lands) — `reminder.fired` event surfaces in-app for users who happen to have DocsGPT open.

## Critical files

- `application/agents/tools/notes.py` — template for per-user tool pattern (`_pg_enabled()` guard, `tool_id` injection, `user_id` scoping)
- `application/storage/db/repositories/pending_tool_state.py` — template for the new repository
- `application/worker.py` (lines 305 `run_agent_logic` and 1250 `agent_webhook_worker`) — to be extended/mirrored for the wake-up worker
- `application/api/user/tasks.py` — where `wake_scheduled_reminder` and `dispatch_scheduled_reminders` register, alongside existing `cleanup_pending_tool_state`
- `application/api/answer/services/stream_processor.py:900` `resume_from_tool_actions` — canonical reconstitute-an-agent-from-saved-state code path; the wake-up worker should follow this shape rather than reinvent it

## External patterns referenced

- **Cloudflare Agents SDK** `this.schedule(seconds, "callback", payload)` — the cleanest public API for this pattern. One agent instance per user, hibernation = zero idle cost, built-in `cancelSchedule` / `getSchedules`. Mental model to copy even though we don't run on CF.
- **Inngest** / **Trigger.dev** — both have published "scheduled email reminder" examples that match this spec exactly using `await wait.until(date)` durable sleep.
- **Anthropic's `ScheduleWakeup` tool** in Claude Code — the cleanest tool-API reference, including teaching the model about the 5-minute prompt-cache TTL via the tool description so it picks sensible delays.
- **Letta / Lettabot** — silent-by-default delivery: woken agents must explicitly invoke a send tool to break silence. Worth copying as an anti-spam guardrail.
- **Autobot** (Crystal-language framework) — cron-fired prompts enter the agent through the same message bus as user input, so they appear in session history naturally. Best architectural insight for "the wake-up turn becomes a real conversation message."
