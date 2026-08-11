"""Backfill ``tool_call_attempts.user_id`` / ``agent_id`` (migration 0018).

New rows are stamped at propose time by the tool executor. This script
fills historical rows from data we already trust; tiers run in one
transaction so each later tier sees only the rows still NULL.

Tiers
-----
1. Parent message (high confidence). Rows with a ``message_id`` copy the
   message's ``user_id`` and the conversation's ``agent_id``.

Message-less rows (headless: scheduled / webhook runs, plus pre-0018
parse-failure rows) are left NULL on purpose: there is no FK linking an
attempt to its run, so any inference from a schedule-run *time window*
would also catch webhook attempts and misattribute them to an unrelated
tenant whose run happened to span the same instant. The analytics reader
treats unattributable rows as invisible rather than guessing an owner,
and new headless rows are stamped at propose time by the executor.

Usage::

    # Dry-run (default): runs the fills in a rolled-back transaction and
    # reports exactly how many rows each tier would touch.
    python scripts/db/backfill_tool_attempts_attribution.py

    # Commit the backfill.
    python scripts/db/backfill_tool_attempts_attribution.py --apply

Exit codes:
    0 — success (dry-run or apply)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402

from application.storage.db.engine import get_engine  # noqa: E402


# Tier 1: parent message → user, conversation → agent.
_TIER1 = text(
    """
    UPDATE tool_call_attempts t
       SET user_id = m.user_id,
           agent_id = c.agent_id
      FROM conversation_messages m
      LEFT JOIN conversations c ON c.id = m.conversation_id
     WHERE t.message_id = m.id
       AND t.user_id IS NULL
    """
)

_COUNT_NULL = text(
    "SELECT count(*) FROM tool_call_attempts WHERE user_id IS NULL"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill tool_call_attempts.user_id/agent_id from existing data."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the backfill. Default is a rolled-back dry-run.",
    )
    args = parser.parse_args()

    engine = get_engine()
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            # A one-shot maintenance UPDATE can run well past the engine's
            # 30s per-statement guardrail; lift it for this transaction.
            conn.execute(text("SET LOCAL statement_timeout = 0"))

            before = conn.execute(_COUNT_NULL).scalar_one()

            t1 = conn.execute(_TIER1).rowcount or 0

            after = conn.execute(_COUNT_NULL).scalar_one()

            print(f"NULL user_id rows before:           {before}")
            print(f"  tier 1 (parent message):          {t1}")
            print(f"NULL user_id rows remaining:        {after}")
            print("  (message-less headless rows left NULL by design)")

            if args.apply:
                trans.commit()
                print("\nCommitted.")
            else:
                trans.rollback()
                print("\nDry run — rolled back. Re-run with --apply to commit.")
        except Exception:
            trans.rollback()
            raise

    return 0


if __name__ == "__main__":
    sys.exit(main())
