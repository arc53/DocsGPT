"""Tests for application.agents.default_tools — the default chat tools."""

from __future__ import annotations

import uuid

import pytest

from application.agents import default_tools


@pytest.fixture(autouse=True)
def _reset_tool_cache():
    """Drop the module caches so settings overrides take effect."""
    def _clear():
        default_tools._tool_cache.clear()
        default_tools._ids_cache.clear()
        default_tools._id_set_cache.clear()
        default_tools._loaded_cache.clear()
        default_tools._builtin_ids_cache.clear()
        default_tools._builtin_id_set_cache.clear()
        default_tools._builtin_loaded_cache.clear()

    _clear()
    yield
    _clear()


# ---------------------------------------------------------------------------
# Synthetic ids
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSyntheticIds:
    def test_default_tool_id_is_a_valid_uuid(self):
        tool_id = default_tools.default_tool_id("memory")
        assert str(uuid.UUID(tool_id)) == tool_id

    def test_default_tool_id_is_deterministic(self):
        assert default_tools.default_tool_id("memory") == default_tools.default_tool_id(
            "memory"
        )

    def test_distinct_names_get_distinct_ids(self):
        assert default_tools.default_tool_id("memory") != default_tools.default_tool_id(
            "read_webpage"
        )

    def test_default_tool_ids_covers_configured_set(self, monkeypatch):
        monkeypatch.setattr(
            default_tools.settings, "DEFAULT_CHAT_TOOLS", ["memory", "scheduler"]
        )
        ids = default_tools.default_tool_ids()
        assert set(ids) == {"memory", "scheduler"}

    def test_default_tool_ids_is_memoized(self, monkeypatch):
        monkeypatch.setattr(
            default_tools.settings, "DEFAULT_CHAT_TOOLS", ["memory", "scheduler"]
        )
        first = default_tools.default_tool_ids()
        assert default_tools.default_tool_ids() is first

    def test_default_tool_ids_rebuilds_when_setting_changes(self, monkeypatch):
        monkeypatch.setattr(
            default_tools.settings, "DEFAULT_CHAT_TOOLS", ["memory"]
        )
        assert set(default_tools.default_tool_ids()) == {"memory"}
        monkeypatch.setattr(
            default_tools.settings, "DEFAULT_CHAT_TOOLS", ["memory", "read_webpage"]
        )
        assert set(default_tools.default_tool_ids()) == {"memory", "read_webpage"}

    def test_is_default_tool_id_recognises_synthetic_ids(self):
        assert default_tools.is_default_tool_id(
            default_tools.default_tool_id("memory")
        )

    def test_is_default_tool_id_rejects_random_uuid(self):
        assert not default_tools.is_default_tool_id(str(uuid.uuid4()))

    def test_is_default_tool_id_rejects_empty(self):
        assert not default_tools.is_default_tool_id(None)
        assert not default_tools.is_default_tool_id("")

    def test_name_for_id_round_trip(self):
        tool_id = default_tools.default_tool_id("read_webpage")
        assert default_tools.default_tool_name_for_id(tool_id) == "read_webpage"

    def test_name_for_id_unknown_returns_none(self):
        assert default_tools.default_tool_name_for_id(str(uuid.uuid4())) is None


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestValidation:
    def test_unimplemented_tool_is_skipped_not_an_error(self, monkeypatch, caplog):
        monkeypatch.setattr(
            default_tools.settings,
            "DEFAULT_CHAT_TOOLS",
            ["memory", "read_webpage", "future_tool_x"],
        )
        with caplog.at_level("DEBUG", logger="application.agents.default_tools"):
            usable = default_tools.validate_default_chat_tools()
        assert "future_tool_x" not in usable
        assert "memory" in usable and "read_webpage" in usable
        assert any(
            "future_tool_x" in rec.message and rec.levelname == "DEBUG"
            for rec in caplog.records
        )
        assert not any(rec.levelname == "WARNING" for rec in caplog.records)

    def test_loaded_default_tools_is_silent(self, monkeypatch, caplog):
        # Runs per request — must never log.
        monkeypatch.setattr(
            default_tools.settings,
            "DEFAULT_CHAT_TOOLS",
            ["memory", "read_webpage", "future_tool_x"],
        )
        with caplog.at_level("DEBUG", logger="application.agents.default_tools"):
            default_tools.loaded_default_tools()
        assert caplog.records == []

    def test_fk_bound_tool_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            default_tools.settings, "DEFAULT_CHAT_TOOLS", ["memory", "notes"]
        )
        with pytest.raises(ValueError, match="notes"):
            default_tools.validate_default_chat_tools()

    def test_fk_bound_todo_list_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            default_tools.settings, "DEFAULT_CHAT_TOOLS", ["memory", "todo_list"]
        )
        with pytest.raises(ValueError, match="todo_list"):
            default_tools.validate_default_chat_tools()

    def test_fully_unknown_name_is_skipped(self, monkeypatch):
        monkeypatch.setattr(
            default_tools.settings,
            "DEFAULT_CHAT_TOOLS",
            ["memory", "definitely_not_a_real_tool"],
        )
        usable = default_tools.validate_default_chat_tools()
        assert usable == ["memory"]

    def test_config_free_tools_pass(self, monkeypatch):
        monkeypatch.setattr(
            default_tools.settings, "DEFAULT_CHAT_TOOLS", ["memory", "read_webpage"]
        )
        assert default_tools.validate_default_chat_tools() == [
            "memory",
            "read_webpage",
        ]

    def test_scheduler_is_config_free(self, monkeypatch):
        # Dual-registration only works if scheduler passes the config-free
        # assertion — otherwise startup would reject DEFAULT_CHAT_TOOLS.
        monkeypatch.setattr(
            default_tools.settings, "DEFAULT_CHAT_TOOLS", ["scheduler"]
        )
        assert default_tools.validate_default_chat_tools() == ["scheduler"]

    def test_sandbox_tools_are_defaultable(self, monkeypatch):
        # code_executor / artifact_generator persist artifacts (no user_tools
        # FK) and have no REQUIRED config field, so they validate as defaults.
        monkeypatch.setattr(
            default_tools.settings,
            "DEFAULT_CHAT_TOOLS",
            ["code_executor", "artifact_generator"],
        )
        assert default_tools.validate_default_chat_tools() == [
            "code_executor",
            "artifact_generator",
        ]

    def test_shipped_defaults_validate(self):
        # The real shipped DEFAULT_CHAT_TOOLS must pass startup validation. Neither
        # sandbox-backed tool is shipped default-on (both need a running runner).
        usable = default_tools.validate_default_chat_tools()
        assert "code_executor" not in default_tools.settings.DEFAULT_CHAT_TOOLS
        assert "artifact_generator" not in default_tools.settings.DEFAULT_CHAT_TOOLS
        assert usable  # the remaining defaults (memory/read_webpage/scheduler) validate

    def test_sandbox_tools_not_shipped_defaults(self):
        # code_executor and artifact_generator both render/execute through the
        # sandbox runner, an opt-in service; a fresh deploy without a runner must
        # not advertise tools that hard-fail on every call. Enable per-agent.
        assert "code_executor" not in default_tools.settings.DEFAULT_CHAT_TOOLS
        assert "artifact_generator" not in default_tools.settings.DEFAULT_CHAT_TOOLS
        names = {r["name"] for r in default_tools.synthesized_default_tools(None)}
        assert "code_executor" not in names
        assert "artifact_generator" not in names

    def test_tool_with_required_config_is_rejected(self, monkeypatch):
        # ``brave`` needs an API key.
        monkeypatch.setattr(
            default_tools.settings, "DEFAULT_CHAT_TOOLS", ["memory", "brave"]
        )
        with pytest.raises(ValueError, match="brave"):
            default_tools.validate_default_chat_tools()

    def test_loaded_default_tools_filters_unimplemented(self, monkeypatch):
        monkeypatch.setattr(
            default_tools.settings,
            "DEFAULT_CHAT_TOOLS",
            ["memory", "read_webpage", "future_tool_x"],
        )
        assert default_tools.loaded_default_tools() == ["memory", "read_webpage"]


