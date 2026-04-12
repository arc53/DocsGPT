"""Comprehensive tests for application/agents/tools/internal_search.py

Covers: InternalSearchTool (search, list_files, path_filter, error handling,
directory structure loading), build helpers, add_internal_search_tool,
sources_have_directory_structure.
"""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from application.agents.tools.internal_search import (
    INTERNAL_TOOL_ENTRY,
    INTERNAL_TOOL_ID,
    InternalSearchTool,
    add_internal_search_tool,
    build_internal_tool_config,
    build_internal_tool_entry,
    sources_have_directory_structure,
)


# =====================================================================
# InternalSearchTool - Search
# =====================================================================


def _make_tool(**config_overrides):
    config = {"source": {}, "retriever_name": "classic", "chunks": 2}
    config.update(config_overrides)
    return InternalSearchTool(config)


@pytest.mark.unit
class TestInternalSearchToolSearch:

    def test_search_no_query_returns_error(self):
        tool = _make_tool()
        result = tool.execute_action("search", query="")
        assert "required" in result.lower()

    def test_search_returns_formatted_docs(self):
        tool = _make_tool()
        mock_retriever = Mock()
        mock_retriever.search.return_value = [
            {
                "text": "Hello world",
                "title": "Doc1",
                "source": "test",
                "filename": "doc1.md",
            },
        ]
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="hello")
        assert "doc1.md" in result
        assert "Hello world" in result
        assert len(tool.retrieved_docs) == 1

    def test_search_no_results(self):
        tool = _make_tool()
        mock_retriever = Mock()
        mock_retriever.search.return_value = []
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="nonexistent")
        assert "No documents found" in result

    def test_search_accumulates_docs(self):
        tool = _make_tool()
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
        tool = _make_tool()
        doc = {"text": "Same", "title": "Same", "source": "same"}
        mock_retriever = Mock()
        mock_retriever.search.return_value = [doc]
        tool._retriever = mock_retriever

        tool.execute_action("search", query="q1")
        tool.execute_action("search", query="q2")

        assert len(tool.retrieved_docs) == 1

    def test_search_with_path_filter(self):
        tool = _make_tool()
        mock_retriever = Mock()
        mock_retriever.search.return_value = [
            {"text": "A", "title": "T", "source": "src/main.py", "filename": "main.py"},
            {"text": "B", "title": "T", "source": "docs/readme.md", "filename": "readme.md"},
        ]
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="code", path_filter="src/")
        assert "main.py" in result
        assert "readme.md" not in result

    def test_search_path_filter_matches_title(self):
        tool = _make_tool()
        mock_retriever = Mock()
        mock_retriever.search.return_value = [
            {"text": "A", "title": "src/main.py", "source": "other", "filename": ""},
        ]
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="code", path_filter="src/main")
        assert "src/main.py" in result

    def test_search_path_filter_no_match(self):
        tool = _make_tool()
        mock_retriever = Mock()
        mock_retriever.search.return_value = [
            {"text": "A", "title": "T", "source": "other/file.txt"},
        ]
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="code", path_filter="src/")
        assert "No documents found" in result

    def test_search_retriever_error(self):
        tool = _make_tool()
        mock_retriever = Mock()
        mock_retriever.search.side_effect = Exception("Connection error")
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="test")
        assert "failed" in result.lower() or "error" in result.lower()

    def test_unknown_action(self):
        tool = _make_tool()
        result = tool.execute_action("nonexistent")
        assert "Unknown action" in result

    def test_search_formats_with_separator(self):
        tool = _make_tool()
        mock_retriever = Mock()
        mock_retriever.search.return_value = [
            {"text": "A", "title": "D1", "source": "s1", "filename": "f1.md"},
            {"text": "B", "title": "D2", "source": "s2", "filename": "f2.md"},
        ]
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="test")
        assert "---" in result
        assert "[1]" in result
        assert "[2]" in result

    def test_search_uses_title_when_no_filename(self):
        tool = _make_tool()
        mock_retriever = Mock()
        mock_retriever.search.return_value = [
            {"text": "Content", "title": "My Title", "source": "src", "filename": ""},
        ]
        tool._retriever = mock_retriever

        result = tool.execute_action("search", query="q")
        assert "My Title" in result


