"""Tool-call policy: which actions may run, and with what arguments."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from application.guardrails.base import GuardrailCheck, ScanContext
from application.guardrails.types import CheckOutcome, Stage


def _matches(name: str, entry: str) -> bool:
    """Match ``tool``, ``tool.action`` or a trailing ``*`` prefix."""
    name, entry = name.lower(), entry.lower()
    if entry.endswith("*"):
        return name.startswith(entry[:-1])
    return name == entry or name.startswith(entry + ".")


# Argument text handed to an operator-supplied regex. Small on purpose: the
# stage deadline cannot actually preempt a runaway match, because CPython's
# ``re`` holds the GIL for the duration, so a catastrophic pattern starves the
# whole worker rather than just its own thread. Bounding the input and
# rejecting the exponential pattern shapes below are the real defences.
_MAX_HAYSTACK = 1024

_UNBOUNDED_QUANTIFIER = re.compile(r"(?<!\\)[*+]|(?<!\\)\{\d+,\}")


def _group_spans(pattern: str):
    """Yield ``(open_index, close_index)`` for each top-level-balanced group."""
    stack = []
    for index, char in enumerate(pattern):
        if index and pattern[index - 1] == "\\":
            continue
        if char == "(":
            stack.append(index)
        elif char == ")" and stack:
            yield stack.pop(), index


def assert_not_redos_prone(pattern: str) -> None:
    """Reject the nested-quantifier shapes that backtrack exponentially.

    ``(a+)+``, ``(a*)*``, ``(\\d+){2,}`` and friends: a quantified group whose
    body itself contains an unbounded quantifier. This is a heuristic, not a
    proof of safety, but it rejects every classic exponential construction
    while leaving ordinary patterns like ``.*@(?!arc53\\.com)`` alone.

    Raises:
        ValueError: When the pattern carries a nested quantifier.
    """
    for open_index, close_index in _group_spans(pattern):
        suffix = pattern[close_index + 1 : close_index + 2]
        quantified = suffix in ("*", "+")
        if not quantified and suffix == "{":
            end = pattern.find("}", close_index)
            if end != -1:
                bound = pattern[close_index + 2 : end]
                quantified = bound not in ("", "0", "1", "0,1", "1,1")
        if not quantified:
            continue
        body = pattern[open_index + 1 : close_index]
        if _UNBOUNDED_QUANTIFIER.search(body):
            raise ValueError(
                "pattern has a quantifier inside a repeated group "
                f"('{pattern[open_index : close_index + 2]}'), which can "
                "backtrack exponentially; rewrite it without the nesting"
            )


class ToolPolicyCheck(GuardrailCheck):
    name = "tool_policy"
    label = "Tool policy"
    description = (
        "Restricts which tool actions an agent may invoke and inspects their arguments "
        "before execution. Names match 'tool', 'tool.action' or a 'prefix*' wildcard."
    )
    supported_stages = {Stage.TOOL_CALL}
    supports_redaction = False
    latency_hint_ms = 1
    # Operator-supplied regex. validate_settings rejects the exponential
    # shapes and scan() bounds the haystack, but neither is a proof, so this
    # also runs under the stage deadline.
    unbounded_runtime = True

    @classmethod
    def validate_settings(cls, settings: Dict[str, Any]) -> Dict[str, Any]:
        allow = settings.get("allow_tools") or []
        block = settings.get("block_tools") or []
        raw_patterns = settings.get("arg_patterns") or []
        for label, value in (
            ("allow_tools", allow),
            ("block_tools", block),
            ("arg_patterns", raw_patterns),
        ):
            if not isinstance(value, list):
                raise ValueError(f"{label} must be a list")
            if len(value) > 100:
                raise ValueError(f"{label} accepts at most 100 entries")
        if not allow and not block and not raw_patterns:
            raise ValueError("provide allow_tools, block_tools or arg_patterns")

        patterns: List[Dict[str, str]] = []
        for entry in raw_patterns:
            if not isinstance(entry, dict):
                raise ValueError("each arg_patterns entry must be an object")
            pattern = str(entry.get("pattern", "")).strip()
            if not pattern:
                raise ValueError("each arg_patterns entry needs a 'pattern'")
            if len(pattern) > 300:
                raise ValueError("arg_patterns pattern must be <= 300 characters")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid regex '{pattern}': {exc}")
            assert_not_redos_prone(pattern)
            patterns.append(
                {"arg": str(entry.get("arg", "")).strip(), "pattern": pattern}
            )

        return {
            "allow_tools": [str(t).strip() for t in allow if str(t).strip()],
            "block_tools": [str(t).strip() for t in block if str(t).strip()],
            "arg_patterns": patterns,
        }

    def scan(self, text: str, stage: Stage, context: ScanContext) -> CheckOutcome:
        tool = (context.tool_name or "").strip()
        action = (context.action_name or "").strip()
        qualified = f"{tool}.{action}" if tool and action else (tool or action)
        if not qualified:
            return CheckOutcome.not_evaluated("tool call carried no name")

        allow = self.settings.get("allow_tools") or []
        block = self.settings.get("block_tools") or []
        categories: List[str] = []
        details: List[str] = []

        if any(_matches(qualified, entry) for entry in block):
            categories.append("TOOL_BLOCKED")
            details.append(f"'{qualified}' is on the blocked list")
        elif allow and not any(_matches(qualified, entry) for entry in allow):
            categories.append("TOOL_NOT_ALLOWED")
            details.append(f"'{qualified}' is not on the allowed list")

        for entry in self.settings.get("arg_patterns") or []:
            pattern = re.compile(entry["pattern"])
            arg_name = entry.get("arg") or ""
            if arg_name:
                value = context.tool_args.get(arg_name)
                haystack = "" if value is None else str(value)
            else:
                haystack = text
            haystack = haystack[:_MAX_HAYSTACK]
            if haystack and pattern.search(haystack):
                categories.append("ARG_PATTERN")
                details.append(
                    f"argument{' ' + arg_name if arg_name else ''} matched "
                    f"/{entry['pattern']}/"
                )

        if not categories:
            return CheckOutcome.clean()
        return CheckOutcome.hit(
            categories=list(dict.fromkeys(categories)), detail="; ".join(details)
        )
