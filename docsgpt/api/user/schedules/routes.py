"""Schedules REST API.

A schedule on an agent belongs to the agent's owner: it is stored (and runs)
under the owner's ``user_id`` whoever creates it, and managing it needs
``manage_schedules`` on the agent (owner and team editors). A schedule the
caller made themselves (e.g. via the chat scheduler tool on a shared agent)
stays theirs to manage.

A team's agent is the exception: a team pays for nothing, so a schedule
on it is stored under the member who set it, who pays for its runs (the run
still acts as the team's principal). Its Editors and up manage every such
schedule, and the list is per workspace: a team's agents' schedules show in
that team only.
"""

from __future__ import annotations

import functools
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from docsgpt.agents.scheduler_utils import (
    ScheduleValidationError,
    clamp_once_horizon,
    cron_interval_seconds,
    next_cron_run,
    parse_cron,
    parse_run_at,
    resolve_timezone,
)
from docsgpt.api import api
from docsgpt.api.audit import record_event
from docsgpt.api.user.agents.graph_checks import refuse_unfinished_graph
from docsgpt.api.user.resource_access import (
    WORKSPACE_ACTIONS,
    AccessDenied,
    allowed_actions,
    created_by_payload,
    creator_payloads,
    require,
    settings_many,
    workspace_allowed_actions,
)
from docsgpt.api.user.team_sharing import visible_with_access
from docsgpt.core.settings import settings
from docsgpt.quotas.pause import PayerChecks, schedule_pause
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.schedule_runs import (
    ScheduleRunsRepository,
)
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.utils import generate_image_url
from docsgpt.workspaces.context import WorkspaceError, current_workspace
from docsgpt.workspaces.principal import is_principal_id, team_of_principal
from docsgpt.workspaces.roles import role_at_least, team_role_for


logger = logging.getLogger(__name__)


schedules_ns = Namespace(
    "schedules", description="Agent schedule management", path="/api",
)


def _ok(data: Any, status: int = 200):
    return make_response(jsonify(data), status)


def _err(message: str, status: int = 400):
    return make_response(jsonify({"success": False, "message": message}), status)


def _refuse(status: int, code: str, message: str):
    """An error response with a machine-readable ``error`` code beside the message."""
    return make_response(jsonify({"success": False, "error": code, "message": message}), status)


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


def _mark_owner_inactive(conn, rows: list[Dict[str, Any]], agent_owners: list[Optional[str]]) -> None:
    """Set ``owner_inactive`` on each schedule row, in place.

    A schedule pauses while the owner of its agent, or the user it is stored
    under, is deactivated: its runs are skipped with that reason.

    Args:
        conn: Open database connection.
        rows: Schedule rows (need ``user_id``).
        agent_owners: The owner of each row's agent, None when agentless.
    """
    inactive = UsersRepository(conn).deactivated_among(
        [row.get("user_id") for row in rows] + list(agent_owners)
    )
    for row, agent_owner in zip(rows, agent_owners):
        row["owner_inactive"] = row.get("user_id") in inactive or agent_owner in inactive


def _format_run(row: Dict[str, Any], caller: Optional[str] = None) -> Dict[str, Any]:
    """Render a schedule_run row for the API.

    Args:
        row: The run.
        caller: Who asked. A teammate managing the owner's schedule gets no
            ``conversation_id``/``message_id``: the run's chat is the
            owner's, and the link would open nothing.

    Returns:
        The run as JSON-ready fields.
    """
    if not row:
        return {}
    out = dict(row)
    for key in (
        "id", "schedule_id", "agent_id", "conversation_id", "message_id",
    ):
        if out.get(key) is not None:
            out[key] = str(out[key])
    if caller is not None and "user_id" in out and out["user_id"] != caller:
        for key in ("conversation_id", "message_id"):
            if key in out:
                out[key] = None
    out.pop("_id", None)
    return out