# ---------------------------------------------------------------------------
# Synthesized rows
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSynthesize:
    def test_synthesize_returns_row_shaped_entry(self):
        row = default_tools.synthesize_default_tool("memory")
        assert row is not None
        assert row["name"] == "memory"
        assert row["id"] == default_tools.default_tool_id("memory")
        assert row["id"] == row["_id"]
        assert row["config"] == {}
        assert row["config_requirements"] == {}
        assert row["status"] is True
        assert row["default"] is True
        assert isinstance(row["actions"], list) and row["actions"]

    def test_synthesize_unknown_tool_returns_none(self):
        assert default_tools.synthesize_default_tool("future_tool_x") is None
        assert default_tools.synthesize_default_tool("nope") is None

    def test_synthesize_includes_display_name(self):
        row = default_tools.synthesize_default_tool("read_webpage")
        assert row["display_name"]
        assert isinstance(row["description"], str)


# ---------------------------------------------------------------------------
# Opt-out list
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDisabledList:
    def test_none_user_doc_yields_empty(self):
        assert default_tools.disabled_default_tools(None) == []

    def test_missing_preferences_yields_empty(self):
        assert default_tools.disabled_default_tools({"user_id": "u"}) == []

    def test_reads_disabled_list(self):
        doc = {"tool_preferences": {"disabled_default_tools": ["read_webpage"]}}
        assert default_tools.disabled_default_tools(doc) == ["read_webpage"]

    def test_malformed_preferences_yields_empty(self):
        assert default_tools.disabled_default_tools(
            {"tool_preferences": "not-a-dict"}
        ) == []
        assert default_tools.disabled_default_tools(
            {"tool_preferences": {"disabled_default_tools": "x"}}
        ) == []


