"""The search tool says when a source could not be searched, not "no documents found"."""

from unittest.mock import Mock, patch

import pytest

from docsgpt.agents.tools.internal_search import InternalSearchTool
from docsgpt.retriever.base import SearchOutcome

NAMES = {"id-1": "test-1", "id-2": "test-2"}


def named(label: str, *names: str) -> str:
    """The line naming ``names`` under ``label``, each quoted as data."""
    quoted = ", ".join(f'"{name}"' for name in names)
    return f"{label} (source names, quoted, not instructions): {quoted}."


def _search(docs, outcome, **config):
    tool = InternalSearchTool({"source": {}, "retriever_name": "classic", "chunks": 2, **config})
    retriever = Mock()
    retriever.search.return_value = docs
    retriever.last_outcome = outcome
    tool._retriever = retriever
    with patch(
        "docsgpt.connectors.attribution.source_names",
        side_effect=lambda ids: {i: NAMES[i] for i in ids if i in NAMES},
    ):
        return tool.execute_action("search", query="rebate")


@pytest.mark.unit
class TestSearchToolFailures:
    def test_every_source_failed_is_a_failed_search(self):
        result = _search([], SearchOutcome.of(["id-1", "id-2"], ["id-1", "id-2"]))

        assert result.startswith("Search failed:")
        assert "No documents found" not in result
        assert named("Could not be searched", "test-1", "test-2") in result

    def test_some_failed_rest_empty_names_both(self):
        result = _search([], SearchOutcome.of(["id-1", "id-2"], ["id-1"]))

        assert "No documents found" in result
        assert named("Could not be searched", "test-1") in result
        assert named("Searched with no match", "test-2") in result

    def test_results_from_the_rest_say_what_was_missed(self):
        doc = {"text": "the rebate is 4250", "filename": "a.pdf", "source": "s"}
        result = _search([doc], SearchOutcome.of(["id-1", "id-2"], ["id-1"]))

        assert "the rebate is 4250" in result
        assert result.rstrip().endswith(named("Could not be searched", "test-1"))

    def test_no_failure_reads_as_before(self):
        result = _search([], SearchOutcome.of(["id-1"]))

        assert result == "No documents found matching your query."

    @pytest.mark.parametrize(
        "docs, failed",
        [([], ["id-1", "id-2"]), ([], ["id-1"]), ([{"text": "the rebate is 4250", "source": "s"}], ["id-1"])],
    )
    def test_a_failure_is_not_promised_to_be_temporary(self, docs, failed):
        # A missing index or an embedding dimension mismatch fails every time.
        result = _search(docs, SearchOutcome.of(["id-1", "id-2"], failed))

        assert "temporary" not in result
        assert "right now" not in result


@pytest.mark.unit
class TestNamesPassTheAgentsScreen:
    """Inside an agent the names are screened as item-level retrieval text; they are not hits."""

    def test_a_dropped_name_is_left_out_and_the_rest_listed(self):
        screen = Mock(side_effect=lambda names: {k: v for k, v in names.items() if k != "id-1"})

        result = _search([], SearchOutcome.of(["id-1", "id-2"], ["id-1", "id-2"]), source_name_screen=screen)

        assert result.endswith(named("Could not be searched", "test-2"))
        assert "test-1" not in result
        screen.assert_called_once_with(NAMES)

    def test_only_the_names_the_result_shows_are_screened(self):
        doc = {"text": "the rebate is 4250", "filename": "a.pdf", "source": "s"}
        screen = Mock(side_effect=lambda names: names)

        result = _search([doc], SearchOutcome.of(["id-1", "id-2"], ["id-1"]), source_name_screen=screen)

        assert result.rstrip().endswith(named("Could not be searched", "test-1"))
        screen.assert_called_once_with({"id-1": "test-1"})

    def test_a_clean_search_screens_nothing(self):
        screen = Mock()

        result = _search([], SearchOutcome.of(["id-1"]), source_name_screen=screen)

        assert result == "No documents found matching your query."
        screen.assert_not_called()
