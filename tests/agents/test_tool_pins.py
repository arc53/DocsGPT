"""Fixed ("pinned") tool parameters: the model never sees or overrides them."""

from unittest.mock import Mock

import pytest

from docsgpt.agents.tool_executor import ToolExecutor


def _action(**properties):
    return {
        "name": "telegram_send_message",
        "description": "Send a message",
        "active": True,
        "parameters": {"type": "object", "properties": properties},
    }


def _llm(description="", **extra):
    return {"type": "string", "description": description, "filled_by_llm": True, "value": "", **extra}


def _pinned(value, type_="string"):
    return {"type": type_, "description": "", "filled_by_llm": False, "value": value}


def _run(executor, tools_dict, call_args, monkeypatch):
    monkeypatch.setattr(
        "docsgpt.agents.tool_executor.ToolActionParser",
        lambda _cls, **kw: Mock(parse_args=Mock(return_value=("t1", "telegram_send_message", call_args))),
    )
    call = Mock()
    call.name = "telegram_send_message"
    call.id = "c1"
    call.arguments = "{}"
    gen = executor.execute(tools_dict, call, "MockLLM")
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


def _tools(action):
    return {
        "t1": {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "telegram",
            "config": {},
            "actions": [action],
        }
    }


@pytest.mark.unit
class TestPinnedValuesAtRunTime:
    def test_llm_cannot_override_a_pinned_value(self, mock_tool_manager, monkeypatch):
        """A model that sends the pinned key anyway (a mistake, or a prompt
        injection naming another chat) still sends to the pinned chat."""
        tool = mock_tool_manager.load_tool.return_value
        action = _action(text=_llm(), chat_id=_pinned("111"))
        _run(ToolExecutor(user="u"), _tools(action), {"text": "hi", "chat_id": "666"}, monkeypatch)
        tool.execute_action.assert_called_once_with("telegram_send_message", text="hi", chat_id="111")

    @pytest.mark.parametrize("value", [0, False])
    def test_falsy_pins_are_honoured(self, mock_tool_manager, monkeypatch, value):
        tool = mock_tool_manager.load_tool.return_value
        action = _action(text=_llm(), limit=_pinned(value, "integer"))
        _run(ToolExecutor(user="u"), _tools(action), {"text": "hi", "limit": 50}, monkeypatch)
        tool.execute_action.assert_called_once_with("telegram_send_message", text="hi", limit=value)

    def test_hidden_parameter_without_a_value_is_omitted_even_if_the_llm_sends_it(
        self, mock_tool_manager, monkeypatch,
    ):
        """An empty fixed value means "leave it out" (an OpenAPI optional
        parameter); the model was never shown it, so its value is dropped."""
        tool = mock_tool_manager.load_tool.return_value
        action = _action(text=_llm(), chat_id=_pinned(""))
        _run(ToolExecutor(user="u"), _tools(action), {"text": "hi", "chat_id": "666"}, monkeypatch)
        tool.execute_action.assert_called_once_with("telegram_send_message", text="hi")

    def test_llm_filled_parameter_keeps_its_default_when_omitted(self, mock_tool_manager, monkeypatch):
        tool = mock_tool_manager.load_tool.return_value
        action = _action(text=_llm(), chat_id=_llm(value="42"))
        _run(ToolExecutor(user="u"), _tools(action), {"text": "hi"}, monkeypatch)
        tool.execute_action.assert_called_once_with("telegram_send_message", text="hi", chat_id="42")

    def test_llm_filled_parameter_takes_the_llm_value(self, mock_tool_manager, monkeypatch):
        tool = mock_tool_manager.load_tool.return_value
        action = _action(text=_llm(), chat_id=_llm(value="42"))
        _run(ToolExecutor(user="u"), _tools(action), {"text": "hi", "chat_id": "7"}, monkeypatch)
        tool.execute_action.assert_called_once_with("telegram_send_message", text="hi", chat_id="7")

    def test_unknown_llm_arguments_are_dropped(self, mock_tool_manager, monkeypatch):
        tool = mock_tool_manager.load_tool.return_value
        action = _action(text=_llm())
        _run(ToolExecutor(user="u"), _tools(action), {"text": "hi", "token": "x"}, monkeypatch)
        tool.execute_action.assert_called_once_with("telegram_send_message", text="hi")

    def test_api_tool_pinned_header_is_not_overridden(self, mock_tool_manager, monkeypatch):
        executor = ToolExecutor(user="u")
        monkeypatch.setattr(
            "docsgpt.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(parse_args=Mock(return_value=("t1", "get_item", {"id": "1", "X-Tenant": "b"}))),
        )
        tools_dict = {
            "t1": {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "api_tool",
                "config": {
                    "actions": {
                        "get_item": {
                            "name": "get_item",
                            "url": "https://api.example.com/items",
                            "method": "GET",
                            "active": True,
                            "headers": {"properties": {"X-Tenant": _pinned("a")}},
                            "query_params": {"properties": {"id": _llm()}},
                            "body": {"properties": {}},
                        }
                    }
                },
            }
        }
        call = Mock()
        call.name = "get_item"
        call.id = "c1"
        gen = executor.execute(tools_dict, call, "MockLLM")
        while True:
            try:
                next(gen)
            except StopIteration:
                break
        _, kwargs = mock_tool_manager.load_tool.call_args
        assert kwargs["tool_config"]["headers"] == {"X-Tenant": "a"}
        assert kwargs["tool_config"]["query_params"] == {"id": "1"}


