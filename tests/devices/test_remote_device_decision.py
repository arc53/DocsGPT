"""Tests for ``RemoteDeviceTool._decide_approval`` (two-mode model)."""

from __future__ import annotations

import pytest

from application.agents.tools.remote_device import RemoteDeviceTool


def _tool(monkeypatch, *, sticky=False):
    tool = RemoteDeviceTool.__new__(RemoteDeviceTool)
    tool.device_id = "dev_abc"
    tool.user_id = "alice"
    monkeypatch.setattr(tool, "_matches_sticky", lambda command: sticky)
    return tool


@pytest.mark.unit
class TestDecideApproval:
    def test_full_passthrough(self, monkeypatch):
        tool = _tool(monkeypatch)
        reason, mode = tool._decide_approval({"approval_mode": "full"}, "rm /tmp/x")
        assert (reason, mode) == ("full_access_passthrough", "full")

    def test_full_denylist_forces_prompt(self, monkeypatch):
        tool = _tool(monkeypatch)
        reason, mode = tool._decide_approval({"approval_mode": "full"}, "rm -rf /")
        assert (reason, mode) == ("denylist_forced_prompt", "ask")

    def test_ask_requires_approval(self, monkeypatch):
        tool = _tool(monkeypatch, sticky=False)
        reason, mode = tool._decide_approval({"approval_mode": "ask"}, "ls -la")
        assert (reason, mode) == ("user_approval_required", "ask")

    def test_ask_sticky_auto_approves(self, monkeypatch):
        tool = _tool(monkeypatch, sticky=True)
        reason, mode = tool._decide_approval({"approval_mode": "ask"}, "ls -la")
        assert (reason, mode) == ("sticky_auto_approve", "full")

    def test_ask_sticky_denylist_still_forces_prompt(self, monkeypatch):
        # Regression: a "don't ask again" sticky pattern must not let a
        # denylisted command (e.g. sticky ``rm *`` -> ``rm -rf /``, or sticky
        # ``git push *`` -> ``git push --force --mirror``) auto-run. The
        # denylist forces a prompt on every path, including the sticky one.
        from application.devices.denylist import check_denylist

        assert check_denylist("rm -rf /") is not None
        assert check_denylist("git push --force --mirror") is not None

        tool = _tool(monkeypatch, sticky=True)
        for command in ("rm -rf /", "git push --force --mirror"):
            reason, mode = tool._decide_approval({"approval_mode": "ask"}, command)
            assert (reason, mode) == ("denylist_forced_prompt", "ask")

    def test_missing_mode_defaults_to_ask(self, monkeypatch):
        tool = _tool(monkeypatch, sticky=False)
        reason, mode = tool._decide_approval({}, "ls -la")
        assert (reason, mode) == ("user_approval_required", "ask")
