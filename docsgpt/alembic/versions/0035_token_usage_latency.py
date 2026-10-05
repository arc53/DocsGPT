"""0035 token usage latency — how long the call took, and time to first token.

Nothing in the schema recorded how long an LLM call took. The wrappers in
``docsgpt/usage.py`` already measured it for the ``llm_gen_finished`` /
``llm_stream_finished`` log lines and then threw the number away, so an
operator could see what an instance spent but never how slow it was.

Two columns, both nullable because both are genuinely unknown for some rows:

* ``duration_ms`` — wall-clock for the whole call.
* ``ttft_ms`` — time to the first streamed chunk. NULL on non-streaming calls
  and on streams that failed before yielding anything, which is the honest
  reading: "no first token", not "instant".

NULL also means "written before this migration", so historical rows never
drag a p50 towards zero.

Idempotent both ways.

Revision ID: 0035_token_usage_latency
Revises: 0034_auth_events_actor_target
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0035_token_usage_latency"
down_revision: Union[str, None] = "0034_auth_events_actor_target"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS duration_ms INTEGER;")
    op.execute("ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS ttft_ms INTEGER;")


def downgrade() -> None:
    op.execute("ALTER TABLE token_usage DROP COLUMN IF EXISTS ttft_ms;")
    op.execute("ALTER TABLE token_usage DROP COLUMN IF EXISTS duration_ms;")
