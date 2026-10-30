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

#: What ``str.strip`` strips: every character ``str.isspace`` holds (Unicode White_Space, and U+001C..U+001F). The
#: candidate queries test blank text against this set too, as Postgres's ``[[:space:]]`` follows the database's
#: locale (U+00A0 is a space on one, not on another; U+001C..U+001F on none), and a message SQL counts while the
#: states leave it out is a candidate no state is ever built for. A test pins it to ``str.isspace``.
WHITESPACE = ("\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007"
              "\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000")


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
        source_hash: The hash of what states read of the row, when it was loaded with one
            (``ConversationLabelsRepository.source_messages``).
    """

    id: str
    prompt: str
    response: str
    sources: list = field(default_factory=list)
    status: str = "complete"
    timestamp: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None
    source_hash: Optional[str] = None

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
    calls = row["has_tool_calls"] if "has_tool_calls" in row else row.get("tool_calls")
    return row.get("prompt") == COMPRESSION_SUMMARY_PROMPT and not calls and not metadata


def messages(rows: list[dict]) -> list[Message]:
    """A conversation's user messages, in position order, from its ``conversation_messages`` rows.

    Args:
        rows: The rows as ``ConversationsRepository.get_messages`` returns them, or as
            ``ConversationLabelsRepository.source_messages`` loads them (``has_tool_calls`` for ``tool_calls``).
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
                           timestamp=_time(row.get("timestamp")), updated_at=_time(row.get("updated_at")),
                           source_hash=row.get("source_hash")))
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
# kana before kanji so Japanese is not read as Chinese. Latin text votes on common words: Spanish was trained, the
# other Latin languages were not, so they are told apart from English for the language note rather than read as it.
_SCRIPTS = [("ja", re.compile(r"[぀-ヿ]")), ("ko", re.compile(r"[가-힯]")),
            ("ru", re.compile(r"[Ѐ-ӿ]")), ("zh", re.compile(r"[一-鿿]"))]
_WORDS = {
    "en": {"the", "is", "are", "how", "what", "do", "does", "can", "i", "to", "of", "and", "my", "it", "for", "in",
           "on", "where", "why", "with", "you", "this", "that", "or", "when", "which"},
    "es": {"el", "la", "los", "las", "que", "para", "cómo", "como", "por", "una", "del", "qué", "está", "puedo", "es",
           "con", "mi", "se", "y"},
    "fr": {"le", "les", "des", "est", "une", "comment", "pour", "je", "de", "du", "que", "pas", "avec", "mon", "sur",
           "ce", "et", "mot", "passe"},
    "de": {"der", "die", "das", "ist", "wie", "ich", "nicht", "und", "mit", "kann", "ein", "eine", "für", "auf", "zu",
           "mein", "den", "dem"},
    "pt": {"o", "os", "as", "é", "não", "como", "faço", "para", "com", "um", "uma", "do", "da", "meu", "minha", "eu",
           "você", "que"},
    "it": {"il", "lo", "gli", "è", "come", "posso", "per", "non", "un", "una", "che", "di", "mi", "con", "sono",
           "della", "la"},
}
_WORD = re.compile(r"\w+")
LANGUAGES = ("en", "es", "zh", "ru", "ja", "ko", "fr", "de", "pt", "it")


def lang(text: str) -> str:
    """The language a label row records for the user text it read: one of ``LANGUAGES``.

    Latin text is English unless another language's common words outnumber English ones, at least two of them.
    """
    for name, pattern in _SCRIPTS:
        if len(pattern.findall(text)) >= 3:
            return name
    words = [w.lower() for w in _WORD.findall(text)]
    hits = {name: sum(w in vocab for w in words) for name, vocab in _WORDS.items()}
    best = max((name for name in _WORDS if name != "en"), key=lambda name: hits[name])
    return best if hits[best] >= 2 and hits[best] > hits["en"] else "en"
