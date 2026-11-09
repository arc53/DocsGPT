"""Clarifying questions a model asks the user: their shape, checked and normalized, and how they read as text.

Shared by the chat's ``ask_user`` tool (:mod:`docsgpt.agents.tools.ask_user`) and the
drafter (:mod:`docsgpt.drafter.output`). Each describes the arguments in its own
words (:func:`questions_schema`); the shape and the limits are the same.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from docsgpt.drafter.fencing import clean_text

#: Most questions one round asks, and the options each one offers.
MAX_QUESTIONS = 3
MIN_OPTIONS = 2
MAX_OPTIONS = 5
QUESTION_CHARS = 300
NOTE_CHARS = 300
OPTION_CHARS = 150
PLACEHOLDER_CHARS = 100
MESSAGE_CHARS = 1000

#: Most characters of a user's answer to one question round that reach the model.
ANSWER_CHARS = 4000


class QuestionsInvalid(ValueError):
    """The model's questions broke a rule it can fix.

    Attributes:
        problems: One sentence per broken rule, addressed to the model.
    """

    def __init__(self, problems: List[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def questions_schema(*, message: str, questions: str, note: str) -> Dict[str, Any]:
    """The JSON schema of the questions' arguments, with the caller's wording where it differs.

    Args:
        message: Description of ``message``, the lead-in line.
        questions: Description of the ``questions`` list.
        note: Description of a question's ``note``.

    Returns:
        A fresh schema dict.
    """
    return {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": message},
            "questions": {
                "type": "array",
                "description": questions,
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The question."},
                        "note": {"type": "string", "description": note},
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


#: Arguments of the chat's ``ask_user`` tool.
CHAT_QUESTIONS_SCHEMA: Dict[str, Any] = questions_schema(
    message="One short line shown above the questions, in the user's language.",
    questions="One to three questions, the ones whose answers change your answer most.",
    note="Optional: one sentence on why you ask.",
)


def schema_problems(schema: Dict[str, Any], value: Any) -> List[str]:
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


def option_label(option: Any) -> Any:
    """An option sent as an object (``{"text": …}`` or ``{"label": …}``) as its text; anything else as it is.

    Args:
        option: One entry of a question's ``options``.

    Returns:
        The label text, or ``option`` unchanged.
    """
    if isinstance(option, dict):
        for key in ("label", "text"):
            if isinstance(option.get(key), str):
                return option[key]
    return option


def shaped_questions(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Question arguments with the slips models make in the question shape undone.

    Models mix up the question and option shapes: they send ``{"text": …, "multi": …}``
    as an option, ``null`` for an optional field, or no ``options`` for a typed
    answer. Reading those as meant spares a correction round.

    Args:
        arguments: The arguments as the model sent them.

    Returns:
        The arguments with each question reshaped (a new dict).
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
                question["options"] = [option_label(o) for o in options]
        shaped.append(question)
    return {**arguments, "questions": shaped}


def normalize_questions(
    arguments: Dict[str, Any],
    schema: Optional[Dict[str, Any]] = None,
    *,
    empty_problem: str = "Ask at least one question, or answer without asking.",
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Check and shape question arguments into the payload a client draws.

    Ids are assigned here (``q1``…, options ``a``…); at most three questions
    and five options are kept. A question with no options takes a typed
    answer: it keeps its ``placeholder`` and is never ``multi``.

    Args:
        arguments: The arguments as the model sent them.
        schema: The schema they are checked against (the chat's by default).
        empty_problem: The problem reported when no usable question is left.

    Returns:
        ``(message, questions)``.

    Raises:
        QuestionsInvalid: No usable question, or a question with exactly one option.
    """
    arguments = shaped_questions(arguments)
    problems = schema_problems(schema or CHAT_QUESTIONS_SCHEMA, arguments)
    if problems:
        raise QuestionsInvalid(problems)
    message = clean_text(arguments.get("message"), MESSAGE_CHARS) or None
    out: List[Dict[str, Any]] = []
    for raw in arguments.get("questions", [])[:MAX_QUESTIONS]:
        text = clean_text(raw.get("text"), QUESTION_CHARS)
        labels: List[str] = []
        for option in raw.get("options", []):
            label = clean_text(option, OPTION_CHARS)
            if label and label.casefold() not in {x.casefold() for x in labels}:
                labels.append(label)
        if not text:
            raise QuestionsInvalid(["Every question needs text."])
        if 0 < len(labels) < MIN_OPTIONS:
            raise QuestionsInvalid([f"Question {text!r} needs at least two different options, or none for an "
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
        raise QuestionsInvalid([empty_problem])
    return message, out


def render_questions_text(message: Optional[str], questions: List[Dict[str, Any]]) -> str:
    """Normalized questions as markdown, for a client that can't draw question cards.

    The model's ``message`` is the lead-in; nothing else is added, since the
    server can't word anything in the user's language. A typed question shows
    no placeholder; a ``note`` is an italic line under its question.

    Args:
        message: The lead-in line, or None.
        questions: What :func:`normalize_questions` returned.

    Returns:
        The text, e.g. ``"Which plan?\\n\\n**1. Team size?**\\na) 1-10\\nb) 11-50"``.
    """
    blocks: List[str] = [message] if message else []
    for number, question in enumerate(questions, start=1):
        lines = [f"**{number}. {question.get('text') or ''}**"]
        if question.get("note"):
            lines.append(f"*{question['note']}*")
        for option in question.get("options") or []:
            lines.append(f"{option.get('id')}) {option.get('label')}")
        # Markdown joins lines into one paragraph unless they end in a hard break.
        blocks.append("  \n".join(lines))
    return "\n\n".join(blocks)
