"""The agent recipe: draft an agent step by step, or improve a saved one, from what the user writes.

A new agent is built in four steps (:data:`STEPS`): ``basics`` (name,
description), ``knowledge`` (sources, tools, ``agent_type``: ``classic`` or
``research``, the two the form offers), ``prompt`` (an existing prompt, or a
new one the user reviews in the prompt editor, and starters) and ``safety``
(request or token limits, guardrail checks from :data:`GUARDRAIL_MENU`, and
starting Insights topics). A step sets its own fields and, when the user's
words call for them, later steps' fields except safety's; a new prompt is
written only in the prompt step, and safety is asked about before anything
is set. A ``starter`` (one of :data:`STARTERS`, picked from the drawer's first screen) adds
a brief for that kind of agent to every step. Improve mode (no step, a saved
agent) touches the first three steps' fields only. Models, origins, the API write allowlist, the JSON schema and
sharing are never in a proposal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import ValidationError

from docsgpt.analytics.config import AnalyticsTopic, TOPIC_DESCRIPTION_UNITS, TOPIC_NAME_CHARS
from docsgpt.core.settings import settings
from docsgpt.drafter.catalog import is_template, load_workspace, Workspace
from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.prompt_rules import (
    COMPOSER_ADDS,
    CONTACT_DETAILS_ROUND,
    hand_off_rule,
    HAND_OFF_OPTIONS,
    no_placeholders,
    TEMPLATE_PROBLEM,
    template_parses,
    tool_variables_problem,
)
from docsgpt.drafter.recipe import BadDraftRequest, DraftRequest, ProposalInvalid, Recipe, register
from docsgpt.drafter.runner import question_rounds
from docsgpt.drafter.topics_recipe import TopicsWorkspace

AGENT_TYPES = ("classic", "research")
BUILTIN_PROMPTS = ("default", "creative", "strict")

#: The guided build's steps, in order, and the fields each one sets.
STEPS = ("basics", "knowledge", "prompt", "safety")
STEP_FIELDS: dict[str, tuple[str, ...]] = {
    "basics": ("name", "description"),
    "knowledge": ("sources", "tools", "agent_type"),
    "prompt": ("prompt", "starters"),
    "safety": ("limits", "guardrails", "analytics"),
}
SAFETY_FIELDS = STEP_FIELDS["safety"]
FIELDS = tuple(name for step in STEPS for name in STEP_FIELDS[step])

#: The guardrail checks the safety step offers, each as the ``(stage, action)`` controls it adds.
GUARDRAIL_MENU: dict[str, tuple[tuple[str, str], ...]] = {
    "pii": (("input", "redact"), ("output", "redact")),
    "injection": (("input", "block"),),
    "groundedness": (("output", "flag"),),
    "secrets": (("output", "redact"),),
}
LIMIT_MODES = ("requests", "tokens", "none")
GUARDRAIL_MODES = ("monitor_only", "scan_all")

#: Lengths a drafted value may have. The agent routes store text without a cap; these keep a draft card-sized.
NAME_MAX = 100
DESCRIPTION_MAX = 500
PROMPT_NAME_MAX = 100
PROMPT_CONTENT_MAX = 20000
#: Most sources and tools a proposal attaches.
MAX_REFS = 30
#: Largest request or token limit a proposal sets.
LIMIT_MAX = 1_000_000_000
#: Most Insights topics one proposal adds.
MAX_NEW_TOPICS = 4
MESSAGE_MAX = 600
REASON_SUMMARY_MAX = 200
REASON_DETAIL_MAX = 400
MAX_REASONS = 10
MAX_NOTES = 3
NOTE_MAX = 300

#: Caps on the form values a request sends.
_FORM_TEXT = {"name": 200, "description": 2000, "agent_type": 40}
_FORM_MAX_REFS = 200
_FORM_MAX_NAMES = 100
_ID_CHARS = 100
#: Most of the user's messages from finished steps a request sends, and characters of one.
MAX_EARLIER = 12
EARLIER_CHARS = 2000
#: The id a drafted topic is checked under (the form gives it its own).
_CHECK_TOPIC_ID = "drafttopic"

ASK_FIRST = (
    "Ask the user first: call ask_user with a question for each part of this step you can set (limits, "
    "guardrails, topics), the recommended option first, then set only what they pick."
)


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass
class AgentWorkspace(Workspace):
    """The caller's workspace plus what the safety step may set on this instance.

    Attributes:
        guardrail_menu: The :data:`GUARDRAIL_MENU` checks this instance can add (empty while guardrails are off).
        insights: Whether Insights labels conversations here (``DECISION_ANALYTICS_ENABLED`` with the decision
            model available, as ``/api/config`` reports it).
        max_topics: ``ANALYTICS_MAX_TOPICS``, the most one-per-question topics an agent has, folders included.
        folders: The source folders of the form's sources ``{name, description}``, largest first (safety step
            only): each is already an option of the agent's topic question.
    """

    guardrail_menu: list[str] = field(default_factory=list)
    insights: bool = False
    max_topics: int = 15
    folders: list[dict] = field(default_factory=list)


def _ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:_FORM_MAX_REFS]:
        if isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip()[:_ID_CHARS])
    return out


def _names(value: Any, limit: int, *, lower: bool = False) -> list[str]:
    """Distinct non-empty strings of a list, cleaned and capped (lowercased when ``lower``)."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:_FORM_MAX_NAMES]:
        name = clean_text(item, limit)
        name = name.lower() if lower else name
        if name and name not in out:
            out.append(name)
    return out


