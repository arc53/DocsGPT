"""The Activity › Now snapshot: what runs for a user right now, what waits for
them, and what runs in the next day.

Each kind of work keeps its state in its own table; this module only reads
them, one bounded query per kind, and folds them into one payload. Live
updates come from the events each kind already publishes; the client refetches
this snapshot on them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from docsgpt.activity.flags import list_runs
from docsgpt.activity.labels import tool_labels
from docsgpt.agents.scheduler_utils import ScheduleValidationError, next_cron_run
from docsgpt.background.service import job_summary
from docsgpt.core.settings import settings
from docsgpt.storage.db.base_repository import row_to_dict

logger = logging.getLogger(__name__)

#: A chat answer whose heartbeat is older than this is not running any more
#: (the stream ticker stamps it every 30 s; the reconciler sweeps it later).
CHAT_FRESH_SECONDS = 90

#: How far ahead "Up next" looks.
UP_NEXT_WINDOW = timedelta(hours=24)

#: Rows per kind; a user with more than this running at once is an outlier.
PER_KIND_LIMIT = 50

#: Occurrences counted per recurring schedule inside the window.
MAX_OCCURRENCES = 500


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def _str(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


def _rows(conn: Connection, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [row_to_dict(r) for r in conn.execute(text(sql), params).fetchall()]


def _running_chats(conn: Connection, user_id: str) -> List[Dict[str, Any]]:
    rows = _rows(
        conn,
        """
        SELECT m.id AS message_id, m.conversation_id, m.status, m.timestamp,
               c.name AS conversation_name, c.agent_id, a.name AS agent_name
        FROM conversation_messages m
        JOIN conversations c ON c.id = m.conversation_id
        LEFT JOIN agents a ON a.id = c.agent_id
        WHERE m.user_id = :user_id
          AND m.status IN ('pending', 'streaming')
          AND c.visibility = 'listed'
          AND COALESCE(
                (m.message_metadata ->> 'last_heartbeat_at')::timestamptz,
                m.timestamp
              ) > now() - make_interval(secs => :fresh)
        ORDER BY m.timestamp ASC
        LIMIT :limit
        """,
        {"user_id": user_id, "fresh": CHAT_FRESH_SECONDS, "limit": PER_KIND_LIMIT},
    )
    return [
        {
            "kind": "chat",
            "id": _str(r["message_id"]),
            "message_id": _str(r["message_id"]),
            "conversation_id": _str(r["conversation_id"]),
            "title": r.get("conversation_name") or None,
            "agent_id": _str(r.get("agent_id")),
            "agent_name": r.get("agent_name"),
            "status": r.get("status"),
            "started_at": _iso(r.get("timestamp")),
            "workflow": False,
        }
        for r in rows
    ]


def _running_api(conn: Connection, user_id: str) -> List[Dict[str, Any]]:
    """Answers being written through the API on the user's agents, one row per agent.

    API, OpenAI-compatible and shared-agent calls write hidden conversations,
    some under the caller's user id; a busy agent would flood the list, so
    each agent is one row whose ``count`` is its requests. The agent's Logs
    list them one by one.
    """
    rows = _rows(
        conn,
        """
        SELECT c.agent_id, a.name AS agent_name, COUNT(*) AS count,
               MIN(m.timestamp) AS started_at
        FROM conversation_messages m
        JOIN conversations c ON c.id = m.conversation_id
        JOIN agents a ON a.id = c.agent_id
        WHERE a.user_id = :user_id
          AND c.visibility <> 'listed'
          AND m.status IN ('pending', 'streaming')
          AND COALESCE(
                (m.message_metadata ->> 'last_heartbeat_at')::timestamptz,
                m.timestamp
              ) > now() - make_interval(secs => :fresh)
        GROUP BY c.agent_id, a.name
        ORDER BY MIN(m.timestamp) ASC
        LIMIT :limit
        """,
        {"user_id": user_id, "fresh": CHAT_FRESH_SECONDS, "limit": PER_KIND_LIMIT},
    )
    return [
        {
            "kind": "api",
            "id": f"api:{r['agent_id']}",
            "title": r.get("agent_name"),
            "agent_id": _str(r["agent_id"]),
            "agent_name": r.get("agent_name"),
            "count": int(r.get("count") or 0),
            "started_at": _iso(r.get("started_at")),
            "workflow": False,
        }
        for r in rows
    ]


def _running_jobs(conn: Connection, user_id: str) -> List[Dict[str, Any]]:
    rows = _rows(
        conn,
        """
        SELECT j.*, c.name AS conversation_name, a.name AS agent_name
        FROM background_jobs j
        LEFT JOIN conversations c ON c.id = j.conversation_id
        LEFT JOIN agents a ON a.id = j.agent_id
        WHERE j.user_id = :user_id AND j.status = 'working'
        ORDER BY j.created_at ASC
        LIMIT :limit
        """,
        {"user_id": user_id, "limit": PER_KIND_LIMIT},
    )
    labels = tool_labels(conn, user_id, [r.get("tool_name") for r in rows])
    out = []
    for r in rows:
        summary = job_summary(r)
        out.append(
            {
                "kind": "job",
                "id": summary["job_id"],
                "job_id": summary["job_id"],
                "conversation_id": summary.get("conversation_id"),
                "conversation_name": r.get("conversation_name"),
                "title": r.get("conversation_name") or None,
                "agent_id": _str(r.get("agent_id")),
                "agent_name": r.get("agent_name"),
                "tool_name": summary.get("tool_name"),
                "tool_label": labels.get(summary.get("tool_name") or ""),
                "action_name": summary.get("action_name"),
                "job_kind": r.get("kind"),
                "status_message": summary.get("status_message"),
                "progress": summary.get("progress"),
                "output_tail": summary.get("output_tail"),
                "cancel_requested": summary.get("cancel_requested"),
                "started_at": summary.get("started_at") or _iso(r.get("created_at")),
            }
        )
    return out


def _running_schedule_runs(conn: Connection, user_id: str) -> List[Dict[str, Any]]:
    rows = _rows(
        conn,
        """
        SELECT sr.id, sr.schedule_id, sr.status, sr.started_at, sr.scheduled_for,
               sr.trigger_source, s.name, s.instruction, s.agent_id,
               a.name AS agent_name
        FROM schedule_runs sr
        JOIN schedules s ON s.id = sr.schedule_id
        LEFT JOIN agents a ON a.id = s.agent_id
        WHERE sr.user_id = :user_id AND sr.status IN ('pending', 'running')
        ORDER BY sr.scheduled_for ASC
        LIMIT :limit
        """,
        {"user_id": user_id, "limit": PER_KIND_LIMIT},
    )
    return [
        {
            "kind": "schedule",
            "id": _str(r["id"]),
            "run_id": _str(r["id"]),
            "schedule_id": _str(r["schedule_id"]),
            "title": r.get("name") or (r.get("instruction") or "")[:80] or None,
            "agent_id": _str(r.get("agent_id")),
            "agent_name": r.get("agent_name"),
            "status": r.get("status"),
            "trigger_source": r.get("trigger_source"),
            "scheduled_for": _iso(r.get("scheduled_for")),
            "started_at": _iso(r.get("started_at") or r.get("scheduled_for")),
            "workflow": False,
        }
        for r in rows
    ]


def _running_workflows(conn: Connection, user_id: str) -> List[Dict[str, Any]]:
    rows = _rows(
        conn,
        """
        SELECT r.id, r.started_at, r.workflow_id, r.progress, w.name AS workflow_name,
               a.id AS agent_id, a.name AS agent_name
        FROM workflow_runs r
        JOIN workflows w ON w.id = r.workflow_id
        LEFT JOIN LATERAL (
            SELECT id, name FROM agents WHERE workflow_id = r.workflow_id
            ORDER BY created_at ASC LIMIT 1
        ) a ON TRUE
        WHERE r.user_id = :user_id AND r.status = 'running'
        ORDER BY r.started_at ASC
        LIMIT :limit
        """,
        {"user_id": user_id, "limit": PER_KIND_LIMIT},
    )
    return [
        {
            "kind": "workflow",
            "id": _str(r["id"]),
            "run_id": _str(r["id"]),
            "workflow_id": _str(r["workflow_id"]),
            "title": r.get("agent_name") or r.get("workflow_name"),
            "agent_id": _str(r.get("agent_id")),
            "agent_name": r.get("agent_name"),
            "started_at": _iso(r.get("started_at")),
            "workflow_progress": r.get("progress"),
        }
        for r in rows
    ]


def _running_ingests(conn: Connection, user_id: str) -> List[Dict[str, Any]]:
    rows = _rows(
        conn,
        """
        SELECT s.id, s.name, p.total_chunks, p.embedded_chunks, p.last_updated
        FROM sources s
        JOIN ingest_chunk_progress p ON p.source_id = s.id
        WHERE s.user_id = :user_id
          AND p.status <> 'stalled'
          AND p.embedded_chunks < p.total_chunks
        ORDER BY p.last_updated ASC
        LIMIT :limit
        """,
        {"user_id": user_id, "limit": PER_KIND_LIMIT},
    )
    out = []
    for r in rows:
        total = int(r.get("total_chunks") or 0)
        done = int(r.get("embedded_chunks") or 0)
        out.append(
            {
                "kind": "ingest",
                "id": _str(r["id"]),
                "source_id": _str(r["id"]),
                "title": r.get("name"),
                "progress": (done / total) if total else None,
                "embedded_chunks": done,
                "total_chunks": total,
                "updated_at": _iso(r.get("last_updated")),
            }
        )
    return out


def _running_webhooks(user_id: str) -> List[Dict[str, Any]]:
    out = []
    for marker in list_runs(user_id):
        started = marker.get("started_at")
        out.append(
            {
                "kind": marker.get("kind") or "webhook",
                "id": _str(marker.get("id")),
                "title": marker.get("agent_name"),
                "agent_id": _str(marker.get("agent_id")),
                "agent_name": marker.get("agent_name"),
                "started_at": (
                    datetime.fromtimestamp(float(started), tz=timezone.utc).isoformat()
                    if started is not None
                    else None
                ),
            }
        )
    return out


def _fold_workflows(running: List[Dict[str, Any]], workflows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fold each workflow run into the chat, scheduled run or webhook run that started it.

    A workflow agent's chat, scheduled run or webhook run also writes a
    ``workflow_runs`` row; listing both would show one piece of work twice.
    Runs are matched by agent, oldest run to oldest host, one run per host;
    the host takes the run's step (``workflow_progress``). Runs left over go
    into the agent's API row, which stands for many requests; a run with
    nothing to fold into (a builder preview) is listed on its own.
    """
    hosts: Dict[str, List[Dict[str, Any]]] = {}
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    for item in sorted(running, key=lambda entry: _as_datetime(entry.get("started_at")) or oldest):
        if item["kind"] in ("chat", "schedule", "webhook") and item.get("agent_id"):
            hosts.setdefault(item["agent_id"], []).append(item)
    api_rows = {item["agent_id"]: item for item in running if item["kind"] == "api"}
    standalone = []
    for flow in workflows:
        waiting = hosts.get(flow.get("agent_id")) if flow.get("agent_id") else None
        if waiting:
            host = waiting.pop(0)
            host["workflow"] = True
            host["workflow_progress"] = flow.get("workflow_progress")
        elif flow.get("agent_id") in api_rows:
            api_rows[flow["agent_id"]]["workflow"] = True
        else:
            standalone.append(flow)
    return standalone


