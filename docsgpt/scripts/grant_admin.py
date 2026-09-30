"""Grant, revoke, or list the ``admin`` role for DocsGPT users.

Manual admin grants are the bootstrap mechanism for RBAC: the first admin is
created here (there is no UI to grant admin until you already are one), and that
admin can then manage others. Grants are written to ``user_roles`` with
``source='manual'`` and take effect on the user's next request. Persisted roles
apply only under ``AUTH_TYPE=oidc``, and ``user_id`` is the OIDC ``sub``.

Usage::

    docsgpt grant-admin <user_id>            # grant admin
    docsgpt grant-admin <user_id> --revoke   # revoke the manual admin grant
    docsgpt grant-admin --list               # list current admins
    docsgpt grant-admin <user_id> --force    # grant even if no users row exists

Inside the Docker image, where the ``docsgpt`` console script is not
installed, run ``python -m docsgpt grant-admin ...``.

Exit codes:
    0 — success
    1 — bad usage / user not found (without --force)
    2 — database error
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Callable, Optional, Sequence

from docsgpt.storage.db.repositories.auth_events import AuthEventsRepository
from docsgpt.storage.db.repositories.user_roles import UserRolesRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger("grant_admin")

ACTOR = "cli"


def _list_admins() -> int:
    """Print every user holding the admin role, with where the grant came from.

    Returns:
        The exit code (always 0).
    """
    with db_readonly() as conn:
        admins = UserRolesRepository(conn).list_admins()
    if not admins:
        print("No admins found.")
        return 0
    print(f"{'user_id':40}  {'sources':20}  granted_at")
    for row in admins:
        sources = ",".join(row.get("sources") or [])
        print(f"{row['user_id']:40}  {sources:20}  {row.get('granted_at')}")
    return 0


def _grant(user_id: str, force: bool) -> int:
    """Grant the manual admin role to ``user_id`` and audit it once.

    Args:
        user_id: The user's OIDC ``sub``.
        force: Grant even when the user has never signed in.

    Returns:
        0 on success or when the grant already exists, 1 when the user is unknown and ``force`` is off.
    """
    with db_session() as conn:
        if not force and UsersRepository(conn).get(user_id) is None:
            print(
                f"No users row for {user_id!r}. The user must have signed in at least "
                f"once, or pass --force to grant anyway (creates a dangling grant).",
                file=sys.stderr,
            )
            return 1
        inserted = UserRolesRepository(conn).grant(user_id, "admin", source="manual", granted_by=ACTOR)
        if inserted:
            AuthEventsRepository(conn).insert(
                user_id,
                "role_granted",
                metadata={"role": "admin", "source": "manual", "granted_by": ACTOR},
            )
            print(f"Granted admin to {user_id!r}.")
        else:
            print(f"{user_id!r} already has a manual admin grant; nothing to do.")
    return 0


def _revoke(user_id: str) -> int:
    """Remove the manual admin grant from ``user_id``; OIDC-group grants are left alone.

    Args:
        user_id: The user's OIDC ``sub``.

    Returns:
        The exit code (always 0).
    """
    with db_session() as conn:
        removed = UserRolesRepository(conn).revoke(user_id, "admin", source="manual")
        if removed:
            AuthEventsRepository(conn).insert(
                user_id,
                "role_revoked",
                metadata={"role": "admin", "source": "manual", "revoked_by": ACTOR},
            )
            print(f"Revoked the manual admin grant from {user_id!r}.")
        else:
            print(
                f"{user_id!r} has no manual admin grant. "
                f"(OIDC-group grants are managed by group membership, not this command.)"
            )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse the arguments and grant, revoke or list admins.

    Args:
        argv: The arguments after the command name; ``sys.argv[1:]`` when omitted.

    Returns:
        The process exit code: 0 success, 1 bad usage or unknown user, 2 database error.
    """
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        prog="docsgpt grant-admin",
        description=(
            "Grant, revoke or list the admin role. Roles apply only under AUTH_TYPE=oidc; "
            "user_id is the user's OIDC sub."
        ),
    )
    parser.add_argument("user_id", nargs="?", help="The user's auth sub (OIDC subject id).")
    parser.add_argument("--revoke", action="store_true", help="Revoke the manual admin grant.")
    parser.add_argument("--list", action="store_true", help="List current admins and exit.")
    parser.add_argument("--force", action="store_true", help="Grant even if no users row exists yet.")
    args = parser.parse_args(argv)

    action: Callable[[], int]
    if args.list:
        action = _list_admins
    elif not args.user_id:
        parser.error("user_id is required unless --list is given.")
    elif args.revoke:
        action = lambda: _revoke(args.user_id)  # noqa: E731
    else:
        action = lambda: _grant(args.user_id, args.force)  # noqa: E731

    try:
        return action()
    except Exception:
        logger.error("Database operation failed", exc_info=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
