"""The Activity › History list: finished runs of every kind, newest first.

Five sources are folded into one row shape with one status vocabulary
(``success``, ``failed``, ``timeout``, ``skipped``, ``cancelled``):

- **schedule**: ``schedule_runs`` that ended.
- **webhook**: webhook runs, from their ``request_traces`` row (a webhook run
  has no table of its own).
- **workflow**: ``workflow_runs`` that ended, except those a webhook or
  scheduled run already lists (its trace names the workflow run, and a
  scheduled one is also named by the run's ``started_by``).
- **job**: ``background_jobs`` that ended.
- **monitor**: ``conversation_wakes`` a monitor, trigger link or approval
  link delivered to its conversation.

Settings › Logs stays the raw, technical log; this is the readable "what did
my automations do" view.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from docsgpt.activity.labels import tool_labels
from docsgpt.storage.db.base_repository import like_escape, row_to_dict

KINDS = ("schedule", "webhook", "workflow", "job", "monitor")
STATUSES = ("success", "failed", "timeout", "skipped", "cancelled")

#: Default and widest look-back, in days (traces are kept 30 days by default,
#: scheduled runs 90, background jobs 7).
DEFAULT_DAYS = 30
MAX_DAYS = 90

#: Rows per page.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

#: The furthest a page may start; any page past the runs is empty anyway,
#: and Postgres rejects an OFFSET past int8.
MAX_OFFSET = 1_000_000

_SCHEDULE = """
    SELECT 'schedule' AS kind, sr.id::text AS id,
           COALESCE(s.name, LEFT(s.instruction, 80)) AS title,
           s.agent_id::text AS agent_id, a.name AS agent_name,
           sr.conversation_id::text AS conversation_id, NULL::text AS conversation_name,
           sr.trigger_source AS trigger, sr.status AS status,
           COALESCE(sr.finished_at, sr.scheduled_for) AS at,
           (EXTRACT(EPOCH FROM (sr.finished_at - sr.started_at)) * 1000)::bigint AS duration_ms,
           (sr.prompt_tokens + sr.generated_tokens)::bigint AS tokens,
           sr.schedule_id::text AS schedule_id, NULL::text AS trace_id,
           NULL::text AS workflow_run_id,
           sr.error_type AS error_type, LEFT(sr.error, 300) AS error
    FROM schedule_runs sr
    JOIN schedules s ON s.id = sr.schedule_id
    LEFT JOIN agents a ON a.id = s.agent_id
    WHERE sr.user_id = :user_id
      AND sr.status IN ('success', 'failed', 'skipped', 'timeout')
      AND COALESCE(sr.finished_at, sr.scheduled_for) > now() - make_interval(days => :days)
"""

_WEBHOOK = """
    SELECT 'webhook' AS kind, t.id::text AS id,
           COALESCE(a.name, t.name) AS title,
           t.agent_id::text AS agent_id, a.name AS agent_name,
           t.conversation_id::text AS conversation_id, NULL::text AS conversation_name,
           'webhook' AS trigger,
           CASE t.status WHEN 'ok' THEN 'success' WHEN 'cancelled' THEN 'cancelled' ELSE 'failed' END AS status,
           t.started_at + make_interval(secs => COALESCE(t.duration_ms, 0) / 1000.0) AS at,
           t.duration_ms::bigint AS duration_ms,
           (COALESCE((t.summary ->> 'input_tokens')::bigint, 0)
            + COALESCE((t.summary ->> 'output_tokens')::bigint, 0)) AS tokens,
           NULL::text AS schedule_id, t.id::text AS trace_id,
           t.workflow_run_id::text AS workflow_run_id,
           NULL::text AS error_type, NULL::text AS error
    FROM request_traces t
    LEFT JOIN agents a ON a.id = t.agent_id
    WHERE t.user_id = :user_id
      AND t.source = 'webhook'
      AND t.status IN ('ok', 'error', 'cancelled')
      AND t.started_at > now() - make_interval(days => :days)
