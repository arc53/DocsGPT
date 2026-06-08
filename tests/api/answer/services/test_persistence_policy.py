"""Unit tests for ``resolve_persistence`` (persist + sidebar visibility)."""

import pytest

from application.api.answer.services.persistence_policy import (
    VISIBILITY_HIDDEN,
    VISIBILITY_LISTED,
    resolve_persistence,
)


@pytest.mark.unit
class TestResolvePersistence:
    def test_first_party_default_lists(self):
        persist, visibility = resolve_persistence(display_flag=None)
        assert persist is True
        assert visibility == VISIBILITY_LISTED

    def test_api_key_caller_defaults_hidden(self):
        persist, visibility = resolve_persistence(display_flag=None, api_key="k-1")
        assert persist is True
        assert visibility == VISIBILITY_HIDDEN

    def test_shared_usage_defaults_hidden(self):
        _, visibility = resolve_persistence(display_flag=None, is_shared_usage=True)
        assert visibility == VISIBILITY_HIDDEN

    def test_explicit_display_true_lists_api_key_caller(self):
        _, visibility = resolve_persistence(display_flag=True, api_key="k-1")
        assert visibility == VISIBILITY_LISTED

    def test_explicit_display_false_hides_first_party(self):
        persist, visibility = resolve_persistence(display_flag=False)
        # Still persisted, just not shown in the sidebar.
        assert persist is True
        assert visibility == VISIBILITY_HIDDEN

    def test_persist_opt_out(self):
        persist, _ = resolve_persistence(display_flag=None, persist_flag=False)
        assert persist is False

    def test_persist_defaults_true_for_hidden_api_caller(self):
        persist, _ = resolve_persistence(display_flag=False, api_key="k-1")
        assert persist is True
