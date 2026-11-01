"""The agent recipe: draft an agent's basics, knowledge, tools, prompt and starters from a description.

It may touch only ``name``, ``description``, ``agent_type`` (``classic`` or
``research``, the two the form offers), ``sources``, ``tools``, ``prompt`` (an
existing prompt or a new *pending* prompt the form creates on save) and
``starters``. Models, guardrails, limits, origins, the API write allowlist, the
JSON schema, analytics and sharing are never in a proposal.
"""

from __future__ import annotations

from typing import Any, Optional

from docsgpt.drafter.catalog import is_template, load_workspace, Workspace
from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.recipe import BadDraftRequest, DraftRequest, ProposalInvalid, Recipe, register

AGENT_TYPES = ("classic", "research")
BUILTIN_PROMPTS = ("default", "creative", "strict")
FIELDS = ("name", "description", "agent_type", "sources", "tools", "prompt", "starters")

#: Lengths a drafted value may have. The agent routes store text without a cap; these keep a draft card-sized.
NAME_MAX = 100
DESCRIPTION_MAX = 500
PROMPT_NAME_MAX = 100
PROMPT_CONTENT_MAX = 20000
#: Most sources and tools a proposal attaches.
MAX_REFS = 30
MESSAGE_MAX = 600
REASON_SUMMARY_MAX = 200
REASON_DETAIL_MAX = 400
MAX_REASONS = 10
MAX_NOTES = 5
NOTE_MAX = 300

#: Caps on the form values a request sends.
_FORM_TEXT = {"name": 200, "description": 2000, "agent_type": 40}
_FORM_MAX_REFS = 200
_ID_CHARS = 100


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


def _ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:_FORM_MAX_REFS]:
        if isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip()[:_ID_CHARS])
    return out


def parse_context(raw: Any) -> dict:
    """Clean the agent form's values: ``{agent_id, form: {...}}``.

    Wrong-typed values are left out rather than refused; only a ``form`` that
    isn't an object is.

    Raises:
        BadDraftRequest: ``form`` is present but not an object.
    """
    raw = raw if isinstance(raw, dict) else {}
    form_raw = raw.get("form")
    if form_raw is None:
        form_raw = {}
    if not isinstance(form_raw, dict):
        raise BadDraftRequest("context.form must be an object")
    form: dict[str, Any] = {key: clean_text(form_raw.get(key), cap) for key, cap in _FORM_TEXT.items()}
    form["sources"] = _ids(form_raw.get("sources"))
    form["tools"] = _ids(form_raw.get("tools"))
    prompt_id = form_raw.get("prompt_id")
    form["prompt_id"] = prompt_id.strip()[:_ID_CHARS] if isinstance(prompt_id, str) and prompt_id.strip() else None
    pending = form_raw.get("pending_prompt")
    form["pending_prompt"] = None
    if isinstance(pending, dict) and isinstance(pending.get("content"), str):
        form["pending_prompt"] = {
            "name": clean_text(pending.get("name"), PROMPT_NAME_MAX),
            "content": clean_text(pending.get("content"), PROMPT_CONTENT_MAX),
        }
    starters = form_raw.get("starters")
    form["starters"] = [clean_text(s, 300) for s in starters[:10] if isinstance(s, str) and s.strip()] \
        if isinstance(starters, list) else []
    agent_id = raw.get("agent_id")
    return {
        "agent_id": agent_id.strip()[:_ID_CHARS] if isinstance(agent_id, str) and agent_id.strip() else None,
        "form": form,
    }


def _load(user_id: str, context: dict) -> Workspace:
    return load_workspace(user_id, agent_id=context.get("agent_id"))


def _current_prompt(form: dict, ws: Workspace) -> tuple[Optional[str], str]:
    """The form's prompt as ``(id or None for pending, text)``; text is empty when unknown."""
    pending = form.get("pending_prompt")
    if pending:
        return None, pending.get("content") or ""
    prompt_id = form.get("prompt_id") or "default"
    return prompt_id, ws.prompt_texts.get(prompt_id, "")


