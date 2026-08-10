"""Local heuristic checks: prompt injection and lexical groundedness."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from application.guardrails.base import GuardrailCheck, ScanContext
from application.guardrails.types import CheckOutcome, Span, Stage

# Instruction-override phrasings. Deliberately narrow: these are the shapes that
# appear in real indirect-injection payloads, not every sentence about them.
_INJECTION_PATTERNS = [
    (
        "INSTRUCTION_OVERRIDE",
        re.compile(
            r"(?i)\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}?\b"
            r"(?:previous|prior|earlier|above|preceding|all)\b[^.\n]{0,20}?\b"
            r"(?:instruction|prompt|rule|direction|context|message)s?\b"
        ),
    ),
    (
        "ROLE_HIJACK",
        re.compile(
            r"(?i)\b(?:you are now|from now on,? you|act as if you (?:are|were)|"
            r"pretend (?:to be|you are)|new (?:system )?instructions?:)\b"
        ),
    ),
    (
        "SYSTEM_PROMPT_EXFIL",
        re.compile(
            r"(?i)\b(?:reveal|show|print|repeat|output|disclose)\b[^.\n]{0,30}?\b"
            r"(?:system prompt|initial instructions?|your instructions?|"
            r"prompt above|hidden (?:prompt|instructions?))\b"
        ),
    ),
    (
        "FAKE_TURN",
        re.compile(r"(?i)(?:^|\n)\s*(?:###\s*)?(?:system|assistant)\s*:\s*\S"),
    ),
    (
        "TOOL_COERCION",
        re.compile(
            r"(?i)\b(?:you must|always|immediately)\b[^.\n]{0,30}?\b"
            r"(?:call|invoke|execute|run)\b[^.\n]{0,25}?\b(?:tool|function|command)\b"
        ),
    ),
]


class InjectionCheck(GuardrailCheck):
    name = "injection"
    label = "Prompt injection (heuristic)"
    description = (
        "Pattern-matches instruction-override phrasings in user input and in retrieved "
        "content. Catches unobfuscated payloads only — it is not a defence against a "
        "motivated attacker, who can evade it trivially."
    )
    supported_stages = {Stage.INPUT, Stage.RETRIEVAL, Stage.TOOL_RESULT}
    supports_redaction = False
    latency_hint_ms = 3
    max_match_chars = 512

    @classmethod
    def validate_settings(cls, settings: Dict[str, Any]) -> Dict[str, Any]:
        min_hits = settings.get("min_hits", 1)
        try:
            min_hits = int(min_hits)
        except (TypeError, ValueError):
            raise ValueError("min_hits must be an integer")
        if min_hits < 1 or min_hits > 10:
            raise ValueError("min_hits must be between 1 and 10")
        return {"min_hits": min_hits}

    def scan(self, text: str, stage: Stage, context: ScanContext) -> CheckOutcome:
        spans: List[Span] = []
        categories: List[str] = []
        for label, pattern in _INJECTION_PATTERNS:
            for match in pattern.finditer(text):
                spans.append(Span(match.start(), match.end(), label))
                if label not in categories:
                    categories.append(label)
        min_hits = int(self.settings.get("min_hits", 1))
        if len(spans) < min_hits:
            return CheckOutcome.clean()
        return CheckOutcome.hit(
            categories=categories,
            spans=spans,
            detail=f"{len(spans)} injection-like phrase(s): {', '.join(categories)}",
        )


_WORD = re.compile(r"[A-Za-z0-9']+")
_STOPWORDS: Set[str] = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "for", "from",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that", "the", "then",
    "there", "these", "this", "to", "was", "were", "will", "with", "you", "your",
}


def _shingles(text: str, size: int) -> Set[str]:
    tokens = [t.lower() for t in _WORD.findall(text)]
    content = [t for t in tokens if t not in _STOPWORDS and len(t) > 2]
    if len(content) < size:
        return {" ".join(content)} if content else set()
    return {" ".join(content[i : i + size]) for i in range(len(content) - size + 1)}


class GroundednessCheck(GuardrailCheck):
    name = "groundedness"
    label = "Grounding in sources"
    description = (
        "Flags answers that are not supported by the retrieved sources, measured by "
        "lexical overlap. Lexical overlap is a proxy, not entailment — keep this on "
        "flag unless you have tuned the threshold against real traffic."
    )
    supported_stages = {Stage.OUTPUT}
    supports_redaction = False
    latency_hint_ms = 5
    # Overlap against a half-written answer is meaningless, so this only runs
    # once the answer is complete.
    requires_complete_text = True

    @classmethod
    def validate_settings(cls, settings: Dict[str, Any]) -> Dict[str, Any]:
        try:
            min_overlap = float(settings.get("min_overlap", 0.3))
        except (TypeError, ValueError):
            raise ValueError("min_overlap must be a number")
        if not 0.0 <= min_overlap <= 1.0:
            raise ValueError("min_overlap must be between 0 and 1")
        try:
            min_words = int(settings.get("min_words", 25))
        except (TypeError, ValueError):
            raise ValueError("min_words must be an integer")
        if min_words < 1 or min_words > 1000:
            raise ValueError("min_words must be between 1 and 1000")
        return {
            "min_overlap": min_overlap,
            "min_words": min_words,
            "require_retrieval": bool(settings.get("require_retrieval", True)),
        }

    def scan(self, text: str, stage: Stage, context: ScanContext) -> CheckOutcome:
        docs = context.retrieved_docs or []
        require_retrieval = bool(self.settings.get("require_retrieval", True))
        min_words = int(self.settings.get("min_words", 25))
        min_overlap = float(self.settings.get("min_overlap", 0.3))

        word_count = len(_WORD.findall(text))
        if word_count < min_words:
            return CheckOutcome.clean()

        if not docs:
            if require_retrieval:
                return CheckOutcome.hit(
                    categories=["NO_SOURCES"],
                    score=0.0,
                    detail="answer produced with no retrieved sources",
                )
            return CheckOutcome.clean()

        corpus = "\n".join(str(d.get("text", "")) for d in docs if isinstance(d, dict))
        answer_shingles = _shingles(text, 4)
        if not answer_shingles:
            return CheckOutcome.clean()
        source_shingles = _shingles(corpus, 4)
        if not source_shingles:
            # Sources carried no usable text — cannot judge grounding from here.
            return CheckOutcome.not_evaluated("sources contained no comparable text")
        overlap = len(answer_shingles & source_shingles) / len(answer_shingles)
        if overlap >= min_overlap:
            return CheckOutcome.clean()
        return CheckOutcome.hit(
            categories=["UNGROUNDED"],
            score=round(overlap, 4),
            detail=f"source overlap {overlap:.2f} below threshold {min_overlap:.2f}",
        )
