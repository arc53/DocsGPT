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

Improve mode also reads the agent's Insights when the caller may edit it and Insights has enough of its
conversations (``docsgpt/drafter/gaps.py``): the gap summary, the gap the user started from (``gap``) or one
conversation from Logs (``conversation_id``), and two live, capped read tools for example questions. Its proposal
then lists the gaps it fixes (``gaps``, with the summary's counts filled in by the server), and may add the
groundedness guardrail, monitor-only, for answers the docs don't back.

The steps, fields, guardrail menu and caps are in ``agent_form.py``, the instruction text in
``agent_instructions.py``, and the reading of the safety step's English wording in ``safety_wording.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import ValidationError

from docsgpt.analytics.config import AnalyticsTopic, TOPIC_DESCRIPTION_UNITS, TOPIC_NAME_CHARS
from docsgpt.core.settings import settings
from docsgpt.drafter.agent_form import (
    AGENT_TYPES,
    BUILTIN_PROMPTS,
    checks_on,
    DESCRIPTION_MAX,
    FIELDS,
    GAP_EXAMPLE_MAX,
    GAP_NEEDS_MAX,
    GUARDRAIL_MENU,
    GUARDRAIL_MODES,
    INSIGHTS_CHECK,
    LIMIT_MAX,
    LIMIT_MODES,
    MAX_GAP_LINKS,
    MAX_GAPS,
    MAX_NEW_TOPICS,
    MAX_NOTES,
    MAX_REASONS,
    MAX_REFS,
    NAME_MAX,
    NOTE_MAX,
    PROMPT_CONTENT_MAX,
    PROMPT_NAME_MAX,
    REASON_SUMMARY_MAX,
    SAFETY_FIELDS,
    STEP_FIELDS,
    STEPS,
    UNGROUNDED,
)
from docsgpt.drafter.agent_instructions import (
    AGENT_FIELDS,
    CONVERSATION_RULES,
    DESIGN_RULES,
    GUIDED,
    INSIGHTS_RULES,
    NEVER_GUIDED,
    NEVER_OTHER,
    NEVER_POLICY,
    NEVER_POLICY_INSIGHTS,
    safety_guide,
    SKIPPED,
    STARTERS,
    STEP_GUIDES,
)
from docsgpt.drafter.catalog import (
    is_template,
    load_models,
    prompt_text,
    PROMPT_CHARS,
    read_workspace,
    Workspace,
)
from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.gaps import (
    agent_gaps,
    conversation_excerpt,
    focus_group,
    InsightsReader,
    PAGE_GROUPS,
)
from docsgpt.drafter.prompt_edits import apply_edits, CHECK_TO_PERSONA, check_drafted_prompt, checks_for
from docsgpt.drafter.prompt_recipe import PROMPT_RECIPE, PromptTooLong, RAW_READ_MAX, READ_MAX
from docsgpt.drafter.recipe import (
    BadDraftRequest,
    clean_id,
    DraftRequest,
    ID_CHARS,
    MESSAGE_MAX,
    ProposalInvalid,
    Recipe,
    register,
)
from docsgpt.drafter.runner import question_rounds
from docsgpt.drafter.safety_wording import (
    CLAIMS_UNSET,
    check_questions,
    PART_NAMES,
    SETTLED_AGAINST,
    settled_parts,
    stated,
    unbacked_claims,
)
from docsgpt.drafter import topics_recipe
from docsgpt.drafter.topics_recipe import TopicsWorkspace
from docsgpt.storage.db.repositories.conversation_labels import LOG_LABELS, SUMMARY_GAP_TYPES, TOPIC_PREFIX

logger = logging.getLogger(__name__)

#: Caps on the form values a request sends.
_FORM_TEXT = {"name": 200, "description": 2000, "agent_type": 40}
_FORM_MAX_REFS = 200
_FORM_MAX_NAMES = 100
#: Most of the user's messages from finished steps a request sends, and characters of one.
MAX_EARLIER = 12
EARLIER_CHARS = 2000
#: The id a drafted topic is checked under (the form gives it its own).
_CHECK_TOPIC_ID = "drafttopic"
#: Characters of the context's focus gap topic, and of its page or source row's key (a page's URL).
_GAP_TOPIC_CHARS = 200
_GAP_KEY_CHARS = 500
#: Sources one improve turn with Insights or a Logs conversation may read (``get_source``).
IMPROVE_SOURCE_READS = 3

ASK_FIRST = (
    "Ask the user first: call ask_user with a question for each part of this step their words leave open ({parts}), "
    "the recommended option first, then set what they pick and what they said."
)
SKIPPED_OPEN = (
    "The user skipped the questions, so set only what their own words state: leave {parts} out of fields, and "
    "don't say in your message that you set them; say they are not set and the user can set them in the form's "
    "Safety section."
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
        topics_from_conversations: The saved agent has enough recent conversations for Suggest from conversations
            (safety step only), so the step leaves topics to it rather than guessing them.
        editable_prompt_text: The whole saved text of the prompt edits may change (``prompt_texts`` holds it whole
            too, for the model), or None when the form has none or its unsaved text is open in the prompt view.
        long_prompt: The caller's own saved prompt the form uses when it is over :data:`READ_MAX` characters: the
            model reads only its start, so it takes no edits.
        gaps: The saved agent's gap summary (``gaps.agent_gaps``), improve mode only, for a caller who may edit it;
            None when not read.
        insights_reader: The live reads behind ``get_gap_examples`` and ``get_conversations``, for that agent, while
            its summary is available.
        conversation: The Logs conversation the user started from (``gaps.conversation_excerpt``), or None.
        source_reads_left: The ``get_source`` reads this turn has left (:data:`IMPROVE_SOURCE_READS` in improve
            mode with Insights or a Logs conversation), or None for no cap.
        focus_row: The Docs gaps row a page or source focus gap names, as a gap card's row titled by that page or
            source (``{topic, gap_type, expected, turns, previous, group_by, group_key}``), or None.
    """

    guardrail_menu: list[str] = field(default_factory=list)
    insights: bool = False
    max_topics: int = 15
    folders: list[dict] = field(default_factory=list)
    topics_from_conversations: bool = False
    editable_prompt_text: Optional[str] = None
    long_prompt: Optional[str] = None
    gaps: Optional[dict] = None
    insights_reader: Optional[InsightsReader] = None
    conversation: Optional[dict] = None
    source_reads_left: Optional[int] = None
    focus_row: Optional[dict] = None

    def reads_insights(self) -> bool:
        """Whether this turn has the agent's gap summary to work from."""
        return bool(self.gaps and self.gaps.get("available"))

    def counts(self) -> dict[str, int]:
        """The ``reading`` status, with the conversations Insights analysed when the summary was read."""
        out = super().counts()
        if self.reads_insights():
            out["insights_conversations"] = int(self.gaps["conversations"])
        return out

    def summary(self) -> dict[str, Any]:
        """The compact catalog, with the agent's gap summary when it was read."""
        out = super().summary()
        if self.reads_insights():
            out["insights"] = {
                "days": self.gaps["days"],
                "analysed_conversations": self.gaps["conversations"],
                "gaps": [{**row, "topic": _gap_topic(row["topic"])} for row in self.gaps["rows"]],
            }
        return out


def _ids(value: Any) -> list[str]:
    """Distinct non-empty ids of a form list, each cleaned (:func:`clean_id`), at most ``_FORM_MAX_REFS`` read."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:_FORM_MAX_REFS]:
        ref = clean_id(item)
        if ref and ref not in out:
            out.append(ref)
    return out


def _names(value: Any, limit: int) -> list[str]:
    """Distinct non-empty strings of a list, cleaned and capped."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:_FORM_MAX_NAMES]:
        name = clean_text(item, limit)
        if name and name not in out:
            out.append(name)
    return out


def _guardrail_controls(guardrails: dict) -> list[dict]:
    """The controls the form runs, ``{check, stage}`` each once, lowercased (the form sends only those on)."""
    out: list[dict] = []
    raw = guardrails.get("controls")
    for item in raw[:_FORM_MAX_NAMES] if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        control = {"check": clean_text(item.get("check"), 40).lower(), "stage": clean_text(item.get("stage"), 40)}
        if control["check"] and control["stage"] and control not in out:
            out.append(control)
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
            "controls": _guardrail_controls(guardrails),
        },
        # Collecting insights is on by default for an agent.
        "analytics": {
            "enabled": analytics.get("enabled") is not False,
            "topics": _names(names, TOPIC_NAME_CHARS),
            "overlapping": _names(overlapping, TOPIC_NAME_CHARS),
            "hidden_folders": _names(analytics.get("hidden_folders"), TOPIC_NAME_CHARS),
        },
    }