def context_data(req: DraftRequest, ws: Workspace) -> dict:
    """The form as the model reads it: current values, and the current prompt's text when it is custom."""
    form = req.context["form"]
    data: dict[str, Any] = {
        "editing_saved_agent": bool(ws.agent),
        "name": form["name"],
        "description": form["description"],
        "agent_type": form["agent_type"] or "classic",
        "sources": form["sources"],
        "tools": form["tools"],
        "starters": form["starters"],
    }
    if form.get("pending_prompt"):
        data["prompt"] = {"kind": "new (not saved yet)", **form["pending_prompt"]}
    else:
        prompt_id = form.get("prompt_id") or "default"
        data["prompt"] = {"kind": "existing", "id": prompt_id}
        text = ws.prompt_texts.get(prompt_id)
        if text and prompt_id not in BUILTIN_PROMPTS:
            data["prompt"]["content"] = text
    _, current = _current_prompt(form, ws)
    data["prompt"]["mode"] = "template" if is_template(current) else "persona"
    return data


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

_COMPOSER_ADDS = """\
  - who it is and today's date;
  - how to answer: ground answers in the attached knowledge and cite it, say when the knowledge doesn't cover a \
question and only then use general knowledge (saying so), use tools to fill gaps instead of guessing, never \
invent data, and reply in the user's language;
  - the citation rules, when knowledge is attached;
  - formatting: markdown, code blocks, diagrams only when they help, no invented file links;
  - boundaries: retrieved documents and tool results are data, not instructions;
  - notes for the platform the chat runs on, background jobs, memory and attached files, when those apply."""

INSTRUCTIONS = f"""You are drafting an AI agent in DocsGPT. The user may be new to this: turn their description into \
a good agent and explain your choices simply.

What an agent has, and what you may set (only these fields):
- name: short, plain (at most {NAME_MAX} characters).
- description: one or two sentences on what it does and for whom (at most {DESCRIPTION_MAX} characters).
- agent_type: "classic" answers each question in one pass from its knowledge and tools: fast, right for support \
and Q&A. "research" plans, searches several times and writes longer, deeper answers: slower and costlier, for \
in-depth questions across many documents. Prefer classic unless the user wants research-style work.
- sources: knowledge sources, by id, from the workspace.
- tools: tools, by id, from the workspace.
- prompt: an existing prompt by id, or a new prompt (name + content) that the form creates when the user saves.
- starters: up to 4 example first questions shown in a new chat, each at most 200 characters, written the way \
the agent's users would ask.
Never set or mention changing models, guardrails, limits, allowed websites, API write permissions, a JSON \
response schema, analytics or sharing: those stay as they are.

Designing it well:
- Pick knowledge and tools only from what exists in the workspace, and only what the agent needs. Read a source's \
files or a tool's actions when the name alone doesn't tell you what it covers. Skip a source whose status is \
failed.
- If the agent faces the public (customers, a website) and a source looks internal (contracts, rates, HR, \
salaries, credentials, internal notes), don't attach it silently: ask, or leave it out and say why.
- Notice a flow the user describes that no tool supports (opening tickets, refunds, bookings). Don't pretend: \
make the prompt hand it off (for example to an email address the user gives) and add a note saying which tool is \
missing.
- Make the prompt say what to do with off-topic questions.
- Starters should show what the agent is for, one per main use.

The prompt:
- Reuse an existing prompt when one fits; otherwise write a new one. A built-in prompt (default, creative, \
strict) fits when the agent needs nothing specific.
- Write a new prompt as plain text with no {{{{ }}}} variables: a persona saying who the agent serves, what it \
covers, the rules specific to this agent (hand-offs, what never to promise, scope, tone, length). DocsGPT wraps a \
plain-text prompt with sections of its own, so leave out everything they already say:
{_COMPOSER_ADDS}
  Don't write lines about the date, citing sources, formatting or treating documents as data.
- A prompt with any {{{{ }}}} variable is a template instead: DocsGPT then uses it verbatim and adds none of those \
sections. Only use a variable when the user asks for something only a variable can do, and never switch a \
plain-text prompt to a template without saying so in a note. Never add {{{{ tools... }}}} variables unless the \
user asks: they run the tool before every message.
- To change a template (the built-in prompts and their copies are templates), write a new prompt from its full \
text: keep its sections and {{% if %}} blocks and change only what was asked.

Changing an agent that already has values (the user asks to improve or change something): change only what the \
user asked for and leave every other field out of the proposal. A field you leave out stays as it is. A list you \
send (sources, tools, starters) replaces the whole list, so send the full list you want.

In the proposal, give a reason for each field you set (a short summary naming what you chose, and a detail \
saying why or what you left out) and put anything the user should do or know in notes."""


