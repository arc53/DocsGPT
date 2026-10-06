"""Migration round-trip test for 0049_push_and_unread."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0048 = "0048_monitors_and_trigger_links"


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _state(conn) -> tuple[bool, bool]:
    table = conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' "
            "AND table_name = 'push_subscriptions'"
        )
    ).fetchone()
    column = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'conversations' "
            "AND column_name = 'unread_at'"
        )
    ).fetchone()
    return table is not None, column is not None


class TestMigration0049RoundTrip:
    def test_head_has_the_table_and_the_column(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _state(conn) == (True, True)

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0048)
        with pg_engine.connect() as conn:
            assert _state(conn) == (False, False)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _state(conn) == (True, True)

    def test_endpoint_is_unique(self, pg_engine):
        with pg_engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) "
                    "VALUES ('u1', 'https://x', 'p', 'a')"
                )
            )
            with pytest.raises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) "
                        "VALUES ('u2', 'https://x', 'p', 'a')"
                    )
                )
