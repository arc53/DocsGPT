"""Tests for InternalSearchTool and its helper functions."""

from unittest.mock import Mock, patch

import pytest
from application.agents.tools.internal_search import (
    INTERNAL_TOOL_ID,
    InternalSearchTool,
    add_internal_search_tool,
    build_internal_tool_config,
    build_internal_tool_entry,
)


@pytest.mark.unit
class TestInternalSearchToolSearch:

    def _make_tool(self, **config_overrides):
        config = {"source": {}, "retriever_name": "classic", "chunks": 2}
        config.update(config_overrides)
        return InternalSearchTool(config)

    def test_search_no_query_returns_error(self):
        tool = self._make_tool()
        result = tool.execute_action("search", query="")
        assert "required" in result.lower()

    def test_search_returns_formatted_docs(self):
        tool = self._make_tool()
        mock_retriever = Mock()
        mock_retriever.search.return_value = [
            {"text": "Hello world", "title": "Doc1", "source": "test", "filename": "doc1.md"},
        ]
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="hello")
        assert "doc1.md" in result
        assert "Hello world" in result
        assert len(tool.retrieved_docs) == 1

    def test_search_no_results(self):
        tool = self._make_tool()
        mock_retriever = Mock()
        mock_retriever.search.return_value = []
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="nonexistent")
        assert "No documents found" in result

    def test_search_accumulates_docs(self):
        tool = self._make_tool()
        mock_retriever = Mock()
        tool._retriever = mock_retriever

        mock_retriever.search.return_value = [
            {"text": "A", "title": "D1", "source": "s1"},
        ]
        tool.execute_action("search", query="first")

        mock_retriever.search.return_value = [
            {"text": "B", "title": "D2", "source": "s2"},
        ]
        tool.execute_action("search", query="second")

        assert len(tool.retrieved_docs) == 2

    def test_search_deduplicates_docs(self):
        tool = self._make_tool()
        doc = {"text": "Same", "title": "Same", "source": "same"}
        mock_retriever = Mock()
        mock_retriever.search.return_value = [doc]
        tool._retriever = mock_retriever

        tool.execute_action("search", query="q1")
        tool.execute_action("search", query="q2")

        assert len(tool.retrieved_docs) == 1

    def test_search_with_path_filter(self):
        tool = self._make_tool()
        mock_retriever = Mock()
        mock_retriever.search.return_value = [
            {"text": "A", "title": "T", "source": "src/main.py", "filename": "main.py"},
            {"text": "B", "title": "T", "source": "docs/readme.md", "filename": "readme.md"},
        ]
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="code", path_filter="src/")
        assert "main.py" in result
        assert "readme.md" not in result

    def test_search_path_filter_no_match(self):
        tool = self._make_tool()
        mock_retriever = Mock()
        mock_retriever.search.return_value = [
            {"text": "A", "title": "T", "source": "other/file.txt"},
        ]
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="code", path_filter="src/")
        assert "No documents found" in result

    def test_search_retriever_error(self):
        tool = self._make_tool()
        mock_retriever = Mock()
        mock_retriever.search.side_effect = Exception("Connection error")
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="test")
        assert "failed" in result.lower() or "error" in result.lower()

    def test_unknown_action(self):
        tool = self._make_tool()
        result = tool.execute_action("nonexistent")
        assert "Unknown action" in result


@pytest.mark.unit
class TestInternalSearchToolListFiles:

    def test_list_files_no_structure(self):
        tool = InternalSearchTool({"source": {}})
        tool._dir_structure_loaded = True
        tool._directory_structure = None

        result = tool.execute_action("list_files")
        assert "No file structure" in result

    def test_list_files_root(self):
        tool = InternalSearchTool({"source": {}})
        tool._dir_structure_loaded = True
        tool._directory_structure = {
            "src": {"main.py": {}},
            "README.md": {"type": "md", "token_count": 100},
        }

        result = tool.execute_action("list_files")
        assert "src/" in result
        assert "README.md" in result

    def test_list_files_nested_path(self):
        tool = InternalSearchTool({"source": {}})
        tool._dir_structure_loaded = True
        tool._directory_structure = {
            "src": {
                "utils": {"helper.py": {}},
            },
        }

        result = tool.execute_action("list_files", path="src")
        assert "utils/" in result

    def test_list_files_invalid_path(self):
        tool = InternalSearchTool({"source": {}})
        tool._dir_structure_loaded = True
        tool._directory_structure = {"src": {}}

        result = tool.execute_action("list_files", path="nonexistent")
        assert "not found" in result


@pytest.mark.unit
class TestInternalSearchToolMetadata:

    def test_actions_without_directory_structure(self):
        tool = InternalSearchTool({"has_directory_structure": False})
        meta = tool.get_actions_metadata()

        action_names = [a["name"] for a in meta]
        assert "search" in action_names
        assert "list_files" not in action_names

        # search should not have path_filter
        search = meta[0]
        assert "path_filter" not in search["parameters"]["properties"]

    def test_actions_with_directory_structure(self):
        tool = InternalSearchTool({"has_directory_structure": True})
        meta = tool.get_actions_metadata()

        action_names = [a["name"] for a in meta]
        assert "search" in action_names
        assert "list_files" in action_names

        # search should have path_filter
        search = next(a for a in meta if a["name"] == "search")
        assert "path_filter" in search["parameters"]["properties"]


@pytest.mark.unit
class TestBuildHelpers:

    def test_build_entry_without_directory_structure(self):
        entry = build_internal_tool_entry(has_directory_structure=False)
        assert entry["name"] == "internal_search"
        action_names = [a["name"] for a in entry["actions"]]
        assert "search" in action_names
        assert "list_files" not in action_names

    def test_build_entry_with_directory_structure(self):
        entry = build_internal_tool_entry(has_directory_structure=True)
        action_names = [a["name"] for a in entry["actions"]]
        assert "list_files" in action_names

    def test_build_config(self):
        config = build_internal_tool_config(
            source={"active_docs": ["abc"]},
            retriever_name="semantic",
            chunks=4,
        )
        assert config["source"] == {"active_docs": ["abc"]}
        assert config["retriever_name"] == "semantic"
        assert config["chunks"] == 4

    def test_internal_tool_id(self):
        assert INTERNAL_TOOL_ID == "internal"

    def test_add_internal_search_tool_with_sources(self):
        tools_dict = {}
        retriever_config = {
            "source": {"active_docs": ["abc"]},
            "retriever_name": "classic",
            "chunks": 2,
            "model_id": "gpt-4",
            "llm_name": "openai",
            "api_key": "key",
        }

        with patch(
            "application.agents.tools.internal_search.sources_have_directory_structure",
            return_value=False,
        ):
            add_internal_search_tool(tools_dict, retriever_config)

        assert INTERNAL_TOOL_ID in tools_dict
        assert tools_dict[INTERNAL_TOOL_ID]["name"] == "internal_search"
        assert "config" in tools_dict[INTERNAL_TOOL_ID]

    def test_add_internal_search_tool_no_sources(self):
        tools_dict = {}
        retriever_config = {"source": {}}

        add_internal_search_tool(tools_dict, retriever_config)

        assert INTERNAL_TOOL_ID not in tools_dict

    def test_add_internal_search_tool_empty_config(self):
        tools_dict = {}
        add_internal_search_tool(tools_dict, {})
        assert INTERNAL_TOOL_ID not in tools_dict