# ---------------------------------------------------------------------------
# Chat resolver — synthesized defaults
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSynthesizedDefaults:
    def test_all_defaults_present_when_nothing_disabled(self):
        rows = default_tools.synthesized_default_tools(None)
        names = {r["name"] for r in rows}
        assert names == set(default_tools.loaded_default_tools())

    def test_opt_out_removes_a_tool(self):
        doc = {"tool_preferences": {"disabled_default_tools": ["read_webpage"]}}
        rows = default_tools.synthesized_default_tools(doc)
        names = {r["name"] for r in rows}
        assert "read_webpage" not in names
        assert "memory" in names


# ---------------------------------------------------------------------------
# default_tools_for_management — the tool-management listing
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDefaultToolsForManagement:
    def test_lists_every_loaded_default(self):
        rows = default_tools.default_tools_for_management(None)
        assert {r["name"] for r in rows} == set(
            default_tools.loaded_default_tools()
        )

    def test_all_enabled_when_nothing_disabled(self):
        rows = default_tools.default_tools_for_management(None)
        assert all(r["status"] is True for r in rows)

    def test_disabled_default_still_listed_with_status_false(self):
        doc = {"tool_preferences": {"disabled_default_tools": ["read_webpage"]}}
        rows = default_tools.default_tools_for_management(doc)
        by_name = {r["name"]: r for r in rows}
        assert "read_webpage" in by_name
        assert by_name["read_webpage"]["status"] is False
        assert by_name["memory"]["status"] is True


