"""Grant, revoke, or list the ``admin`` role for DocsGPT users.

Manual admin grants are the bootstrap mechanism for RBAC: the first admin is
created here (there is no UI to grant admin until you already are one), and that
admin can then manage others. Grants are written to ``user_roles`` with
``source='manual'`` and take effect on the user's next request (persisted RBAC
applies under ``AUTH_TYPE=oidc``; ``user_id`` is the OIDC ``sub``).

Usage::

    python scripts/grant_admin.py <user_id>            # grant admin
    python scripts/grant_admin.py <user_id> --revoke   # revoke the manual admin grant
    python scripts/grant_admin.py --list               # list current admins
    python scripts/grant_admin.py <user_id> --force    # grant even if no users row exists

Exit codes:
    0 — success
    1 — bad usage / user not found (without --force)
    2 — database error
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make the project root importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dotenv  # noqa: E402

dotenv.load_dotenv()

from application.storage.db.repositories.auth_events import AuthEventsRepository  # noqa: E402
from application.storage.db.repositories.user_roles import UserRolesRepository  # noqa: E402
from application.storage.db.repositories.users import UsersRepository  # noqa: E402
from application.storage.db.session import db_readonly, db_session  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("grant_admin")

ACTOR = "cli"


def _list_admins() -> int:
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
    with db_session() as conn:
        if not force:
            if UsersRepository(conn).get(user_id) is None:
                print(
                    f"No users row for {user_id!r}. The user must have signed in at least "
                    f"once, or pass --force to grant anyway (creates a dangling grant).",
                    file=sys.stderr,
                )
                return 1
        inserted = UserRolesRepository(conn).grant(
            user_id, "admin", source="manual", granted_by=ACTOR
        )
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
                f"(OIDC-group grants are managed by group membership, not this script.)"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the admin role for DocsGPT users.")
    parser.add_argument("user_id", nargs="?", help="The user's auth sub (OIDC subject id).")
    parser.add_argument("--revoke", action="store_true", help="Revoke the manual admin grant.")
    parser.add_argument("--list", action="store_true", help="List current admins and exit.")
    parser.add_argument(
        "--force", action="store_true", help="Grant even if no users row exists yet."
    )
    args = parser.parse_args(argv)

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
