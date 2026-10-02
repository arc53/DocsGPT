"""Arrival order of an answer's parts, persisted so a reload renders the turn as it streamed.

``response``, ``thought`` and ``tool_calls`` stay the source of truth; the segments only
arrange them. Text and thought segments carry a length rather than a copy of the text, in
UTF-16 code units so the browser can slice ``response`` / ``thought`` with ``String.slice``.
"""

from typing import Any, Dict, List, Optional


def utf16_length(text: str) -> int:
    """Return the length of ``text`` as JavaScript counts it.

    Args:
        text: Any string.

    Returns:
        The number of UTF-16 code units (an astral character counts twice, a lone
        surrogate once).
    """
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


class AnswerSegments:
    """Records text, thought and tool-call events in the order they were emitted.

    The list it builds is held by reference in the stream's ``query_metadata`` under
    ``segments`` (from the first recorded part on), so every persistence path (finalize,
    abort, error, pause) stores the order as it stands at that moment.
    """

    def __init__(self, metadata: Dict[str, Any]) -> None:
        """Attach the recorder to a turn's metadata.

        Args:
            metadata: The stream's ``query_metadata``; ``segments`` is set on it.
        """
        self._metadata = metadata
        self._seen_calls: set = set()
        self.items: List[Dict[str, Any]] = []

    def _append(self, item: Dict[str, Any]) -> None:
        # The key appears with the first segment, so a turn that streamed nothing
        # leaves the stored metadata exactly as it was.
        self._metadata["segments"] = self.items
        self.items.append(item)

    def _grow(self, kind: str, text: str) -> None:
        length = utf16_length(text)
        if not length:
            return
        last = self.items[-1] if self.items else None
        if last is not None and last["kind"] == kind:
            last["length"] += length
        else:
            self._append({"kind": kind, "length": length})

    def answer(self, text: Any) -> None:
        """Record an answer chunk, as ``response_full`` appends it."""
        self._grow("text", str(text))

    def thought(self, text: Any) -> None:
        """Record a reasoning chunk, as ``thought`` appends it."""
        self._grow("thought", str(text))

    def tool_call(self, data: Optional[Dict[str, Any]]) -> None:
        """Record a tool call's position; each call is emitted again on completion.

        Args:
            data: The ``tool_call`` event's ``data``; its first sighting fixes the position.
        """
        call_id = (data or {}).get("call_id")
        if not call_id or call_id in self._seen_calls:
            return
        self._seen_calls.add(call_id)
        self._append({"kind": "tool", "call_id": str(call_id)})

    def reset(self) -> None:
        """Forget the order, when the stream retracts what it emitted (a guardrail trip)."""
        self.items.clear()
        self._seen_calls.clear()
