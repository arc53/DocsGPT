"""Streaming-safe output guarding.

Once a token reaches ``_emit`` it is on the wire and journalled — it cannot be
recalled. So output controls run *before* release, using the cheapest strategy
that still catches a match straddling a chunk boundary:

* Deterministic checks (regex-shaped, local): hold the last ``lookback``
  characters, run detection over ``held + new``, release only the safe prefix.
  Detecting over the whole buffer rather than the about-to-emit prefix is what
  makes this correct — a truncated prefix would fail to match a
  boundary-anchored pattern and the partial hit would leak.
* Remote checks (LLM judge, vendor API): accumulate to a sentence boundary and
  evaluate whole segments, because per-token calls are unaffordable and
  sentence granularity is the level at which such verdicts are meaningful.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from application.guardrails.engine import GuardrailEngine
from application.guardrails.guardrail_creator import GuardrailCreator
from application.guardrails.types import Stage, StageDecision

DEFAULT_LOOKBACK = 128
DEFAULT_SEGMENT_CHARS = 400
# Ceiling on the withhold window, and the hard release point that keeps a
# stream with no sentence boundary from stalling. The ceiling sits well below
# the stall point so the force path always has something to release.
MAX_WINDOW_CHARS = 8192
MAX_HOLD_CHARS = 16000

_SENTENCE_END = re.compile(r"[.!?\n](?=\s|$)")


def _last_boundary(text: str) -> int:
    """Index just past the last sentence terminator, or 0 if there is none."""
    last = 0
    for match in _SENTENCE_END.finditer(text):
        last = match.end()
    return last


@dataclass
class StreamChunk:
    """One step of the guarded stream."""

    emit: str = ""
    blocked: bool = False
    block_message: Optional[str] = None
    decisions: List[StageDecision] = field(default_factory=list)


class StreamingOutputGuard:
    """Buffers model output so output-stage controls can act before release."""

    def __init__(
        self,
        engine: GuardrailEngine,
        lookback: Optional[int] = None,
        segment_chars: int = DEFAULT_SEGMENT_CHARS,
    ):
        self.engine = engine
        self.segment_chars = max(1, segment_chars)
        self._held = ""
        self._blocked = False
        self._block_message: Optional[str] = None
        self.decisions: List[StageDecision] = []

        controls = engine.config.controls_for(Stage.OUTPUT)
        self._incremental = [c for c in controls if not self._complete_only(c)]
        self._deferred = [c for c in controls if self._complete_only(c)]
        self._has_remote = any(self._attr(c, "remote", False) for c in self._incremental)
        # The window must cover the longest match any active check can report,
        # or that check silently stops working the moment output is streamed.
        self.lookback = (
            max(0, lookback) if lookback is not None else self._required_window()
        )
        # Complete-text checks need the finished answer, not the tail.
        self._full = "" if self._deferred else None

    @staticmethod
    def _attr(control, name: str, default):
        try:
            return getattr(GuardrailCreator.get(control.check), name, default)
        except Exception:
            return default

    @classmethod
    def _complete_only(cls, control) -> bool:
        return bool(cls._attr(control, "requires_complete_text", False))

    def _required_window(self) -> int:
        window = DEFAULT_LOOKBACK
        for control in self._incremental:
            try:
                check_cls = GuardrailCreator.get(control.check)
                window = max(window, check_cls.window_for(control.settings))
            except Exception:
                continue
        return min(window, MAX_WINDOW_CHARS)

    @property
    def active(self) -> bool:
        return self.engine.has_stage(Stage.OUTPUT)

    @property
    def blocked(self) -> bool:
        return self._blocked

    @property
    def block_message(self) -> Optional[str]:
        return self._block_message

    @property
    def pending(self) -> str:
        """Text buffered but not yet released."""
        return self._held

    def feed(self, text: str) -> StreamChunk:
        """Absorb ``text``; return whatever is now safe to emit."""
        if self._blocked:
            return StreamChunk(blocked=True, block_message=self._block_message)
        if not text:
            return StreamChunk()
        if not self.active:
            return StreamChunk(emit=text)

        combined = self._held + text
        emit_end = self._release_point(combined)
        # Nothing to release yet and the buffer is still small: keep waiting
        # rather than paying for a scan of text that isn't going out.
        if emit_end == 0 and len(combined) <= MAX_HOLD_CHARS:
            self._held = combined
            return StreamChunk()

        return self._scan_and_split(combined, force=len(combined) > MAX_HOLD_CHARS)

    def flush(self) -> StreamChunk:
        """Release the tail at end of stream, after a final scan."""
        if self._blocked:
            return StreamChunk(blocked=True, block_message=self._block_message)
        if not self.active:
            tail, self._held = self._held, ""
            return StreamChunk(emit=tail)
        step = (
            self._scan_and_split(self._held, force=True, final=True)
            if self._held
            else StreamChunk()
        )
        if step.blocked:
            return step
        return self._run_deferred(step)

    def _run_deferred(self, step: StreamChunk) -> StreamChunk:
        """Run complete-text checks over the finished answer.

        These verdicts can only arrive after the answer is fully streamed, so a
        block here is a retraction, not a prevention — the caller emits the
        retract signal and rewrites the persisted message.
        """
        if not self._deferred or self._full is None:
            return step
        decision = self.engine.evaluate(
            self._full, Stage.OUTPUT, controls=self._deferred
        )
        self.decisions.append(decision)
        step.decisions.append(decision)
        if decision.blocked:
            self._blocked = True
            self._block_message = decision.block_message
            return StreamChunk(
                emit=step.emit,
                blocked=True,
                block_message=decision.block_message,
                decisions=step.decisions,
            )
        return step

    def _release_point(self, combined: str) -> int:
        """How much of ``combined`` is eligible for release this step."""
        lookback_point = max(0, len(combined) - self.lookback)
        if not self._has_remote:
            return lookback_point
        boundary = _last_boundary(combined)
        if boundary < self.segment_chars:
            return 0
        # Never release past the lookback point just because a sentence ended:
        # the deterministic checks still need their overlap window, and losing
        # it would let a match straddling two segments through.
        return min(boundary, lookback_point)

    def _scan_and_split(
        self, combined: str, force: bool = False, final: bool = False
    ) -> StreamChunk:
        if not self._incremental:
            # Only complete-text controls are configured; there is nothing to
            # decide per chunk, so don't manufacture an empty decision.
            return self._split(combined, force=force, final=final, decision=None)

        decision = self.engine.evaluate(
            combined, Stage.OUTPUT, controls=self._incremental
        )
        self.decisions.append(decision)

        if decision.blocked:
            self._blocked = True
            self._block_message = decision.block_message
            self._held = ""
            return StreamChunk(
                blocked=True,
                block_message=decision.block_message,
                decisions=[decision],
            )

        return self._split(decision.text, force=force, final=final, decision=decision)

    def _split(
        self, scanned: str, force: bool, final: bool, decision: Optional[StageDecision]
    ) -> StreamChunk:
        if final:
            emit_end = len(scanned)
        else:
            emit_end = self._release_point(scanned)
            if force and emit_end == 0:
                # Over the hold ceiling with no boundary in sight: release all
                # but the lookback tail so the stream cannot stall forever.
                emit_end = max(0, len(scanned) - self.lookback)

        self._held = scanned[emit_end:]
        emitted = scanned[:emit_end]
        if self._full is not None:
            self._full += emitted
        return StreamChunk(
            emit=emitted, decisions=[decision] if decision is not None else []
        )
