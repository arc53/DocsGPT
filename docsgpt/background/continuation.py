"""The continuation turn: a headless agent turn that answers queued wake events in their conversation.

Body of the ``continue_conversation`` Celery task. It reuses the scheduled
one-time run's machinery: ``run_agent_headless`` with the conversation's agent
(or an agentless chat config) and model, the owner's quota and per-call token
billing, approval-gated tools denied (headless, no allowlist), and an
appended assistant message.

Rules, in order:

* **Defer while busy.** A generation streaming in the conversation, or a turn
  paused for approval, re-queues the task with a backoff.
* **Dedupe.** Wakes are claimed under the conversation's row lock, one
  continuation at a time; a job's result is taken with a conditional update,
  so a result ``check_job`` or the user's next message took is never repeated.
* **Batch.** Up to eight events go into one turn.
* **Silence.** ``NO_REPLY`` persists nothing and notifies no one.
* **Bounded.** No continuation in conversations auto-resume does not apply to,
  and at most ``AUTO_RESUME_MAX_CONSECUTIVE`` in a row without a user message;
  past that, events wait for the user's next message.

A continuation is a turn like a chat turn: its message id is reserved before
it runs, so its tool calls are journaled and its files attached under it, and
a slow call may become a background job (with ``check_job`` to look at it).
It stays headless: tools that need approval are denied.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Connection, text

from docsgpt.background import jobs, wake
from docsgpt.background.context import BackgroundContext, auto_resume_allowed
from docsgpt.background.events import publish_conversation_continued
from docsgpt.core.settings import settings
from docsgpt.storage.db.base_repository import row_to_dict
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.conversation_wakes import ConversationWakesRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.tool_call_attempts import ToolCallAttemptsRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

#: Deferral backoff: seconds before the next try, by attempt; the last value repeats.
DEFER_BACKOFF_SECONDS = (5, 10, 20, 40, 60)

#: Deferrals before the task gives up; the background sweep picks the events up later.
MAX_DEFERRALS = 40

#: A message heartbeat younger than this means a generation is running.
ACTIVE_HEARTBEAT_SECONDS = 120

#: Claims older than this belong to a continuation that died.
CLAIM_TTL_SECONDS = 1800


def defer_delay(attempt: int) -> int:
    """Seconds to wait before retrying a deferred continuation."""
    return DEFER_BACKOFF_SECONDS[min(attempt, len(DEFER_BACKOFF_SECONDS) - 1)]


def generation_active(conn: Connection, conversation_id: str) -> bool:
    """Whether a turn is streaming in the conversation, or paused waiting on the user.

    Args:
        conn: A database connection.
        conversation_id: The conversation.

    Returns:
        True when a continuation must wait.
    """
    row = conn.execute(
        text(
            """
            SELECT 1 FROM conversation_messages cm
            WHERE cm.conversation_id = CAST(:cid AS uuid)
              AND cm.status IN ('pending', 'streaming')
              AND COALESCE((cm.message_metadata->>'last_heartbeat_at')::timestamptz, cm.timestamp)
                  > now() - make_interval(secs => :fresh)
            UNION ALL
            SELECT 1 FROM pending_tool_state pts
            WHERE pts.conversation_id = CAST(:cid AS uuid)
              AND ((pts.status = 'pending' AND pts.expires_at > now())
                   OR (pts.status = 'resuming' AND pts.resumed_at > now() - interval '10 minutes'))
            LIMIT 1
            """
        ),
        {"cid": str(conversation_id), "fresh": ACTIVE_HEARTBEAT_SECONDS},
    ).fetchone()
    return row is not None


def is_final_job_event(event: Dict[str, Any]) -> bool:
    """Whether a wake carries a job's final result (a watch wake comes while the job still runs)."""
    return (
        event.get("source") in ("job", "lost")
        and bool(event.get("ref_id"))
        and str(event.get("dedupe_key") or "").endswith(":final")
    )


def consecutive_continuations(messages: List[Dict[str, Any]]) -> int:
    """How many continuation messages close the conversation, with no user message after them."""
    count = 0
    for message in reversed(messages):
        if "wake" in (message.get("metadata") or {}):
            count += 1
        else:
            break
    return count