def _parse_policy(form_raw: dict) -> dict:
    """The form's limits, guardrails and Insights values, with defaults for what is missing or wrong."""
    limits = form_raw.get("limits") if isinstance(form_raw.get("limits"), dict) else {}
    mode = limits.get("mode") if limits.get("mode") in LIMIT_MODES else "none"
    value = limits.get("value")
    if mode == "none" or isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        value = None
    guardrails = form_raw.get("guardrails") if isinstance(form_raw.get("guardrails"), dict) else {}
    analytics = form_raw.get("analytics") if isinstance(form_raw.get("analytics"), dict) else {}
    topics = analytics.get("topics") if isinstance(analytics.get("topics"), list) else []
    overlapping = [t.get("name") for t in topics if isinstance(t, dict) and t.get("overlap") is True]
    names = [t.get("name") if isinstance(t, dict) else t for t in topics]
    return {
        "limits": {"mode": mode, "value": value},
        "guardrails": {
            "enabled": guardrails.get("enabled") is True,
            "mode": guardrails.get("mode") if guardrails.get("mode") in GUARDRAIL_MODES else "monitor_only",
            "checks": _names(guardrails.get("checks"), 40, lower=True),
        },
        # Collecting insights is on by default for an agent.
        "analytics": {
            "enabled": analytics.get("enabled") is not False,
            "topics": _names(names, TOPIC_NAME_CHARS),
            "overlapping": _names(overlapping, TOPIC_NAME_CHARS),
            "hidden_folders": _names(analytics.get("hidden_folders"), TOPIC_NAME_CHARS),
        },
    }


def parse_context(raw: Any) -> dict:
    """Clean the agent form's values: ``{agent_id, step, starter?, earlier, form: {...}}``.

    Wrong-typed values are left out rather than refused; only a ``form`` that
    isn't an object, or an unknown ``step``, is.

    Raises:
        BadDraftRequest: ``form`` is present but not an object, or ``step`` is not one of :data:`STEPS` or null.
    """
    raw = raw if isinstance(raw, dict) else {}
    form_raw = raw.get("form")
    if form_raw is None:
        form_raw = {}
    if not isinstance(form_raw, dict):
        raise BadDraftRequest("context.form must be an object")
    step = raw.get("step")
    if step is not None and step not in STEPS:
        raise BadDraftRequest(f"context.step must be one of {', '.join(STEPS)}, or null")
    form: dict[str, Any] = {key: clean_text(form_raw.get(key), cap) for key, cap in _FORM_TEXT.items()}
    form["sources"] = _ids(form_raw.get("sources"))
    form["tools"] = _ids(form_raw.get("tools"))
    prompt_id = form_raw.get("prompt_id")
    form["prompt_id"] = prompt_id.strip()[:_ID_CHARS] if isinstance(prompt_id, str) and prompt_id.strip() else None
    draft = form_raw.get("prompt_draft")
    form["prompt_draft"] = None
    if isinstance(draft, dict) and isinstance(draft.get("content"), str):
        form["prompt_draft"] = {
            "name": clean_text(draft.get("name"), PROMPT_NAME_MAX),
            "content": clean_text(draft.get("content"), PROMPT_CONTENT_MAX),
        }
    starters = form_raw.get("starters")
    form["starters"] = [clean_text(s, 300) for s in starters[:10] if isinstance(s, str) and s.strip()] \
        if isinstance(starters, list) else []
    form.update(_parse_policy(form_raw))
    earlier = raw.get("earlier") if isinstance(raw.get("earlier"), list) else []
    agent_id = raw.get("agent_id")
    starter = raw.get("starter")
    return {
        "agent_id": agent_id.strip()[:_ID_CHARS] if isinstance(agent_id, str) and agent_id.strip() else None,
        "step": step,
        "starter": starter if starter in STARTERS else None,
        "earlier": [text for text in (clean_text(t, EARLIER_CHARS) for t in earlier) if text][:MAX_EARLIER],
        "form": form,
    }


