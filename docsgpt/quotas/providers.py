"""Extension point for limits that do not come from ``quota_policies``.

A deployment can register a provider that supplies per-user default policies
(for example from a subscription plan) and adjusts the quota error payload.
Defaults sit below every stored layer: a stored instance, team or user row
with an opinion always wins.
"""

from __future__ import annotations

from typing import Mapping


class QuotaDefaultsProvider:
    """Base provider: no defaults, error payload unchanged."""

    def default_policies(self, user_id: str) -> list[dict]:
        """Return default policy rows for ``user_id``.

        Each row uses the ``quota_policies`` field names (``bucket``,
        ``token_limit``, ``token_unlimited``, ``cost_limit_usd``,
        ``cost_unlimited``); ``scope`` is set by the caller.
        """
        return []

    def error_payload(self, payload: dict, user_id: str) -> dict:
        """Return the payload sent to a client whose quota is exhausted."""
        return payload


_provider: QuotaDefaultsProvider = QuotaDefaultsProvider()


def register_defaults_provider(provider: QuotaDefaultsProvider) -> None:
    """Replace the process-wide defaults provider."""
    global _provider
    _provider = provider


def get_defaults_provider() -> QuotaDefaultsProvider:
    """Return the registered defaults provider."""
    return _provider


def default_rows(user_id: str) -> list[dict]:
    """Return the provider's defaults for ``user_id`` as ``default``-layer rows."""
    rows: list[dict] = []
    for row in get_defaults_provider().default_policies(user_id) or []:
        if isinstance(row, Mapping):
            rows.append({"bucket": "all", "enabled": True, **row, "scope": "default", "subject_id": None})
    return rows
