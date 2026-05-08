"""Tests for InternalSearchTool and its helper functions."""

from unittest.mock import MagicMock, Mock, patch

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


@pytest.mark.unit
class TestInternalSearchToolGetRetriever:
    """Cover line 32: _get_retriever creates retriever lazily."""

    def test_get_retriever_creates_retriever(self):
        tool = InternalSearchTool({
            "source": {},
            "retriever_name": "classic",
            "chunks": 2,
        })
        assert tool._retriever is None

        mock_retriever = Mock()
        with patch(
            "application.agents.tools.internal_search.RetrieverCreator"
        ) as mock_rc:
            mock_rc.create_retriever.return_value = mock_retriever
            result = tool._get_retriever()

        assert result is mock_retriever
        assert tool._retriever is mock_retriever

    def test_get_retriever_cached(self):
        """Cover line 32: second call returns cached retriever."""
        tool = InternalSearchTool({"source": {}, "retriever_name": "classic"})
        mock_retriever = Mock()
        tool._retriever = mock_retriever

        result = tool._get_retriever()
        assert result is mock_retriever


@pytest.mark.unit
class TestGetDirectoryStructure:
    """Cover ``_get_directory_structure`` loader semantics (post-Postgres cutover)."""

    def test_no_active_docs_returns_none(self):
        """No ``active_docs`` short-circuits to None without opening a connection."""
        tool = InternalSearchTool({"source": {}})
        result = tool._get_directory_structure()
        assert result is None
        assert tool._dir_structure_loaded is True


@pytest.mark.unit
class TestFormatStructureAdditional:
    """Cover lines 186, 193, 200, 221: format structure branches."""

    def test_format_structure_non_dict_node(self):
        """Cover line 173: non-dict node returns file message."""
        tool = InternalSearchTool({"source": {}})
        result = tool._format_structure("a string node", "/path")
        assert "is a file" in result

    def test_format_structure_file_with_type_metadata(self):
        """Cover lines 186-193: file with type and token_count metadata."""
        tool = InternalSearchTool({"source": {}})
        node = {
            "readme.md": {"type": "markdown", "token_count": 500},
            "data.json": {"size_bytes": 1024},
        }
        result = tool._format_structure(node, "/root")
        assert "readme.md" in result
        assert "500 tokens" in result

    def test_format_structure_empty_directory(self):
        """Cover lines 206-208: empty directory."""
        tool = InternalSearchTool({"source": {}})
        result = tool._format_structure({}, "/empty")
        assert "(empty)" in result

    def test_format_structure_plain_file_entry(self):
        """Cover line 198: plain file entry (non-dict value)."""
        tool = InternalSearchTool({"source": {}})
        node = {"file.txt": "some_value"}
        result = tool._format_structure(node, "/root")
        assert "file.txt" in result

    def test_count_files_nested(self):
        """Cover line 221: _count_files counts nested files."""
        tool = InternalSearchTool({"source": {}})
        node = {
            "sub": {"file1.txt": {"type": "text"}},
            "file2.txt": "plain",
        }
        count = tool._count_files(node)
        assert count == 2


@pytest.mark.unit
class TestSourcesHaveDirectoryStructure:
    """Cover line 240, 254, 298: sources_have_directory_structure helper."""

    def test_no_active_docs_returns_false(self):
        from application.agents.tools.internal_search import (
            sources_have_directory_structure,
        )

        assert sources_have_directory_structure({}) is False
        assert sources_have_directory_structure({"active_docs": []}) is False

    def test_get_config_requirements(self):
        """Cover line 280: get_config_requirements."""
        tool = InternalSearchTool({"source": {}})
        assert tool.get_config_requirements() == {}


