"""The prompt recipe: improve a prompt with reasoned edits, or write a new one from a description.

Improve returns *edits*, not a rewrite: each ``find`` is an exact passage of the
current text that occurs once, each ``replace`` its new text (``''`` deletes;
an insertion anchors on nearby text and repeats it). The server checks them,
applies them to check the text they make (only the edits go out: the client
applies them itself; ``docsgpt/drafter/prompt_edits.py``), and reports what the change does to the
prompt's mode:
a plain-text prompt is a persona DocsGPT wraps with its own sections, any
``{{ }}`` makes it a template used verbatim. Those findings go
out as ``checks`` codes the client words in the user's language; the model's
own ``warnings`` are already in it.

Write returns a name and a plain-text persona, and may first ask what the
description leaves out (the company, the hand-off, the tone); a ``starter``
(one of :data:`STARTERS`, picked from the drawer's first screen) adds a brief
for that kind of prompt, and ``skip_questions`` drafts at once. Improve asks
only for a detail a change needs that only the user knows (a contact), and its
edits may never add a blank or drop the ``{summaries}`` marker. Both return up to three ``suggestions`` (next changes, worded as the
user's request); write also lists the ``assumptions`` the user should check.

Review (``docsgpt/drafter/prompt_review.py``) runs a fixed checklist (``REVIEW_CHECKS``) over a saved or unsaved
prompt and never asks. The model reads the text DocsGPT really wraps around a
persona (``docsgpt/drafter/composer_ref.py``), the agents the caller can see
that use the prompt (names, types, source counts and tool names, never their
content) and the server's model-free checks (``docsgpt/drafter/prompt_checks.py``).
It returns ``findings``, each tied to at most one of its edits; the server
adds a finding for each server check the model left out and lists the checks
that ``passed``.
"""

from __future__ import annotations

import logging
from typing import Any

from docsgpt.drafter.catalog import is_template, Workspace
from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.prompt_checks import prompt_checks
from docsgpt.drafter.prompt_edits import (
    apply_edits,
    ASK_INSTEAD,
    check_drafted_prompt,
    checks_for,
    CONTENT_MAX,
    REASON_MAX,
)
from docsgpt.drafter.prompt_review import (
    PromptWorkspace,
    read_agents,
    review,
    review_instructions,
    REVIEW_CHECKS,
    SEVERITIES,
)
from docsgpt.drafter.prompt_rules import (
    COMPOSER_ADDS,
    CONTACT_DETAILS_ROUND,
    EDIT_RULES,
    hand_off_rule,
    HAND_OFF_OPTIONS,
    no_placeholders,
)
from docsgpt.drafter.recipe import (
    BadDraftRequest,
    clean_id,
    DraftRequest,
    MESSAGE_MAX,
    ProposalInvalid,
    Recipe,
    register,
)

logger = logging.getLogger(__name__)

MODES = ("improve", "write", "review")
#: Modes that work on the prompt's existing text, and those that may ask questions.
_ON_TEXT = ("improve", "review")
_ASKS = ("write", "improve")

NAME_MAX = 100
#: Most characters of prompt text the drafter reads. The prompt routes save any length, so a prompt over
#: ``prompt_edits.CONTENT_MAX`` is read whole (edits must fit the saved text, not a cut copy) and a longer one is
#: refused.
READ_MAX = 100_000
#: Longest prompt text a request may send before it is cleaned: past it the text is refused unread. Cleaning only
#: drops characters, so the slack keeps a text that cleans to :data:`READ_MAX` (``\r\n`` line ends) accepted.
RAW_READ_MAX = 2 * READ_MAX


class PromptTooLong(BadDraftRequest):
    """The prompt to draft with is over the read cap; the refusal's ``reason`` is ``too_long`` with the ``limit``."""

    reason = "too_long"

    def __init__(self, limit: int) -> None:
        super().__init__(f"The prompt is too long to draft with: at most {limit:,} characters")
        self.limit = limit


MAX_WARNINGS = 3
WARNING_MAX = 300
MAX_ASSUMPTIONS = 3
ASSUMPTION_MAX = 200
MAX_SUGGESTIONS = 3
SUGGESTION_MAX = 120

# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


def parse_context(raw: Any) -> dict:
    """Clean the prompt recipe's ``context``: ``{mode, prompt: {id, name, content}, starter?, skip_questions?}``.

    ``starter`` only means something to write mode, ``skip_questions`` to the
    modes that may ask (write, improve); an unknown starter is dropped. The prompt's text is cleaned but never cut.

    Raises:
        BadDraftRequest: An unknown mode, a missing prompt, nothing to improve
            or review, or a text over :data:`READ_MAX` characters.
    """
    raw = raw if isinstance(raw, dict) else {}
    mode = raw.get("mode")
    if mode not in MODES:
        raise BadDraftRequest('context.mode must be "improve", "write" or "review"')
    prompt = raw.get("prompt")
    if not isinstance(prompt, dict):
        raise BadDraftRequest("context.prompt must be an object")
    raw_content = prompt.get("content")
    if isinstance(raw_content, str) and len(raw_content) > RAW_READ_MAX:
        raise PromptTooLong(READ_MAX)
    content = clean_text(raw_content, len(raw_content)) if isinstance(raw_content, str) else ""
    if len(content) > READ_MAX:
        raise PromptTooLong(READ_MAX)
    if mode in _ON_TEXT and not content:
        raise BadDraftRequest(f"There is no prompt text to {mode}")
    writing = mode == "write"
    starter = raw.get("starter")
    return {
        "mode": mode,
        "prompt": {
            "id": clean_id(prompt.get("id")),
            "name": clean_text(prompt.get("name"), NAME_MAX),
            "content": content,
        },
        "starter": starter if writing and isinstance(starter, str) and starter in STARTERS else None,
        "skip_questions": mode in _ASKS and raw.get("skip_questions") is True,
    }