def guardrail_menu() -> list[str]:
    """The :data:`GUARDRAIL_MENU` checks this instance can add: guardrails on, every control of the check valid.

    A check that isn't registered, isn't allowed by ``GUARDRAILS_CHECKS_ENABLED`` or can't run without settings
    of its own fails the same validation a save applies, and is left out.
    """
    from docsgpt.guardrails.config import GuardrailControl

    if not settings.GUARDRAILS_ENABLED:
        return []
    out = []
    for check, controls in GUARDRAIL_MENU.items():
        try:
            for stage, action in controls:
                GuardrailControl.model_validate({"check": check, "stage": stage, "action": action})
        except ValueError:
            continue
        out.append(check)
    return out


def insights_available() -> bool:
    """Whether Insights labels conversations on this instance (``decision_analytics_enabled`` in ``/api/config``)."""
    from docsgpt import decisions

    try:
        return bool(settings.DECISION_ANALYTICS_ENABLED) and bool(decisions.available())
    except Exception:
        return False


def source_folders(source_ids: list[str]) -> list[dict]:
    """The folders of these sources, as the agent's topic question offers them (``topics.folders``)."""
    from docsgpt.analytics import topics as analytics_topics
    from docsgpt.storage.db.repositories.sources import SourcesRepository
    from docsgpt.storage.db.session import db_readonly

    if not source_ids:
        return []
    with db_readonly() as conn:
        rows = SourcesRepository(conn).list_by_ids(source_ids)
    return analytics_topics.folders(rows)


def _load(user_id: str, context: dict) -> AgentWorkspace:
    ws = load_workspace(user_id, agent_id=context.get("agent_id"))
    out = AgentWorkspace(
        **vars(ws),
        guardrail_menu=guardrail_menu(),
        insights=insights_available(),
        max_topics=int(settings.ANALYTICS_MAX_TOPICS),
    )
    if context.get("step") == "safety" and out.insights:
        attachable = ws.ids("sources")
        out.folders = source_folders([s for s in (context.get("form") or {}).get("sources", []) if s in attachable])
    return out


def _current_prompt(form: dict, ws: Workspace) -> tuple[Optional[str], str]:
    """The form's prompt as ``(id or None for unsaved text, text)``; text is empty when unknown."""
    draft = form.get("prompt_draft")
    if draft:
        return None, draft.get("content") or ""
    prompt_id = form.get("prompt_id") or "default"
    return prompt_id, ws.prompt_texts.get(prompt_id, "")


def _topic_view(form: dict, ws: AgentWorkspace) -> TopicsWorkspace:
    """The form's topics and the sources' folders, for the topics recipe's room rules."""
    analytics = form["analytics"]
    overlapping = {name.lower() for name in analytics["overlapping"]}
    own = [{"name": name, "overlap": name.lower() in overlapping} for name in analytics["topics"]]
    return TopicsWorkspace(own=own, folders=ws.folders, hidden_folders=analytics["hidden_folders"],
                           max_topics=ws.max_topics)


def _topic_room(form: dict, ws: AgentWorkspace) -> dict[str, int]:
    """One-per-question topics that push no folder out (``free``), and the most that fit at all (``max``)."""
    room = _topic_view(form, ws).capacity()
    return {"free": room["one_per_question_free"], "max": room["one_per_question_max"]}


def _safety_options(form: dict, ws: AgentWorkspace) -> dict:
    """What the safety step may set for this caller on this instance, for the model."""
    no_access = {"available": False, "why": "no_access"}
    defaults = settings.DEFAULT_AGENT_LIMITS
    limits = {
        "available": True,
        "recommended": {"requests": defaults["request_limit"], "tokens": defaults["token_limit"]},
    } if ws.policy_editable else no_access
    if not ws.policy_editable:
        guardrails = no_access
    elif not ws.guardrail_menu:
        guardrails = {"available": False, "why": "off_on_this_instance"}
    else:
        guardrails = {"available": True, "checks": [
            {"id": check, "controls": [{"stage": stage, "action": action} for stage, action in GUARDRAIL_MENU[check]]}
            for check in ws.guardrail_menu
        ]}
    room = _topic_room(form, ws)
    if not ws.insights:
        topics = {"available": False, "why": "off_on_this_instance"}
    elif not form["analytics"]["enabled"]:
        topics = {"available": False, "why": "turned_off_for_this_agent"}
    elif not room["max"]:
        topics = {"available": False, "why": "no_room"}
    else:
        topics = {"available": True, "room": room["free"]}
        if room["max"] > room["free"]:
            topics["room_pushing_folders_out"] = room["max"] - room["free"]
        offered = [folder["name"] for folder in _topic_view(form, ws).offered_folders()]
        if offered:
            topics["source_folders"] = offered
    return {"limits": limits, "guardrails": guardrails, "insights_topics": topics}


