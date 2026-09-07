"""0011 scheduler — make schedules.agent_id / schedule_runs.agent_id nullable.

Agentless schedules (created from agentless chats via the dual-registered
``scheduler`` default chat tool) carry ``agent_id IS NULL``. Existing FK +
``ON DELETE CASCADE`` semantics on ``agents(id)`` are unaffected — Postgres
only cascades when the parent row is deleted, NULL rows aren't matched.

Revision ID: 0011_schedules_nullable_agent
Revises: 0010_schedules
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0011_schedules_nullable_agent"
down_revision: Union[str, None] = "0010_schedules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE schedules ALTER COLUMN agent_id DROP NOT NULL;")
    op.execute("ALTER TABLE schedule_runs ALTER COLUMN agent_id DROP NOT NULL;")


def downgrade() -> None:
    # Destructive otherwise: agentless rows have agent_id IS NULL by design,
    # so restoring NOT NULL must fail loudly if any exist.
    op.execute(
        """
        DO $$
        DECLARE
            sched_nulls INTEGER;
            run_nulls INTEGER;
        BEGIN
            SELECT count(*) INTO sched_nulls
            FROM schedules WHERE agent_id IS NULL;
            SELECT count(*) INTO run_nulls
            FROM schedule_runs WHERE agent_id IS NULL;
            IF sched_nulls > 0 OR run_nulls > 0 THEN
                RAISE EXCEPTION
                    'Cannot downgrade 0011: agentless rows present '
                    '(schedules=%, schedule_runs=%). '
                    'Delete or reassign them before retrying.',
                    sched_nulls, run_nulls;
            END IF;
        END$$;
        """
    )
    op.execute("ALTER TABLE schedule_runs ALTER COLUMN agent_id SET NOT NULL;")
    op.execute("ALTER TABLE schedules ALTER COLUMN agent_id SET NOT NULL;")
