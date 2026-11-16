"""Body of ``execute_scheduled_run`` — runs a single agent execution.

Not a DURABLE_TASK: agent runs have side effects (messages, CRM writes)
and blind auto-retry would double them. Failures after agent.gen starts
are terminal and recorded; only the pre-start load is retry-safe.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import text as sql_text

from docsgpt.agents.headless_runner import run_agent_headless
from docsgpt.core.settings import settings
from docsgpt.events.publisher import publish_user_event
from docsgpt.quotas.agent_limits import AgentLimitExceeded
from docsgpt.quotas.pause import NO_PAYER, PAYER_OUT_OF_ALLOWANCE, PAUSE_REASONS, Pause, schedule_pause
from docsgpt.quotas.service import NoPayerError, QuotaExceededError
from docsgpt.storage.db.engine import get_engine
from docsgpt.storage.db.repositories.agents import agent_row_to_dict
from docsgpt.storage.db.repositories.conversations import (
    ConversationsRepository,
)
from docsgpt.storage.db.repositories.schedule_runs import (
    ScheduleRunsRepository,
)
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import is_principal_id

logger = logging.getLogger(__name__)


# Cap output verbatim in the run log; beyond the cap we keep the head and stamp output_truncated.
_OUTPUT_CAP_CHARS = 24_000


def _agent_config_for_schedule(schedule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve the agent row (agent-bound) or build an ephemeral classic config.

    For agentless schedules (``agent_id IS NULL``), the worker constructs an
    in-memory agent shape carrying just enough fields for ``run_agent_headless``:
    classic agent type, system-default retriever/chunks/prompt, no source, and
    the optional ``model_id`` override. The runtime toolset is rebuilt by
    ``ToolExecutor`` at fire time (current ``user_tools`` + non-disabled,
    non-headless-excluded defaults), so a snapshot here would be dead code.
    """
    if schedule.get("agent_id"):
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                sql_text("SELECT * FROM agents WHERE id = CAST(:id AS uuid)"),
                {"id": str(schedule["agent_id"])},
            ).fetchone()
        return agent_row_to_dict(row)
    return _ephemeral_agent_for_agentless(schedule)


