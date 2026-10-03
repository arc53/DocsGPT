"""Tests for ``docsgpt.core.docs_pages``, the ``lastUpdated`` frontmatter helpers."""

import pytest

from docsgpt.core.docs_pages import read_last_updated, set_last_updated

PAGE = "---\ntitle: Example\ndescription: An example page.\nlastUpdated: 2026-09-30\n---\n\n# Example\n"


@pytest.mark.unit
class TestReadLastUpdated:
    def test_reads_the_date(self):
        assert read_last_updated(PAGE) == "2026-09-30"

    def test_accepts_a_quoted_date(self):
        assert read_last_updated(PAGE.replace("2026-09-30", "'2026-09-30'")) == "2026-09-30"

    def test_none_without_the_field(self):
        assert read_last_updated("---\ntitle: Example\n---\n\n# Example\n") is None

    def test_ignores_the_field_outside_the_frontmatter(self):
        assert read_last_updated("---\ntitle: Example\n---\n\nlastUpdated: 2026-09-30\n") is None

    def test_none_without_frontmatter(self):
        assert read_last_updated("# Example\n") is None


@pytest.mark.unit
class TestSetLastUpdated:
    def test_replaces_the_date(self):
        assert set_last_updated(PAGE, "2026-10-03") == PAGE.replace("2026-09-30", "2026-10-03")

    def test_adds_the_field_at_the_end_of_the_frontmatter(self):
        page = "---\ntitle: Example\n---\n\n# Example\n"
        assert set_last_updated(page, "2026-10-03") == "---\ntitle: Example\nlastUpdated: 2026-10-03\n---\n\n# Example\n"

    def test_leaves_the_body_alone(self):
        page = "---\ntitle: Example\n---\n\nlastUpdated: 2020-01-01\n"
        assert set_last_updated(page, "2026-10-03").endswith("\nlastUpdated: 2020-01-01\n")

    def test_rejects_a_page_without_frontmatter(self):
        with pytest.raises(ValueError):
            set_last_updated("# Example\n", "2026-10-03")