def context_data(req: DraftRequest, ws: Workspace) -> dict:
    """The form as the model reads it: the step, current values, and the current prompt's text when it is custom."""
    form = req.context["form"]
    step = req.context["step"]
    data: dict[str, Any] = {"editing_saved_agent": bool(ws.agent)}
    if step:
        data["step"] = step
    if req.context["earlier"]:
        data["users_earlier_messages"] = req.context["earlier"]
    data.update({
        "name": form["name"],
        "description": form["description"],
        "agent_type": form["agent_type"] or "classic",
        "sources": form["sources"],
        "tools": form["tools"],
        "starters": form["starters"],
    })
    if form.get("prompt_draft"):
        data["prompt"] = {"kind": "new (open in the prompt editor, not saved yet)", **form["prompt_draft"]}
    else:
        prompt_id = form.get("prompt_id") or "default"
        data["prompt"] = {"kind": "existing", "id": prompt_id}
        text = ws.prompt_texts.get(prompt_id)
        if text and prompt_id not in BUILTIN_PROMPTS:
            data["prompt"]["content"] = text
    _, current = _current_prompt(form, ws)
    data["prompt"]["mode"] = "template" if is_template(current) else "persona"
    if step == "safety":
        data.update({key: form[key] for key in SAFETY_FIELDS})
        data["analytics"] = {key: form["analytics"][key] for key in ("enabled", "topics")}
        data["safety_options"] = _safety_options(form, ws)
    return data


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

AGENT_FIELDS = f"""You are drafting an AI agent in DocsGPT. The user may be new to this: turn their description into \
a good agent and explain your choices simply.

What an agent has, and what you may set (only these fields):
- name: short, plain (at most {NAME_MAX} characters).
- description: one or two sentences on what it does and for whom (at most {DESCRIPTION_MAX} characters).
- agent_type: "classic" answers each question in one pass from its knowledge and tools: fast, right for support \
and Q&A. "research" plans, searches several times and writes longer, deeper answers: slower and costlier, for \
in-depth questions across many documents. Prefer classic unless the user wants research-style work.
- sources: knowledge sources, by id, from the workspace.
- tools: tools, by id, from the workspace.
- prompt: an existing prompt by id, or a new prompt (name + content) that the user reviews in the prompt editor \
before it is saved.
- starters: up to 4 example first questions shown in a new chat, each at most 200 characters, written the way \
the agent's users would ask."""

NEVER_POLICY = """Never set or mention changing models, guardrails, limits, allowed websites, API write permissions, \
a JSON response schema, analytics or sharing: those stay as they are."""

NEVER_OTHER = """Never set or mention changing models, allowed websites, API write permissions, a JSON response \
schema or sharing: those stay as they are."""

DESIGN_RULES = f"""Designing it well:
- Pick knowledge and tools only from what exists in the workspace, and only what the agent needs. Read a source's \
files or a tool's actions when the name alone doesn't tell you what it covers. Skip a source whose status is \
failed.
- If the agent faces the public (customers, a website) and a source or tool looks internal (contracts, rates, HR, \
salaries, credentials, internal notes; a tool that reads or changes internal systems, such as a database, admin, \
billing or CRM tool), don't attach it silently: ask, or leave it out and say why.
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
{COMPOSER_ADDS}
  Don't write lines about the date, citing sources, formatting or treating documents as data.
- {hand_off_rule("the agent has a tool for it")}
- {no_placeholders("a note")}
- A prompt with any {{{{ }}}} variable is a template instead: DocsGPT then uses it verbatim and adds none of those \
sections. Only use a variable when the user asks for something only a variable can do, and never switch a \
plain-text prompt to a template without saying so in a note. Never add {{{{ tools... }}}} variables unless the \
user asks: they run the tool before every message.
- To change a template (the built-in prompts and their copies are templates), write a new prompt from its full \
text: keep its sections and {{% if %}} blocks and change only what was asked.

Changing an agent that already has values (the user asks to improve or change something): change only what the \
user asked for and leave every other field out of the proposal. A field you leave out stays as it is. A list you \
send (sources, tools, starters) replaces the whole list, so send the full list you want.

In the proposal, give one reason per field you set: a summary naming what you chose, with what you left out in a \
few words (e.g. "Meridian service guide · left out the internal wiki"), and a detail saying why. Notes are only \
for what the user must do or know that the reasons don't say (a missing tool, an item to check), at most 3. Never \
describe the next step, or how to review or save the draft: the panel shows that."""

