"""Repository for the ``users`` table.

Covers every operation the legacy Mongo code performs on
``users_collection``:

1. ``ensure_user_doc`` in ``application/api/user/base.py`` (upsert + get)
2. Pin/unpin agents in ``application/api/user/agents/routes.py`` (add/remove
   on ``agent_preferences.pinned``)
3. Share accept/reject in ``application/api/user/agents/sharing.py`` (add/
   bulk-remove on ``agent_preferences.shared_with_me``)
4. Cascade delete of an agent id from both arrays at once

All array mutations are implemented as single atomic UPDATE statements
using JSONB operators (``jsonb_set``, ``jsonb_array_elements``, ``@>``)
so there is no read-modify-write race between concurrent writers on the
same user row.

The repository takes a ``Connection`` and does not manage its own
transactions. Callers are responsible for wrapping writes in
``with engine.begin() as conn:`` (production) or the test fixture's
rollback-per-test connection (tests).
"""

from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


_DEFAULT_PREFERENCES = '{"pinned": [], "shared_with_me": []}'


class UsersRepository:
    """Postgres-backed replacement for Mongo ``users_collection`` writes/reads."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get(self, user_id: str) -> Optional[dict]:
        """Return the user row as a dict, or ``None`` if missing.

        Args:
            user_id: Auth-provider ``sub`` (opaque string).
        """
        result = self._conn.execute(
            text("SELECT * FROM users WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------
    def upsert(self, user_id: str) -> dict:
        """Ensure a row exists for ``user_id`` and return it.

        Matches Mongo's ``find_one_and_update(..., $setOnInsert, upsert=True,
        return_document=AFTER)`` semantics: if the row exists, preferences
        are preserved untouched; if it doesn't, a new row is created with
        default preferences.

        The ``DO UPDATE SET user_id = EXCLUDED.user_id`` branch is a
        deliberate no-op that lets ``RETURNING *`` fire on both the insert
        and conflict paths (``DO NOTHING`` would suppress the returning).
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO users (user_id, agent_preferences)
                VALUES (:user_id, CAST(:default_prefs AS jsonb))
                ON CONFLICT (user_id) DO UPDATE
                    SET user_id = EXCLUDED.user_id
                RETURNING *
                """
            ),
            {"user_id": user_id, "default_prefs": _DEFAULT_PREFERENCES},
        )
        return row_to_dict(result.fetchone())

    # ------------------------------------------------------------------
    # Pinned agents
    # ------------------------------------------------------------------
    def add_pinned(self, user_id: str, agent_id: str) -> None:
        """Idempotently append ``agent_id`` to ``agent_preferences.pinned``.

        Uses ``@>`` containment so a duplicate add is a no-op rather than a
        silent double-insert. The whole update is a single atomic statement
        so concurrent add_pinned calls on the same user cannot interleave
        into a read-modify-write race.
        """
        self._append_to_jsonb_array(user_id, "pinned", agent_id)

    def remove_pinned(self, user_id: str, agent_id: str) -> None:
        """Remove ``agent_id`` from ``agent_preferences.pinned`` if present."""
        self._remove_from_jsonb_array(user_id, "pinned", [agent_id])

    def remove_pinned_bulk(self, user_id: str, agent_ids: Iterable[str]) -> None:
        """Remove every id in ``agent_ids`` from ``agent_preferences.pinned``.

        No-op if the list is empty. Unknown ids are silently ignored so
        callers can pass the full "stale" set without pre-filtering.
        """
        ids = list(agent_ids)
        if not ids:
            return
        self._remove_from_jsonb_array(user_id, "pinned", ids)

    # ------------------------------------------------------------------
    # Shared-with-me agents
    # ------------------------------------------------------------------
    def add_shared(self, user_id: str, agent_id: str) -> None:
        """Idempotently append ``agent_id`` to ``agent_preferences.shared_with_me``."""
        self._append_to_jsonb_array(user_id, "shared_with_me", agent_id)

    def remove_shared_bulk(self, user_id: str, agent_ids: Iterable[str]) -> None:
        """Bulk-remove from ``agent_preferences.shared_with_me``. Empty list is a no-op."""
        ids = list(agent_ids)
        if not ids:
            return
        self._remove_from_jsonb_array(user_id, "shared_with_me", ids)

    # ------------------------------------------------------------------
    # Combined removal — called when an agent is hard-deleted
    # ------------------------------------------------------------------
    def remove_agent_from_all(self, user_id: str, agent_id: str) -> None:
        """Remove ``agent_id`` from BOTH pinned and shared_with_me atomically.

        Mirrors the Mongo ``$pull`` that targets both nested array fields
        in one ``update_one`` — see ``application/api/user/agents/routes.py``
        around the agent-delete path.
        """
        self._conn.execute(
            text(
                """
                UPDATE users
                SET
                    agent_preferences = jsonb_set(
                        jsonb_set(
                            agent_preferences,
                            '{pinned}',
                            COALESCE(
                                (
                                    SELECT jsonb_agg(elem)
                                    FROM jsonb_array_elements(
                                        COALESCE(agent_preferences->'pinned', '[]'::jsonb)
                                    ) AS elem
                                    WHERE (elem #>> '{}') != :agent_id
                                ),
                                '[]'::jsonb
                            )
                        ),
                        '{shared_with_me}',
                        COALESCE(
                            (
                                SELECT jsonb_agg(elem)
                                FROM jsonb_array_elements(
                                    COALESCE(agent_preferences->'shared_with_me', '[]'::jsonb)
                                ) AS elem
                                WHERE (elem #>> '{}') != :agent_id
                            ),
                            '[]'::jsonb
                        )
                    ),
                    updated_at = now()
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id, "agent_id": agent_id},
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _append_to_jsonb_array(self, user_id: str, key: str, agent_id: str) -> None:
        """Idempotent append of ``agent_id`` to ``agent_preferences.<key>``.

        The ``key`` argument is NOT user input — it's hard-coded by the
        calling method (``pinned`` / ``shared_with_me``). It goes into the
        SQL literal because ``jsonb_set`` requires a path literal, not a
        bind parameter. This is safe as long as callers never pass
        untrusted strings for ``key``.
        """
        if key not in ("pinned", "shared_with_me"):
            raise ValueError(f"unsupported jsonb key: {key!r}")
        self._conn.execute(
            text(
                f"""
                UPDATE users
                SET
                    agent_preferences = jsonb_set(
                        agent_preferences,
                        '{{{key}}}',
                        CASE
                            WHEN agent_preferences->'{key}' @> to_jsonb(CAST(:agent_id AS text))
                                THEN agent_preferences->'{key}'
                            ELSE
                                COALESCE(agent_preferences->'{key}', '[]'::jsonb)
                                || to_jsonb(CAST(:agent_id AS text))
                        END
                    ),
                    updated_at = now()
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id, "agent_id": agent_id},
        )

    def _remove_from_jsonb_array(
        self, user_id: str, key: str, agent_ids: list[str]
    ) -> None:
        """Remove every id in ``agent_ids`` from ``agent_preferences.<key>``."""
        if key not in ("pinned", "shared_with_me"):
            raise ValueError(f"unsupported jsonb key: {key!r}")
        self._conn.execute(
            text(
                f"""
                UPDATE users
                SET
                    agent_preferences = jsonb_set(
                        agent_preferences,
                        '{{{key}}}',
                        COALESCE(
                            (
                                SELECT jsonb_agg(elem)
                                FROM jsonb_array_elements(
                                    COALESCE(agent_preferences->'{key}', '[]'::jsonb)
                                ) AS elem
                                WHERE NOT ((elem #>> '{{}}') = ANY(:agent_ids))
                            ),
                            '[]'::jsonb
                        )
                    ),
                    updated_at = now()
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id, "agent_ids": agent_ids},
        )
