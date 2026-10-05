"""0048 monitors and trigger links — checks that wake a conversation, and the public links that feed them.

A monitor is a ``schedules`` row with ``trigger_type = 'monitor'``: the
dispatcher already owns cadence (``next_run_at``), expiry (``end_at``),
status and the failure counter. What only a monitor needs lives 1:1 in
``monitors`` (keyed by the schedule id, which is the monitor id):

* ``monitor_spec``: what it watches (``source``), how it decides (``check``,
  ``condition``), what the woken agent does (``on_match``) and the interval.
* ``monitor_state``: what the last check saw (content hash, excerpt, seen
  item ids, check state), kept under 16 KB by the code that writes it.
* ``approval``: the creation-time approval of a tool source, bound to the
  tool, action and arguments template it was given for.
* counters and timestamps (checks, wakes, judge tokens, last change, the
  time the source became unreachable) and a tick lease.

``trigger_links`` holds webhook and approval links: only the sha256 of the
token is stored (the raw token is shown once), an optional HMAC secret
encrypted at rest, and the approval question or its decision.
``trigger_hits`` keeps accepted webhook deliveries, bounded, unique per
link and dedupe key, until a worker has run them through the check.

Rows cascade with the schedule and with the conversation; deleting a monitor row
(its conversation went) deletes its schedule too, by trigger. Idempotent both
ways; downgrade folds monitor schedules away before narrowing the check.

Revision ID: 0048_monitors_and_trigger_links
Revises: 0047_background_jobs
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0048_monitors_and_trigger_links"
down_revision: Union[str, None] = "0047_background_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE schedules DROP CONSTRAINT IF EXISTS schedules_trigger_type_chk;")
    op.execute(
        "ALTER TABLE schedules ADD CONSTRAINT schedules_trigger_type_chk "
        "CHECK (trigger_type IN ('once', 'recurring', 'monitor'));"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS monitors (
            schedule_id      UUID PRIMARY KEY REFERENCES schedules(id) ON DELETE CASCADE,
            user_id          TEXT NOT NULL,
            conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            agent_id         UUID,
            description      TEXT NOT NULL,
            source_type      TEXT NOT NULL
                CONSTRAINT monitors_source_type_chk
                CHECK (source_type IN ('webpage', 'tool', 'ingest', 'webhook', 'approval')),
            monitor_spec     JSONB NOT NULL DEFAULT '{}'::jsonb,
            monitor_state    JSONB NOT NULL DEFAULT '{}'::jsonb,
            approval         JSONB,
            interval_seconds INTEGER,
            check_count      INTEGER NOT NULL DEFAULT 0,
            wake_count       INTEGER NOT NULL DEFAULT 0,
            max_wakes        INTEGER NOT NULL DEFAULT 1,
            judge_tokens     INTEGER NOT NULL DEFAULT 0,
            last_checked_at  TIMESTAMPTZ,
            last_changed_at  TIMESTAMPTZ,
            last_woken_at    TIMESTAMPTZ,
            last_error       TEXT,
            unreachable_since TIMESTAMPTZ,
            paused_reason    TEXT,
            tick_started_at  TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS monitors_user_idx ON monitors (user_id, source_type);")
    op.execute("CREATE INDEX IF NOT EXISTS monitors_conversation_idx ON monitors (conversation_id);")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trigger_links (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            monitor_id       UUID NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
            user_id          TEXT NOT NULL,
            conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            token_hash       TEXT NOT NULL,
            kind             TEXT NOT NULL
                CONSTRAINT trigger_links_kind_chk CHECK (kind IN ('webhook', 'approval')),
            secret_encrypted TEXT,
            signature_scheme TEXT NOT NULL DEFAULT 'none'
                CONSTRAINT trigger_links_signature_scheme_chk
                CHECK (signature_scheme IN ('none', 'standard_webhooks', 'github', 'hmac_sha256')),
            approval_spec    JSONB,
            decision         JSONB,
            expires_at       TIMESTAMPTZ NOT NULL,
            max_hits         INTEGER NOT NULL DEFAULT 1,
            hit_count        INTEGER NOT NULL DEFAULT 0,
            last_hit_at      TIMESTAMPTZ,
            revoked_at       TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT trigger_links_token_hash_uidx UNIQUE (token_hash)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS trigger_links_monitor_idx ON trigger_links (monitor_id);")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trigger_hits (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            link_id      UUID NOT NULL REFERENCES trigger_links(id) ON DELETE CASCADE,
            dedupe_key   TEXT NOT NULL,
            payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
            status       TEXT NOT NULL DEFAULT 'pending'
                CONSTRAINT trigger_hits_status_chk
                CHECK (status IN ('pending', 'processed', 'ignored', 'failed')),
            error        TEXT,
            received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ,
            CONSTRAINT trigger_hits_link_dedupe_uidx UNIQUE (link_id, dedupe_key)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS trigger_hits_received_idx ON trigger_hits (received_at);")
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'monitors_set_updated_at') THEN "
        "CREATE TRIGGER monitors_set_updated_at BEFORE UPDATE ON monitors "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at(); "
        "END IF; END $$;"
    )
    # A monitor row goes with its conversation; its schedule must go too, or
    # it would stay 'active' with nothing to run and count against the cap.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION monitors_drop_schedule() RETURNS trigger AS $$
        BEGIN
            DELETE FROM schedules WHERE id = OLD.schedule_id AND trigger_type = 'monitor';
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'monitors_drop_schedule') THEN "
        "CREATE TRIGGER monitors_drop_schedule AFTER DELETE ON monitors "
        "FOR EACH ROW EXECUTE FUNCTION monitors_drop_schedule(); "
        "END IF; END $$;"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS monitors_drop_schedule ON monitors;")
    op.execute("DROP FUNCTION IF EXISTS monitors_drop_schedule();")
    op.execute("DROP TABLE IF EXISTS trigger_hits;")
    op.execute("DROP TABLE IF EXISTS trigger_links;")
    op.execute("DROP TABLE IF EXISTS monitors;")
    op.execute("DELETE FROM schedules WHERE trigger_type = 'monitor';")
    op.execute("ALTER TABLE schedules DROP CONSTRAINT IF EXISTS schedules_trigger_type_chk;")
    op.execute(
        "ALTER TABLE schedules ADD CONSTRAINT schedules_trigger_type_chk "
        "CHECK (trigger_type IN ('once', 'recurring'));"
    )
