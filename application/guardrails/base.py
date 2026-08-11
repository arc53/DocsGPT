"""Base contract every guardrail check implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, Optional, Set

from application.guardrails.types import CheckOutcome, Stage


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
    #: True when the check needs a network round trip (LLM or vendor API).
    remote: ClassVar[bool] = False
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
            "available": cls.is_available(),
        }
