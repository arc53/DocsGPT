"""0028 index the per-agent log lookups so /api/get_user_logs stops timing out.

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
they are not instant; CONCURRENTLY keeps them non-blocking. Because a cancelled
concurrent build leaves an INVALID index behind that ``IF NOT EXISTS`` would
then skip forever, each build first clears such a leftover — see
``_rebuild_if_invalid``. Idempotent both ways.

Revision ID: 0028_user_logs_agent_lookup_idx
Revises: 0027_schedule_run_error_types
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0028_user_logs_agent_lookup_idx"
down_revision: Union[str, None] = "0027_schedule_run_error_types"
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


def _rebuild_if_invalid(name: str) -> None:
    """Drop ``name`` only when a previous concurrent build left it INVALID.

    A failed/cancelled ``CREATE INDEX CONCURRENTLY`` does not roll back — it
    leaves an index in the catalog with ``indisvalid = false`` that still owns
    the name. ``IF NOT EXISTS`` then skips it forever, so the migration reports
    success while the planner refuses to use the index: a silent no-op. Clearing
    it first makes the rebuild actually happen.

    The check is deliberately conditional rather than an unconditional drop
    (0018's approach): the ``user_logs`` builds detoast ~1.16 GB each, so
    re-running this migration against a healthy database should not pay that
    cost again. ``to_regclass`` returns NULL for a name that doesn't exist, so
    the first run selects no row and skips the drop.
    """
    invalid = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT NOT indisvalid FROM pg_index "
            f"WHERE indexrelid = to_regclass('{name}')"
        )
        .scalar()
    )
    if invalid:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name};")


def upgrade() -> None:
    # CONCURRENTLY can't run inside a transaction; the autocommit block lets
    # each build run without locking out writers on a multi-GB live table.
    for name, target, predicate in _INDEXES:
        with op.get_context().autocommit_block():
            _rebuild_if_invalid(name)
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON {target} WHERE {predicate};"
            )


def downgrade() -> None:
    for name, _target, _predicate in reversed(_INDEXES):
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name};")
