"""Scheduler tool: one-time agent tasks in agent-bound or agentless chats."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from application.agents.scheduler_utils import (
    ScheduleValidationError,
    clamp_once_horizon,
    parse_delay,
    parse_run_at,
)
from application.core.settings import settings
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.schedules import SchedulesRepository
from application.storage.db.session import db_readonly, db_session

from .base import Tool


logger = logging.getLogger(__name__)


class SchedulerTool(Tool):
    """Scheduling"""

    # internal=True keeps scheduler out of /api/available_tools and the
    # agentless Add-Tool modal; tool_manager.load_tool still lazy-loads it
    # per-user at execute time (same as memory/notes/todo_list).
    internal: bool = True

    def __init__(
        self,
        tool_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        cfg = tool_config or {}
        self.user_id: Optional[str] = user_id
        self.agent_id: Optional[str] = cfg.get("agent_id")
        self.conversation_id: Optional[str] = cfg.get("conversation_id")

    def execute_action(self, action_name: str, **kwargs: Any) -> str:
        """Dispatch on the LLM-supplied action name."""
        if not self.user_id:
            return "Error: SchedulerTool requires a valid user_id."
        # Agent-bound: agent_id must look like a UUID. Agentless: agent_id is
        # absent; an originating conversation is then mandatory (the schedule's
        # conversation home, used for history + output append).
        if self.agent_id and not looks_like_uuid(str(self.agent_id)):
            return "Error: SchedulerTool received an invalid agent_id."
        if not self.agent_id and not self.conversation_id:
            return (
                "Error: SchedulerTool requires an agent_id or a "
                "conversation_id (no conversation home)."
            )
        if action_name == "schedule_task":
            return self._schedule_task(
                instruction=kwargs.get("instruction", ""),
                delay=kwargs.get("delay"),
                run_at=kwargs.get("run_at"),
                tz=kwargs.get("timezone"),
            )
        if action_name == "list_scheduled_tasks":
            return self._list_scheduled_tasks()
        if action_name == "cancel_scheduled_task":
            return self._cancel_scheduled_task(kwargs.get("task_id", ""))
        return f"Unknown action: {action_name}"

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        """Action schemas for the LLM tool catalogue."""
        return [
            {
                "name": "schedule_task",
                "description": (
                    "Schedule a one-time task. Provide either a `delay` "
                    "(e.g. '30m', '2h', '1d') from now, or a `run_at` ISO-8601 "
                    "absolute time. Optionally pass an IANA `timezone` to resolve "
                    "naive run_at values. The instruction is the task that will "
                    "execute at fire time (including delivery, e.g. 'send to my "
                    "Telegram'). For recurring schedules in an agent chat, point "
                    "the user to the agent's Schedules tab."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "instruction": {
                            "type": "string",
                            "description": "What the agent should do at fire time.",
                        },
                        "delay": {
                            "type": "string",
                            "description": "Duration like '30m', '2h', '1d'.",
                        },
                        "run_at": {
                            "type": "string",
                            "description": "Absolute ISO 8601 timestamp.",
                        },
                        "timezone": {
                            "type": "string",
                            "description": (
                                "IANA timezone (e.g. Europe/Warsaw) for naive run_at."
                            ),
                        },
                    },
                    "required": ["instruction"],
                },
            },
            {
                "name": "list_scheduled_tasks",
                "description": (
                    "List pending one-time tasks for the current chat. "
                    "Agent-bound chats scope to user+agent; agentless chats "
                    "scope to user+originating conversation."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "cancel_scheduled_task",
                "description": "Cancel a pending one-time task by its task_id.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "The schedule id returned by schedule_task.",
                        },
                    },
                    "required": ["task_id"],
                },
            },
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        return {}

    def _schedule_task(
        self,
        instruction: str,
        delay: Optional[str],
        run_at: Optional[str],
        tz: Optional[str],
    ) -> str:
        if not instruction or not isinstance(instruction, str):
            return "Error: instruction is required."
        if not delay and not run_at:
            return "Error: provide either `delay` or `run_at`."
        if delay and run_at:
            return "Error: provide only one of `delay` or `run_at`."

        try:
            if delay:
                fire = datetime.now(timezone.utc) + parse_delay(delay)
            else:
                fire = parse_run_at(run_at, tz)
            clamp_once_horizon(fire, settings.SCHEDULE_ONCE_MAX_HORIZON)
        except ScheduleValidationError as exc:
            return f"Error: {exc}"

        with db_readonly() as conn:
            count = SchedulesRepository(conn).count_active_for_user(self.user_id)
        if (
            settings.SCHEDULE_MAX_PER_USER > 0
            and count >= settings.SCHEDULE_MAX_PER_USER
        ):
            return (
                "Error: you have reached the maximum number of active schedules."
            )

        # Chat-created tasks default to the user's non-approval tools (for the
        # agent's toolset when agent-bound, or the user's defaults+user_tools
        # when agentless).
        allowlist = _safe_default_allowlist(self.agent_id, self.user_id)

        auto_name = _name_from_instruction(instruction)
        try:
            with db_session() as conn:
                created = SchedulesRepository(conn).create(
                    user_id=self.user_id,
                    agent_id=self.agent_id,
                    trigger_type="once",
                    instruction=instruction.strip(),
                    name=auto_name,
                    run_at=fire,
                    next_run_at=fire,
                    timezone=tz or "UTC",
                    tool_allowlist=allowlist,
                    origin_conversation_id=self.conversation_id,
                    created_via="chat",
                )
        except Exception as exc:
            logger.exception("schedule_task create failed: %s", exc)
            return "Error: failed to create scheduled task."
        return json.dumps(
            {
                "task_id": str(created["id"]),
                "resolved_run_at": _iso_utc(fire),
                "timezone": tz or "UTC",
                "instruction": instruction.strip(),
                "name": auto_name,
            }
        )

    def _list_scheduled_tasks(self) -> str:
        """Pending one-time tasks for this user, oldest fire first.

        Agent-bound chats scope to user+agent. Agentless chats scope to user+
        origin_conversation_id so a user only sees tasks created from this chat.
        """
        with db_readonly() as conn:
            repo = SchedulesRepository(conn)
            if self.agent_id:
                rows = repo.list_for_agent(
                    self.agent_id,
                    self.user_id,
                    statuses=["active"],
                    trigger_type="once",
                )
            else:
                rows = repo.list_for_conversation(
                    self.user_id,
                    self.conversation_id,
                    statuses=["active"],
                    trigger_type="once",
                )
        # Values arrive as ISO strings (coerce_pg_native); string sentinel keeps types uniform.
        rows.sort(key=lambda r: r.get("next_run_at") or "9999-12-31T23:59:59Z")
        items = [
            {
                "task_id": str(r["id"]),
                "instruction": r.get("instruction"),
                "name": r.get("name"),
                "resolved_run_at": _iso_utc(r.get("next_run_at")),
                "timezone": r.get("timezone"),
                "status": r.get("status"),
            }
            for r in rows
        ]
        return json.dumps({"tasks": items})

    def _cancel_scheduled_task(self, task_id: str) -> str:
        if not task_id or not looks_like_uuid(str(task_id)):
            return "Error: task_id must be a valid id."
        with db_session() as conn:
            repo = SchedulesRepository(conn)
            # Agentless: scope cancel to user + originating conversation so a
            # user can only cancel tasks they created in the current chat.
            if not self.agent_id:
                row = repo.get(task_id, self.user_id)
                if row is None or row.get("agent_id") is not None or (
                    str(row.get("origin_conversation_id") or "")
                    != str(self.conversation_id or "")
                ):
                    return (
                        "Error: scheduled task not found or already terminal."
                    )
            ok = repo.cancel(task_id, self.user_id)
        if not ok:
            return "Error: scheduled task not found or already terminal."
        return json.dumps({"task_id": str(task_id), "status": "cancelled"})


def _name_from_instruction(instruction: str, *, max_len: int = 80) -> str:
    """Compact display name derived from the instruction's first line."""
    first_line = instruction.strip().split("\n", 1)[0]
    if len(first_line) <= max_len:
        return first_line
    return first_line[: max_len - 1] + "…"


