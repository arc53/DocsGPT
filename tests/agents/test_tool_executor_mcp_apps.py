"""MCP Apps in the tool executor: who sees an app-only tool, and the view a call carries."""

from unittest.mock import Mock

import pytest

from docsgpt.agents.tool_executor import ToolExecutor

TOOL_ROW_ID = "00000000-0000-0000-0000-0000000000aa"
VIEW = "ui://excalidraw/mcp-app.html"


def _tools_dict():
    return {
        "t1": {
            "id": TOOL_ROW_ID,
            "name": "mcp_tool",
            "config": {},
            "actions": [
                {"name": "create_view", "description": "Draw", "active": True, "parameters": {"properties": {}},
                 "ui": {"resourceUri": VIEW}},
                {"name": "save_checkpoint", "description": "Save", "active": True, "parameters": {"properties": {}},
                 "ui": {"visibility": ["app"]}},
                {"name": "read_me", "description": "Docs", "active": True, "parameters": {"properties": {}}},
            ],
        }
    }


def _call(name, call_id="c1"):
    call = Mock()
    call.name = name
    call.id = call_id
    call.arguments = "{}"
    return call


def _drain(gen):
    while True:
        try:
            yield next(gen)
        except StopIteration:
            return


@pytest.fixture
def apps(monkeypatch):
    """Switch MCP Apps on or off for the executor."""

    def switch(on: bool) -> None:
        monkeypatch.setattr("docsgpt.agents.mcp_apps.enabled", lambda: on)

    switch(True)
    return switch


def _route(monkeypatch, action):
    monkeypatch.setattr(
        "docsgpt.agents.tool_executor.ToolActionParser",
        lambda _cls, **kw: Mock(parse_args=Mock(return_value=("t1", action, {}))),
    )


@pytest.mark.unit
class TestModelVisibility:
    def test_app_only_tools_are_not_offered_to_the_model(self, apps):
        names = [t["function"]["name"] for t in ToolExecutor().prepare_tools_for_llm(_tools_dict())]
        assert names == ["create_view", "read_me"]
        assert ToolExecutor._advertisable_action_names(_tools_dict()) == {"create_view", "read_me"}

    def test_with_mcp_apps_off_every_tool_is_offered_as_before(self, apps):
        apps(False)
        names = [t["function"]["name"] for t in ToolExecutor().prepare_tools_for_llm(_tools_dict())]
        assert names == ["create_view", "save_checkpoint", "read_me"]

    def test_a_model_call_to_an_app_only_tool_is_refused(self, apps, mock_tool_manager, monkeypatch):
        _route(monkeypatch, "save_checkpoint")
        executor = ToolExecutor(user="u1")

        events = list(_drain(executor.execute(_tools_dict(), _call("save_checkpoint"), "MockLLM")))

        assert events[-1]["data"]["status"] == "error"
        assert "app" in events[-1]["data"]["result"]
        mock_tool_manager.load_tool.return_value.execute_action.assert_not_called()

    def test_the_refusal_is_journaled_like_other_refused_calls(self, apps, mock_tool_manager, monkeypatch):
        _route(monkeypatch, "save_checkpoint")
        proposed, failed = Mock(return_value=True), Mock()
        monkeypatch.setattr("docsgpt.agents.tool_executor._record_proposed", proposed)
        monkeypatch.setattr("docsgpt.agents.tool_executor._mark_failed", failed)
        executor = ToolExecutor(user="u1")

        list(_drain(executor.execute(_tools_dict(), _call("save_checkpoint", call_id="c9"), "MockLLM")))

        args, kwargs = proposed.call_args
        assert args[:3] == ("c9", "mcp_tool", "save_checkpoint")
        assert kwargs["tool_id"] == TOOL_ROW_ID
        assert failed.call_args.args[0] == "c9"


