"""0005 ingest_chunk_progress.attempt_id — per-attempt resume scoping.

Without this column, a completed checkpoint row poisoned every later
embed call on the same ``source_id``: a sync after an upload finished
read the upload's terminal ``last_index`` and either embedded zero
chunks (if new ``total_docs <= last_index + 1``) or stacked new chunks
on top of the old vectors (if ``total_docs > last_index + 1``).

``attempt_id`` is stamped from ``self.request.id`` (Celery's stable
task id, which survives ``acks_late`` retries of the same task but
differs across separate task invocations). The repository's
``init_progress`` upsert resets ``last_index`` / ``embedded_chunks``
when the incoming ``attempt_id`` differs from the stored one — so a
fresh sync starts from chunk 0 while a retry of the same task resumes
from the last checkpointed chunk.

Revision ID: 0005_ingest_attempt_id
Revises: 0004_durability_foundation
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0005_ingest_attempt_id"
down_revision: Union[str, None] = "0004_durability_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE ingest_chunk_progress
            ADD COLUMN attempt_id TEXT;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ingest_chunk_progress DROP COLUMN IF EXISTS attempt_id;"
    )