def asks(req: DraftRequest) -> bool:
    """Write asks before drafting and improve for a detail only the user knows, unless the user chose to skip;
    review never asks."""
    return req.context["mode"] in _ASKS and not req.context.get("skip_questions")


def load_workspace(user_id: str, context: dict) -> Workspace:
    """A prompt is drafted on its own text; a review of a saved prompt also reads the agents using it.

    The agents only inform the review, so a failed read is logged and the review runs without them.
    """
    prompt_id = context["prompt"]["id"]
    if context["mode"] != "review":
        return Workspace()
    if not prompt_id:
        return PromptWorkspace()
    from docsgpt.storage.db.session import db_readonly

    try:
        with db_readonly() as conn:
            return PromptWorkspace(agents=read_agents(conn, user_id, prompt_id))
    except Exception:  # noqa: BLE001 - the review stands without them
        logger.warning("drafter: could not read the agents using a prompt", exc_info=True)
        return PromptWorkspace()


def context_data(req: DraftRequest, ws: Workspace) -> dict:
    """The prompt as the model reads it: its name, text and mode, and for a review the server's checks."""
    prompt = req.context["prompt"]
    data: dict[str, Any] = {
        "mode": req.context["mode"],
        "prompt": {
            "name": prompt["name"],
            "content": prompt["content"],
            "kind": "template" if is_template(prompt["content"]) else "persona",
        },
    }
    if req.context["mode"] == "review":
        data["server_checks"] = prompt_checks(prompt["content"])
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
  - {summaries} (single braces): an older marker DocsGPT still supports: DocsGPT fills it with the retrieved \
documents, like {{ source.summaries }}. It is not a placeholder or an invalid variable: keep it where it is.
  A prompt that writes {{ source.content }}, {{ source.summaries }}, {{ source.docs_together }}, \
{{ source.documents }} or {summaries} gets the documents in the prompt instead of with the question."""

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

#: Improve may ask, but only for the details a change needs that only the user knows.
IMPROVE_ASK = """- When the change needs a detail only the user knows (an email address, a link, a phone number, \
opening hours) that neither the prompt nor the user's messages give, don't guess it and don't leave a blank: call \
ask_user once, with a typed question for each missing detail (no options, a placeholder such as \
"e.g. support@northwind.com"). Ask about nothing else, and don't ask when nothing is missing."""

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
- A question you asked that the user's answer leaves out (left blank) is theirs to leave: don't ask it again; write \
around it and list it in assumptions.
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
don't confirm, legal or medical advice, and anything internal. DocsGPT already answers in the visitor's language: \
don't add a line for it.""",
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
        ask = IMPROVE_ASK if asks(req) else None
        return "\n".join(filter(None, [f"{COMMON}\n\n{IMPROVE}", "- " + no_placeholders("your message"), ask,
                                        IMPROVE_NEXT]))
    if req.context["mode"] == "review":
        return f"{COMMON}\n\n{review_instructions(ws)}"
    starter = STARTERS.get(req.context.get("starter") or "")
    return "\n\n".join(filter(None, [COMMON, WRITE, starter]))


# ---------------------------------------------------------------------------
# Proposal
# ---------------------------------------------------------------------------

PROPOSAL_SCHEMA: dict = {
    "type": "object",
    "description": 'For mode "improve" send edits; for mode "review" send findings and their edits; for mode '
                   '"write" send name, content and reason.',
    "properties": {
        "message": {"type": "string", "description": "One or two sentences for the user: what you changed or wrote."},
        "edits": {
            "type": "array",
            "description": "Improve and review: the changes, each one exact passage of the current prompt.",
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
        "findings": {
            "type": "array",
            "description": "Review: the checks that fail, one finding each.",
            "items": {
                "type": "object",
                "properties": {
                    "check": {"type": "string", "enum": list(REVIEW_CHECKS), "description": "The check's code."},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "title": {"type": "string", "description": "What is wrong, in a few words."},
                    "detail": {"type": "string", "description": "One or two sentences: the passage and its effect."},
                    "edit": {"type": "integer", "description": "The fixing edit's position in edits (1 = first)."},
                    "ask": {
                        "type": "object",
                        "description": "A detail only the user knows, when there is no edit.",
                        "properties": {
                            "label": {"type": "string", "description": "A short button label."},
                            "prefill": {"type": "string", "description": "The start of the user's sentence."},
                        },
                        "required": ["label", "prefill"],
                    },
                    "agent": {"type": "string", "description": "The id of the agent it is about."},
                },
                "required": ["check", "severity", "title", "detail"],
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


def validate(args: dict, req: DraftRequest, ws: Workspace) -> dict:
    """Turn ``submit_proposal`` arguments into the prompt ``proposal`` payload for the request's mode.

    Raises:
        ProposalInvalid: A problem the model can fix (edits, name, content, template rules).
    """
    current = req.context["prompt"]["content"]
    message = clean_text(args.get("message"), MESSAGE_MAX)
    if req.context["mode"] == "review":
        return review(args, req, ws, message, _warnings(args))
    if req.context["mode"] == "improve":
        edits, result = apply_edits(current, [e for e in args.get("edits") or [] if isinstance(e, dict)])
        check_drafted_prompt(result, current, req, edited=True, ask_instead=ASK_INSTEAD["improve"])
        return {
            "mode": "improve",
            "message": message,
            "edits": edits,
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
    check_drafted_prompt(content, current, req, edited=False)
    return {
        "mode": "write",
        "message": message,
        "name": name,
        "content": content,
        "reason": clean_text(args.get("reason"), REASON_MAX),
        "warnings": _warnings(args),
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