@pytest.mark.unit
class TestViewOnTheCall:
    def test_a_call_with_a_view_carries_it(self, apps, mock_tool_manager, monkeypatch):
        _route(monkeypatch, "create_view")
        tool = mock_tool_manager.load_tool.return_value
        typed = {"content": [{"type": "text", "text": "ok"}], "structuredContent": {"checkpointId": "c"}, "isError": False}
        tool.take_app_result = Mock(return_value=typed)
        executor = ToolExecutor(user="u1")

        events = list(_drain(executor.execute(_tools_dict(), _call("create_view"), "MockLLM")))

        completed = next(e for e in events if e["data"].get("status") == "completed")
        assert completed["data"]["ui"] == {"resource_uri": VIEW, "tool_id": TOOL_ROW_ID, "result": typed}
        # Saved with the conversation, so the view renders again on reload.
        assert executor.get_truncated_tool_calls()[0]["ui"]["resource_uri"] == VIEW

    def test_a_result_the_guardrail_changed_shows_no_view(self, apps, mock_tool_manager, monkeypatch):
        # Masked or blocked output must not reach the view or the saved call in the clear.
        _route(monkeypatch, "create_view")
        tool = mock_tool_manager.load_tool.return_value
        tool.take_app_result = Mock(return_value={"content": [{"type": "text", "text": "sk-secret"}]})
        executor = ToolExecutor(user="u1")
        monkeypatch.setattr(executor, "_guardrail_tool_result", lambda result, *_: "[masked]")

        events = list(_drain(executor.execute(_tools_dict(), _call("create_view"), "MockLLM")))

        assert all("ui" not in e["data"] for e in events)
        assert all("ui" not in c for c in executor.get_truncated_tool_calls())
        tool.take_app_result.assert_called_once()

    def test_the_views_result_is_screened_on_its_own(self, apps, mock_tool_manager, monkeypatch):
        # The model's copy drops structuredContent when there is content; the view keeps it.
        _route(monkeypatch, "create_view")
        tool = mock_tool_manager.load_tool.return_value
        tool.take_app_result = Mock(return_value={
            "content": [{"type": "text", "text": "ok"}], "structuredContent": {"token": "sk-secret"},
        })
        executor = ToolExecutor(user="u1")
        scanned = []

        def guardrail(result, *_):
            scanned.append(result)
            return "[masked]" if "sk-secret" in str(result) else result

        monkeypatch.setattr(executor, "_guardrail_tool_result", guardrail)

        events = list(_drain(executor.execute(_tools_dict(), _call("create_view"), "MockLLM")))

        completed = next(e for e in events if e["data"].get("status") == "completed")
        assert "ui" not in completed["data"]
        assert any(isinstance(r, dict) and "structuredContent" in r for r in scanned)

    def test_the_views_copy_is_sanitized_and_redacted(
        self, apps, mock_tool_manager, monkeypatch
    ):
        _route(monkeypatch, "create_view")
        tool = mock_tool_manager.load_tool.return_value
        # A control character too: the view's copy is sanitized like every other.
        tool.take_app_result = Mock(return_value={
            "content": [{"type": "text", "text": "key=raw-secret\x07"}], "structuredContent": {"key": "raw-secret"},
        })
        executor = ToolExecutor(user="u1")
        monkeypatch.setattr(executor, "exposed_secrets", lambda: {"raw-secret": "{{link_secret:ABCDEF}}"})

        events = list(_drain(executor.execute(_tools_dict(), _call("create_view"), "MockLLM")))

        completed = next(e for e in events if e["data"].get("status") == "completed")
        assert completed["data"]["ui"]["result"] == {
            "content": [{"type": "text", "text": "key={{link_secret:ABCDEF}}"}],
            "structuredContent": {"key": "{{link_secret:ABCDEF}}"},
        }

    def test_a_call_without_a_view_carries_none(self, apps, mock_tool_manager, monkeypatch):
        _route(monkeypatch, "read_me")
        mock_tool_manager.load_tool.return_value.take_app_result = Mock(return_value={"content": []})
        executor = ToolExecutor(user="u1")

        events = list(_drain(executor.execute(_tools_dict(), _call("read_me"), "MockLLM")))

        assert all("ui" not in e["data"] for e in events)

    def test_with_mcp_apps_off_no_view(self, apps, mock_tool_manager, monkeypatch):
        apps(False)
        _route(monkeypatch, "create_view")
        mock_tool_manager.load_tool.return_value.take_app_result = Mock(return_value={"content": []})
        executor = ToolExecutor(user="u1")

        events = list(_drain(executor.execute(_tools_dict(), _call("create_view"), "MockLLM")))

        assert all("ui" not in e["data"] for e in events)
