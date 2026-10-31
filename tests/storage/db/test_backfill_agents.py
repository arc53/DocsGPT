"""``_backfill_agents`` in ``scripts/db/backfill.py``: legacy Mongo agents' prompt presets."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.db.backfill import _backfill_agents  # noqa: E402


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


def ObjectId() -> str:  # noqa: N802 - stands in for bson's, which pymongo (not installed) ships
    return secrets.token_hex(12)


def _mongo(agents):
    return {"agents": _Collection(agents)}


def _run(conn, agents):
    return _backfill_agents(conn=conn, mongo_db=_mongo(agents), batch_size=10, dry_run=False)


def _prompt_columns(conn):
    rows = conn.execute(text("SELECT name, prompt_id, prompt_preset FROM agents ORDER BY name")).fetchall()
    return {name: (str(pid) if pid else None, preset) for name, pid, preset in rows}


def test_stored_presets_land_in_prompt_preset(pg_conn):
    agents = [
        {"_id": ObjectId(), "user": "u", "name": "creative", "prompt_id": "creative"},
        {"_id": ObjectId(), "user": "u", "name": "strict", "prompt_id": "strict"},
        {"_id": ObjectId(), "user": "u", "name": "default", "prompt_id": "default"},
        {"_id": ObjectId(), "user": "u", "name": "none"},
    ]
    _run(pg_conn, agents)
    assert _prompt_columns(pg_conn) == {
        "creative": (None, "creative"),
        "default": (None, None),
        "none": (None, None),
        "strict": (None, "strict"),
    }


def test_a_rerun_sets_both_prompt_columns_together(pg_conn):
    prompt = pg_conn.execute(
        text("INSERT INTO prompts (user_id, name, content, legacy_mongo_id) VALUES ('u', 'p', 'c', :oid) RETURNING id"),
        {"oid": "507f1f77bcf86cd799439011"},
    ).scalar()
    oid = ObjectId()
    _run(pg_conn, [{"_id": oid, "user": "u", "name": "a", "prompt_id": "strict"}])
    # The Mongo agent moved to a custom prompt: the preset must clear in the same write.
    _run(pg_conn, [{"_id": oid, "user": "u", "name": "a", "prompt_id": "507f1f77bcf86cd799439011"}])
    assert _prompt_columns(pg_conn) == {"a": (str(prompt), None)}
    _run(pg_conn, [{"_id": oid, "user": "u", "name": "a", "prompt_id": "creative"}])
    assert _prompt_columns(pg_conn) == {"a": (None, "creative")}
