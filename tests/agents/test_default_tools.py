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
        default_tools._loaded_cache.clear()

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
            ["memory", "read_webpage", "scheduler"],
        )
        with caplog.at_level("DEBUG", logger="application.agents.default_tools"):
            usable = default_tools.validate_default_chat_tools()
        assert "scheduler" not in usable
        assert "memory" in usable and "read_webpage" in usable
        assert any(
            "scheduler" in rec.message and rec.levelname == "DEBUG"
            for rec in caplog.records
        )
        assert not any(rec.levelname == "WARNING" for rec in caplog.records)

    def test_loaded_default_tools_is_silent(self, monkeypatch, caplog):
        # Runs per request — must never log.
        monkeypatch.setattr(
            default_tools.settings,
            "DEFAULT_CHAT_TOOLS",
            ["memory", "read_webpage", "scheduler"],
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
            ["memory", "read_webpage", "scheduler"],
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
        assert default_tools.synthesize_default_tool("scheduler") is None
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

    def test_unimplemented_default_resolves_to_none(self):
        tool_id = default_tools.default_tool_id("scheduler")
        assert default_tools.resolve_tool_by_id(tool_id, "user-x") is None


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
