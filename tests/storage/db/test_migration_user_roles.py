"""Guards for the 0020_user_roles migration.

The single-head assertion catches a branched Alembic history (e.g. a new
migration numbered off the wrong parent), which would wedge ``upgrade head``.
"""

from __future__ import annotations

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory


@pytest.mark.unit
def test_single_migration_head(_alembic_ini_path):
    script = ScriptDirectory.from_config(Config(str(_alembic_ini_path)))
    heads = script.get_heads()
    assert len(heads) == 1, f"expected one head, found {heads}"


@pytest.mark.unit
def test_user_roles_revision_chains_off_0019(_alembic_ini_path):
    script = ScriptDirectory.from_config(Config(str(_alembic_ini_path)))
    rev = script.get_revision("0020_user_roles")
    assert rev is not None
    assert rev.down_revision == "0019_agent_slug"


class TestUserRolesSchema:
    def test_table_exists_after_migration(self, pg_conn):
        from sqlalchemy import text

        cols = pg_conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'user_roles'"
            )
        ).fetchall()
        names = {c[0] for c in cols}
        assert names == {"user_id", "role", "source", "granted_by", "granted_at"}

    def test_role_check_rejects_unknown_role(self, pg_conn):
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            pg_conn.execute(
                text("INSERT INTO user_roles (user_id, role) VALUES ('x', 'superuser')")
            )

    def test_source_check_rejects_unknown_source(self, pg_conn):
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            pg_conn.execute(
                text(
                    "INSERT INTO user_roles (user_id, role, source) "
                    "VALUES ('x', 'admin', 'sso')"
                )
            )
