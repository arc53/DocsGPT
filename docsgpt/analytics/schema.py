"""The analytics label schema: every question the model answers about a conversation, and the state it reads.

Ported from arc-decide's ``arcd/analytics/schema.py`` (MIT), the file its data builders, trainer and evals share.
The model reads question text, option order and state key names, so a paraphrase, a reordered ``criteria`` dict or
a renamed key is an untrained input: change nothing here without a new model. The fixed questions are the harness's
trained copies (``docsgpt.decisions.Q``); ``tests/analytics/test_schema_port.py`` checks every question, builder and
the hash against a fixture exported from arc-decide. ``SCHEMA_HASH`` goes on every stored label, so labels made
under different wording are never mixed.

Four levels, each with a short state, so no label needs a whole long conversation in one window:

- ``turn``         an assistant answer: the question, up to two prior turns, the retrieved sources, the answer
- ``reaction``     how the user's next message responds to that answer
- ``message``      a user message on its own (request type, topic)
- ``conversation`` the opening request and the last turns

The ``tool`` labels are kept so the hash matches the model's schema; DocsGPT does not ask them yet. States render
with sorted keys and are cut from the end at the model's state budget, so the builders order content by key name
on purpose (long, least important text sorts last) and cap each field.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

from docsgpt.decisions.questions import Q

SCHEMA_VERSION = 1
NONE_OPTION = "none of these"

# Per-field caps in Latin-character units; together they keep a state inside a 2,048-token budget. Measured on the
# model's tokenizer, English runs ~4.4 characters a token and Chinese prose ~1.4, so a CJK character counts 3 units
# and a Cyrillic one 1.2: a Chinese answer capped by characters would push the question out of the state.
CAPS = {"answer": 2500, "question": 800, "reply": 800, "history_turn": 600, "sources": 3000, "source_each": 1000,
        "message": 1200, "context": 600, "opening": 800, "transcript": 4000, "result": 2000, "arguments": 600,
        "next_step": 800, "request": 800, "previous_result": 800}


@dataclass(frozen=True)
class Label:
    """One analytics label.

    Attributes:
        name: The question key (the key the model's temperature uses) or the derived label's name.
        level: ``turn``, ``reaction``, ``message``, ``conversation`` or ``tool``.
        question: The question, or ``None`` for labels computed from other labels.
        note: How a label without a question is computed.
    """

    name: str
    level: str
    question: Optional[dict[str, Any]]
    note: str = ""


ANSWER_STATUS = Q.ANSWER_STATUS
UNANSWERED_REASON = Q.UNANSWERED_REASON
REACTION = Q.REACTION
FRUSTRATED = Q.FRUSTRATED
ASKS_HUMAN = Q.ASKS_HUMAN
SENTIMENT = Q.SENTIMENT
# not "intent": that key is the choice family's (CLINC, MASSIVE), and a shared key shares one temperature
INTENT = Q.REQUEST_TYPE
TOPIC_INSTRUCTIONS = "Which section of the documentation is this message about?"
GOAL_MET = Q.GOAL_MET
TAG_GROUP_INSTRUCTIONS = "Which of these tags best fits this conversation?"

LABELS: tuple[Label, ...] = (
    Label("answer_status", "turn", ANSWER_STATUS),
    Label("unanswered_reason", "turn", UNANSWERED_REASON, "asked only when answer_status is not 'fully answered'"),
    Label("grounded", "turn", None, "the grounding family's `supported`, per answer sentence against the sources"),
    Label("retrieval_relevance", "turn", None, "max p(relevant) over the retrieved chunks"),
    Label("answerable_from_corpus", "turn", None, "max p(relevant) over a wider re-retrieval at analysis time"),
    Label("gap_type", "turn", None, "derive.gap_type"),
    Label("reaction", "reaction", REACTION),
    Label("frustrated", "reaction", FRUSTRATED),
    Label("asks_human", "reaction", ASKS_HUMAN),
    Label("sentiment", "reaction", SENTIMENT),
    Label("request_type", "message", INTENT),
    Label("topic", "message", None, "topic_question(options): the source's own sections, plus none of these"),
    Label("goal_met", "conversation", GOAL_MET),
    Label("resolution", "conversation", None, "derive.resolution"),
    Label("experience", "conversation", None, "derive.experience"),
    Label("tool_needed", "tool", Q.TOOL_NEEDED),
    Label("right_tool", "tool", Q.RIGHT_TOOL),
    Label("tool_succeeded", "tool", Q.TOOL_SUCCEEDED),
    Label("result_used", "tool", Q.RESULT_USED),
    Label("induced_by_untrusted", "tool", Q.INDUCED_BY_UNTRUSTED),
    Label("loop", "tool", None, "derive.is_loop"),
)
BY_NAME = {lab.name: lab for lab in LABELS}


def _choice(instructions: str, options: dict[str, Optional[str]]) -> dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": dict(options)}


def _noul(instructions: str) -> dict[str, Any]:
    return {"type": "noul", "instructions": instructions}


def questions(level: str) -> dict[str, dict[str, Any]]:
    """Every fixed model question at one level, keyed by label name (the key the model's temperature uses)."""
    return {lab.name: lab.question for lab in LABELS if lab.level == level and lab.question is not None}


def topic_question(options: dict[str, Optional[str]]) -> dict[str, Any]:
    """A choice over documentation sections (name to optional description, e.g. its page titles), with the
    reserved 'none of these' last: its share of traffic is what feeds cluster discovery."""
    opts = {k: v for k, v in options.items() if k != NONE_OPTION}
    opts[NONE_OPTION] = "The message is not about any of these sections."
    return _choice(TOPIC_INSTRUCTIONS, opts)


def tag_question(name: str, description: str) -> dict[str, Any]:
    """A custom tag, asked in one practised form: new tags are new content in that form, not new tasks."""
    return _noul("Does the following tag apply to this conversation?\n\n"
                 f"Tag: {name.strip()}\nDescription: {description.strip()}")


# ---- states -------------------------------------------------------------------------------------------------------

def _weight(ch: str) -> float:
    o = ord(ch)
    if 0x2E80 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF:
        return 3.0
    if 0x0400 <= o <= 0x04FF:
        return 1.2
    return 1.0


def units(text: str) -> float:
    """The length of ``text`` in Latin-character units: a CJK character counts 3, a Cyrillic one 1.2."""
    return sum(_weight(c) for c in text)


def cap(text: Any, n: int) -> str:
    """``text`` stripped and cut to ``n`` units, ending in "…" when it was cut."""
    s = "" if text is None else str(text).strip()
    used = 0.0
    for i, ch in enumerate(s):
        used += _weight(ch)
        if used > n - 1:
            return s[:i].rstrip() + "…"
    return s


def _turns_text(turns: list[dict[str, str]], each: int) -> str:
    return "\n".join(f"{t['role'].capitalize()}: {cap(t['text'], each)}" for t in turns)


def turn_state(question: str, answer: str, sources: Optional[list[dict[str, str]]] = None,
               history: Optional[list[dict[str, str]]] = None) -> dict[str, Any]:
    """An assistant turn. Keys sort answer, history, question, sources: the sources are long and cut first."""
    state: dict[str, Any] = {"answer": cap(answer, CAPS["answer"]), "question": cap(question, CAPS["question"])}
    if history:
        state["history"] = _turns_text(history[-4:], CAPS["history_turn"])
    if sources:
        budget, out = CAPS["sources"], []
        for s in sources:
            text = cap(s.get("text"), min(CAPS["source_each"], budget))
            if not text:
                break
            out.append({"title": cap(s.get("title"), 120), "text": text})
            budget -= units(text)
            if budget <= 0:
                break
        state["sources"] = out
    return state


def reaction_state(question: str, answer: str, reply: str) -> dict[str, str]:
    """The user's next message after an answer. Keys sort answer, question, reply."""
    return {"answer": cap(answer, CAPS["answer"]), "question": cap(question, CAPS["question"]),
            "reply": cap(reply, CAPS["reply"])}


def message_state(message: str, context: Optional[str] = None) -> dict[str, str]:
    """A user message, with the previous exchange as optional context. Keys sort context, message."""
    state = {"message": cap(message, CAPS["message"])}
    if context:
        state["context"] = cap(context, CAPS["context"])
    return state


def conversation_state(turns: list[dict[str, str]]) -> dict[str, str]:
    """The opening request and the last turns. Keys sort opening, transcript."""
    first_user = next((t["text"] for t in turns if t["role"] == "user"), "")
    recent = turns[-8:]
    text = _turns_text(recent, CAPS["transcript"] // max(1, len(recent)))
    if len(turns) > len(recent):
        text = f"[{len(turns) - len(recent)} earlier messages omitted]\n{text}"
    return {"opening": cap(first_user, CAPS["opening"]), "transcript": cap(text, CAPS["transcript"])}


def _hash() -> str:
    body = {"version": SCHEMA_VERSION, "none": NONE_OPTION, "caps": CAPS, "topic": TOPIC_INSTRUCTIONS,
            "tag": tag_question("{name}", "{description}"), "tag_group": TAG_GROUP_INSTRUCTIONS,
            "labels": [[lab.name, lab.level, lab.question] for lab in LABELS]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


SCHEMA_HASH = _hash()
