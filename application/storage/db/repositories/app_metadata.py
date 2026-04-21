"""Repository for the ``app_metadata`` singleton key/value table.

Owns the instance-wide state the version-check client needs:
``instance_id`` (anonymous UUID sent with each check) and
``version_check_notice_shown`` (one-shot flag for the first-run
telemetry notice). Kept deliberately generic so future one-off config
values can piggyback without a new migration each time.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Connection, text


class AppMetadataRepository:
    """Postgres-backed ``app_metadata`` store. Tiny by design."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            text("SELECT value FROM app_metadata WHERE key = :key"),
            {"key": key},
        ).fetchone()
        return row[0] if row is not None else None

    def set(self, key: str, value: str) -> None:
        self._conn.execute(
            text(
                "INSERT INTO app_metadata (key, value) VALUES (:key, :value) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ),
            {"key": key, "value": value},
        )

    def get_or_create_instance_id(self) -> str:
        """Return the anonymous instance UUID, generating one if absent.

        Uses ``INSERT ... ON CONFLICT DO NOTHING`` + re-read so two
        workers racing on the very first startup converge on a single
        UUID instead of each persisting their own.
        """
        existing = self.get("instance_id")
        if existing:
            return existing
        candidate = str(uuid.uuid4())
        self._conn.execute(
            text(
                "INSERT INTO app_metadata (key, value) VALUES ('instance_id', :value) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"value": candidate},
        )
        # Re-read: if another worker won the race, their UUID is now authoritative.
        winner = self.get("instance_id")
        return winner or candidate
