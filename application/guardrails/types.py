"""Core value types for the guardrails subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Stage(str, Enum):
    """Intervention points a control can be attached to."""

    INPUT = "input"
    RETRIEVAL = "retrieval"
    TOOL_RESULT = "tool_result"
    OUTPUT = "output"


class Action(str, Enum):
    """What happens when a control triggers."""

    FLAG = "flag"
    REDACT = "redact"
    BLOCK = "block"


ACTIONS_BY_STAGE = {
    Stage.INPUT: {Action.FLAG, Action.REDACT, Action.BLOCK},
    Stage.RETRIEVAL: {Action.FLAG, Action.REDACT, Action.BLOCK},
    Stage.TOOL_RESULT: {Action.FLAG, Action.REDACT, Action.BLOCK},
    Stage.OUTPUT: {Action.FLAG, Action.REDACT, Action.BLOCK},
}


@dataclass(frozen=True)
class Span:
    """A matched region of the scanned text."""

    start: int
    end: int
    label: str
    replacement: Optional[str] = None

    def masked_with(self) -> str:
        return self.replacement if self.replacement is not None else f"[{self.label}]"


@dataclass
class CheckOutcome:
    """What a single check reports about one piece of text.

    ``evaluated=False`` marks "we could not tell" (timeout, provider error,
    missing credentials) and is deliberately distinct from a clean pass — the
    engine routes it through the fail-open/fail-closed policy instead of
    treating it as safe.
    """

    triggered: bool = False
    evaluated: bool = True
    categories: List[str] = field(default_factory=list)
    spans: List[Span] = field(default_factory=list)
    score: Optional[float] = None
    detail: str = ""
    error: Optional[str] = None

    @classmethod
    def clean(cls) -> "CheckOutcome":
        return cls()

    @classmethod
    def not_evaluated(cls, error: str) -> "CheckOutcome":
        return cls(evaluated=False, error=error)

    @classmethod
    def hit(
        cls,
        categories: Optional[List[str]] = None,
        spans: Optional[List[Span]] = None,
        score: Optional[float] = None,
        detail: str = "",
    ) -> "CheckOutcome":
        return cls(
            triggered=True,
            categories=categories or [],
            spans=spans or [],
            score=score,
            detail=detail,
        )


@dataclass
class ControlVerdict:
    """One control's outcome, carrying the action it was configured with."""

    check: str
    stage: Stage
    action: Action
    outcome: CheckOutcome

    @property
    def blocking(self) -> bool:
        return self.outcome.triggered and self.action is Action.BLOCK

    def as_log(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "stage": self.stage.value,
            "action": self.action.value,
            "triggered": self.outcome.triggered,
            "evaluated": self.outcome.evaluated,
            "categories": self.outcome.categories,
            "score": self.outcome.score,
            "detail": self.outcome.detail,
            "error": self.outcome.error,
            "match_count": len(self.outcome.spans),
        }


@dataclass
class StageDecision:
    """The engine's aggregate answer for one stage."""

    stage: Stage
    text: str
    blocked: bool = False
    redacted: bool = False
    block_message: Optional[str] = None
    verdicts: List[ControlVerdict] = field(default_factory=list)

    @property
    def triggered(self) -> List[ControlVerdict]:
        return [v for v in self.verdicts if v.outcome.triggered]

    @property
    def unevaluated(self) -> List[ControlVerdict]:
        return [v for v in self.verdicts if not v.outcome.evaluated]

    @property
    def clean(self) -> bool:
        return not self.blocked and not self.redacted and not self.triggered

    def categories(self) -> List[str]:
        seen: List[str] = []
        for verdict in self.triggered:
            for category in verdict.outcome.categories:
                if category not in seen:
                    seen.append(category)
        return seen

    def as_log(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "blocked": self.blocked,
            "redacted": self.redacted,
            "categories": self.categories(),
            "verdicts": [v.as_log() for v in self.verdicts if v.outcome.triggered or not v.outcome.evaluated],
        }


def apply_spans(text: str, spans: List[Span]) -> str:
    """Replace ``spans`` in ``text``, right-to-left so offsets stay valid.

    Overlapping spans are unioned, not deduplicated: two checks that both match
    the same region must not leave the un-overlapped remainder in the clear.
    Dropping the later span used to mean a 4-char ``BIN`` hit beat a 16-char
    ``CREDIT_CARD`` hit at the same offset and twelve digits survived.
    """
    if not spans:
        return text
    clamped: List[Span] = []
    for span in spans:
        start = max(0, span.start)
        end = min(len(text), span.end)
        if start >= end:
            continue
        clamped.append(
            span if (start, end) == (span.start, span.end)
            else Span(start, end, span.label, span.replacement)
        )
    if not clamped:
        return text

    merged: List[Span] = []
    for span in sorted(clamped, key=lambda s: (s.start, -s.end)):
        if merged and span.start < merged[-1].end:
            previous = merged[-1]
            if span.end > previous.end:
                merged[-1] = Span(
                    previous.start, span.end, previous.label, previous.replacement
                )
            continue
        merged.append(span)

    out = text
    for span in reversed(merged):
        out = out[: span.start] + span.masked_with() + out[span.end :]
    return out