# =====================================================================
# InternalSearchTool - List Files
# =====================================================================


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

    def test_list_files_empty_directory(self):
        tool = InternalSearchTool({"source": {}})
        tool._dir_structure_loaded = True
        tool._directory_structure = {"empty_dir": {}}

        result = tool.execute_action("list_files", path="empty_dir")
        assert "(empty)" in result

    def test_list_files_file_with_metadata(self):
        tool = InternalSearchTool({"source": {}})
        tool._dir_structure_loaded = True
        tool._directory_structure = {
            "data.csv": {
                "type": "text/csv",
                "size_bytes": 1024,
                "token_count": 500,
            },
        }

        result = tool.execute_action("list_files")
        assert "data.csv" in result
        assert "500 tokens" in result
        assert "text/csv" in result

    def test_list_files_file_is_not_directory(self):
        tool = InternalSearchTool({"source": {}})
        tool._dir_structure_loaded = True
        tool._directory_structure = {
            "src": {
                "main.py": "plain_file_value",
            },
        }

        result = tool.execute_action("list_files", path="src/main.py")
        assert "is a file" in result

    def test_list_files_deep_nested_path_with_slashes(self):
        tool = InternalSearchTool({"source": {}})
        tool._dir_structure_loaded = True
        tool._directory_structure = {
            "a": {"b": {"c": {"file.txt": {"type": "text"}}}},
        }

        result = tool.execute_action("list_files", path="a/b/c")
        assert "file.txt" in result


# =====================================================================
# Count Files Helper
# =====================================================================


@pytest.mark.unit
class TestCountFiles:

    def test_count_files_nested(self):
        tool = InternalSearchTool({"source": {}})
        node = {
            "file1.txt": {"type": "text"},
            "dir": {
                "file2.txt": {"type": "text"},
                "file3.txt": "plain_value",
            },
        }
        assert tool._count_files(node) == 3

    def test_count_files_empty(self):
        tool = InternalSearchTool({"source": {}})
        assert tool._count_files({}) == 0


# =====================================================================
# Directory Structure Loading
# =====================================================================


@pytest.mark.unit
class TestGetDirectoryStructure:

    def test_loads_from_mongo(self):
        tool = InternalSearchTool({
            "source": {"active_docs": ["507f1f77bcf86cd799439011"]},
        })

        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "name": "test_source",
            "directory_structure": {"src": {"main.py": {}}},
        }

        with patch("application.core.mongo_db.MongoDB") as mock_mongo:
            mock_db = MagicMock()
            mock_db.__getitem__ = MagicMock(return_value=mock_collection)
            mock_client = MagicMock()
            mock_client.__getitem__ = MagicMock(return_value=mock_db)
            mock_mongo.get_client.return_value = mock_client

            result = tool._get_directory_structure()
            assert result is not None
            assert "src" in result

    def test_returns_none_without_active_docs(self):
        tool = InternalSearchTool({"source": {}})
        result = tool._get_directory_structure()
        assert result is None
        assert tool._dir_structure_loaded is True

    def test_caches_after_first_load(self):
        tool = InternalSearchTool({"source": {}})
        tool._dir_structure_loaded = True
        tool._directory_structure = {"cached": True}

        result = tool._get_directory_structure()
        assert result == {"cached": True}

    def test_handles_json_string_structure(self):
        tool = InternalSearchTool({
            "source": {"active_docs": ["507f1f77bcf86cd799439011"]},
        })

        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "name": "test_source",
            "directory_structure": json.dumps({"src": {"app.py": {}}}),
        }

        with patch("application.core.mongo_db.MongoDB") as mock_mongo:
            mock_db = MagicMock()
            mock_db.__getitem__ = MagicMock(return_value=mock_collection)
            mock_client = MagicMock()
            mock_client.__getitem__ = MagicMock(return_value=mock_db)
            mock_mongo.get_client.return_value = mock_client

            result = tool._get_directory_structure()
            assert result is not None
            assert "src" in result

    def test_handles_string_active_docs(self):
        tool = InternalSearchTool({
            "source": {"active_docs": "507f1f77bcf86cd799439011"},
        })

        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "directory_structure": {"dir": {}},
        }

        with patch("application.core.mongo_db.MongoDB") as mock_mongo:
            mock_db = MagicMock()
            mock_db.__getitem__ = MagicMock(return_value=mock_collection)
            mock_client = MagicMock()
            mock_client.__getitem__ = MagicMock(return_value=mock_db)
            mock_mongo.get_client.return_value = mock_client

            result = tool._get_directory_structure()
            assert result is not None

    def test_merges_multiple_sources(self):
        tool = InternalSearchTool({
            "source": {
                "active_docs": [
                    "507f1f77bcf86cd799439011",
                    "507f1f77bcf86cd799439012",
                ],
            },
        })

        mock_collection = MagicMock()
        mock_collection.find_one.side_effect = [
            {"name": "src1", "directory_structure": {"a": {}}},
            {"name": "src2", "directory_structure": {"b": {}}},
        ]

        with patch("application.core.mongo_db.MongoDB") as mock_mongo:
            mock_db = MagicMock()
            mock_db.__getitem__ = MagicMock(return_value=mock_collection)
            mock_client = MagicMock()
            mock_client.__getitem__ = MagicMock(return_value=mock_db)
            mock_mongo.get_client.return_value = mock_client

            result = tool._get_directory_structure()
            assert "src1" in result
            assert "src2" in result


