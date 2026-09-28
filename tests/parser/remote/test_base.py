"""Tests for the shared web-ingest path helpers in docsgpt/parser/remote/base.py."""

import pytest

from docsgpt.parser.remote.base import (
    MAX_QUERY_SEGMENT_LENGTH,
    dedupe_virtual_paths,
    normalize_page_url,
    url_to_virtual_path,
)
from docsgpt.parser.schema.base import Document


@pytest.mark.unit
class TestUrlToVirtualPath:
    @pytest.mark.parametrize(
        "url, path",
        [
            # Paths without a query string are unchanged.
            ("https://x.io/", "index.md"),
            ("https://x.io", "index.md"),
            ("https://x.io/guides/setup", "guides/setup.md"),
            ("https://x.io/guides/setup/", "guides/setup.md"),
            ("https://x.io/page.html", "page.md"),
            ("https://x.io/readme.md", "readme.md"),
            # The fragment names a spot on the same page.
            ("https://x.io/p#install", "p.md"),
            ("https://x.io/p?#install", "p.md"),
        ],
    )
    def test_query_less_paths_are_unchanged(self, url, path):
        assert url_to_virtual_path(url) == path

    def test_distinct_queries_get_distinct_paths(self):
        first = url_to_virtual_path("https://x.io/p?page=1")
        second = url_to_virtual_path("https://x.io/p?page=2")

        assert first == "p__page=1.md"
        assert second == "p__page=2.md"
        assert url_to_virtual_path("https://x.io/p") == "p.md"

    def test_parameter_order_does_not_matter(self):
        assert (
            url_to_virtual_path("https://x.io/p?b=2&a=1")
            == url_to_virtual_path("https://x.io/p?a=1&b=2")
            == "p__a=1&b=2.md"
        )

    def test_query_on_the_root_and_on_page_extensions(self):
        assert url_to_virtual_path("https://x.io/?page=2") == "index__page=2.md"
        assert url_to_virtual_path("https://x.io/a.php?id=7#top") == "a__id=7.md"
        assert url_to_virtual_path("https://x.io/doc.md?v=2") == "doc__v=2.md"

    def test_query_is_sanitized_to_a_single_tree_segment(self):
        path = url_to_virtual_path("https://x.io/p?q=a/b%20c&next=..%2Fetc&flag")

        assert path == "p__flag&next=..-etc&q=a-b-c.md"
        assert path.count("/") == 0
        assert "?" not in path and "#" not in path and "%" not in path

    def test_unicode_query_values_survive(self):
        assert url_to_virtual_path("https://x.io/s?q=%D0%BA%D0%BE%D1%82") == "s__q=кот.md"

    def test_long_queries_are_bounded_with_a_stable_hash(self):
        long_a = "https://x.io/p?q=" + "a" * 500
        long_b = "https://x.io/p?q=" + "a" * 499 + "b"

        path_a = url_to_virtual_path(long_a)
        path_b = url_to_virtual_path(long_b)

        segment = path_a[len("p__"):-len(".md")]
        assert len(segment) <= MAX_QUERY_SEGMENT_LENGTH
        assert path_a != path_b
        assert url_to_virtual_path(long_a) == path_a

    def test_host_prefix_still_applies(self):
        assert (
            url_to_virtual_path("https://x.io/p?page=1", include_host=True)
            == "x.io/p__page=1.md"
        )


def _doc(url, file_path=None):
    return Document(
        "text",
        extra_info={"source": url, "file_path": file_path or url_to_virtual_path(url)},
    )


def _paths(docs):
    return [d.extra_info["file_path"] for d in docs]


@pytest.mark.unit
class TestDedupeVirtualPaths:
    def test_distinct_pages_are_left_alone(self):
        docs = [_doc("https://x.io/"), _doc("https://x.io/a"), _doc("https://x.io/b")]

        assert _paths(dedupe_virtual_paths(docs)) == ["index.md", "a.md", "b.md"]

    def test_extension_collision_gets_a_numbered_suffix(self):
        docs = [_doc("https://x.io/a.html"), _doc("https://x.io/a")]

        assert _paths(dedupe_virtual_paths(docs)) == ["a-2.md", "a.md"]

    def test_suffixes_do_not_depend_on_input_order(self):
        urls = ["https://x.io/a", "https://x.io/a.htm", "https://x.io/a.html"]

        forward = _paths(dedupe_virtual_paths([_doc(u) for u in urls]))
        backward = _paths(dedupe_virtual_paths([_doc(u) for u in reversed(urls)]))

        assert forward == ["a.md", "a-2.md", "a-3.md"]
        assert backward == list(reversed(forward))

    def test_suffix_skips_a_path_another_page_already_has(self):
        docs = [
            _doc("https://x.io/g/a-2"),
            _doc("https://x.io/g/a"),
            _doc("https://x.io/g/a.html"),
        ]

        assert _paths(dedupe_virtual_paths(docs)) == ["g/a-2.md", "g/a.md", "g/a-3.md"]

    def test_the_same_page_reached_twice_keeps_one_path(self):
        # A crawler that followed ``#section`` fetched the same page again.
        docs = [_doc("https://x.io/a"), _doc("https://x.io/a#section")]

        assert _paths(dedupe_virtual_paths(docs)) == ["a.md", "a.md"]

    def test_documents_without_a_file_path_are_ignored(self):
        doc = Document("text", extra_info={"source": "https://x.io/a"})

        assert dedupe_virtual_paths([doc]) == [doc]
        assert "file_path" not in doc.extra_info


@pytest.mark.unit
class TestNormalizePageUrl:
    def test_query_order_does_not_matter(self):
        assert normalize_page_url("https://x.io/p?a=1&b=2") == normalize_page_url("https://x.io/p?b=2&a=1")

    def test_fragment_is_dropped(self):
        assert normalize_page_url("https://x.io/p?a=1#top") == normalize_page_url("https://x.io/p?a=1")

    def test_distinct_queries_stay_distinct(self):
        assert normalize_page_url("https://x.io/p?page=1") != normalize_page_url("https://x.io/p?page=2")

    def test_blank_values_are_kept(self):
        assert normalize_page_url("https://x.io/p?flag") != normalize_page_url("https://x.io/p")

    def test_url_without_query_or_fragment_is_unchanged(self):
        assert normalize_page_url("https://x.io/guides/setup") == "https://x.io/guides/setup"


@pytest.mark.unit
class TestDedupeReorderedQuery:
    def test_reordered_query_is_one_page(self):
        docs = [_doc("https://x.com/p?a=1&b=2"), _doc("https://x.com/p?b=2&a=1")]

        assert _paths(dedupe_virtual_paths(docs)) == ["p__a=1&b=2.md", "p__a=1&b=2.md"]