"""

_WORKFLOW = """
    SELECT 'workflow' AS kind, r.id::text AS id,
           COALESCE(ag.name, w.name) AS title,
           ag.id::text AS agent_id, ag.name AS agent_name,
           NULL::text AS conversation_id, NULL::text AS conversation_name,
           NULL::text AS trigger,
           CASE r.status WHEN 'completed' THEN 'success' ELSE 'failed' END AS status,
           COALESCE(r.ended_at, r.started_at) AS at,
           (EXTRACT(EPOCH FROM (r.ended_at - r.started_at)) * 1000)::bigint AS duration_ms,
           NULL::bigint AS tokens,
           NULL::text AS schedule_id, NULL::text AS trace_id,
           r.id::text AS workflow_run_id,
           NULL::text AS error_type, NULL::text AS error
    FROM workflow_runs r
    JOIN workflows w ON w.id = r.workflow_id
    LEFT JOIN LATERAL (
        -- The agent that ran it; a run from before that was recorded
        -- falls back to the runner's own oldest, never another user's.
        SELECT id, name FROM agents
        WHERE workflow_id = r.workflow_id
          AND CASE WHEN r.inputs ? 'agent_id' THEN id::text = r.inputs ->> 'agent_id'
                   ELSE user_id = r.user_id END
        ORDER BY created_at ASC LIMIT 1
    ) ag ON TRUE
    WHERE r.user_id = :user_id
      AND r.status IN ('completed', 'failed')
      AND COALESCE(r.ended_at, r.started_at) > now() - make_interval(days => :days)
      AND NOT EXISTS (
          SELECT 1 FROM request_traces t
          WHERE t.workflow_run_id = r.id AND t.source IN ('webhook', 'schedule')
      )
      -- A scheduled run's workflow names it (started_by), which outlasts
      -- its trace: traces are purged sooner, or not recorded at all. The
      -- CASE keeps a starter that isn't a uuid from failing the cast.
      AND NOT EXISTS (
          SELECT 1 FROM schedule_runs sr
          WHERE sr.user_id = r.user_id
            AND sr.id = CASE
                WHEN r.inputs ->> 'started_by'
                     ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                THEN CAST(r.inputs ->> 'started_by' AS uuid)
            END
      )
"""

_JOB = """
    SELECT 'job' AS kind, j.id::text AS id,
           COALESCE(j.tool_name, 'job') AS title,
           j.agent_id::text AS agent_id, a.name AS agent_name,
           j.conversation_id::text AS conversation_id, c.name AS conversation_name,
           'chat' AS trigger,
           CASE j.status WHEN 'completed' THEN 'success' WHEN 'cancelled' THEN 'cancelled' ELSE 'failed' END AS status,
           COALESCE(j.finished_at, j.last_updated_at) AS at,
           (EXTRACT(EPOCH FROM (j.finished_at - COALESCE(j.started_at, j.created_at))) * 1000)::bigint AS duration_ms,
           NULL::bigint AS tokens,
           NULL::text AS schedule_id, NULL::text AS trace_id,
           j.workflow_run_id::text AS workflow_run_id,
           NULL::text AS error_type, LEFT(j.error::text, 300) AS error
    FROM background_jobs j
    LEFT JOIN agents a ON a.id = j.agent_id
    LEFT JOIN conversations c ON c.id = j.conversation_id
    WHERE j.user_id = :user_id
      AND j.status IN ('completed', 'failed', 'cancelled', 'lost')
      AND COALESCE(j.finished_at, j.last_updated_at) > now() - make_interval(days => :days)
"""

_MONITOR = """
    SELECT 'monitor' AS kind, wk.id::text AS id,
           COALESCE(NULLIF(wk.title, ''), c.name) AS title,
           c.agent_id::text AS agent_id, a.name AS agent_name,
           wk.conversation_id::text AS conversation_id, c.name AS conversation_name,
           wk.source AS trigger,
           CASE wk.status WHEN 'failed' THEN 'failed' ELSE 'success' END AS status,
           COALESCE(wk.delivered_at, wk.created_at) AS at,
           NULL::bigint AS duration_ms, NULL::bigint AS tokens,
           NULL::text AS schedule_id, NULL::text AS trace_id,
           NULL::text AS workflow_run_id,
           NULL::text AS error_type, LEFT(wk.error, 300) AS error
    FROM conversation_wakes wk
    JOIN conversations c ON c.id = wk.conversation_id
    LEFT JOIN agents a ON a.id = c.agent_id
    WHERE wk.user_id = :user_id
      AND wk.source IN ('monitor', 'trigger', 'approval', 'monitor_paused', 'monitor_expired')
      AND wk.status IN ('delivered', 'folded', 'failed')
      AND COALESCE(wk.delivered_at, wk.created_at) > now() - make_interval(days => :days)
