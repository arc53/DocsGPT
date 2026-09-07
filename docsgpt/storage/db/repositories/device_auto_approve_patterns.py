"""Per-device, per-user sticky "don't ask again" patterns."""

from __future__ import annotations


from sqlalchemy import Connection, text


class DeviceAutoApprovePatternsRepository:
    """Normalized sticky-approval patterns scoped to (device, user)."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def add(self, device_id: str, user_id: str, pattern: str) -> bool:
        """Idempotently add a pattern; returns True if newly inserted."""
        result = self._conn.execute(
            text(
                """
                INSERT INTO device_auto_approve_patterns
                    (device_id, user_id, pattern)
                VALUES (:device_id, :user_id, :pattern)
                ON CONFLICT (device_id, user_id, pattern) DO NOTHING
                """
            ),
            {"device_id": device_id, "user_id": user_id, "pattern": pattern},
        )
        return result.rowcount > 0

    def remove(self, device_id: str, user_id: str, pattern: str) -> bool:
        result = self._conn.execute(
            text(
                """
                DELETE FROM device_auto_approve_patterns
                WHERE device_id = :device_id
                  AND user_id   = :user_id
                  AND pattern   = :pattern
                """
            ),
            {"device_id": device_id, "user_id": user_id, "pattern": pattern},
        )
        return result.rowcount > 0

    def list_for_device(self, device_id: str, user_id: str) -> list[str]:
        result = self._conn.execute(
            text(
                """
                SELECT pattern FROM device_auto_approve_patterns
                WHERE device_id = :device_id AND user_id = :user_id
                ORDER BY created_at
                """
            ),
            {"device_id": device_id, "user_id": user_id},
        )
        return [row[0] for row in result.fetchall()]

    def has_pattern(
        self, device_id: str, user_id: str, pattern: str
    ) -> bool:
        row = self._conn.execute(
            text(
                """
                SELECT 1 FROM device_auto_approve_patterns
                WHERE device_id = :device_id
                  AND user_id   = :user_id
                  AND pattern   = :pattern
                LIMIT 1
                """
            ),
            {"device_id": device_id, "user_id": user_id, "pattern": pattern},
        ).fetchone()
        return row is not None

    def clear_for_device(self, device_id: str) -> int:
        result = self._conn.execute(
            text(
                "DELETE FROM device_auto_approve_patterns WHERE device_id = :device_id"
            ),
            {"device_id": device_id},
        )
        return result.rowcount or 0