def _approvals(conn: Connection, user_id: str) -> List[Dict[str, Any]]:
    rows = _rows(
        conn,
        """
        SELECT p.conversation_id, p.created_at, p.expires_at, p.pending_tool_calls,
               c.name AS conversation_name, c.agent_id, a.name AS agent_name
        FROM pending_tool_state p
        JOIN conversations c ON c.id = p.conversation_id
        LEFT JOIN agents a ON a.id = c.agent_id
        WHERE p.user_id = :user_id
          AND p.status = 'pending'
          AND p.expires_at > now()
          AND EXISTS (
              SELECT 1 FROM json_array_elements(p.pending_tool_calls) e
              WHERE e ->> 'pause_type' = 'awaiting_approval'
          )
        ORDER BY p.expires_at ASC
        LIMIT :limit
        """,
        {"user_id": user_id, "limit": PER_KIND_LIMIT},
    )
    out = []
    for r in rows:
        calls = r.get("pending_tool_calls") or []
        tools = []
        for call in calls if isinstance(calls, list) else []:
            if isinstance(call, dict) and call.get("pause_type") == "awaiting_approval":
                name = call.get("tool_name") or call.get("name")
                if name and name not in tools:
                    tools.append(name)
        out.append(
            {
                "kind": "approval",
                "id": f"approval:{r['conversation_id']}",
                "conversation_id": _str(r["conversation_id"]),
                "title": r.get("conversation_name") or None,
                "agent_id": _str(r.get("agent_id")),
                "agent_name": r.get("agent_name"),
                "tools": tools,
                "created_at": _iso(r.get("created_at")),
                "expires_at": _iso(r.get("expires_at")),
            }
        )
    return out