def _earlier(values: list) -> list[str]:
    """The finished steps' messages: the first :data:`MAX_EARLIER` that aren't empty, cleaned and capped.

    Stops cleaning once it has them, so a long list costs no more than its kept items.
    """
    out: list[str] = []
    for value in values:
        if len(out) >= MAX_EARLIER:
            break
        text = clean_text(value, EARLIER_CHARS)
        if text:
            out.append(text)
    return out


def parse_context(raw: Any) -> dict:
    """Clean the agent form's values: ``{agent_id, step, starter?, skip_questions?, earlier, form: {...}}``.

    ``skip_questions`` (true only) is a turn the user sent with Skip on a question round: it takes no questions.

    Wrong-typed values are left out rather than refused; only a ``form`` that
    isn't an object, or an unknown ``step``, is. The prompt view's unsaved
    text is cleaned but never cut, since edits must fit it.

    Raises:
        BadDraftRequest: ``form`` is present but not an object, ``step`` is not one of :data:`STEPS` or null, or
            the prompt view's text is over :data:`READ_MAX` characters.
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
    form["prompt_id"] = clean_id(form_raw.get("prompt_id"))
    draft = form_raw.get("prompt_draft")
    form["prompt_draft"] = None
    if isinstance(draft, dict) and isinstance(draft.get("content"), str):
        if len(draft["content"]) > RAW_READ_MAX:
            raise PromptTooLong(READ_MAX)
        content = clean_text(draft["content"], len(draft["content"]))
        if len(content) > READ_MAX:
            raise PromptTooLong(READ_MAX)
        form["prompt_draft"] = {"name": clean_text(draft.get("name"), PROMPT_NAME_MAX), "content": content}
        # The saved prompt whose unsaved changes the view holds; none for a new prompt.
        draft_id = clean_id(draft.get("id"))
        if draft_id:
            form["prompt_draft"]["id"] = draft_id
    starters = form_raw.get("starters")
    form["starters"] = [clean_text(s, 300) for s in starters[:10] if isinstance(s, str) and s.strip()] \
        if isinstance(starters, list) else []
    form.update(_parse_policy(form_raw))
    earlier = raw.get("earlier") if isinstance(raw.get("earlier"), list) else []
    starter = raw.get("starter")
    conversation_id = clean_id(raw.get("conversation_id")) if step is None else None
    return {
        "skip_questions": raw.get("skip_questions") is True,
        "agent_id": clean_id(raw.get("agent_id")),
        "step": step,
        "starter": starter if isinstance(starter, str) and starter in STARTERS else None,
        "earlier": _earlier(earlier),
        "form": form,
        # Improve mode's ways in from Insights: the gap or the Logs conversation the user started from.
        "gap": _parse_gap(raw.get("gap")) if step is None else None,
        "conversation_id": conversation_id,
        # The Logs row the user clicked, read only inside that conversation.
        "message_id": clean_id(raw.get("message_id")) if conversation_id else None,
    }


def _gap_topic(value: Any) -> Optional[str]:
    """A gap's topic as the model reads and names it, cleaned; None for none."""
    return clean_text(value, _GAP_TOPIC_CHARS) or None


def _parse_gap(raw: Any) -> Optional[dict]:
    """The focus gap of an improve request, or None when it isn't one.

    ``{topic, gap_type}``, plus ``group_by`` (``page`` or ``source``) and ``group_key`` (the Docs gaps row's key;
    None for the row of answers with no source) when the user started from a row grouped by page or source.
    """
    if not isinstance(raw, dict) or raw.get("gap_type") not in SUMMARY_GAP_TYPES:
        return None
    gap = {"topic": _gap_topic(raw.get("topic")), "gap_type": raw["gap_type"]}
    if raw.get("group_by") in PAGE_GROUPS:
        gap["group_by"] = raw["group_by"]
        gap["group_key"] = clean_text(raw.get("group_key"), _GAP_KEY_CHARS) or None
    return gap


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


