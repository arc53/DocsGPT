"""Builtin guardrail checks. Importing this module registers them."""

from docsgpt.guardrails.checks.heuristics import GroundednessCheck, InjectionCheck
from docsgpt.guardrails.checks.judge import PolicyCheck
from docsgpt.guardrails.checks.patterns import (
    DenylistCheck,
    PIICheck,
    SecretsCheck,
    URLCheck,
)
from docsgpt.guardrails.guardrail_creator import GuardrailCreator

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
