"""Connector OAuth sign-ins, bound to the user who started them.

The provider sends the browser back to the app's ``/connectors/callback``
page (directly, or through the API callback that forwards there). The page
posts the ``code`` and ``state`` with its own login, and the sign-in is only
finished when that login is the user who started it. A sign-in link handed
to someone else ends with a code their own login cannot spend on the
starter's account.

A sign-in for a team (``owner_id``, the team's principal) is still finished
only by the person who started it; the flow row, never the request, says
which team the account is for and whether it replaces the account of an
existing team connection (``replace_account``).
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


def start(
    conn,
    user_id: str,
    provider: str,
    connection_id: str,
    return_origin: str,
    *,
    owner_id: Optional[str] = None,
    replace_account: bool = False,
) -> str:
    """Record a new sign-in and return the ``state`` to send to the provider.

    Args:
        conn: Open connection inside a transaction.
        user_id: The person starting the sign-in; only they can finish it.
        provider: The connector, e.g. ``google_drive``.
        connection_id: The connection the sign-in writes into.
        return_origin: The app origin that started it; the API callback
            forwards there. Must already be an allowed origin.
        owner_id: The team principal the account is connected for; None for
            the person's own connection.
        replace_account: Whether finishing it replaces the account of the
            team connection ``connection_id`` in place.

    Returns:
        The ``state`` to send to the provider.
    """
    conn.execute(text("DELETE FROM connector_oauth_flows WHERE expires_at < now()"))
    state = secrets.token_urlsafe(32)
    conn.execute(
        text(
            "INSERT INTO connector_oauth_flows (user_id, provider, connection_id, state_hash, return_origin, "
            "expires_at, owner_id, replace_account) VALUES (:user_id, :provider, CAST(:connection_id AS uuid), "
            f":state_hash, :return_origin, now() + interval '{STATE_TTL_MINUTES} minutes', :owner_id, "
            ":replace_account)"
        ),
        {
            "user_id": user_id,
            "provider": provider,
            "connection_id": connection_id,
            "state_hash": _digest(state),
            "return_origin": return_origin,
            "owner_id": owner_id,
            "replace_account": bool(replace_account),
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
        The sign-in (with its ``owner_id`` and ``replace_account``), or None
        when the state is unknown, used, expired or was started by another user.
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
