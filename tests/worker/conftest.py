"""Fixtures for Celery worker smoke tests.

These tests exercise the task *bodies* in ``application.worker`` against a
real Postgres schema (via the ephemeral ``pg_conn`` fixture from the root
``tests/conftest.py``). External I/O — storage, the embedding pipeline,
the retriever, the LLM, the backend HTTP callback — is mocked, but every
PG write is allowed to hit the real ephemeral DB so the assertions can
read the resulting rows back.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Connection


@pytest.fixture
def patch_worker_db(pg_conn, monkeypatch):
    """Redirect ``db_session`` / ``db_readonly`` in ``application.worker``.

    Both helpers yield the per-test transactional ``pg_conn``, so any
    writes a task performs are visible to the test and roll back on
    teardown. Without this patch the worker would open its own pooled
    engine and punch past the per-test transaction.
    """

    @contextmanager
    def _use_pg_conn() -> Iterator[Connection]:
        yield pg_conn

    monkeypatch.setattr("application.worker.db_session", _use_pg_conn)
    monkeypatch.setattr("application.worker.db_readonly", _use_pg_conn)


@pytest.fixture
def task_self():
    """Minimal stand-in for the Celery task ``self`` passed to workers.

    Only ``update_state`` is ever exercised in the happy paths we cover
    here, so a MagicMock is more than enough.
    """
    return MagicMock(name="celery_task_self")
