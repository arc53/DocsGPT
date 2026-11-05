"""Migration round-trip test for 0055_content_scores."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


pytestmark = pytest.mark.integration

_0054 = "0054_decision_usage"


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _score(conn, scorer: str = "injection:v:q1:w512o50") -> None:
    conn.execute(
        text(
            "INSERT INTO content_scores (content_hash, scorer, p, windows_scored, windows_total) "
            "VALUES ('h', :scorer, 0.97, 1, 1)"
        ),
        {"scorer": scorer},
    )


def _has_table(conn) -> bool:
    return conn.execute(text("SELECT to_regclass('public.content_scores')")).scalar() is not None


def _has_item_ref(conn) -> bool:
    return conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'guardrail_events' AND column_name = 'item_ref'"
        )
    ).scalar() is not None


class TestMigration0055RoundTrip:
    def test_head_keys_a_score_by_text_hash_and_scorer(self, pg_engine):
        with pg_engine.begin() as conn:
            _score(conn)
            _score(conn, scorer="injection:v2:q1:w512o50")
            row = conn.execute(text("SELECT created_at, last_seen_at FROM content_scores LIMIT 1")).one()
            assert row.created_at is not None and row.last_seen_at is not None
        with pytest.raises(IntegrityError, match="content_scores_pkey"):
            with pg_engine.begin() as conn:
                _score(conn)

    def test_head_adds_a_nullable_item_ref_to_guardrail_events(self, pg_engine):
        with pg_engine.begin() as conn:
            assert _has_item_ref(conn)
            conn.execute(
                text(
                    "INSERT INTO guardrail_events (stage, check_name, detector_type, action, outcome, item_ref) "
                    "VALUES ('retrieval', 'injection_model', 'INJECTION_MODEL', 'block', 'triggered', 'chunk:s:k')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO guardrail_events (stage, check_name, detector_type, action, outcome) "
                    "VALUES ('input', 'injection', 'INJECTION', 'flag', 'triggered')"
                )
            )

    def test_downgrade_drops_the_table_and_the_column(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.begin() as conn:
            _score(conn)
        _run_alembic(url, "downgrade", _0054)
        with pg_engine.connect() as conn:
            assert not _has_table(conn) and not _has_item_ref(conn)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _has_table(conn) and _has_item_ref(conn)