def _agent_for_schedules(agent_id: str, user_id: str) -> tuple[Dict[str, Any], str]:
    """The agent row and the id a new schedule on it is stored under.

    Args:
        agent_id: Agent id from the URL.
        user_id: The caller.

    Returns:
        ``(agent, owner_id)``: the agent's owner, or the caller on a team's
        agent (the setter pays, never the team's principal).

    Raises:
        AccessDenied: 404 when the agent isn't visible, 403 without
            ``manage_schedules``.
    """
    if not looks_like_uuid(str(agent_id)):
        raise AccessDenied(404, "agent not found")
    with db_readonly() as conn:
        try:
            ra = require(conn, "agent", agent_id, user_id, "manage_schedules")
        except AccessDenied as denied:
            if denied.status == 404:
                raise AccessDenied(404, "agent not found")
            raise
        agent = AgentsRepository(conn).get_by_id(ra.resource_id)
    if agent is None:
        raise AccessDenied(404, "agent not found")
    return agent, (user_id if ra.is_team_item else ra.owner_id)


def _schedule_for(
    conn, schedule_id: str, user_id: str, own_action: str = "manage_schedules",
) -> tuple[Dict[str, Any], str]:
    """Fetch a schedule the caller may manage, and the id to act as.

    The caller's own schedule is theirs, except on a team's agent, where they
    still need ``own_action`` there: someone who left the team, or lost the
    role, stops managing what they set. Otherwise it must be a schedule of an
    agent they hold ``manage_schedules`` on, stored under that agent's owner
    (another member's private schedule stays hidden).

    Args:
        conn: Open database connection.
        schedule_id: Schedule UUID.
        user_id: The caller.
        own_action: The agent action the caller needs on a team's agent to
            reach their own schedule: ``manage_schedules`` to change it,
            ``use`` to read it (a Viewer still lists the schedules they set).

    Returns:
        ``(schedule, acting_user_id)``.

    On a team's agent every member's schedule is reachable by the team's
    Editors and up, and acted on as the member who set it (they still pay).

    Raises:
        AccessDenied: 404 when not visible, 403 when the role can't manage it.
    """
    row = SchedulesRepository(conn).get_internal(schedule_id)
    # A monitor is managed from /api/monitors, never as a schedule.
    if row is None or row.get("trigger_type") == "monitor":
        raise AccessDenied(404, "schedule not found")
    agent_id = row.get("agent_id")
    if row.get("user_id") == user_id:
        agent = AgentsRepository(conn).get_by_id(str(agent_id)) if agent_id else None
        if agent is None or not is_principal_id(agent.get("user_id")):
            return row, user_id
        _require_on_agent(conn, str(agent_id), user_id, own_action)
        return row, user_id
    if not agent_id:
        raise AccessDenied(404, "schedule not found")
    ra = _require_on_agent(conn, str(agent_id), user_id, "manage_schedules")
    if ra.is_team_item and not is_principal_id(row.get("user_id")):
        return row, row["user_id"]
    if row.get("user_id") != ra.owner_id:
        raise AccessDenied(404, "schedule not found")
    return row, ra.owner_id


def _require_on_agent(conn, agent_id: str, user_id: str, action: str):
    """``require`` on a schedule's agent, a hidden agent reading as a missing schedule.

    Args:
        conn: Open database connection.
        agent_id: The schedule's agent.
        user_id: The caller.
        action: The agent action needed.

    Returns:
        The caller's ``ResourceAccess`` on the agent.

    Raises:
        AccessDenied: 404 when the agent isn't visible, 403 when the role can't do ``action``.
    """
    try:
        return require(conn, "agent", agent_id, user_id, action)
    except AccessDenied as denied:
        if denied.status == 404:
            raise AccessDenied(404, "schedule not found")
        raise


