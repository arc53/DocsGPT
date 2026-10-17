"""Arrival order of an answer's parts, persisted so a reload renders the turn as it streamed.

``response``, ``thought`` and ``tool_calls`` stay the source of truth; the segments only
arrange them. Text and thought segments carry a length rather than a copy of the text, in
UTF-16 code units so the browser can slice ``response`` / ``thought`` with ``String.slice``.
"""

from typing import Any, Dict, List, Optional

#: Blank lines between answer text written before a tool call and text written after it.
_PARAGRAPH_BREAK = 2


def separated(previous: str, chunk: str, *, after_tool: bool) -> str:
    """``chunk`` as it should follow ``previous``: as a new paragraph when a tool call came between them.

    Models write "I'll check the page." before a call and "Done: ..." after
    it; concatenated, the stored answer read "page.Done". The web UI splits
    the text by its segments, but the stored answer also reaches the API, the
    model's own history, shares and notifications.

    Args:
        previous: The answer text so far.
        chunk: The next answer chunk.
        after_tool: A tool call was recorded since the last text.

    Returns:
        ``chunk``, led by the newlines that make it a new paragraph when needed.
    """
    if not after_tool or not previous.strip() or not chunk.strip():
        return chunk
    have = (len(previous) - len(previous.rstrip("\n"))) + (len(chunk) - len(chunk.lstrip("\n")))
    return "\n" * max(0, _PARAGRAPH_BREAK - have) + chunk


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
        self._tool_since_text = False
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

    def join(self, previous: str, chunk: Any) -> str:
        """The answer chunk to append after ``previous``: a new paragraph when a tool call came between."""
        return separated(previous, str(chunk), after_tool=self._tool_since_text)

    def answer(self, text: Any) -> None:
        """Record an answer chunk, as ``response_full`` appends it."""
        if str(text).strip():
            self._tool_since_text = False
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
        self._tool_since_text = True
        self._seen_calls.add(call_id)
        self._append({"kind": "tool", "call_id": str(call_id)})

    def reset(self) -> None:
        """Forget the order, when the stream retracts what it emitted (a guardrail trip)."""
        self.items.clear()
        self._seen_calls.clear()
        self._tool_since_text = False


def merge_tool_calls(earlier: List[Dict[str, Any]], latest: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One turn's tool calls across its approval rounds, in the order they were made.

    A turn that pauses for approval resumes in a new stream whose agent
    reports only the calls made after the resume; the message must keep the
    earlier rounds' calls too. A call reported again (the approved call, its
    ``awaiting_approval`` entry superseded by its result) keeps its first
    position and takes its latest state.

    Args:
        earlier: The calls of the rounds before this stream.
        latest: The calls this stream reported.

    Returns:
        The merged list.
    """
    merged: List[Dict[str, Any]] = []
    position: Dict[str, int] = {}
    for call in list(earlier or []) + list(latest or []):
        if not isinstance(call, dict):
            continue
        call_id = call.get("call_id")
        if call_id and call_id in position:
            merged[position[call_id]] = call
            continue
        if call_id:
            position[call_id] = len(merged)
        merged.append(call)
    return merged
