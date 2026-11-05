"""Fixtures for the monitor tests: a committed per-test database, a conversation, and recorders."""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from tests.monitors.helpers import FakeRedis


@pytest.fixture()
def mon_db(pg_engine, monkeypatch):
    """Route ``db_session`` / ``db_readonly`` to the per-test database (committed, not rolled back)."""
    monkeypatch.setattr("docsgpt.storage.db.engine._engine", pg_engine)
    return pg_engine


@pytest.fixture()
def conversation_id(mon_db) -> str:
    """A conversation ``u1`` owns outright (auto-resume applies)."""
    with mon_db.begin() as conn:
        return str(ConversationsRepository(conn).create("u1", "chat")["id"])


@pytest.fixture()
def events(monkeypatch) -> List[Dict[str, Any]]:
    """Every ``monitor.updated`` publish, in order."""
    published: List[Dict[str, Any]] = []

    def record(user_id, event_type, payload, scope=None):
        published.append({"user_id": user_id, "type": event_type, "payload": payload})
        return "1-0"

    monkeypatch.setattr("docsgpt.monitors.events.publish_user_event", record)
    return published


@pytest.fixture()
def wakes(monkeypatch) -> List[Dict[str, Any]]:
    """Every ``wake_conversation`` call the monitor code makes (none reach the queue)."""
    calls: List[Dict[str, Any]] = []

    def record(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("docsgpt.background.wake.wake_conversation", record)
    return calls


class _HeldClock:
    """The ``time`` module with ``time()`` held at one instant."""

    def __init__(self, now: float):
        self._now = now

    def time(self) -> float:
        return self._now

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


@pytest.fixture()
def fake_redis(monkeypatch) -> FakeRedis:
    """A fake Redis, with the trigger code's clock held at the test's start.

    The rate limits count per clock minute: a burst that ran across ``:00``
    started a fresh count, and the request meant to be refused got through.
    Only ``docsgpt.monitors.triggers`` sees the held clock.
    """
    from docsgpt.monitors import triggers

    monkeypatch.setattr(triggers, "time", _HeldClock(time.time()))
    return FakeRedis()
