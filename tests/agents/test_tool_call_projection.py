"""``get_truncated_tool_calls`` is what the client persists and reloads.

It is a hand-written key whitelist, and two keys the UI depends on were never
added to it. The per-call ``tool_call`` stream event carries the full dict, so
everything looks right live and then disappears on reload:

- ``artifacts`` — the per-file download chips. Without it a turn falls back to
  the single ``artifact_id``, so a ``run_code`` that wrote three files shows one
  chip labelled "Code Executor" instead of three labelled by filename. That is
  precisely the bug ``get_artifacts`` was added to fix, reintroduced at the
  persistence boundary. Measured in production: 0 of 265 persisted tool calls
  carry ``artifacts`` while 32 of 296 ``user_logs`` rows (written from the raw
  dict) do.
- ``device_id`` — the remote-device approval UI reads it to wire up its sticky
  "don't ask again" action (``ConversationBubble.tsx:742-752``).
"""

from __future__ import annotations

import pytest

from application.agents.tool_executor import ToolExecutor


@pytest.mark.unit
class TestTruncatedToolCallsKeepsWhatTheUiNeeds:
    @staticmethod
    def _executor(**extra):
        executor = ToolExecutor()
        executor.tool_calls = [
            {
                "tool_name": "code_executor",
                "call_id": "c1",
                "action_name": "run_code",
                "arguments": {"code": "..."},
                "artifact_id": "a1",
                "result": "ok",
                "status": "completed",
                **extra,
            }
        ]
        return executor

    def test_keeps_every_artifact_not_just_the_first(self):
        artifacts = [
            {"id": "a1", "filename": "chart.png", "ref": "A1"},
            {"id": "a2", "filename": "data.csv", "ref": "A2"},
        ]
        projected = self._executor(artifacts=artifacts).get_truncated_tool_calls()
        assert projected[0]["artifacts"] == artifacts

    def test_keeps_the_device_id_for_the_approval_ui(self):
        projected = self._executor(device_id="windows-8e15").get_truncated_tool_calls()
        assert projected[0]["device_id"] == "windows-8e15"

    def test_omits_the_keys_entirely_when_absent(self):
        """A plain tool call must not grow null keys in every persisted row."""
        projected = self._executor().get_truncated_tool_calls()
        assert "artifacts" not in projected[0]
        assert "device_id" not in projected[0]

    def test_still_truncates_the_result_and_drops_the_bulky_keys(self):
        executor = self._executor(
            result_full="x" * 100000,
            resolved_arguments={"code": "y" * 100000},
        )
        projected = executor.get_truncated_tool_calls()
        # ``result_full``/``resolved_arguments`` are deliberately not persisted:
        # they are the untruncated copies this projection exists to shed.
        assert "result_full" not in projected[0]
        assert "resolved_arguments" not in projected[0]

    def test_shape_is_otherwise_unchanged(self):
        projected = self._executor().get_truncated_tool_calls()
        assert set(projected[0]) == {
            "tool_name",
            "call_id",
            "action_name",
            "arguments",
            "artifact_id",
            "result",
            "status",
        }