# ---------------------------------------------------------------------------
# resolve_tool_by_id
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestResolveToolById:
    def test_synthetic_id_resolves_in_memory(self):
        tool_id = default_tools.default_tool_id("memory")
        row = default_tools.resolve_tool_by_id(tool_id, "user-x")
        assert row is not None
        assert row["name"] == "memory"
        assert row["id"] == tool_id

    def test_non_default_id_delegates_to_repo(self):
        sentinel = {"id": "real", "name": "brave"}

        class _Repo:
            def get_any(self, tool_id, user):
                assert user == "user-x"
                return sentinel

        row = default_tools.resolve_tool_by_id(
            str(uuid.uuid4()), "user-x", user_tools_repo=_Repo()
        )
        assert row is sentinel

    def test_non_default_id_without_repo_returns_none(self):
        assert default_tools.resolve_tool_by_id(str(uuid.uuid4()), "user-x") is None

    def test_builtin_agent_tool_id_resolves_in_memory(self):
        """Dual-registered scheduler resolves with BOTH ``default`` and
        ``builtin`` flags so either path can branch on the discriminator."""
        tool_id = default_tools.default_tool_id("scheduler")
        row = default_tools.resolve_tool_by_id(tool_id, "user-x")
        assert row is not None
        assert row["name"] == "scheduler"
        assert row["builtin"] is True
        assert row["default"] is True

    @pytest.mark.parametrize("name", ["code_executor", "artifact_generator"])
    def test_sandbox_tool_id_resolves_in_memory(self, name):
        # Both sandbox tools are opt-in per agent (removed from DEFAULT_CHAT_TOOLS)
        # but stay registered as agent-selectable builtins, so their synthetic id
        # still resolves to an in-memory row (loaded user-scoped at execute time)
        # — an agent that enabled one never silently loses it.
        assert name not in default_tools.settings.DEFAULT_CHAT_TOOLS
        assert name in default_tools.BUILTIN_AGENT_TOOLS
        tool_id = default_tools.default_tool_id(name)
        row = default_tools.resolve_tool_by_id(tool_id, "user-x")
        assert row is not None
        assert row["name"] == name
        assert row["id"] == tool_id
        assert row["builtin"] is True

    def test_read_document_builtin_id_resolves_workflow_only(self):
        # read_document is a workflow-only builtin: its synthetic id resolves
        # to a row flagged workflow_only for the frontend to gate visibility.
        tool_id = default_tools.default_tool_id("read_document")
        row = default_tools.resolve_tool_by_id(tool_id, "user-x")
        assert row is not None
        assert row["name"] == "read_document"
        assert row["builtin"] is True
        assert row["workflow_only"] is True


