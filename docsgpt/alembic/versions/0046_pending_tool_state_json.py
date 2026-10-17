"""0046 pending tool state as json — keep a paused turn's key order.

A paused tool turn is stored in ``pending_tool_state`` and replayed to the
model when it resumes: its tool schemas, tool calls, messages and output
schema. ``jsonb`` re-sorts object keys (shorter keys first), so a resumed
round rebuilt its tools block in a different order from the paused call's
(a ``query, k`` parameter list came back as ``k, query``) and the provider
prompt cache missed from just after the system prompt onward. ``json``
stores the text as written, so the payload replays byte for byte.

Every JSON column here feeds what the model sees, so all six change. Nothing
queries inside them (only ``status``, ``expires_at`` and ``resumed_at`` are
filtered on), so losing the ``jsonb`` operators costs nothing. Rows live
about 30 minutes and the table stays small, so the rewrite under the
``ALTER TABLE`` lock is brief. Rows written before the upgrade keep their
already sorted order; they age out with their TTL.

Idempotent both ways: only columns still of the other type are altered.

Revision ID: 0046_pending_tool_state_json
Revises: 0045_attachment_archive_idx
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0046_pending_tool_state_json"
down_revision: Union[str, None] = "0045_attachment_archive_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "pending_tool_state"
_COLUMNS = (
    "messages",
    "pending_tool_calls",
    "tools_dict",
    "tool_schemas",
    "agent_config",
    "client_tools",
)


def _retype(source: str, target: str) -> None:
    """Change every listed column still of type ``source`` to ``target``.

    Args:
        source: The column type to convert from (``json`` or ``jsonb``).
        target: The column type to convert to.
    """
    names = ", ".join(f"'{name}'" for name in _COLUMNS)
    rows = op.get_bind().exec_driver_sql(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema = current_schema() AND table_name = '{_TABLE}' "
        f"AND column_name IN ({names}) AND data_type = '{source}'"
    )
    pending = {row[0] for row in rows}
    columns = [name for name in _COLUMNS if name in pending]
    if not columns:
        return
    clauses = ", ".join(f"ALTER COLUMN {name} TYPE {target} USING {name}::{target}" for name in columns)
    op.execute(f"ALTER TABLE {_TABLE} {clauses};")


def upgrade() -> None:
    _retype("jsonb", "json")


def downgrade() -> None:
    _retype("json", "jsonb")