def _refuse_unfinished_agent_graph(conn, agent_id) -> Any:
    """The 400 that keeps a schedule from running a workflow agent's unfinished graph.

    Args:
        conn: Open database connection.
        agent_id: The schedule's agent, or None for an agentless one.

    Returns:
        The error response, or None when the schedule may run.
    """
    if not agent_id:
        return None
    agent = AgentsRepository(conn).get_by_id(str(agent_id))
    return refuse_unfinished_graph(conn, agent) if agent else None


def _user_id() -> Optional[str]:
    decoded = getattr(request, "decoded_token", None)
    if not decoded:
        return None
    return decoded.get("sub")


def _reschedule_once(
    existing: Dict[str, Any], run_at_raw: Any, tz_override: Optional[str],
) -> tuple[Dict[str, Any], Any]:
    """Validate a new ``run_at`` for a one-time task and build its update.

    Applies the same rules as creating a one-time task: a naive time is read
    in the task's timezone (the one in the same request, if any), and the time
    must be in the future and within ``SCHEDULE_ONCE_MAX_HORIZON``. An active
    task is re-armed at the new time; a paused one keeps ``next_run_at`` empty
    so that resuming it picks the new ``run_at`` up.

    Args:
        existing: The stored schedule row.
        run_at_raw: The ``run_at`` value from the request body.
        tz_override: The timezone sent in the same request, if any.

    Returns:
        ``(fields, None)`` with the columns to update, or ``({}, response)``
        with the error response to return.
    """
    if existing.get("trigger_type") != "once":
        return {}, _err(
            "run_at can only be changed on a one-time task; "
            "change a recurring schedule's cron instead",
        )
    status = existing.get("status")
    if status in ("completed", "cancelled"):
        return {}, _err(f"a {status} task can't be rescheduled", 409)
    if status == "active" and existing.get("next_run_at") is None:
        return {}, _err("the task is already running and can't be rescheduled", 409)
    tz_name = tz_override or existing.get("timezone") or "UTC"
    try:
        fire = parse_run_at(run_at_raw, tz_name)
        clamp_once_horizon(fire, settings.SCHEDULE_ONCE_MAX_HORIZON)
    except ScheduleValidationError as exc:
        return {}, _err(str(exc))
    fields: Dict[str, Any] = {"run_at": fire}
    if status == "active":
        fields["next_run_at"] = fire
    return fields, None


def _publish_schedule_event(
    user_id: str, event_type: str, schedule_id: str, *, status: str,
) -> None:
    """Best-effort SSE so other clients revoke a stale schedule state.

    A resume/cancel must override an earlier ``schedule.autopaused``; that
    envelope is durable and replays from the backlog on reconnect, so
    without a newer event the schedule reads 'paused' even though it will
    fire on the next tick.
    """
    try:
        from docsgpt.events.publisher import publish_user_event

        publish_user_event(
            user_id,
            event_type,
            {"schedule_id": str(schedule_id), "status": status},
            scope={"kind": "schedule", "id": str(schedule_id)},
        )
    except Exception:
        logger.exception(
            "schedules: publish %s failed for %s", event_type, schedule_id,
        )


def _mark_paid_by(conn, viewer: str, rows: list[Dict[str, Any]], agent_owners: list[Optional[str]]) -> None:
    """Set ``paid_by`` (``{user_id, label}``) on each schedule row, in place: the person it is stored under.

    A team's agent names its schedules' setters to every member, as its own
    record; a personal agent names someone only to a reader who knows them
    (``resource_access.creator_payloads``). A schedule stored under a team's
    principal has nobody paying for it (the team is never billed), so its
    ``paid_by`` is None.

    Args:
        conn: Open database connection.
        viewer: The caller.
        rows: Schedule rows (need ``user_id``).
        agent_owners: The owner of each row's agent, None when agentless.
    """
    pairs = [{"user_id": owner, "created_by": row.get("user_id")} for row, owner in zip(rows, agent_owners)]
    payers = creator_payloads(conn, viewer, pairs)
    for row, pair in zip(rows, pairs):
        row["paid_by"] = None if is_principal_id(row.get("user_id")) else created_by_payload(pair, payers)


