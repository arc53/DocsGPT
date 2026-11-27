"""Processes that migrate one empty database at the same time all succeed.

``docsgpt dev`` (and any deployment) boots the API and the worker together, and each runs
``alembic upgrade head`` on start. On an empty database both used to create ``alembic_version``
and the loser crashed with a unique violation on ``pg_type``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

pytestmark = pytest.mark.integration

PROCESSES = 3
EMPTY_DB = "docsgpt_concurrent_boot"


def _alembic_ini() -> Path:
    return Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"


def _admin(info) -> psycopg.Connection:
    return psycopg.connect(
        host=info.host, port=info.port, user=info.user, password=info.password or None,
        dbname=info.dbname, autocommit=True,
    )


@pytest.fixture()
def empty_database(postgresql):
    info = postgresql.info
    with _admin(info) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(EMPTY_DB)))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(EMPTY_DB)))
    yield f"postgresql+psycopg://{info.user}:{info.password or ''}@{info.host}:{info.port}/{EMPTY_DB}"
    with _admin(info) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(EMPTY_DB)))


def test_concurrent_upgrades_of_an_empty_database_all_succeed(empty_database):
    env = {**os.environ, "POSTGRES_URI": empty_database}
    command = [sys.executable, "-m", "alembic", "-c", str(_alembic_ini()), "upgrade", "head"]
    runs = [
        subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for _ in range(PROCESSES)
    ]
    outputs = [run.communicate(timeout=300)[0] for run in runs]
    failed = [
        [line for line in output.splitlines() if "Error" in line][-3:]
        for run, output in zip(runs, outputs)
        if run.returncode != 0
    ]
    assert not failed, failed

    heads = subprocess.check_output(
        [sys.executable, "-m", "alembic", "-c", str(_alembic_ini()), "heads"], env=env, text=True, timeout=60
    ).split()[0]
    with psycopg.connect(empty_database.replace("+psycopg", "")) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [(heads,)]
