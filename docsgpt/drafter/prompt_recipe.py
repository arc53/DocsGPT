"""The prompt recipe: improve a prompt with reasoned edits, or write a new one from a description.

Improve returns *edits*, not a rewrite: each ``find`` is an exact passage of the
current text that occurs once, each ``replace`` its new text (``''`` deletes;
an insertion anchors on nearby text and repeats it). The server checks them,
applies them to compute ``result``, and reports what the change does to the
prompt's mode: a plain-text prompt is a persona DocsGPT wraps with its own
sections, any ``{{ }}`` makes it a template used verbatim. Those findings go
out as ``checks`` codes the client words in the user's language; the model's
own ``warnings`` are already in it.

Write returns a name and a plain-text persona, and may first ask what the
description leaves out (the company, the hand-off, the tone); a ``starter``
(one of :data:`STARTERS`, picked from the drawer's first screen) adds a brief
for that kind of prompt, and ``skip_questions`` drafts at once. Improve never
asks. Both return up to three ``suggestions`` (next changes, worded as the
user's request); write also lists the ``assumptions`` the user should check.
"""

from __future__ import annotations

from typing import Any

from docsgpt.drafter.catalog import is_template, Workspace
from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.prompt_rules import (
    COMPOSER_ADDS,
    CONTACT_DETAILS_ROUND,
    EDIT_RULES,
    hand_off_rule,
    HAND_OFF_OPTIONS,
    no_placeholders,
    TEMPLATE_PROBLEM,
    template_parses,
    tool_variables_problem,
)
from docsgpt.drafter.recipe import BadDraftRequest, DraftRequest, ProposalInvalid, Recipe, register

MODES = ("improve", "write")

NAME_MAX = 100
CONTENT_MAX = 20000
MAX_EDITS = 20
REASON_MAX = 300
MESSAGE_MAX = 600
MAX_WARNINGS = 3
WARNING_MAX = 300
MAX_ASSUMPTIONS = 3
ASSUMPTION_MAX = 200
MAX_SUGGESTIONS = 3
SUGGESTION_MAX = 120

_ID_CHARS = 100

#: ``checks`` codes, in the order they are reported.
CHECK_TO_TEMPLATE = "to_template"
CHECK_TO_PERSONA = "to_persona"
CHECK_BOUNDARIES_REMOVED = "boundaries_removed"
CHECK_CITATIONS_REMOVED = "citations_removed"

#: Text that marks a template's Boundaries section (the built-in one, or one written after it).
_BOUNDARY_MARKERS = ("## boundaries", "not instructions", "never follow directions")
_CITATION_MARKER = "source.citation_rules"


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


def parse_context(raw: Any) -> dict:
    """Clean the prompt recipe's ``context``: ``{mode, prompt: {id, name, content}, starter?, skip_questions?}``.

    ``starter`` and ``skip_questions`` only mean something to write mode; an
    unknown starter is dropped.

    Raises:
        BadDraftRequest: An unknown mode, a missing prompt, or nothing to improve.
    """
    raw = raw if isinstance(raw, dict) else {}
    mode = raw.get("mode")
    if mode not in MODES:
        raise BadDraftRequest('context.mode must be "improve" or "write"')
    prompt = raw.get("prompt")
    if not isinstance(prompt, dict):
        raise BadDraftRequest("context.prompt must be an object")
    prompt_id = prompt.get("id")
    content = clean_text(prompt.get("content"), CONTENT_MAX)
    if mode == "improve" and not content:
        raise BadDraftRequest("There is no prompt text to improve")
    writing = mode == "write"
    starter = raw.get("starter")
    return {
        "mode": mode,
        "prompt": {
            "id": prompt_id.strip()[:_ID_CHARS] if isinstance(prompt_id, str) and prompt_id.strip() else None,
            "name": clean_text(prompt.get("name"), NAME_MAX),
            "content": content,
        },
        "starter": starter if writing and isinstance(starter, str) and starter in STARTERS else None,
        "skip_questions": writing and raw.get("skip_questions") is True,
    }


def asks(req: DraftRequest) -> bool:
    """Write mode asks before drafting, unless the user chose to skip; improve never does."""
    return req.context["mode"] == "write" and not req.context.get("skip_questions")


