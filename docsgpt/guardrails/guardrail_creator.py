"""Registry of guardrail checks."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Type

from docsgpt.core.settings import settings
from docsgpt.guardrails.base import GuardrailCheck

logger = logging.getLogger(__name__)


class GuardrailCreator:
    """Dict registry with lazy builtin bootstrap, mirroring ``ChunkerCreator``."""

    checks: Dict[str, Type[GuardrailCheck]] = {}
    _bootstrapped = False

    @classmethod
    def _ensure_builtin(cls) -> None:
        if cls._bootstrapped:
            return
        cls._bootstrapped = True
        import docsgpt.guardrails.checks  # noqa: F401

    @classmethod
    def register(cls, key: str, check_class: Type[GuardrailCheck]) -> None:
        cls.checks[key] = check_class

    @classmethod
    def is_registered(cls, key: str) -> bool:
        cls._ensure_builtin()
        return key in cls.checks

    @classmethod
    def get(cls, key: str) -> Type[GuardrailCheck]:
        cls._ensure_builtin()
        check_class = cls.checks.get(key)
        if not check_class:
            raise ValueError(f"No guardrail check found for key {key}")
        return check_class

    @classmethod
    def create(cls, key: str, settings_dict: Optional[Dict[str, Any]] = None) -> GuardrailCheck:
        if key not in cls.enabled_keys():
            raise ValueError(f"guardrail check {key} is disabled on this instance")
        return cls.get(key)(settings_dict or {})

    @classmethod
    def enabled_keys(cls) -> List[str]:
        """Registry keys permitted by ``GUARDRAILS_CHECKS_ENABLED``.

        An empty allowlist means "everything registered", so adding a check
        does not require an operator to also edit their env.
        """
        cls._ensure_builtin()
        allowlist = settings.GUARDRAILS_CHECKS_ENABLED or []
        if not allowlist:
            return sorted(cls.checks)
        return sorted(k for k in cls.checks if k in set(allowlist))

    @classmethod
    def catalog(cls) -> List[Dict[str, Any]]:
        cls._ensure_builtin()
        return [cls.checks[k].describe() for k in cls.enabled_keys()]


def warn_unknown_checks_enabled() -> List[str]:
    """Log a warning for ``GUARDRAILS_CHECKS_ENABLED`` entries that name no registered check.

    Such entries are filtered out like any other name outside the allowlist, so a typo, or a
    value such as ``none`` meant to turn checks off, quietly leaves only the names that do
    match: with none left, every check is disabled. That stays the behaviour; this only says so.

    Returns:
        The unknown entries, in the order they were configured; empty when every entry is a check.
    """
    GuardrailCreator._ensure_builtin()
    configured = settings.GUARDRAILS_CHECKS_ENABLED or []
    unknown = [key for key in configured if key not in GuardrailCreator.checks]
    if unknown:
        enabled = GuardrailCreator.enabled_keys()
        logger.warning(
            "GUARDRAILS_CHECKS_ENABLED has entries that are not registered guardrail checks: %s. They are "
            "ignored, so %s. Registered checks: %s. To turn guardrails off, set GUARDRAILS_ENABLED=false instead.",
            ", ".join(unknown),
            "the enabled checks are " + ", ".join(enabled) if enabled else "no guardrail check is enabled",
            ", ".join(sorted(GuardrailCreator.checks)),
        )
    return unknown
