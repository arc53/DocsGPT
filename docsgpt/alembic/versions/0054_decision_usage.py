"""0054 decision usage — how often each feature called the decision model, per day.

* ``decision_usage``: one row per day, feature, mode (``local`` or ``api``),
  model version and call status, holding counters only: calls, states asked
  about, states answered, and the total wall and queue time. Each process
  writes increments to its day's rows once a minute (``docsgpt.decisions.usage``),
  so the key is the primary key and every write is an upsert. No text, user
  or request is stored; the guardrail journal records what fired, and these
  rows are its denominators.

``cleanup_decision_usage`` on beat deletes days past
``DECISION_USAGE_RETENTION_DAYS``; the primary key leads with ``day`` for it.

Idempotent both ways. Downgrade drops the counts.

Revision ID: 0054_decision_usage
Revises: 0053_workflow_run_progress
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0054_decision_usage"
down_revision: Union[str, None] = "0053_workflow_run_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_usage (
            day             DATE NOT NULL,
            feature         TEXT NOT NULL,
            mode            TEXT NOT NULL,
            model_version   TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL,
            calls           BIGINT NOT NULL DEFAULT 0,
            states          BIGINT NOT NULL DEFAULT 0,
            answered        BIGINT NOT NULL DEFAULT 0,
            ms_total        DOUBLE PRECISION NOT NULL DEFAULT 0,
            queue_ms_total  DOUBLE PRECISION NOT NULL DEFAULT 0,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT decision_usage_pkey PRIMARY KEY (day, feature, mode, model_version, status)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS decision_usage;")
