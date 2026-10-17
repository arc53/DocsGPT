"""Resolve the policy rows that apply to a user into effective limits.

Each budget (tokens, cost) resolves on its own: the user's row wins, then the
most generous of the user's team rows, then the instance row, then the
registered defaults. A row with neither a limit nor the unlimited flag for a
budget has no opinion on it and is skipped.

Teams resolve to the most generous allowance because team membership is not
controlled by the instance admin: under "most restrictive", any team admin
could throttle a user by adding them to a low-allowance team.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

LAYERS = ("user", "team", "instance", "default")

_FIELDS = {"tokens": ("token_limit", "token_unlimited"), "cost": ("cost_limit_usd", "cost_unlimited")}


@dataclass(frozen=True)
class ResolvedLimit:
    """One budget's effective limit and the layer it came from.

    ``limit`` is ``None`` when the budget is unlimited. ``source`` is ``None``
    when no layer had an opinion, otherwise one of ``LAYERS``; ``source_id`` is
    the team id for a team-sourced limit.
    """

    limit: Optional[float] = None
    source: Optional[str] = None
    source_id: Optional[str] = None

    @property
    def unlimited(self) -> bool:
        return self.limit is None


@dataclass(frozen=True)
class ResolvedLimits:
    """A user's effective token and cost limits for one bucket."""

    tokens: ResolvedLimit
    cost: ResolvedLimit

    @property
    def unlimited(self) -> bool:
        return self.tokens.unlimited and self.cost.unlimited


def _opinion(row: Mapping, budget: str) -> Optional[tuple[bool, Optional[float]]]:
    """Return ``(unlimited, limit)`` for a row's budget, or ``None`` if it defers."""
    limit_field, unlimited_field = _FIELDS[budget]
    if row.get(unlimited_field):
        return True, None
    value = row.get(limit_field)
    if value is None:
        return None
    return False, float(value)


def _resolve_budget(rows: Iterable[Mapping], budget: str) -> ResolvedLimit:
    by_layer: dict[str, list[tuple[Mapping, tuple[bool, Optional[float]]]]] = {}
    for row in rows:
        opinion = _opinion(row, budget)
        if opinion is not None:
            by_layer.setdefault(row["scope"], []).append((row, opinion))
    for layer in LAYERS:
        candidates = by_layer.get(layer)
        if not candidates:
            continue
        # Most generous first: unlimited, then the larger limit. Only the team
        # layer can hold more than one candidate. Ties break on subject id so
        # the reported source is stable.
        row, (unlimited, limit) = min(
            candidates,
            key=lambda c: (not c[1][0], -(c[1][1] or 0.0), str(c[0].get("subject_id") or "")),
        )
        source_id = str(row["subject_id"]) if layer == "team" else None
        return ResolvedLimit(limit=None if unlimited else limit, source=layer, source_id=source_id)
    return ResolvedLimit()


def resolve_limits(rows: Iterable[Mapping], bucket: str = "all") -> ResolvedLimits:
    """Return the effective limits for ``bucket`` from a user's applicable rows.

    Args:
        rows: Policy rows that apply to the user (their own, their teams', the
            instance's and any provider defaults). Disabled rows and rows for
            other buckets are ignored.
        bucket: The policy bucket to resolve.
    """
    applicable = [r for r in rows if r.get("bucket", "all") == bucket and r.get("enabled", True)]
    return ResolvedLimits(
        tokens=_resolve_budget(applicable, "tokens"),
        cost=_resolve_budget(applicable, "cost"),
    )
