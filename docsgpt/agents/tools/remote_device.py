"""Remote Device tool.

Run shell commands on a paired remote device via the DeviceBroker.

In a chat turn the call runs on a background pool thread
(:mod:`docsgpt.background.handoff`): the tool dispatches the command and
follows it, and once the turn hands the call off (it outlived the yield
window, or the model passed ``background=true``) the rest of the run moves
to the ``device`` runner's poll chain (:mod:`docsgpt.background.device_runner`)
instead of holding a thread. Outside a turn (a scheduled run, a monitor
check) the call blocks until the device reports, as before.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from docsgpt.agents.tools.base import Tool
from docsgpt.devices.broker import get_broker
from docsgpt.devices.denylist import check_denylist
from docsgpt.devices.normalizer import normalize_command
from docsgpt.storage.db.repositories.device_audit_log import (
    DeviceAuditLogRepository,
)
from docsgpt.storage.db.repositories.device_auto_approve_patterns import (
    DeviceAutoApprovePatternsRepository,
)
from docsgpt.storage.db.repositories.devices import DevicesRepository
from docsgpt.storage.db.session import db_readonly, db_session


logger = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_MS = 30_000
_MAX_TIMEOUT_MS = 600_000

#: Seconds past a background command's own lifetime its broker keys are kept, for a late report.
KEY_MARGIN_SECONDS = 900


def device_job_max_ms() -> int:
    """Longest a background command may run on a device (``DEVICE_JOB_MAX_SECONDS``), in milliseconds."""
    from docsgpt.core.settings import settings

    return int(settings.DEVICE_JOB_MAX_SECONDS) * 1000


def clamp_timeout_ms(value: Any, *, background: bool = False) -> int:
    """The command's timeout: the model's value within the cap, or the default.

    Args:
        value: What the model passed (may be empty, a string, or junk).
        background: An explicit background command: the cap is the device
            job maximum and the default is the cap itself.

    Returns:
        Milliseconds, at least 1.
    """
    cap = device_job_max_ms() if background else _MAX_TIMEOUT_MS
    default = cap if background else _DEFAULT_TIMEOUT_MS
    try:
        timeout_ms = int(value) if value else default
    except (TypeError, ValueError):
        timeout_ms = default
    return min(max(timeout_ms, 1), cap)


class RemoteDeviceTool(Tool):
    """Remote Device
    Run shell commands on a paired remote machine via docsgpt-cli host.
    """

    def __init__(self, config: Optional[dict] = None, user_id: Optional[str] = None):
        self.config = config or {}
        self.user_id = user_id
        self.device_id = self.config.get("device_id") or ""
        self._device: Optional[dict] = None
        if self.device_id and self.user_id:
            self._device = self._load_device()

    def _load_device(self) -> Optional[dict]:
        try:
            with db_readonly() as conn:
                return DevicesRepository(conn).get(self.device_id, user_id=self.user_id)
        except Exception:
            logger.exception("failed to load device %s", self.device_id)
            return None

    # ------------------------------------------------------------------
    # Tool ABC
    # ------------------------------------------------------------------
    def get_actions_metadata(self):
        device = self._device or {}
        device_name = device.get("name") or "remote device"
        description = device.get("description") or ""
        approval_mode = device.get("approval_mode") or "ask"
        return [
            {
                "name": "run_command",
                "description": (
                    f"Execute a shell command on the remote device "
                    f"'{device_name}'. {description}".strip()
                ),
                "active": True,
                "require_approval": approval_mode != "full",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to run.",
                            "filled_by_llm": True,
                            "value": "",
                        },
                        "working_directory": {
                            "type": "string",
                            "description": "Working directory on the remote.",
                            "filled_by_llm": True,
                            "value": "",
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "description": (
                                "Timeout in milliseconds (max 600000; with background=true up to the device "
                                "job maximum, which is also the default then)."
                            ),
                            "filled_by_llm": True,
                            "value": "",
                        },
                    },
                    "required": ["command"],
                },
            }
        ]

    def get_config_requirements(self):
        return {
            "device_id": {
                "type": "string",
                "label": "Device",
                "description": "Paired remote device id.",
                "required": True,
                "source": "devices",
            }
        }

    def preview_requires_approval(self, action_name: str, params: dict) -> bool:
        """Live approval decision for a specific invocation.

        The tool_executor gate calls this for ``remote_device`` so the
        decision considers the device's current ``approval_mode``, sticky
        patterns, and the denylist — rather than trusting the static
        ``user_tools.actions[].require_approval`` snapshot stored at pair
        time. Returns ``True`` when a prompt is required.
        """
        requires_approval, _denylist_forced = self.preview_decision(
            action_name, params,
        )
        return requires_approval

    def preview_decision(
        self, action_name: str, params: dict,
    ) -> tuple[bool, bool]:
        """Live approval decision plus whether it's a denylist-forced prompt.

        Returns ``(requires_approval, denylist_forced)``. ``denylist_forced``
        is True only when the prompt is mandated by the hard denylist, which
        a headless allowlist must never bypass. Unknown / inactive devices
        and missing commands require approval but are NOT denylist-forced.
        """
        if action_name != "run_command":
            return True, False
        if not self.device_id or not self.user_id:
            return True, False
        if self._device is None:
            self._device = self._load_device()
        device = self._device
        if device is None or device.get("status") != "active":
            # Don't bypass the prompt for an unknown / inactive device;
            # execute_action will surface the error.
            return True, False
        command = ((params or {}).get("command") or "").strip()
        if not command:
            return True, False
        reason, effective_mode = self._decide_approval(device, command)
        denylist_forced = reason == "denylist_forced_prompt"
        return effective_mode != "full", denylist_forced

    def execute_action(self, action_name: str, **kwargs):
        if action_name != "run_command":
            return {"error": f"unknown action: {action_name}"}
        if not self.device_id or not self.user_id:
            return {"error": "device_id and user_id required"}
        if self._device is None:
            self._device = self._load_device()
        device = self._device
        if device is None:
            return {"error": "device not found"}
        if device.get("status") != "active":
            return {"error": f"device status: {device.get('status')}"}

        command = (kwargs.get("command") or "").strip()
        if not command:
            return {"error": "command is required"}
        working_directory = kwargs.get("working_directory") or ""
        call = self._background_call()
        explicit = bool(call is not None and call.explicit)
        timeout_ms = clamp_timeout_ms(kwargs.get("timeout_ms"), background=explicit)

        decision_reason, effective_mode = self._decide_approval(device, command)
        denied = self._denylist_label(command)

        envelope = {
            "invocation_id": "inv_" + uuid.uuid4().hex,
            "action": "run_command",
            "params": {
                "command": command,
                "working_directory": working_directory,
                "timeout_ms": timeout_ms,
            },
            "approval_mode": effective_mode,
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }
        broker = get_broker()
        # A command that may become a background job keeps its broker keys for the job's lifetime.
        ttl = (device_job_max_ms() // 1000 + KEY_MARGIN_SECONDS) if explicit else None
        inv = broker.dispatch_invocation(self.device_id, self.user_id, envelope, ttl_seconds=ttl)
        dispatched_at = time.time()

        try:
            with db_session() as conn:
                DeviceAuditLogRepository(conn).record_dispatch(
                    device_id=self.device_id,
                    user_id=self.user_id,
                    invocation_id=inv.invocation_id,
                    command=command,
                    working_dir=working_directory,
                    approval_mode=effective_mode,
                    decision="dispatched",
                    decision_reason=decision_reason or ("denylist:" + denied if denied else None),
                    issued_at=datetime.now(timezone.utc),
                )
        except Exception:
            logger.exception("audit record_dispatch failed for %s", inv.invocation_id)

        if call is not None:
            return self._follow(broker, inv, device, timeout_ms, call, dispatched_at)
        return self._collect_result(broker, inv, device, timeout_ms)

    # ------------------------------------------------------------------
    # Background jobs
    # ------------------------------------------------------------------
    @staticmethod
    def _background_call() -> Any:
        """The background call this command belongs to, when the turn may hand it off."""
        from docsgpt.background.handoff import current_call

        return current_call()

    def supports_detached(self) -> bool:
        """A command runs on the device whatever this process does, so a poller can always follow it."""
        return True

    def _follow(
        self, broker, inv, device: dict, timeout_ms: int, call: Any, dispatched_at: float
    ) -> Any:
        """Wait for the command while the turn waits; hand it to the device runner once the turn hands it off.

        Args:
            broker: The device broker.
            inv: The dispatched invocation.
            device: The device row.
            timeout_ms: The command's own timeout.
            call: The background call handle.
            dispatched_at: When the command was queued (Unix time).

        Returns:
            The command's result, or the detached marker when a background
            job took the command over.
        """
        if inv.completed and inv.error:
            return self._result_from(broker, inv, device)
        from docsgpt.background.handoff import DETACHED

        deadline = dispatched_at + timeout_ms / 1000.0 + 5.0
        interval = 0.05
        while True:
            if call.handoff_requested():
                external = {
                    "invocation_id": inv.invocation_id,
                    "device_id": self.device_id,
                    "device_name": device.get("name"),
                    "timeout_ms": int(timeout_ms),
                    "dispatched_at": dispatched_at,
                }
                if call.detach(external, runner="device"):
                    return DETACHED
            current = broker.get_invocation(inv.invocation_id)
            if current is None or current.completed or time.time() > deadline:
                return self._result_from(broker, inv, device)
            call.wait(interval)
            interval = min(interval * 1.3, 1.0)

    @staticmethod
    def _result_from(broker, inv, device: dict) -> Dict[str, Any]:
        """The command's result from its whole output stream, then its broker state is dropped."""
        try:
            return command_result(broker, inv.invocation_id, device.get("name"), dispatch_error=inv.error)
        finally:
            broker.cleanup_invocation(inv.invocation_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _decide_approval(self, device: dict, command: str) -> tuple[Optional[str], str]:
        """Resolve the effective approval mode + a short audit reason.

        Effective mode is ``full`` (auto-run, no prompt) or ``ask`` (prompt).
        """
        mode = device.get("approval_mode") or "ask"
        # Denylist forces a prompt on every path — full access and the
        # ask-mode sticky auto-approve alike.
        if check_denylist(command):
            return ("denylist_forced_prompt", "ask")
        if mode == "full":
            return ("full_access_passthrough", "full")
        # mode == "ask"
        if self._matches_sticky(command):
            return ("sticky_auto_approve", "full")
        return ("user_approval_required", "ask")

    def _denylist_label(self, command: str) -> Optional[str]:
        return check_denylist(command)

    def _matches_sticky(self, command: str) -> bool:
        pattern = normalize_command(command)
        if not pattern:
            return False
        try:
            with db_readonly() as conn:
                return DeviceAutoApprovePatternsRepository(conn).has_pattern(
                    self.device_id, self.user_id, pattern,
                )
        except Exception:
            logger.exception("sticky lookup failed")
            return False

    def _collect_result(self, broker, inv, device: dict, timeout_ms: int) -> Dict[str, Any]:
        """Drain output from the broker until the control chunk arrives.

        Result fields come from the drained chunks, not from ``inv``: the
        invocation runs and reports back in a different process (the web
        tier), so the dispatching process never sees ``inv`` mutated.
        """
        # Dispatch already failed (e.g. broker/Redis unavailable): report it.
        if inv.completed and inv.error:
            return {
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "duration_ms": None,
                "device_name": device.get("name"),
                "error": inv.error,
            }

        deadline = time.time() + (timeout_ms / 1000.0) + 5.0
        stdout = []
        stderr = []
        exit_code = None
        duration_ms = None
        error = None
        saw_control = False
        try:
            for chunk in broker.drain_output(
                inv.invocation_id, timeout=1.0, deadline=deadline
            ):
                stream = chunk.get("stream")
                if stream == "stdout":
                    stdout.append(chunk.get("chunk", ""))
                elif stream == "stderr":
                    stderr.append(chunk.get("chunk", ""))
                elif stream == "control":
                    saw_control = True
                    exit_code = chunk.get("exit_code")
                    duration_ms = chunk.get("duration_ms")
                    error = chunk.get("error") or error
                # Stop once past the deadline — but only AFTER capturing a chunk
                # the drain already yielded, so a near-deadline control chunk
                # isn't dropped and misreported as a timeout.
                if time.time() > deadline:
                    break
            # No control chunk observed: consult the authoritative completion
            # state (before cleanup deletes it) so a late or dropped control
            # chunk isn't misreported as "device did not respond".
            if not saw_control:
                final = broker.get_invocation(inv.invocation_id)
                if final is not None and final.completed:
                    saw_control = True
                    exit_code = final.exit_code
                    duration_ms = final.duration_ms
                    error = final.error or error
        finally:
            broker.cleanup_invocation(inv.invocation_id)

        # Deadline hit with no completion at all: the device never connected or
        # never finished. Surface a clear timeout instead of empty success.
        if not saw_control and exit_code is None and not error:
            error = "device did not respond (timed out)"

        return {
            "exit_code": exit_code,
            "stdout": "".join(stdout),
            "stderr": "".join(stderr),
            "duration_ms": duration_ms,
            "device_name": device.get("name"),
            "error": error,
        }


def command_result(
    broker, invocation_id: str, device_name: Optional[str], *, dispatch_error: Optional[str] = None
) -> Dict[str, Any]:
    """A command's result as the tool returns it, read from its whole output stream.

    Args:
        broker: The device broker.
        invocation_id: The invocation.
        device_name: Shown in the result.
        dispatch_error: Why the dispatch itself failed, if it did.

    Returns:
        ``{exit_code, stdout, stderr, duration_ms, device_name, error}``.
    """
    if dispatch_error:
        return {
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "duration_ms": None,
            "device_name": device_name,
            "error": dispatch_error,
        }
    stdout: list = []
    stderr: list = []
    exit_code = duration_ms = error = None
    saw_control = False
    cursor = "0-0"
    while True:
        chunks, next_cursor = broker.read_output(invocation_id, cursor)
        for chunk in chunks:
            stream = chunk.get("stream")
            if stream == "stdout":
                stdout.append(chunk.get("chunk", ""))
            elif stream == "stderr":
                stderr.append(chunk.get("chunk", ""))
            elif stream == "control":
                saw_control = True
                exit_code = chunk.get("exit_code")
                duration_ms = chunk.get("duration_ms")
                error = chunk.get("error") or error
        if next_cursor == cursor:
            break
        cursor = next_cursor
    if not saw_control:
        final = broker.get_invocation(invocation_id)
        if final is not None and final.completed:
            saw_control = True
            exit_code = final.exit_code
            duration_ms = final.duration_ms
            error = final.error or error
    if not saw_control and exit_code is None and not error:
        error = "device did not respond (timed out)"
    return {
        "exit_code": exit_code,
        "stdout": "".join(str(part) for part in stdout),
        "stderr": "".join(str(part) for part in stderr),
        "duration_ms": duration_ms,
        "device_name": device_name,
        "error": error,
    }