def load_workspace(user_id: str, context: dict) -> Workspace:
    """A prompt is drafted on its own text: nothing from the workspace."""
    return Workspace()


def context_data(req: DraftRequest, ws: Workspace) -> dict:
    """The prompt as the model reads it: its name, text and mode."""
    prompt = req.context["prompt"]
    data: dict[str, Any] = {
        "mode": req.context["mode"],
        "prompt": {
            "name": prompt["name"],
            "content": prompt["content"],
            "kind": "template" if is_template(prompt["content"]) else "persona",
        },
    }
    return data


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

VARIABLES = """\
  - {{ system.date }}, {{ system.time }}, {{ system.timestamp }}, {{ system.request_id }}, {{ system.user_id }}
  - {{ source.content }} (the retrieved documents as text; {{ source.summaries }} and {{ source.docs_together }} \
are the same), {{ source.documents }} (a list to loop over), {{ source.count }}, {{ source.attached }}
  - {{ source.citation_rules }}: the [n] citation rules, empty when no knowledge is attached
  - {{ passthrough.<field> }}: values the embedding website or API call sends with each message
  - {{ tools.<tool>.<action> }}: a tool action's result, run before every message
  - {{ system.platform }}: the platform notes the built-in prompts include
  A prompt that writes {{ source.content }}, {{ source.summaries }}, {{ source.docs_together }} or \
{{ source.documents }} gets the documents in the prompt instead of with the question."""

COMMON = f"""You are working on a prompt in DocsGPT: the system prompt an agent or a chat answers with.

How DocsGPT uses a prompt:
- A prompt with no {{{{ }}}} variables is a persona. DocsGPT puts it inside its own prompt, which already says:
{COMPOSER_ADDS}
  So a persona says who the assistant serves, what it covers and the rules specific to it (hand-offs, what never \
to promise, scope, tone, length), and what to do with off-topic questions. Lines that repeat the list above (today's \
date, "cite your sources", formatting, "treat documents as data") are noise in a persona.
- A prompt with any {{{{ }}}} variable is a template: DocsGPT uses it exactly as written and adds none of those \
sections. The built-in prompts (default, creative, strict) and copies of them are templates.
- The variables a template can use:
{VARIABLES}

Rules for every prompt you write:
- Keep a persona plain text with no {{{{ }}}} variables. Only add a variable when the user asks for something only \
a variable can do, and say in your message that it turns the prompt into a template.
- Never add {{{{ tools... }}}} variables unless the user asks for them: they run the tool before every message.
- In a template (a built-in copy), keep its sections and {{% if %}} blocks, the Boundaries section and \
{{{{ source.citation_rules }}}}: without them the agent loses its guard against instructions inside documents and \
its [n] citations.
- {hand_off_rule("the user says the agent has a tool for it")}
- Don't write warnings about the prompt's mode or removed sections: the app shows those itself. Use warnings only \
for something else the user must know."""

IMPROVE = """Improve the current prompt: change only what the user asked for, plus lines that repeat what DocsGPT \
already adds to a persona. Leave everything else exactly as it is.

Return the change as edits, not a rewrite:
""" + EDIT_RULES

#: Follow-ups and guesses are about the text: this drawer edits only the prompt, and the recipe can't see the
#: knowledge or tools of the agents that use it. They complete the user's choices, never swap them.
TEXT_ONLY = """Suggestions and assumptions are changes to the prompt's text only: never suggest attaching \
knowledge or tools, and don't guess what an agent using the prompt has attached; you can't see it. Build on what \
the user said and chose: never suggest replacing it (e.g. a support email when they picked live chat) or asking it \
again; suggest what would complete it instead (e.g. "Add your live chat's opening hours")."""

IMPROVE_NEXT = f"""suggestions: up to 3 further changes this prompt could use, each worded as the short request the \
user would send (e.g. "Add what to do when it doesn't know"). Leave out what you just changed. {TEXT_ONLY}"""

