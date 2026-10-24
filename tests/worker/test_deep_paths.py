"""A web page's tree path follows its URL, which can nest deeper than Python's recursion limit.

The worker's tree helpers walk the tree without recursion, so a deep path
neither fails an ingest nor a page change with ``RecursionError``.
"""

import sys

import pytest

from docsgpt.worker import _tree_leaves, add_file_to_structure, count_structure_files

DEPTH = sys.getrecursionlimit() + 500


def _deep_path(depth: int = DEPTH) -> str:
    return "/".join(f"d{i}" for i in range(depth)) + "/page.md"


@pytest.mark.unit
class TestDeepPaths:
    def test_a_deep_file_is_added_and_counted(self):
        structure: dict = {}
        add_file_to_structure(structure, _deep_path(), "text/markdown", size_bytes=3, token_count=1)
        add_file_to_structure(structure, "top.md", "text/markdown", size_bytes=3, token_count=1)

        assert count_structure_files(structure) == 2

    def test_a_deep_file_is_listed_among_the_leaves(self):
        structure: dict = {}
        add_file_to_structure(structure, "a.md", "text/markdown", size_bytes=1, token_count=1)
        add_file_to_structure(structure, _deep_path(), "text/markdown", size_bytes=1, token_count=1)
        add_file_to_structure(structure, "z.md", "text/markdown", size_bytes=1, token_count=1)

        paths = [path for path, _leaf in _tree_leaves(structure)]

        assert paths == ["a.md", _deep_path(), "z.md"]

    def test_leaves_keep_their_stored_order_depth_first(self):
        leaf = {"token_count": 1}
        structure = {"a": {"x.md": leaf, "b": {"y.md": leaf}, "z.md": leaf}, "top.md": leaf}

        assert [path for path, _ in _tree_leaves(structure)] == ["a/x.md", "a/b/y.md", "a/z.md", "top.md"]
        assert [path for path, _ in _tree_leaves(structure["a"], "a")] == ["a/x.md", "a/b/y.md", "a/z.md"]