def source_folders(conn, source_ids: list[str]) -> list[dict]:
    """The folders of these sources, as the agent's topic question offers them (``topics.folders``)."""
    from docsgpt.analytics import topics as analytics_topics
    from docsgpt.storage.db.repositories.sources import SourcesRepository

    if not source_ids:
        return []
    return analytics_topics.folders(SourcesRepository(conn).list_by_ids(source_ids))


def editable_saved_agent(conn, user_id: str, agent_id: str) -> Optional[dict]:
    """The saved agent's row when the caller may edit it, else None."""
    from docsgpt.api.user.resource_access import AccessDenied

    try:
        return topics_recipe.editable_agent(conn, user_id, agent_id)
    except AccessDenied:
        return None


def saved_source_ids(conn, agent: dict) -> set[str]:
    """The source ids of a saved agent the caller may edit (:func:`editable_saved_agent`).

    An editor's form keeps the owner's private sources, which the editor can't attach: their folders are still
    the agent's topics.
    """
    from docsgpt.analytics.topics import agent_sources

    return {str(row["id"]) for row in agent_sources(conn, agent)}


def saved_prompt_text(conn, user_id: str, prompt_id: str) -> Optional[str]:
    """The whole text of the caller's own saved prompt, cleaned as the model reads it but not cut; None if not theirs."""
    from docsgpt.storage.db.repositories.prompts import PromptsRepository

    row = PromptsRepository(conn).get(prompt_id, user_id)
    content = (row or {}).get("content")
    return clean_text(content, len(content)) if isinstance(content, str) and content else None


def _load(user_id: str, context: dict) -> AgentWorkspace:
    """The caller's workspace plus what this request's step needs, read in one read-only transaction.

    Every step reads the text of the form's saved prompt, the one prompt the model is always shown: whole when
    edits may change it. The safety step also reads the instance's guardrail menu and Insights switch, the folders
    of the agent's sources, and whether a saved agent has enough conversations for Suggest from conversations; the
    saved agent's row is read once for both.
    """
    from docsgpt.storage.db.session import db_readonly

    form = context.get("form") or {}
    # The instance's switches first: the decision model's status needn't hold a connection.
    menu, insights = guardrail_menu(), topics_recipe.insights_on_here()
    with db_readonly() as conn:
        ws = read_workspace(conn, user_id, context.get("agent_id"))
        out = AgentWorkspace(**vars(ws), guardrail_menu=menu, insights=insights,
                             max_topics=int(settings.ANALYTICS_MAX_TOPICS))
        editable = _editable_prompt(form, ws)
        if editable and not form.get("prompt_draft"):
            text = saved_prompt_text(conn, user_id, editable)
            if text is not None and len(text) > READ_MAX:
                out.long_prompt = editable
                out.prompt_texts[editable] = clean_text(text, PROMPT_CHARS)
            elif text is not None:
                # The model reads the prompt it may edit whole, not the catalog's cut copy.
                out.editable_prompt_text = out.prompt_texts[editable] = text
        if not form.get("prompt_draft"):
            prompt_text(out, form.get("prompt_id") or "default", conn)
        if context.get("step") is None and ws.agent:
            agent = editable_saved_agent(conn, user_id, ws.agent["id"])
            if agent:
                _read_insights(conn, agent, context, out)
        if context.get("step") == "safety" and out.insights:
            agent = editable_saved_agent(conn, user_id, ws.agent["id"]) if ws.agent else None
            # The form's sources the caller may attach, and those already on the saved agent.
            known = ws.ids("sources") | (saved_source_ids(conn, agent) if agent else set())
            out.folders = source_folders(conn, [s for s in form.get("sources", []) if s in known])
            if agent:
                # Last in the transaction: a failed count leaves nothing after it to read.
                try:
                    out.topics_from_conversations = bool(topics_recipe.status_of(conn, agent)["available"])
                except Exception:
                    out.topics_from_conversations = False
    load_models(user_id, out)
    return out


def _read_insights(conn, agent: dict, context: dict, ws: AgentWorkspace) -> None:
    """Fill the improve mode's Insights reads for a saved agent the caller may edit: its gap summary (with the
    read tools' reader while it is available) and the Logs conversation the user started from.

    Each read runs in a savepoint: one that fails costs only itself, never the rest of the transaction.
    """
    try:
        with conn.begin_nested():
            ws.gaps = agent_gaps(conn, agent)
        if ws.reads_insights():
            ws.insights_reader = InsightsReader.for_summary(agent, ws.gaps).focused(context.get("gap"))
    except Exception:
        logger.warning("drafter: could not read the agent's gap summary", exc_info=True)
        ws.gaps = None
    if ws.reads_insights() and (context.get("gap") or {}).get("group_by") in PAGE_GROUPS:
        try:
            with conn.begin_nested():
                ws.focus_row = _focus_row(focus_group(conn, agent, context["gap"]), context["gap"], ws)
        except Exception:
            logger.warning("drafter: could not read the focus gap's page or source row", exc_info=True)
            ws.focus_row = None
    if context.get("conversation_id"):
        try:
            with conn.begin_nested():
                ws.conversation = conversation_excerpt(conn, agent, context["conversation_id"],
                                                       context.get("message_id"))
        except Exception:
            logger.warning("drafter: could not read the conversation", exc_info=True)
            ws.conversation = None
    if ws.reads_insights() or ws.conversation:
        ws.source_reads_left = IMPROVE_SOURCE_READS


def _focus_row(group: Optional[dict], gap: dict, ws: AgentWorkspace) -> Optional[dict]:
    """A page or source focus gap's Docs gaps row as a gap card's row, titled by the page or the source."""
    if group is None:
        return None
    names = {str(row["id"]): row.get("name") for row in ws.sources}
    title = (names.get(str(group["key"])) if gap["group_by"] == "source" else None) or group.get("name") \
        or group["key"]
    return {"topic": clean_text(title, _GAP_TOPIC_CHARS), "gap_type": gap["gap_type"], "expected": group["expected"],
            "turns": group["turns"], "previous": group["previous"], "group_by": gap["group_by"],
            "group_key": group["key"]}