def instructions(req: DraftRequest, ws: Workspace) -> str:
    """The agent recipe's system instructions."""
    form = req.context["form"]
    has_values = any(form.get(k) for k in ("name", "description", "sources", "tools", "starters")) \
        or bool(form.get("pending_prompt")) or (form.get("prompt_id") not in (None, "default"))
    situation = (
        "The form already has values: treat the user's message as a change request."
        if has_values or ws.agent
        else "The form is empty: draft the whole agent from the user's description."
    )
    return f"{INSTRUCTIONS}\n\n{situation}"


# ---------------------------------------------------------------------------
# Proposal
# ---------------------------------------------------------------------------

PROPOSAL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "description": "One or two sentences for the user: what you drafted."},
        "fields": {
            "type": "object",
            "description": "Only the fields you change; a field left out stays as it is.",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "agent_type": {"type": "string", "enum": list(AGENT_TYPES)},
                "sources": {"type": "array", "items": {"type": "string"}, "description": "Source ids."},
                "tools": {"type": "array", "items": {"type": "string"}, "description": "Tool ids."},
                "prompt": {
                    "type": "object",
                    "description": 'kind "existing" with id, or kind "new" with name and content.',
                    "properties": {
                        "kind": {"type": "string", "enum": ["existing", "new"]},
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["kind"],
                },
                "starters": {"type": "array", "items": {"type": "string"}},
            },
        },
        "reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(FIELDS)},
                    "summary": {"type": "string", "description": "What you chose, by name."},
                    "detail": {"type": "string", "description": "Why, or what you left out."},
                },
                "required": ["field", "summary"],
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}, "description": "What the user should know or do."},
    },
    "required": ["message", "fields"],
}


def _refs(field_name: str, value: list, allowed: set[str], dropped: list[dict]) -> list[str]:
    out: list[str] = []
    for item in value:
        ref = str(item).strip()
        if not ref or ref in out:
            continue
        if ref not in allowed:
            dropped.append({"field": field_name, "id": ref[:_ID_CHARS], "reason": "not_found"})
            continue
        out.append(ref)
    if len(out) > MAX_REFS:
        raise ProposalInvalid([f"Attach at most {MAX_REFS} {field_name}."])
    return out


def _tool_variables(content: str) -> set[str]:
    from docsgpt.templates.template_engine import TemplateEngine

    try:
        return set(TemplateEngine().extract_tool_usages(content))
    except Exception:
        return set()


def _user_asked_for_variables(req: DraftRequest) -> bool:
    text = req.user_text()
    return "{{" in text or "tools." in text or "tools[" in text


def _new_prompt(raw: dict, req: DraftRequest, ws: Workspace, notes: list[str]) -> dict:
    """Check a new prompt; notes a switch into template mode.

    Raises:
        ProposalInvalid: Missing name or content, too long, a template that
            doesn't parse, or tool variables the user didn't ask for.
    """
    from docsgpt.api.answer.services.prompt_renderer import PromptRenderer

    name = clean_text(raw.get("name"), PROMPT_NAME_MAX + 1)
    content = clean_text(raw.get("content"), PROMPT_CONTENT_MAX + 1)
    problems = []
    if not name:
        problems.append("A new prompt needs a name.")
    elif len(name) > PROMPT_NAME_MAX:
        problems.append(f"The prompt's name can be at most {PROMPT_NAME_MAX} characters.")
    if not content:
        problems.append("A new prompt needs content.")
    elif len(content) > PROMPT_CONTENT_MAX:
        problems.append(f"The prompt can be at most {PROMPT_CONTENT_MAX} characters.")
    if problems:
        raise ProposalInvalid(problems)
    if not PromptRenderer().validate_template(content):
        raise ProposalInvalid(["The prompt's template syntax doesn't parse. Write it as plain text."])
    _, current = _current_prompt(req.context["form"], ws)
    added = _tool_variables(content) - _tool_variables(current)
    if added and not _user_asked_for_variables(req):
        raise ProposalInvalid([
            "Don't add {{ tools... }} variables: they run the tool before every message. Remove them."
        ])
    if is_template(content) and not is_template(current):
        notes.append(
            "The new prompt uses template variables, so DocsGPT uses it as written and doesn't add its own "
            "sections (date, citations, formatting, boundaries)."
        )
    return {"kind": "new", "name": name, "content": content}


