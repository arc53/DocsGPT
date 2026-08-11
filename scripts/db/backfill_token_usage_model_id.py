"""Backfill ``token_usage.model_id`` for rows written before the column.

New rows get ``model_id`` stamped at write time (see
``application.llm.llm_creator`` / ``application.usage``). This script
fills the historical NULLs by deriving the model from data we already
trust, in priority order. A row is only ever filled by the
highest-priority tier that matches it; tiers run in one transaction so
each later tier sees only the rows still NULL.

Tiers (both touch only ``source='agent_stream'`` rows)
-----
1. ``request_id`` join (high confidence). The route stamps the same
   ``request_id`` on the token_usage row and the assistant message, so
   ``conversation_messages.model_id`` is authoritative for the call.
2. ``agent_id`` + nearest message (medium confidence). For primary rows
   with no usable ``request_id`` (legacy), copy ``model_id`` from the
   closest-in-time message of any conversation belonging to the same
   agent, within ``--window-minutes`` (ties broken toward the later
   message so re-runs are reproducible).

Side-channel rows (``fallback`` / ``compression`` / ``title`` /
``rag_condense`` / ``schedule``) are left NULL: they share the primary
turn's ``request_id`` or agent but often ran a *different* model (a
backup, a compression override), so copying the primary turn's model
onto them would mis-attribute spend. New rows already get the correct
per-call model stamped at write time, so this only concerns history.

Rows that match neither tier are left NULL on purpose — the partial
index ``token_usage_model_ts_idx`` excludes them, and a model we can't
tie to the specific call (e.g. the agent's configured default) would
poison the analytics it feeds.

Both ``model_id`` columns store the canonical id (catalog name for
built-ins, UUID for BYOM), so BYOM rows backfill to the UUID unchanged.

Usage::

    # Dry-run (default): runs the fills in a rolled-back transaction and
    # reports exactly how many rows each tier would touch.
    python scripts/db/backfill_token_usage_model_id.py

    # Commit the backfill.
    python scripts/db/backfill_token_usage_model_id.py --apply

    # Widen the tier-2 match window (default 5 minutes).
    python scripts/db/backfill_token_usage_model_id.py --window-minutes 10 --apply

Exit codes:
    0 — success (dry-run or apply)
    1 — bad arguments
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402

from application.storage.db.engine import get_engine  # noqa: E402


# Tier 1: same request -> same model, primary (agent_stream) rows only.
# conversation_messages.model_id is authoritative for that turn; fallback
# / compression rows share the request_id but ran a different model.
_TIER1 = text(
    """
    UPDATE token_usage tu
    SET model_id = cm.model_id
    FROM conversation_messages cm
    WHERE cm.request_id = tu.request_id
      AND cm.model_id IS NOT NULL
      AND tu.model_id IS NULL
      AND tu.request_id IS NOT NULL
      AND tu.source = 'agent_stream'
    """
)

# Tier 2: nearest message of the same agent within the window, primary
# (agent_stream) rows only. The EXISTS mirror skips rows with no match
# (else the subquery would set NULL); the ORDER BY tiebreak (later message
# wins) keeps the pick reproducible across re-runs.
_TIER2 = text(
    """
    UPDATE token_usage tu
    SET model_id = (
        SELECT cm.model_id
        FROM conversation_messages cm
        JOIN conversations c ON c.id = cm.conversation_id
        WHERE c.agent_id = tu.agent_id
          AND cm.model_id IS NOT NULL
          AND cm.timestamp BETWEEN tu.timestamp - make_interval(mins => :win)
                               AND tu.timestamp + make_interval(mins => :win)
        ORDER BY abs(extract(epoch FROM (cm.timestamp - tu.timestamp))), cm.timestamp DESC
        LIMIT 1
    )
    WHERE tu.model_id IS NULL
      AND tu.agent_id IS NOT NULL
      AND tu.source = 'agent_stream'
      AND EXISTS (
        SELECT 1
        FROM conversation_messages cm
        JOIN conversations c ON c.id = cm.conversation_id
        WHERE c.agent_id = tu.agent_id
          AND cm.model_id IS NOT NULL
          AND cm.timestamp BETWEEN tu.timestamp - make_interval(mins => :win)
                               AND tu.timestamp + make_interval(mins => :win)
      )
    """
)

_COUNT_NULL = text("SELECT count(*) FROM token_usage WHERE model_id IS NULL")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill token_usage.model_id from existing data.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the backfill. Default is a rolled-back dry-run.",
    )
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=5,
        metavar="N",
        help="Tier-2 nearest-message match window, in minutes (default 5).",
    )
    args = parser.parse_args()

    if args.window_minutes < 0:
        print("--window-minutes must be >= 0", file=sys.stderr)
        return 1

    engine = get_engine()
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            # A one-shot maintenance UPDATE can run well past the engine's
            # 30s per-statement guardrail; lift it for this transaction.
            conn.execute(text("SET LOCAL statement_timeout = 0"))

            before = conn.execute(_COUNT_NULL).scalar_one()

            t1 = conn.execute(_TIER1).rowcount or 0
            t2 = conn.execute(_TIER2, {"win": args.window_minutes}).rowcount or 0

            after = conn.execute(_COUNT_NULL).scalar_one()

            print(f"NULL model_id rows before:         {before}")
            print(f"  tier 1 (request_id):             {t1}")
            print(f"  tier 2 (agent + nearest msg):    {t2}")
            print(f"NULL model_id rows remaining:      {after}")

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