def _current_prompt(form: dict, ws: Workspace) -> tuple[Optional[str], str]:
    """The form's prompt as ``(id or None for unsaved text, text)``; text is empty when unknown."""
    draft = form.get("prompt_draft")
    if draft:
        return None, draft.get("content") or ""
    prompt_id = form.get("prompt_id") or "default"
    whole = getattr(ws, "editable_prompt_text", None)
    if whole is not None and prompt_id == _editable_prompt(form, ws):
        return prompt_id, whole
    return prompt_id, prompt_text(ws, prompt_id) or ""


def _editable_prompt(form: dict, ws: Workspace) -> Optional[str]:
    """The id of the saved prompt a proposal may change with edits: the caller's own prompt the form uses, or the
    one whose unsaved changes the prompt view holds. None for a built-in, a shared or a new prompt."""
    draft = form.get("prompt_draft")
    target = draft.get("id") if draft else form.get("prompt_id")
    # The caller's own prompts over the workspace cap aren't shown to the model, but are still theirs to edit.
    own = {str(p["id"]) for p in ws.prompts if p.get("kind") == "own"} | ws.own_prompts
    # One too long to read whole would be edited from a cut copy.
    return target if target in own and target != getattr(ws, "long_prompt", None) else None


def _checks_view(guardrails: dict) -> list[str]:
    """The form's checks as the model reads them: a menu check on at some of its stages says which, as
    ``pii (input only)``, so the model may add the rest."""
    stages: dict[str, list[str]] = {}
    for control in guardrails["controls"]:
        stages.setdefault(control["check"], []).append(control["stage"])
    full = checks_on(guardrails)
    return [check if check in full or check not in GUARDRAIL_MENU else f"{check} ({' and '.join(on)} only)"
            for check, on in stages.items()]


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


def _safety_unavailable(form: dict, ws: AgentWorkspace) -> dict[str, Optional[str]]:
    """Why each safety part (:data:`SAFETY_FIELDS`) can't be set for this caller on this instance; None when it can.

    Limits and guardrails need ``edit_policy`` (``no_access``); guardrails also a menu (``off_on_this_instance``).
    Topics need Insights on here and for the agent, no Suggest from conversations, and room.
    """
    if not ws.insights:
        topics = "off_on_this_instance"
    elif not form["analytics"]["enabled"]:
        topics = "turned_off_for_this_agent"
    elif ws.topics_from_conversations:
        topics = "suggest_from_conversations"
    elif not _topic_room(form, ws)["max"]:
        topics = "no_room"
    else:
        topics = None
    if not ws.policy_editable:
        return {"limits": "no_access", "guardrails": "no_access", "analytics": topics}
    return {"limits": None, "guardrails": None if ws.guardrail_menu else "off_on_this_instance", "analytics": topics}


def _safety_options(form: dict, ws: AgentWorkspace) -> dict:
    """What the safety step may set for this caller on this instance, for the model."""
    off = {part: {"available": False, "why": why} for part, why in _safety_unavailable(form, ws).items() if why}
    defaults = settings.DEFAULT_AGENT_LIMITS
    limits = off.get("limits") or {
        "available": True,
        "recommended": {"requests": defaults["request_limit"], "tokens": defaults["token_limit"]},
    }
    guardrails = off.get("guardrails") or {"available": True, "checks": [
        {"id": check, "controls": [{"stage": stage, "action": action} for stage, action in GUARDRAIL_MENU[check]]}
        for check in ws.guardrail_menu
    ]}
    topics = off.get("analytics")
    if topics is None:
        room = _topic_room(form, ws)
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
    draft = form.get("prompt_draft")
    if draft and draft.get("id"):
        data["prompt"] = {"kind": "existing, changed in the prompt view (not saved yet)", **draft}
    elif draft:
        data["prompt"] = {"kind": "new (open in the prompt editor, not saved yet)", **draft}
    else:
        prompt_id = form.get("prompt_id") or "default"
        data["prompt"] = {"kind": "existing", "id": prompt_id}
        text = prompt_text(ws, prompt_id)
        if text and prompt_id not in BUILTIN_PROMPTS:
            data["prompt"]["content"] = text
    _, current = _current_prompt(form, ws)
    data["prompt"]["mode"] = "template" if is_template(current) else "persona"
    if _editable_prompt(form, ws):
        data["prompt"]["editable"] = True
    elif data["prompt"].get("id") and data["prompt"]["id"] == getattr(ws, "long_prompt", None):
        data["prompt"]["note"] = (f"Over {READ_MAX:,} characters, too long to change here: you read only its start. "
                                  "Leave it as it is.")
    if step == "safety":
        data.update({key: form[key] for key in SAFETY_FIELDS})
        guardrails = form["guardrails"]
        data["guardrails"] = {"enabled": guardrails["enabled"], "mode": guardrails["mode"],
                              "checks": _checks_view(guardrails)}
        data["analytics"] = {key: form["analytics"][key] for key in ("enabled", "topics")}
        data["safety_options"] = _safety_options(form, ws)
    if not step:
        data.update(_insights_data(req, ws))
    return data


def _insights_data(req: DraftRequest, ws: Workspace) -> dict:
    """Improve mode's Insights part of the form data: the gap the user started from, the Logs conversation (end
    users' text), and whether the groundedness guardrail may be added."""
    data: dict[str, Any] = {}
    if req.context.get("gap"):
        data["focus_gap"] = req.context["gap"]
    conversation = getattr(ws, "conversation", None)
    if conversation:
        data["conversation_from_logs"] = conversation
    if isinstance(ws, AgentWorkspace) and ws.reads_insights():
        data["guardrail_from_insights"] = _insights_guardrail(req.context["form"], ws)
    return data


