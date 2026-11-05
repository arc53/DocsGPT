"""Agent prompt presets survive an idempotent migration round trip."""

import importlib
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from docsgpt.storage.db.repositories.agents import AgentsRepository


def _columns(conn) -> set:
    return {
        r[0]
        for r in conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'agents'")
        )
    }


def test_round_trip_adds_and_drops_the_preset(pg_conn):
    migration = importlib.import_module("docsgpt.alembic.versions.0060_agent_prompt_preset")
    repo = AgentsRepository(pg_conn)
    with patch.object(migration, "op", Operations(MigrationContext.configure(pg_conn))):
        migration.upgrade()
        migration.upgrade()
        row = repo.create("u", "a", "draft", prompt_id="creative")
        assert repo.get(str(row["id"]), "u")["prompt_id"] == "creative"
        with pytest.raises(IntegrityError), pg_conn.begin_nested():
            pg_conn.execute(text("UPDATE agents SET prompt_preset = 'bogus'"))
        migration.downgrade()
        migration.downgrade()
        assert "prompt_preset" not in _columns(pg_conn)
        # The agent survives on the default prompt.
        assert repo.get(str(row["id"]), "u")["prompt_id"] is None
        migration.upgrade()
        assert "prompt_preset" in _columns(pg_conn)
        assert pg_conn.execute(text("SELECT count(*) FROM agents")).scalar() == 1


def _indexes(conn) -> set:
    return {
        r[0]
        for r in conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'agents'"))
    }


def test_round_trip_adds_and_drops_the_usage_indexes(pg_conn):
    migration = importlib.import_module("docsgpt.alembic.versions.0060_agent_prompt_preset")
    with patch.object(migration, "op", Operations(MigrationContext.configure(pg_conn))):
        migration.upgrade()
        migration.upgrade()
        assert {"agents_tools_gin_idx", "agents_extra_source_ids_gin_idx"} <= _indexes(pg_conn)
        migration.downgrade()
        migration.downgrade()
        assert not {"agents_tools_gin_idx", "agents_extra_source_ids_gin_idx"} & _indexes(pg_conn)
        migration.upgrade()
        assert {"agents_tools_gin_idx", "agents_extra_source_ids_gin_idx"} <= _indexes(pg_conn)


def test_upgrade_lowercases_legacy_tool_ids(pg_conn):
    migration = importlib.import_module("docsgpt.alembic.versions.0060_agent_prompt_preset")
    upper = "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"
    other = "11111111-2222-4333-8444-555555555555"
    pg_conn.execute(
        text(
            "INSERT INTO agents (user_id, name, status, tools) VALUES "
            "('u', 'legacy', 'draft', CAST(:legacy AS jsonb)), ('u', 'clean', 'draft', CAST(:clean AS jsonb)), "
            "('u', 'odd', 'draft', CAST('{}' AS jsonb))"
        ),
        {
            # An upper-case id next to its lower-case twin, a non-UUID id and a non-string entry.
            "legacy": f'["{upper}", "{other}", "{upper.lower()}", "Mongo507f1f77bcf86cd799439011", 7]',
            "clean": f'["{other}"]',
        },
    )
    with patch.object(migration, "op", Operations(MigrationContext.configure(pg_conn))):
        migration.upgrade()
        migration.upgrade()
    tools = dict(pg_conn.execute(text("SELECT name, tools FROM agents")).fetchall())
    assert tools["legacy"] == [upper.lower(), other, "Mongo507f1f77bcf86cd799439011", 7]
    assert tools["clean"] == [other]
    assert tools["odd"] == {}


def _trigger_when(conn) -> str:
    return conn.execute(
        text(
            "SELECT pg_get_triggerdef(oid) FROM pg_trigger "
            "WHERE tgrelid = 'agents'::regclass AND tgname = 'agents_set_updated_at'"
        )
    ).scalar()


def test_round_trip_swaps_the_updated_at_trigger(pg_conn):
    migration = importlib.import_module("docsgpt.alembic.versions.0060_agent_prompt_preset")
    with patch.object(migration, "op", Operations(MigrationContext.configure(pg_conn))):
        migration.upgrade()
        migration.upgrade()
        assert "last_used_at" in _trigger_when(pg_conn)
        migration.downgrade()
        migration.downgrade()
        assert "last_used_at" not in _trigger_when(pg_conn)
        assert "old.* IS DISTINCT FROM new.*" in _trigger_when(pg_conn)
        migration.upgrade()
        assert "last_used_at" in _trigger_when(pg_conn)


def _node_indexes(conn) -> set:
    return {
        r[0]
        for r in conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'workflow_nodes'"))
    }


_NODE_REF_INDEXES = {"workflow_nodes_tool_refs_gin_idx", "workflow_nodes_source_refs_gin_idx"}


def test_round_trip_adds_and_drops_the_node_ref_indexes(pg_conn):
    migration = importlib.import_module("docsgpt.alembic.versions.0060_agent_prompt_preset")
    with patch.object(migration, "op", Operations(MigrationContext.configure(pg_conn))):
        migration.upgrade()
        migration.upgrade()
        assert _NODE_REF_INDEXES <= _node_indexes(pg_conn)
        migration.downgrade()
        migration.downgrade()
        assert not _NODE_REF_INDEXES & _node_indexes(pg_conn)
        exists = "SELECT count(*) FROM pg_proc WHERE proname = 'workflow_node_refs'"
        assert pg_conn.execute(text(exists)).scalar() == 0
        migration.upgrade()
        assert _NODE_REF_INDEXES <= _node_indexes(pg_conn)


@pytest.mark.parametrize(
    ("config", "refs"),
    [
        ({"tools": ["AB-1", "c"]}, ["ab-1", "c"]),
        ({"config": {"tools": "One"}}, ["one"]),
        ({"config": "x", "tools": [7]}, ["7"]),
        ({"tools": {"a": 1}}, []),
        ({}, []),
    ],
)
def test_workflow_node_refs_reads_a_node_like_the_engine(pg_conn, config, refs):
    import json

    got = pg_conn.execute(
        text("SELECT workflow_node_refs(CAST(:c AS jsonb), 'tools')"), {"c": json.dumps(config)},
    ).scalar()
    assert got == refs


def test_the_used_by_workflow_lookup_can_use_the_node_ref_index(pg_conn):
    """The query's expression must be the indexed one, or the lookup scans every node."""
    from docsgpt.api.user import resource_usage

    sql = resource_usage._WORKFLOW_SQL.format(key="tools").format(
        match=resource_usage._WORKFLOW_MATCH.format(key="tools").format(ids=":full"),
    )
    pg_conn.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(
        r[0] for r in pg_conn.execute(text(f"EXPLAIN {sql}"), {"full": ["x"], "ids": ["x"]})
    )
    assert "workflow_nodes_tool_refs_gin_idx" in plan
