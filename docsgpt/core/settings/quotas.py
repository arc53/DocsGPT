"""Admin-set usage quotas and the pricing that feeds their cost budgets."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, field_validator

from docsgpt.core.settings._shared import SettingsGroup


class QuotaSettings(SettingsGroup):
    """Quota window and the treatment of unpriced models."""

    QUOTA_PERIOD: Literal["day", "week", "month"] = Field(
        default="month",
        description=(
            "Window every usage quota is measured over. Windows are calendar-aligned in UTC: "
            "a day starts at 00:00, a week on Monday, a month on the 1st."
        ),
    )
    QUOTA_UNPRICED_RATE_PER_MILLION: Optional[list[float]] = Field(
        default=None,
        description=(
            "Fallback `[input, output]` USD rates per 1M tokens for models that declare no price, "
            "e.g. `[0.5, 1.5]`. Unset, such calls are recorded at $0 and only count toward token quotas."
        ),
    )
    @field_validator("QUOTA_UNPRICED_RATE_PER_MILLION")
    @classmethod
    def _two_non_negative_rates(cls, v: Optional[list[float]]) -> Optional[list[float]]:
        if v is None:
            return None
        if len(v) != 2 or any(rate < 0 for rate in v):
            raise ValueError("QUOTA_UNPRICED_RATE_PER_MILLION must be two non-negative numbers")
        return v