def _insights_guardrail(form: dict, ws: AgentWorkspace) -> dict:
    """Whether an improve proposal may add :data:`INSIGHTS_CHECK`, and why not."""
    if not ws.policy_editable:
        return {"available": False, "why": "no_access"}
    if INSIGHTS_CHECK not in ws.guardrail_menu:
        return {"available": False, "why": "off_on_this_instance"}
    if form["guardrails"]["enabled"] and INSIGHTS_CHECK in checks_on(form["guardrails"]):
        return {"available": False, "why": "already_on"}
    if not any(row["gap_type"] == UNGROUNDED for row in ws.gaps["rows"]):
        return {"available": False, "why": "no_ungrounded_gap"}
    return {"available": True, "check": INSIGHTS_CHECK}


# ---------------------------------------------------------------------------
# Instructions (the text is in ``agent_instructions.py``)
# ---------------------------------------------------------------------------


def instructions(req: DraftRequest, ws: Workspace) -> str:
    """The agent recipe's system instructions: the shared rules, then the current step's or improve mode's."""
    step = req.context["step"]
    form = req.context["form"]
    insights = not step and isinstance(ws, AgentWorkspace) and ws.reads_insights()
    never = NEVER_OTHER if step == "safety" else NEVER_GUIDED if step else NEVER_POLICY_INSIGHTS if insights \
        else NEVER_POLICY
    parts = [AGENT_FIELDS, never, DESIGN_RULES]
    if step:
        own = ", ".join(STEP_FIELDS[step])
        parts += [GUIDED, f"The current step is {step}. In this step set only: {own}.",
                  safety_guide() if step == "safety" else STEP_GUIDES[step]]
        if req.context.get("starter"):
            parts.append(STARTERS[req.context["starter"]])
        if req.context.get("skip_questions"):
            parts.append(SKIPPED)
        return "\n\n".join(parts)
    has_values = any(form.get(k) for k in ("name", "description", "sources", "tools", "starters")) \
        or bool(form.get("prompt_draft")) or (form.get("prompt_id") not in (None, "default"))
    parts.append(
        "The form already has values: treat the user's message as a change request."
        if has_values or ws.agent
        else "The form is empty: draft the whole agent from the user's description."
    )
    if insights:
        parts.append(INSIGHTS_RULES)
    if not step and getattr(ws, "conversation", None):
        parts.append(CONVERSATION_RULES)
    if req.context.get("skip_questions"):
        parts.append(SKIPPED)
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
                    "description": 'kind "existing" with id, kind "new" with name and content, or kind "edit" '
                                   "with the editable prompt's id and edits.",
                    "properties": {
                        "kind": {"type": "string", "enum": ["existing", "new", "edit"]},
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "content": {"type": "string"},
                        "edits": PROMPT_RECIPE.proposal_schema["properties"]["edits"],
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
                    "description": "Step safety: checks to add, from the menu. Improve mode: only "
                                   f'["{INSIGHTS_CHECK}"], for an answer-not-backed gap (see the Insights rules).',
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
                },
                "required": ["field", "summary"],
            },
        },
        "notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "At most 3: what the user must do or know that the reasons don't say.",
        },
        "gaps": {
            "type": "array",
            "description": f"Improve mode with Insights only: the gaps from the summary this proposal acts on, at most "
                           f"{MAX_GAPS}.",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "The row's topic, exactly; leave out when it has none."},
                    "gap_type": {"type": "string", "enum": list(SUMMARY_GAP_TYPES)},
                    "example": {"type": "string", "description": "One question you read for this gap, at most "
                                                                    f"{GAP_EXAMPLE_MAX} characters."},
                    "fields": {"type": "array", "items": {"type": "string", "enum": list(FIELDS)},
                               "description": "The proposal's fields that fix this gap."},
                    "needs": {"type": "string", "description": "What only the user can do, at most "
                                                                  f"{GAP_NEEDS_MAX} characters; leave out otherwise."},
                    "links": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": ["source", "logs"]},
                                "id": {"type": "string", "description": "kind source: the source's id."},
                                "label": {"type": "string", "description": "kind logs: the Logs label."},
                            },
                            "required": ["kind"],
                        },
                    },
                },
                "required": ["gap_type"],
            },
        },
    },
    "required": ["message", "fields"],
}


def _refs(
    field_name: str, value: Any, allowed: set[str], current: list[str], dropped: list[dict]
) -> Optional[list[str]]:
    """The drafted list of source or tool ids, each once, those the caller can't attach dropped as ``not_found``.

    None when ids were sent and every one was dropped (a name in place of an id): the form's list stays as it is,
    rather than being cleared. An empty list sent on purpose stays empty.

    Args:
        field_name: ``sources`` or ``tools``.
        value: The model's list.
        allowed: Ids the caller can attach, and those already on the form.
        current: The form's ids: they don't count towards :data:`MAX_REFS`, which caps what the proposal adds.
        dropped: Where dropped ids are listed.

    Raises:
        ProposalInvalid: The proposal adds more than :data:`MAX_REFS` ids.
    """
    out: list[str] = []
    missing = 0
    for item in value if isinstance(value, list) else []:
        ref = str(item).strip()
        if not ref or ref in out:
            continue
        if ref not in allowed:
            dropped.append({"field": field_name, "id": ref[:ID_CHARS], "reason": "not_found"})
            missing += 1
            continue
        out.append(ref)
    if missing and not out:
        return None
    if len([ref for ref in out if ref not in current]) > MAX_REFS:
        raise ProposalInvalid([f"Add at most {MAX_REFS} {field_name}."])
    return out


