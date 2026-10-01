"""``replace_database`` against a real Postgres: a pre-upgrade dump over an upgraded database.

Reproduces the failure it exists for. ``pg_dump --clean --if-exists`` drops only the tables it knows,
so a table the newer release added keeps a foreign key into an older table and the dump's
``DROP TABLE`` stops the load. Skipped when ``pg_dump``/``psql`` are not on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import psycopg
import pytest

from docsgpt.deploy.commands import replace_database
from docsgpt.deploy.docker import DeployError

pytestmark = pytest.mark.skipif(
    not (shutil.which("pg_dump") and shutil.which("psql")), reason="needs the pg_dump and psql clients"
)


@pytest.fixture
def server(postgresql_proc):
    """Connection details for the session's throwaway Postgres cluster, and a fresh database name."""
    info = {
        "host": postgresql_proc.host,
        "port": postgresql_proc.port,
        "user": postgresql_proc.user,
        "password": postgresql_proc.password or "",
    }
    name = f"restore_{uuid.uuid4().hex[:8]}"
    yield info, name
    with psycopg.connect(dbname="postgres", autocommit=True, **info) as conn:
        for db in (name, f"{name}_before_restore"):
            conn.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")


def _sql(info, database, *statements):
    with psycopg.connect(dbname=database, autocommit=True, **info) as conn:
        for statement in statements:
            conn.execute(statement)


def _client_env(info):
    """The current environment (PATH, LD_LIBRARY_PATH for the client binaries) plus the connection."""
    return {**os.environ, "PGHOST": info["host"], "PGPORT": str(info["port"]), "PGUSER": info["user"],
            "PGPASSWORD": info["password"]}


def _psql_load(info, database, dump):
    """What the stack runs: psql with ON_ERROR_STOP, the dump on stdin."""
    result = subprocess.run(
        ["psql", "--quiet", "--set", "ON_ERROR_STOP=on", "-d", database],
        input=dump, text=True, capture_output=True, env=_client_env(info),
    )
    if result.returncode:
        raise DeployError(result.stderr.strip())


def _upgraded_database_with_old_dump(info, name):
    """An 'old' schema dumped, then 'upgraded' with a new table referencing an old one."""
    _sql(info, "postgres", f"CREATE DATABASE {name}")
    _sql(info, name,
         "CREATE TABLE conversation_messages (id int PRIMARY KEY, body text)",
         "INSERT INTO conversation_messages VALUES (1, 'from the backup')")
    dump = subprocess.run(
        ["pg_dump", "--clean", "--if-exists", "-d", name],
        capture_output=True, text=True, check=True, env=_client_env(info),
    ).stdout
    _sql(info, name,
         "INSERT INTO conversation_messages VALUES (2, 'written after the backup')",
         "CREATE TABLE request_traces (id int PRIMARY KEY, "
         "message_id int REFERENCES conversation_messages(id))",
         "INSERT INTO request_traces VALUES (1, 2)")
    return dump


def _tables(info, name):
    with psycopg.connect(dbname=name, **info) as conn:
        rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1").fetchall()
    return [row[0] for row in rows]


def _databases(info):
    with psycopg.connect(dbname="postgres", **info) as conn:
        return {row[0] for row in conn.execute("SELECT datname FROM pg_database").fetchall()}


def test_loading_over_the_upgraded_database_fails(server):
    """The bug: the dump's DROP TABLE conversation_messages is blocked by request_traces' foreign key."""
    info, name = server
    dump = _upgraded_database_with_old_dump(info, name)
    with pytest.raises(DeployError, match="other objects depend on it"):
        _psql_load(info, name, dump)


def test_the_backup_replaces_the_upgraded_database(server):
    info, name = server
    dump = _upgraded_database_with_old_dump(info, name)

    replace_database(lambda db, statements: _sql(info, db, *statements),
                     lambda: _psql_load(info, name, dump), name, info["user"])

    assert _tables(info, name) == ["conversation_messages"]
    with psycopg.connect(dbname=name, **info) as conn:
        assert conn.execute("SELECT body FROM conversation_messages").fetchall() == [("from the backup",)]
    assert f"{name}_before_restore" not in _databases(info)


def test_a_failed_load_leaves_the_current_database_in_place(server):
    info, name = server
    _upgraded_database_with_old_dump(info, name)

    with pytest.raises(DeployError):
        replace_database(lambda db, statements: _sql(info, db, *statements),
                         lambda: _psql_load(info, name, "SELECT no_such_function();"), name, info["user"])

    assert _tables(info, name) == ["conversation_messages", "request_traces"]
    assert f"{name}_before_restore" not in _databases(info)
