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
        assert executor.agent_id is None
        assert executor.tool_calls == []
        assert executor._loaded_tools == {}
        assert executor.conversation_id is None

    def test_init_with_params(self):
        executor = ToolExecutor(
            user_api_key="key",
            user="alice",
            decoded_token={"sub": "alice"},
            agent_id="agent-1",
        )
        assert executor.user_api_key == "key"
        assert executor.user == "alice"
        assert executor.agent_id == "agent-1"


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

    def test_agentless_chat_synthesizes_defaults(self, pg_conn, monkeypatch):
        from application.agents.default_tools import loaded_default_tools
        from application.storage.db.repositories.user_tools import UserToolsRepository

        UserToolsRepository(pg_conn).create(
            user_id="alice", name="tool1", status=True
        )
        self._patch_conn(monkeypatch, pg_conn)

        executor = ToolExecutor(user="alice")
        tools = executor.get_tools()
        assert isinstance(tools, dict)
        assert len(tools) == 1 + len(loaded_default_tools())
        names = {t["name"] for t in tools.values()}
        assert "tool1" in names
        assert "memory" in names

    def test_agent_bound_chat_via_user_path_excludes_defaults(
        self, pg_conn, monkeypatch
    ):
        """``agent_id`` forces ``agents.tools``-only; no defaults synthesized."""
        from application.agents.default_tools import loaded_default_tools
        from application.storage.db.repositories.user_tools import UserToolsRepository

        UserToolsRepository(pg_conn).create(
            user_id="alice", name="tool1", status=True
        )
        self._patch_conn(monkeypatch, pg_conn)

        executor = ToolExecutor(user="alice", agent_id="agent-x")
        tools = executor.get_tools()
        names = {t["name"] for t in tools.values()}
        assert "tool1" in names
        assert not (set(loaded_default_tools()) & names)

    def test_get_tools_defaults_to_local(self, pg_conn, monkeypatch):
        from application.agents.default_tools import loaded_default_tools

        self._patch_conn(monkeypatch, pg_conn)

        executor = ToolExecutor()
        tools = executor.get_tools()
        assert isinstance(tools, dict)
        assert len(tools) == len(loaded_default_tools())
        assert {t["name"] for t in tools.values()} == set(loaded_default_tools())

    def test_api_key_path_excludes_defaults(self, pg_conn, monkeypatch):
        """Agent-bound resolution returns exactly ``agents.tools``."""
        from application.agents.default_tools import loaded_default_tools
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.user_tools import UserToolsRepository

        tool = UserToolsRepository(pg_conn).create(user_id="alice", name="tool1")
        AgentsRepository(pg_conn).create(
            user_id="alice",
            name="a",
            status="active",
            key="key-agentbound",
            tools=[str(tool["id"])],
        )
        self._patch_conn(monkeypatch, pg_conn)

        executor = ToolExecutor(user_api_key="key-agentbound", user="alice")
        tools = executor.get_tools()
        names = {t["name"] for t in tools.values()}
        assert names == {"tool1"}
        assert not (set(loaded_default_tools()) & names)

    def test_api_key_path_empty_agent_tools_gets_nothing(
        self, pg_conn, monkeypatch
    ):
        """Empty ``agents.tools`` invoked via API key yields no tools."""
        from application.storage.db.repositories.agents import AgentsRepository

        AgentsRepository(pg_conn).create(
            user_id="bob",
            name="a",
            status="active",
            key="key-empty",
            tools=[],
        )
        self._patch_conn(monkeypatch, pg_conn)

        executor = ToolExecutor(user_api_key="key-empty", user="bob")
        assert executor.get_tools() == {}

    def test_api_key_path_only_synthesizes_author_added_defaults(
        self, pg_conn, monkeypatch
    ):
        """Only ``read_webpage`` in ``agents.tools`` -> exactly that; no other defaults bolted on."""
        from application.agents.default_tools import default_tool_id
        from application.storage.db.repositories.agents import AgentsRepository

        read_webpage_id = default_tool_id("read_webpage")
        memory_id = default_tool_id("memory")
        AgentsRepository(pg_conn).create(
            user_id="erin",
            name="a",
            status="active",
            key="key-only-read",
            tools=[read_webpage_id],
        )
        self._patch_conn(monkeypatch, pg_conn)

        executor = ToolExecutor(
            user_api_key="key-only-read", user="erin", agent_id="erin-agent"
        )
        tools = executor.get_tools()
        assert set(tools) == {read_webpage_id}
        assert tools[read_webpage_id]["name"] == "read_webpage"
        assert memory_id not in tools
        assert "memory" not in {t["name"] for t in tools.values()}

    def test_explicit_default_on_agent_resolves(
        self, pg_conn, monkeypatch
    ):
        """A default tool added explicitly to ``agents.tools`` resolves for every caller."""
        from application.agents.default_tools import default_tool_id
        from application.storage.db.repositories.agents import AgentsRepository

        memory_id = default_tool_id("memory")
        AgentsRepository(pg_conn).create(
            user_id="erin",
            name="a",
            status="active",
            key="key-explicit-default",
            tools=[memory_id],
        )
        self._patch_conn(monkeypatch, pg_conn)

        executor = ToolExecutor(
            user_api_key="key-explicit-default", user="erin"
        )
        tools = executor.get_tools()
        assert set(tools) == {memory_id}
        assert tools[memory_id]["name"] == "memory"

    def test_no_dedup_between_explicit_and_default_memory(
        self, pg_conn, monkeypatch
    ):
        from application.storage.db.repositories.user_tools import UserToolsRepository

        # Explicit ``memory`` row and the default ``memory`` coexist (separate stores).
        UserToolsRepository(pg_conn).create(
            user_id="dave", name="memory", status=True
        )
        self._patch_conn(monkeypatch, pg_conn)

        executor = ToolExecutor(user="dave")
        tools = executor.get_tools()
        memory_entries = [t for t in tools.values() if t["name"] == "memory"]
        assert len(memory_entries) == 2
        ids = {t["id"] for t in memory_entries}
        assert len(ids) == 2


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

    def test_prepare_tools_duplicate_names_get_tool_prefixes(self):
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
        assert "tool_a_search" in names
        assert "tool_b_search" in names
        assert executor._name_to_tool["tool_a_search"] == ("t1", "search")
        assert executor._name_to_tool["tool_b_search"] == ("t2", "search")

    def test_prepare_tools_same_named_tools_fall_back_to_numbers(self):
        """Two tools with the same name (e.g. two MCP rows) still get unique names."""
        executor = ToolExecutor()
        tools_dict = {
            "t1": {
                "name": "mcp",
                "actions": [
                    {"name": "search", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
            "t2": {
                "name": "mcp",
                "actions": [
                    {"name": "search", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
        }
        result = executor.prepare_tools_for_llm(tools_dict)
        names = [r["function"]["name"] for r in result]
        assert "mcp_search" in names
        assert "mcp_search_1" in names
        assert executor._name_to_tool["mcp_search"][1] == "search"
        assert executor._name_to_tool["mcp_search_1"][1] == "search"

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

    def test_prepare_tools_prefixed_names_clamped_to_64_chars(self):
        """Prefixed names must fit the 64-char provider function-name limit."""
        executor = ToolExecutor()
        name_a = "server_" + "x" * 60
        name_b = "server_" + "x" * 60 + "_b"  # same first 64 chars as name_a
        tools_dict = {
            "t1": {
                "name": name_a,
                "actions": [
                    {"name": "search_documents_in_collection", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
            "t2": {
                "name": name_b,
                "actions": [
                    {"name": "search_documents_in_collection", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
        }
        result = executor.prepare_tools_for_llm(tools_dict)
        names = [r["function"]["name"] for r in result]
        assert all(len(n) <= 64 for n in names)
        assert len(set(names)) == 2
        # Routing still resolves each clamped name to its original action.
        assert {executor._name_to_tool[n] for n in names} == {
            ("t1", "search_documents_in_collection"),
            ("t2", "search_documents_in_collection"),
        }

    def test_prepare_tools_long_unique_name_clamped(self):
        """A unique action name over the limit is truncated, not passed through."""
        executor = ToolExecutor()
        long_action = "fetch_" + "y" * 70
        tools_dict = {
            "t1": {
                "name": "tool_a",
                "actions": [
                    {"name": long_action, "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
        }
        result = executor.prepare_tools_for_llm(tools_dict)
        names = [r["function"]["name"] for r in result]
        assert names == [long_action[:64]]
        assert executor._name_to_tool[long_action[:64]] == ("t1", long_action)

    def test_prepare_tools_prefix_skips_collision_with_unique_name(self):
        """A prefixed candidate must not steal another action's unique name."""
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
                    {"name": "tool_a_foo", "description": "D", "active": True, "parameters": {"properties": {}}},
                ],
            },
        }
        result = executor.prepare_tools_for_llm(tools_dict)
        names = [r["function"]["name"] for r in result]
        # tool_a_foo is taken by the unique action, so t1's duplicate
        # falls back to a numbered variant of its prefixed name.
        assert "tool_a_foo" in names  # The unique action
        assert "tool_a_foo_1" in names
        assert "tool_b_foo" in names
        assert executor._name_to_tool["tool_a_foo"] == ("t3", "tool_a_foo")
        assert executor._name_to_tool["tool_a_foo_1"] == ("t1", "foo")

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
class TestCheckPauseRemoteDevice:
    """The gate must consult the live ``RemoteDeviceTool`` decision for
    ``remote_device`` so ``approval_mode`` changes after pair time and
    per-command heuristics (denylist, sticky) are respected.
    """

    def _make_call(self, name="run_command", call_id="c1", command="ls -la /tmp"):
        import json

        call = Mock()
        call.name = name
        call.id = call_id
        call.arguments = json.dumps({"command": command})
        call.thought_signature = None
        return call

    def _tools_dict(self, *, device_id="dev_abc"):
        return {
            "rd0": {
                "id": "rd0",
                "name": "remote_device",
                "config": {"device_id": device_id},
                "actions": [
                    {
                        "name": "run_command",
                        "description": "Execute on device",
                        "active": True,
                        "require_approval": False,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "filled_by_llm": True,
                                    "value": "",
                                },
                            },
                            "required": ["command"],
                        },
                    }
                ],
            }
        }

    def _patch_device(self, monkeypatch, device):
        """Stub ``RemoteDeviceTool._load_device`` to return ``device``."""
        from application.agents.tools import remote_device

        monkeypatch.setattr(
            remote_device.RemoteDeviceTool,
            "_load_device",
            lambda self: device,
        )

    def _patch_sticky(self, monkeypatch, patterns):
        """Stub the sticky lookup to match any normalized pattern in ``patterns``."""
        from application.agents.tools import remote_device

        monkeypatch.setattr(
            remote_device,
            "normalize_command",
            lambda cmd: cmd.split()[0] + " *" if cmd else "",
        )
        captured = {"patterns": set(patterns)}

        class _StubRepo:
            def __init__(self, conn):
                pass

            def has_pattern(self, device_id, user_id, pattern):
                return pattern in captured["patterns"]

        monkeypatch.setattr(
            remote_device,
            "DeviceAutoApprovePatternsRepository",
            _StubRepo,
        )

        class _StubConn:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(remote_device, "db_readonly", lambda: _StubConn())

    def test_full_non_deny_no_pause(self, monkeypatch):
        """``full`` + a non-denylisted command auto-approves."""
        executor = ToolExecutor(user="alice")
        self._patch_device(
            monkeypatch,
            {
                "id": "dev_abc",
                "approval_mode": "full",
                "status": "active",
            },
        )
        self._patch_sticky(monkeypatch, set())

        tools_dict = self._tools_dict()
        executor.prepare_tools_for_llm(tools_dict)
        call = self._make_call(command="whoami")
        assert executor.check_pause(tools_dict, call, "OpenAILLM") is None

    def test_full_writing_command_no_pause(self, monkeypatch):
        """``full`` auto-approves writes too (only the denylist stops it)."""
        executor = ToolExecutor(user="alice")
        self._patch_device(
            monkeypatch,
            {
                "id": "dev_abc",
                "approval_mode": "full",
                "status": "active",
            },
        )
        self._patch_sticky(monkeypatch, set())

        tools_dict = self._tools_dict()
        executor.prepare_tools_for_llm(tools_dict)
        call = self._make_call(command="rm /tmp/foo")
        assert executor.check_pause(tools_dict, call, "OpenAILLM") is None

    def test_full_denylist_forces_pause(self, monkeypatch):
        """``full`` + a denylisted command still pauses (forced prompt)."""
        executor = ToolExecutor(user="alice")
        self._patch_device(
            monkeypatch,
            {
                "id": "dev_abc",
                "approval_mode": "full",
                "status": "active",
            },
        )
        self._patch_sticky(monkeypatch, set())

        tools_dict = self._tools_dict()
        executor.prepare_tools_for_llm(tools_dict)
        call = self._make_call(command="rm -rf /")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")
        assert result is not None
        assert result["pause_type"] == "awaiting_approval"

    def test_ask_mode_pauses(self, monkeypatch):
        """``ask`` + any command pauses by default."""
        executor = ToolExecutor(user="alice")
        self._patch_device(
            monkeypatch,
            {
                "id": "dev_abc",
                "approval_mode": "ask",
                "status": "active",
            },
        )
        self._patch_sticky(monkeypatch, set())

        tools_dict = self._tools_dict()
        executor.prepare_tools_for_llm(tools_dict)
        call = self._make_call(command="ls -la /tmp")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")
        assert result is not None
        assert result["pause_type"] == "awaiting_approval"

    def test_ask_mode_sticky_match_no_pause(self, monkeypatch):
        """``ask`` + a command matching a stored sticky pattern auto-approves."""
        executor = ToolExecutor(user="alice")
        self._patch_device(
            monkeypatch,
            {
                "id": "dev_abc",
                "approval_mode": "ask",
                "status": "active",
            },
        )
        # The stub normalizer turns ``ls -la /tmp`` into ``ls *``.
        self._patch_sticky(monkeypatch, {"ls *"})

        tools_dict = self._tools_dict()
        executor.prepare_tools_for_llm(tools_dict)
        call = self._make_call(command="ls -la /tmp")
        assert executor.check_pause(tools_dict, call, "OpenAILLM") is None


@pytest.mark.unit
class TestCheckPauseRemoteDeviceHeadless:
    """Headless gating for ``remote_device``.

    A denylist-forced prompt must NOT be bypassed by the run's
    ``tool_allowlist`` — otherwise a scheduled/headless run with the device
    allowlisted would auto-execute even a denylisted command. Normal
    (non-forced) approvals keep the allowlist bypass.
    """

    def _make_call(self, name="run_command", call_id="c1", command="whoami"):
        import json

        call = Mock()
        call.name = name
        call.id = call_id
        call.arguments = json.dumps({"command": command})
        call.thought_signature = None
        return call

    def _tools_dict(self, *, device_id="dev_abc"):
        return {
            "rd0": {
                "id": "rd0",
                "name": "remote_device",
                "config": {"device_id": device_id},
                "actions": [
                    {
                        "name": "run_command",
                        "description": "Execute on device",
                        "active": True,
                        "require_approval": False,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "filled_by_llm": True,
                                    "value": "",
                                },
                            },
                            "required": ["command"],
                        },
                    }
                ],
            }
        }

    def _patch_device(self, monkeypatch, device):
        from application.agents.tools import remote_device

        monkeypatch.setattr(
            remote_device.RemoteDeviceTool,
            "_load_device",
            lambda self: device,
        )

    def _patch_sticky(self, monkeypatch, patterns):
        from application.agents.tools import remote_device

        monkeypatch.setattr(
            remote_device,
            "normalize_command",
            lambda cmd: cmd.split()[0] + " *" if cmd else "",
        )
        captured = {"patterns": set(patterns)}

        class _StubRepo:
            def __init__(self, conn):
                pass

            def has_pattern(self, device_id, user_id, pattern):
                return pattern in captured["patterns"]

        monkeypatch.setattr(
            remote_device, "DeviceAutoApprovePatternsRepository", _StubRepo
        )

        class _StubConn:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(remote_device, "db_readonly", lambda: _StubConn())

    def test_headless_allowlisted_denylisted_command_denied(self, monkeypatch):
        """Device allowlisted, but ``rm -rf /`` is a forced prompt -> denied."""
        executor = ToolExecutor(
            user="alice", headless=True, tool_allowlist={"rd0"}
        )
        self._patch_device(
            monkeypatch,
            {"id": "dev_abc", "approval_mode": "full", "status": "active"},
        )
        self._patch_sticky(monkeypatch, set())

        tools_dict = self._tools_dict()
        executor.prepare_tools_for_llm(tools_dict)
        call = self._make_call(command="rm -rf /")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")
        assert result is not None
        assert result["pause_type"] == "headless_denied"
        assert result["error_type"] == "tool_not_allowed"

    def test_headless_allowlisted_normal_command_executes(self, monkeypatch):
        """Device allowlisted + a normal command in ``full`` -> executes."""
        executor = ToolExecutor(
            user="alice", headless=True, tool_allowlist={"rd0"}
        )
        self._patch_device(
            monkeypatch,
            {"id": "dev_abc", "approval_mode": "full", "status": "active"},
        )
        self._patch_sticky(monkeypatch, set())

        tools_dict = self._tools_dict()
        executor.prepare_tools_for_llm(tools_dict)
        call = self._make_call(command="whoami")
        assert executor.check_pause(tools_dict, call, "OpenAILLM") is None

    def test_headless_not_allowlisted_denied(self, monkeypatch):
        """Without the allowlist, an ask-mode command is denied headless."""
        executor = ToolExecutor(user="alice", headless=True, tool_allowlist=set())
        self._patch_device(
            monkeypatch,
            {"id": "dev_abc", "approval_mode": "ask", "status": "active"},
        )
        self._patch_sticky(monkeypatch, set())

        tools_dict = self._tools_dict()
        executor.prepare_tools_for_llm(tools_dict)
        call = self._make_call(command="ls -la /tmp")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")
        assert result is not None
        assert result["pause_type"] == "headless_denied"

    def test_headless_allowlisted_ask_mode_normal_executes(self, monkeypatch):
        """ask-mode + allowlisted + non-denylisted -> bypass allowed."""
        executor = ToolExecutor(
            user="alice", headless=True, tool_allowlist={"rd0"}
        )
        self._patch_device(
            monkeypatch,
            {"id": "dev_abc", "approval_mode": "ask", "status": "active"},
        )
        self._patch_sticky(monkeypatch, set())

        tools_dict = self._tools_dict()
        executor.prepare_tools_for_llm(tools_dict)
        call = self._make_call(command="ls -la /tmp")
        # Not denylist-forced, so the allowlist bypass applies.
        assert executor.check_pause(tools_dict, call, "OpenAILLM") is None


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

    def test_get_or_load_tool_decrypts_with_tool_owner(self, monkeypatch):
        """Team-shared tool: credentials decrypt with the OWNER's sub, not the
        invoker's (teams OQ2 — delegation). The tool row carries user_id=owner
        while the executor runs as a different member."""
        executor = ToolExecutor(user="member_bob")

        mock_tm = Mock()
        mock_tm.load_tool.return_value = Mock()
        monkeypatch.setattr(
            "application.agents.tool_executor.ToolManager", lambda config: mock_tm
        )
        captured = {}

        def _fake_decrypt(creds, user):
            captured["user"] = user
            return {"api_key": "owner_secret"}

        monkeypatch.setattr(
            "application.agents.tool_executor.decrypt_credentials", _fake_decrypt
        )

        tool_data = {
            "id": "00000000-0000-0000-0000-000000000009",
            "name": "custom_tool",
            "user_id": "owner_alice",
            "config": {"encrypted_credentials": "blob"},
        }
        executor._get_or_load_tool(tool_data, "t9", "act")
        # Decrypted under the tool owner, NOT the invoking member.
        assert captured["user"] == "owner_alice"

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
