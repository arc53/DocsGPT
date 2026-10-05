"""Admin-set usage quotas.

Limits live in ``quota_policies`` at three layers (instance default, team
per-member allowance, user override), each with a token budget and a USD
budget. ``QuotaService`` resolves a user's effective limits and compares them
with their ``token_usage`` totals over the current ``QUOTA_PERIOD`` window.
"""

from docsgpt.quotas.providers import QuotaDefaultsProvider, register_defaults_provider
from docsgpt.quotas.resolver import ResolvedLimit, ResolvedLimits, resolve_limits
from docsgpt.quotas.service import BucketStatus, QuotaExceeded, QuotaExceededError, QuotaService
from docsgpt.quotas.windows import window_bounds

__all__ = [
    "BucketStatus",
    "QuotaDefaultsProvider",
    "QuotaExceeded",
    "QuotaExceededError",
    "QuotaService",
    "ResolvedLimit",
    "ResolvedLimits",
    "register_defaults_provider",
    "resolve_limits",
    "window_bounds",
]