def _autopaused_schedules(conn: Connection, user_id: str) -> List[Dict[str, Any]]:
    threshold = max(1, int(settings.SCHEDULE_AUTOPAUSE_FAILURES or 1))
    rows = _rows(
        conn,
        """
        SELECT s.id, s.name, s.instruction, s.agent_id, s.consecutive_failure_count,
               s.updated_at, a.name AS agent_name,
               last.error_type AS last_error_type, last.error AS last_error,
               last.finished_at AS last_failed_at
        FROM schedules s
        LEFT JOIN agents a ON a.id = s.agent_id
        LEFT JOIN LATERAL (
            SELECT error_type, error, finished_at FROM schedule_runs
            WHERE schedule_id = s.id AND status IN ('failed', 'timeout')
            ORDER BY scheduled_for DESC LIMIT 1
        ) last ON TRUE
        WHERE s.user_id = :user_id
          AND s.status = 'paused'
          AND s.trigger_type <> 'monitor'
          AND s.consecutive_failure_count >= :threshold
        ORDER BY s.updated_at DESC
        LIMIT :limit
        """,
        {"user_id": user_id, "threshold": threshold, "limit": PER_KIND_LIMIT},
    )
    return [
        {
            "kind": "schedule_paused",
            "id": f"schedule:{r['id']}",
            "schedule_id": _str(r["id"]),
            "title": r.get("name") or (r.get("instruction") or "")[:80] or None,
            "agent_id": _str(r.get("agent_id")),
            "agent_name": r.get("agent_name"),
            "failures": int(r.get("consecutive_failure_count") or 0),
            "last_error_type": r.get("last_error_type"),
            "last_error": (r.get("last_error") or "")[:300] or None,
            "last_failed_at": _iso(r.get("last_failed_at")),
        }
        for r in rows
    ]


