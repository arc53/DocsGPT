"""0057 conversation labels — what the decision model said about stored conversations.

* ``conversation_labels``: one row per conversation, message (NULL for the
  conversation itself) and label, written by the ``analytics_sweep`` beat task
  (``docsgpt/analytics/tasks.py``). ``probabilities`` holds every option's
  probability (``yes``/``no`` for a yes/no question, ``"0"``.. for a score),
  ``top`` and ``p_top`` the most likely one. Reaction rows sit on the answer
  reacted to and point at the reply they read through ``reply_message_id``,
  so editing either side deletes them by cascade. ``derived`` rows
  (``gap_type``, ``topic_effective``, ``resolution``, ``experience``) are
  computed from the others without a model call. ``schema_hash`` and
  ``model_version`` say which wording and which model made a row, so labels
  of different wording are never mixed and an older model's are relabelled.
  ``created_at`` is when the row was last written. ``source_updated_at`` and
  ``source_hash`` record what a row was built from, as the sweep read it: the
  message's ``updated_at`` (for a conversation-level row, the latest over its
  messages) and a hash of what the states read of it. A label stays current
  while its message is unchanged since then or still hashes the same, so
  feedback or a finished background job does not have it asked again, and an
  edit made while the sweep ran does. Rows hold no user text. ``pending``
  (generated) marks a ``resolution`` that still has pending mass; the sweep
  looks for those past their window every few minutes, and
  ``conversation_labels_resolution_idx`` holds only them, not the settled
  ones that make up nearly all resolutions.
  ``cleanup_conversation_labels`` on beat deletes rows past
  ``ANALYTICS_RETENTION_DAYS`` by ``occurred_at``.
* ``conversation_messages_ts_idx``: the sweep reads messages by time across
  every user; the only time index was ``(user_id, timestamp)``. Built
  ``CONCURRENTLY`` in an autocommit block (following 0045) so the build never
  blocks chat writes; an INVALID leftover of a cancelled build is dropped
  first.

Idempotent both ways. Downgrade drops the table and the index.

Revision ID: 0057_conversation_labels
Revises: 0056_conversation_passthrough
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0057_conversation_labels"
down_revision: Union[str, None] = "0056_conversation_passthrough"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS_INDEX = "conversation_messages_ts_idx"


def _drop_if_invalid(name: str) -> None:
    """Drop ``name`` when a previous concurrent build left it INVALID.

    Args:
        name: The index name.
    """
    invalid = (
        op.get_bind()
        .exec_driver_sql(f"SELECT NOT indisvalid FROM pg_index WHERE indexrelid = to_regclass('{name}')")
        .scalar()
    )
    if invalid:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name};")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_labels (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id   uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            message_id        uuid REFERENCES conversation_messages(id) ON DELETE CASCADE,
            reply_message_id  uuid REFERENCES conversation_messages(id) ON DELETE CASCADE,
            user_id           text NOT NULL,
            agent_id          uuid,
            level             text NOT NULL,
            label             text NOT NULL,
            top               text,
            p_top             double precision,
            probabilities     jsonb NOT NULL,
            derived           boolean NOT NULL DEFAULT false,
            lang              text,
            options_hash      text,
            schema_hash       text NOT NULL,
            model_version     text NOT NULL,
            occurred_at       timestamptz NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),
            source_updated_at timestamptz,
            source_hash       text,
            pending           boolean NOT NULL GENERATED ALWAYS AS (
                CASE WHEN label = 'resolution' THEN COALESCE((probabilities->>'pending')::float8, 0) > 0
                     ELSE false END
            ) STORED
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS conversation_labels_target_uidx ON conversation_labels "
        "(conversation_id, COALESCE(message_id, '00000000-0000-0000-0000-000000000000'::uuid), label);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS conversation_labels_agent_time_idx ON conversation_labels (agent_id, occurred_at);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS conversation_labels_user_time_idx ON conversation_labels (user_id, occurred_at);"
    )
    op.execute("CREATE INDEX IF NOT EXISTS conversation_labels_message_idx ON conversation_labels (message_id);")
    op.execute("CREATE INDEX IF NOT EXISTS conversation_labels_reply_idx ON conversation_labels (reply_message_id);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS conversation_labels_resolution_idx ON conversation_labels (occurred_at) "
        "WHERE pending;"
    )
    # CONCURRENTLY can't run inside a transaction.
    with op.get_context().autocommit_block():
        _drop_if_invalid(_TS_INDEX)
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_TS_INDEX} ON conversation_messages (timestamp);")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_TS_INDEX};")
    op.execute("DROP TABLE IF EXISTS conversation_labels;")
