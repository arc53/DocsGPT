"""0034 auth events actor/target — who did it, and to whom.

``auth_events.user_id`` was overloaded: admin mutations file the row under the
*target* user and hide the acting admin in ``metadata->>'by'``, team events file
it under the *actor*, and quota events switch between the two depending on
scope. The practical consequence is that "show me everything admin X did" is
unanswerable — the first question any audit review asks.

This adds two explicit columns:

* ``actor_id`` — who performed the action (never NULL going forward).
* ``target_id`` — the user the action was performed on; NULL when the event is
  not about a user (a team or an instance-wide policy change).

``user_id`` is deliberately left alone. It stays the per-user feed key
(``list_recent``) and every historical row keeps its meaning, so this migration
is additive and the backfill never rewrites it.

Backfill rules, applied only to rows that predate the columns:

* ``actor_id`` = the first present of ``metadata->>'by'``,
  ``metadata->>'granted_by'``, ``metadata->>'revoked_by'``, else ``user_id``.
* ``target_id`` = ``user_id``, except for events that were always filed under
  the actor and have no single user target: ``team.*``, and instance- or
  team-scoped ``quota_policy_*`` changes.

The same two rules are installed as SQL functions and applied by a BEFORE
INSERT trigger to any row that arrives without an ``actor_id``, so a writer
from a release that predates these columns keeps its attribution instead of
being rejected or flattened to a sentinel.

Also adds the indexes the global admin feed needs. Before this the only index
was ``(user_id, created_at DESC)``, so the cross-user feed — which orders by
``created_at DESC`` with no user predicate — degraded to a sequential scan plus
a sort on every page.

Idempotent both ways.

Revision ID: 0034_auth_events_actor_target
Revises: 0033_quotas
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0034_auth_events_actor_target"
down_revision: Union[str, None] = "0033_quotas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE auth_events ADD COLUMN IF NOT EXISTS actor_id TEXT;")
    op.execute("ALTER TABLE auth_events ADD COLUMN IF NOT EXISTS target_id TEXT;")

    # The derivation rules, as functions, so the backfill below and the
    # compatibility trigger share one definition instead of two copies of the
    # same CASE drifting apart.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_events_derive_actor(
            metadata jsonb, user_id text
        ) RETURNS text
        LANGUAGE sql IMMUTABLE AS $$
            SELECT COALESCE(
                metadata->>'by',
                metadata->>'granted_by',
                metadata->>'revoked_by',
                user_id
            );
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_events_derive_target(
            event text, metadata jsonb, user_id text
        ) RETURNS text
        LANGUAGE sql IMMUTABLE AS $$
            SELECT CASE
                -- Team events were always filed under the actor.
                WHEN event LIKE 'team.%' THEN NULL
                -- An instance or team quota policy is filed under the acting
                -- admin, not a target user (see api/admin/quotas.py::_audit);
                -- only a user-scoped policy has one.
                WHEN event IN ('quota_policy_set', 'quota_policy_deleted')
                     AND COALESCE(metadata->>'scope', '') <> 'user' THEN NULL
                ELSE user_id
            END;
        $$;
        """
    )

    # Backfill. ``actor_id IS NULL`` scopes this to pre-migration rows, so a
    # re-run (or a downgrade/upgrade cycle) never clobbers written values.
    op.execute(
        """
        UPDATE auth_events
        SET actor_id = auth_events_derive_actor(metadata, user_id),
            target_id = auth_events_derive_target(event, metadata, user_id)
        WHERE actor_id IS NULL;
        """
    )

    # A writer from a release that predates these columns names only the old
    # ones, so ``actor_id`` arrives NULL. Two things follow, and the trigger
    # handles both:
    #
    #   1. The NOT NULL below would reject the insert. In admin/routes.py that
    #      insert shares the request's transaction, so a NotNullViolation would
    #      500 the deactivate or role grant and roll its write back with it.
    #   2. Defaulting it to a sentinel would keep the write but lose the
    #      attribution -- and the highest-volume events are the recoverable
    #      ones: for a login or a silent renewal the actor is simply the user.
    #
    # ``actor_id IS NULL`` identifies a legacy insert exactly, because the
    # repository always supplies one. That matters for ``target_id``: a current
    # writer sets it to NULL deliberately for events with no user target
    # (``conversation.deleted``), and deriving there would wrongly name the
    # actor as their own target.
    #
    # Kept rather than dropped in a follow-up: it costs nothing on the path the
    # repository takes, and it keeps the column's contract true for any writer
    # that bypasses it.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_events_fill_attribution()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.actor_id IS NULL THEN
                NEW.actor_id := auth_events_derive_actor(
                    NEW.metadata, NEW.user_id
                );
                NEW.target_id := auth_events_derive_target(
                    NEW.event, NEW.metadata, NEW.user_id
                );
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS auth_events_fill_attribution_trg ON auth_events;")
    op.execute(
        """
        CREATE TRIGGER auth_events_fill_attribution_trg
        BEFORE INSERT ON auth_events
        FOR EACH ROW EXECUTE FUNCTION auth_events_fill_attribution();
        """
    )

    # Backfilled above and guaranteed by the trigger, so this is safe to assert.
    op.execute("ALTER TABLE auth_events ALTER COLUMN actor_id SET NOT NULL;")

    op.execute(
        "CREATE INDEX IF NOT EXISTS auth_events_created_idx "
        "ON auth_events (created_at DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS auth_events_event_created_idx "
        "ON auth_events (event, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS auth_events_actor_idx "
        "ON auth_events (actor_id, created_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS auth_events_actor_idx;")
    op.execute("DROP INDEX IF EXISTS auth_events_event_created_idx;")
    op.execute("DROP INDEX IF EXISTS auth_events_created_idx;")
    op.execute("DROP TRIGGER IF EXISTS auth_events_fill_attribution_trg ON auth_events;")
    op.execute("DROP FUNCTION IF EXISTS auth_events_fill_attribution();")
    op.execute("ALTER TABLE auth_events DROP COLUMN IF EXISTS target_id;")
    op.execute("ALTER TABLE auth_events DROP COLUMN IF EXISTS actor_id;")
    op.execute("DROP FUNCTION IF EXISTS auth_events_derive_target(text, jsonb, text);")
    op.execute("DROP FUNCTION IF EXISTS auth_events_derive_actor(jsonb, text);")