# =====================================================================
# Metadata
# =====================================================================


@pytest.mark.unit
class TestInternalSearchToolMetadata:

    def test_actions_without_directory_structure(self):
        tool = InternalSearchTool({"has_directory_structure": False})
        meta = tool.get_actions_metadata()

        action_names = [a["name"] for a in meta]
        assert "search" in action_names
        assert "list_files" not in action_names

        search = meta[0]
        assert "path_filter" not in search["parameters"]["properties"]

    def test_actions_with_directory_structure(self):
        tool = InternalSearchTool({"has_directory_structure": True})
        meta = tool.get_actions_metadata()

        action_names = [a["name"] for a in meta]
        assert "search" in action_names
        assert "list_files" in action_names

        search = next(a for a in meta if a["name"] == "search")
        assert "path_filter" in search["parameters"]["properties"]

    def test_config_requirements_empty(self):
        tool = InternalSearchTool({})
        assert tool.get_config_requirements() == {}


# =====================================================================
# Build Helpers
# =====================================================================


@pytest.mark.unit
class TestBuildHelpers:

    def test_build_entry_without_directory_structure(self):
        entry = build_internal_tool_entry(has_directory_structure=False)
        assert entry["name"] == "internal_search"
        action_names = [a["name"] for a in entry["actions"]]
        assert "search" in action_names
        assert "list_files" not in action_names
        assert entry["actions"][0].get("active") is True

    def test_build_entry_with_directory_structure(self):
        entry = build_internal_tool_entry(has_directory_structure=True)
        action_names = [a["name"] for a in entry["actions"]]
        assert "list_files" in action_names
        # path_filter should be in search params
        search_action = next(a for a in entry["actions"] if a["name"] == "search")
        assert "path_filter" in search_action["parameters"]["properties"]

    def test_build_config(self):
        config = build_internal_tool_config(
            source={"active_docs": ["abc"]},
            retriever_name="semantic",
            chunks=4,
        )
        assert config["source"] == {"active_docs": ["abc"]}
        assert config["retriever_name"] == "semantic"
        assert config["chunks"] == 4

    def test_build_config_defaults(self):
        config = build_internal_tool_config(source={"active_docs": ["abc"]})
        assert config["retriever_name"] == "classic"
        assert config["chunks"] == 2
        assert config["doc_token_limit"] == 50000

    def test_internal_tool_id(self):
        assert INTERNAL_TOOL_ID == "internal"

    def test_internal_tool_entry_constant(self):
        assert INTERNAL_TOOL_ENTRY["name"] == "internal_search"

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


# =====================================================================
# sources_have_directory_structure
# =====================================================================


@pytest.mark.unit
class TestSourcesHaveDirectoryStructure:

    def test_no_active_docs(self):
        assert sources_have_directory_structure({}) is False

    def test_with_directory_structure(self):
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            "directory_structure": {"src": {}},
        }

        with patch("application.core.mongo_db.MongoDB") as mock_mongo:
            mock_db = MagicMock()
            mock_db.__getitem__ = MagicMock(return_value=mock_collection)
            mock_client = MagicMock()
            mock_client.__getitem__ = MagicMock(return_value=mock_db)
            mock_mongo.get_client.return_value = mock_client

            result = sources_have_directory_structure(
                {"active_docs": ["507f1f77bcf86cd799439011"]}
            )
            assert result is True

    def test_without_directory_structure(self):
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {"directory_structure": None}

        with patch("application.core.mongo_db.MongoDB") as mock_mongo:
            mock_db = MagicMock()
            mock_db.__getitem__ = MagicMock(return_value=mock_collection)
            mock_client = MagicMock()
            mock_client.__getitem__ = MagicMock(return_value=mock_db)
            mock_mongo.get_client.return_value = mock_client

            result = sources_have_directory_structure(
                {"active_docs": ["507f1f77bcf86cd799439011"]}
            )
            assert result is False

    def test_handles_exception_gracefully(self):
        with patch(
            "application.core.mongo_db.MongoDB.get_client",
            side_effect=Exception("DB down"),
        ):
            result = sources_have_directory_structure(
                {"active_docs": ["507f1f77bcf86cd799439011"]}
            )
            assert result is False

    def test_string_active_docs(self):
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            "directory_structure": {"a": {}},
        }

        with patch("application.core.mongo_db.MongoDB") as mock_mongo:
            mock_db = MagicMock()
            mock_db.__getitem__ = MagicMock(return_value=mock_collection)
            mock_client = MagicMock()
            mock_client.__getitem__ = MagicMock(return_value=mock_db)
            mock_mongo.get_client.return_value = mock_client

            result = sources_have_directory_structure(
                {"active_docs": "507f1f77bcf86cd799439011"}
            )
            assert result is True
