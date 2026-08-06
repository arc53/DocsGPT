"""0027 index the per-agent log lookups so /api/get_user_logs stops timing out.

The per-agent Logs timeline filters ``user_logs`` on two JSONB keys
(``data->>'api_key'`` / ``data->>'agent_id'``) and ``stack_logs`` on
``(agent_id OR api_key)``. None of those had a usable index, so both branches
seq-scanned.

``user_logs`` is the expensive one, and not for the obvious reason: its heap is
only ~107 MB but ``data`` is a ~1.16 GB TOAST, and filtering on a JSONB key
forces a detoast of *every* row. Measured on prod (99,535 rows): **618,809
buffer accesses to return 6,012 rows — 4.5 s warm, >90 s cold**, against a 30 s
``STATEMENT_TIMEOUT_MS``. That warm/cold spread is why the endpoint failed
intermittently rather than always. (``stack_logs`` seq-scans too but stays
~38 ms: its filter columns live in the heap, so its own 1.9 GB TOAST is never
touched.)

The two expression indexes turn that detoast scan into a direct lookup. They
also give the planner statistics on the expressions, which it badly lacked —
it estimated 974 rows where the truth was 6,012.

``stack_logs (api_key)`` matters for a subtler reason: 0026 added
``ix_stack_logs_agent_id`` and it works well in isolation (1,759 buffers /
11.6 ms), but the query ORs it against the unindexed ``api_key`` and Postgres
cannot BitmapOr when only one side is indexed — so the new index was being
bypassed entirely. Indexing the second arm is what actually activates it.

Indexes are built ``CONCURRENTLY`` in autocommit blocks (following 0018): a
plain CREATE INDEX would take an ACCESS EXCLUSIVE lock on a 1.3 GB table on a
live database. The ``user_logs`` builds each detoast the full ~1.16 GB once, so
they are not instant; CONCURRENTLY keeps them non-blocking. Idempotent both
ways.

Revision ID: 0027_user_logs_agent_lookup_idx
Revises: 0026_stack_logs_agent_id
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0027_user_logs_agent_lookup_idx"
down_revision: Union[str, None] = "0026_stack_logs_agent_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Partial: only rows that actually carry the key are ever looked up by it, and
# most user_logs rows (owner chats) carry neither, so this keeps the indexes
# small without changing which rows they can answer for.
_INDEXES = (
    (
        "user_logs_data_api_key_idx",
        "user_logs ((data->>'api_key'))",
        "(data->>'api_key') IS NOT NULL",
    ),
    (
        "user_logs_data_agent_id_idx",
        "user_logs ((data->>'agent_id'))",
        "(data->>'agent_id') IS NOT NULL",
    ),
    (
        "stack_logs_api_key_idx",
        "stack_logs (api_key)",
        "api_key IS NOT NULL",
    ),
)


def upgrade() -> None:
    # CONCURRENTLY can't run inside a transaction; the autocommit block lets
    # each build run without locking out writers on a multi-GB live table.
    for name, target, predicate in _INDEXES:
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON {target} WHERE {predicate};"
            )


def downgrade() -> None:
    for name, _target, _predicate in reversed(_INDEXES):
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name};")