def _claim(conversation_id: str, limit: int) -> Tuple[Optional[List[Dict[str, Any]]], bool]:
    """Claim the conversation's pending wakes, unless another continuation holds some.

    The conversation row lock serializes claimers, so two tasks never run a
    continuation in one conversation at once.

    Returns:
        ``(wakes, busy)``: ``busy`` when another continuation is running.
    """
    with db_session() as conn:
        conn.execute(
            text("SELECT id FROM conversations WHERE id = CAST(:cid AS uuid) FOR UPDATE"),
            {"cid": conversation_id},
        )
        running = conn.execute(
            text(
                "SELECT 1 FROM conversation_wakes WHERE conversation_id = CAST(:cid AS uuid) "
                "AND status = 'claimed' AND claimed_at > now() - make_interval(secs => :ttl) LIMIT 1"
            ),
            {"cid": conversation_id, "ttl": CLAIM_TTL_SECONDS},
        ).fetchone()
        if running is not None:
            return None, True
        return ConversationWakesRepository(conn).claim_batch(conversation_id, limit=limit), False


def _take_job_results(wakes: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Take each job event's result for this turn; drop events whose result was delivered another way.

    Returns:
        ``(kept, dropped)``.
    """
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    with db_session() as conn:
        jobs_repo = BackgroundJobsRepository(conn)
        for event in wakes:
            if is_final_job_event(event):
                if jobs_repo.claim_delivery(str(event["ref_id"]), "resumed") is None:
                    dropped.append(event)
                    continue
            kept.append(event)
        if dropped:
            ConversationWakesRepository(conn).mark([w["id"] for w in dropped], "superseded")
    return kept, dropped


def _settle(wakes: List[Dict[str, Any]], status: str, *, message_id: Optional[str] = None,
            job_state: Optional[str] = None, error: Optional[str] = None) -> None:
    """Record the outcome on the wakes, and on their jobs' delivery state."""
    with db_session() as conn:
        ConversationWakesRepository(conn).mark([w["id"] for w in wakes], status, message_id=message_id, error=error)
        jobs_repo = BackgroundJobsRepository(conn)
        for event in wakes:
            if not is_final_job_event(event):
                continue
            job_id = str(event["ref_id"])
            if job_state == "pending":
                jobs_repo.release_delivery(job_id, "resumed")
            elif job_state:
                jobs_repo.set_delivery_state(job_id, job_state, from_state="resumed")
            if message_id:
                jobs_repo.set_followup(job_id, message_id)


def _release(wakes: List[Dict[str, Any]]) -> None:
    """Hand claimed wakes and their job results back, for a later turn or the user's next message."""
    with db_session() as conn:
        ConversationWakesRepository(conn).release([w["id"] for w in wakes])
        jobs_repo = BackgroundJobsRepository(conn)
        for event in wakes:
            if is_final_job_event(event):
                jobs_repo.release_delivery(str(event["ref_id"]), "resumed")


def _agent_config(conn: Connection, conversation: Dict[str, Any], model_id: Optional[str]) -> Optional[dict]:
    """The agent a continuation runs: the conversation's agent, or an agentless chat."""
    agent_id = conversation.get("agent_id")
    if agent_id:
        row = conn.execute(
            text("SELECT * FROM agents WHERE id = CAST(:id AS uuid)"), {"id": str(agent_id)}
        ).fetchone()
        return row_to_dict(row) if row is not None else None
    return {
        "id": None,
        "user_id": conversation["user_id"],
        "agent_type": settings.AGENT_NAME,
        "retriever": "classic",
        # The chat's sources were picked per request and are not stored; a
        # continuation answers from the conversation and its tools.
        "chunks": 0,
        "prompt_id": "default",
        "source_id": None,
        "default_model_id": model_id or "",
    }


def _history(messages: List[Dict[str, Any]], model_id: Optional[str], user_id: str) -> List[Dict[str, Any]]:
    """The conversation as a chat turn would replay it, trimmed to the model's window."""
    from docsgpt.api.answer.services.compression.types import is_compression_summary_row
    from docsgpt.utils import limit_chat_history

    history: List[Dict[str, Any]] = []
    for message in messages:
        if message.get("status") not in (None, "complete") or is_compression_summary_row(message):
            continue
        if not message.get("prompt") and not message.get("response"):
            continue
        entry: Dict[str, Any] = {"prompt": message.get("prompt") or "", "response": message.get("response") or ""}
        if message.get("thought"):
            entry["thought"] = message["thought"]
        if message.get("tool_calls"):
            entry["tool_calls"] = message["tool_calls"]
        if message.get("metadata"):
            entry["metadata"] = message["metadata"]
        history.append(entry)
    return limit_chat_history(history, model_id=model_id, user_id=user_id)


def _replay(
    conversation: Dict[str, Any], messages: List[Dict[str, Any]], model_id: Optional[str], user_id: str
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """The compressed summary and the history a chat turn would replay.

    A conversation with a saved compression point replays its summary (in the
    system prompt) and only the turns after the point, as ``/stream`` does;
    replaying the raw history instead sent a continuation several times the
    context of the chat turns around it. No compression is run here.

    Args:
        conversation: The conversation row (its ``compression_metadata``).
        messages: Its messages, in order.
        model_id: The model the turn runs on.
        user_id: The conversation's owner.

    Returns:
        ``(summary, history)``: ``summary`` is None when no usable point exists.
    """
    from docsgpt.api.answer.services.compression.service import CompressionService
    from docsgpt.api.answer.services.compression.types import latest_usable_compression_point

    metadata = conversation.get("compression_metadata") or {}
    if not (metadata.get("is_compressed") and latest_usable_compression_point(metadata.get("compression_points"))):
        return None, _history(messages, model_id, user_id)
    summary, recent = CompressionService(llm=None, model_id=model_id or "").get_compressed_context(
        {**conversation, "queries": messages}
    )
    return summary or None, _history(recent, model_id, user_id)


def _last_model(messages: List[Dict[str, Any]]) -> Optional[str]:
    """The model the conversation last used: the continuation answers with the same one."""
    for message in reversed(messages):
        if message.get("model_id"):
            return str(message["model_id"])
    return None


def continue_conversation_body(conversation_id: str, attempt: int = 0) -> Dict[str, Any]:
    """Run one continuation turn for a conversation's queued events.

    Args:
        conversation_id: The conversation.
        attempt: Deferrals so far.

    Returns:
        A summary for the task result: ``state`` and details.
    """
    if attempt == 0:
        wake.clear_scheduled(conversation_id)
    with db_readonly() as conn:
        conversation = conn.execute(
            text("SELECT * FROM conversations WHERE id = CAST(:id AS uuid)"), {"id": conversation_id}
        ).fetchone()
        conversation = row_to_dict(conversation) if conversation is not None else None
        if conversation is None:
            return {"state": "gone"}
        user_id = conversation["user_id"]
        allowed = auto_resume_allowed(conn, conversation_id, user_id)
        busy = generation_active(conn, conversation_id)
        messages = ConversationsRepository(conn).get_messages(conversation_id)
    if not allowed:
        # Job results stay deliverable to check_job and the user's next message.
        _drop_pending(conversation_id)
        return {"state": "not_allowed"}
    if busy:
        return _defer(conversation_id, attempt, "a generation is running")
    if consecutive_continuations(messages) >= int(settings.AUTO_RESUME_MAX_CONSECUTIVE):
        logger.info("continuation cap reached in %s; events wait for the user", conversation_id)
        return {"state": "capped"}

    wakes, other_running = _claim(conversation_id, wake.MAX_BATCH)
    if other_running:
        return _defer(conversation_id, attempt, "another continuation is running")
    if not wakes:
        return {"state": "idle"}
    wakes, dropped = _take_job_results(wakes)
    if not wakes:
        return {"state": "superseded", "dropped": len(dropped)}

    from docsgpt.agents.tool_executor import defer_journal_parent, release_journal_parent

    # The turn's message is written after the turn; its calls are journaled under this id meanwhile.
    message_id = str(uuid.uuid4())
    defer_journal_parent(message_id)
    try:
        return _answer(conversation, messages, wakes, message_id)
    finally:
        release_journal_parent(message_id)


def _answer(conversation: Dict[str, Any], messages: List[Dict[str, Any]], wakes: List[Dict[str, Any]],
            message_id: str) -> Dict[str, Any]:
    """Run the turn for the claimed wakes and deliver its answer as ``message_id`` (or stay silent)."""
    conversation_id = str(conversation["id"])
    user_id = conversation["user_id"]
    try:
        outcome = _run_turn(conversation, messages, wakes, message_id=message_id)
    except Exception as exc:
        from docsgpt.quotas.service import QuotaExceededError

        if isinstance(exc, QuotaExceededError):
            logger.info("continuation in %s skipped: quota exhausted", conversation_id)
        else:
            logger.exception("continuation turn failed in %s", conversation_id)
        # The results stay deliverable: check_job or the user's next message takes them.
        _settle(wakes, "failed", job_state="pending", error=str(exc)[:500])
        return {"state": "failed", "error": type(exc).__name__}

    answer = (outcome.get("answer") or "").strip()
    if outcome.get("error_type") and not answer:
        _settle(wakes, "failed", job_state="pending", error=str(outcome.get("error") or "")[:500])
        return {"state": "failed", "error": outcome.get("error_type")}
    if wake.is_no_reply(answer):
        _settle(wakes, "suppressed", job_state="suppressed")
        _schedule_rest(conversation_id)
        return {"state": "suppressed", "events": len(wakes)}

    message = _append(conversation, wakes, outcome, message_id=message_id)
    _link_turn(message_id, outcome)
    _settle(wakes, "delivered", message_id=str(message["id"]))
    publish_conversation_continued(user_id, conversation_id, str(message["id"]), wakes[0].get("source") or "job")
    _notify(conversation, wakes, answer)
    _schedule_rest(conversation_id)
    return {"state": "delivered", "message_id": str(message["id"]), "events": len(wakes)}


def _drop_pending(conversation_id: str) -> None:
    """Retire the queued events of a conversation auto-resume does not apply to."""
    with db_session() as conn:
        conn.execute(
            text(
                "UPDATE conversation_wakes SET status = 'suppressed', error = 'auto-resume does not apply', "
                "delivered_at = now() WHERE conversation_id = CAST(:cid AS uuid) AND status = 'pending'"
            ),
            {"cid": conversation_id},
        )


def _defer(conversation_id: str, attempt: int, reason: str) -> Dict[str, Any]:
    if attempt + 1 >= MAX_DEFERRALS:
        logger.info("continuation for %s gave up deferring (%s); the sweep retries later", conversation_id, reason)
        return {"state": "gave_up"}
    wake.schedule_continuation(conversation_id, countdown=defer_delay(attempt), attempt=attempt + 1)
    return {"state": "deferred", "reason": reason}


def _schedule_rest(conversation_id: str) -> None:
    """Queue another continuation when events arrived while this one ran."""
    with db_readonly() as conn:
        pending = conn.execute(
            text(
                "SELECT 1 FROM conversation_wakes WHERE conversation_id = CAST(:cid AS uuid) "
                "AND status = 'pending' LIMIT 1"
            ),
            {"cid": conversation_id},
        ).fetchone()
    if pending is not None:
        wake.schedule_continuation(conversation_id)


def _run_turn(
    conversation: Dict[str, Any],
    messages: List[Dict[str, Any]],
    wakes: List[Dict[str, Any]],
    *,
    message_id: str,
):
    """Run the headless turn as ``message_id`` and return its outcome (``run_agent_headless``'s dict).

    The turn gets a background context of its own, so a slow call becomes a
    job (reporting back to this message) instead of holding the worker.
    """
    from docsgpt.agents.headless_runner import run_agent_headless

    user_id = conversation["user_id"]
    model_id = _last_model(messages)
    with db_readonly() as conn:
        agent_config = _agent_config(conn, conversation, model_id)
    if agent_config is None:
        raise LookupError("the conversation's agent no longer exists")
    query = wake.render_events(wakes)
    summary, history = _replay(conversation, messages, model_id, user_id)
    agent_id = agent_config.get("id")
    background = BackgroundContext(
        user_id=str(user_id),
        conversation_id=str(conversation["id"]),
        origin_message_id=message_id,
        agent_id=str(agent_id) if agent_id else None,
        continuation=True,
    )
    return run_agent_headless(
        agent_config,
        query,
        tool_allowlist=[],
        model_id_override=model_id,
        endpoint="continuation",
        chat_history=history,
        compressed_summary=summary,
        conversation_id=str(conversation["id"]),
        request_id=str(uuid.uuid4()),
        trace_user_id=user_id,
        message_id=message_id,
        background=background,
    )


#: Characters of an event's detail the chat's event row shows.
EVENT_DETAIL_CHARS = 280

#: Keys of a job's JSON result that say what happened, in the order they are preferred.
_RESULT_KEYS = ("error", "stdout_tail", "text", "result", "summary", "message", "content")


def _job_detail(result: Any) -> str:
    """What a finished job produced, in a line or two: its error, the end of its output, or its text."""
    if not isinstance(result, str) or not result.strip():
        return ""
    try:
        data = json.loads(result)
    except ValueError:
        return result
    if isinstance(data, dict):
        for key in _RESULT_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                if key == "stdout_tail":
                    # The last lines a run printed carry its outcome ("DONE: 7 batches").
                    return "\n".join([line for line in value.splitlines() if line.strip()][-3:])
                return value
        return ""
    return result


def _event_view(wake_row: Dict[str, Any], jobs_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """An event as the chat's event row shows it: a label, a status and a short detail, never the model's text.

    The wake's title and body are written for the model (tool ids, job ids,
    instructions); this is what a person reads instead. The detail comes from
    the event's data, which passed the guardrails when it was queued.
    """
    from docsgpt.notifications.kinds import plain_preview, user_title

    source = wake_row.get("source")
    payload = wake_row.get("payload") if isinstance(wake_row.get("payload"), dict) else {}
    view: Dict[str, Any] = {}
    if source in ("job", "lost"):
        job = jobs_by_id.get(str(wake_row.get("ref_id"))) or {}
        words = str(job.get("action_name") or "").replace("_", " ").strip()
        view["label"] = words[:1].upper() + words[1:]
        if job.get("status"):
            view["status"] = str(job["status"])
        detail = _job_detail(payload.get("result"))
    else:
        view["label"] = user_title(wake_row.get("title"))
        if source == "approval":
            detail = payload.get("comment") or ""
        else:
            detail = payload.get("summary") or payload.get("error") or ""
    detail = plain_preview(str(detail), EVENT_DETAIL_CHARS) if detail else ""
    if detail:
        view["detail"] = detail
    return {key: value for key, value in view.items() if value}


def _wake_metadata(wakes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """``message_metadata.wake``: the event that woke the turn; ``wakes`` lists them all when batched.

    Each entry carries the routing fields and the event as a person reads it
    (``label``, ``status``, ``detail``; see :func:`_event_view`).
    """
    job_ids = [str(w["ref_id"]) for w in wakes if w.get("source") in ("job", "lost") and w.get("ref_id")]
    jobs_by_id: Dict[str, Dict[str, Any]] = {}
    if job_ids:
        try:
            with db_readonly() as conn:
                repo = BackgroundJobsRepository(conn)
                jobs_by_id = {job_id: repo.get(job_id) or {} for job_id in job_ids}
        except Exception:
            logger.exception("reading the jobs behind a continuation's events failed")
    entries = [
        {
            "source": w.get("source"),
            "ref_id": w.get("ref_id"),
            "dedupe_key": w.get("dedupe_key"),
            **_event_view(w, jobs_by_id),
        }
        for w in wakes
    ]
    metadata: Dict[str, Any] = {"wake": entries[0], "continuation": True}
    if len(entries) > 1:
        metadata["wakes"] = entries
    return metadata


#: Keys of a turn's agent metadata a continuation message keeps (as a chat turn stores them).
_RESPONSES_METADATA_KEYS = ("response_id", "response_chain_key", "responses_state", "usage", "compression_epoch")


def _responses_metadata(outcome: Dict[str, Any]) -> Dict[str, Any]:
    """The Responses continuity a headless turn reported, for its message's metadata."""
    reported = outcome.get("metadata")
    if not isinstance(reported, dict):
        return {}
    return {key: reported[key] for key in _RESPONSES_METADATA_KEYS if reported.get(key) is not None}


def _append(
    conversation: Dict[str, Any], wakes: List[Dict[str, Any]], outcome: Dict[str, Any], *, message_id: str
) -> Dict[str, Any]:
    """Append the continuation as an assistant turn; its prompt is the event text, marked as not the user's."""
    with db_session() as conn:
        return ConversationsRepository(conn).append_message(
            str(conversation["id"]),
            {
                "id": message_id,
                "prompt": wake.render_events(wakes),
                "response": outcome.get("answer") or "",
                "thought": outcome.get("thought") or "",
                "sources": outcome.get("sources") or [],
                "tool_calls": outcome.get("tool_calls") or [],
                "model_id": outcome.get("model_id"),
                # The turn's Responses state (response id, reasoning) beside
                # the wake: without it the user's next turn cannot chain onto
                # this one and resends the whole history.
                "metadata": {**_responses_metadata(outcome), **_wake_metadata(wakes)},
            },
        )


def _link_turn(message_id: str, outcome: Dict[str, Any]) -> None:
    """Link what the turn did before its message existed: its journal rows, and the jobs that already ended.

    A call the turn handed off reports to this message; one that finished
    before the message was written could not show its outcome on it, so it
    is shown now. Never raises: the answer is delivered either way.
    """
    calls = [c for c in outcome.get("tool_calls") or [] if isinstance(c, dict)]
    keys = [f"{message_id}:{c['call_id']}" for c in calls if c.get("call_id")]
    job_ids = [str(c["job_id"]) for c in calls if c.get("job_id")]
    try:
        with db_session() as conn:
            ToolCallAttemptsRepository(conn).attach_message(keys, message_id)
            repo = BackgroundJobsRepository(conn)
            for job_id in job_ids:
                job = repo.get(job_id)
                if job and job.get("status") != "working" and str(job.get("origin_message_id")) == message_id:
                    jobs.patch_origin_entry(conn, job)
    except Exception:
        logger.exception("continuation %s: linking its tool calls failed", message_id)


def _job_label(job_id: Optional[str]) -> str:
    """A job's action as a person reads it (``run_code`` -> "Run code"), or "" when unknown."""
    if not job_id:
        return ""
    try:
        with db_readonly() as conn:
            job = BackgroundJobsRepository(conn).get(str(job_id))
    except Exception:
        logger.debug("reading a job for its notification label failed", exc_info=True)
        return ""
    words = str((job or {}).get("action_name") or "").replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def _notify_title(conversation: Dict[str, Any], first: Dict[str, Any]) -> str:
    """The notification's title: what a person calls the event, never a tool's internal name.

    A job's wake title names it for the model (``code_executor.run_code
    finished``); the user gets the conversation's name, else the action in
    words. Other events keep their title (a monitor's description).
    """
    from docsgpt.notifications.kinds import user_title

    if first.get("source") in ("job", "lost"):
        name = str(conversation.get("name") or "").strip()
        return name or _job_label(first.get("ref_id"))
    return user_title(first.get("title"))


def _notify(conversation: Dict[str, Any], wakes: List[Dict[str, Any]], answer: str) -> None:
    from docsgpt.notifications.kinds import plain_preview
    from docsgpt.notifications.notify import notify_user

    first = wakes[0]
    title = _notify_title(conversation, first)
    if len(wakes) > 1:
        title = f"{title} (+{len(wakes) - 1} more)" if title else f"+{len(wakes) - 1} more"
    notify_user(
        user_id=conversation["user_id"],
        conversation_id=str(conversation["id"]),
        kind=str(first.get("source") or "job"),
        title=title[:200],
        body=plain_preview(answer),
        url=f"/c/{conversation['id']}",
    )