WRITE = """Write a new prompt from the user's description: a short name (at most 100 characters) and the prompt \
text as a plain-text persona, plus one sentence on why it is written that way (reason). If the prompt has text \
already, treat it as the user's starting point.

A good persona knows: who it serves and for which company or product; what it covers and what is off-limits; \
where it sends people when it can't help (""" + HAND_OFF_OPTIONS + """); and its tone.
- When you may ask (ask_user is offered), ask first about what the description and the brief below leave out, in \
one round of at most 3 questions, most important first: usually the company or product, where it sends people it \
can't help and the tone (a brief below may name others). The company or product is a typed answer: a question \
with no options and a placeholder such as "e.g. Northwind Travel". Offer options for the rest; where it sends \
people is a pick-any question. Don't ask about off-limits topics: use the usual ones (the brief below names them) \
and list them in assumptions. Don't ask what the user already said, and don't ask at all when the description \
covers it.
- """ + CONTACT_DETAILS_ROUND + """
- """ + no_placeholders("assumptions") + """
- assumptions: up to 3 short sentences, each a guess the user should check (e.g. "Hand-offs go to your support \
team; you didn't name a contact.").
- suggestions: up to 3 next changes this prompt could use, each worded as the short request the user would send \
(e.g. "Add your opening hours").
""" + TEXT_ONLY

#: Briefs for the drawer's starting points, by ``starter`` id.
STARTERS: dict[str, str] = {
    "website": """The user picked "Website chat for customers": a chat on the company's public website. Its \
users are visitors and customers who may know nothing about the company. Find out the company or product, where \
it sends people it can't help, and the tone. Usually off-limits: prices, discounts or delivery dates the documents \
don't confirm, legal or medical advice, and anything internal. It answers in the visitor's language.""",
    "helpdesk": """The user picked "Internal helpdesk": answers the company's own staff on HR, IT and policy \
questions. Find out the company, which areas it covers (HR, IT, policies, office and facilities), and who staff \
contact when it can't help (a team, an email, a ticket portal). Personal cases (pay, health, disputes, \
complaints) go to a person; it never guesses a policy the documents don't state.""",
    "research": """The user picked "Research assistant": digs through the user's documents and answers from them. \
Find out what the documents are (contracts, reports, papers, case files), who uses it, and how answers should \
look (a short answer first, then detail; quotes; tables). It says plainly when the documents are silent, and \
points out where documents disagree rather than picking one.""",
}


def instructions(req: DraftRequest, ws: Workspace) -> str:
    """The prompt recipe's system instructions for the request's mode (and the write starter's brief)."""
    if req.context["mode"] == "improve":
        return f"{COMMON}\n\n{IMPROVE}\n{IMPROVE_NEXT}"
    starter = STARTERS.get(req.context.get("starter") or "")
    return "\n\n".join(filter(None, [COMMON, WRITE, starter]))


# ---------------------------------------------------------------------------
# Proposal
# ---------------------------------------------------------------------------

PROPOSAL_SCHEMA: dict = {
    "type": "object",
    "description": 'For mode "improve" send edits; for mode "write" send name, content and reason.',
    "properties": {
        "message": {"type": "string", "description": "One or two sentences for the user: what you changed or wrote."},
        "edits": {
            "type": "array",
            "description": "Improve: the changes, each one exact passage of the current prompt.",
            "items": {
                "type": "object",
                "properties": {
                    "find": {"type": "string", "description": "Exact text of the current prompt; occurs once."},
                    "replace": {"type": "string", "description": "Its new text; '' deletes it."},
                    "reason": {"type": "string", "description": "Why, in one short sentence."},
                },
                "required": ["find", "replace", "reason"],
            },
        },
        "name": {"type": "string", "description": "Write: the prompt's name."},
        "content": {"type": "string", "description": "Write: the prompt text."},
        "reason": {"type": "string", "description": "Write: why it is written this way."},
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Anything else the user must know (not the prompt's mode).",
        },
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Write: up to 3 guesses the user should check.",
        },
        "suggestions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Up to 3 next changes, each worded as the user's short request.",
        },
    },
    "required": ["message"],
}


def _has_boundaries(text: str) -> bool:
    """Whether a prompt's text holds the Boundaries section, or the lines it adds about treating data as data."""
    lowered = text.lower()
    return any(marker in lowered for marker in _BOUNDARY_MARKERS)


