"""Base contract every guardrail check implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextvars import ContextVar
from time import monotonic
from typing import Any, ClassVar, Dict, List, Optional, Sequence, Set

from docsgpt.guardrails.types import Action, CheckOutcome, ControlVerdict, Stage

# Monotonic deadline of the stage a remote check is running for, set by the
# engine in the check's own thread.
stage_deadline: ContextVar[Optional[float]] = ContextVar("guardrail_stage_deadline", default=None)


def stage_time_left() -> Optional[float]:
    """Seconds until the stage deadline, in a remote check the engine runs; ``None`` outside one."""
    deadline = stage_deadline.get()
    return None if deadline is None else deadline - monotonic()


class ScanContext:
    """Ambient request state a check may need beyond the text itself."""

    def __init__(
        self,
        query: Optional[str] = None,
        retrieved_docs: Optional[list] = None,
        docs_provider=None,
        tool_name: Optional[str] = None,
        action_name: Optional[str] = None,
        tool_args: Optional[Dict[str, Any]] = None,
        llm_factory=None,
        agent_id: Optional[str] = None,
        user: Optional[str] = None,
        item_hints: Optional[List[Dict[str, Any]]] = None,
    ):
        self.query = query
        # Retrieval can land after the engine is built, and an agent rebinds
        # ``retrieved_docs`` rather than mutating it (tool collection, token
        # shedding, redaction), so a snapshot taken here goes stale. Reading
        # through a provider keeps every stage — including the streaming
        # output guard, which does not go through ``_guardrail_stage`` — on
        # this turn's actual documents.
        self._docs_provider = docs_provider
        self._retrieved_docs = retrieved_docs or []
        self.tool_name = tool_name
        self.action_name = action_name
        self.tool_args = tool_args or {}
        self.llm_factory = llm_factory
        self.agent_id = agent_id
        self.user = user
        # What the caller knows about each item of an item-level scan, aligned
        # with the items: ``allowed`` (the source's owner marked the text safe)
        # and ``injection`` (a score stored with the item, as an attachment
        # parsed with a scan carries). Set per ``evaluate_items`` call.
        self.item_hints = item_hints

    @property
    def retrieved_docs(self) -> list:
        if self._docs_provider is not None:
            try:
                return self._docs_provider() or []
            except Exception:
                return []
        return self._retrieved_docs

    @retrieved_docs.setter
    def retrieved_docs(self, value: Optional[list]) -> None:
        # An explicit assignment is authoritative: it replaces the provider so
        # a caller that pins documents is not silently overridden by the agent.
        self._docs_provider = None
        self._retrieved_docs = value or []


class GuardrailCheck(ABC):
    """A detector. Stateless per scan; constructed once per control."""

    #: Registry key.
    name: ClassVar[str] = ""
    #: Stages this check can meaningfully run at.
    supported_stages: ClassVar[Set[Stage]] = set()
    #: Whether ``scan`` reports character spans usable by the redact action.
    supports_redaction: ClassVar[bool] = False
    #: Rough inline cost, surfaced in the builder UI so the price of turning a
    #: check on is legible before it is turned on.
    latency_hint_ms: ClassVar[int] = 10
    #: Human-facing label and blurb for the agent builder.
    label: ClassVar[str] = ""
    description: ClassVar[str] = ""
    #: True when the check may block on a network call or model inference;
    #: it then runs under the stage deadline.
    remote: ClassVar[bool] = False
    #: True when the check scores each item of an item stage (a retrieved
    #: document, an attached file) on its own, so ``block`` withholds that item.
    #: Such a check is left out of the whole-text pass over the joined items.
    item_level: ClassVar[bool] = False
    #: Longest match this check can report, in characters. The streaming guard
    #: sizes its withhold window from this, so a check that under-declares it
    #: will miss matches straddling a chunk boundary.
    max_match_chars: ClassVar[int] = 128
    #: True when the verdict is only meaningful over the finished answer
    #: (groundedness), so the streaming guard defers it to the final scan.
    requires_complete_text: ClassVar[bool] = False

    @classmethod
    def window_for(cls, settings: Optional[Dict[str, Any]] = None) -> int:
        """Withhold window this check needs, given its configured settings."""
        return cls.max_match_chars

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        self.settings = settings or {}

    @classmethod
    def validate_settings(cls, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Strict-validate and normalise per-control settings on write.

        Returning the normalised dict lets a check fill defaults so a stored
        control is self-describing.
        """
        return settings

    @classmethod
    def is_available(cls) -> bool:
        """False when the check cannot run here (missing credentials, deps)."""
        return True

    @abstractmethod
    def scan(self, text: str, stage: Stage, context: ScanContext) -> CheckOutcome:
        """Inspect ``text`` and report an outcome. Must not raise."""

    def scan_items(self, texts: Sequence[str], stage: Stage, context: ScanContext) -> List[CheckOutcome]:
        """Inspect each item on its own; one outcome per item, in order. Must not raise.

        The default scans them one by one; a check that can score many texts
        in one call overrides it.
        """
        return [self.scan(text, stage, context) for text in texts]

    def settled(self, action: Action, verdict: ControlVerdict) -> None:
        """Called after ``scan`` with the verdict the engine reached; a no-op unless a check needs it.

        Args:
            action: The control's action at this stage, after the agent's mode
                (``monitor_only`` makes every action a flag).
            verdict: The control's verdict, its action capped by the outcome.
        """

    def settled_items(self, action: Action, verdicts: List[ControlVerdict], withheld: List[bool]) -> None:
        """Called after ``scan_items`` with the verdicts the engine reached; a no-op unless a check needs it.

        Args:
            action: The control's action at this stage, after the agent's mode.
            verdicts: One verdict per item, in order.
            withheld: Per item, whether the stage withholds it.
        """

    @classmethod
    def describe(cls) -> Dict[str, Any]:
        """Catalog entry consumed by the agent-builder UI."""
        return {
            "name": cls.name,
            "label": cls.label or cls.name,
            "description": cls.description,
            "stages": sorted(s.value for s in cls.supported_stages),
            "supports_redaction": cls.supports_redaction,
            "latency_hint_ms": cls.latency_hint_ms,
            "remote": cls.remote,
            "item_level": cls.item_level,
            "available": cls.is_available(),
        }
