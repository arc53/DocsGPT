"""States built from stored message rows, in the shapes the model was trained and evaluated on.

The mapping is the one arc-decide's real-traffic evaluation read DocsGPT's own rows with (``arcd/data/prod.py``):
the stored prompt and response, each source's title (else its ``source``) and stored text. Stored sources are cut
to 1,000 characters on save, which is also the builders' per-source cap, so labelling from rows loses nothing.

A *user message* is any finished row (``complete`` or ``failed``) with a prompt; compression summary rows are not
messages. A *turn* is a complete one with a real answer. History and context pair every earlier user message with
its answer, an empty one where it has none, as in training.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from docsgpt.analytics import schema

# The placeholder a turn whose stream died keeps (``conversation_service``) and the compression summary row's marks
# (``compression/types.py``), kept literal so the worker does not import the answer routes; a test pins them.
TERMINATED_RESPONSE_PLACEHOLDER = "Response was terminated prior to completion, try regenerating."
COMPRESSION_SUMMARY_MARKER = "compression_summary"
COMPRESSION_SUMMARY_PROMPT = "[Context Compression Summary]"

#: Earlier user messages a turn state shows as history.
HISTORY_MESSAGES = 2


@dataclass(frozen=True)
class Message:
    """One stored user message and the answer to it.

    Attributes:
        id: The ``conversation_messages`` id.
        prompt: The user's message.
        response: The stored answer; empty when it has none.
        sources: The stored sources (``title``, ``source``, ``text``, ...).
        status: ``complete`` or ``failed``.
        timestamp: When the message was sent.
        updated_at: When the row last changed.
    """

    id: str
    prompt: str
    response: str
    sources: list = field(default_factory=list)
    status: str = "complete"
    timestamp: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    @property
    def is_turn(self) -> bool:
        """Whether the row holds a finished answer."""
        answer = self.response.strip()
        return self.status == "complete" and bool(answer) and answer != TERMINATED_RESPONSE_PLACEHOLDER

    @property
    def answer(self) -> str:
        """The answer as states read it: empty where the message has no finished answer."""
        return self.response if self.is_turn else ""


def _summary_row(row: dict) -> bool:
    """A compression summary row, as ``compression.types.is_compression_summary_row`` tells it."""
    metadata = row.get("metadata", row.get("message_metadata"))
    if isinstance(metadata, dict) and metadata.get(COMPRESSION_SUMMARY_MARKER) is True:
        return True
    return row.get("prompt") == COMPRESSION_SUMMARY_PROMPT and not row.get("tool_calls") and not metadata


def messages(rows: list[dict]) -> list[Message]:
    """A conversation's user messages, in position order, from its ``conversation_messages`` rows.

    Args:
        rows: The rows as ``ConversationsRepository.get_messages`` returns them.
    """
    out = []
    for row in sorted(rows, key=lambda r: int(r.get("position") or 0)):
        if row.get("status") not in ("complete", "failed") or _summary_row(row):
            continue
        prompt = row.get("prompt") or ""
        if not prompt.strip():
            continue
        sources = row.get("sources") if isinstance(row.get("sources"), list) else []
        out.append(Message(id=str(row["id"]), prompt=prompt, response=row.get("response") or "",
                           sources=[s for s in sources if isinstance(s, dict)], status=row["status"],
                           timestamp=_time(row.get("timestamp")), updated_at=_time(row.get("updated_at"))))
    return out


def _time(value: Any) -> Optional[datetime.datetime]:
    if isinstance(value, str):
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _exchange(m: Message) -> list[dict[str, str]]:
    return [{"role": "user", "text": m.prompt}, {"role": "assistant", "text": m.answer}]


def turn(msgs: list[Message], i: int) -> dict:
    """The turn state of message ``i``: its question, answer and sources, and the two exchanges before it."""
    m = msgs[i]
    history = [x for prev in msgs[max(0, i - HISTORY_MESSAGES):i] for x in _exchange(prev)]
    sources = [{"title": str(s.get("title") or s.get("source") or ""), "text": str(s.get("text") or "")}
               for s in m.sources]
    return schema.turn_state(m.prompt, m.response, sources, history)


def reaction(msgs: list[Message], i: int) -> Optional[dict]:
    """How message ``i`` responds to the answer before it; ``None`` on the first message or after no answer."""
    if i == 0 or not msgs[i - 1].is_turn:
        return None
    prev = msgs[i - 1]
    return schema.reaction_state(prev.prompt, prev.response, msgs[i].prompt)


def message(msgs: list[Message], i: int) -> dict:
    """Message ``i`` with the exchange before it as context (``request_type``)."""
    context = None
    if i:
        prev = msgs[i - 1]
        context = f"User: {prev.prompt}\nAssistant: {prev.answer}"
    return schema.message_state(msgs[i].prompt, context)


def topic(msgs: list[Message], i: int) -> dict:
    """Message ``i`` on its own, without context, as the topic question was trained."""
    return schema.message_state(msgs[i].prompt)


def conversation(msgs: list[Message]) -> dict:
    """The opening request and the last turns (``goal_met`` and tags)."""
    return schema.conversation_state([x for m in msgs for x in _exchange(m)])


def retrieval_relevance(m: Message) -> Optional[float]:
    """The best relevance score over the message's stored sources (set where relevance ran), else ``None``."""
    scores = [float(s["relevance"]) for s in m.sources
              if isinstance(s.get("relevance"), (int, float)) and not isinstance(s.get("relevance"), bool)]
    return max(scores) if scores else None


# Script heuristics from arc-decide's real-traffic evaluation (``arcd/data/prod.py``): three characters of a script,
# else two common Spanish words. Latin text that is not Spanish reads as ``en``: English or another Latin language.
_SCRIPTS = [("zh", re.compile(r"[一-鿿]")), ("ru", re.compile(r"[Ѐ-ӿ]")),
            ("ja", re.compile(r"[぀-ヿ]")), ("ko", re.compile(r"[가-힯]"))]
_ES = re.compile(r"\b(?:el|la|los|las|que|para|cómo|como|por|una|del|qué|está|puedo)\b", re.IGNORECASE)
LANGUAGES = ("en", "es", "zh", "ru", "ja", "ko")


def lang(text: str) -> str:
    """The language a label row records for the user text it read: one of ``LANGUAGES``."""
    for name, pattern in _SCRIPTS:
        if len(pattern.findall(text)) >= 3:
            return name
    return "es" if len(_ES.findall(text)) >= 2 else "en"
