"""How the agent recipe reads the safety step's wording, in English: what the user's own words settle, which safety
part a question asks about, and what a guided step's message claims it set.

Most of it reads common English phrasing only; each function says what it reads.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from docsgpt.agents.questions import MAX_OPTIONS
from docsgpt.analytics.config import TOPIC_NAME_CHARS
from docsgpt.drafter.agent_form import checks_on, SAFETY_FIELDS
from docsgpt.drafter.catalog import Workspace
from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.recipe import DraftRequest, ProposalInvalid

#: How a part of the safety step is named in a correction to the model.
PART_NAMES = {"limits": "limits", "guardrails": "guardrails", "analytics": "topics"}
#: Words that name a guardrail check in the user's own text, besides its id.
_CHECK_WORDS: dict[str, tuple[str, ...]] = {
    "pii": ("pii", "personal data"),
    "injection": ("injection",),
    "groundedness": ("groundedness", "grounded"),
    "secrets": ("secret",),
}


#: Longer runs of digits aren't a limit anyone means; skipping them keeps ``int()`` within Python's digit cap.
_MAX_NUMBER_DIGITS = 18
#: A run of a number's digits and separators, read to its end once: a ``\s*`` after it would split the same
#: spaces every way (quadratic on "1 1 1 …"). Starts only where a run starts and holds a digit.
_NUMBER_RUN = r"(?<![\d,.\s\u00a0\u202f'])(?=[\d,.\s\u00a0\u202f']*?\d)[\d,.\s\u00a0\u202f']*+"


def _numbers(text: str) -> set[int]:
    """The whole numbers a text names, however they are grouped: ``1,000``, ``1.000``, ``1 000``, ``1000``, ``1k``."""
    grouped = re.sub(r"(?<=\d)[,.\s\u00a0\u202f'](?=\d{3}(?!\d))", "", text)
    out = {int(n) for n in re.findall(r"\d+", grouped) if len(n) <= _MAX_NUMBER_DIGITS}
    out |= {int(n) * 1000 for n in re.findall(rf"(?<!\d)(\d{{1,{_MAX_NUMBER_DIGITS}}})\s*k\b", grouped, flags=re.I)}
    return out


def _users_words(req: DraftRequest) -> str:
    """Everything the user wrote in the build: the finished steps' messages and this conversation's."""
    return "\n".join([*req.context.get("earlier", []), req.user_text()])


def stated(key: str, raw: Any, req: DraftRequest) -> bool:
    """Whether the user's own words state a drafted safety part, so it needs no question first.

    A limit's value is a number they wrote; each guardrail check is one they named; each topic a name they wrote.
    Anything else (no limit, a check named another way) is asked about.
    """
    words = _users_words(req)
    lowered = words.casefold()
    if key == "limits":
        value = raw.get("value") if isinstance(raw, dict) else None
        return isinstance(value, int) and not isinstance(value, bool) and value in _numbers(words)
    if key == "guardrails":
        checks = raw.get("checks") if isinstance(raw, dict) else None
        names = [str(check).strip().lower() for check in checks] if isinstance(checks, list) else []
        return bool(names) and all(any(w in lowered for w in _CHECK_WORDS.get(name, (name,))) for name in names)
    topics = raw.get("topics") if isinstance(raw, dict) else None
    names = [clean_text(t.get("name"), TOPIC_NAME_CHARS).casefold() for t in topics if isinstance(t, dict)] \
        if isinstance(topics, list) else []
    return bool(names) and all(name and name in lowered for name in names)


SETTLED_AGAINST = (
    "The user's words already settle the {parts}: set them as they said, without asking, and never offer a "
    "different value."
)
SETTLED_ASKED = (
    "The user's words already settle the {part} ({how}): don't ask about it. Ask only about the parts still open, "
    "or submit the proposal when none is, setting this part as they said."
)
_CHECK_NAMES = r"(?:pii|personal data|injection|groundedness|grounded|secrets?)"
#: How the user's words settle a safety part, in English: declined ("no topics"), or stated (a number, named checks).
_DECLINED = {
    "limits": re.compile(r"\b(?:no|without(?: a| any)?)\s+(?:daily\s+|usage\s+|request\s+|token\s+)?"
                         r"(?:limits?|caps?)\b|\bunlimited\b"),
    "guardrails": re.compile(r"\b(?:no|without(?: any)?)\s+(?:extra\s+|additional\s+|safety\s+)*"
                             r"(?:checks?|guardrails?)\b"),
    "analytics": re.compile(r"\b(?:no|without(?: any)?)\s+(?:insights\s+)?topics?\b"),
}
_STATED = {
    "limits": re.compile(rf"{_NUMBER_RUN}k?\s*(?:requests?|tokens?)\b"),
    # "guardrails … pii" on one line: from the line's first "guardrail" only, so repeats don't each rescan it.
    "guardrails": re.compile(rf"\b{_CHECK_NAMES}\b(?:\s+(?:and|or|,)?\s*\w+){{0,3}}\s+(?:checks?|guardrails?)\b"
                             rf"|^(?>.*?\bguardrails?\b).*\b{_CHECK_NAMES}\b", re.M),
}
#: Topics asked for again after being declined reopen them.
_TOPICS = re.compile(r"\btopics?\b")


def _plain(text: str) -> str:
    """Text folded for the English phrase checks: casefolded, hyphens as spaces."""
    return re.sub(r"[-\u2010\u2011\u2013\u2014]", " ", text).casefold()


def settled_parts(req: DraftRequest) -> dict[str, str]:
    """The safety parts the user's own words settle: ``{part: "declined" | "stated"}``.

    Read in English over the finished steps' messages and this conversation's, in order; a later message that
    settles a part again wins, and one asking about topics after "no topics" opens them again.
    """
    settled: dict[str, str] = {}
    for text in [*req.context.get("earlier", []), *(m["content"] for m in req.messages if m.get("role") == "user")]:
        words = _plain(text)
        for key in SAFETY_FIELDS:
            if _DECLINED[key].search(words):
                settled[key] = "declined"
            elif key in _STATED and _STATED[key].search(words):
                settled[key] = "stated"
            elif key == "analytics" and _TOPICS.search(words):
                settled.pop(key, None)
    return settled


def _question_part(question: dict) -> Optional[str]:
    """The safety part a question asks about (English wording only), or None."""
    words = _plain(" ".join([question["text"], *(o["label"] for o in question["options"])]))
    if _TOPICS.search(words) or re.search(r"\binsights\b", words):
        return "analytics"
    if re.search(rf"guardrail|\bchecks?\b|\b{_CHECK_NAMES}\b", words):
        return "guardrails"
    if re.search(r"\blimits?\b|\bcaps?\b|\brequests?\b|\btokens?\b|\bper day\b", words):
        return "limits"
    return None


#: The decline option added, as a last resort, to a guardrails or topics question that has none.
_NONE_LABELS = {"guardrails": "No extra checks", "analytics": "No topics"}
NONE_MISSING = (
    "The {part} question has no option for none: add a last option meaning \"{label}\", worded in the user's "
    "language, with \"exclusive\": true."
)


def _none_option(question: dict) -> Optional[dict]:
    """A question's decline option: one reading "No…" / "None…" in English, else the one the model marked
    exclusive (its wording in the user's language), else None."""
    options = question["options"]
    return next((o for o in options if re.match(r"\s*(?:no|none)\b", _plain(o["label"]))), None) \
        or next((o for o in options if o.get("exclusive")), None)


def _pick_any(question: dict, part: str) -> None:
    """Make a guardrails or topics question pick-any, its "No extra checks" / "No topics" option exclusive and last.

    A question without one gets the English label (:data:`_NONE_LABELS`), the last regular option giving way when
    the question is full: :func:`check_questions` sends it back for one in the user's words first.
    """
    question["multi"] = True
    options = question["options"]
    none = _none_option(question)
    if none is None:
        del options[MAX_OPTIONS - 1:]
        none = {"id": "", "label": _NONE_LABELS[part], "input": None, "exclusive": True}
        options.append(none)
    for option in options:
        option["exclusive"] = option is none
    options.sort(key=lambda option: option["exclusive"])
    for i, option in enumerate(options):
        option["id"] = chr(ord("a") + i)


def check_questions(questions: list[dict], req: DraftRequest, ws: Workspace) -> list[dict]:
    """The safety step's questions, checked against what the user's words settle and shaped as the step asks.

    A question about a part the user settled goes back once (:data:`SETTLED_ASKED`); with no correction left it is
    dropped, unless it is the only one. The guardrails and topics questions become pick-any with their "No extra
    checks" / "No topics" option exclusive, whatever the model sent; one without that option goes back once for it
    in the user's words (:data:`NONE_MISSING`), and with no correction left gets the English label. Other steps'
    questions pass as they are.

    Raises:
        ProposalInvalid: A question about a settled part, or a guardrails or topics question with no option for none,
            while a correction is left.
    """
    if req.context.get("step") != "safety":
        return questions
    settled = settled_parts(req)
    problems: list[str] = []
    kept: list[dict] = []
    for question in questions:
        part = _question_part(question)
        if part in settled:
            how = "they want none" if settled[part] == "declined" else "they said what they want"
            problems.append(SETTLED_ASKED.format(part=PART_NAMES[part], how=how))
            continue
        if part in ("guardrails", "analytics") and question["options"]:
            if _none_option(question) is None and req.can_correct:
                problems.append(NONE_MISSING.format(part=PART_NAMES[part], label=_NONE_LABELS[part]))
            _pick_any(question, part)
        kept.append(question)
    if problems and req.can_correct:
        raise ProposalInvalid(problems)
    if not kept:
        return questions
    for i, question in enumerate(kept):
        question["id"] = f"q{i + 1}"
    return kept


CLAIMS_UNSET = (
    "Your message says you set {parts}, but fields doesn't set it and the form doesn't have it. Describe only what "
    "fields sets: add it to fields if you meant to set it, or leave it out of the message."
)
#: A sentence that says something was set, as opposed to one that only suggests it.
_CLAIM_VERBS = re.compile(r"\b(?:set|picked|added|attached|chose|chosen|selected|drafted|included|enabled|"
                          r"turned on|switched on)\b", re.I)
_HEDGES = re.compile(r"\b(?:if you|could|would|might|consider|suggest\w*|starting point)\b", re.I)
_COUNT = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|a few|several)"
#: What a sentence names, per field, in English: a request or token budget, a number of topics, sources, tools.
_CLAIM_MENTIONS = {
    "limits": re.compile(rf"{_NUMBER_RUN}k?\s*-?\s*(?:requests?|tokens?)\b", re.I),
    "analytics": re.compile(rf"\b{_COUNT}\s+(?:new\s+|starting\s+|insights\s+)*topics?\b", re.I),
    "sources": re.compile(r"\bsources?\b", re.I),
    "tools": re.compile(r"\btools?\b", re.I),
}
_NONE_OF = re.compile(r"\b(?:no|without|not)\s+(?:\w+\s+){0,2}(?:sources?|tools?)\b", re.I)
#: The fields each step's message is read for, and how a missing one is named back to the model.
_CLAIM_FIELDS = {"safety": ("limits", "guardrails", "analytics"), "knowledge": ("sources", "tools")}
_CLAIM_NAMES = {"limits": "a usage limit", "guardrails": "guardrail checks", "analytics": "Insights topics",
                "sources": "sources", "tools": "tools"}