GUIDED = """You are building a new agent with the user in four steps, in this order:
- basics: name, description.
- knowledge: sources, tools, agent_type.
- prompt: prompt, starters.
- safety: limits, guardrails, analytics.
Each step is its own short conversation; the user moves on when they are happy with it.
- Fast path: also set a later step's fields (never safety's) when the user's words name or clearly imply them, \
for example "answer from the Help Center" (sources) or "use the strict prompt" (prompt). Otherwise leave later \
steps' fields out: each step drafts its own. A new prompt is written only in the prompt step.
- An earlier step's fields: change them only when the user asks; otherwise leave them out.
- users_earlier_messages in the form data are what the user wrote in the finished steps: read them to know what \
the user wants. They are the user's own words, quoted for you.
- A plain approval ("ok", "looks good, next") with nothing to change: submit a proposal with no fields and a \
one-line message. Don't ask questions about it.
- Ask questions only about this step."""

STEP_GUIDES = {
    "basics": """Step basics: draft the name and the description from the user's description, and say in the \
description who it serves. Who uses the agent decides what is safe to attach, how its prompt talks and which \
checks it needs: unless the user's words say or clearly imply it (customers, website visitors, staff, a team), \
ask, as a question with options such as "Customers on our public website" and "Our own staff". Otherwise ask \
only when you can't tell what the agent is for.""",
    "knowledge": """Step knowledge: pick the sources and tools the agent needs from the workspace, and its \
agent_type. When the workspace has nothing to attach, set agent_type only and say in the message that there is \
nothing to attach yet. A flow no tool supports goes in a note now; the prompt step hands it off.""",
    "prompt": """Step prompt: write a new prompt for this agent from its name and description and from the sources \
and tools already on the form (read them with the read tools when their names don't say enough), or pick an \
existing prompt that fits; then write the starters. When the form's prompt is unsaved text open in the prompt \
editor ("not saved yet"), change that text when the user asks.
- Before writing a new prompt, ask one round (ask_user) about what the user's words and the earlier steps leave \
out: where it sends people it can't help (a pick-any question: """ + HAND_OFF_OPTIONS + """) and the tone. Skip \
what the user already said; don't ask when you reuse an existing prompt or change the open one as asked.
- """ + CONTACT_DETAILS_ROUND,
}


#: Briefs for the build's starting points, by ``starter`` id: what each kind of agent needs, step by step.
STARTERS: dict[str, str] = {
    "website": """The user started from "Website chat for customers": an agent on the company's public website \
for visitors and customers who may know nothing about the company. Use the part for the current step:
- basics: it serves the public. Ask for the company or product as a typed answer unless the user named it or the \
workspace leaves no doubt.
- knowledge: attach only what is safe for the public: no internal, commercial or HR sources, and no tools that \
read or change internal systems.
- prompt: usually off-limits are prices, discounts or delivery dates the documents don't confirm, legal advice and \
anything internal. It answers in the visitor's language.
- safety: recommend pii and injection.""",
    "helpdesk": """The user started from "Internal helpdesk": an agent for the company's own staff, answering HR, \
IT and policy questions. Use the part for the current step:
- basics: it serves staff. Ask which areas it covers (HR, IT, policies, office and facilities) unless the user \
said.
- knowledge: internal sources fit, but leave out what not every employee may read (salaries, individual HR \
cases, credentials) and ask when unsure.
- prompt: personal cases (pay, health, disputes, complaints) go to a person, and it never guesses a policy the \
documents don't state. The hand-off is who staff contact: a team, an email or a ticket portal.
- safety: recommend pii, and secrets when it covers IT.""",
    "research": """The user started from "Research assistant": an agent that digs through the user's documents \
and answers from them. Use the part for the current step:
- basics: ask what the documents are (contracts, reports, papers, case files) and who uses it, unless the user \
said.
- knowledge: attach the sources that hold those documents. agent_type research fits long, deep answers across \
many documents, classic quick lookups: ask when it isn't clear which.
- prompt: it says plainly when the documents are silent, points out where documents disagree rather than \
picking one, and names the document an answer comes from. A hand-off is often not needed.
- safety: recommend groundedness and pii.""",
}

