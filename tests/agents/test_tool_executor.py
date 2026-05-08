"""Tests for ToolExecutor — tool discovery, preparation, and execution."""

from unittest.mock import Mock

import pytest
from application.agents.tool_executor import ToolExecutor


@pytest.mark.unit
class TestToolExecutorInit:

    def test_default_state(self):
        executor = ToolExecutor()
        assert executor.user_api_key is None
        assert executor.user is None
        assert executor.tool_calls == []
        assert executor._loaded_tools == {}
        assert executor.conversation_id is None

    def test_init_with_params(self):
        executor = ToolExecutor(
            user_api_key="key", user="alice", decoded_token={"sub": "alice"}
        )
        assert executor.user_api_key == "key"
        assert executor.user == "alice"


@pytest.mark.unit
class TestToolExecutorGetTools:

    @staticmethod
    def _patch_conn(monkeypatch, pg_conn):
        from contextlib import contextmanager

        @contextmanager
        def _use_pg_conn():
            yield pg_conn

        monkeypatch.setattr(
            "application.agents.tool_executor.db_readonly", _use_pg_conn
        )

    def test_get_tools_uses_api_key_when_present(self, pg_conn, monkeypatch):
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.user_tools import UserToolsRepository

        tool = UserToolsRepository(pg_conn).create(user_id="alice", name="tool1")
        AgentsRepository(pg_conn).create(
            user_id="alice",
            name="a",
            status="active",
            key="test_key",
            tools=[str(tool["id"])],
        )
        self._patch_conn(monkeypatch, pg_conn)

        executor = ToolExecutor(user_api_key="test_key", user="alice")
        tools = executor.get_tools()
        assert isinstance(tools, dict)
        # The tool id should appear as key; tool_data['id'] is set
        assert str(tool["id"]) in tools
        assert tools[str(tool["id"])]["id"] == tool["id"]

    def test_get_tools_uses_user_when_no_api_key(self, pg_conn, monkeypatch):
        from application.storage.db.repositories.user_tools import UserToolsRepository

        UserToolsRepository(pg_conn).create(
            user_id="alice", name="tool1", status=True
        )
        self._patch_conn(monkeypatch, pg_conn)

        executor = ToolExecutor(user="alice")
        tools = executor.get_tools()
        assert isinstance(tools, dict)
        assert len(tools) == 1

    def test_get_tools_defaults_to_local(self, pg_conn, monkeypatch):
        self._patch_conn(monkeypatch, pg_conn)

        executor = ToolExecutor()
        tools = executor.get_tools()
        assert isinstance(tools, dict)
        assert tools == {}


