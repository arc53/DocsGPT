"""Builtin guardrail checks. Importing this module registers them."""

from application.guardrails.checks.heuristics import GroundednessCheck, InjectionCheck
from application.guardrails.checks.judge import PolicyCheck
from application.guardrails.checks.patterns import (
    DenylistCheck,
    PIICheck,
    SecretsCheck,
    URLCheck,
)
from application.guardrails.guardrail_creator import GuardrailCreator

BUILTIN_CHECKS = (
    PIICheck,
    SecretsCheck,
    DenylistCheck,
    URLCheck,
    InjectionCheck,
    GroundednessCheck,
    PolicyCheck,
)

for _check in BUILTIN_CHECKS:
    GuardrailCreator.register(_check.name, _check)

__all__ = ["BUILTIN_CHECKS"]
