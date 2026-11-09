"""Reading and checking what the drafter's model hands back."""

from __future__ import annotations

import json
from typing import Any, Optional

from docsgpt.agents.questions import (  # noqa: F401 - re-exported for the drafter's runner
    MAX_OPTIONS,
    MAX_QUESTIONS,
    MESSAGE_CHARS,
    MIN_OPTIONS,
    NOTE_CHARS,
    OPTION_CHARS,
    PLACEHOLDER_CHARS,
    QUESTION_CHARS,
    QuestionsInvalid,
    normalize_questions as _normalize_questions,
    questions_schema,
    schema_problems,
)
from docsgpt.drafter.recipe import ProposalInvalid

#: Most characters of a ``questions`` or ``proposal`` event as the panel sends it back as an assistant message
#: (``JSON.stringify``). The largest a recipe builds is a near-total rewrite of a prompt at its 20000-character
#: cap with edits: every find and replace (40000 together) and their reasons, about 47000 characters, at worst
#: doubled by JSON escaping. An agent proposal adds its other fields to that; a new prompt's text is at most
#: 20000. The runner sends a longer event back to the model, so whatever the server emits comes back whole.
EVENT_CHARS = 120_000

#: Arguments of the ``ask_user`` terminal tool.
QUESTIONS_SCHEMA: dict = questions_schema(
    message="One short line shown above the questions, in the user's language.",
    questions="One to three questions, the ones whose answers change the draft most.",
    note="Optional: one sentence on why you ask (what you noticed in the workspace).",
)


def parse_json_object(raw: Any) -> Optional[dict]:
    """The JSON object in a model's text answer, tolerant of code fences and prose around it.

    The first ``{`` from which a whole object decodes wins. Looking for the
    object itself rather than for a code fence keeps a fence inside a string
    value (a prompt with a code block) from being taken for the answer's own.

    Args:
        raw: The model's text (or a dict already parsed by the provider).

    Returns:
        The object, or None when there is none.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            value = None
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    return None


def echo_length(event: dict) -> int:
    """The characters ``event`` takes once the panel sends it back with ``JSON.stringify``.

    That is the compact JSON with non-ASCII text kept; a lone surrogate, which
    ``JSON.stringify`` writes as a six-character escape, is counted as one.
    """
    body = json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str)
    return len(body) + 5 * sum(1 for ch in body if "\ud800" <= ch <= "\udfff")


def parse_arguments(arguments: Any) -> Optional[dict]:
    """A tool call's arguments as a dict (providers send a JSON string or a dict)."""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        if not arguments.strip():
            return {}
        return parse_json_object(arguments)
    return None


def normalize_questions(arguments: dict) -> tuple[Optional[str], list[dict]]:
    """Check and shape ``ask_user`` arguments into the ``questions`` event payload.

    Ids are assigned here (``q1``…, options ``a``…); at most three questions
    and five options are kept. A question with no options takes a typed
    answer: it keeps its ``placeholder`` and is never ``multi``
    (:func:`docsgpt.agents.questions.normalize_questions`).

    Args:
        arguments: The ``ask_user`` arguments.

    Returns:
        ``(message, questions)``.

    Raises:
        ProposalInvalid: No usable question, or a question with exactly one option.
    """
    try:
        return _normalize_questions(
            arguments, QUESTIONS_SCHEMA, empty_problem="Ask at least one question, or submit the proposal instead."
        )
    except QuestionsInvalid as exc:
        raise ProposalInvalid(exc.problems) from None
