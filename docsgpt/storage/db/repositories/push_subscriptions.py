"""Repository for ``push_subscriptions``: the browsers a user gets Web Push notifications in.

A subscription is keyed by its push service endpoint, which is unique to one
browser profile. Saving an endpoint that exists moves it to the caller (the
same browser after another user signed in) and resets its failure count.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict


class PushSubscriptionsRepository:
    """Save, list and settle the deliveries of Web Push subscriptions."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert(
        self,
        *,
        user_id: str,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: Optional[str] = None,
    ) -> dict:
        """Save a subscription for ``user_id``; an existing endpoint moves to them with the new keys.

        ``updated_at`` is the wall clock, not the transaction time, so saves in
        one transaction still order (``trim_for_user`` keeps the newest).

        Args:
            user_id: The signed-in user.
            endpoint: The push service URL (already validated by the caller).
            p256dh: The browser's ECDH public key, base64url.
            auth: The browser's auth secret, base64url.
            user_agent: The browser's User-Agent, for the user to tell subscriptions apart.

        Returns:
            The saved row.
        """
        row = self._conn.execute(
            text(
                """
                INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent, updated_at)
                VALUES (:user_id, :endpoint, :p256dh, :auth, :user_agent, clock_timestamp())
                ON CONFLICT (endpoint) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    p256dh = EXCLUDED.p256dh,
                    auth = EXCLUDED.auth,
                    user_agent = EXCLUDED.user_agent,
                    updated_at = clock_timestamp(),
                    failure_count = 0
                RETURNING *
                """
            ),
            {"user_id": user_id, "endpoint": endpoint, "p256dh": p256dh, "auth": auth, "user_agent": user_agent},
        ).fetchone()
        return row_to_dict(row)

    def list_for_user(self, user_id: str) -> List[dict]:
        """The user's subscriptions, newest first."""
        rows = self._conn.execute(
            text("SELECT * FROM push_subscriptions WHERE user_id = :user_id ORDER BY updated_at DESC, id DESC"),
            {"user_id": user_id},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def count_for_user(self, user_id: str) -> int:
        """How many subscriptions the user has."""
        return int(
            self._conn.execute(
                text("SELECT count(*) FROM push_subscriptions WHERE user_id = :user_id"), {"user_id": user_id}
            ).scalar()
            or 0
        )

    def trim_for_user(self, user_id: str, keep: int) -> int:
        """Delete all but the user's ``keep`` most recently saved subscriptions.

        Returns:
            How many were deleted.
        """
        result = self._conn.execute(
            text(
                """
                DELETE FROM push_subscriptions WHERE id IN (
                    SELECT id FROM push_subscriptions WHERE user_id = :user_id
                    ORDER BY updated_at DESC, id DESC OFFSET :keep
                )
                """
            ),
            {"user_id": user_id, "keep": max(0, int(keep))},
        )
        return int(result.rowcount or 0)

    def delete_for_user(self, user_id: str, endpoint: str) -> bool:
        """Delete the user's subscription for ``endpoint``; False when they have none."""
        result = self._conn.execute(
            text("DELETE FROM push_subscriptions WHERE user_id = :user_id AND endpoint = :endpoint"),
            {"user_id": user_id, "endpoint": endpoint},
        )
        return bool(result.rowcount)

    def delete(self, subscription_id: str) -> bool:
        """Delete one subscription (the push service said it is gone)."""
        if not looks_like_uuid(subscription_id):
            return False
        result = self._conn.execute(
            text("DELETE FROM push_subscriptions WHERE id = CAST(:id AS uuid)"), {"id": subscription_id}
        )
        return bool(result.rowcount)

    def record_success(self, subscription_id: str) -> None:
        """A delivery went through: stamp it and reset the failure count."""
        if not looks_like_uuid(subscription_id):
            return
        self._conn.execute(
            text(
                "UPDATE push_subscriptions SET last_success_at = now(), failure_count = 0 "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": subscription_id},
        )

    def record_failure(self, subscription_id: str) -> Optional[int]:
        """A delivery failed: count it.

        Returns:
            The consecutive failure count, or None when the row is gone.
        """
        if not looks_like_uuid(subscription_id):
            return None
        value = self._conn.execute(
            text(
                "UPDATE push_subscriptions SET last_failure_at = now(), failure_count = failure_count + 1 "
                "WHERE id = CAST(:id AS uuid) RETURNING failure_count"
            ),
            {"id": subscription_id},
        ).scalar()
        return int(value) if value is not None else None
