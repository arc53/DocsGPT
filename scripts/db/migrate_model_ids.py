"""Rewrite stored model IDs across active config tables.

Run this when a provider renames or deprecates a model ID. The catalog
in ``application/core/models/<provider>.yaml`` is updated to the new ID,
but existing agents and schedules still reference the old one and will
fail on the next call. This script rewrites every active config row
in-place inside a single transaction.

Tables touched (active config — would fail against the provider):

  * ``agents.default_model_id``   (Text)
  * ``agents.models``             (JSONB array of model-id strings)
  * ``schedules.model_id``        (Text)

Tables intentionally NOT touched (history):

  * ``conversation_messages.model_id`` — records which model wrote each
    assistant turn. Rewriting it would falsify history.
  * ``sources.model`` — stores the *embeddings* model name captured at
    ingestion, not a chat LLM.
  * ``user_custom_models.upstream_model_id`` — user-supplied BYOM config
    against a non-catalog endpoint. Out of scope for catalog rewrites.

Usage::

    # Dry-run with the built-in Gemini preview -> GA mapping (default).
    python scripts/db/migrate_model_ids.py

    # Apply the built-in mapping.
    python scripts/db/migrate_model_ids.py --apply

    # Custom mapping (replaces the built-in; repeat --map per pair).
    python scripts/db/migrate_model_ids.py \\
        --map gemini-3-flash-preview=gemini-3.5-flash \\
        --map gemini-3.1-flash-lite-preview=gemini-3.1-flash-lite \\
        --apply

Exit codes:
    0 — success (dry-run or apply)
    1 — bad arguments
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402

from application.storage.db.session import db_session  # noqa: E402


# Built-in mapping reflects the 2026-05-25 Google preview -> GA swap.
# Update when a new round of catalog churn happens.
DEFAULT_MAPPING: Dict[str, str] = {
    "gemini-3-flash-preview": "gemini-3.5-flash",
    "gemini-3.1-flash-lite-preview": "gemini-3.1-flash-lite",
}


# JSONB array element rewrite. The ``@>`` containment check in the
# WHERE clause skips rows that don't reference the old ID — without it
# every agent would be touched on every iteration.
_UPDATE_AGENTS_MODELS = text(
    """
    UPDATE agents
    SET models = (
        SELECT jsonb_agg(
            CASE WHEN elem = to_jsonb(CAST(:old AS text))
                 THEN to_jsonb(CAST(:new AS text))
                 ELSE elem
            END
        )
        FROM jsonb_array_elements(models) AS elem
    )
    WHERE models IS NOT NULL
      AND models @> to_jsonb(ARRAY[CAST(:old AS text)])
    """
)


def _parse_overrides(pairs: Iterable[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            raise SystemExit(f"--map expects OLD=NEW, got {raw!r}")
        old, new = (s.strip() for s in raw.split("=", 1))
        if not old or not new:
            raise SystemExit(f"--map values must be non-empty, got {raw!r}")
        mapping[old] = new
    return mapping


def _count_pre(conn, mapping: Dict[str, str]) -> Dict[str, int]:
    """Count rows that match the OLD IDs across all target columns."""
    out = {
        "agents.default_model_id": 0,
        "agents.models": 0,
        "schedules.model_id": 0,
    }
    for old in mapping:
        out["agents.default_model_id"] += conn.execute(
            text("SELECT count(*) FROM agents WHERE default_model_id = :old"),
            {"old": old},
        ).scalar_one()
        out["agents.models"] += conn.execute(
            text(
                "SELECT count(*) FROM agents "
                "WHERE models IS NOT NULL "
                "AND models @> to_jsonb(ARRAY[CAST(:old AS text)])"
            ),
            {"old": old},
        ).scalar_one()
        out["schedules.model_id"] += conn.execute(
            text("SELECT count(*) FROM schedules WHERE model_id = :old"),
            {"old": old},
        ).scalar_one()
    return out


def _apply(conn, mapping: Dict[str, str]) -> Dict[str, int]:
    """Execute the rewrites inside the caller's transaction."""
    out = {
        "agents.default_model_id": 0,
        "agents.models": 0,
        "schedules.model_id": 0,
    }
    for old, new in mapping.items():
        res = conn.execute(
            text(
                "UPDATE agents SET default_model_id = :new "
                "WHERE default_model_id = :old"
            ),
            {"new": new, "old": old},
        )
        out["agents.default_model_id"] += res.rowcount or 0

        res = conn.execute(_UPDATE_AGENTS_MODELS, {"old": old, "new": new})
        out["agents.models"] += res.rowcount or 0

        res = conn.execute(
            text("UPDATE schedules SET model_id = :new WHERE model_id = :old"),
            {"new": new, "old": old},
        )
        out["schedules.model_id"] += res.rowcount or 0
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rewrite stored model IDs across active config tables.",
    )
    parser.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="OLD=NEW",
        help=(
            "Replace the built-in mapping. Repeat for each pair. "
            "If any --map is given, the built-in mapping is replaced, "
            "not merged."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the UPDATEs. Default is dry-run.",
    )
    args = parser.parse_args()

    mapping = _parse_overrides(args.map) if args.map else dict(DEFAULT_MAPPING)

    print("Mapping:")
    for old, new in mapping.items():
        print(f"  {old}  ->  {new}")
    print()

    with db_session() as conn:
        counts = _count_pre(conn, mapping)
        print("Rows matching old IDs (pre-update):")
        for col, n in counts.items():
            print(f"  {col:30s}  {n}")
        print()

        if sum(counts.values()) == 0:
            print("Nothing to do.")
            return 0

        if not args.apply:
            print("Dry run. Re-run with --apply to commit.")
            return 0

        updated = _apply(conn, mapping)
        print("Rows updated:")
        for col, n in updated.items():
            print(f"  {col:30s}  {n}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
