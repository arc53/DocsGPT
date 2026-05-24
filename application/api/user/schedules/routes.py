"""Schedules REST API (owner-scoped via request.decoded_token)."""

from __future__ import annotations

import functools
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from application.agents.scheduler_utils import (
    ScheduleValidationError,
    clamp_once_horizon,
    cron_interval_seconds,
    next_cron_run,
    parse_cron,
    parse_run_at,
    resolve_timezone,
)
from application.api import api
from application.core.settings import settings
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.schedule_runs import (
    ScheduleRunsRepository,
)
from application.storage.db.repositories.schedules import SchedulesRepository
from application.storage.db.session import db_readonly, db_session


logger = logging.getLogger(__name__)


schedules_ns = Namespace(
    "schedules", description="Agent schedule management", path="/api",
)


def _ok(data: Any, status: int = 200):
    return make_response(jsonify(data), status)


def _err(message: str, status: int = 400):
    return make_response(jsonify({"success": False, "message": message}), status)


def _safe_route(func: Callable) -> Callable:
    """Decorator: log + mask exceptions that escape a route body as 500.

    ``ScheduleValidationError`` messages are explicitly surfaced via
    ``_err(str(exc))`` at each call site (deliberate, user-safe). This
    decorator only fires for *unexpected* exceptions (DB driver errors,
    NPEs, etc.) that escape the route body. The full trace is logged
    server-side; the response body carries no internal detail.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            try:
                current_app.logger.exception(
                    "unhandled exception in schedules route %s: %s",
                    func.__qualname__, exc,
                )
            except RuntimeError:
                # Out of Flask app context (rare in tests); use module logger.
                logger.exception(
                    "unhandled exception in schedules route %s: %s",
                    func.__qualname__, exc,
                )
            return _err("internal error", 500)
    return wrapper


def _format_schedule(row: Dict[str, Any]) -> Dict[str, Any]:
    """Render a schedule row for the API (id-as-string + ISO timestamps)."""
    if not row:
        return {}
    out = dict(row)
    for key in (
        "id", "agent_id", "origin_conversation_id",
    ):
        if out.get(key) is not None:
            out[key] = str(out[key])
    out.pop("_id", None)  # drop dual-id legacy mirror
    return out


def _format_run(row: Dict[str, Any]) -> Dict[str, Any]:
    """Render a schedule_run row for the API."""
    if not row:
        return {}
    out = dict(row)
    for key in (
        "id", "schedule_id", "agent_id", "conversation_id", "message_id",
    ):
        if out.get(key) is not None:
            out[key] = str(out[key])
    out.pop("_id", None)
    return out


def _agent_owned(agent_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    if not looks_like_uuid(str(agent_id)):
        return None
    with db_readonly() as conn:
        return AgentsRepository(conn).get_any(agent_id, user_id)


def _user_id() -> Optional[str]:
    decoded = getattr(request, "decoded_token", None)
    if not decoded:
        return None
    return decoded.get("sub")


@schedules_ns.route("/agents/<string:agent_id>/schedules")
class AgentSchedules(Resource):
    @api.doc(description="List schedules for an agent (recurring + one-time).")
    @_safe_route
    def get(self, agent_id):
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        agent = _agent_owned(agent_id, user_id)
        if agent is None:
            return _err("agent not found", 404)
        try:
            with db_readonly() as conn:
                rows = SchedulesRepository(conn).list_for_agent(
                    str(agent["id"]), user_id,
                )
        except Exception as exc:
            current_app.logger.error("list schedules failed: %s", exc, exc_info=True)
            return _err("internal error", 500)
        return _ok({"schedules": [_format_schedule(r) for r in rows]})

    create_model = api.model(
        "ScheduleCreate",
        {
            "instruction": fields.String(required=True),
            "trigger_type": fields.String(
                required=False,
                description="'recurring' (default) or 'once'",
            ),
            "cron": fields.String(
                required=False,
                description="Required when trigger_type == 'recurring'",
            ),
            "run_at": fields.String(
                required=False,
                description="ISO 8601 — required when trigger_type == 'once'",
            ),
            "timezone": fields.String(required=False),
            "name": fields.String(required=False),
            "end_at": fields.String(required=False, description="ISO 8601"),
            "tool_allowlist": fields.List(fields.String, required=False),
            "model_id": fields.String(required=False),
            "token_budget": fields.Integer(required=False),
        },
    )

    @api.expect(create_model)
    @api.doc(description="Create a schedule (recurring or one-time) for an agent.")
    @_safe_route
    def post(self, agent_id):
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        agent = _agent_owned(agent_id, user_id)
        if agent is None:
            return _err("agent not found", 404)
        data = request.get_json(silent=True) or {}
        instruction = (data.get("instruction") or "").strip()
        tz_name = (data.get("timezone") or "UTC").strip() or "UTC"
        trigger_type = (data.get("trigger_type") or "recurring").strip().lower()
        if trigger_type not in ("recurring", "once"):
            return _err("trigger_type must be 'recurring' or 'once'")
        if not instruction:
            return _err("instruction is required")
        try:
            resolve_timezone(tz_name)
        except ScheduleValidationError as exc:
            return _err(str(exc))
        token_budget = data.get("token_budget")
        if token_budget is not None:
            try:
                token_budget = int(token_budget)
                if token_budget < 0:
                    raise ValueError
            except (TypeError, ValueError):
                return _err("token_budget must be a non-negative integer")
        with db_readonly() as conn:
            count = SchedulesRepository(conn).count_active_for_user(user_id)
        if (
            settings.SCHEDULE_MAX_PER_USER > 0
            and count >= settings.SCHEDULE_MAX_PER_USER
        ):
            return _err("max schedules per user reached", 429)

        if trigger_type == "once":
            run_at_raw = (data.get("run_at") or "").strip()
            if not run_at_raw:
                return _err("run_at is required for trigger_type 'once'")
            try:
                fire = parse_run_at(run_at_raw, tz_name)
                clamp_once_horizon(
                    fire, settings.SCHEDULE_ONCE_MAX_HORIZON,
                )
            except ScheduleValidationError as exc:
                return _err(str(exc))
            try:
                with db_session() as conn:
                    created = SchedulesRepository(conn).create(
                        user_id=user_id,
                        agent_id=str(agent["id"]),
                        trigger_type="once",
                        instruction=instruction,
                        run_at=fire,
                        next_run_at=fire,
                        timezone=tz_name,
                        name=(data.get("name") or "").strip() or None,
                        tool_allowlist=data.get("tool_allowlist") or [],
                        model_id=(data.get("model_id") or None),
                        token_budget=token_budget,
                        created_via="ui",
                    )
            except Exception as exc:
                current_app.logger.error(
                    "create one-time schedule failed: %s", exc, exc_info=True,
                )
                return _err("internal error", 500)
            return _ok({"schedule": _format_schedule(created)}, status=201)

        cron = (data.get("cron") or "").strip()
        if not cron:
            return _err("cron is required")
        try:
            parse_cron(cron)
        except ScheduleValidationError as exc:
            return _err(str(exc))
        min_interval = max(0, int(settings.SCHEDULE_MIN_INTERVAL))
        if min_interval > 0:
            try:
                cadence = cron_interval_seconds(cron, tz_name)
            except ScheduleValidationError as exc:
                return _err(str(exc))
            if cadence < min_interval:
                return _err(
                    "cadence below minimum interval "
                    f"({cadence}s < {min_interval}s)",
                )
        end_at = None
        if data.get("end_at"):
            try:
                end_at = datetime.fromisoformat(
                    str(data["end_at"]).replace("Z", "+00:00"),
                )
            except ValueError:
                return _err("invalid end_at")
        try:
            next_run = next_cron_run(cron, tz_name, after=datetime.now(timezone.utc))
        except ScheduleValidationError as exc:
            return _err(str(exc))
        if end_at is not None and next_run > end_at:
            return _err("end_at is before the first cron tick")
        try:
            with db_session() as conn:
                created = SchedulesRepository(conn).create(
                    user_id=user_id,
                    agent_id=str(agent["id"]),
                    trigger_type="recurring",
                    instruction=instruction,
                    cron=cron,
                    timezone=tz_name,
                    next_run_at=next_run,
                    end_at=end_at,
                    name=(data.get("name") or "").strip() or None,
                    tool_allowlist=data.get("tool_allowlist") or [],
                    model_id=(data.get("model_id") or None),
                    token_budget=token_budget,
                    created_via="ui",
                )
        except Exception as exc:
            current_app.logger.error(
                "create schedule failed: %s", exc, exc_info=True,
            )
            return _err("internal error", 500)
        return _ok({"schedule": _format_schedule(created)}, status=201)


@schedules_ns.route("/schedules/<string:schedule_id>")
class ScheduleResource(Resource):
    @api.doc(description="Get schedule by id.")
    @_safe_route
    def get(self, schedule_id):
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        if not looks_like_uuid(schedule_id):
            return _err("invalid schedule id", 400)
        with db_readonly() as conn:
            row = SchedulesRepository(conn).get(schedule_id, user_id)
        if row is None:
            return _err("schedule not found", 404)
        return _ok({"schedule": _format_schedule(row)})

    @api.doc(description="Edit a schedule's editable fields.")
    @_safe_route
    def put(self, schedule_id):
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        if not looks_like_uuid(schedule_id):
            return _err("invalid schedule id", 400)
        data = request.get_json(silent=True) or {}
        fields_in: Dict[str, Any] = {}
        if "instruction" in data:
            inst = (data["instruction"] or "").strip()
            if not inst:
                return _err("instruction must not be empty")
            fields_in["instruction"] = inst
        if "cron" in data:
            cron = (data["cron"] or "").strip()
            try:
                parse_cron(cron)
            except ScheduleValidationError as exc:
                return _err(str(exc))
            fields_in["cron"] = cron
        if "timezone" in data:
            tz_name = (data["timezone"] or "UTC").strip() or "UTC"
            try:
                resolve_timezone(tz_name)
            except ScheduleValidationError as exc:
                return _err(str(exc))
            fields_in["timezone"] = tz_name
        if "tool_allowlist" in data:
            fields_in["tool_allowlist"] = data["tool_allowlist"] or []
        if "name" in data:
            fields_in["name"] = (data["name"] or "").strip() or None
        if "model_id" in data:
            fields_in["model_id"] = (data["model_id"] or None)
        if "token_budget" in data:
            tb = data["token_budget"]
            if tb is not None:
                try:
                    tb = int(tb)
                    if tb < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    return _err("token_budget must be a non-negative integer")
            fields_in["token_budget"] = tb
        if "end_at" in data:
            if data["end_at"]:
                try:
                    fields_in["end_at"] = datetime.fromisoformat(
                        str(data["end_at"]).replace("Z", "+00:00"),
                    )
                except ValueError:
                    return _err("invalid end_at")
            else:
                fields_in["end_at"] = None
        # Recompute next_run_at when cron/tz changes.
        with db_session() as conn:
            existing = SchedulesRepository(conn).get(schedule_id, user_id)
            if existing is None:
                return _err("schedule not found", 404)
            if (
                ("cron" in fields_in or "timezone" in fields_in)
                and existing.get("trigger_type") == "recurring"
            ):
                cron_eff = fields_in.get("cron") or existing.get("cron")
                tz_eff = fields_in.get("timezone") or existing.get("timezone")
                if cron_eff:
                    min_interval = max(0, int(settings.SCHEDULE_MIN_INTERVAL))
                    if min_interval > 0:
                        try:
                            cadence = cron_interval_seconds(cron_eff, tz_eff)
                        except ScheduleValidationError as exc:
                            return _err(str(exc))
                        if cadence < min_interval:
                            return _err(
                                "cadence below minimum interval "
                                f"({cadence}s < {min_interval}s)",
                            )
                    try:
                        fields_in["next_run_at"] = next_cron_run(
                            cron_eff, tz_eff, after=datetime.now(timezone.utc),
                        )
                    except ScheduleValidationError as exc:
                        return _err(str(exc))
            updated = SchedulesRepository(conn).update(
                schedule_id, user_id, fields_in,
            )
        return _ok({"schedule": _format_schedule(updated or {})})

    @api.doc(description="Pause / resume a schedule.")
    @_safe_route
    def patch(self, schedule_id):
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        if not looks_like_uuid(schedule_id):
            return _err("invalid schedule id", 400)
        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "").lower().strip()
        if action not in {"pause", "resume"}:
            return _err("action must be 'pause' or 'resume'")
        with db_session() as conn:
            existing = SchedulesRepository(conn).get(schedule_id, user_id)
            if existing is None:
                return _err("schedule not found", 404)
            if existing.get("status") in ("cancelled", "completed"):
                return _err("schedule is terminal", 409)
            if action == "pause":
                fields_in: Dict[str, Any] = {"status": "paused", "next_run_at": None}
            else:
                # Resume: recurring recomputes from now; once honours run_at if still future.
                fields_in = {"status": "active"}
                if existing.get("trigger_type") == "recurring":
                    try:
                        fields_in["next_run_at"] = next_cron_run(
                            existing["cron"],
                            existing["timezone"],
                            after=datetime.now(timezone.utc),
                        )
                    except ScheduleValidationError as exc:
                        return _err(str(exc))
                else:
                    new_run_at = data.get("run_at")
                    if new_run_at:
                        try:
                            run_at_dt = datetime.fromisoformat(
                                str(new_run_at).replace("Z", "+00:00"),
                            )
                        except ValueError:
                            return _err("invalid run_at")
                        if run_at_dt <= datetime.now(timezone.utc):
                            return _err(
                                "run_at must be in the future to resume", 409,
                            )
                        fields_in["next_run_at"] = run_at_dt
                        fields_in["run_at"] = run_at_dt
                    else:
                        run_at = existing.get("run_at")
                        if run_at:
                            if isinstance(run_at, str):
                                try:
                                    run_at_dt = datetime.fromisoformat(
                                        run_at.replace("Z", "+00:00"),
                                    )
                                except ValueError:
                                    return _err("schedule run_at is invalid")
                            else:
                                run_at_dt = run_at
                            if run_at_dt <= datetime.now(timezone.utc):
                                return _err(
                                    "the once schedule has elapsed; recreate "
                                    "it or supply a new run_at",
                                    409,
                                )
                            fields_in["next_run_at"] = run_at_dt
            updated = SchedulesRepository(conn).update(
                schedule_id, user_id, fields_in,
            )
            if action == "resume":
                SchedulesRepository(conn).reset_failure_count(schedule_id)
        return _ok({"schedule": _format_schedule(updated or {})})

    @api.doc(description="Cancel / delete a schedule.")
    @_safe_route
    def delete(self, schedule_id):
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        if not looks_like_uuid(schedule_id):
            return _err("invalid schedule id", 400)
        with db_session() as conn:
            ok = SchedulesRepository(conn).delete(schedule_id, user_id)
        if not ok:
            return _err("schedule not found", 404)
        return _ok({"success": True})


@schedules_ns.route("/schedules/<string:schedule_id>/run")
class ScheduleRunNow(Resource):
    @api.doc(description="Run a schedule immediately (trigger_source='manual').")
    @_safe_route
    def post(self, schedule_id):
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        if not looks_like_uuid(schedule_id):
            return _err("invalid schedule id", 400)
        # FOR UPDATE serializes concurrent Run-Now POSTs (timestamp-unique
        # scheduled_for values would otherwise sneak past the unique index).
        with db_session() as conn:
            schedule = SchedulesRepository(conn).get_for_update(
                schedule_id, user_id,
            )
            if schedule is None:
                return _err("schedule not found", 404)
            if schedule.get("status") == "cancelled":
                return _err("schedule is cancelled", 409)
            if ScheduleRunsRepository(conn).has_active_run(schedule_id):
                return _err("a run is already in flight", 409)
            scheduled_for = datetime.now(timezone.utc)
            agent_id_raw = schedule.get("agent_id")
            run = ScheduleRunsRepository(conn).record_pending(
                schedule_id,
                user_id,
                str(agent_id_raw) if agent_id_raw else None,
                scheduled_for,
                trigger_source="manual",
            )
        if run is None:
            return _err("could not claim run (concurrent dispatch)", 409)
        # Import inside the handler to avoid a circular tasks <-> routes import.
        try:
            from application.api.user.tasks import execute_scheduled_run
            execute_scheduled_run.apply_async(args=[str(run["id"])], queue="docsgpt")
        except Exception as exc:
            current_app.logger.error(
                "run-now enqueue failed: %s", exc, exc_info=True,
            )
            return _err("enqueue failed", 500)
        return _ok({"run": _format_run(run)}, status=202)


@schedules_ns.route("/schedules/<string:schedule_id>/runs")
class ScheduleRunList(Resource):
    @api.doc(
        description="Paginated run log for a schedule.",
        params={"limit": "Page size (default 50)", "offset": "Page offset"},
    )
    @_safe_route
    def get(self, schedule_id):
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        if not looks_like_uuid(schedule_id):
            return _err("invalid schedule id", 400)
        try:
            limit = max(1, min(int(request.args.get("limit", 50)), 200))
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = max(0, int(request.args.get("offset", 0)))
        except (TypeError, ValueError):
            offset = 0
        with db_readonly() as conn:
            schedule = SchedulesRepository(conn).get(schedule_id, user_id)
            if schedule is None:
                return _err("schedule not found", 404)
            rows = ScheduleRunsRepository(conn).list_runs(
                schedule_id, user_id, limit=limit, offset=offset,
            )
        return _ok(
            {
                "runs": [_format_run(r) for r in rows],
                "limit": limit,
                "offset": offset,
            }
        )


@schedules_ns.route("/schedules/<string:schedule_id>/runs/<string:run_id>")
class ScheduleRunDetail(Resource):
    @api.doc(description="Full output / error for a single run.")
    @_safe_route
    def get(self, schedule_id, run_id):
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        if not looks_like_uuid(schedule_id) or not looks_like_uuid(run_id):
            return _err("invalid id", 400)
        with db_readonly() as conn:
            schedule = SchedulesRepository(conn).get(schedule_id, user_id)
            if schedule is None:
                return _err("schedule not found", 404)
            run = ScheduleRunsRepository(conn).get(run_id, user_id)
            if run is None or str(run.get("schedule_id")) != str(
                schedule["id"]
            ):
                return _err("run not found", 404)
        return _ok({"run": _format_run(run)})
