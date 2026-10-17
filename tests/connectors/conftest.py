"""Shared fixtures for connector tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _oauth_connectors_configured(monkeypatch):
    """Give the OAuth connectors their server settings.

    A connector without them is off and hidden from members, so tests about
    anything else start from configured connectors. A test about setup sets
    a setting back to None itself.
    """
    from docsgpt.core.settings import settings

    for name in (
        "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
        "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET",
        "CONFLUENCE_CLIENT_ID", "CONFLUENCE_CLIENT_SECRET",
    ):
        if not getattr(settings, name, None):
            monkeypatch.setattr(settings, name, f"test-{name.lower()}")
