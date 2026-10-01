"""Migration round-trip test for 0044_attachment_content_hash."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0043 = "0043_wiki_outside_edits"
_HASH = "a" * 64


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _column_exists(conn) -> bool:
    return conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = 'attachments' AND column_name = 'content_hash'"
        )
    ).fetchone() is not None


def _index_exists(conn) -> bool:
    return conn.execute(
        text(
            "SELECT 1 FROM pg_indexes WHERE schemaname = 'public' "
            "AND indexname = 'attachments_user_content_hash_idx'"
        )
    ).fetchone() is not None


class TestMigration0044RoundTrip:
    def test_head_has_column_and_index(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _column_exists(conn)
            assert _index_exists(conn)

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0043)
        with pg_engine.connect() as conn:
            assert not _column_exists(conn)
            assert not _index_exists(conn)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _column_exists(conn)
            assert _index_exists(conn)

    def test_upgrade_backfills_the_hash_from_metadata(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0043)
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO attachments (user_id, filename, upload_path, metadata) VALUES "
                    "('m44', 'hashed.pdf', '/a', CAST(:hashed AS jsonb)), "
                    "('m44', 'bogus.pdf', '/b', '{\"content_hash\": \"not-a-sha256\"}'::jsonb), "
                    "('m44', 'plain.pdf', '/c', '{}'::jsonb), "
                    "('m44', 'none.pdf', '/d', NULL)"
                ),
                {"hashed": f'{{"content_hash": "{_HASH}"}}'},
            )
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            rows = dict(
                conn.execute(
                    text("SELECT filename, content_hash FROM attachments WHERE user_id = 'm44'")
                ).fetchall()
            )
        assert rows == {
            "hashed.pdf": _HASH,
            "bogus.pdf": None,
            "plain.pdf": None,
            "none.pdf": None,
        }
