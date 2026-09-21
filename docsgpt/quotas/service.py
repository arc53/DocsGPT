"""Compare a user's usage with their effective limits."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from docsgpt.core.settings import settings
from docsgpt.quotas.providers import default_rows, get_defaults_provider
from docsgpt.quotas.resolver import ResolvedLimit, ResolvedLimits, resolve_limits
from docsgpt.quotas.windows import window_bounds
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

REQUEST_BUCKETS = ("direct", "agent")

_UNITS = {"tokens": "tokens", "cost": "USD"}


@dataclass(frozen=True)
class BucketStatus:
    """A user's limits and usage for one policy bucket in the current window."""

    bucket: str
    limits: ResolvedLimits
    tokens_used: int
    cost_used: float
    resets_at: datetime

    def exceeded_budget(self) -> Optional[str]:
        """Return ``tokens`` or ``cost`` when that budget is used up, else ``None``."""
        if not self.limits.tokens.unlimited and self.tokens_used >= self.limits.tokens.limit:
            return "tokens"
        if not self.limits.cost.unlimited and self.cost_used >= self.limits.cost.limit:
            return "cost"
        return None

    def to_dict(self) -> dict:
        """Return the JSON shape shared by the admin and user quota endpoints."""

        def budget(limit: ResolvedLimit, used: float) -> dict:
            return {
                "limit": limit.limit,
                "used": used,
                "source": limit.source,
                "source_id": limit.source_id,
            }

        return {
            "bucket": self.bucket,
            "tokens": budget(self.limits.tokens, self.tokens_used),
            "cost": budget(self.limits.cost, round(self.cost_used, 6)),
            "resets_at": self.resets_at.isoformat(),
        }


@dataclass(frozen=True)
class QuotaExceeded:
    """The exhausted budget that blocks a request."""

    user_id: str
    bucket: str
    budget: str
    usage: float
    limit: float
    source: Optional[str]
    source_id: Optional[str]
    resets_at: datetime

    @property
    def retry_after_seconds(self) -> int:
        now = datetime.now(self.resets_at.tzinfo)
        return max(int((self.resets_at - now).total_seconds()), 1)

    def to_payload(self) -> dict:
        """Return the client-facing error body, after the provider's adjustments."""
        unit = _UNITS[self.budget]
        if self.budget == "cost":
            amounts = f"${self.usage:.2f} of ${self.limit:.2f}"
        else:
            amounts = f"{int(self.usage):,} of {int(self.limit):,} tokens"
        payload = {
            "success": False,
            "error_code": "quota-exceeded",
            "message": f"Usage quota reached ({amounts}). It resets at {self.resets_at.isoformat()}.",
            "limit_scope": "user_quota",
            "dimension": self.budget,
            "unit": unit,
            "usage": round(self.usage, 6) if self.budget == "cost" else int(self.usage),
            "limit": self.limit if self.budget == "cost" else int(self.limit),
            "bucket": self.bucket,
            "source": self.source,
            "resets_at": self.resets_at.isoformat(),
        }
        try:
            return get_defaults_provider().error_payload(payload, self.user_id) or payload
        except Exception:
            logger.exception("quota defaults provider failed to build the error payload")
            return payload


class QuotaService:
    """Resolve limits and measure usage for the current ``QUOTA_PERIOD`` window."""

    @staticmethod
    def status(
        user_id: str,
        buckets: tuple[str, ...] = ("all",),
        now: Optional[datetime] = None,
    ) -> list[BucketStatus]:
        """Return the user's status for each of ``buckets``.

        Usage is only summed for buckets that carry a limit, so a user with no
        applicable policy costs one policy lookup and no usage query.
        """
        start, resets_at = window_bounds(settings.QUOTA_PERIOD, now)
        statuses: list[BucketStatus] = []
        with db_readonly() as conn:
            rows = QuotaPoliciesRepository(conn).policies_for_user(user_id) + default_rows(user_id)
            usage_repo = TokenUsageRepository(conn)
            for bucket in buckets:
                limits = resolve_limits(rows, bucket)
                tokens_used, cost_used = (0, 0.0)
                if not limits.unlimited:
                    tokens_used, cost_used = usage_repo.usage_totals(user_id=user_id, start=start, bucket=bucket)
                statuses.append(BucketStatus(bucket, limits, tokens_used, cost_used, resets_at))
        return statuses

    @classmethod
    def check(
        cls, user_id: Optional[str], bucket: str = "direct", now: Optional[datetime] = None
    ) -> Optional[QuotaExceeded]:
        """Return why ``user_id`` may not start a request, or ``None`` if they may.

        Both the ``all`` policies and the request's own bucket must have room.
        The check runs before the request, so the call that crosses a limit
        completes and the next one is refused. Any failure here allows the
        request: a quota outage must not take chat down.

        Args:
            user_id: The billable user. Requests with no user are not limited.
            bucket: ``direct`` for chat without an agent, ``agent`` for traffic through one.
            now: Reference instant, for tests.
        """
        if not user_id:
            return None
        if bucket not in REQUEST_BUCKETS:
            raise ValueError(f"unknown request bucket: {bucket!r}")
        try:
            statuses = cls.status(user_id, ("all", bucket), now)
        except Exception:
            logger.exception("quota check failed; allowing the request", extra={"user_id": user_id})
            return None
        for status in statuses:
            budget = status.exceeded_budget()
            if budget is None:
                continue
            limit = status.limits.tokens if budget == "tokens" else status.limits.cost
            return QuotaExceeded(
                user_id=user_id,
                bucket=status.bucket,
                budget=budget,
                usage=status.tokens_used if budget == "tokens" else status.cost_used,
                limit=limit.limit,
                source=limit.source,
                source_id=limit.source_id,
                resets_at=status.resets_at,
            )
        return None
