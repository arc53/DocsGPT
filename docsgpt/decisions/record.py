"""The request's decision record: what each feature asked the decision model and what it did with the answer.

Features do not thread a dict through the request. The harness keeps one record per request in a context variable,
and the chat stream stores it on the assistant message as ``metadata.decisions``:

    from docsgpt.decisions import record

    record.add("retrieval_gate", {"p": 0.07, "threshold": 0.2, "action": "skip_retrieval"},
               status="ok", applied=True, ms=212.4)        # a no-op when no record is active

    {"v": 1,
     "model": {"id": "arc53/arc-decide-0.4b-v0.2", "version": "...", "runtime": "onnx-int8", "mode": "api"},
     "entries": [{"feature": "retrieval_gate", "round": 0, "status": "ok", "applied": true, "ms": 212.4,
                  "outcome": {"p": 0.07, "threshold": 0.2, "action": "skip_retrieval"}}],
     "dropped": 0}

An outcome holds numbers, flags, labels and short lists, never text: the record is stored with the message, and
``add`` refuses anything that could carry the user's words. A message keeps at most ``MAX_ENTRIES`` entries; later
ones are only counted in ``dropped``. A paused turn saves the record with its other per-turn state
(``BaseAgent.paused_turn_state``), and the resume continues it in the next ``round``, so the message the resumed
turn finalizes holds every round.
"""

from __future__ import annotations

import contextlib
import math
import re
import threading
from contextvars import ContextVar
from typing import Any, Iterator, Optional

from docsgpt import decisions, tracing
from docsgpt.decisions.types import ModelInfo

#: Format of the stored record.
VERSION = 1
#: Entries one message keeps; the rest are counted in ``dropped``, so the metadata stays small.
MAX_ENTRIES = 64
#: Items an outcome list may hold.
MAX_LIST_ITEMS = 16
#: What an entry's ``status`` may be.
STATUSES = frozenset({"ok", "unavailable", "timeout", "skipped", "error"})
#: A string an outcome may hold: a label such as an option name or an action, never a sentence.
_LABEL = re.compile(r"^[\w.:/-]{0,64}$")

_current: ContextVar[Optional["DecisionRecord"]] = tracing.carry(ContextVar("docsgpt_decision_record", default=None))


def _model(info: ModelInfo) -> dict:
    return {"id": info.id, "version": info.version, "runtime": info.runtime, "mode": info.mode}


def _scalar(key: str, value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"decision record outcome {key!r} is not a finite number")
        return value
    if isinstance(value, str) and _LABEL.match(value):
        return value
    raise ValueError(f"decision record outcome {key!r} must be a number, a flag or a short label, never text")


def _outcome(outcome: dict) -> dict:
    """``outcome`` checked to hold nothing but scalars and short lists of them.

    Raises:
        ValueError: For text, nested structures or long lists: a caller bug.
    """
    checked = {}
    for key, value in outcome.items():
        if not isinstance(key, str) or not _LABEL.match(key):
            raise ValueError(f"decision record outcome key {key!r} is not a short label")
        if isinstance(value, (list, tuple)):
            if len(value) > MAX_LIST_ITEMS:
                raise ValueError(f"decision record outcome {key!r} has more than {MAX_LIST_ITEMS} items")
            checked[key] = [_scalar(key, item) for item in value]
        else:
            checked[key] = _scalar(key, value)
    return checked