# ---------------------------------------------------------------------------
# Coverage — additional uncovered lines: 77, 135, 186, 200, 221, 240, 254, 298
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInternalSearchToolAdditionalCoverage:

    def test_get_directory_structure_returns_cached(self):
        """Cover line 77: source_doc not found in DB returns None."""
        tool = InternalSearchTool({"source": {"active_docs": ["nonexistent"]}})
        tool._dir_structure_loaded = True
        tool._directory_structure = {"cached": True}
        result = tool._get_directory_structure()
        assert result == {"cached": True}

    def test_execute_search_appends_to_retrieved_docs(self):
        """Cover line 135: doc appended to retrieved_docs."""
        tool = InternalSearchTool({"source": {}})
        mock_retriever = Mock()
        mock_retriever.search.return_value = [
            {"title": "Doc1", "text": "content", "source": "src"},
        ]
        tool._retriever = mock_retriever
        tool._execute_search(query="test")
        assert len(tool.retrieved_docs) == 1

    def test_format_structure_file_metadata(self):
        """Cover line 186: file with metadata (type, token_count)."""
        tool = InternalSearchTool({"source": {}})
        node = {
            "readme.md": {"type": "markdown", "token_count": 100},
            "subfolder": {"nested_file.py": {}},
        }
        result = tool._format_structure(node, "/")
        assert "readme.md" in result
        assert "markdown" in result
        assert "100 tokens" in result

    def test_format_structure_folders_and_files(self):
        """Cover line 200: folders and files sections in output."""
        tool = InternalSearchTool({"source": {}})
        node = {
            "src": {"main.py": {}},
            "README.md": "file",
        }
        result = tool._format_structure(node, "/")
        assert "Folders:" in result
        assert "Files:" in result

    def test_count_files_recursive(self):
        """Cover line 221: _count_files counts nested files."""
        tool = InternalSearchTool({"source": {}})
        node = {
            "a.py": "file",
            "subdir": {
                "b.py": {"type": "python", "token_count": 50},
            },
        }
        count = tool._count_files(node)
        assert count == 2

    def test_get_actions_metadata_with_directory_structure(self):
        """Cover line 240+: actions include path_filter and list_files."""
        tool = InternalSearchTool({"source": {}, "has_directory_structure": True})
        actions = tool.get_actions_metadata()
        action_names = [a["name"] for a in actions]
        assert "search" in action_names
        assert "list_files" in action_names
        # Check path_filter is in search params
        search_action = next(a for a in actions if a["name"] == "search")
        assert "path_filter" in search_action["parameters"]["properties"]

    def test_get_actions_metadata_without_directory_structure(self):
        """Cover line 254: actions without directory structure."""
        tool = InternalSearchTool({"source": {}, "has_directory_structure": False})
        actions = tool.get_actions_metadata()
        action_names = [a["name"] for a in actions]
        assert "search" in action_names
        assert "list_files" not in action_names

    def test_build_internal_tool_entry_with_directory_structure(self):
        """Cover line 298: build_internal_tool_entry with has_directory_structure."""
        entry = build_internal_tool_entry(has_directory_structure=True)
        action_names = [a["name"] for a in entry["actions"]]
        assert "list_files" in action_names
        search_action = next(a for a in entry["actions"] if a["name"] == "search")
        assert "path_filter" in search_action["parameters"]["properties"]


# ---------------------------------------------------------------------------
# Additional coverage for internal_search.py
# Lines: 101 (unknown action), 108 (empty query), 114-115 (search exception),
# 117-118 (no docs), 130-131 (path filter no match),
# 154-155 (no dir structure), 165-166 (path not found)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInternalSearchUnknownAction:
    """Cover line 101: unknown action returns error string."""

    def test_unknown_action(self):
        tool = InternalSearchTool({"source": {}})
        result = tool.execute_action("unknown_action")
        assert "Unknown action" in result


@pytest.mark.unit
class TestInternalSearchEmptyQuery:
    """Cover line 108: empty query returns error."""

    def test_empty_query(self):
        tool = InternalSearchTool({"source": {}})
        result = tool.execute_action("search", query="")
        assert "required" in result.lower()


@pytest.mark.unit
class TestInternalSearchException:
    """Cover lines 114-115: search exception returns error."""

    def test_search_raises(self):
        tool = InternalSearchTool({"source": {}})
        mock_retriever = MagicMock()
        mock_retriever.search.side_effect = RuntimeError("DB down")
        tool._get_retriever = MagicMock(return_value=mock_retriever)
        result = tool.execute_action("search", query="hello")
        assert "internal error" in result.lower()


@pytest.mark.unit
class TestInternalSearchNoDocs:
    """Cover lines 117-118: no docs found."""

    def test_no_docs(self):
        tool = InternalSearchTool({"source": {}})
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = []
        tool._get_retriever = MagicMock(return_value=mock_retriever)
        result = tool.execute_action("search", query="hello")
        assert "No documents found" in result


@pytest.mark.unit
class TestInternalSearchPathFilterNoMatch:
    """Cover lines 130-131: path filter with no matching docs."""

    def test_path_filter_no_match(self):
        tool = InternalSearchTool({"source": {}})
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = [
            {"source": "other.txt", "text": "data", "title": "Other"}
        ]
        tool._get_retriever = MagicMock(return_value=mock_retriever)
        result = tool.execute_action(
            "search", query="hello", path_filter="nonexistent"
        )
        assert "No documents found" in result
        assert "nonexistent" in result


@pytest.mark.unit
class TestInternalSearchListFilesNoDirStructure:
    """Cover lines 154-155: no directory structure."""

    def test_no_dir_structure(self):
        tool = InternalSearchTool({"source": {}})
        tool._get_directory_structure = MagicMock(return_value=None)
        result = tool.execute_action("list_files")
        assert "No file structure" in result


@pytest.mark.unit
class TestInternalSearchListFilesPathNotFound:
    """Cover lines 165-166: path not found."""

    def test_path_not_found(self):
        tool = InternalSearchTool({"source": {}})
        tool._get_directory_structure = MagicMock(
            return_value={"folder": {"file.txt": {}}}
        )
        result = tool.execute_action("list_files", path="missing_dir")
        assert "not found" in result.lower()
