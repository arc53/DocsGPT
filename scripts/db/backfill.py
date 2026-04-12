"""Backfill DocsGPT's Postgres user-data tables from MongoDB.

One script for every migrated collection. Adding a new collection is a
two-step change in this file:

1. Write a ``_backfill_<name>`` function that takes keyword args
   ``conn``, ``mongo_db``, ``batch_size``, ``dry_run`` and returns a
   stats ``dict``.
2. Add a single entry to :data:`BACKFILLERS`.

There are intentionally no per-collection CLI flags or environment
variables — ``USE_POSTGRES`` / ``READ_POSTGRES`` in ``.env`` are the
only knobs operators need. This script discovers what's available from
the :data:`BACKFILLERS` registry and runs whichever tables were asked for.

Usage::

    python scripts/db/backfill.py                     # every registered table
    python scripts/db/backfill.py --tables users     # only specific tables
    python scripts/db/backfill.py --dry-run          # count without writing
    python scripts/db/backfill.py --batch 1000       # tune commit size

Exit codes:
    0 — every requested table completed successfully
    1 — misconfiguration (missing env var, unknown table name)
    2 — at least one table failed at runtime (others may still have succeeded)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

# Make the project root importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import Connection, text  # noqa: E402

from application.core.mongo_db import MongoDB  # noqa: E402
from application.core.settings import settings  # noqa: E402
from application.storage.db.engine import get_engine  # noqa: E402

logger = logging.getLogger("backfill")


# ---------------------------------------------------------------------------
# Per-table backfillers
# ---------------------------------------------------------------------------


def _backfill_users(
    *,
    conn: Connection,
    mongo_db: Any,
    batch_size: int,
    dry_run: bool,
) -> dict:
    """Sync the ``users`` table from Mongo ``users`` collection.

    Overwrites each Postgres row's ``agent_preferences`` with the Mongo
    state (Mongo is source of truth during the cutover window). Missing
    ``pinned`` / ``shared_with_me`` keys are filled with empty arrays so
    the Postgres row always has the full shape the application expects.
    """
    upsert_sql = text(
        """
        INSERT INTO users (user_id, agent_preferences)
        VALUES (:user_id, CAST(:prefs AS jsonb))
        ON CONFLICT (user_id) DO UPDATE
            SET agent_preferences = EXCLUDED.agent_preferences,
                updated_at = now()
        """
    )

    cursor = (
        mongo_db["users"]
        .find({}, no_cursor_timeout=True)
        .batch_size(batch_size)
    )

    seen = 0
    written = 0
    skipped = 0
    batch: list[dict] = []

    try:
        for doc in cursor:
            seen += 1
            user_id = doc.get("user_id")
            if not user_id:
                skipped += 1
                continue

            raw_prefs = doc.get("agent_preferences") or {}
            prefs = {
                "pinned": list(raw_prefs.get("pinned") or []),
                "shared_with_me": list(raw_prefs.get("shared_with_me") or []),
            }
            batch.append({"user_id": user_id, "prefs": json.dumps(prefs)})

            if len(batch) >= batch_size:
                if not dry_run:
                    conn.execute(upsert_sql, batch)
                written += len(batch)
                batch.clear()

        if batch:
            if not dry_run:
                conn.execute(upsert_sql, batch)
            written += len(batch)
    finally:
        cursor.close()

    return {"seen": seen, "written": written, "skipped_no_user_id": skipped}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


BackfillFn = Callable[..., dict]

# Register new tables here. Order matters only in the sense that
# ``--tables`` without arguments iterates in insertion order — put tables
# with FK dependencies after the tables they reference so a full-run
# backfill doesn't hit FK errors.
BACKFILLERS: dict[str, BackfillFn] = {
    "users": _backfill_users,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill DocsGPT Postgres tables from MongoDB."
    )
    parser.add_argument(
        "--tables",
        default="",
        help=(
            "Comma-separated table names to backfill. "
            f"Defaults to every registered table ({','.join(BACKFILLERS)})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Iterate Mongo without writing to Postgres.",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=500,
        help="How many rows to commit per Postgres statement (default: 500).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    )

    if not settings.POSTGRES_URI:
        logger.error("POSTGRES_URI is not set. Configure it in .env first.")
        return 1
    if not settings.MONGO_URI:
        logger.error("MONGO_URI is not set. Configure it in .env first.")
        return 1

    requested = [t.strip() for t in args.tables.split(",") if t.strip()]
    if not requested:
        requested = list(BACKFILLERS)

    unknown = [t for t in requested if t not in BACKFILLERS]
    if unknown:
        logger.error(
            "Unknown table(s): %s. Available: %s",
            ", ".join(unknown),
            ", ".join(BACKFILLERS),
        )
        return 1

    mongo = MongoDB.get_client()
    mongo_db = mongo[settings.MONGO_DB_NAME]
    engine = get_engine()

    failures = 0
    for table in requested:
        logger.info("backfill %s: start", table)
        try:
            with engine.begin() as conn:
                stats = BACKFILLERS[table](
                    conn=conn,
                    mongo_db=mongo_db,
                    batch_size=args.batch,
                    dry_run=args.dry_run,
                )
            logger.info(
                "backfill %s: done %s dry_run=%s", table, stats, args.dry_run
            )
        except Exception:
            failures += 1
            logger.exception("backfill %s: failed", table)

    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
