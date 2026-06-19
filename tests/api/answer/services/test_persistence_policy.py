"""Unit tests for ``resolve_persistence`` (persist + sidebar visibility)."""

import pytest

from application.api.answer.services.persistence_policy import (
    VISIBILITY_HIDDEN,
    VISIBILITY_LISTED,
    resolve_persistence,
)


@pytest.mark.unit
class TestResolvePersistence:
    def test_default_is_hidden(self):
        persist, visibility = resolve_persistence()
        assert persist is True
        assert visibility == VISIBILITY_HIDDEN

    def test_explicit_listed_lists(self):
        persist, visibility = resolve_persistence(visibility_flag=VISIBILITY_LISTED)
        assert persist is True
        assert visibility == VISIBILITY_LISTED

    def test_explicit_hidden_stays_hidden(self):
        _, visibility = resolve_persistence(visibility_flag=VISIBILITY_HIDDEN)
        assert visibility == VISIBILITY_HIDDEN

    def test_unknown_visibility_value_falls_back_to_hidden(self):
        _, visibility = resolve_persistence(visibility_flag="sidebar-please")
        assert visibility == VISIBILITY_HIDDEN

    def test_non_string_visibility_value_falls_back_to_hidden(self):
        # Clients sending booleans (e.g. a stray ``visibility: true``) must
        # not accidentally list — only the exact string "listed" opts in.
        _, visibility = resolve_persistence(visibility_flag=True)
        assert visibility == VISIBILITY_HIDDEN

    def test_persist_opt_out(self):
        persist, _ = resolve_persistence(persist_flag=False)
        assert persist is False

    def test_persist_defaults_true_when_listed(self):
        persist, _ = resolve_persistence(visibility_flag=VISIBILITY_LISTED)
        assert persist is True
