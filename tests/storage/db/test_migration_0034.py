"""Migration round-trip test for 0034_auth_events_actor_target."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration


def _alembic_ini() -> Path:
    return Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"


def _run_alembic(url: str, *args: str) -> None:
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(_alembic_ini()), *args],
        timeout=60,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _alembic_heads(url: str) -> list[str]:
    out = subprocess.check_output(
        [sys.executable, "-m", "alembic", "-c", str(_alembic_ini()), "heads"],
        timeout=60,
        env={**os.environ, "POSTGRES_URI": url},
        text=True,
    )
    return [line for line in out.splitlines() if line.strip()]


def _alembic_version(conn) -> str:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c AND table_schema = 'public'"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None


def _index_exists(conn, name: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = :n"),
        {"n": name},
    ).fetchone()
    return row is not None


_0034 = "0034_auth_events_actor_target"
_0033 = "0033_quotas"


class TestMigration0034RoundTrip:
    def test_single_head(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        assert len(_alembic_heads(url)) == 1

    def test_head_has_actor_target_columns(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0034
            assert _column_exists(conn, "auth_events", "actor_id")
            assert _column_exists(conn, "auth_events", "target_id")

    def test_head_has_feed_indexes(self, pg_engine):
        """The global feed orders by created_at with no user filter."""
        with pg_engine.connect() as conn:
            assert _index_exists(conn, "auth_events_created_idx")
            assert _index_exists(conn, "auth_events_event_created_idx")
            assert _index_exists(conn, "auth_events_actor_idx")

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0033)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0033
            assert not _column_exists(conn, "auth_events", "actor_id")
            assert not _column_exists(conn, "auth_events", "target_id")
            assert not _index_exists(conn, "auth_events_created_idx")
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0034
            assert _column_exists(conn, "auth_events", "actor_id")

    def test_backfill_reads_actor_out_of_metadata(self, pg_engine):
        """An admin action filed under its target keeps the acting admin."""
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0033)
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO auth_events (user_id, event, metadata) VALUES "
                    "('victim', 'admin_user_deactivated', '{\"by\": \"admin-1\"}'::jsonb), "
                    "('grantee', 'role_granted', '{\"granted_by\": \"admin-2\"}'::jsonb), "
                    "('someone', 'oidc_login', '{}'::jsonb), "
                    "('actor-3', 'team.create', '{\"team_id\": \"t1\"}'::jsonb)"
                )
            )
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            rows = dict(
                conn.execute(
                    text(
                        "SELECT event, actor_id || '|' || COALESCE(target_id, '-') "
                        "FROM auth_events WHERE user_id IN "
                        "('victim', 'grantee', 'someone', 'actor-3')"
                    )
                ).fetchall()
            )
        assert rows["admin_user_deactivated"] == "admin-1|victim"
        assert rows["role_granted"] == "admin-2|grantee"
        # Self-service events: the user is both actor and target.
        assert rows["oidc_login"] == "someone|someone"
        # Team events were always filed under the actor; they have no user target.
        assert rows["team.create"] == "actor-3|-"

    def test_backfill_scopes_quota_policy_targets(self, pg_engine):
        """Only a user-scoped quota policy has a user target.

        Instance and team policies are filed under the acting admin, so
        backfilling ``target_id = user_id`` would claim the admin was acted on.
        """
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0033)
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO auth_events (user_id, event, metadata) VALUES "
                    "('admin-q', 'quota_policy_set', "
                    " '{\"by\": \"admin-q\", \"scope\": \"instance\"}'::jsonb), "
                    "('admin-q2', 'quota_policy_deleted', "
                    " '{\"by\": \"admin-q2\", \"scope\": \"team\"}'::jsonb), "
                    "('capped-user', 'quota_policy_set', "
                    " '{\"by\": \"admin-q3\", \"scope\": \"user\"}'::jsonb)"
                )
            )
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            rows = dict(
                conn.execute(
                    text(
                        "SELECT user_id, actor_id || '|' || COALESCE(target_id, '-') "
                        "FROM auth_events WHERE user_id IN "
                        "('admin-q', 'admin-q2', 'capped-user')"
                    )
                ).fetchall()
            )
        assert rows["admin-q"] == "admin-q|-"
        assert rows["admin-q2"] == "admin-q2|-"
        assert rows["capped-user"] == "admin-q3|capped-user"
