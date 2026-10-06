"""0050 device jobs and links — background jobs on paired devices, and what links can do.

* ``background_jobs.runner`` takes ``device``: a ``remote_device`` command a
  turn handed off, followed by a Celery poll chain that reads the device's
  output from the broker until the command reports its exit code.
* ``devices.capabilities``: what the paired client said it can do on its
  last request (``X-Device-Capabilities``: ``cancel``, ``outbox``); null
  until it has reported.
* ``trigger_links.ref``: a signed link's short reference id, unique per
  user. The model is given ``{{link_secret:REF}}`` instead of the secret,
  and the executor fills the value into tool calls the user approves.
  ``trigger_links.expose_secret`` records a link whose owner chose, in
  Settings > Monitors, to show its raw secret to the assistant (never the
  model's choice); a partial index finds a user's exposed links.
* ``trigger_links.allow_get``: a webhook link that also takes GET calls
  (query parameters are the payload), for machine callers that can't POST.
* ``trigger_links.signature_scheme`` takes ``stripe``, ``slack``,
  ``header_token`` and ``bearer``; ``trigger_links.signature_header`` is the
  header a ``header_token`` link reads (``X-Webhook-Token`` when null).
  Downgrade revokes links with a new scheme: they could only be kept by
  dropping their signature, which would leave them open.
* ``monitor_events``: an ingest event an ingest monitor watches, stored
  before its task is queued (unique per monitor and event), so a task the
  broker loses is queued again by the dispatcher's sweep instead of the event
  being dropped. Same lifecycle as ``trigger_hits``.

Idempotent both ways. Downgrade first reports running device jobs ``lost``
(nothing would follow them any more), then narrows the check.

Revision ID: 0050_device_jobs_links
Revises: 0049_push_and_unread
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0050_device_jobs_links"
down_revision: Union[str, None] = "0049_push_and_unread"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RUNNERS_BEFORE = "'inprocess', 'celery', 'sandbox', 'mcp'"
_RUNNERS_AFTER = "'inprocess', 'celery', 'sandbox', 'mcp', 'device'"

_SCHEMES_BEFORE = "'none', 'standard_webhooks', 'github', 'hmac_sha256'"
_SCHEMES_AFTER = "'none', 'standard_webhooks', 'github', 'hmac_sha256', 'stripe', 'slack', 'header_token', 'bearer'"

_LOST_ON_DOWNGRADE = (
    '{"type": "Lost", "message": "This job was interrupted before it finished and will not report back. It may '
    "or may not have taken effect: verify before retrying, and never re-run a non-idempotent action blindly.\"}"
)


def _runners(values: str) -> None:
    op.execute("ALTER TABLE background_jobs DROP CONSTRAINT IF EXISTS background_jobs_runner_chk;")
    op.execute(
        f"ALTER TABLE background_jobs ADD CONSTRAINT background_jobs_runner_chk CHECK (runner IN ({values}));"
    )


def _schemes(values: str) -> None:
    op.execute("ALTER TABLE trigger_links DROP CONSTRAINT IF EXISTS trigger_links_signature_scheme_chk;")
    op.execute(
        "ALTER TABLE trigger_links ADD CONSTRAINT trigger_links_signature_scheme_chk "
        f"CHECK (signature_scheme IN ({values}));"
    )


def upgrade() -> None:
    _runners(_RUNNERS_AFTER)
    op.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS capabilities TEXT;")
    op.execute("ALTER TABLE trigger_links ADD COLUMN IF NOT EXISTS ref TEXT;")
    op.execute("ALTER TABLE trigger_links ADD COLUMN IF NOT EXISTS expose_secret BOOLEAN NOT NULL DEFAULT false;")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS trigger_links_user_ref_uidx ON trigger_links (user_id, ref) "
        "WHERE ref IS NOT NULL;"
    )
    op.execute("ALTER TABLE trigger_links ADD COLUMN IF NOT EXISTS allow_get BOOLEAN NOT NULL DEFAULT false;")
    op.execute(
        "CREATE INDEX IF NOT EXISTS trigger_links_exposed_idx ON trigger_links (user_id) WHERE expose_secret;"
    )
    op.execute("ALTER TABLE trigger_links ADD COLUMN IF NOT EXISTS signature_header TEXT;")
    _schemes(_SCHEMES_AFTER)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_events (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            monitor_id   UUID NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
            dedupe_key   TEXT NOT NULL,
            payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
            status       TEXT NOT NULL DEFAULT 'pending'
                CONSTRAINT monitor_events_status_chk
                CHECK (status IN ('pending', 'processed', 'ignored', 'failed')),
            attempts     INTEGER NOT NULL DEFAULT 0,
            error        TEXT,
            received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ,
            CONSTRAINT monitor_events_monitor_dedupe_uidx UNIQUE (monitor_id, dedupe_key)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS monitor_events_status_received_idx ON monitor_events (status, received_at);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS monitor_events;")
    op.execute(
        "UPDATE background_jobs SET status = 'lost', finished_at = now(), last_updated_at = now(), "
        "expires_at = now() + interval '7 days', "
        "status_message = 'interrupted: the server was downgraded', "
        f"error = CAST('{_LOST_ON_DOWNGRADE}' AS jsonb) "
        "WHERE runner = 'device' AND status = 'working';"
    )
    op.execute("UPDATE background_jobs SET runner = 'inprocess' WHERE runner = 'device';")
    _runners(_RUNNERS_BEFORE)
    op.execute("ALTER TABLE devices DROP COLUMN IF EXISTS capabilities;")
    # A link signed a new way would be left unsigned (open) by narrowing the check: revoke it instead.
    op.execute(
        "UPDATE trigger_links SET revoked_at = COALESCE(revoked_at, now()), signature_scheme = 'hmac_sha256' "
        "WHERE signature_scheme IN ('stripe', 'slack', 'header_token', 'bearer');"
    )
    _schemes(_SCHEMES_BEFORE)
    op.execute("ALTER TABLE trigger_links DROP COLUMN IF EXISTS signature_header;")
    op.execute("ALTER TABLE trigger_links DROP COLUMN IF EXISTS allow_get;")
    op.execute("DROP INDEX IF EXISTS trigger_links_exposed_idx;")
    op.execute("DROP INDEX IF EXISTS trigger_links_user_ref_uidx;")
    op.execute("ALTER TABLE trigger_links DROP COLUMN IF EXISTS expose_secret;")
    op.execute("ALTER TABLE trigger_links DROP COLUMN IF EXISTS ref;")