def _safety_guide() -> str:
    """The safety step's section: ask first, then the three parts, with the instance's default limits."""
    limits = settings.DEFAULT_AGENT_LIMITS
    return f"""Step safety: limits, guardrails and Insights topics. Which of them you may set is in safety_options \
in the form data. Leave out a part marked unavailable and don't ask about it; when it is unavailable for lack of \
access, say once that the agent's owner or an editor with policy access can set it.
- Ask first: before any proposal, ask one round of questions (ask_user), one question per available part. Put the \
recommended option first and say in its label that it is recommended. Set only what the user picked: a part the \
user declines stays out of the proposal.
- limits: one budget shared by everyone using the agent, counted over the last 24 hours: either a request limit \
or a token limit, never both. Recommend {limits["request_limit"]:,} requests (or {limits["token_limit"]:,} tokens \
when the user thinks in cost). mode "none" turns limits off.
- guardrails: checks from the menu in safety_options, added to the agent's own. Unless the agent already enforces \
its guardrails (mode scan_all), they run in monitor-only mode: they record what they would have done, and the \
owner turns enforcement on later. pii hides personal data (emails, \
phone numbers, card numbers) in questions and answers; injection blocks messages that try to override the agent's \
instructions; groundedness flags answers its knowledge doesn't back; secrets hides keys and passwords in answers. \
Recommend pii and injection for an agent that faces the public.
- analytics: Insights sorts the agent's conversations by topic so its owner sees what users ask about. Ask \
whether to sort conversations into these starting topics, naming up to {MAX_NEW_TOPICS} topics drawn from what \
the agent is for, each a name of at most {TOPIC_NAME_CHARS} characters and a description of at most \
{TOPIC_DESCRIPTION_UNITS} characters listing concrete things users ask ("Late or stuck parcels, missed delivery \
windows"). Never reuse a topic the agent already has. The folders of its sources (source_folders in \
safety_options) already sort conversations as topics: never suggest a topic a folder already covers, only what \
they miss, and at most room topics. Past room, each topic pushes the smallest folder out (up to \
room_pushing_folders_out more): suggest that only when the user asks for more topics, and say which folder."""


def instructions(req: DraftRequest, ws: Workspace) -> str:
    """The agent recipe's system instructions: the shared rules, then the current step's or improve mode's."""
    step = req.context["step"]
    form = req.context["form"]
    parts = [AGENT_FIELDS, NEVER_OTHER if step == "safety" else NEVER_POLICY, DESIGN_RULES]
    if step:
        own = ", ".join(STEP_FIELDS[step])
        parts += [GUIDED, f"The current step is {step}. In this step set only: {own}.",
                  _safety_guide() if step == "safety" else STEP_GUIDES[step]]
        if req.context.get("starter"):
            parts.append(STARTERS[req.context["starter"]])
        return "\n\n".join(parts)
    has_values = any(form.get(k) for k in ("name", "description", "sources", "tools", "starters")) \
        or bool(form.get("prompt_draft")) or (form.get("prompt_id") not in (None, "default"))
    parts.append(
        "The form already has values: treat the user's message as a change request."
        if has_values or ws.agent
        else "The form is empty: draft the whole agent from the user's description."
    )
    return "\n\n".join(parts)


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
                "limits": {
                    "type": "object",
                    "description": 'Step safety only. mode "requests" or "tokens" with value, or "none" (no limit).',
                    "properties": {
                        "mode": {"type": "string", "enum": list(LIMIT_MODES)},
                        "value": {"type": "integer", "description": "Requests or tokens per 24 hours."},
                    },
                    "required": ["mode"],
                },
                "guardrails": {
                    "type": "object",
                    "description": "Step safety only. Checks to add, from the menu.",
                    "properties": {
                        "checks": {"type": "array", "items": {"type": "string", "enum": list(GUARDRAIL_MENU)}},
                    },
                    "required": ["checks"],
                },
                "analytics": {
                    "type": "object",
                    "description": f"Step safety only. Insights topics to add, at most {MAX_NEW_TOPICS}.",
                    "properties": {
                        "topics": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
                                "required": ["name", "description"],
                            },
                        },
                    },
                    "required": ["topics"],
                },
            },
        },
        "reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(FIELDS)},
                    "summary": {"type": "string", "description": "What you chose, by name, and what you left out."},
                    "detail": {"type": "string", "description": "Why, or what you left out."},
                },
                "required": ["field", "summary"],
            },
        },
        "notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "At most 3: what the user must do or know that the reasons don't say.",
        },
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


