"""Tests for ``DeviceAuditLogRepository.list_for_device`` paging against real Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.device_audit_log import DeviceAuditLogRepository


@pytest.fixture()
def seeded(pg_conn):
    """Five audit rows for ``dev-1`` (two share a created_at) plus one foreign row."""
    pg_conn.execute(
        text(
            "INSERT INTO devices "
            "(id, user_id, name, machine_pubkey_fingerprint, token_hash, status) VALUES "
            "('dev-1', 'u-dev', 'laptop', 'fp-1', 'hash-1', 'active'), "
            "('dev-2', 'u-dev', 'desktop', 'fp-2', 'hash-2', 'active')"
        )
    )
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stamps = [base, base + timedelta(minutes=1), base + timedelta(minutes=2),
              base + timedelta(minutes=2), base + timedelta(minutes=3)]
    for i, ts in enumerate(stamps):
        pg_conn.execute(
            text(
                "INSERT INTO device_audit_log "
                "(device_id, user_id, invocation_id, action, command, "
                " approval_mode, decision, issued_at, created_at) VALUES "
                "('dev-1', 'u-dev', :inv, 'run_command', 'ls', 'ask', 'dispatched', :ts, :ts)"
            ),
            {"inv": f"inv-{i}", "ts": ts},
        )
    pg_conn.execute(
        text(
            "INSERT INTO device_audit_log "
            "(device_id, user_id, invocation_id, action, command, "
            " approval_mode, decision, issued_at, created_at) VALUES "
            "('dev-2', 'u-dev', 'other', 'run_command', 'ls', 'ask', 'dispatched', :ts, :ts)"
        ),
        {"ts": base},
    )
    return DeviceAuditLogRepository(pg_conn)


def test_default_is_newest_first_with_id_tie_breaker(seeded):
    rows = seeded.list_for_device("dev-1", "u-dev")
    # inv-3 and inv-2 share created_at; the higher id (inv-3) comes first.
    assert [r["invocation_id"] for r in rows] == ["inv-4", "inv-3", "inv-2", "inv-1", "inv-0"]


def test_limit_and_offset_page_each_row_once(seeded):
    seen = []
    for offset in (0, 2, 4):
        seen += [r["invocation_id"] for r in seeded.list_for_device("dev-1", "u-dev", limit=2, offset=offset)]
    assert seen == ["inv-4", "inv-3", "inv-2", "inv-1", "inv-0"]
    assert seeded.list_for_device("dev-1", "u-dev", limit=2, offset=6) == []


def test_scoped_to_device_and_user(seeded):
    assert seeded.list_for_device("dev-1", "someone-else") == []
    assert [r["invocation_id"] for r in seeded.list_for_device("dev-2", "u-dev")] == ["other"]