def _new_prompt(raw: dict, req: DraftRequest, ws: Workspace) -> dict:
    """Check a new prompt; its ``checks`` say what it does to the prompt it replaces, as an edit's do.

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
    replaced, current = _current_prompt(req.context["form"], ws)
    check_drafted_prompt(content, current, req, edited=False, earlier=req.context["earlier"])
    checks = checks_for(current, content)
    if replaced in BUILTIN_PROMPTS:
        # A built-in reads as a template only once composed: plain text in its place keeps DocsGPT's sections.
        checks = [check for check in checks if check != CHECK_TO_PERSONA]
    return {"kind": "new", "name": name, "content": content, "checks": checks}


def _edited_prompt(raw: dict, req: DraftRequest, ws: Workspace) -> Optional[dict]:
    """Check edits to the editable prompt against the text the model read; None when they change nothing.

    Raises:
        ProposalInvalid: No editable prompt, another prompt's id, or edits the prompt recipe refuses (a find that
            isn't there once, overlaps, no reason, a text that doesn't parse, unasked tool variables).
    """
    form = req.context["form"]
    target = _editable_prompt(form, ws)
    if not target or str(raw.get("id") or "").strip() != target:
        raise ProposalInvalid([
            "Edits change only the agent's own prompt (prompt.editable in the form data): write a new prompt "
            "instead."
        ])
    _, current = _current_prompt(form, ws)
    edits, result = apply_edits(current, [e for e in raw.get("edits") or [] if isinstance(e, dict)])
    if not edits:
        return None
    check_drafted_prompt(result, current, req, edited=True, earlier=req.context["earlier"])
    # The edits fit the prompt's whole saved text (or the view's unsaved text), the text the form applies them to.
    return {"kind": "edit", "id": target, "edits": edits, "checks": checks_for(current, result)}


def _for_step(raw_fields: dict, step: Optional[str], dropped: list[dict], insights: bool = False) -> dict:
    """The proposal's fields the step may set: policy only in the safety step (guardrails also in improve mode
    with ``insights``), a new or edited prompt only in the prompt step or improve mode.

    A field a later step sets is left out quietly: the model drafted ahead and that step drafts it. One only a
    step already passed sets (a prompt in the safety step) is listed in ``dropped`` as
    ``{field, reason: "other_step", step}``, so the user knows why it didn't change.
    """
    out = {key: value for key, value in raw_fields.items()
           if step == "safety" or key not in SAFETY_FIELDS or (insights and not step and key == "guardrails")}
    prompt = out.get("prompt")
    if step not in (None, "prompt") and isinstance(prompt, dict) and prompt.get("kind") in ("new", "edit"):
        del out["prompt"]
        if STEPS.index(step) > STEPS.index("prompt"):
            dropped.append({"field": "prompt", "reason": "other_step", "step": "prompt"})
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


def _checks(raw: Any, form: dict, ws: AgentWorkspace) -> list[dict]:
    """The controls of the menu checks to add, ``{check, stage, action}``, in the model's order.

    A check is added when it is available here and not already on at every stage the menu gives it (an agent whose
    guardrails are off gets a check it has again, since adding it turns them on). Each brings all its menu
    controls: the form keeps one it already runs at that stage.
    """
    checks = raw.get("checks") if isinstance(raw, dict) else None
    guardrails = form["guardrails"]
    present = checks_on(guardrails) if guardrails["enabled"] else set()
    picked: list[str] = []
    for check in checks if isinstance(checks, list) else []:
        key = str(check).strip().lower()
        if key in ws.guardrail_menu and key not in present and key not in picked:
            picked.append(key)
    return [{"check": check, "stage": stage, "action": action}
            for check in picked for stage, action in GUARDRAIL_MENU[check]]


def _topics(raw: Any, form: dict, ws: AgentWorkspace, notes: list[str]) -> list[dict]:
    """The Insights topics to add, checked with the rules the agent's analytics config applies on save.

    A name the agent, one of its offered or cut source folders (or an earlier topic of the proposal) already has
    is left out.
    Topics that push folders out of the topic question add a note naming them.

    Raises:
        ProposalInvalid: Too many topics, a name or description the analytics config refuses, or more topics
            than the agent has room for.
    """
    items = raw.get("topics") if isinstance(raw, dict) else None
    items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    if len(items) > MAX_NEW_TOPICS:
        raise ProposalInvalid([f"Suggest at most {MAX_NEW_TOPICS} topics."])
    taken = set(_topic_view(form, ws).taken_names())
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
    instance or the agent has turned off is left out. What remains is accepted after a questions round, or
    without one when the user's own words state it (``safety_wording.stated``). A turn that skipped the questions
    sets only what the user's words state; the rest is left out.

    Raises:
        ProposalInvalid: Policy the user's words leave open, proposed before asking them, or a value the model can
            fix.
    """
    form = req.context["form"]
    available = {part: why is None for part, why in _safety_unavailable(form, ws).items()}
    wanted = []
    for key in SAFETY_FIELDS:
        if key not in raw_fields:
            continue
        if key != "analytics" and not ws.policy_editable:
            dropped.append({"field": key, "reason": "not_allowed"})
        elif available[key]:
            wanted.append(key)
    # What the user's words settle is never asked about: a part they declined is left out (a limit of "none"
    # excepted), and a value against what they said goes back once, unless a questions round has given them a say.
    settled = settled_parts(req)
    against = []
    for key in list(wanted):
        how = settled.get(key)
        if how == "declined" and not (key == "limits" and isinstance(raw_fields[key], dict)
                                      and raw_fields[key].get("mode") == "none"):
            wanted.remove(key)
        elif how == "stated" and not question_rounds(req.messages) and not stated(key, raw_fields[key], req):
            against.append(key)
    if against:
        if req.can_correct:
            raise ProposalInvalid([SETTLED_AGAINST.format(parts=", ".join(PART_NAMES[key] for key in against))])
        wanted = [key for key in wanted if key not in against]
    open_parts = [key for key in wanted if key not in settled and not stated(key, raw_fields[key], req)]
    if req.context.get("skip_questions"):
        # The user skipped the questions: only what their own words state is set. A message written for the parts
        # left open would claim them, so the model hears it once; with no correction left they are dropped.
        if open_parts and req.can_correct:
            parts = ", ".join(PART_NAMES[key] for key in open_parts)
            raise ProposalInvalid([SKIPPED_OPEN.format(parts=parts)])
        wanted = [key for key in wanted if key not in open_parts]
    elif open_parts and not question_rounds(req.messages):
        raise ProposalInvalid([ASK_FIRST.format(parts=", ".join(PART_NAMES[key] for key in open_parts))])
    if "limits" in wanted:
        fields["limits"] = _limits(raw_fields["limits"])
    if "guardrails" in wanted:
        controls = _checks(raw_fields["guardrails"], form, ws)
        if controls:
            fields["guardrails"] = {"controls": controls}
    if "analytics" in wanted:
        topics = _topics(raw_fields["analytics"], form, ws, notes)
        if topics:
            fields["analytics"] = {"topics": topics}


