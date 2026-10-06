"""Tests for tool sources: resolving the call, the creation-time approval gate, and replaying it on a check."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from docsgpt.monitors import sources
from docsgpt.monitors.fetch import SourceError, SourceRevoked, SourceUnreachable
from docsgpt.monitors.spec import SpecError, canonical_args_hash

NOW = datetime(2026, 10, 5, 12, 7, tzinfo=timezone.utc)

TOOLS = {
    "t-web": {"id": "t-web", "name": "read_webpage", "actions": [{"name": "read_webpage", "active": True}]},
    "t-dev": {
        "id": "t-dev",
        "name": "remote_device",
        "config": {"device_id": "d1"},
        "actions": [{"name": "run_command", "active": True}],
    },
    "t-gh": {
        "id": "t-gh",
        "name": "mcp_tool",
        "display_name": "GitHub",
        "actions": [{"name": "list_issues", "active": True}, {"name": "create_issue", "active": True}],
    },
}


class FakeExecutor:
    """The parts of ``ToolExecutor`` the source code touches."""

    def __init__(self, tools=TOOLS, *, pause=None, forced=False, result=None, status="completed", raises=None):
        self._name_to_tool = {}
        self._tool_to_name = {}
        for key, data in tools.items():
            for action in data["actions"]:
                self._name_to_tool[action["name"]] = (key, action["name"])
                self._tool_to_name[(key, action["name"])] = action["name"]
        self.pause = pause
        self.forced = forced
        self.result = result
        self.status = status
        self.raises = raises
        self.tool_calls = []
        self.calls = []
        self.conversation_id = None

    def check_pause(self, tools, call, llm_class):
        self.calls.append(("check_pause", call.name, call.arguments))
        return self.pause

    def _remote_device_requires_approval(self, tool_data, action, args):
        return True, self.forced

    def execute(self, tools, call, llm_class):
        self.calls.append(("execute", call.name, call.arguments))
        if self.raises is not None:
            raise self.raises
        yield {"type": "tool_call"}
        self.tool_calls.append({"status": self.status})
        return self.result, call.id


class TestResolve:
    def test_function_name(self):
        resolved = sources.resolve_tool(FakeExecutor(), TOOLS, "list_issues", None)
        assert (resolved.key, resolved.action, resolved.llm_name) == ("t-gh", "list_issues", "list_issues")

    def test_dotted_tool_and_action(self):
        resolved = sources.resolve_tool(FakeExecutor(), TOOLS, "remote_device.run_command", None)
        assert resolved.tool_id == "t-dev" and resolved.action == "run_command"

    def test_tool_label_plus_action(self):
        resolved = sources.resolve_tool(FakeExecutor(), TOOLS, "GitHub", "list_issues")
        assert resolved.key == "t-gh"

    def test_ambiguous_label_is_refused(self):
        with pytest.raises(SpecError, match="ambiguous"):
            sources.resolve_tool(FakeExecutor(), TOOLS, "github", None)

    def test_unknown_tool_lists_what_exists(self):
        with pytest.raises(SpecError, match="available: "):
            sources.resolve_tool(FakeExecutor(), TOOLS, "send_email", None)


class TestGate:
    def _resolved(self, executor, name):
        return sources.resolve_tool(executor, TOOLS, name, None)

    def test_no_pause_needs_no_approval(self):
        executor = FakeExecutor(pause=None)
        gate = sources.gate(executor, TOOLS, self._resolved(executor, "read_webpage"), {"url": "https://x"})
        assert gate.requires_approval is False and gate.refusal is None

    def test_an_approval_pause_needs_approval(self):
        executor = FakeExecutor(pause={"pause_type": "awaiting_approval"})
        gate = sources.gate(executor, TOOLS, self._resolved(executor, "create_issue"), {})
        assert gate.requires_approval is True and gate.refusal is None

    @pytest.mark.parametrize(
        "pause,needle",
        [
            ({"pause_type": "headless_denied", "deny_reason": "An admin turned off changes"}, "admin"),
            ({"pause_type": "requires_client_execution"}, "client"),
            ({"pause_type": "awaiting_approval", "connection_required": {"connector_name": "Gmail"}}, "Gmail"),
        ],
    )
    def test_refusals(self, pause, needle):
        executor = FakeExecutor(pause=pause)
        gate = sources.gate(executor, TOOLS, self._resolved(executor, "list_issues"), {})
        assert gate.refusal and needle in gate.refusal

    def test_denylisted_device_command_is_refused_outright(self):
        executor = FakeExecutor(pause={"pause_type": "awaiting_approval"}, forced=True)
        gate = sources.gate(executor, TOOLS, self._resolved(executor, "run_command"), {"command": "rm -rf /"})
        assert gate.refusal and "denylist" in gate.refusal

    def test_binding_hashes_the_template(self):
        executor = FakeExecutor()
        resolved = self._resolved(executor, "list_issues")
        args = {"q": "updated:>{{last_checked_at}}"}
        bound = sources.binding(resolved, args, sources.Gate(True), now_iso="2026-10-05T12:07:00Z")
        assert bound["args_hash"] == canonical_args_hash("t-gh", "list_issues", args)
        assert bound["required"] is True and bound["approved_at"]
        free = sources.binding(resolved, args, sources.Gate(False), now_iso="x")
        assert free["required"] is False and free["approved_at"] is None


def _approval(tool_id="t-gh", action="list_issues", args=None, required=True):
    args = {"q": "is:open {{last_checked_date}}"} if args is None else args
    return {
        "tool_id": tool_id,
        "tool_name": "mcp_tool",
        "action": action,
        "args_hash": canonical_args_hash(tool_id, action, args),
        "required": required,
    }, args


class TestRunCall:
    @pytest.fixture()
    def built(self, monkeypatch):
        holder = {}

        def install(executor):
            def build(user_id, agent_id, *, headless, allowlist=()):
                holder.update(user_id=user_id, agent_id=agent_id, headless=headless, allowlist=list(allowlist))
                return executor, TOOLS

            monkeypatch.setattr(sources, "build_executor", build)
            return holder

        return install

    def _run(self, approval, args, **overrides):
        kwargs = dict(
            user_id="u1",
            agent_id=None,
            conversation_id="c1",
            approval=approval,
            args_template=args,
            placeholders={"now": NOW, "last_checked_at": "2026-10-04T08:00:00Z"},
            call_tag="m1",
        )
        kwargs.update(overrides)
        return sources.run_call(**kwargs)

    def test_replays_the_bound_call_with_placeholders_substituted(self, built):
        executor = FakeExecutor(result={"items": [1]})
        holder = built(executor)
        approval, args = _approval()
        content = self._run(approval, args)
        assert content.data == {"items": [1]}
        assert holder["headless"] is True and holder["allowlist"] == ["t-gh"]
        executed = [c for c in executor.calls if c[0] == "execute"][0]
        assert executed[2] == {"q": "is:open 2026/10/04"}
        assert executor.conversation_id == "c1"

    def test_a_call_that_needed_no_approval_is_not_allowlisted(self, built):
        holder = built(FakeExecutor(result="ok"))
        approval, args = _approval(required=False)
        self._run(approval, args)
        assert holder["allowlist"] == []

    def test_changed_arguments_are_refused(self, built):
        built(FakeExecutor(result="ok"))
        approval, _args = _approval()
        with pytest.raises(SourceRevoked, match="no longer match"):
            self._run(approval, {"q": "is:closed"})

    def test_a_removed_tool_or_action_is_revoked(self, built):
        built(FakeExecutor(result="ok"))
        approval, args = _approval(tool_id="t-gone")
        with pytest.raises(SourceRevoked, match="no longer available"):
            self._run(approval, args)
        approval, args = _approval(action="delete_repo")
        with pytest.raises(SourceRevoked):
            self._run(approval, args)

    def test_a_denial_on_the_check_revokes(self, built):
        executor = FakeExecutor(pause={"pause_type": "headless_denied", "deny_reason": "denylisted command"})
        built(executor)
        approval, args = _approval()
        with pytest.raises(SourceRevoked, match="denylisted"):
            self._run(approval, args)
        assert not [c for c in executor.calls if c[0] == "execute"]

    @pytest.mark.parametrize(
        "result,error",
        [
            ({"error": "device status: revoked"}, SourceRevoked),
            ({"error": "device is offline"}, SourceUnreachable),
            ({"status_code": 503}, SourceUnreachable),
            ({"status_code": 404}, SourceError),
            ("Error: invalid query", SourceError),
        ],
    )
    def test_in_band_failures_are_sorted(self, built, result, error):
        built(FakeExecutor(result=result))
        approval, args = _approval()
        with pytest.raises(error):
            self._run(approval, args)

    def test_a_nonzero_exit_code_is_content(self, built):
        built(FakeExecutor(result={"exit_code": 1, "stdout": "", "stderr": "nope"}))
        approval, args = _approval(tool_id="t-dev", action="run_command", args={"command": "systemctl is-active x"})
        content = self._run(approval, args)
        assert content.data["exit_code"] == 1

    def test_exceptions_are_sorted(self, built):
        built(FakeExecutor(raises=TimeoutError("timed out")))
        approval, args = _approval()
        with pytest.raises(SourceUnreachable):
            self._run(approval, args)
        built(FakeExecutor(raises=ValueError("bad input")))
        with pytest.raises(SourceError) as info:
            self._run(approval, args)
        assert not isinstance(info.value, SourceUnreachable)
