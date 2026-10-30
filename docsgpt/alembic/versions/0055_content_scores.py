"""0055 content scores — prompt-injection scores cached by content, and the item a guardrail event is about.

* ``content_scores``: one row per text and scorer. ``content_hash`` is the
  sha256 of the exact text scored and ``scorer`` names the model, question
  and windowing that scored it (``docsgpt.guardrails.injection_scoring.scorer_id``),
  so a new model revision misses every row instead of reusing old scores.
  ``p`` is the highest probability over the text's windows, and
  ``windows_scored`` of ``windows_total`` says how much of it was read. A
  score is a function of the text alone, so rows are shared across users;
  they hold no text. ``cleanup_content_scores`` on beat deletes rows unseen
  for ``GUARDRAILS_CONTENT_SCORES_RETENTION_DAYS``, by ``last_seen_at``.
* ``guardrail_events.item_ref``: the retrieved document (``chunk:<source>:<key>``)
  or attached file (``attachment:<id>``) an item-level verdict was about;
  NULL for a verdict on a whole text.

Idempotent both ways. Downgrade drops the scores and the column.

Revision ID: 0055_content_scores
Revises: 0054_decision_usage
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0055_content_scores"
down_revision: Union[str, None] = "0054_decision_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS content_scores (
            content_hash    TEXT NOT NULL,
            scorer          TEXT NOT NULL,
            p               REAL NOT NULL,
            windows_scored  SMALLINT NOT NULL,
            windows_total   SMALLINT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT content_scores_pkey PRIMARY KEY (content_hash, scorer)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS content_scores_last_seen_idx ON content_scores (last_seen_at);")
    op.execute("ALTER TABLE guardrail_events ADD COLUMN IF NOT EXISTS item_ref TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE guardrail_events DROP COLUMN IF EXISTS item_ref;")
    op.execute("DROP TABLE IF EXISTS content_scores;")