def _iso_utc(value: Any) -> Optional[str]:
    """Render a datetime (or ISO string) as RFC3339 UTC; ``None`` passes through."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_default_allowlist(
    agent_id: Optional[str], user_id: str,
) -> List[str]:
    """Return ids of available tools whose actions are all non-approval.

    Agent-bound: the agent's ``agents.tools`` entries.
    Agentless: the user's active ``user_tools`` rows plus synthesized default
    chat tools (resolved against ``settings.DEFAULT_CHAT_TOOLS`` and the
    user's ``tool_preferences.disabled_default_tools`` opt-outs).
    """
    from application.agents.default_tools import (
        resolve_tool_by_id,
        synthesized_default_tools,
    )
    from application.storage.db.repositories.agents import AgentsRepository
    from application.storage.db.repositories.user_tools import UserToolsRepository
    from application.storage.db.repositories.users import UsersRepository

    def _is_safe(row: Dict[str, Any]) -> bool:
        actions = row.get("actions") or []
        return not any(a.get("require_approval") for a in actions)

    safe_ids: List[str] = []
    try:
        with db_readonly() as conn:
            tools_repo = UserToolsRepository(conn)
            if agent_id:
                agent = AgentsRepository(conn).get(agent_id, user_id)
                tool_ids = (agent or {}).get("tools") or []
                for raw_id in tool_ids:
                    tool_id = str(raw_id)
                    row = resolve_tool_by_id(
                        tool_id, user_id, user_tools_repo=tools_repo,
                    )
                    if not row or not _is_safe(row):
                        continue
                    safe_ids.append(tool_id)
            else:
                # Agentless: explicit user_tools (active=true) + synthesized
                # defaults respecting the user's opt-out preferences.
                user_doc = UsersRepository(conn).get(user_id)
                for row in tools_repo.list_active_for_user(user_id):
                    if not _is_safe(row):
                        continue
                    safe_ids.append(str(row["id"]))
                for default_row in synthesized_default_tools(user_doc):
                    if not _is_safe(default_row):
                        continue
                    safe_ids.append(str(default_row["id"]))
    except Exception:  # pragma: no cover — best-effort fallback
        logger.exception("scheduler: default allowlist build failed")
        return []
    return safe_ids