@pytest.mark.unit
class TestPinnedValuesInTheSchema:
    def test_pinned_parameter_is_not_shown_to_the_llm(self):
        executor = ToolExecutor(user="u")
        action = _action(text=_llm(), chat_id=_pinned("111"), limit=_pinned(0, "integer"))
        functions = executor.prepare_tools_for_llm(_tools(action))
        params = functions[0]["function"]["parameters"]
        assert set(params["properties"]) == {"text"}

    def test_pinned_parameter_is_dropped_from_the_required_list(self):
        executor = ToolExecutor(user="u")
        action = _action(text=_llm(required=True), chat_id={**_pinned("111"), "required": True})
        params = executor.prepare_tools_for_llm(_tools(action))[0]["function"]["parameters"]
        assert params["required"] == ["text"]


@pytest.mark.unit
class TestPinHelpers:
    def test_set_pins_fixes_and_releases_parameters(self):
        from docsgpt.agents.tool_pins import set_pins

        action = _action(text=_llm(), chat_id=_llm())
        pinned = set_pins(action, {"chat_id": "123"})
        assert pinned["parameters"]["properties"]["chat_id"] == {
            "type": "string", "description": "", "filled_by_llm": False, "value": "123",
        }
        released = set_pins(pinned, {"chat_id": None})
        assert released["parameters"]["properties"]["chat_id"]["filled_by_llm"] is True
        assert released["parameters"]["properties"]["chat_id"]["value"] == ""
        # The input is not modified.
        assert action["parameters"]["properties"]["chat_id"]["filled_by_llm"] is True

    def test_set_pins_rejects_unknown_parameters(self):
        from docsgpt.agents.tool_pins import set_pins

        with pytest.raises(ValueError):
            set_pins(_action(text=_llm()), {"token": "x"})

    @pytest.mark.parametrize(
        "type_, value, expected",
        [
            ("integer", "5", 5),
            ("integer", 0, 0),
            ("number", "2.5", 2.5),
            ("boolean", "false", False),
            ("boolean", True, True),
            ("string", 12, "12"),
        ],
    )
    def test_coerce_value(self, type_, value, expected):
        from docsgpt.agents.tool_pins import coerce_value

        assert coerce_value({"type": type_}, value) == expected

    @pytest.mark.parametrize(
        "type_, value",
        [("integer", "five"), ("integer", 2.5), ("boolean", "maybe"), ("string", ""), ("string", None),
         ("string", {"a": 1}), ("array", "x")],
    )
    def test_coerce_value_rejects(self, type_, value):
        from docsgpt.agents.tool_pins import coerce_value

        with pytest.raises(ValueError):
            coerce_value({"type": type_}, value)

    def test_merge_keeps_schema_and_ignores_type_changes(self):
        from docsgpt.agents.tool_pins import merge_submitted_actions

        stored = [_action(text=_llm(), chat_id=_llm())]
        merged = merge_submitted_actions(stored, [{
            "name": "telegram_send_message",
            "parameters": {"properties": {"chat_id": {"type": "object", "filled_by_llm": False, "value": "9"}}},
        }], may_change_pins=True)
        chat_id = merged[0]["parameters"]["properties"]["chat_id"]
        assert chat_id["type"] == "string"
        assert chat_id["value"] == "9" and chat_id["filled_by_llm"] is False

    def test_merge_refuses_pin_changes_without_permission(self):
        from docsgpt.agents.tool_pins import PinChangeRefused, merge_submitted_actions

        stored = [_action(text=_llm(), chat_id=_pinned("111"))]
        with pytest.raises(PinChangeRefused):
            merge_submitted_actions(stored, [{
                "name": "telegram_send_message",
                "parameters": {"properties": {"chat_id": {"filled_by_llm": True}}},
            }], may_change_pins=False)
        # Resending the stored values unchanged is fine.
        merged = merge_submitted_actions(stored, [{
            "name": "telegram_send_message",
            "active": False,
            "parameters": {"properties": {"chat_id": {"filled_by_llm": False, "value": "111"}}},
        }], may_change_pins=False)
        assert merged[0]["active"] is False

    def test_carry_pins(self):
        from docsgpt.agents.tool_pins import carry_pins

        old = _action(q=_llm(), team=_pinned("ENG"))
        fresh = _action(q={"type": "string", "filled_by_llm": True, "value": ""}, team={"type": "string"})
        carried = carry_pins(old, fresh)
        assert carried["parameters"]["properties"]["team"]["value"] == "ENG"
        assert carried["parameters"]["properties"]["team"]["filled_by_llm"] is False


