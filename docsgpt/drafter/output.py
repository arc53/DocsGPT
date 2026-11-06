"""Reading and checking what the drafter's model hands back."""

from __future__ import annotations

import json
from typing import Any, Optional

from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.recipe import ProposalInvalid

#: Most questions one turn asks, and the options each one offers.
MAX_QUESTIONS = 3
MIN_OPTIONS = 2
MAX_OPTIONS = 5
QUESTION_CHARS = 300
NOTE_CHARS = 300
OPTION_CHARS = 150
PLACEHOLDER_CHARS = 100
MESSAGE_CHARS = 1000

#: Most characters of a ``questions`` or ``proposal`` event as the panel sends it back as an assistant message
#: (``JSON.stringify``). The largest a recipe builds is a near-total rewrite of a prompt at its 20000-character
#: cap: the result plus every edit's find and replace (60000 together) and the reasons, at worst doubled by JSON
#: escaping. The runner sends a longer event back to the model, so whatever the server emits comes back whole.
EVENT_CHARS = 160_000

#: Arguments of the ``ask_user`` terminal tool.
QUESTIONS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "One short line shown above the questions, in the user's language.",
        },
        "questions": {
            "type": "array",
            "description": "One to three questions, the ones whose answers change the draft most.",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The question."},
                    "note": {
                        "type": "string",
                        "description": "Optional: one sentence on why you ask (what you noticed in the workspace).",
                    },
                    "multi": {"type": "boolean", "description": "True when several options may be picked."},
                    "options": {
                        "type": "array",
                        "description": "Two to five short answers to click; the user can always type their own. "
                                       "Empty for an answer only the user can type (a company name, a contact).",
                        "items": {"type": "string"},
                    },
                    "placeholder": {
                        "type": "string",
                        "description": "With no options: a short example answer shown in the empty field.",
                    },
                },
                "required": ["text", "options"],
            },
        },
    },
    "required": ["questions"],
}


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


def schema_problems(schema: dict, value: Any) -> list[str]:
    """Where ``value`` breaks ``schema``, one sentence each (empty when it fits).

    Args:
        schema: A JSON schema.
        value: The value to check.

    Returns:
        Up to five problems, addressed to the model.
    """
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema)
    problems = []
    for error in sorted(validator.iter_errors(value), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in error.absolute_path) or "(top level)"
        problems.append(f"{where}: {error.message[:200]}")
        if len(problems) >= 5:
            break
    return problems


def _option_label(option: Any) -> Any:
    """An option sent as an object (``{"text": …}`` or ``{"label": …}``) as its text; anything else as it is."""
    if isinstance(option, dict):
        for key in ("label", "text"):
            if isinstance(option.get(key), str):
                return option[key]
    return option


def _shaped_questions(arguments: dict) -> dict:
    """``ask_user`` arguments with the slips models make in the question shape undone.

    Models mix up the question and option shapes: they send ``{"text": …, "multi": …}``
    as an option, ``null`` for an optional field, or no ``options`` for a typed
    answer. Reading those as meant spares a correction round.
    """
    questions = arguments.get("questions")
    if not isinstance(questions, list):
        return arguments
    shaped = []
    for question in questions:
        if isinstance(question, dict):
            question = {k: v for k, v in question.items() if v is not None}
            options = question.get("options", [])
            if isinstance(options, list):
                question["options"] = [_option_label(o) for o in options]
        shaped.append(question)
    return {**arguments, "questions": shaped}


def normalize_questions(arguments: dict) -> tuple[Optional[str], list[dict]]:
    """Check and shape ``ask_user`` arguments into the ``questions`` event payload.

    Ids are assigned here (``q1``…, options ``a``…); at most three questions
    and five options are kept. A question with no options takes a typed
    answer: it keeps its ``placeholder`` and is never ``multi``.

    Args:
        arguments: The ``ask_user`` arguments.

    Returns:
        ``(message, questions)``.

    Raises:
        ProposalInvalid: No usable question, or a question with exactly one option.
    """
    arguments = _shaped_questions(arguments)
    problems = schema_problems(QUESTIONS_SCHEMA, arguments)
    if problems:
        raise ProposalInvalid(problems)
    message = clean_text(arguments.get("message"), MESSAGE_CHARS) or None
    out: list[dict] = []
    for raw in arguments.get("questions", [])[:MAX_QUESTIONS]:
        text = clean_text(raw.get("text"), QUESTION_CHARS)
        labels: list[str] = []
        for option in raw.get("options", []):
            label = clean_text(option, OPTION_CHARS)
            if label and label.casefold() not in {x.casefold() for x in labels}:
                labels.append(label)
        if not text:
            raise ProposalInvalid(["Every question needs text."])
        if 0 < len(labels) < MIN_OPTIONS:
            raise ProposalInvalid([f"Question {text!r} needs at least two different options, or none for an "
                                   "answer the user types."])
        typed = not labels
        out.append({
            "id": f"q{len(out) + 1}",
            "text": text,
            "note": clean_text(raw.get("note"), NOTE_CHARS) or None,
            "multi": bool(raw.get("multi")) and not typed,
            "options": [{"id": chr(ord("a") + i), "label": label} for i, label in enumerate(labels[:MAX_OPTIONS])],
            "placeholder": (clean_text(raw.get("placeholder"), PLACEHOLDER_CHARS) or None) if typed else None,
        })
    if not out:
        raise ProposalInvalid(["Ask at least one question, or submit the proposal instead."])
    return message, out
