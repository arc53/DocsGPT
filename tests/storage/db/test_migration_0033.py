"""Migration round-trip test for 0033_quotas."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


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


_0033 = "0033_quotas"
_0032 = "0032_personal_access_tokens"


def _table_exists(conn, table: str) -> bool:
    return conn.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}).scalar() is not None


def _insert_policy(conn, **values) -> None:
    cols = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    conn.execute(text(f"INSERT INTO quota_policies ({cols}) VALUES ({params})"), values)


class TestMigration0033RoundTrip:
    def test_single_head(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        assert len(_alembic_heads(url)) == 1

    def test_head_has_quota_schema(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0033
            assert _table_exists(conn, "quota_policies")
            assert _column_exists(conn, "token_usage", "cost")

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0032)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0032
            assert not _table_exists(conn, "quota_policies")
            assert not _column_exists(conn, "token_usage", "cost")
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _table_exists(conn, "quota_policies")
            assert _column_exists(conn, "token_usage", "cost")

    def test_upgrade_tolerates_an_existing_cost_column(self, pg_engine):
        """A database that already carries ``token_usage.cost`` upgrades cleanly."""
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0032)
        with pg_engine.begin() as conn:
            conn.execute(text("ALTER TABLE token_usage ADD COLUMN cost NUMERIC(12,8) NOT NULL DEFAULT 0"))
            conn.execute(
                text(
                    "INSERT INTO token_usage (user_id, prompt_tokens, generated_tokens, cost) "
                    "VALUES ('u-mig33', 10, 1, 0.5)"
                )
            )
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            cost = conn.execute(text("SELECT cost FROM token_usage WHERE user_id = 'u-mig33'")).scalar()
            assert float(cost) == 0.5


class TestQuotaPolicyConstraints:
    def test_one_row_per_subject_and_bucket(self, pg_conn):
        _insert_policy(pg_conn, scope="instance", token_limit=10)
        with pytest.raises(IntegrityError):
            with pg_conn.begin_nested():
                _insert_policy(pg_conn, scope="instance", token_limit=20)
        _insert_policy(pg_conn, scope="instance", bucket="agent", token_limit=20)

    @pytest.mark.parametrize(
        "values",
        [
            {"scope": "instance", "subject_id": "u1"},
            {"scope": "user"},
            {"scope": "user", "subject_id": "u1", "token_limit": 5, "token_unlimited": True},
            {"scope": "user", "subject_id": "u1", "cost_limit_usd": 5, "cost_unlimited": True},
            {"scope": "user", "subject_id": "u1", "token_limit": -1},
            {"scope": "user", "subject_id": "u1", "bucket": "nope"},
            {"scope": "org", "subject_id": "u1"},
        ],
    )
    def test_invalid_rows_rejected(self, pg_conn, values):
        with pytest.raises(IntegrityError):
            with pg_conn.begin_nested():
                _insert_policy(pg_conn, **values)

    def test_deleting_a_team_removes_its_policies(self, pg_conn):
        team_id = pg_conn.execute(
            text("INSERT INTO teams (name, slug, owner_id) VALUES ('Q', 'q-mig33', 'owner') RETURNING id")
        ).scalar()
        _insert_policy(pg_conn, scope="team", subject_id=str(team_id), token_limit=10)
        _insert_policy(pg_conn, scope="user", subject_id=str(team_id), token_limit=10)
        pg_conn.execute(text("DELETE FROM teams WHERE id = :id"), {"id": team_id})
        scopes = pg_conn.execute(
            text("SELECT scope FROM quota_policies WHERE subject_id = :id"), {"id": str(team_id)}
        ).scalars().all()
        assert scopes == ["user"]