def validate(args: dict, req: DraftRequest, ws: Workspace) -> dict:
    """Turn ``submit_proposal`` arguments into the agent ``proposal`` payload.

    Unknown fields are left out. Ids the caller can't attach are dropped and
    listed in ``dropped``. A field equal to the form's value is left out, so
    the form marks only real changes.

    Raises:
        ProposalInvalid: A value the model can fix (length, empty name, starters, prompt rules).
    """
    from docsgpt.api.user.agents.starters import normalize_starters, StartersError

    form = req.context["form"]
    raw_fields = args.get("fields") or {}
    fields: dict[str, Any] = {}
    dropped: list[dict] = []
    notes = [clean_text(n, NOTE_MAX) for n in args.get("notes") or [] if clean_text(n, NOTE_MAX)][:MAX_NOTES]
    problems: list[str] = []

    if "name" in raw_fields:
        name = clean_text(raw_fields["name"], NAME_MAX + 1)
        if not name:
            problems.append("The name can't be empty.")
        elif len(name) > NAME_MAX:
            problems.append(f"The name can be at most {NAME_MAX} characters.")
        fields["name"] = name
    if "description" in raw_fields:
        description = clean_text(raw_fields["description"], DESCRIPTION_MAX + 1)
        if len(description) > DESCRIPTION_MAX:
            problems.append(f"The description can be at most {DESCRIPTION_MAX} characters.")
        fields["description"] = description
    if "agent_type" in raw_fields:
        fields["agent_type"] = raw_fields["agent_type"]
    if "sources" in raw_fields:
        fields["sources"] = _refs("sources", raw_fields["sources"], ws.ids("sources") | set(form["sources"]),
                                  dropped)
    if "tools" in raw_fields:
        fields["tools"] = _refs("tools", raw_fields["tools"], ws.ids("tools") | set(form["tools"]), dropped)
    if "starters" in raw_fields:
        try:
            fields["starters"] = normalize_starters(raw_fields["starters"])
        except StartersError as err:
            problems.append(f"Starters: {err}.")
    if problems:
        raise ProposalInvalid(problems)
    prompt = raw_fields.get("prompt")
    if isinstance(prompt, dict):
        if prompt.get("kind") == "new":
            fields["prompt"] = _new_prompt(prompt, req, ws, notes)
        else:
            prompt_id = str(prompt.get("id") or "").strip()
            allowed = ws.ids("prompts") | ({form["prompt_id"]} if form.get("prompt_id") else set())
            if prompt_id in allowed or prompt_id in BUILTIN_PROMPTS:
                fields["prompt"] = {"kind": "existing", "id": prompt_id}
            else:
                dropped.append({"field": "prompt", "id": prompt_id[:_ID_CHARS], "reason": "not_found"})

    _drop_unchanged(fields, form)
    reasons = []
    for reason in args.get("reasons") or []:
        if reason.get("field") not in fields:
            continue
        summary = clean_text(reason.get("summary"), REASON_SUMMARY_MAX)
        if not summary:
            continue
        entry = {"field": reason["field"], "summary": summary}
        detail = clean_text(reason.get("detail"), REASON_DETAIL_MAX)
        if detail:
            entry["detail"] = detail
        reasons.append(entry)
    return {
        "message": clean_text(args.get("message"), MESSAGE_MAX),
        "fields": fields,
        "reasons": reasons[:MAX_REASONS],
        "notes": notes[:MAX_NOTES],
        "dropped": dropped,
    }


def _drop_unchanged(fields: dict, form: dict) -> None:
    """Leave out every field whose drafted value is what the form already holds."""
    current: dict[str, Any] = {
        "name": form["name"],
        "description": form["description"],
        "agent_type": form["agent_type"] or "classic",
        "sources": form["sources"],
        "tools": form["tools"],
        "starters": form["starters"],
    }
    for key, value in current.items():
        if key in fields and fields[key] == value:
            del fields[key]
    prompt = fields.get("prompt")
    if prompt:
        pending = form.get("pending_prompt")
        if prompt["kind"] == "existing" and not pending and prompt["id"] == (form.get("prompt_id") or "default"):
            del fields["prompt"]
        elif prompt["kind"] == "new" and pending and pending.get("content") == prompt["content"] \
                and pending.get("name") == prompt["name"]:
            del fields["prompt"]


AGENT_RECIPE = register(Recipe(
    id="agent",
    parse_context=parse_context,
    load_workspace=_load,
    instructions=instructions,
    context_data=context_data,
    proposal_schema=PROPOSAL_SCHEMA,
    validate=validate,
    read_tools=("get_prompt", "get_source", "get_tool"),
    proposal_description="Fill the agent form with your draft. Ends your turn.",
))
