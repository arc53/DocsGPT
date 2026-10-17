"""Connector OAuth sign-ins, bound to the user who started them.

The provider sends the browser back to the app's ``/connectors/callback``
page (directly, or through the API callback that forwards there). The page
posts the ``code`` and ``state`` with its own login, and the sign-in is only
finished when that login is the user who started it. A sign-in link handed
to someone else ends with a code their own login cannot spend on the
starter's account.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Optional

from sqlalchemy import text

from docsgpt.storage.db.base_repository import row_to_dict

# From the authorization URL to the app posting the code: consent can take a while.
STATE_TTL_MINUTES = 15


def _digest(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def start(conn, user_id: str, provider: str, connection_id: str, return_origin: str) -> str:
    """Record a new sign-in and return the ``state`` to send to the provider.

    Args:
        conn: Open connection inside a transaction.
        user_id: The user starting the sign-in.
        provider: The connector, e.g. ``google_drive``.
        connection_id: The connection the sign-in writes into.
        return_origin: The app origin that started it; the API callback
            forwards there. Must already be an allowed origin.
    """
    conn.execute(text("DELETE FROM connector_oauth_flows WHERE expires_at < now()"))
    state = secrets.token_urlsafe(32)
    conn.execute(
        text(
            "INSERT INTO connector_oauth_flows (user_id, provider, connection_id, state_hash, return_origin, "
            "expires_at) VALUES (:user_id, :provider, CAST(:connection_id AS uuid), :state_hash, :return_origin, "
            f"now() + interval '{STATE_TTL_MINUTES} minutes')"
        ),
        {
            "user_id": user_id,
            "provider": provider,
            "connection_id": connection_id,
            "state_hash": _digest(state),
            "return_origin": return_origin,
        },
    )
    return state


def peek(conn, state: Optional[str]) -> Optional[dict]:
    """The unexpired sign-in ``state`` names, without using it up."""
    if not state:
        return None
    row = conn.execute(
        text("SELECT * FROM connector_oauth_flows WHERE state_hash = :state_hash AND expires_at > now()"),
        {"state_hash": _digest(state)},
    ).fetchone()
    return row_to_dict(row) if row is not None else None


def take(conn, state: Optional[str], user_id: str) -> Optional[dict]:
    """Use up ``state`` for ``user_id``.

    The state is spent whoever presents it, so a refused one cannot be
    retried.

    Returns:
        The sign-in, or None when the state is unknown, used, expired or was
        started by another user.
    """
    if not state or not user_id:
        return None
    row = conn.execute(
        text(
            "DELETE FROM connector_oauth_flows "
            "WHERE state_hash = :state_hash AND expires_at > now() RETURNING *"
        ),
        {"state_hash": _digest(state)},
    ).fetchone()
    if row is None:
        return None
    flow = row_to_dict(row)
    return flow if flow["user_id"] == user_id else None