#: Statuses of a schedule that still runs, or would once resumed.
_LIVE_STATUSES = ("active", "paused")


def _may_take_over(conn, checks: PayerChecks, viewer: str, row: Dict[str, Any], agent_owner: Optional[str]) -> bool:
    """Whether ``viewer`` may make themselves the payer of a schedule.

    Only a schedule on a team's agent can change payer (a personal agent's
    schedule is its setter's own), only by someone whose team role manages
    schedules there (Editor and up), and only when they don't pay already.

    Args:
        conn: Open database connection.
        checks: The request's payer checks (caches team roles).
        viewer: The caller.
        row: The schedule (``user_id``, ``status``).
        agent_owner: The owner of its agent; None when agentless.

    Returns:
        True when a take over would be allowed.
    """
    team_id = team_of_principal(agent_owner)
    if not team_id or row.get("user_id") == viewer or row.get("status") not in _LIVE_STATUSES:
        return False
    return role_at_least(checks.team_role(conn, viewer, team_id), WORKSPACE_ACTIONS["agent"]["manage_schedules"])


def _mark_payer_state(
    conn, viewer: str, rows: list[Dict[str, Any]], agent_owners: list[Optional[str]],
) -> None:
    """Set ``paused_for`` and ``can_take_over`` on each schedule row, in place.

    ``paused_for`` is ``{reason, until, since}`` while the schedule is paused
    for its payer (``quotas.pause.schedule_pause``), else None: ``until`` is
    when it resumes by itself (an allowance's reset), ``since`` when its runs
    began to be skipped for that reason (None before the first skip). Only an
    ``active`` schedule is reported paused: one a person or auto-pause
    stopped isn't running, so nothing pauses it for its payer (the team's
    Usage tab and the payer's quota leave it out too). Each distinct payer's
    allowance is checked once per call.

    Args:
        conn: Open database connection.
        viewer: The caller.
        rows: Schedule rows (``id``, ``user_id``, ``agent_id``, ``status``).
        agent_owners: The owner of each row's agent, None when agentless.
    """
    checks = PayerChecks()
    pauses = []
    for row, owner in zip(rows, agent_owners):
        running = row.get("status") == "active"
        agent = {"id": row.get("agent_id"), "user_id": owner} if row.get("agent_id") else None
        pauses.append(schedule_pause(conn, row, agent, checks=checks) if running else None)
        row["can_take_over"] = _may_take_over(conn, checks, viewer, row, owner)
    paused = [str(row["id"]) for row, pause in zip(rows, pauses) if pause is not None]
    latest = ScheduleRunsRepository(conn).latest_finished(paused) if paused else {}
    for row, pause in zip(rows, pauses):
        if pause is None:
            row["paused_for"] = None
            continue
        run = latest.get(str(row["id"])) or {}
        # A paused streak keeps one row, its first skip; a new payer's pause starts a streak of its own.
        streak = (
            run.get("status") == "skipped"
            and run.get("error_type") == pause.reason
            and run.get("user_id") == row.get("user_id")
        )
        row["paused_for"] = {**pause.payload(), "since": run.get("scheduled_for") if streak else None}