def _as_datetime(value: Any) -> Optional[datetime]:
    """A timestamp from ``row_to_dict`` (an ISO string) as an aware datetime."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _occurrences(row: Dict[str, Any], start: datetime, end: datetime) -> int:
    """How many times a schedule fires in ``[start, end)``.

    An overdue run (``next_run_at`` already past, the scheduler behind) is not
    counted: it is due now, not planned.
    """
    first = _as_datetime(row.get("next_run_at"))
    if first is None or first >= end:
        return 0
    if row.get("trigger_type") != "recurring" or not row.get("cron"):
        return 1 if first >= start else 0
    stop = end
    end_at = _as_datetime(row.get("end_at"))
    if end_at is not None:
        stop = min(stop, end_at)
    count, fire = 0, first
    try:
        if fire < start:
            fire = next_cron_run(row["cron"], row.get("timezone"), after=start - timedelta(seconds=1))
        while fire < stop and count < MAX_OCCURRENCES:
            count += 1
            fire = next_cron_run(row["cron"], row.get("timezone"), after=fire)
    except ScheduleValidationError:
        return max(count, 1)
    return count


def _up_next(conn: Connection, user_id: str, now: datetime) -> List[Dict[str, Any]]:
    end = now + UP_NEXT_WINDOW
    rows = _rows(
        conn,
        """
        SELECT s.id, s.name, s.instruction, s.agent_id, s.trigger_type, s.cron,
               s.timezone, s.next_run_at, s.end_at, s.origin_conversation_id,
               a.name AS agent_name, c.name AS origin_conversation_name
        FROM schedules s
        LEFT JOIN agents a ON a.id = s.agent_id
        LEFT JOIN conversations c ON c.id = s.origin_conversation_id
        WHERE s.user_id = :user_id
          AND s.status = 'active'
          AND s.trigger_type <> 'monitor'
          AND s.next_run_at IS NOT NULL
          AND s.next_run_at < :end
        ORDER BY s.next_run_at ASC
        LIMIT :limit
        """,
        {"user_id": user_id, "end": end, "limit": PER_KIND_LIMIT},
    )
    out = []
    for r in rows:
        out.append(
            {
                "schedule_id": _str(r["id"]),
                "name": r.get("name") or (r.get("instruction") or "")[:80] or None,
                "agent_id": _str(r.get("agent_id")),
                "agent_name": r.get("agent_name"),
                "trigger_type": r.get("trigger_type"),
                "cron": r.get("cron"),
                "timezone": r.get("timezone"),
                "next_run_at": _iso(r.get("next_run_at")),
                "origin_conversation_id": _str(r.get("origin_conversation_id")),
                "origin_conversation_name": r.get("origin_conversation_name"),
                "runs_in_window": _occurrences(r, now, end),
            }
        )
    return out


def _failed_last_day(conn: Connection, user_id: str) -> int:
    scalar = conn.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*) FROM schedule_runs
               WHERE user_id = :user_id AND status IN ('failed', 'timeout')
                 AND COALESCE(finished_at, scheduled_for) > now() - interval '24 hours')
            + (SELECT COUNT(*) FROM background_jobs
               WHERE user_id = :user_id AND status IN ('failed', 'lost')
                 AND COALESCE(finished_at, last_updated_at) > now() - interval '24 hours')
            """
        ),
        {"user_id": user_id},
    ).scalar()
    return int(scalar or 0)


