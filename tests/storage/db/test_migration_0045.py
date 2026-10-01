"""Migration round-trip test for 0045_attachment_archive_idx."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0044 = "0044_attachment_content_hash"
_INDEX = "attachments_archive_processing_idx"


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _index_def(conn):
    return conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname = :name"),
        {"name": _INDEX},
    ).scalar()


class TestMigration0045RoundTrip:
    def test_head_indexes_only_zips_still_processing(self, pg_engine):
        with pg_engine.connect() as conn:
            definition = _index_def(conn)
        assert definition is not None
        assert "archive" in definition and "processing" in definition

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0044)
        with pg_engine.connect() as conn:
            assert _index_def(conn) is None
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _index_def(conn) is not None