@pytest.mark.unit
class TestToolExecutorPrepare:

    def test_prepare_tools_for_llm_empty(self):
        executor = ToolExecutor()
        result = executor.prepare_tools_for_llm({})
        assert result == []

    def test_prepare_tools_for_llm_non_api_tool(self):
        executor = ToolExecutor()
        tools_dict = {
            "t1": {
                "name": "test_tool",
                "actions": [
                    {
                        "name": "do_thing",
                        "description": "Does a thing",
                        "active": True,
                        "parameters": {
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "The query",
                                    "filled_by_llm": True,
                                    "required": True,
                                }
                            }
                        },
                    }
                ],
            }
        }

        result = executor.prepare_tools_for_llm(tools_dict)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "do_thing"
        assert "query" in result[0]["function"]["parameters"]["properties"]

    def test_prepare_tools_skips_inactive_actions(self):
        executor = ToolExecutor()
        tools_dict = {
            "t1": {
                "name": "test_tool",
                "actions": [
                    {"name": "active_one", "description": "D", "active": True, "parameters": {"properties": {}}},
                    {"name": "inactive_one", "description": "D", "active": False, "parameters": {"properties": {}}},
                ],
            }
        }

        result = executor.prepare_tools_for_llm(tools_dict)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "active_one"

    def test_prepare_tools_builds_name_mapping(self):
        executor = ToolExecutor()
        tools_dict = {
            "t1": {
                "name": "test_tool",
                "actions": [
                    {"name": "do_thing", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            }
        }
        executor.prepare_tools_for_llm(tools_dict)
        assert executor._name_to_tool["do_thing"] == ("t1", "do_thing")
        assert executor._tool_to_name[("t1", "do_thing")] == "do_thing"

    def test_prepare_tools_duplicate_names_get_numbered_suffixes(self):
        executor = ToolExecutor()
        tools_dict = {
            "t1": {
                "name": "tool_a",
                "actions": [
                    {"name": "search", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
            "t2": {
                "name": "tool_b",
                "actions": [
                    {"name": "search", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
        }
        result = executor.prepare_tools_for_llm(tools_dict)
        names = [r["function"]["name"] for r in result]
        assert "search_1" in names
        assert "search_2" in names
        assert executor._name_to_tool["search_1"][1] == "search"
        assert executor._name_to_tool["search_2"][1] == "search"

    def test_prepare_tools_unique_name_no_suffix(self):
        executor = ToolExecutor()
        tools_dict = {
            "t1": {
                "name": "tool_a",
                "actions": [
                    {"name": "get_weather", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
            "t2": {
                "name": "tool_b",
                "actions": [
                    {"name": "send_email", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
        }
        result = executor.prepare_tools_for_llm(tools_dict)
        names = [r["function"]["name"] for r in result]
        assert "get_weather" in names
        assert "send_email" in names

    def test_prepare_tools_suffix_skips_collision_with_unique_name(self):
        """If action 'foo_1' exists as unique and 'foo' is duplicated, skip '_1'."""
        executor = ToolExecutor()
        tools_dict = {
            "t1": {
                "name": "tool_a",
                "actions": [
                    {"name": "foo", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
            "t2": {
                "name": "tool_b",
                "actions": [
                    {"name": "foo", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
            "t3": {
                "name": "tool_c",
                "actions": [
                    {"name": "foo_1", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
        }
        result = executor.prepare_tools_for_llm(tools_dict)
        names = [r["function"]["name"] for r in result]
        # foo_1 is taken by the unique action, so duplicates skip to _2 and _3
        assert "foo_1" in names  # The unique action
        assert "foo_2" in names
        assert "foo_3" in names
        assert executor._name_to_tool["foo_1"] == ("t3", "foo_1")

    def test_build_tool_parameters_filters_non_llm_fields(self):
        executor = ToolExecutor()
        action = {
            "parameters": {
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                        "filled_by_llm": True,
                        "value": "default_val",
                        "required": True,
                    },
                    "hidden": {
                        "type": "string",
                        "filled_by_llm": False,
                    },
                }
            }
        }

        result = executor._build_tool_parameters(action)
        assert "query" in result["properties"]
        assert "hidden" not in result["properties"]
        assert "query" in result["required"]
        # filled_by_llm, value, required stripped from schema
        assert "filled_by_llm" not in result["properties"]["query"]
        assert "value" not in result["properties"]["query"]


@pytest.mark.unit
class TestCheckPause:

    def _make_call(self, name="action_toolid", call_id="c1", arguments="{}"):
        call = Mock()
        call.name = name
        call.id = call_id
        call.arguments = arguments
        call.thought_signature = None
        return call

    def test_client_side_tool_returns_llm_name(self):
        """check_pause returns the clean LLM-facing name and llm_name field."""
        executor = ToolExecutor()

        tools_dict = {
            "ct0": {
                "name": "write_file",
                "client_side": True,
                "actions": [
                    {"name": "write_file", "description": "Write a file", "active": True, "parameters": {}},
                ],
            }
        }

        # Prepare tools so the mapping is built
        executor.prepare_tools_for_llm(tools_dict)

        call = self._make_call(name="write_file")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")

        assert result is not None
        assert result["name"] == "write_file"
        assert result["llm_name"] == "write_file"
        assert result["action_name"] == "write_file"
        assert result["tool_id"] == "ct0"

    def test_approval_required_returns_llm_name(self):
        """check_pause for approval-required tools returns clean LLM name."""
        executor = ToolExecutor()

        tools_dict = {
            "t1": {
                "name": "dangerous_tool",
                "actions": [
                    {"name": "delete_all", "description": "Deletes everything", "active": True,
                     "require_approval": True, "parameters": {}},
                ],
            }
        }

        executor.prepare_tools_for_llm(tools_dict)

        call = self._make_call(name="delete_all")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")

        assert result is not None
        assert result["name"] == "delete_all"
        assert result["llm_name"] == "delete_all"
        assert result["action_name"] == "delete_all"


@pytest.mark.unit
class TestToolExecutorExecute:

    def _make_call(self, name="action_toolid", call_id="c1", arguments="{}"):
        call = Mock()
        call.name = name
        call.id = call_id
        call.arguments = arguments
        return call

    def test_execute_parse_failure(self, monkeypatch):
        executor = ToolExecutor()

        monkeypatch.setattr(
            "application.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(parse_args=Mock(return_value=(None, None, {}))),
        )

        call = self._make_call(name="bad")
        gen = executor.execute({}, call, "MockLLM")

        events = []
        result = None
        while True:
            try:
                events.append(next(gen))
            except StopIteration as e:
                result = e.value
                break

        assert result[0] == "Failed to parse tool call."
        assert len(executor.tool_calls) == 1
        assert events[0]["data"]["status"] == "error"

    def test_execute_tool_not_found(self, monkeypatch):
        executor = ToolExecutor()

        monkeypatch.setattr(
            "application.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(parse_args=Mock(return_value=("missing_id", "action", {}))),
        )

        call = self._make_call()
        gen = executor.execute({}, call, "MockLLM")

        events = []
        result = None
        while True:
            try:
                events.append(next(gen))
            except StopIteration as e:
                result = e.value
                break

        assert "not found" in result[0]
        assert events[0]["data"]["status"] == "error"

    def test_execute_success(self, mock_tool_manager, monkeypatch):
        executor = ToolExecutor(user="test_user")

        monkeypatch.setattr(
            "application.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(parse_args=Mock(return_value=("t1", "test_action", {"param1": "val"}))),
        )

        tools_dict = {
            "t1": {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "test_tool",
                "config": {"key": "val"},
                "actions": [
                    {"name": "test_action", "description": "Test", "parameters": {"properties": {}}},
                ],
            }
        }

        call = self._make_call(name="test_action_t1", call_id="c1")
        gen = executor.execute(tools_dict, call, "MockLLM")

        events = []
        result = None
        while True:
            try:
                events.append(next(gen))
            except StopIteration as e:
                result = e.value
                break

        assert result[0] == "Tool result"
        assert result[1] == "c1"

        statuses = [e["data"]["status"] for e in events]
        assert "pending" in statuses
        assert "completed" in statuses

    def test_get_truncated_tool_calls(self):
        executor = ToolExecutor()
        executor.tool_calls = [
            {
                "tool_name": "test",
                "call_id": "1",
                "action_name": "act",
                "arguments": {},
                "result": "A" * 100,
            }
        ]

        truncated = executor.get_truncated_tool_calls()
        assert len(truncated) == 1
        assert len(truncated[0]["result"]) <= 53
        assert truncated[0]["status"] == "completed"

    def test_tool_caching(self, mock_tool_manager, monkeypatch):
        executor = ToolExecutor(user="test_user")

        monkeypatch.setattr(
            "application.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(parse_args=Mock(return_value=("t1", "test_action", {}))),
        )

        tools_dict = {
            "t1": {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "test_tool",
                "config": {"key": "val"},
                "actions": [
                    {"name": "test_action", "description": "Test", "parameters": {"properties": {}}},
                ],
            }
        }

        call = self._make_call(name="test_action_t1")

        # First execution — loads tool
        gen = executor.execute(tools_dict, call, "MockLLM")
        while True:
            try:
                next(gen)
            except StopIteration:
                break

        # Second execution — should use cache
        gen = executor.execute(tools_dict, call, "MockLLM")
        while True:
            try:
                next(gen)
            except StopIteration:
                break

        # load_tool called only once due to cache
        assert mock_tool_manager.load_tool.call_count == 1

    def test_execute_api_tool(self, mock_tool_manager, monkeypatch):
        """Cover lines 199-202, 256-267: api_tool execution path."""
        executor = ToolExecutor(user="test_user")

        monkeypatch.setattr(
            "application.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(
                parse_args=Mock(return_value=("t1", "get_users", {"body_param": "val"}))
            ),
        )

        tools_dict = {
            "t1": {
                "name": "api_tool",
                "config": {
                    "actions": {
                        "get_users": {
                            "name": "get_users",
                            "description": "Get users",
                            "url": "https://api.example.com/users",
                            "method": "GET",
                            "query_params": {"properties": {}},
                            "headers": {"properties": {}},
                            "body": {"properties": {}},
                            "active": True,
                        }
                    }
                },
            }
        }

        call = self._make_call(name="get_users_t1", call_id="c2")
        gen = executor.execute(tools_dict, call, "MockLLM")

        events = []
        result = None
        while True:
            try:
                events.append(next(gen))
            except StopIteration as e:
                result = e.value
                break

        assert result is not None
        statuses = [e["data"]["status"] for e in events]
        assert "pending" in statuses

    def test_execute_with_prefilled_param_values(self, mock_tool_manager, monkeypatch):
        """Cover line 179: params not in call_args use default value."""
        executor = ToolExecutor(user="test_user")

        monkeypatch.setattr(
            "application.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(
                parse_args=Mock(return_value=("t1", "act", {}))
            ),
        )

        tools_dict = {
            "t1": {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "test_tool",
                "config": {"key": "val"},
                "actions": [
                    {
                        "name": "act",
                        "description": "Test",
                        "parameters": {
                            "properties": {
                                "hidden_param": {
                                    "type": "string",
                                    "value": "default_val",
                                    "filled_by_llm": False,
                                }
                            }
                        },
                    }
                ],
            }
        }

        call = self._make_call(name="act_t1")
        gen = executor.execute(tools_dict, call, "MockLLM")

        while True:
            try:
                next(gen)
            except StopIteration as e:
                result = e.value
                break

        assert result[0] == "Tool result"

    def test_execute_tool_with_artifact_id(self, mock_tool_manager, monkeypatch):
        """Cover lines 217-218: tool with get_artifact_id."""
        executor = ToolExecutor(user="test_user")

        monkeypatch.setattr(
            "application.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(
                parse_args=Mock(return_value=("t1", "act", {"q": "v"}))
            ),
        )

        mock_tool = mock_tool_manager.load_tool.return_value
        mock_tool.get_artifact_id = Mock(return_value="artifact-123")

        tools_dict = {
            "t1": {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "test_tool",
                "config": {"key": "val"},
                "actions": [
                    {
                        "name": "act",
                        "description": "Test",
                        "parameters": {"properties": {}},
                    }
                ],
            }
        }

        call = self._make_call(name="act_t1")
        gen = executor.execute(tools_dict, call, "MockLLM")

        events = []
        while True:
            try:
                events.append(next(gen))
            except StopIteration:
                break

        completed_events = [
            e for e in events if e["data"].get("status") == "completed"
        ]
        assert any(
            "artifact_id" in e.get("data", {}) for e in completed_events
        )

    def test_get_or_load_tool_encrypted_credentials(self, monkeypatch):
        """Cover lines 273-278: encrypted credentials path."""
        executor = ToolExecutor(user="test_user")

        mock_tm = Mock()
        mock_tool = Mock()
        mock_tm.load_tool.return_value = mock_tool
        monkeypatch.setattr(
            "application.agents.tool_executor.ToolManager", lambda config: mock_tm
        )
        monkeypatch.setattr(
            "application.agents.tool_executor.decrypt_credentials",
            lambda creds, user: {"api_key": "decrypted_key"},
        )

        tool_data = {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "custom_tool",
            "config": {"encrypted_credentials": "encrypted_blob"},
        }

        result = executor._get_or_load_tool(tool_data, "t1", "act")
        assert result is mock_tool
        call_kwargs = mock_tm.load_tool.call_args
        tool_config = call_kwargs[1]["tool_config"] if "tool_config" in call_kwargs[1] else call_kwargs[0][1]
        assert "api_key" in tool_config.get("auth_credentials", tool_config)

    def test_get_or_load_tool_mcp_tool(self, monkeypatch):
        """Cover lines 281-283: mcp_tool path sets query_mode."""
        executor = ToolExecutor(user="test_user")
        executor.conversation_id = "conv-123"

        mock_tm = Mock()
        mock_tool = Mock()
        mock_tm.load_tool.return_value = mock_tool
        monkeypatch.setattr(
            "application.agents.tool_executor.ToolManager", lambda config: mock_tm
        )

        tool_data = {
            "id": "00000000-0000-0000-0000-000000000002",
            "name": "mcp_tool",
            "config": {},
        }

        result = executor._get_or_load_tool(tool_data, "t1", "act")
        assert result is mock_tool
        call_kwargs = mock_tm.load_tool.call_args
        tool_config = call_kwargs[1].get("tool_config", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {})
        assert tool_config.get("query_mode") is True
        assert tool_config.get("conversation_id") == "conv-123"


# ---------------------------------------------------------------------------
# Coverage — additional uncovered lines: 217-218, 256-267
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolExecutorAdditionalCoverage:

    def test_get_artifact_id_exception_handled(self, monkeypatch):
        """Cover lines 217-218: get_artifact_id raises exception."""
        from types import SimpleNamespace

        executor = ToolExecutor(user="user1")

        mock_tool = Mock()
        mock_tool.execute_action.return_value = "result"
        mock_tool.get_artifact_id.side_effect = RuntimeError("artifact error")

        monkeypatch.setattr(
            "application.agents.tool_executor.ToolManager",
            lambda config: Mock(load_tool=Mock(return_value=mock_tool)),
        )

        tools_dict = {
            "t1": {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "custom_tool",
                "config": {"key": "val"},
                "actions": [
                    {
                        "name": "action1",
                        "active": True,
                        "parameters": {"properties": {}},
                    }
                ],
            }
        }
        # Create a fake call object matching what ToolActionParser expects
        call = SimpleNamespace(
            id="c1",
            function=SimpleNamespace(
                name="action1_t1",
                arguments="{}",
            ),
        )
        events = list(executor.execute(tools_dict, call, "OpenAILLM"))
        # Should complete without raising; artifact_id error is logged but not raised
        assert any(
            isinstance(e, dict) and e.get("type") == "tool_call"
            for e in events
        )

    def test_get_or_load_api_tool_with_body_content_type(self, monkeypatch):
        """Cover lines 256-267: api_tool with body_content_type."""
        executor = ToolExecutor(user="user1")

        mock_tm = Mock()
        mock_tool = Mock()
        mock_tm.load_tool.return_value = mock_tool
        monkeypatch.setattr(
            "application.agents.tool_executor.ToolManager", lambda config: mock_tm
        )

        tool_data = {
            "name": "api_tool",
            "config": {
                "actions": {
                    "create": {
                        "url": "https://api.example.com/items",
                        "method": "POST",
                        "body_content_type": "application/json",
                        "body_encoding_rules": {"encode_as": "json"},
                    }
                }
            },
        }

        result = executor._get_or_load_tool(
            tool_data, "t1", "create",
            headers={"Authorization": "Bearer tok"},
            query_params={"page": "1"},
        )
        assert result is mock_tool
        # Verify config was built with body_content_type
        call_args = mock_tm.load_tool.call_args
        tool_config = call_args[1].get("tool_config", call_args[0][1] if len(call_args[0]) > 1 else {})
        assert tool_config.get("body_content_type") == "application/json"
        assert tool_config.get("body_encoding_rules") == {"encode_as": "json"}
