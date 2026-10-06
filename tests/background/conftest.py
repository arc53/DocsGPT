"""Fixtures for the background-jobs tests."""

from __future__ import annotations

import pytest

from docsgpt.storage.db.repositories.conversations import ConversationsRepository


@pytest.fixture()
def bg_db(pg_engine, monkeypatch):
    """Route ``db_session`` / ``db_readonly`` to the per-test database (committed, not rolled back).

    Background work runs on other threads, which can't share the rolled-back
    ``pg_conn`` transaction; each test gets its own cloned database instead.
    """
    monkeypatch.setattr("docsgpt.storage.db.engine._engine", pg_engine)
    return pg_engine


@pytest.fixture()
def conversation(bg_db):
    """A conversation owned by ``u1`` with one finished message; returns ``(conversation_id, message_id)``."""
    with bg_db.begin() as conn:
        repo = ConversationsRepository(conn)
        conv = repo.create("u1", "chat")
        message = repo.append_message(str(conv["id"]), {"prompt": "p", "response": "r"})
    return str(conv["id"]), str(message["id"])