def unbacked_claims(message: str, step: str, fields: dict, form: dict) -> list[str]:
    """What a guided step's message says it set that neither ``fields`` nor the form holds.

    Read in English only, sentence by sentence: a sentence counts when it says something was set ("I picked",
    "added", "drafted") and doesn't only suggest it ("if you'd like", "a good starting point"). A miss costs
    nothing; a false alarm costs a correction, so the caller asks only while one is left.

    Args:
        message: The proposal's message.
        step: The guided step; only the safety and knowledge steps are read.
        fields: The checked fields.
        form: The form's values.

    Returns:
        The names (:data:`_CLAIM_NAMES`) of the parts claimed but not set, in field order.
    """
    have = {
        "limits": "limits" in fields or form["limits"]["mode"] != "none",
        "analytics": "analytics" in fields or bool(form["analytics"]["topics"]),
        "sources": "sources" in fields or bool(form["sources"]),
        "tools": "tools" in fields or bool(form["tools"]),
    }
    on = checks_on(form["guardrails"])
    claimed: set[str] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", message):
        if not _CLAIM_VERBS.search(sentence) or _HEDGES.search(sentence):
            continue
        words = re.sub(r"[-\u2010\u2011]", " ", sentence).casefold()
        for key in _CLAIM_FIELDS.get(step, ()):
            if key == "guardrails":
                named = {check for check, names in _CHECK_WORDS.items() if any(n in words for n in names)}
                if named and "guardrails" not in fields and not named <= on:
                    claimed.add(key)
            elif not have[key] and _CLAIM_MENTIONS[key].search(sentence) and not _NONE_OF.search(sentence):
                claimed.add(key)
    return [_CLAIM_NAMES[key] for key in _CLAIM_FIELDS.get(step, ()) if key in claimed]
