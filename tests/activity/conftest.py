"""Shared fixtures for the Activity tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_beat(monkeypatch):
    """Keep the snapshot and calendar off the real RedBeat: no sync times
    unless a test sets its own."""
    from docsgpt.activity import now, planned

    monkeypatch.setattr(now, "next_sync_times", lambda: {})
    monkeypatch.setattr(planned, "sync_schedule", lambda: {})
