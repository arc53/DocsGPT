"""Registry of guardrail checks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from application.core.settings import settings
from application.guardrails.base import GuardrailCheck


class GuardrailCreator:
    """Dict registry with lazy builtin bootstrap, mirroring ``ChunkerCreator``."""

    checks: Dict[str, Type[GuardrailCheck]] = {}
    _bootstrapped = False

    @classmethod
    def _ensure_builtin(cls) -> None:
        if cls._bootstrapped:
            return
        cls._bootstrapped = True
        import application.guardrails.checks  # noqa: F401

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
        allowlist = getattr(settings, "GUARDRAILS_CHECKS_ENABLED", None) or []
        if not allowlist:
            return sorted(cls.checks)
        return sorted(k for k in cls.checks if k in set(allowlist))

    @classmethod
    def catalog(cls) -> List[Dict[str, Any]]:
        cls._ensure_builtin()
        return [cls.checks[k].describe() for k in cls.enabled_keys()]