class DecisionRecord:
    """One request's decision entries, safe to add to from several threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.round = 0
        # The stored document. Its keys are fixed from the start, so the stream
        # can serialize the metadata holding it while another thread adds an entry.
        self._doc: dict = {"v": VERSION, "model": None, "entries": [], "dropped": 0}
        self._metadata: Optional[dict] = None

    def add(self, feature: str, outcome: dict, *, status: str, applied: bool, ms: Optional[float] = None,
            model: Optional[ModelInfo] = None) -> None:
        """Record one feature's use of the decision model.

        Args:
            feature: The feature's label, as it passes to ``decide``.
            outcome: What the feature defines: numbers, flags, labels and short lists, never text.
            status: ``ok``, ``unavailable``, ``timeout``, ``skipped`` or ``error``.
            applied: False when the feature only watched (monitor mode) and did not act on the answer.
            ms: How long the feature waited for the model.
            model: The model that answered; the process's current one when omitted.

        Raises:
            ValueError: For an unknown status or an outcome that could hold text.
        """
        if status not in STATUSES:
            raise ValueError(f"decision record status must be one of {', '.join(sorted(STATUSES))}")
        entry: dict = {"feature": feature, "round": self.round, "status": status, "applied": bool(applied)}
        if ms is not None:
            entry["ms"] = round(float(ms), 1)
        entry["outcome"] = _outcome(outcome)
        if model is None:
            model = decisions.model_info()
        described = _model(model) if model is not None else None
        with self._lock:
            if described is not None:
                if self._doc["model"] is None:
                    self._doc["model"] = described
                elif described != self._doc["model"]:
                    entry["model"] = described
            if len(self._doc["entries"]) < MAX_ENTRIES:
                self._doc["entries"].append(entry)
            else:
                self._doc["dropped"] += 1
            if self._metadata is not None:
                self._metadata["decisions"] = self._doc

    def attach(self, metadata: dict) -> None:
        """Hold the record in ``metadata["decisions"]`` by reference, from its first entry on.

        Every path that persists ``metadata`` then stores the record as it stands; a request that recorded nothing
        leaves ``metadata`` without the key.
        """
        with self._lock:
            self._metadata = metadata
            if self._doc["entries"] or self._doc["dropped"]:
                metadata["decisions"] = self._doc

    def snapshot(self) -> Optional[dict]:
        """A JSON-safe copy for a paused turn's saved state, or ``None`` when nothing was recorded."""
        with self._lock:
            if not self._doc["entries"] and not self._doc["dropped"]:
                return None
            # Entries and the model are never changed once stored, so a shallow copy is a stable one.
            return {**self._doc, "entries": list(self._doc["entries"]), "round": self.round}

    def resume(self, saved: Any) -> None:
        """Continue the record a paused turn saved, one round later.

        Args:
            saved: The paused turn's ``snapshot()``; ``None`` when its rounds recorded nothing.
        """
        with self._lock:
            if not isinstance(saved, dict):
                self.round = 1
                return
            self.round = int(saved.get("round") or 0) + 1
            model = saved.get("model")
            self._doc["model"] = dict(model) if isinstance(model, dict) else None
            entries = [dict(e) for e in saved.get("entries") or [] if isinstance(e, dict)]
            self._doc["entries"] = entries[:MAX_ENTRIES]
            self._doc["dropped"] = int(saved.get("dropped") or 0) + len(entries[MAX_ENTRIES:])


def current() -> Optional[DecisionRecord]:
    """The record active in this context, or ``None``."""
    return _current.get()


@contextlib.contextmanager
def activate(rec: Optional[DecisionRecord]) -> Iterator[Optional[DecisionRecord]]:
    """Make ``rec`` the active record for the enclosed block (a no-op for ``None``)."""
    if rec is None:
        yield None
        return
    token = _current.set(rec)
    try:
        yield rec
    finally:
        try:
            _current.reset(token)
        except ValueError:
            # Reset from another context (a generator finalized elsewhere).
            _current.set(None)


def add(feature: str, outcome: dict, *, status: str, applied: bool, ms: Optional[float] = None,
        model: Optional[ModelInfo] = None) -> None:
    """Record into the active record (see ``DecisionRecord.add``); a no-op when none is active."""
    rec = _current.get()
    if rec is not None:
        rec.add(feature, outcome, status=status, applied=applied, ms=ms, model=model)


def attach(metadata: dict) -> None:
    """Hold the active record in ``metadata["decisions"]`` (see ``DecisionRecord.attach``)."""
    rec = _current.get()
    if rec is not None:
        rec.attach(metadata)


def snapshot() -> Optional[dict]:
    """The active record's ``snapshot()``, or ``None``."""
    rec = _current.get()
    return rec.snapshot() if rec is not None else None