def _new_prompt(raw: dict, req: DraftRequest, ws: Workspace, notes: list[str]) -> dict:
    """Check a new prompt; notes a switch into template mode.

    Raises:
        ProposalInvalid: Missing name or content, too long, a template that
            doesn't parse, or tool variables the user didn't ask for.
    """
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
    if not template_parses(content):
        raise ProposalInvalid([TEMPLATE_PROBLEM])
    _, current = _current_prompt(req.context["form"], ws)
    problem = tool_variables_problem(content, current, req)
    if problem:
        raise ProposalInvalid([problem])
    if is_template(content) and not is_template(current):
        notes.append(
            "The new prompt uses template variables, so DocsGPT uses it as written and doesn't add its own "
            "sections (date, citations, formatting, boundaries)."
        )
    return {"kind": "new", "name": name, "content": content}


def _for_step(raw_fields: dict, step: Optional[str]) -> dict:
    """The proposal's fields the step may set: policy only in the safety step, a new prompt only in the prompt
    step or improve mode. Anything else is left out without a problem: the model drafted ahead."""
    out = {key: value for key, value in raw_fields.items() if step == "safety" or key not in SAFETY_FIELDS}
    prompt = out.get("prompt")
    if step not in (None, "prompt") and isinstance(prompt, dict) and prompt.get("kind") == "new":
        del out["prompt"]
    return out


def _limits(raw: Any) -> dict:
    """A drafted limit: ``{mode: "none"}`` or ``{mode, value}``.

    Raises:
        ProposalInvalid: An unknown mode, or a request or token limit without a whole number in range.
    """
    mode = raw.get("mode") if isinstance(raw, dict) else None
    if mode not in LIMIT_MODES:
        raise ProposalInvalid(['limits.mode is "requests", "tokens" or "none".'])
    if mode == "none":
        return {"mode": "none"}
    value = raw.get("value")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= LIMIT_MAX:
        raise ProposalInvalid([f"A {mode} limit needs a whole number from 1 to {LIMIT_MAX:,}."])
    return {"mode": mode, "value": value}


def _checks(raw: Any, form: dict, ws: AgentWorkspace) -> list[str]:
    """The menu checks to add, in the model's order: available here, and not already on (an agent whose
    guardrails are off gets a check it has again, since adding it turns them on)."""
    checks = raw.get("checks") if isinstance(raw, dict) else None
    guardrails = form["guardrails"]
    present = set(guardrails["checks"]) if guardrails["enabled"] else set()
    out: list[str] = []
    for check in checks if isinstance(checks, list) else []:
        key = str(check).strip().lower()
        if key in ws.guardrail_menu and key not in present and key not in out:
            out.append(key)
    return out


def _topics(raw: Any, form: dict, ws: AgentWorkspace, notes: list[str]) -> list[dict]:
    """The Insights topics to add, checked with the rules the agent's analytics config applies on save.

    A name the agent, one of its source folders (or an earlier topic of the proposal) already has is left out.
    Topics that push folders out of the topic question add a note naming them.

    Raises:
        ProposalInvalid: Too many topics, a name or description the analytics config refuses, or more topics
            than the agent has room for.
    """
    items = raw.get("topics") if isinstance(raw, dict) else None
    items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    if len(items) > MAX_NEW_TOPICS:
        raise ProposalInvalid([f"Suggest at most {MAX_NEW_TOPICS} topics."])
    taken = {name.lower() for name in form["analytics"]["topics"]} | {f["name"].lower() for f in ws.folders}
    out: list[dict] = []
    problems: list[str] = []
    for item in items:
        name = clean_text(item.get("name"), TOPIC_NAME_CHARS + 50)
        description = clean_text(item.get("description"), TOPIC_DESCRIPTION_UNITS * 2)
        if not description:
            problems.append(f"Topic {name!r} needs a description.")
            continue
        try:
            topic = AnalyticsTopic.model_validate({"id": _CHECK_TOPIC_ID, "name": name, "description": description})
        except ValidationError as err:
            problems.append(f"Topic {name!r}: {err.errors()[0].get('msg', err)}.".replace("Value error, ", ""))
            continue
        if topic.name.lower() in taken:
            continue
        taken.add(topic.name.lower())
        out.append({"name": topic.name, "description": topic.description})
    if problems:
        raise ProposalInvalid(problems[:5])
    room = _topic_room(form, ws)["max"]
    if len(out) > room:
        raise ProposalInvalid([f"The agent has room for {room} more topics: suggest at most {room}."])
    pushed = _topic_view(form, ws).pushes_out(len(out))
    if pushed:
        names = pushed[0] if len(pushed) == 1 else ", ".join(pushed[:-1]) + " and " + pushed[-1]
        notes.append(f"Insights offers {ws.max_topics} topics, source folders included: these leave out the "
                     f"folder{'s' if len(pushed) > 1 else ''} {names}.")
    return out


