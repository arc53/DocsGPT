"""Clarifying questions a model asks the user: their shape, checked and normalized.

Shared by the chat's ``ask_user`` tool (:mod:`docsgpt.agents.tools.ask_user`) and the
drafter (:mod:`docsgpt.drafter.output`). Each describes the arguments in its own
words (:func:`questions_schema`); the shape and the limits are the same.
"""

from __future__ import annotations

import re
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

#: What a question's ``options`` are, for every model that asks (chat and drafter).
OPTIONS_DESCRIPTION = (
    "Two to five short answers to click: a string, or an object whose input opens a field to type the rest "
    "(never an option that asks the user to type something; give it an input instead) or that is exclusive. "
    'Every question already ends with "Something else…" for a free answer: never add an option like it '
    '("Other", "Type my own"). Never invent contact details (emails, phone numbers, addresses, links) as '
    "options; ask with an input instead. Empty for an answer only the user can type (a company name, a contact)."
)


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
                            "description": OPTIONS_DESCRIPTION,
                            "items": {"anyOf": [
                                {"type": "string"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string", "description": "The option's text."},
                                        "input": {
                                            "type": "string",
                                            "description": "A placeholder: picking the option opens a short field "
                                                           "to type the rest (\"Another city\" with input \"City "
                                                           "name\").",
                                        },
                                        "exclusive": {
                                            "type": "boolean",
                                            "description": "Multi questions only: picking it clears the other "
                                                           "options (\"None of these\"). At most one per question.",
                                        },
                                    },
                                    "required": ["label"],
                                },
                            ]},
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
                question = _typed_where_meant(question, [_shaped_option(o) for o in options])
        shaped.append(question)
    return {**arguments, "questions": shaped}


#: An option that only asks the user to type something ("Input for store name"): the free answer's job.
_INPUT_FOR = re.compile(r"^\s*input\b\s*(?:for\b|:|-)?\s*(.*)$", re.I)


def _typing_hint(option: Any) -> Optional[str]:
    """The placeholder an option that only asks to type carries (``"Input for X"``, or an object with an input
    and no label), "" when it gives none; None for a real option."""
    if isinstance(option, dict) and not isinstance(option_label(option), str):
        return str(option["input"]).strip() if isinstance(option.get("input"), str) else None
    if isinstance(option, str):
        match = _INPUT_FOR.match(option)
        return match.group(1).strip() if match else None
    return None


def _typed_where_meant(question: Dict[str, Any], options: List[Any]) -> Dict[str, Any]:
    """A question with its typing-only options left out, typed when fewer than two real options remain.

    Models ask for a typed answer in ways the shape doesn't take: one option, an ``"Input for …"`` option, or
    an option object with an input and no label. Every question already takes a typed answer ("Something
    else…"), so beside two or more real options those are dropped; otherwise the question is a typed one, its
    placeholder its own or the first typing option's.
    """
    hints = [_typing_hint(option) for option in options]
    real = [option for option, hint in zip(options, hints) if hint is None]
    if len(real) >= MIN_OPTIONS:
        return {**question, "options": real}
    if not options:
        return {**question, "options": []}
    placeholder = question.get("placeholder")
    if not (isinstance(placeholder, str) and placeholder.strip()):
        typed_input = next((option_parts(o)[1] for o in real if isinstance(o, dict) and o.get("input")), None)
        placeholder = next((h for h in hints if h), None) or typed_input
    typed = {**question, "options": []}
    if placeholder:
        typed["placeholder"] = placeholder
    return typed


def _shaped_option(option: Any) -> Any:
    """An option as a plain label, or ``{label, input?, exclusive?}`` when it opens a field or is exclusive.

    An object whose text is under ``text`` rather than ``label`` is read the
    same; keys an option doesn't have (``multi``…) and null values are
    dropped. An object without any text stays as it is, for the schema check
    to refuse.
    """
    label = option_label(option)
    if not isinstance(option, dict) or not isinstance(label, str):
        return label
    extra = {key: option[key] for key in ("input", "exclusive") if option.get(key) not in (None, False, "")}
    return {"label": label, **extra} if extra else label


def option_parts(option: Any) -> Tuple[Any, Optional[str], bool]:
    """``(label, input, exclusive)`` of a shaped option."""
    if isinstance(option, dict):
        return option.get("label"), option.get("input"), bool(option.get("exclusive"))
    return option, None, False


def normalize_questions(
    arguments: Dict[str, Any],
    schema: Optional[Dict[str, Any]] = None,
    *,
    empty_problem: str = "Ask at least one question, or answer without asking.",
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Check and shape question arguments into the payload a client draws.

    Ids are assigned here (``q1``…, options ``a``…); at most three questions
    and five options are kept. A question with no options takes a typed
    answer: it keeps its ``placeholder`` and is never ``multi``. An option is
    ``{id, label, input, exclusive}``: ``input`` is the placeholder of the
    field picking it opens (the client sends ``"<label>: <typed>"``), or None;
    ``exclusive`` (multi questions only, at most one) clears the other options
    when picked and is listed last.

    Args:
        arguments: The arguments as the model sent them.
        schema: The schema they are checked against (the chat's by default).
        empty_problem: The problem reported when no usable question is left.

    Returns:
        ``(message, questions)``.

    Raises:
        QuestionsInvalid: No usable question, a question left with exactly one option once duplicates are
            merged, or two exclusive options.
    """
    arguments = shaped_questions(arguments)
    problems = schema_problems(schema or CHAT_QUESTIONS_SCHEMA, arguments)
    if problems:
        raise QuestionsInvalid(problems)
    message = clean_text(arguments.get("message"), MESSAGE_CHARS) or None
    out: List[Dict[str, Any]] = []
    for raw in arguments.get("questions", [])[:MAX_QUESTIONS]:
        text = clean_text(raw.get("text"), QUESTION_CHARS)
        options: List[Tuple[str, Optional[str], bool]] = []
        for option in raw.get("options", []):
            label, typed_input, exclusive = option_parts(option)
            label = clean_text(label, OPTION_CHARS)
            if label and label.casefold() not in {x[0].casefold() for x in options}:
                options.append((label, clean_text(typed_input, PLACEHOLDER_CHARS) or None, exclusive))
        if not text:
            raise QuestionsInvalid(["Every question needs text."])
        if 0 < len(options) < MIN_OPTIONS:
            raise QuestionsInvalid([f"Question {text!r} needs at least two different options, or none for an "
                                    "answer the user types."])
        typed = not options
        multi = bool(raw.get("multi")) and not typed
        options = options[:MAX_OPTIONS]
        if multi and sum(1 for option in options if option[2]) > 1:
            raise QuestionsInvalid([f"Question {text!r}: at most one option can be exclusive."])
        # An exclusive option only means something where several can be picked; it is listed last.
        options = [(label, typed_input, multi and exclusive) for label, typed_input, exclusive in options]
        options.sort(key=lambda option: option[2])
        out.append({
            "id": f"q{len(out) + 1}",
            "text": text,
            "note": clean_text(raw.get("note"), NOTE_CHARS) or None,
            "multi": multi,
            "options": [{"id": chr(ord("a") + i), "label": label, "input": typed_input, "exclusive": exclusive}
                        for i, (label, typed_input, exclusive) in enumerate(options)],
            "placeholder": (clean_text(raw.get("placeholder"), PLACEHOLDER_CHARS) or None) if typed else None,
        })
    if not out:
        raise QuestionsInvalid([empty_problem])
    return message, out