def _ephemeral_agent_for_agentless(
    schedule: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Build an agent-shaped config for a schedule with no parent agent."""
    # ``agent_config["tools"]`` is intentionally omitted: ``run_agent_headless``
    # never reads it. The runtime toolset is rebuilt by
    # ``ToolExecutor._get_user_tools(owner)`` at fire time — same dereference
    # the agent-bound path uses, so a tool added/disabled after creation is
    # reflected. Headless mode there filters chat-only tools (``scheduler``).
    user_id = schedule.get("user_id")
    if not user_id:
        return None
    return {
        "id": None,
        "user_id": user_id,
        "agent_type": "classic",
        "retriever": "classic",
        "chunks": 6,
        "prompt_id": "default",
        "source_id": None,
        "default_model_id": schedule.get("model_id") or "",
    }


def _load_chat_history(schedule: Dict[str, Any]) -> list:
    """Originating conversation history (one-time only; recurring has none)."""
    origin = schedule.get("origin_conversation_id")
    if not origin or schedule.get("trigger_type") != "once":
        return []
    user_id = schedule.get("user_id")
    if not user_id:
        return []
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conv = ConversationsRepository(conn).get_any(str(origin), user_id)
            if conv is None:
                return []
            messages = ConversationsRepository(conn).get_messages(str(conv["id"]))
    except Exception:
        logger.exception("scheduler: failed loading chat history")
        return []
    history: list = []
    for msg in messages:
        if msg.get("prompt") and msg.get("response"):
            history.append({
                "prompt": msg["prompt"],
                "response": msg["response"],
            })
    return history


def _publish_run_event(
    event_type: str, run: Dict[str, Any], schedule: Dict[str, Any], **extra: Any
) -> None:
    """Best-effort SSE publish for a scheduler run state transition."""
    user_id = run.get("user_id") or schedule.get("user_id")
    if not user_id:
        return
    agent_id_raw = schedule.get("agent_id")
    payload = {
        "run_id": str(run["id"]),
        "schedule_id": str(schedule["id"]),
        "agent_id": str(agent_id_raw) if agent_id_raw else None,
        "trigger_type": schedule.get("trigger_type"),
        "status": run.get("status"),
        **extra,
    }
    try:
        publish_user_event(
            user_id,
            event_type,
            payload,
            scope={"kind": "schedule", "id": str(schedule["id"])},
        )
    except Exception:
        logger.exception(
            "scheduler: SSE publish failed event=%s run=%s",
            event_type, run.get("id"),
        )


def _publish_message_appended(
    user_id: str,
    conversation_id: str,
    message: Dict[str, Any],
    schedule_id: str,
    run_id: str,
) -> None:
    """SSE message-appended event for a one-time run's chat turn."""
    try:
        publish_user_event(
            user_id,
            "schedule.message.appended",
            {
                "conversation_id": str(conversation_id),
                "message_id": str(message["id"]),
                "schedule_id": str(schedule_id),
                "run_id": str(run_id),
                "position": int(message.get("position", 0)),
            },
            scope={"kind": "conversation", "id": str(conversation_id)},
        )
    except Exception:
        logger.exception(
            "scheduler: message.appended publish failed run=%s", run_id,
        )


def _notify_appended(schedule: Dict[str, Any], message: Dict[str, Any], outcome: Dict[str, Any]) -> None:
    """Tell the user a one-time run answered in its conversation (a toast, a push or an unread mark).

    Like a continuation's answer: nothing while the user watches that
    conversation (``notify_user`` decides). Never raises.
    """
    from docsgpt.notifications.kinds import plain_preview
    from docsgpt.notifications.notify import notify_user

    conversation_id = str(message["conversation_id"])
    notify_user(
        user_id=str(schedule.get("user_id")),
        conversation_id=conversation_id,
        kind="schedule",
        title=_schedule_title(schedule),
        body=plain_preview(outcome.get("answer") or ""),
        url=f"/c/{conversation_id}",
    )


def _schedule_title(schedule: Dict[str, Any]) -> str:
    """A schedule as a notification names it: its name, else the head of its instruction."""
    from docsgpt.notifications.kinds import plain_preview

    title = (schedule.get("name") or "").strip() or plain_preview(schedule.get("instruction") or "", 120)
    return title or "Scheduled task"


#: Characters of a run's error a notification shows.
_FAILURE_LINE_CHARS = 200


def _failure_line(error_type: Optional[str], error_text: Optional[str]) -> str:
    """A failed run's error as one line: its first line (a traceback's message, not its frames)."""
    from docsgpt.notifications.kinds import plain_preview

    first = next((line for line in str(error_text or "").splitlines() if line.strip()), "")
    return plain_preview(first or error_type or "", _FAILURE_LINE_CHARS)


def _notify_failing(schedule: Dict[str, Any], kind: str, error_type: Optional[str], error_text: Optional[str]) -> None:
    """Tell a recurring schedule's owner it paused itself (``schedule_paused``) or started failing.

    A recurring run has no conversation to land in, so without this only an
    open tab ever learns of it. Open goes to the schedule. Never raises.
    """
    from docsgpt.notifications.notify import notify_user

    schedule_id = str(schedule["id"])
    notify_user(
        user_id=str(schedule.get("user_id")),
        conversation_id=None,
        kind=kind,
        title=_schedule_title(schedule)[:200],
        body=_failure_line(error_type, error_text),
        url=f"/activity/schedules?schedule={schedule_id}",
        schedule_id=schedule_id,
    )


def _counts_toward_autopause(run: Dict[str, Any], error_type: Optional[str] = None) -> bool:
    """Whether a failed run bumps the failure count.

    A Run now is watched by whoever started it, so it doesn't. Nor does a run
    stopped for its payer (out of allowance mid-run): that clears by itself,
    and auto-pause would leave the schedule off after it had.

    Args:
        run: The run.
        error_type: Why it failed, when known.

    Returns:
        True when the failure counts.
    """
    return run.get("trigger_source") != "manual" and error_type not in PAUSE_REASONS


def _autopause_if_due(schedules_repo: SchedulesRepository, schedule: Dict[str, Any], failures: int) -> bool:
    """Pause a recurring schedule that has failed ``SCHEDULE_AUTOPAUSE_FAILURES`` runs in a row; True if it paused."""
    if (
        settings.SCHEDULE_AUTOPAUSE_FAILURES > 0
        and failures >= settings.SCHEDULE_AUTOPAUSE_FAILURES
        and schedule.get("trigger_type") == "recurring"
    ):
        return schedules_repo.autopause(str(schedule["id"]))
    return False


def _after_failure(
    schedule: Dict[str, Any],
    run: Dict[str, Any],
    autopaused: bool,
    failures: int,
    error_type: Optional[str],
    error_text: Optional[str],
) -> None:
    """Publish a pause and tell the owner: once per pause, or on the first failure in a row when switched on."""
    if autopaused:
        _publish_run_event(
            "schedule.autopaused",
            run,
            schedule,
            consecutive_failure_count=settings.SCHEDULE_AUTOPAUSE_FAILURES,
        )
        # Once per pause: ``autopause`` flips only an active schedule, so the
        # runs a paused one still gets (Run now) don't notify again.
        _notify_failing(schedule, "schedule_paused", error_type, error_text)
    elif (
        failures == 1
        and settings.SCHEDULE_NOTIFY_RECURRING_FAILURES
        and schedule.get("trigger_type") == "recurring"
        and run.get("trigger_source") != "manual"
    ):
        _notify_failing(schedule, "schedule_failed", error_type, error_text)


def _append_one_time_turn(
    schedule: Dict[str, Any],
    run: Dict[str, Any],
    outcome: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Insert an assistant turn in the originating conversation (once only)."""
    origin = schedule.get("origin_conversation_id")
    if not origin:
        return None
    engine = get_engine()
    user_id = schedule.get("user_id")
    metadata = {
        "scheduled": True,
        "schedule_id": str(schedule["id"]),
        "run_id": str(run["id"]),
        "scheduled_run_at": (
            run.get("scheduled_for")
            if isinstance(run.get("scheduled_for"), str)
            else None
        ),
    }
    with engine.begin() as conn:
        conv = ConversationsRepository(conn).get_any(str(origin), user_id)
        if conv is None:
            return None
        message = ConversationsRepository(conn).append_message(
            str(conv["id"]),
            {
                "prompt": schedule.get("instruction") or "",
                "response": outcome.get("answer") or "",
                "thought": outcome.get("thought") or "",
                "sources": outcome.get("sources") or [],
                "tool_calls": outcome.get("tool_calls") or [],
                "model_id": outcome.get("model_id"),
                "metadata": metadata,
            },
        )
    return message


def _scheduler_still_allowed(schedule: Dict[str, Any], agent_config: Dict[str, Any]) -> bool:
    """Whether the schedule's user may still run this agent.

    The run always executes as the agent's owner. A schedule stored under
    someone else (set from chat on a shared agent) needs that user to still
    see the agent — a live team grant, or a public link that is still on and
    that they opened — so revoking a grant stops their schedules on the next
    tick.

    On a team's agent the schedule's user is the person who set it and pays
    for it: it runs only while they still hold ``manage_schedules`` there
    (Editor and up). Leaving the team or a demotion to Viewer is reported
    before this, as a pause (``payer_left``); so is a schedule stored under a
    team's principal (``no_payer``), which never runs: a principal pays for
    nothing. This stays as the last word for both.

    Args:
        schedule: The schedule row.
        agent_config: The agent row (or the agentless ephemeral config).

    Returns:
        True when the run may proceed.
    """
    user_id = schedule.get("user_id")
    agent_id = agent_config.get("id")
    if is_principal_id(user_id):
        return False
    if not agent_id or not user_id or agent_config.get("user_id") == user_id:
        return True
    from docsgpt.api.user.resource_access import resolve

    if is_principal_id(agent_config.get("user_id")):
        with get_engine().connect() as conn:
            ra = resolve(conn, "agent", str(agent_id), user_id)
        return ra is not None and ra.can("manage_schedules")
    with get_engine().connect() as conn:
        # A link user needs the link on and the record that they opened it;
        # the agent being link-shared is not enough on its own.
        if (
            agent_config.get("shared")
            and agent_config.get("shared_token")
            and UsersRepository(conn).has_shared(user_id, str(agent_id))
        ):
            return True
        return resolve(conn, "agent", str(agent_id), user_id) is not None


def _out_of_allowance_line(pause: Pause) -> str:
    """The notice body for an allowance pause: until when, when the window's reset is known."""
    if pause.until is None:
        return "Paused: you're out of allowance"
    return f"Paused: you're out of allowance until {pause.until.day} {pause.until:%b}"


def _skip_paused(
    run: Dict[str, Any], schedule: Dict[str, Any], pause: Pause, *, collapse: bool = True,
) -> Dict[str, Any]:
    """Record a run skipped while the schedule is paused for its payer.

    A pause, not a failure: it neither counts toward auto-pause nor sends a
    failure notice, and the schedule keeps its cadence, so runs carry on by
    themselves once the reason clears (a reactivated account, the setter back
    in the role, someone taking over, a new allowance window). ``error_type``
    names the reason (the UI reads it); ``error`` repeats it for the run log.

    One row stands for a whole streak: when the schedule's latest finished run
    is already skipped for the same reason and billed to the same payer, a
    scheduled run is deleted instead of stored, so a paused schedule doesn't
    fill its log. A Run now keeps its row, since whoever started it is
    watching it. The payer hears of an allowance pause once, on the streak's
    first skip; nobody else is told from here. Someone who takes over while
    out of allowance themselves starts a streak of their own.

    A one-time task has no next run to carry on with, so it gets one: when the
    payer's allowance resets, when that is known, else after the shortest
    recurring interval. Take over brings it forward to now.

    Args:
        run: The pending run.
        schedule: Its schedule.
        pause: Why it is paused.
        collapse: Whether a run inside a streak may be deleted; False once the
            run has started.

    Returns:
        The task's result dict.
    """
    reason = pause.reason
    with get_engine().begin() as conn:
        runs = ScheduleRunsRepository(conn)
        latest = runs.latest_finished([str(schedule["id"])]).get(str(schedule["id"]))
        in_streak = (
            latest is not None
            and latest.get("status") == "skipped"
            and latest.get("error_type") == reason
            and latest.get("user_id") == run.get("user_id")
        )
        if schedule.get("trigger_type") == "once" and run.get("trigger_source") != "manual":
            retry_at = pause.until or datetime.now(timezone.utc) + timedelta(seconds=settings.SCHEDULE_MIN_INTERVAL)
            SchedulesRepository(conn).rearm_once(str(schedule["id"]), retry_at)
        if in_streak and collapse and run.get("trigger_source") != "manual":
            if runs.delete_pending(str(run["id"])):
                return {"status": "skipped", "reason": reason, "collapsed": True}
        runs.update(
            str(run["id"]),
            {
                "status": "skipped",
                "finished_at": datetime.now(timezone.utc),
                "error_type": reason,
                "error": reason,
            },
        )
    if reason == PAYER_OUT_OF_ALLOWANCE and pause.payer and not in_streak:
        from docsgpt.notifications.notify import notify_user

        schedule_id = str(schedule["id"])
        notify_user(
            user_id=pause.payer,
            conversation_id=None,
            kind="schedule_paused",
            title=_schedule_title(schedule)[:200],
            body=_out_of_allowance_line(pause),
            url=f"/activity/schedules?schedule={schedule_id}",
            schedule_id=schedule_id,
        )
    return {"status": "skipped", "reason": reason}


def _pause_from_refusal(exc: QuotaExceededError, payer: Optional[str]) -> Optional[Pause]:
    """The payer pause a refusal from the run's own pre-check stands for, or None for a failure.

    The schedule's pause check ran just before, so this only catches what
    changed in between. The agent's own limit is not a payer pause; nor is a
    stop that came mid-run (``stops_run``), which is a failed run.

    Args:
        exc: The refusal ``run_agent_headless`` raised.
        payer: The schedule's payer.

    Returns:
        The pause to record, or None when the run is a failure.
    """
    if isinstance(exc, NoPayerError):
        return Pause(NO_PAYER, None)
    exceeded = getattr(exc, "exceeded", None)
    if getattr(exc, "stops_run", False) or exceeded is None or isinstance(exceeded, AgentLimitExceeded):
        return None
    return Pause(PAYER_OUT_OF_ALLOWANCE, payer, getattr(exceeded, "resets_at", None))


def _quota_failure_type(exc: QuotaExceededError) -> str:
    """A refusal recorded as a failed run: the payer's allowance mid-run, else the agent's limit."""
    if getattr(exc, "stops_run", False) and not isinstance(getattr(exc, "exceeded", None), AgentLimitExceeded):
        return PAYER_OUT_OF_ALLOWANCE
    return "budget_exceeded"


def _schedule_caller_rules(schedule: Dict[str, Any], agent_config: Dict[str, Any]) -> Dict[str, bool]:
    """The caller rules a scheduled run keeps, though it acts as the owner.

    A schedule set through the agent's API key is an external caller's; one
    a user without a team grant set (they reach the agent by its public
    link) is a public-link caller's. Neither can approve for the owner, so
    the run writes on the owner's accounts and credentials only as far as
    the agent's API write allowlist allows.

    Args:
        schedule: The schedule row.
        agent_config: The agent row (or the agentless ephemeral config).

    Returns:
        ``external_caller`` and ``public_link_caller`` flags for the run.
    """
    public = False
    user_id = schedule.get("user_id")
    agent_id = agent_config.get("id")
    if agent_id and user_id and agent_config.get("user_id") != user_id:
        from docsgpt.api.user.resource_access import resolve

        with get_engine().connect() as conn:
            public = resolve(conn, "agent", str(agent_id), user_id) is None
    return {"external_caller": schedule.get("created_via") == "api", "public_link_caller": public}


def _fail_before_start(run: Dict[str, Any], schedule: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """Record a run that could not start; it counts toward auto-pause like any other failure."""
    failures, autopaused = 0, False
    with get_engine().begin() as conn:
        updated = ScheduleRunsRepository(conn).update(
            str(run["id"]),
            {
                "status": "failed",
                "finished_at": datetime.now(timezone.utc),
                "error_type": "internal",
                "error": reason,
            },
        )
        if _counts_toward_autopause(run):
            schedules_repo = SchedulesRepository(conn)
            failures = schedules_repo.bump_failure_count(str(schedule["id"]))
            autopaused = _autopause_if_due(schedules_repo, schedule, failures)
    _publish_run_event("schedule.run.failed", updated or run, schedule, error=reason)
    _after_failure(schedule, updated or run, autopaused, failures, "internal", reason)
    return {"status": "failed", "reason": reason}


def execute_scheduled_run_body(run_id: str, celery_task_id: Optional[str]) -> Dict[str, Any]:
    """Execute one scheduled run by id; returns a result dict for tracing."""
    if not settings.POSTGRES_URI:
        return {"status": "skipped", "reason": "POSTGRES_URI not set"}

    engine = get_engine()

    with engine.connect() as conn:
        run = ScheduleRunsRepository(conn).get_internal(run_id)
        if run is None:
            return {"status": "skipped", "reason": "run not found"}
        schedule = SchedulesRepository(conn).get_internal(str(run["schedule_id"]))
    if schedule is None:
        return {"status": "skipped", "reason": "schedule not found"}

    # Refuse non-runnable terminal states; manual run-now bypasses.
    if run.get("status") != "pending":
        return {"status": "skipped", "reason": f"run status={run.get('status')}"}

    # Take over never changes the agent, so its row can be loaded before the claim.
    agent_config = _agent_config_for_schedule(schedule)

    # The claim, under the schedule's row lock (Take over takes it too), with
    # the schedule and run read afresh: the payer, the chat it was set from and
    # its history all come from what holds at the claim. A take over committed
    # before it has moved this run to the taker; one after it leaves the
    # started run with the payer it started under.
    pause: Optional[Pause] = None
    refusal: Optional[str] = None
    with engine.begin() as conn:
        schedule = SchedulesRepository(conn).lock_internal(str(run["schedule_id"]))
        run = ScheduleRunsRepository(conn).get_internal(run_id)
        if schedule is None or run is None:
            return {"status": "skipped", "reason": "schedule not found"}
        if run.get("status") != "pending":
            return {"status": "skipped", "reason": f"run status={run.get('status')}"}
        if schedule.get("status") in {"cancelled", "completed"} and run.get(
            "trigger_source"
        ) != "manual":
            ScheduleRunsRepository(conn).update(
                run_id,
                {
                    "status": "skipped",
                    "finished_at": datetime.now(timezone.utc),
                    "error_type": "internal",
                    "error": "schedule no longer active",
                },
            )
            return {"status": "skipped", "reason": "schedule terminal"}
        if agent_config is None:
            refusal = "agent missing"
        else:
            # Paused for its payer: a deactivated account, a setter no longer in
            # the role on a team agent, nobody to bill, or the payer out of allowance.
            pause = schedule_pause(conn, schedule, agent_config)
            if pause is None and not _scheduler_still_allowed(schedule, agent_config):
                refusal = "agent access revoked"
        if pause is None and refusal is None:
            if not ScheduleRunsRepository(conn).mark_running(run_id, celery_task_id):
                return {"status": "skipped", "reason": "lost race to mark_running"}
    if refusal is not None:
        return _fail_before_start(run, schedule, refusal)
    if pause is not None:
        return _skip_paused(run, schedule, pause)
    _publish_run_event("schedule.run.started", {**run, "status": "running"}, schedule)

    started = datetime.now(timezone.utc)
    instruction = schedule.get("instruction") or ""
    allowlist = schedule.get("tool_allowlist") or []
    chat_history = _load_chat_history(schedule)
    outcome: Dict[str, Any]
    error_type: Optional[str] = None
    error_text: Optional[str] = None
    timed_out = False
    try:
        outcome = run_agent_headless(
            agent_config,
            instruction,
            tool_allowlist=allowlist,
            model_id_override=schedule.get("model_id"),
            endpoint="schedule",
            conversation_id=schedule.get("origin_conversation_id"),
            chat_history=chat_history,
            # Links the run's execution trace to its Logs row, which belongs
            # to the user who scheduled it (not always the agent's owner).
            request_id=str(run_id),
            trace_user_id=run.get("user_id") or schedule.get("user_id"),
            # The person who set the schedule pays; the run still executes as the agent's owner.
            payer=schedule.get("user_id") or run.get("user_id"),
            run_kind="schedule",
            **_schedule_caller_rules(schedule, agent_config),
        )
    except SoftTimeLimitExceeded:
        timed_out = True
        outcome = {"answer": "", "tool_calls": [], "sources": [], "thought": ""}
        error_type = "timeout"
        error_text = "run exceeded soft time limit"
    except QuotaExceededError as exc:
        payer_pause = _pause_from_refusal(exc, schedule.get("user_id") or run.get("user_id"))
        if payer_pause is not None:
            # Refused before it started, for its payer: a pause like the check
            # above, not a failure. The run already shows as started, so it
            # keeps its row, and the UI is told it ended or it stays "running".
            result = _skip_paused(run, schedule, payer_pause, collapse=False)
            _publish_run_event(
                "schedule.run.skipped",
                {**run, "status": "skipped"},
                schedule,
                error_type=payer_pause.reason,
                error=payer_pause.reason,
            )
            return result
        # The agent's own limit, before the run started or mid-run.
        outcome = {"answer": "", "tool_calls": [], "sources": [], "thought": ""}
        error_type = _quota_failure_type(exc)
        error_text = str(exc)
    except Exception as exc:
        outcome = {"answer": "", "tool_calls": [], "sources": [], "thought": ""}
        error_type = "agent_error"
        error_text = str(exc)
        logger.exception("scheduler: agent run failed run=%s", run_id)

    finished = datetime.now(timezone.utc)

    # Honour the outcome the runner reported: it classifies headless denials
    # (``tool_not_allowed``) and mid-stream failures (``stream_error``) alike,
    # and owns the message. Re-deriving the denial case here only duplicated
    # the runner's rule while leaving a failed stream — which returns normally,
    # with an empty answer — to fall through to "success".
    if error_type is None and outcome.get("error_type"):
        error_type = str(outcome["error_type"])
        error_text = str(outcome.get("error") or "") or error_type

    # The agent reported it has no way to do the task (``report_cannot_complete``,
    # or the marker a model without tools opens its answer with; the runner
    # reads both). Without this a schedule that can never work answers "I
    # can't" every time as a success and never pauses.
    if error_type is None and outcome.get("cannot_complete"):
        error_type = "cannot_complete"
        error_text = str(outcome["cannot_complete"])

    prompt_tokens = int(outcome.get("prompt_tokens", 0) or 0)
    generated_tokens = int(outcome.get("generated_tokens", 0) or 0)
    used_tokens = prompt_tokens + generated_tokens
    if (
        schedule.get("token_budget") is not None
        and int(schedule["token_budget"]) > 0
        and used_tokens > int(schedule["token_budget"])
    ):
        error_type = "budget_exceeded"
        error_text = (
            f"used {used_tokens} tokens exceeds budget "
            f"{schedule['token_budget']}"
        )

    # Backstop for silent failures that raise nothing and emit no error event:
    # a run that produced no answer, did no work and burned no completion
    # tokens did not do its job, whatever the absence of an exception suggests.
    # "Work" is deliberately broad — tool calls for a chat agent, completed
    # nodes for a workflow — so a schedule whose whole purpose is a side effect
    # (post a message, file a ticket) is never flagged for staying quiet.
    if (
        error_type is None
        and not (outcome.get("answer") or "").strip()
        and not (outcome.get("tool_calls") or [])
        and not int(outcome.get("steps_completed") or 0)
        and generated_tokens == 0
    ):
        error_type = "empty_output"
        error_text = "run produced no answer, tool calls or completion tokens"

    answer = outcome.get("answer") or ""
    truncated = False
    if len(answer) > _OUTPUT_CAP_CHARS:
        answer = answer[:_OUTPUT_CAP_CHARS]
        truncated = True

    new_status = (
        "timeout" if timed_out else ("failed" if error_type else "success")
    )

    with engine.begin() as conn:
        update_fields: Dict[str, Any] = {
            "status": new_status,
            "started_at": started,
            "finished_at": finished,
            "output": answer or None,
            "output_truncated": truncated,
            "prompt_tokens": prompt_tokens,
            "generated_tokens": generated_tokens,
        }
        if error_type:
            update_fields["error_type"] = error_type
            update_fields["error"] = error_text
        updated_run = ScheduleRunsRepository(conn).update(run_id, update_fields)
        # No token_usage row here: the run's LLM calls were each recorded by
        # the usage decorators as they ran, and a run total on top of them
        # counted every token twice. The run's own total stays on its row.
        schedules_repo = SchedulesRepository(conn)
        autopaused = False
        count = 0
        if new_status == "success":
            schedules_repo.reset_failure_count(str(schedule["id"]))
        elif new_status in ("failed", "timeout") and _counts_toward_autopause(run, error_type):
            count = schedules_repo.bump_failure_count(str(schedule["id"]))
            autopaused = _autopause_if_due(schedules_repo, schedule, count)
        # Once: terminal-flip on cron-fired runs only; manual runs on a
        # still-active once-schedule leave the future cadence intact.
        if (
            schedule.get("trigger_type") == "once"
            and run.get("trigger_source") != "manual"
            and schedule.get("status") == "active"
        ):
            schedules_repo.update_internal(
                str(schedule["id"]),
                {"status": "completed", "next_run_at": None},
            )

    appended: Optional[Dict[str, Any]] = None
    # A task set from a chat that the agent cannot do still answers there, so
    # the user learns why instead of hearing nothing.
    if (
        schedule.get("trigger_type") == "once"
        and (new_status == "success" or error_type == "cannot_complete")
        and schedule.get("origin_conversation_id")
    ):
        # A report with no answer around it still tells the chat why.
        turn_outcome = (
            {**outcome, "answer": error_text}
            if error_type == "cannot_complete" and not (outcome.get("answer") or "").strip()
            else outcome
        )
        try:
            appended = _append_one_time_turn(schedule, updated_run or run, turn_outcome)
        except Exception:
            logger.exception(
                "scheduler: append turn failed run=%s", run_id,
            )
        if appended is not None:
            with engine.begin() as conn:
                ScheduleRunsRepository(conn).update(
                    run_id,
                    {
                        "conversation_id": str(appended["conversation_id"]),
                        "message_id": str(appended["id"]),
                    },
                )
            _publish_message_appended(
                schedule.get("user_id"),
                str(appended["conversation_id"]),
                appended,
                str(schedule["id"]),
                run_id,
            )
            _notify_appended(schedule, appended, turn_outcome)

    if new_status == "success":
        _publish_run_event("schedule.run.completed", updated_run or run, schedule)
    else:
        _publish_run_event(
            "schedule.run.failed",
            updated_run or run,
            schedule,
            error_type=error_type,
            error=error_text,
        )

    _after_failure(schedule, updated_run or run, autopaused, count, error_type, error_text)

    return {
        "status": new_status,
        "run_id": run_id,
        "error_type": error_type,
    }