def _list_payload(conn, viewer: str, rows: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Schedule rows with context (``agent_user_id``, ``agent_image``) as the lists return them.

    Args:
        conn: Open database connection.
        viewer: The caller.
        rows: Rows from a ``*_with_context`` query, with ``team`` already set.

    Returns:
        The rows as JSON-ready payloads, with ``owner_inactive``, ``paid_by``,
        ``paused_for``, ``can_take_over`` and a signed ``agent_image``.
    """
    agent_owners = [row.pop("agent_user_id", None) for row in rows]
    _mark_owner_inactive(conn, rows, agent_owners)
    _mark_paid_by(conn, viewer, rows, agent_owners)
    _mark_payer_state(conn, viewer, rows, agent_owners)
    out = []
    for row, agent_owner in zip(rows, agent_owners):
        image = row.get("agent_image")
        # A storage path never leaves the server: sign it as the agents
        # API does, or drop it.
        row["agent_image"] = (
            generate_image_url(image, row.get("agent_id"), agent_owner)
            if image and row.get("agent_id")
            else None
        )
        out.append(_format_schedule(row))
    return out


def _runs_user(conn, schedule: Dict[str, Any], acting: str, viewer: str) -> Optional[str]:
    """Whose runs a schedule's run log shows: everyone's on a team agent, else the acting user's.

    A team agent's schedule changes payer when someone takes it over; its log
    keeps the runs billed to whoever paid before. Only those who manage the
    team's schedules read that whole log: a setter who is now a Viewer reads
    the runs billed to them.

    Args:
        conn: Open database connection.
        schedule: The schedule row.
        acting: The id the caller acts as on it.
        viewer: The caller.

    Returns:
        The user to filter runs by, or None for every run of the schedule.
    """
    agent_id = schedule.get("agent_id")
    if agent_id:
        agent = AgentsRepository(conn).get_by_id(str(agent_id))
        if agent is not None and is_principal_id(agent.get("user_id")):
            team_id = team_of_principal(agent.get("user_id"))
            if role_at_least(team_role_for(conn, viewer, team_id), WORKSPACE_ACTIONS["agent"]["manage_schedules"]):
                return None
    return acting


def _team_schedule_agents(conn, user_id: str) -> list[str]:
    """Agents shared to the caller's teams on which their role may manage schedules.

    Args:
        conn: Open database connection.
        user_id: The caller.

    Returns:
        Agent ids (the caller's own agents are not included).
    """
    grants = visible_with_access(conn, user_id, "agent")
    if not grants:
        return []
    switches = settings_many(conn, "agent", grants.keys())
    return [
        agent_id
        for agent_id, access in grants.items()
        if "manage_schedules" in allowed_actions("agent", access, switches.get(agent_id))
    ]


@schedules_ns.route("/schedules")
class UserSchedules(Resource):
    @api.doc(
        description=(
            "List the schedules of the current workspace (X-DocsGPT-Workspace). Personal: the caller's own "
            "across every personal agent, agentless ones created in chat, and those of teammates' agents they "
            "manage through a team (team: true). A team: the schedules on the team's agents, every member's "
            "for an Editor and up, the caller's own for a Viewer. Each row names who pays for it (paid_by). "
            "Monitors are not included."
        ),
    )
    @_safe_route
    def get(self):
        """Return the workspace's schedules with agent and origin-chat names.

        Returns:
            A Flask response with ``workspace`` (``{kind, team_id, role}``) and
            ``schedules``: schedule rows plus ``agent_name``, ``agent_image``
            (a signed URL, never a storage path), ``origin_conversation_name``,
            ``team`` (someone else's schedule the caller manages through a
            team) and ``paid_by``.
        """
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        with db_readonly() as conn:
            try:
                workspace = current_workspace(conn)
            except WorkspaceError as err:
                return err.response()
            repo = SchedulesRepository(conn)
            if workspace.is_team:
                manages = "manage_schedules" in workspace_allowed_actions("agent", workspace.role)
                found = repo.list_for_owner_agents_with_context(
                    workspace.owner_id, user_id, setter=None if manages else user_id,
                )
                rows = [{**row, "team": row.get("user_id") != user_id} for row in found]
            else:
                # A schedule on a team's agent lists in that team, not here.
                own = [
                    row for row in repo.list_owned_with_context(user_id)
                    if not is_principal_id(row.get("agent_user_id"))
                ]
                team = repo.list_for_agents_with_context(_team_schedule_agents(conn, user_id))
                seen = {str(row["id"]) for row in own}
                rows = [{**row, "team": False} for row in own] + [
                    {**row, "team": True} for row in team if str(row["id"]) not in seen
                ]
            out = _list_payload(conn, user_id, rows)
        return _ok({"schedules": out, "workspace": workspace.payload()})


@schedules_ns.route("/agents/<string:agent_id>/schedules")
class AgentSchedules(Resource):
    @api.doc(description="List schedules for an agent (recurring + one-time).")
    @_safe_route
    def get(self, agent_id):
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        try:
            agent, owner_id = _agent_for_schedules(agent_id, user_id)
        except AccessDenied as denied:
            return _err(denied.message, denied.status)
        try:
            with db_readonly() as conn:
                # A team agent's schedules are stored under the members who set
                # them, and its Editors manage every one.
                rows = SchedulesRepository(conn).list_for_agent(
                    str(agent["id"]), None if is_principal_id(agent.get("user_id")) else owner_id,
                )
                owners = [agent.get("user_id")] * len(rows)
                _mark_owner_inactive(conn, rows, owners)
                _mark_paid_by(conn, user_id, rows, owners)
                _mark_payer_state(conn, user_id, rows, owners)
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
        try:
            agent, owner_id = _agent_for_schedules(agent_id, user_id)
        except AccessDenied as denied:
            return _err(denied.message, denied.status)
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
            # A schedule runs the agent's graph headless: a workflow agent's
            # must be a finished one.
            refusal = refuse_unfinished_graph(conn, agent)
            count = SchedulesRepository(conn).count_active_for_user(owner_id)
        if refusal is not None:
            return refusal
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
                        user_id=owner_id,
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
                    user_id=owner_id,
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


@schedules_ns.route("/agents/<string:agent_id>/schedules/stats")
class AgentScheduleStats(Resource):
    @api.doc(
        description="Run stats for an agent's schedules over a recent window.",
        params={"days": "Window in days (default 30, clamped to 1..365)"},
    )
    @_safe_route
    def get(self, agent_id: str):
        """Return run count, failures, tokens and latest failure for an agent.

        Args:
            agent_id: Agent id from the URL.

        Returns:
            A Flask response with ``days``, ``runs``, ``failed``, ``tokens``
            and ``latest_failure`` (or an error envelope).
        """
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        try:
            agent, owner_id = _agent_for_schedules(agent_id, user_id)
        except AccessDenied as denied:
            return _err(denied.message, denied.status)
        try:
            days = max(1, min(int(request.args.get("days", 30)), 365))
        except (TypeError, ValueError):
            days = 30
        try:
            with db_readonly() as conn:
                # A team agent's schedules are stored under the members who set
                # them; whoever manages them (Editors and up, checked above)
                # sees every one's runs, as in the schedule list.
                stats = ScheduleRunsRepository(conn).stats_for_agent(
                    str(agent["id"]), None if is_principal_id(agent.get("user_id")) else owner_id, days=days,
                )
        except Exception as exc:
            current_app.logger.error(
                "schedule stats failed: %s", exc, exc_info=True,
            )
            return _err("internal error", 500)
        latest = stats.get("latest_failure")
        return _ok(
            {
                "days": days,
                "runs": stats["runs"],
                "failed": stats["failed"],
                "tokens": stats["tokens"],
                "latest_failure": _format_run(latest, user_id) if latest else None,
            }
        )


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
            try:
                row, _acting = _schedule_for(conn, schedule_id, user_id, own_action="use")
            except AccessDenied as denied:
                return _err(denied.message, denied.status)
            agent = AgentsRepository(conn).get_by_id(str(row["agent_id"])) if row.get("agent_id") else None
            row = dict(row)
            owners = [(agent or {}).get("user_id")]
            _mark_owner_inactive(conn, [row], owners)
            _mark_paid_by(conn, user_id, [row], owners)
            _mark_payer_state(conn, user_id, [row], owners)
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
            try:
                existing, acting = _schedule_for(conn, schedule_id, user_id)
            except AccessDenied as denied:
                return _err(denied.message, denied.status)
            if "run_at" in data:
                rescheduled, error = _reschedule_once(
                    existing, data["run_at"], fields_in.get("timezone"),
                )
                if error is not None:
                    return error
                fields_in.update(rescheduled)
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
            # A reschedule only lands on a task that is still pending: the
            # dispatcher may have claimed it (or someone paused it) since it
            # was read above, and re-arming it then would lose the edit.
            updated = SchedulesRepository(conn).update(
                schedule_id, acting, fields_in,
                pending_once_status=(
                    existing.get("status") if "run_at" in data else None
                ),
            )
            if updated is None and "run_at" in data:
                return _err(
                    "the task started or changed while you edited it; reload and try again",
                    409,
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
            try:
                existing, acting = _schedule_for(conn, schedule_id, user_id)
            except AccessDenied as denied:
                return _err(denied.message, denied.status)
            if existing.get("status") in ("cancelled", "completed"):
                return _err("schedule is terminal", 409)
            if action == "resume":
                refusal = _refuse_unfinished_agent_graph(conn, existing.get("agent_id"))
                if refusal is not None:
                    return refusal
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
                schedule_id, acting, fields_in,
            )
            if action == "resume":
                SchedulesRepository(conn).reset_failure_count(schedule_id)
        if action == "resume" and updated:
            _publish_schedule_event(
                acting, "schedule.resumed", schedule_id, status="active",
            )
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
            try:
                _row, acting = _schedule_for(conn, schedule_id, user_id)
            except AccessDenied as denied:
                return _err(denied.message, denied.status)
            ok = SchedulesRepository(conn).delete(schedule_id, acting)
        if not ok:
            return _err("schedule not found", 404)
        _publish_schedule_event(
            acting, "schedule.cancelled", schedule_id, status="cancelled",
        )
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
            try:
                _row, acting = _schedule_for(conn, schedule_id, user_id)
            except AccessDenied as denied:
                return _err(denied.message, denied.status)
            schedule = SchedulesRepository(conn).get_for_update(
                schedule_id, acting,
            )
            if schedule is None:
                return _err("schedule not found", 404)
            if schedule.get("status") == "cancelled":
                return _err("schedule is cancelled", 409)
            refusal = _refuse_unfinished_agent_graph(conn, schedule.get("agent_id"))
            if refusal is not None:
                return refusal
            if ScheduleRunsRepository(conn).has_active_run(schedule_id):
                return _err("a run is already in flight", 409)
            scheduled_for = datetime.now(timezone.utc)
            agent_id_raw = schedule.get("agent_id")
            # The run belongs to (and executes as) the schedule's owner.
            run = ScheduleRunsRepository(conn).record_pending(
                schedule_id,
                acting,
                str(agent_id_raw) if agent_id_raw else None,
                scheduled_for,
                trigger_source="manual",
            )
        if run is None:
            return _err("could not claim run (concurrent dispatch)", 409)
        # Import inside the handler to avoid a circular tasks <-> routes import.
        try:
            from docsgpt.api.user.tasks import execute_scheduled_run
            execute_scheduled_run.apply_async(args=[str(run["id"])], queue="docsgpt")
        except Exception as exc:
            current_app.logger.error(
                "run-now enqueue failed: %s", exc, exc_info=True,
            )
            return _err("enqueue failed", 500)
        return _ok({"run": _format_run(run, user_id)}, status=202)


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
            try:
                _schedule, acting = _schedule_for(conn, schedule_id, user_id, own_action="use")
            except AccessDenied as denied:
                return _err(denied.message, denied.status)
            rows = ScheduleRunsRepository(conn).list_runs(
                schedule_id, _runs_user(conn, _schedule, acting, user_id), limit=limit, offset=offset,
            )
        return _ok(
            {
                "runs": [_format_run(r, user_id) for r in rows],
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
            try:
                schedule, acting = _schedule_for(conn, schedule_id, user_id, own_action="use")
            except AccessDenied as denied:
                return _err(denied.message, denied.status)
            run = ScheduleRunsRepository(conn).get(run_id, _runs_user(conn, schedule, acting, user_id))
            if run is None or str(run.get("schedule_id")) != str(
                schedule["id"]
            ):
                return _err("run not found", 404)
        return _ok({"run": _format_run(run, user_id)})


@schedules_ns.route("/schedules/<string:schedule_id>/take_over")
class ScheduleTakeOver(Resource):
    @api.doc(
        description=(
            "Make the caller the payer of a schedule on a team agent: it runs under them from now on (its failure "
            "count reset, the chat it was set from no longer linked). Editors and up of the team; a personal "
            "agent's schedule can't be taken over. Returns the schedule in the list's shape and whether anything "
            "changed. Not available to access tokens."
        ),
    )
    @_safe_route
    def post(self, schedule_id: str):
        """Take over a schedule on a team agent.

        Args:
            schedule_id: Schedule id from the URL.

        Returns:
            200 ``{success, schedule, changed}``; ``changed`` is false when the
            caller already paid for it. Refusals carry ``{success: false,
            error, message}``: 401; 404 ``schedule_not_found``; 403
            ``workspace_role_required``; 409 ``take_over_team_only`` or
            ``schedule_finished`` (completed or cancelled); 429 ``max_schedules``.
        """
        user_id = _user_id()
        if not user_id:
            return _err("unauthorized", 401)
        not_found = _refuse(404, "schedule_not_found", "schedule not found")
        if not looks_like_uuid(schedule_id):
            return not_found
        with db_session() as conn:
            schedules = SchedulesRepository(conn)
            row = schedules.get_internal(schedule_id)
            if row is None or row.get("trigger_type") == "monitor":
                return not_found
            agent_id = row.get("agent_id")
            agent = AgentsRepository(conn).get_by_id(str(agent_id)) if agent_id else None
            team_id = team_of_principal((agent or {}).get("user_id"))
            if not team_id:
                # A personal agent's (or an agentless) schedule is its setter's own.
                try:
                    _schedule_for(conn, schedule_id, user_id)
                except AccessDenied as denied:
                    if denied.status == 404:
                        return not_found
                return _refuse(409, "take_over_team_only", "only a schedule on a team agent can be taken over")
            try:
                require(conn, "agent", str(agent_id), user_id, "manage_schedules")
            except AccessDenied as denied:
                if denied.status == 404:
                    return not_found
                return _refuse(403, "workspace_role_required", "your role in this team can't manage its schedules")
            # Locked until commit: two people taking over at once each see who
            # really paid before them.
            locked = schedules.lock_internal(schedule_id)
            if locked is None:
                return not_found
            # A completed or cancelled schedule never runs again: nobody pays for it.
            if locked.get("status") not in _LIVE_STATUSES:
                return _refuse(409, "schedule_finished", "a completed or cancelled schedule can't be taken over")
            previous = locked.get("user_id")
            changed = previous != user_id
            if changed:
                if (
                    settings.SCHEDULE_MAX_PER_USER > 0
                    and schedules.count_active_for_user(user_id) >= settings.SCHEDULE_MAX_PER_USER
                ):
                    return _refuse(429, "max_schedules", "max schedules per user reached")
                schedules.take_over(schedule_id, user_id)
                # A run not yet started bills the new payer; one in flight keeps its own.
                ScheduleRunsRepository(conn).reassign_pending(schedule_id, user_id)
                record_event(
                    conn,
                    "team.schedule_taken_over",
                    actor=user_id,
                    team_id=team_id,
                    schedule_id=str(schedule_id),
                    agent_id=str(agent_id),
                    **{"from": previous, "to": user_id},
                )
            fresh = schedules.get_with_context(schedule_id, user_id)
            payload = _list_payload(conn, user_id, [{**fresh, "team": fresh.get("user_id") != user_id}])[0]
        return _ok({"success": True, "schedule": payload, "changed": changed})