"""

_PARTS = {
    "schedule": _SCHEDULE,
    "webhook": _WEBHOOK,
    "workflow": _WORKFLOW,
    "job": _JOB,
    "monitor": _MONITOR,
}


def _tools_labelled(conn: Connection, user_id: str, query: str) -> List[str]:
    """The tool ids of the user's jobs whose readable label contains ``query``.

    Args:
        conn: A read-only connection.
        user_id: Whose jobs.
        query: The search text, matched case-insensitively and literally.

    Returns:
        Tool ids, as a job row's title holds them.
    """
    names = [
        r[0]
        for r in conn.execute(
            text("SELECT DISTINCT COALESCE(tool_name, 'job') FROM background_jobs WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).fetchall()
    ]
    needle = query.casefold()
    return [name for name, label in tool_labels(conn, user_id, names).items() if needle in label.casefold()]


def list_history(
    conn: Connection,
    user_id: str,
    *,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    query: Optional[str] = None,
    days: int = DEFAULT_DAYS,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> Dict[str, Any]:
    """One page of the user's finished runs, newest first.

    Args:
        conn: A read-only connection.
        user_id: Whose runs.
        kind: One of ``KINDS``, or None for every kind.
        status: ``failed`` (failed or timed out), another of ``STATUSES``,
            or None for all.
        query: Case-insensitive text matched against the run's title (a
            job's as shown), agent and conversation names.
        days: How far back to look (clamped to ``1..MAX_DAYS``).
        limit: Rows per page (clamped to ``1..MAX_LIMIT``).
        offset: Rows to skip (clamped to ``0..MAX_OFFSET``).

    Returns:
        ``{runs, has_more}``. ``duration_ms`` and ``tokens`` are None when the
        source doesn't record them.

    Raises:
        ValueError: For an unknown ``kind`` or ``status``.
    """
    if kind and kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if status and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    parts = [_PARTS[kind]] if kind else list(_PARTS.values())
    days = max(1, min(int(days), MAX_DAYS))
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, min(int(offset), MAX_OFFSET))

    where: List[str] = []
    params: Dict[str, Any] = {"user_id": user_id, "days": days, "limit": limit + 1, "offset": offset}
    if status == "failed":
        where.append("status IN ('failed', 'timeout')")
    elif status:
        where.append("status = :status")
        params["status"] = status
    if query and query.strip():
        # A job is shown by its tool's label, not the id it is stored under,
        # so it matches by the tools whose label holds the text.
        where.append(
            "(CASE WHEN kind = 'job' THEN title = ANY(:job_tools) ELSE title ILIKE :q ESCAPE '\\' END "
            "OR agent_name ILIKE :q ESCAPE '\\' OR conversation_name ILIKE :q ESCAPE '\\')"
        )
        params["q"] = f"%{like_escape(query.strip())}%"
        params["job_tools"] = _tools_labelled(conn, user_id, query.strip())
    sql = (
        "SELECT * FROM (" + " UNION ALL ".join(parts) + ") runs"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY at DESC, id DESC LIMIT :limit OFFSET :offset"
    )
    rows = [row_to_dict(r) for r in conn.execute(text(sql), params).fetchall()]
    # A job's title is its tool's id; show the name the user knows it by.
    labels = tool_labels(conn, user_id, [r["title"] for r in rows if r.get("kind") == "job"])
    for row in rows:
        row.pop("_id", None)
        if row.get("kind") == "job" and row.get("title") in labels:
            row["title"] = labels[row["title"]]
    return {"runs": rows[:limit], "has_more": len(rows) > limit}