def _policy(raw_fields: dict, req: DraftRequest, ws: AgentWorkspace, fields: dict, dropped: list[dict],
            notes: list[str]) -> None:
    """Check the safety step's limits, guardrails and topics into ``fields``.

    Limits and guardrails need ``edit_policy`` (listed in ``dropped`` as ``not_allowed`` without it); a part the
    instance or the agent has turned off is left out. What remains is accepted only after a questions round.

    Raises:
        ProposalInvalid: Policy proposed before asking the user, or a value the model can fix.
    """
    form = req.context["form"]
    available = {
        "limits": ws.policy_editable,
        "guardrails": ws.policy_editable and bool(ws.guardrail_menu),
        "analytics": ws.insights and form["analytics"]["enabled"] and _topic_room(form, ws)["max"] > 0,
    }
    wanted = []
    for key in SAFETY_FIELDS:
        if key not in raw_fields:
            continue
        if key != "analytics" and not ws.policy_editable:
            dropped.append({"field": key, "reason": "not_allowed"})
        elif available[key]:
            wanted.append(key)
    if wanted and not question_rounds(req.messages):
        raise ProposalInvalid([ASK_FIRST])
    if "limits" in wanted:
        fields["limits"] = _limits(raw_fields["limits"])
    if "guardrails" in wanted:
        checks = _checks(raw_fields["guardrails"], form, ws)
        if checks:
            fields["guardrails"] = {"checks": checks}
    if "analytics" in wanted:
        topics = _topics(raw_fields["analytics"], form, ws, notes)
        if topics:
            fields["analytics"] = {"topics": topics}


def _progress(step: Optional[str], fields: dict) -> tuple[list[str], Optional[str]]:
    """The steps a proposal fills (the current one and the later ones it drafted ahead) and the next step to run.

    The prompt step counts as filled only with a prompt: starters alone leave it to write one.
    """
    if step is None:
        return [], None
    later = STEPS[STEPS.index(step) + 1:]
    filled = [step] + [
        s for s in later
        if ("prompt" in fields if s == "prompt" else any(key in fields for key in STEP_FIELDS[s]))
    ]
    return filled, next((s for s in later if s not in filled), None)


def validate(args: dict, req: DraftRequest, ws: Workspace) -> dict:
    """Turn ``submit_proposal`` arguments into the agent ``proposal`` payload.

    Unknown fields, and fields the step may not set, are left out. Ids the
    caller can't attach, and policy they may not change, are dropped and listed
    in ``dropped``. A field equal to the form's value is left out, so the form
    marks only real changes. ``steps`` and ``next_step`` say where the guided
    build goes next (empty and None in improve mode).

    Raises:
        ProposalInvalid: A value the model can fix (length, empty name, starters, prompt rules, limits, topics),
            or policy proposed before asking the user.
    """
    from docsgpt.api.user.agents.starters import normalize_starters, StartersError

    step = req.context["step"]
    form = req.context["form"]
    raw_fields = _for_step(args.get("fields") or {}, step)
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
    if step == "safety":
        _policy(raw_fields, req, ws, fields, dropped, notes)

    _drop_unchanged(fields, form)
    reasons = []
    for reason in args.get("reasons") or []:
        if reason.get("field") not in fields or any(r["field"] == reason["field"] for r in reasons):
            continue
        summary = clean_text(reason.get("summary"), REASON_SUMMARY_MAX)
        if not summary:
            continue
        entry = {"field": reason["field"], "summary": summary}
        detail = clean_text(reason.get("detail"), REASON_DETAIL_MAX)
        if detail:
            entry["detail"] = detail
        reasons.append(entry)
    steps, next_step = _progress(step, fields)
    return {
        "message": clean_text(args.get("message"), MESSAGE_MAX),
        "fields": fields,
        "reasons": reasons[:MAX_REASONS],
        "notes": notes,
        "dropped": dropped,
        "steps": steps,
        "next_step": next_step,
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
    limits = fields.get("limits")
    if limits and limits["mode"] == form["limits"]["mode"] and limits.get("value") == form["limits"]["value"]:
        del fields["limits"]
    prompt = fields.get("prompt")
    if prompt:
        draft = form.get("prompt_draft")
        if prompt["kind"] == "existing" and not draft and prompt["id"] == (form.get("prompt_id") or "default"):
            del fields["prompt"]
        elif prompt["kind"] == "new" and draft and draft.get("content") == prompt["content"] \
                and draft.get("name") == prompt["name"]:
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