def _failed_conversations(conn: Connection, user_id: str) -> List[str]:
    """Unread chats whose latest answer, or latest background job, failed.

    Cleared the way the unread mark is: by opening the chat.
    """
    rows = conn.execute(
        text(
            """
            SELECT c.id FROM conversations c
            WHERE c.user_id = :user_id
              AND c.unread_at IS NOT NULL
              AND (
                (SELECT status FROM background_jobs j
                 WHERE j.conversation_id = c.id
                 ORDER BY j.created_at DESC LIMIT 1) IN ('failed', 'lost')
                OR (SELECT status FROM conversation_messages m
                    WHERE m.conversation_id = c.id
                    ORDER BY m.position DESC LIMIT 1) = 'failed'
              )
            LIMIT :limit
            """
        ),
        {"user_id": user_id, "limit": PER_KIND_LIMIT},
    ).fetchall()
    return [str(r[0]) for r in rows]


def build_now(conn: Connection, user_id: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Collect what runs now, what waits for the user, and what runs next.

    Args:
        conn: A read-only connection.
        user_id: Whose activity.
        now: The current time (tests).

    Returns:
        ``{running, needs_you, up_next, approval_conversations,
        failed_conversations, stats}``. ``running`` and ``needs_you`` items
        carry a ``kind``; ``stats`` holds ``running``, ``needs_you``,
        ``next_24h`` and ``failed_24h``.
    """
    current = now or datetime.now(timezone.utc)
    running: List[Dict[str, Any]] = []
    running += _running_chats(conn, user_id)
    running += _running_api(conn, user_id)
    running += _running_jobs(conn, user_id)
    running += _running_schedule_runs(conn, user_id)
    running += _running_webhooks(user_id)
    running += _fold_workflows(running, _running_workflows(conn, user_id))
    running += _running_ingests(conn, user_id)

    approvals = _approvals(conn, user_id)
    needs_you = approvals + _autopaused_schedules(conn, user_id)
    up_next = _up_next(conn, user_id, current)
    return {
        "running": running,
        "needs_you": needs_you,
        "up_next": up_next,
        "approval_conversations": [item["conversation_id"] for item in approvals],
        "failed_conversations": _failed_conversations(conn, user_id),
        "stats": {
            # An API row stands for its requests.
            "running": sum(item.get("count", 1) for item in running),
            "needs_you": len(needs_you),
            "next_24h": sum(item["runs_in_window"] for item in up_next),
            "failed_24h": _failed_last_day(conn, user_id),
        },
    }