def checks_for(before: str, after: str) -> list[str]:
    """What a change does to a prompt that the user should know, as ``checks`` codes.

    Args:
        before: The prompt's text before the change ('' for a new prompt).
        after: Its text after.

    Returns:
        Codes, in a fixed order: a switch into or out of template mode, and
        the Boundaries or citation rules taken out of a template.
    """
    was, now = is_template(before), is_template(after)
    out: list[str] = []
    if now and not was:
        out.append(CHECK_TO_TEMPLATE)
    if was and not now:
        out.append(CHECK_TO_PERSONA)
    if now and _has_boundaries(before) and not _has_boundaries(after):
        out.append(CHECK_BOUNDARIES_REMOVED)
    if now and _CITATION_MARKER in before and _CITATION_MARKER not in after:
        out.append(CHECK_CITATIONS_REMOVED)
    return out


def _texts(args: dict, key: str, chars: int, most: int) -> list[str]:
    """A list of short texts from the proposal: cleaned, blanks and repeats (any case) dropped, capped."""
    out: list[str] = []
    for raw in args.get(key) or []:
        text = clean_text(raw, chars)
        if text and text.casefold() not in {x.casefold() for x in out}:
            out.append(text)
    return out[:most]


def _warnings(args: dict) -> list[str]:
    """The proposal's warnings, cleaned and capped (:func:`_texts`)."""
    return _texts(args, "warnings", WARNING_MAX, MAX_WARNINGS)


def _suggestions(args: dict) -> list[str]:
    """The proposal's follow-up suggestions, cleaned and capped (:func:`_texts`)."""
    return _texts(args, "suggestions", SUGGESTION_MAX, MAX_SUGGESTIONS)


def _occurrences(content: str, find: str) -> list[int]:
    """Start offsets of ``find`` in ``content``, overlapping matches included (stops at two)."""
    starts: list[int] = []
    index = content.find(find)
    while index != -1 and len(starts) < 2:
        starts.append(index)
        index = content.find(find, index + 1)
    return starts


def _clean_replacement(text: str) -> str:
    """An edit's ``replace`` cleaned as :func:`clean_text` cleans text, keeping the spaces and line breaks around
    it, which place the change in the prompt."""
    core = text.strip()
    if not core:
        return "".join(ch for ch in text if ch in " \t\n")
    start = text.index(core[0])
    lead = "".join(ch for ch in text[:start] if ch in " \t\n")
    trail = "".join(ch for ch in text[start + len(core):] if ch in " \t\n")
    return lead + clean_text(core, len(core)) + trail


def apply_edits(content: str, edits: list[dict]) -> tuple[list[dict], str]:
    """Check edits against ``content`` and apply them.

    Args:
        content: The current prompt.
        edits: ``{find, replace, reason}`` dicts from the model.

    Returns:
        ``(edits, result)``: the edits that change something, in text order
        with ids ``e1``…, and the text with all of them applied.

    Raises:
        ProposalInvalid: Too many edits, a find that doesn't occur exactly
            once, a missing reason, overlapping edits, an empty result, or a
            result over :data:`CONTENT_MAX` that is longer than ``content``.
    """
    if len(edits) > MAX_EDITS:
        raise ProposalInvalid([f"Send at most {MAX_EDITS} edits; merge nearby changes."])
    problems: list[str] = []
    spans: list[tuple[int, int, dict]] = []
    for number, edit in enumerate(edits, start=1):
        find = str(edit.get("find") or "").replace("\r\n", "\n")
        replace = _clean_replacement(str(edit.get("replace") or "").replace("\r\n", "\n"))
        if find == replace:
            continue
        label = f"Edit {number} ({find[:60]!r})"
        if not find:
            problems.append(f"Edit {number}: find can't be empty; anchor an insertion on nearby text.")
            continue
        starts = _occurrences(content, find)
        if not starts:
            problems.append(f"{label}: find was not found in the current prompt; copy it exactly.")
            continue
        if len(starts) > 1:
            count = content.count(find)
            problems.append(f"{label}: find occurs {max(count, 2)} times; quote a longer passage that occurs once.")
            continue
        reason = clean_text(edit.get("reason"), REASON_MAX)
        if not reason:
            problems.append(f"{label}: give a reason.")
            continue
        spans.append((starts[0], starts[0] + len(find), {"find": find, "replace": replace, "reason": reason}))
    spans.sort(key=lambda span: span[0])
    for (_, prev_end, prev), (start, _, edit) in zip(spans, spans[1:]):
        if start < prev_end:
            problems.append(
                f"The edits for {prev['find'][:40]!r} and {edit['find'][:40]!r} overlap; merge them into one edit."
            )
    if problems:
        raise ProposalInvalid(problems)
    parts: list[str] = []
    cursor = 0
    out: list[dict] = []
    for index, (start, end, edit) in enumerate(spans, start=1):
        parts.append(content[cursor:start])
        parts.append(edit["replace"])
        cursor = end
        out.append({"id": f"e{index}", **edit})
    parts.append(content[cursor:])
    result = "".join(parts)
    if not result.strip():
        raise ProposalInvalid(["The edits would leave the prompt empty."])
    if len(result) > CONTENT_MAX and len(result) > len(content):
        # A prompt saved longer than the cap (the prompt routes store any length) may still shrink or stay as long.
        if len(content) > CONTENT_MAX:
            raise ProposalInvalid([f"The prompt is already over {CONTENT_MAX} characters: edits can't make it longer."])
        raise ProposalInvalid([f"The prompt can be at most {CONTENT_MAX} characters."])
    return out, result