def _insights_guardrails(raw: Any, req: DraftRequest, ws: AgentWorkspace, fields: dict, dropped: list[dict]) -> None:
    """Check an improve proposal's guardrails into ``fields``: only :data:`INSIGHTS_CHECK`, only for an
    answer-not-backed gap in the summary, and only for a caller who may change the agent's policy (``dropped`` as
    ``not_allowed`` otherwise). The form runs it monitor-only unless the agent already enforces its guardrails."""
    if not ws.policy_editable:
        dropped.append({"field": "guardrails", "reason": "not_allowed"})
        return
    if not _insights_guardrail(req.context["form"], ws)["available"]:
        return
    controls = [c for c in _checks(raw, req.context["form"], ws) if c["check"] == INSIGHTS_CHECK]
    if controls:
        fields["guardrails"] = {"controls": controls}


def _gap_links(raw: Any, ws: AgentWorkspace, topics: set[str]) -> list[dict]:
    """A gap's links the server can name and open: workspace sources by id (named here) and Logs labels that
    exist; the rest are left out."""
    sources = {str(row["id"]): row for row in ws.sources}
    out: list[dict] = []
    for link in raw if isinstance(raw, list) else []:
        if not isinstance(link, dict) or len(out) >= MAX_GAP_LINKS:
            continue
        entry: Optional[dict] = None
        if link.get("kind") == "source":
            row = sources.get(str(link.get("id") or "").strip())
            entry = {"kind": "source", "id": str(row["id"]), "name": row["name"]} if row else None
        elif link.get("kind") == "logs":
            label = str(link.get("label") or "").strip()
            known = label in LOG_LABELS or (label.startswith(TOPIC_PREFIX) and label[len(TOPIC_PREFIX):] in topics)
            entry = {"kind": "logs", "label": label} if known else None
        if entry and entry not in out:
            out.append(entry)
    return out


def _gaps(raw: Any, fields: dict, ws: AgentWorkspace, focus: Optional[dict] = None,
          can_correct: bool = False) -> list[dict]:
    """The gaps an improve proposal acts on, each matched to its summary row, whose counts the server fills in.

    A gap's ``fields`` keep only the proposal's fields; an agent without topics takes any topic as none. A gap sent
    without a topic is the focus gap's when it has that gap type, or else the only row of its type. A gap that
    matches no row goes back once, naming the rows it may use (:func:`_unmatched_gap`); with no correction left it
    is left out: the card can't show counts, and the rest of the proposal still stands.

    Args:
        raw: The model's ``gaps``.
        fields: The proposal's checked fields.
        ws: The workspace with the gap summary.
        focus: The gap the user started from (the context's ``gap``), or None.
        can_correct: Whether the turn's corrected try is still left.

    Raises:
        ProposalInvalid: A gap that matches no row of the summary, while a correction is left.
    """
    # Matched as the model read them (cleaned); the row keeps the topic as stored, which Logs filters on.
    rows = {(_gap_topic(row["topic"]), row["gap_type"]): row for row in ws.gaps["rows"]}
    by_topic = any(topic is not None for topic, _ in rows)
    topics = {row["topic"] for row in ws.gaps["rows"] if row["topic"] is not None}
    out: list[dict] = []
    problems: list[str] = []
    for item in [i for i in raw if isinstance(i, dict)] if isinstance(raw, list) else []:
        if len(out) >= MAX_GAPS:
            break
        topic = _gap_topic(item.get("topic")) if by_topic else None
        gap_type = item.get("gap_type")
        # A gap the user started from a page or source row is that row, whatever topic the model put on it.
        focus_row = ws.focus_row if ws.focus_row and ws.focus_row["gap_type"] == gap_type else None
        row = focus_row or rows.get((topic, gap_type))
        if row is None and by_topic and topic is None:
            if focus and focus.get("gap_type") == gap_type:
                row = rows.get((focus.get("topic"), gap_type))
            same = [r for (_, kind), r in rows.items() if kind == gap_type]
            row = row or (same[0] if len(same) == 1 else None)
        if row is None:
            if can_correct:
                problems.append(_unmatched_gap(gap_type, topic, by_topic, ws.gaps["rows"]))
            else:
                logger.info("drafter: left out a gap card not in the summary: %r in %r", gap_type, topic)
            continue
        if any(g["topic"] == row["topic"] and g["gap_type"] == row["gap_type"] for g in out):
            continue
        listed = item.get("fields") if isinstance(item.get("fields"), list) else []
        out.append({
            **{key: row[key] for key in ("topic", "gap_type", "expected", "turns", "previous", "group_by",
                                         "group_key") if key in row},
            "example": clean_text(" ".join(str(item.get("example") or "").split()), GAP_EXAMPLE_MAX) or None,
            "fields": [name for name in dict.fromkeys(listed) if isinstance(name, str) and name in fields],
            "needs": clean_text(item.get("needs"), GAP_NEEDS_MAX) or None,
            "links": _gap_links(item.get("links"), ws, topics),
        })
    if problems:
        raise ProposalInvalid(problems[:MAX_GAPS])
    return out


#: Rows an unmatched gap's correction names at most.
_NAMED_ROWS = 8


def _unmatched_gap(gap_type: Any, topic: Optional[str], by_topic: bool, rows: list[dict]) -> str:
    """The correction for a gap that matches no summary row: the rows of its gap type it may use (all rows when
    none has that type), each as its topic and gap type.

    Args:
        gap_type: The gap type the model sent.
        topic: The topic the model sent, cleaned; None when it sent none or the agent sorts no topics.
        by_topic: Whether the summary's rows have topics.
        rows: The summary's rows.
    """
    kind = str(gap_type)[:60]
    same = [row for row in rows if row["gap_type"] == gap_type] or rows
    named = ", ".join(f'"{row["topic"]}" ({row["gap_type"]})' if row["topic"] is not None
                      else f'no topic ({row["gap_type"]})' for row in same[:_NAMED_ROWS])
    where = f" in {topic!r}" if topic else " with no topic" if by_topic else ""
    return (f"Gap {kind!r}{where} is not a row of the gap summary. Give each gap a topic and gap_type exactly as "
            f"one row has them ({named}), or leave that gap out.")


