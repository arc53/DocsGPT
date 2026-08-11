"""Schedule dispatcher: poll Postgres, claim due rows under FOR UPDATE SKIP LOCKED,
advance next_run_at atomically with the run claim, then enqueue.

Per-schedule IANA tz semantics (croniter+zoneinfo) outside Celery's app-wide tz,
plus Postgres-native dedup avoid Redis visibility_timeout double-fires.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from application.agents.scheduler_utils import next_cron_run
from application.core.settings import settings
from application.storage.db.engine import get_engine
from application.storage.db.repositories.schedule_runs import (
    ScheduleRunsRepository,
)
from application.storage.db.repositories.schedules import SchedulesRepository

logger = logging.getLogger(__name__)


def _normalize_dt(value: Any) -> Optional[datetime]:
    """Accept a datetime / ISO string / None and return a tz-aware UTC dt."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else (
            value.replace(tzinfo=timezone.utc)
        )
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else (
            parsed.replace(tzinfo=timezone.utc)
        )
    return None


def _compute_next(
    schedule: Dict[str, Any],
    *,
    after: datetime,
) -> Optional[datetime]:
    """Next next_run_at for a recurring schedule, or None when past end_at."""
    cron = schedule.get("cron")
    if not cron:
        return None
    end_at = _normalize_dt(schedule.get("end_at"))
    candidate = next_cron_run(cron, schedule.get("timezone"), after=after)
    if end_at is not None and candidate > end_at:
        return None
    return candidate


def dispatch_due_runs() -> Dict[str, int]:
    """One dispatcher tick; returns counts for schedule_syncs-style logging."""
    if not settings.POSTGRES_URI:
        return {"enqueued": 0, "skipped": 0, "advanced": 0}

    from application.api.user.tasks import execute_scheduled_run

    now = datetime.now(timezone.utc)
    grace = timedelta(seconds=max(0, settings.SCHEDULE_MISFIRE_GRACE))
    engine = get_engine()
    counts = {"enqueued": 0, "skipped": 0, "advanced": 0}
    enqueue_args: List[str] = []

    with engine.begin() as conn:
        schedules_repo = SchedulesRepository(conn)
        runs_repo = ScheduleRunsRepository(conn)
        for schedule in schedules_repo.list_due():
            scheduled_for = _normalize_dt(schedule.get("next_run_at"))
            if scheduled_for is None:
                continue

            trigger_type = schedule.get("trigger_type")
            agent_id_raw = schedule.get("agent_id")
            agent_id = str(agent_id_raw) if agent_id_raw else None

            # Misfire grace applies to recurring only — once-tasks fire late, not vanish.
            if (
                trigger_type == "recurring"
                and grace > timedelta(0)
                and (now - scheduled_for) > grace
            ):
                runs_repo.record_skipped(
                    str(schedule["id"]),
                    schedule["user_id"],
                    agent_id,
                    scheduled_for,
                    error_type="missed",
                    error="misfire grace exceeded",
                )
                counts["skipped"] += 1
                nxt = _compute_next(schedule, after=now)
                if nxt is None:
                    schedules_repo.update_internal(
                        str(schedule["id"]),
                        {"status": "completed", "next_run_at": None,
                         "last_run_at": now},
                    )
                else:
                    schedules_repo.update_internal(
                        str(schedule["id"]),
                        {"next_run_at": nxt, "last_run_at": now},
                    )
                counts["advanced"] += 1
                continue

            # Overlap guard: never enqueue while a previous run is active.
            if runs_repo.has_active_run(str(schedule["id"])):
                runs_repo.record_skipped(
                    str(schedule["id"]),
                    schedule["user_id"],
                    agent_id,
                    scheduled_for,
                    error_type="overlap",
                    error="previous run still active",
                )
                counts["skipped"] += 1
                if trigger_type == "recurring":
                    nxt = _compute_next(schedule, after=scheduled_for)
                    schedules_repo.update_internal(
                        str(schedule["id"]),
                        {"next_run_at": nxt, "last_run_at": now},
                    )
                else:
                    # Once: null next_run_at so we don't re-pick; the in-flight
                    # run will terminal-flip the schedule when it finishes.
                    schedules_repo.update_internal(
                        str(schedule["id"]),
                        {"next_run_at": None, "last_run_at": now},
                    )
                continue

            # Dedup primitive: two racing dispatchers see exactly one row.
            run = runs_repo.record_pending(
                str(schedule["id"]),
                schedule["user_id"],
                agent_id,
                scheduled_for,
                trigger_source="cron",
            )
            if run is None:
                counts["skipped"] += 1
            else:
                enqueue_args.append(str(run["id"]))
                counts["enqueued"] += 1

            # Advance: recurring picks next tick, once nulls next_run_at
            # (worker terminal-flips status on completion).
            if trigger_type == "recurring":
                nxt = _compute_next(schedule, after=scheduled_for)
                if nxt is None:
                    schedules_repo.update_internal(
                        str(schedule["id"]),
                        {"status": "completed", "next_run_at": None,
                         "last_run_at": now},
                    )
                else:
                    schedules_repo.update_internal(
                        str(schedule["id"]),
                        {"next_run_at": nxt, "last_run_at": now},
                    )
            else:
                schedules_repo.update_internal(
                    str(schedule["id"]),
                    {"next_run_at": None, "last_run_at": now},
                )
            counts["advanced"] += 1

    # Enqueue after commit so the worker sees the schedule_runs row on pick-up.
    for run_id in enqueue_args:
        try:
            execute_scheduled_run.apply_async(args=[run_id], queue="docsgpt")
        except Exception:
            logger.exception(
                "dispatcher: failed to enqueue execute_scheduled_run for %s",
                run_id,
            )
    return counts
