"""``_backfill_agent_folders`` in ``scripts/db/backfill.py``: one tree per owner, sibling names made unique."""

from __future__ import annotations

import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.db.backfill import _backfill_agent_folders  # noqa: E402


class _Cursor(list):
    def batch_size(self, _n):
        return self

    def close(self):
        pass


class _Collection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *_args, **_kwargs):
        return _Cursor(self._docs)


def _oid() -> str:
    return secrets.token_hex(12)


def _run(conn, docs):
    return _backfill_agent_folders(
        conn=conn, mongo_db={"agent_folders": _Collection(docs)}, batch_size=2, dry_run=False
    )


def _tree(conn) -> dict:
    """``legacy id -> (name, parent legacy id)``."""
    rows = conn.execute(
        text(
            "SELECT f.legacy_mongo_id, f.name, p.legacy_mongo_id FROM folders f "
            "LEFT JOIN folders p ON p.id = f.parent_id"
        )
    ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def _at(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


def test_repeated_and_blank_sibling_names_become_unique(pg_conn):
    top, child_a, child_b, blank_a, blank_b, other_user = (_oid() for _ in range(6))
    docs = [
        {"_id": top, "user": "u", "name": "Docs", "created_at": _at(1)},
        # Two children named alike under one parent, and one top-level twin of the parent.
        {"_id": child_a, "user": "u", "name": "Guides", "parent_id": top, "created_at": _at(2)},
        {"_id": child_b, "user": "u", "name": "guides", "parent_id": top, "created_at": _at(3)},
        {"_id": blank_a, "user": "u", "name": "", "created_at": _at(4)},
        {"_id": blank_b, "user": "u", "name": "  ", "created_at": _at(5)},
        {"_id": other_user, "user": "v", "name": "Docs", "created_at": _at(6)},
    ]
    result = _run(pg_conn, docs)
    assert result["written"] == 6 and result["parent_links_resolved"] == 2
    expected = {
        top: ("Docs", None),
        child_a: ("Guides", top),
        child_b: ("guides (2)", top),
        blank_a: ("Folder", None),
        blank_b: ("Folder (2)", None),
        other_user: ("Docs", None),
    }
    assert _tree(pg_conn) == expected
    # A re-run lands on the same names.
    _run(pg_conn, docs)
    assert _tree(pg_conn) == expected


def test_a_name_already_taken_in_postgres_is_kept(pg_conn):
    pg_conn.execute(text("INSERT INTO folders (user_id, name) VALUES ('u', 'Docs')"))
    oid = _oid()
    _run(pg_conn, [{"_id": oid, "user": "u", "name": "docs"}])
    assert _tree(pg_conn)[oid] == ("docs (2)", None)