@pytest.mark.unit
class TestArgumentsShownForACall:
    """What the chat shows for a call is what is sent, not what the model asked."""

    def _pause(self, executor, action, call_args, monkeypatch):
        monkeypatch.setattr(
            "docsgpt.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(parse_args=Mock(return_value=("t1", "telegram_send_message", call_args))),
        )
        call = Mock()
        call.name = "telegram_send_message"
        call.id = "c1"
        return executor.check_pause(_tools(action), call, "MockLLM")

    def test_approval_card_shows_the_fixed_value(self, monkeypatch):
        action = {**_action(text=_llm(), chat_id=_pinned("111")), "require_approval": True}
        pending = self._pause(ToolExecutor(user="u"), action, {"text": "hi", "chat_id": "666"}, monkeypatch)
        assert pending["pause_type"] == "awaiting_approval"
        assert pending["sent_arguments"] == {"text": "hi", "chat_id": "111"}
        # What the model asked stays as it was: resuming replays it to the model.
        assert pending["arguments"] == {"text": "hi", "chat_id": "666"}

    def test_no_separate_arguments_when_nothing_changes(self, monkeypatch):
        action = {**_action(text=_llm()), "require_approval": True}
        pending = self._pause(ToolExecutor(user="u"), action, {"text": "hi"}, monkeypatch)
        assert "sent_arguments" not in pending

    def test_a_finished_call_records_what_was_sent(self, mock_tool_manager, monkeypatch):
        executor = ToolExecutor(user="u")
        action = _action(text=_llm(), chat_id=_pinned("111"))
        _run(executor, _tools(action), {"text": "hi", "chat_id": "666"}, monkeypatch)
        recorded = executor.tool_calls[-1]
        assert recorded["sent_arguments"] == {"text": "hi", "chat_id": "111"}
        assert recorded["arguments"] == {"text": "hi", "chat_id": "666"}

    def test_headers_are_never_shown(self):
        from docsgpt.agents.tool_pins import sent_arguments

        action = {
            "headers": {"properties": {"Authorization": _pinned("Bearer secret")}},
            "query_params": {"properties": {"id": _llm()}},
        }
        assert sent_arguments(action, {"id": "1"}) == {"id": "1"}