def _drafted_ahead(step: str, fields: dict, form: dict) -> bool:
    """Whether a proposal from an earlier step drafted what ``step`` is for, so the build may pass over it.

    Knowledge needs sources or tools (a type alone leaves them to pick); the prompt step a prompt with starters,
    drafted or already on the form (a prompt alone leaves them to write, starters alone the prompt). Safety is
    never drafted ahead.
    """
    if step == "knowledge":
        return "sources" in fields or "tools" in fields
    if step == "prompt":
        return "prompt" in fields and bool(fields.get("starters") or form["starters"])
    return False


def _progress(step: Optional[str], fields: dict, form: dict) -> tuple[list[str], Optional[str]]:
    """The steps a proposal fills (the current one and the later ones it drafted ahead) and the next step to run.

    Args:
        step: The current step; None in improve mode.
        fields: The proposal's checked fields, unchanged ones left out.
        form: The form's values.

    Returns:
        ``(steps, next_step)``: empty and None in improve mode.
    """
    if step is None:
        return [], None
    later = STEPS[STEPS.index(step) + 1:]
    filled = [step] + [s for s in later if _drafted_ahead(s, fields, form)]
    return filled, next((s for s in later if s not in filled), None)


def validate(args: dict, req: DraftRequest, ws: Workspace) -> dict:
    """Turn ``submit_proposal`` arguments into the agent ``proposal`` payload.

    Unknown fields, and fields the step may not set, are left out. Ids the
    caller can't attach, policy they may not change, and a prompt only a step
    already passed sets are dropped and listed in ``dropped``. A field equal to the form's value is left out, so the form
    marks only real changes. ``steps`` and ``next_step`` say where the guided
    build goes next (empty and None in improve mode). Improve mode adds
    ``gaps``, the Insights gaps the proposal acts on (empty without Insights).

    Raises:
        ProposalInvalid: A value the model can fix (length, empty name, starters, prompt rules, limits, topics,
            or policy proposed before asking the user.
    """
    from docsgpt.api.user.agents.starters import normalize_starters, StartersError

    step = req.context["step"]
    form = req.context["form"]
    insights = not step and isinstance(ws, AgentWorkspace) and ws.reads_insights()
    fields: dict[str, Any] = {}
    dropped: list[dict] = []
    raw_fields = _for_step(args.get("fields") or {}, step, dropped, insights)
    # The model's notes, and the server's own (folders pushed out), which go last and always fit the cap.
    notes = [clean_text(n, NOTE_MAX) for n in args.get("notes") or [] if clean_text(n, NOTE_MAX)]
    server_notes: list[str] = []
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
    for kind in ("sources", "tools"):
        if kind in raw_fields:
            refs = _refs(kind, raw_fields[kind], ws.ids(kind) | set(form[kind]), form[kind], dropped)
            if refs is not None:
                fields[kind] = refs
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
            fields["prompt"] = _new_prompt(prompt, req, ws)
        elif prompt.get("kind") == "edit":
            edited = _edited_prompt(prompt, req, ws)
            if edited:
                fields["prompt"] = edited
        else:
            prompt_id = str(prompt.get("id") or "").strip()
            allowed = ws.ids("prompts") | ({form["prompt_id"]} if form.get("prompt_id") else set())
            if prompt_id in allowed or prompt_id in BUILTIN_PROMPTS:
                fields["prompt"] = {"kind": "existing", "id": prompt_id}
            else:
                dropped.append({"field": "prompt", "id": prompt_id[:ID_CHARS], "reason": "not_found"})
    if step == "safety":
        _policy(raw_fields, req, ws, fields, dropped, server_notes)
    elif insights and "guardrails" in raw_fields:
        _insights_guardrails(raw_fields["guardrails"], req, ws, fields, dropped)
    notes = notes[:max(0, MAX_NOTES - len(server_notes))] + server_notes[:MAX_NOTES]

    _drop_unchanged(fields, form)
    gaps = _gaps(args.get("gaps"), fields, ws, req.context.get("gap"), req.can_correct) if insights else []
    reasons = []
    for reason in args.get("reasons") or []:
        if reason.get("field") not in fields or any(r["field"] == reason["field"] for r in reasons):
            continue
        summary = clean_text(reason.get("summary"), REASON_SUMMARY_MAX)
        if not summary:
            continue
        # Only the summary shows in the panel: a detail a model still sends is dropped.
        reasons.append({"field": reason["field"], "summary": summary})
    message = clean_text(args.get("message"), MESSAGE_MAX)
    if step and req.can_correct:
        unbacked = unbacked_claims(message, step, fields, form)
        if unbacked:
            raise ProposalInvalid([CLAIMS_UNSET.format(parts=", ".join(unbacked))])
    steps, next_step = _progress(step, fields, form)
    proposal = {
        "message": message,
        "fields": fields,
        "reasons": reasons[:MAX_REASONS],
        "notes": notes,
        "dropped": dropped,
        "steps": steps,
        "next_step": next_step,
    }
    if not step:
        proposal["gaps"] = gaps
    return proposal


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


#: The read tools every turn offers, and those only an improve turn with the agent's gap summary does.
WORKSPACE_READS = ("get_prompt", "get_source", "get_tool")
INSIGHTS_READS = ("get_gap_examples", "get_conversations")


def asks(req: DraftRequest) -> bool:
    """Every turn may ask questions, except one the user sent with Skip on the questions."""
    return not req.context.get("skip_questions")


def read_tools_for(req: DraftRequest, ws: Workspace) -> tuple[str, ...]:
    """The read tools a turn offers: the Insights reads only in improve mode with the agent's gap summary."""
    reader = isinstance(ws, AgentWorkspace) and ws.reads_insights() and ws.insights_reader is not None
    return WORKSPACE_READS + INSIGHTS_READS if reader and not req.context["step"] else WORKSPACE_READS


AGENT_RECIPE = register(Recipe(
    id="agent",
    parse_context=parse_context,
    load_workspace=_load,
    instructions=instructions,
    context_data=context_data,
    proposal_schema=PROPOSAL_SCHEMA,
    validate=validate,
    read_tools=WORKSPACE_READS + INSIGHTS_READS,
    tools_for=read_tools_for,
    proposal_description="Fill the agent form with your draft. Ends your turn.",
    questions=asks,
    check_questions=check_questions,
))
