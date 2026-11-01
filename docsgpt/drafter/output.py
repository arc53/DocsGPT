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
MESSAGE_CHARS = 1000

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
                        "description": "Two to five short answers to click. The user can always type their own.",
                        "items": {"type": "string"},
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
    from docsgpt.agents.workflows.workflow_engine import WorkflowEngine

    candidate = WorkflowEngine._strip_json_fence(text)
    if candidate is None:
        return None
    try:
        value = json.loads(candidate)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


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


def normalize_questions(arguments: dict) -> tuple[Optional[str], list[dict]]:
    """Check and shape ``ask_user`` arguments into the ``questions`` event payload.

    Ids are assigned here (``q1``…, options ``a``…); at most three questions
    and five options are kept.

    Args:
        arguments: The ``ask_user`` arguments.

    Returns:
        ``(message, questions)``.

    Raises:
        ProposalInvalid: No usable question, or a question with fewer than two options.
    """
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
        if len(labels) < MIN_OPTIONS:
            raise ProposalInvalid([f"Question {text!r} needs at least {MIN_OPTIONS} different options."])
        out.append({
            "id": f"q{len(out) + 1}",
            "text": text,
            "note": clean_text(raw.get("note"), NOTE_CHARS) or None,
            "multi": bool(raw.get("multi")),
            "options": [{"id": chr(ord("a") + i), "label": label} for i, label in enumerate(labels[:MAX_OPTIONS])],
        })
    if not out:
        raise ProposalInvalid(["Ask at least one question, or submit the proposal instead."])
    return message, out