# ---------------------------------------------------------------------------
# Agent-selectable builtins (scheduler) — synthesized like defaults but
# hidden from agentless-chat synthesis and from /api/available_tools.
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestBuiltinAgentTools:
    def test_scheduler_is_a_builtin(self):
        assert "scheduler" in default_tools.BUILTIN_AGENT_TOOLS

    def test_scheduler_dual_registered_in_default_chat_tools(self):
        # Revised decision #8: scheduler is dual-registered as a default
        # chat tool (auto-on in agentless chats) AND a builtin agent tool
        # (opt-in via the agent picker). Both registries share the same
        # ``_DEFAULT_TOOL_NAMESPACE`` so the synthetic id is one stable uuid5.
        assert "scheduler" in default_tools.settings.DEFAULT_CHAT_TOOLS

    def test_dual_registration_produces_one_synthetic_id(self):
        # Same uuid5 namespace → same id whether reached via defaults or builtins.
        as_default = default_tools.default_tool_id("scheduler")
        assert default_tools.is_default_tool_id(as_default)
        assert default_tools.is_builtin_agent_tool_id(as_default)

    def test_builtin_id_is_recognised(self):
        tool_id = default_tools.default_tool_id("scheduler")
        assert default_tools.is_builtin_agent_tool_id(tool_id)
        assert default_tools.builtin_agent_tool_name_for_id(tool_id) == "scheduler"

    def test_synthesize_builtin_marks_flags_correctly(self):
        row = default_tools.synthesize_builtin_agent_tool("scheduler")
        assert row is not None
        assert row["name"] == "scheduler"
        assert row["default"] is False
        assert row["builtin"] is True
        assert isinstance(row["actions"], list) and row["actions"]

    def test_builtin_agent_tools_for_management_lists_scheduler(self):
        rows = default_tools.builtin_agent_tools_for_management()
        names = {r["name"] for r in rows}
        assert "scheduler" in names
        for row in rows:
            assert row["builtin"] is True
            assert row["default"] is False

    def test_synthesized_default_chat_now_includes_scheduler(self):
        # Revised decision #8: scheduler is dual-registered → it appears in
        # ``synthesized_default_tools`` so agentless chats can use it.
        rows = default_tools.synthesized_default_tools(None)
        assert "scheduler" in {r["name"] for r in rows}

    def test_read_document_is_a_builtin(self):
        assert "read_document" in default_tools.BUILTIN_AGENT_TOOLS
        assert "read_document" in default_tools.WORKFLOW_ONLY_BUILTINS

    def test_read_document_not_a_default_chat_tool(self):
        # read_document is a builtin only — never a default agentless chat tool.
        assert "read_document" not in default_tools.settings.DEFAULT_CHAT_TOOLS
        rows = default_tools.synthesized_default_tools(None)
        assert "read_document" not in {r["name"] for r in rows}

    def test_synthesize_read_document_flags_workflow_only(self):
        row = default_tools.synthesize_builtin_agent_tool("read_document")
        assert row is not None
        assert row["builtin"] is True
        assert row["default"] is False
        assert row["workflow_only"] is True
        assert isinstance(row["actions"], list) and row["actions"]

    def test_scheduler_builtin_is_not_workflow_only(self):
        row = default_tools.synthesize_builtin_agent_tool("scheduler")
        assert row["workflow_only"] is False

    def test_code_executor_is_agent_selectable_builtin(self):
        # Off by default (removed from DEFAULT_CHAT_TOOLS) but still reachable: a
        # non-workflow-only builtin, so an agent can enable it, it stays in the
        # picker, and its synthetic id resolves (no silent drop for agents that
        # already had it enabled).
        assert "code_executor" not in default_tools.settings.DEFAULT_CHAT_TOOLS
        assert "code_executor" in default_tools.BUILTIN_AGENT_TOOLS
        assert "code_executor" not in default_tools.WORKFLOW_ONLY_BUILTINS
        row = default_tools.synthesize_builtin_agent_tool("code_executor")
        assert row is not None
        assert row["builtin"] is True and row["default"] is False
        assert row["workflow_only"] is False
        names = {r["name"] for r in default_tools.builtin_agent_tools_for_management()}
        assert "code_executor" in names
        resolved = default_tools.resolve_tool_by_id(
            default_tools.default_tool_id("code_executor"), "user-1"
        )
        assert resolved is not None and resolved["name"] == "code_executor"

    def test_builtin_management_marks_workflow_only(self):
        rows = default_tools.builtin_agent_tools_for_management()
        by_name = {r["name"]: r for r in rows}
        assert by_name["read_document"]["workflow_only"] is True
        assert by_name["scheduler"]["workflow_only"] is False


# ---------------------------------------------------------------------------
# _FK_BOUND_TOOLS — schema introspection guard against rot
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestFkBoundToolsIsInSync:
    # Table name -> tool module name (``application/agents/tools/<name>``).
    _TABLE_TO_TOOL = {
        "notes": "notes",
        "todos": "todo_list",
    }

    def test_fk_bound_tools_matches_metadata(self):
        from application.storage.db.models import metadata

        fk_bound_tables = set()
        for tbl in metadata.tables.values():
            tool_id_col = tbl.columns.get("tool_id")
            if tool_id_col is None:
                continue
            for fk in tool_id_col.foreign_keys:
                if fk.target_fullname == "user_tools.id":
                    fk_bound_tables.add(tbl.name)
                    break

        unmapped = fk_bound_tables - set(self._TABLE_TO_TOOL)
        assert not unmapped, (
            f"New FK-bound table(s) without a tool mapping: {sorted(unmapped)}. "
            "Add an entry to _TABLE_TO_TOOL here AND to "
            "application.agents.default_tools._FK_BOUND_TOOLS."
        )
        derived_names = {
            self._TABLE_TO_TOOL[name] for name in fk_bound_tables
        }
        assert derived_names == set(default_tools._FK_BOUND_TOOLS), (
            "_FK_BOUND_TOOLS is out of sync with schema-derived names: "
            f"derived={sorted(derived_names)} "
            f"declared={sorted(default_tools._FK_BOUND_TOOLS)}"
        )
