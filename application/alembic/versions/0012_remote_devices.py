"""0012 remote devices — devices, device_audit_log, device_auto_approve_patterns.

Adds tables for the Remote Device feature: paired remote hosts that DocsGPT
agents can drive via shell tool calls.

Revision ID: 0012_remote_devices
Revises: 0011_schedules_nullable_agent
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0012_remote_devices"
down_revision: Union[str, None] = "0011_schedules_nullable_agent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE devices (
            id                          TEXT PRIMARY KEY,
            user_id                     TEXT NOT NULL,
            name                        TEXT NOT NULL,
            hostname                    TEXT,
            os                          TEXT,
            arch                        TEXT,
            cli_version                 TEXT,
            machine_pubkey_fingerprint  TEXT NOT NULL,
            token_hash                  TEXT NOT NULL,
            approval_mode               TEXT NOT NULL DEFAULT 'ask',
            description                 TEXT,
            status                      TEXT NOT NULL DEFAULT 'active',
            paired_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at                TIMESTAMPTZ,
            revoked_at                  TIMESTAMPTZ,
            revoke_reason               TEXT,
            CONSTRAINT devices_approval_mode_chk
                CHECK (approval_mode IN ('ask', 'writes-only', 'never')),
            CONSTRAINT devices_status_chk
                CHECK (status IN ('active', 'revoked')),
            CONSTRAINT devices_user_name_uidx UNIQUE (user_id, name)
        );
        """
    )
    op.execute(
        "CREATE INDEX devices_user_active_idx ON devices(user_id) "
        "WHERE status = 'active';"
    )

    op.execute(
        """
        CREATE TABLE device_audit_log (
            id              BIGSERIAL PRIMARY KEY,
            device_id       TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            user_id         TEXT NOT NULL,
            agent_id        TEXT,
            conversation_id TEXT,
            invocation_id   TEXT NOT NULL,
            action          TEXT NOT NULL,
            command         TEXT NOT NULL,
            working_dir     TEXT,
            approval_mode   TEXT NOT NULL,
            decision        TEXT NOT NULL,
            decision_reason TEXT,
            issued_at       TIMESTAMPTZ NOT NULL,
            started_at      TIMESTAMPTZ,
            finished_at     TIMESTAMPTZ,
            exit_code       INTEGER,
            duration_ms     INTEGER,
            stdout_sha256   CHAR(64),
            stderr_sha256   CHAR(64),
            stdout_bytes    INTEGER,
            stderr_bytes    INTEGER,
            error           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX device_audit_device_idx "
        "ON device_audit_log(device_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX device_audit_user_idx "
        "ON device_audit_log(user_id, created_at DESC);"
    )

    # Per-device, per-user sticky "don't ask again" patterns. Normalized
    # form: command head + first sub-token, wildcard rest (see
    # application/devices/normalizer.py).
    op.execute(
        """
        CREATE TABLE device_auto_approve_patterns (
            id          BIGSERIAL PRIMARY KEY,
            device_id   TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            user_id     TEXT NOT NULL,
            pattern     TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT device_auto_approve_uidx
                UNIQUE (device_id, user_id, pattern)
        );
        """
    )
    op.execute(
        "CREATE INDEX device_auto_approve_lookup_idx "
        "ON device_auto_approve_patterns(device_id, user_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS device_auto_approve_patterns CASCADE;")
    op.execute("DROP TABLE IF EXISTS device_audit_log CASCADE;")
    op.execute("DROP TABLE IF EXISTS devices CASCADE;")
