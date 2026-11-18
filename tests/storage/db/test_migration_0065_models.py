"""Team custom models in 0065: ``user_custom_models`` records who added each row, like the other item tables."""

import contextlib
import importlib
import uuid
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

_MIGRATION = "docsgpt.alembic.versions.0065_workspaces"


@contextlib.contextmanager
def _ops(conn):
    migration = importlib.import_module(_MIGRATION)
    with patch.object(migration, "op", Operations(MigrationContext.configure(conn))):
        yield migration


def _columns(conn, table: str) -> set:
    return {
        r[0]
        for r in conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table}
        )
    }


def _triggers(conn) -> set:
    return {r[0] for r in conn.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))}


def _principal(conn) -> str:
    """A team and its principal, inserted the way ``TeamsRepository.create`` does; the principal's id."""
    team = str(
        conn.execute(
            text("INSERT INTO teams (name, slug, owner_id) VALUES ('Ops', :s, 'alice') RETURNING id"),
            {"s": f"ops-{uuid.uuid4().hex[:6]}"},
        ).scalar()
    )
    principal = f"__team__{team}"
    conn.execute(
        text("INSERT INTO users (user_id, kind, team_id) VALUES (:u, 'team', CAST(:t AS uuid))"),
        {"u": principal, "t": team},
    )
    return principal


def _model(conn, owner: str, created_by=None) -> str:
    return str(
        conn.execute(
            text(
                "INSERT INTO user_custom_models (user_id, upstream_model_id, display_name, base_url, "
                "api_key_encrypted, created_by) VALUES (:u, 'm', 'M', 'https://x.example/v1', 'enc', :c) "
                "RETURNING id"
            ),
            {"u": owner, "c": created_by},
        ).scalar()
    )


def _created_by(conn, model_id: str):
    return conn.execute(
        text("SELECT created_by FROM user_custom_models WHERE id = CAST(:i AS uuid)"), {"i": model_id}
    ).scalar()


def test_head_schema(pg_conn):
    assert "created_by" in _columns(pg_conn, "user_custom_models")
    assert "user_custom_models_fill_created_by" in _triggers(pg_conn)


def test_created_by_defaults_to_a_person_owner_only(pg_conn):
    principal = _principal(pg_conn)
    personal = _model(pg_conn, "alice")
    unnamed = _model(pg_conn, principal)
    named = _model(pg_conn, principal, created_by="ana")
    assert _created_by(pg_conn, personal) == "alice"
    # A principal never becomes the creator; the route names the person.
    assert _created_by(pg_conn, unnamed) is None
    assert _created_by(pg_conn, named) == "ana"


def test_upgrade_backfills_created_by_without_touching_updated_at(pg_conn):
    with _ops(pg_conn) as migration:
        migration.downgrade()
        assert "created_by" not in _columns(pg_conn, "user_custom_models")
        model = str(
            pg_conn.execute(
                text(
                    "INSERT INTO user_custom_models (user_id, upstream_model_id, display_name, base_url, "
                    "api_key_encrypted) VALUES ('bob', 'm', 'M', 'https://x.example/v1', 'enc') RETURNING id"
                )
            ).scalar()
        )
        stamp = pg_conn.execute(
            text(
                "UPDATE user_custom_models SET updated_at = '2026-01-01' WHERE id = CAST(:i AS uuid) "
                "RETURNING updated_at"
            ),
            {"i": model},
        ).scalar()

        migration.upgrade()
        migration.upgrade()

        row = pg_conn.execute(
            text("SELECT created_by, updated_at FROM user_custom_models WHERE id = CAST(:i AS uuid)"), {"i": model}
        ).fetchone()
        assert tuple(row) == ("bob", stamp)
        assert "user_custom_models_fill_created_by" in _triggers(pg_conn)


def test_downgrade_drops_the_column_and_trigger(pg_conn):
    _model(pg_conn, "alice")
    with _ops(pg_conn) as migration:
        migration.downgrade()
        migration.downgrade()
        assert "created_by" not in _columns(pg_conn, "user_custom_models")
        assert "user_custom_models_fill_created_by" not in _triggers(pg_conn)
        migration.upgrade()
    assert "created_by" in _columns(pg_conn, "user_custom_models")
