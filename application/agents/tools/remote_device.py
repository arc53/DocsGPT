"""Remote Device tool.

Run shell commands on a paired remote device via the DeviceBroker.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from application.agents.tools.base import Tool
from application.devices.broker import get_broker
from application.devices.denylist import check_denylist
from application.devices.normalizer import normalize_command
from application.storage.db.repositories.device_audit_log import (
    DeviceAuditLogRepository,
)
from application.storage.db.repositories.device_auto_approve_patterns import (
    DeviceAutoApprovePatternsRepository,
)
from application.storage.db.repositories.devices import DevicesRepository
from application.storage.db.session import db_readonly, db_session


logger = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_MS = 30_000
_MAX_TIMEOUT_MS = 600_000


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
                            "description": "Timeout in milliseconds (max 600000).",
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
        if action_name != "run_command":
            return True
        if not self.device_id or not self.user_id:
            return True
        if self._device is None:
            self._device = self._load_device()
        device = self._device
        if device is None or device.get("status") != "active":
            # Don't bypass the prompt for an unknown / inactive device;
            # execute_action will surface the error.
            return True
        command = ((params or {}).get("command") or "").strip()
        if not command:
            return True
        _reason, effective_mode = self._decide_approval(device, command)
        return effective_mode != "full"

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
        timeout_ms = kwargs.get("timeout_ms")
        try:
            timeout_ms = int(timeout_ms) if timeout_ms else _DEFAULT_TIMEOUT_MS
        except (TypeError, ValueError):
            timeout_ms = _DEFAULT_TIMEOUT_MS
        timeout_ms = min(max(timeout_ms, 1), _MAX_TIMEOUT_MS)

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
        inv = broker.dispatch_invocation(self.device_id, self.user_id, envelope)

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

        return self._collect_result(broker, inv, device, timeout_ms)

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
        """Drain output from the broker until the control chunk arrives."""
        deadline = time.time() + (timeout_ms / 1000.0) + 5.0
        stdout = []
        stderr = []
        try:
            for chunk in broker.drain_output(inv.invocation_id, timeout=1.0):
                if time.time() > deadline:
                    break
                stream = chunk.get("stream")
                if stream == "stdout":
                    stdout.append(chunk.get("chunk", ""))
                elif stream == "stderr":
                    stderr.append(chunk.get("chunk", ""))
                elif stream == "control":
                    # control chunks include exit_code; drain loop will stop next iter
                    pass
        finally:
            broker.cleanup_invocation(inv.invocation_id)

        return {
            "exit_code": inv.exit_code,
            "stdout": "".join(stdout) if stdout else "".join(inv.stdout_parts),
            "stderr": "".join(stderr) if stderr else "".join(inv.stderr_parts),
            "duration_ms": inv.duration_ms,
            "device_name": device.get("name"),
            "error": inv.error,
        }