def _check_text(result: str, previous: str, req: DraftRequest) -> None:
    """Template syntax and tool-variable rules for a drafted prompt text.

    A prompt whose text didn't parse before the change (a template with a stray
    ``{%``) isn't blamed on the change.

    Raises:
        ProposalInvalid: The text doesn't parse, or adds tool variables the user didn't ask for.
    """
    if not template_parses(result) and (not previous or template_parses(previous)):
        raise ProposalInvalid([TEMPLATE_PROBLEM])
    problem = tool_variables_problem(result, previous, req)
    if problem:
        raise ProposalInvalid([problem])


def validate(args: dict, req: DraftRequest, ws: Workspace) -> dict:
    """Turn ``submit_proposal`` arguments into the prompt ``proposal`` payload for the request's mode.

    Raises:
        ProposalInvalid: A problem the model can fix (edits, name, content, template rules).
    """
    current = req.context["prompt"]["content"]
    message = clean_text(args.get("message"), MESSAGE_MAX)
    if req.context["mode"] == "improve":
        edits, result = apply_edits(current, [e for e in args.get("edits") or [] if isinstance(e, dict)])
        _check_text(result, current, req)
        return {
            "mode": "improve",
            "message": message,
            "edits": edits,
            "result": result,
            "template_mode": {"before": is_template(current), "after": is_template(result)},
            "warnings": _warnings(args),
            "checks": checks_for(current, result),
            "suggestions": _suggestions(args),
        }
    name = clean_text(args.get("name"), NAME_MAX + 1)
    content = clean_text(args.get("content"), CONTENT_MAX + 1)
    problems = []
    if not name:
        problems.append("Give the prompt a name.")
    elif len(name) > NAME_MAX:
        problems.append(f"The prompt's name can be at most {NAME_MAX} characters.")
    if not content:
        problems.append("Write the prompt text in content.")
    elif len(content) > CONTENT_MAX:
        problems.append(f"The prompt can be at most {CONTENT_MAX} characters.")
    if problems:
        raise ProposalInvalid(problems)
    _check_text(content, current, req)
    return {
        "mode": "write",
        "message": message,
        "name": name,
        "content": content,
        "reason": clean_text(args.get("reason"), REASON_MAX),
        "warnings": _warnings(args),
        "template_mode": {"before": is_template(current), "after": is_template(content)},
        "checks": checks_for(current, content),
        "assumptions": _texts(args, "assumptions", ASSUMPTION_MAX, MAX_ASSUMPTIONS),
        "suggestions": _suggestions(args),
    }


PROMPT_RECIPE = register(Recipe(
    id="prompt",
    parse_context=parse_context,
    load_workspace=load_workspace,
    instructions=instructions,
    context_data=context_data,
    proposal_schema=PROPOSAL_SCHEMA,
    validate=validate,
    proposal_description="Hand the improved or new prompt to the prompt editor. Ends your turn.",
    questions=asks,
    reads_workspace=False,
))
