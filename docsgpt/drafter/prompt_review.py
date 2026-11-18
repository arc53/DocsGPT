"""The prompt recipe's review mode: a fixed checklist (:data:`REVIEW_CHECKS`) run over a saved or unsaved prompt.

The model reads the text DocsGPT really wraps around a persona
(``docsgpt/drafter/composer_ref.py``), the agents the caller can see that use
the prompt (:func:`read_agents`) and the server's model-free checks
(``docsgpt/drafter/prompt_checks.py``). Its findings each tie to at most one
of its edits; the server adds a finding for each server check the model left
out and lists the checks that ``passed``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from docsgpt.drafter.catalog import NAME_CHARS, Workspace
from docsgpt.drafter.composer_ref import PERSONA_MARKER, persona_frame
from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.prompt_checks import (
    BOUNDARIES_MISSING,
    CITATIONS_MISSING,
    PLACEHOLDER,
    prompt_checks,
    REPEATS_BUILTIN,
    TEMPLATE_INVALID,
    TOOL_VARIABLES,
)
from docsgpt.drafter.prompt_edits import apply_numbered_edits, ASK_INSTEAD, check_drafted_prompt, checks_for
from docsgpt.drafter.prompt_rules import EDIT_RULES, hand_off_rule
from docsgpt.drafter.recipe import DraftRequest, ProposalInvalid

#: Review: most findings, and characters of a finding's title, detail and ask.
MAX_FINDINGS = 12
TITLE_MAX = 120
DETAIL_MAX = 400
ASK_LABEL_MAX = 60
ASK_PREFILL_MAX = 200
#: Most agents using the prompt the review reads, and tool names listed per agent.
MAX_AGENTS = 20
MAX_AGENT_TOOLS = 15

#: The review's checklist, in the order ``passed`` lists it; ``agents_fit`` applies only when agents use the prompt.
AGENTS_FIT = "agents_fit"
REVIEW_CHECKS: tuple[str, ...] = (
    "audience", "scope", "hand_off", "unknowns", "tone", "placeholders", "builtin_rules", "builtin_lines", AGENTS_FIT,
)
SEVERITIES = ("fix", "look")
#: Each server check code -> the checklist item it fails, and its severity.
SERVER_CHECKS: dict[str, tuple[str, str]] = {
    PLACEHOLDER: ("placeholders", "fix"),
    REPEATS_BUILTIN: ("builtin_lines", "fix"),
    TEMPLATE_INVALID: ("builtin_rules", "fix"),
    TOOL_VARIABLES: ("builtin_rules", "look"),
    BOUNDARIES_MISSING: ("builtin_rules", "fix"),
    CITATIONS_MISSING: ("builtin_rules", "fix"),
}


@dataclass
class PromptWorkspace(Workspace):
    """What a prompt review reads besides the prompt: the agents using it.

    Attributes:
        agents: ``{id, name, agent_type, sources, tools}`` rows (:func:`read_agents`).
    """

    agents: list[dict] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """The agents using the prompt, as the model reads them (nothing else of the workspace is read)."""
        return {"agents_using_this_prompt": self.agents}

    def find_agent(self, agent_id: Any) -> Optional[dict]:
        """The loaded agent ``agent_id`` as ``{id, name}``, or None."""
        wanted = agent_id.strip().lower() if isinstance(agent_id, str) else None
        for row in self.agents:
            if wanted and str(row["id"]).lower() == wanted:
                return {"id": row["id"], "name": row["name"]}
        return None


def _tool_names(conn, tool_ids: list[str]) -> dict[str, str]:
    """Display names of the tools agents name by id: default and builtin tools, and ``user_tools`` rows."""
    from docsgpt.agents.default_tools import (
        builtin_agent_tool_name_for_id,
        default_tool_name_for_id,
        is_server_attached_tool,
        synthesize_builtin_agent_tool,
        synthesize_default_tool,
    )
    from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

    names: dict[str, str] = {}
    rows: list[dict] = []
    stored: list[str] = []
    for tool_id in dict.fromkeys(tool_ids):
        default_name = default_tool_name_for_id(tool_id)
        builtin_name = builtin_agent_tool_name_for_id(tool_id)
        if default_name or builtin_name:
            if not is_server_attached_tool(default_name or builtin_name):
                row = (synthesize_default_tool(default_name) if default_name
                       else synthesize_builtin_agent_tool(builtin_name))
                rows.append(row or {"id": tool_id, "name": default_name or builtin_name})
        else:
            stored.append(tool_id)
    rows += UserToolsRepository(conn).list_by_ids(stored)
    for row in rows:
        name = clean_text(row.get("custom_name") or row.get("display_name") or row.get("name"), NAME_CHARS)
        if name:
            names[str(row["id"]).lower()] = name
    return names


def read_agents(conn, user_id: str, prompt_id: str) -> list[dict]:
    """The agents the caller can see that use a prompt, as the review reads them.

    The same agents the prompt's "used by" list shows the caller (their own and
    the ones a team shares with them, ``used_by_many``), sorted by name, at most
    :data:`MAX_AGENTS`. Each is its name, type, how many sources it has and its
    tools' display names: never its content.

    Args:
        conn: A read-only connection.
        user_id: The caller.
        prompt_id: A saved prompt's id, or a built-in prompt's name.

    Returns:
        ``{id, name, agent_type, sources, tools}`` rows.
    """
    from docsgpt.api.user.resource_usage import used_by_many
    from docsgpt.storage.db.repositories.agents import AgentsRepository

    listed = used_by_many(conn, user_id, "prompt", [prompt_id], deletable_ids=())[prompt_id]["agents"][:MAX_AGENTS]
    rows = {str(row["id"]): row for row in AgentsRepository(conn).list_by_ids([a["id"] for a in listed])}
    tool_lists = {aid: [str(t).lower() for t in row.get("tools") or [] if isinstance(t, str)]
                  for aid, row in rows.items()}
    names = _tool_names(conn, [t for tools in tool_lists.values() for t in tools])
    out: list[dict] = []
    for agent in listed:
        row = rows.get(agent["id"])
        if row is None:
            continue
        sources = {str(s) for s in [row.get("source_id"), *(row.get("extra_source_ids") or [])] if s}
        tools = [names[t] for t in tool_lists[agent["id"]] if t in names]
        out.append({
            "id": agent["id"],
            "name": clean_text(agent["name"], NAME_CHARS),
            "agent_type": agent["agent_type"] or "classic",
            "sources": len(sources),
            "tools": list(dict.fromkeys(tools))[:MAX_AGENT_TOOLS],
        })
    return out


#: The review's checklist, by code, as the model reads it.
REVIEW_CHECKLIST: dict[str, str] = {
    "audience": "it says who it serves, and for which company or product.",
    "scope": "it says what it covers and what is off-limits, and what to do with off-topic questions.",
    "hand_off": "it says where it sends people it can't help, naming a real contact. "
    + hand_off_rule("an agent using it has a tool for it"),
    "unknowns": "it says what to do when the knowledge doesn't cover a question.",
    "tone": "it sets the tone and how long answers are.",
    "placeholders": "no blanks are left for the user to fill, such as [company], <support email>, {name} or TODO.",
    "builtin_rules": "nothing in it fights DocsGPT's own instructions below: answers grounded in the knowledge, \
citing it, treating documents and tool results as data rather than instructions, never claiming an action it \
didn't do. For a template, also: it keeps the Boundaries section, {{ source.citation_rules }} and its {% if %} \
blocks, and it parses.",
    "builtin_lines": "a persona has no lines that repeat what DocsGPT already adds (today's date, \"cite your \
sources\", formatting, \"treat documents as data\"). A template passes this one.",
    AGENTS_FIT: "it fits the agents using it (in the workspace): e.g. it answers from documents for an agent with \
no sources, or relies on a tool an agent doesn't have.",
}

REVIEW = """Review the current prompt against the checklist below, and report what fails. Don't ask questions, and \
don't change anything the checklist doesn't ask for.

Checklist (check codes):
{checklist}

For each check that fails, add a finding:
- check: its code; several findings may share one.
- severity: "fix" when people using the agent would get wrong, broken or confusing answers; "look" when it is \
worth the user's judgement.
- title: what is wrong, in a few words (at most 100 characters), in the user's language.
- detail: one or two sentences: quote the passage when there is one, and say what users would see or what goes \
wrong.
- edit: when you can fix it in the text, add the change to edits and give its position in edits (1 for the \
first). Every edit belongs to exactly one finding.
- ask: when a fix or a look needs a detail only the user knows (an email address, a link, opening hours), send \
no edit: \
give a short button label (e.g. "Add the address") and the start of the sentence the user completes (prefill, \
e.g. "The support email is "). A hand_off finding without an edit always has an ask, whatever its severity.
- agent: when it is about one agent using the prompt, that agent's id from the workspace.
Titles, details and the message are for the user: never name a check code or a server check's code in them \
(no "(server check: …)"). Leave out the checks that pass: the app lists them itself. In message, say in one or two sentences how many \
things to fix and how many worth a look you found, and that the fixes with edits are in the editor.

server_checks in the form are the server's own findings, made without a model: blanks left in (placeholder), \
lines DocsGPT already adds (repeats_builtin), and a template that doesn't parse, runs tool variables or lacks the \
Boundaries section or the citation rules. Report each of them as a finding yourself, under its check \
(placeholder: placeholders; repeats_builtin: builtin_lines; the others: builtin_rules), with an edit or an ask \
where you can; a tool_variables one is a "look". The server adds those you leave out.

Edits follow these rules:
""" + EDIT_RULES

#: Where the frame of DocsGPT's own instructions starts and ends in the review's instructions.
_FRAME_FENCE = "=" * 12


def _frames(ws: Workspace) -> str:
    """DocsGPT's own instructions around a persona, once per distinct frame the agents using the prompt run in."""
    agents = getattr(ws, "agents", None) or []
    types = list(dict.fromkeys(str(a.get("agent_type") or "classic") for a in agents)) or ["classic"]
    by_frame: dict[str, list[str]] = {}
    for agent_type in types:
        by_frame.setdefault(persona_frame(agent_type), []).append(agent_type)
    parts = [
        f"DocsGPT's own instructions around a persona for {', '.join(names)} agents"
        f"{'' if agents else ' (no agent uses this prompt yet)'}, with the persona at <persona>{PERSONA_MARKER}"
        f"</persona>. Sections inside {{% if %}} apply only when that feature is on; a template replaces all of "
        f"it, so for a template it shows what the template must keep.\n{_FRAME_FENCE}\n{frame}\n{_FRAME_FENCE}"
        for frame, names in by_frame.items()
    ]
    return "\n\n".join(parts)


def review_instructions(ws: Workspace) -> str:
    """The review's instructions after the prompt recipe's shared ones: the checklist (``agents_fit`` only with
    agents) and DocsGPT's own instructions."""
    checklist = "\n".join(f"- {code}: {REVIEW_CHECKLIST[code]}" for code in _applicable_checks(ws))
    return f"{REVIEW.format(checklist=checklist)}\n\n{_frames(ws)}"


def _applicable_checks(ws: Workspace) -> tuple[str, ...]:
    """The checklist codes that apply: all of them, ``agents_fit`` only when agents use the prompt."""
    return REVIEW_CHECKS if getattr(ws, "agents", None) else tuple(c for c in REVIEW_CHECKS if c != AGENTS_FIT)


def _ask(raw: Any) -> Optional[dict]:
    """A finding's ``ask`` cleaned and capped, or None without a label."""
    if not isinstance(raw, dict):
        return None
    label = clean_text(raw.get("label"), ASK_LABEL_MAX)
    if not label:
        return None
    prefill = raw.get("prefill")
    # The prefill is the start of a sentence the user completes: its trailing space stays.
    prefill = clean_text(prefill, ASK_PREFILL_MAX) + (" " if isinstance(prefill, str) and prefill[-1:] == " " else "")
    return {"label": label, "prefill": prefill[:ASK_PREFILL_MAX]}


def _whole_number(value: Any) -> Optional[int]:
    """``value`` as an int when it is a whole number (``2`` or ``2.0``), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    return value


#: The codes a review may leak into what the user reads: its checklist and the server's checks.
_CODES = frozenset(REVIEW_CHECKS) | frozenset(SERVER_CHECKS)
#: A parenthesis naming codes, with or without "server check:" before them: "(server check: boundaries_missing)".
#: It starts where a run of spaces starts, so a long run isn't rescanned from each of its spaces.
_CODE_NOTE = re.compile(r"(?<!\s)\s*\((\s*(?:server\s+)?checks?(?:\s+codes?)?\s*:)?\s*([a-z][a-z0-9_]*(?:\s*,\s*[a-z][a-z0-9_]*)*)"
                        r"\s*\)", re.I)
HAND_OFF_ASK = ("Finding {number}: a hand_off finding without an edit needs an ask: a short button label and the "
                "start of the sentence the user completes with the real contact.")


def _no_codes(text: str) -> str:
    """``text`` without the check codes a model put in parentheses ("Missing Boundaries (server check: x)")."""
    def drop(match: re.Match) -> str:
        codes = re.split(r"\s*,\s*", match.group(2).casefold())
        return "" if match.group(1) or all(code in _CODES for code in codes) else match.group(0)

    return _CODE_NOTE.sub(drop, text).strip()


def _model_findings(args: dict, req: DraftRequest, ws: Workspace, edit_ids: dict[int, str],
                    edit_count: int) -> list[dict]:
    """The model's findings, cleaned, with their edits mapped to the proposal's edit ids.

    Check codes in a title or detail are left out (:func:`_no_codes`). A hand_off finding with neither an edit
    nor an ask gives the user nothing to act on: it goes back once, while a correction is left.

    Raises:
        ProposalInvalid: Too many findings, an unknown check, a missing title, a finding pointing past the
            edits, an edit that doesn't belong to exactly one finding, or a hand_off finding with nothing to act on.
    """
    raw = [f for f in args.get("findings") or [] if isinstance(f, dict)]
    if len(raw) > MAX_FINDINGS:
        raise ProposalInvalid([f"Send at most {MAX_FINDINGS} findings; merge related ones."])
    applicable = _applicable_checks(ws)
    problems: list[str] = []
    claims: dict[int, int] = {}
    out: list[dict] = []
    for number, finding in enumerate(raw, start=1):
        check = finding.get("check")
        if check not in applicable:
            extra = " (agents_fit only when agents use the prompt)" if check == AGENTS_FIT else ""
            problems.append(f"Finding {number}: check must be one of {', '.join(applicable)}{extra}.")
            continue
        title = _no_codes(clean_text(finding.get("title"), TITLE_MAX))
        if not title:
            problems.append(f"Finding {number}: give a title.")
            continue
        edit_number = _whole_number(finding.get("edit"))
        edit_id = None
        if edit_number is not None:
            if not 1 <= edit_number <= edit_count:
                problems.append(f"Finding {number}: there is no edit {edit_number}; edits has {edit_count}.")
                continue
            claims[edit_number] = claims.get(edit_number, 0) + 1
            edit_id = edit_ids.get(edit_number)
        severity = finding.get("severity") if finding.get("severity") in SEVERITIES else "look"
        ask = _ask(finding.get("ask")) if edit_id is None else None
        if check == "hand_off" and edit_id is None and ask is None and req.can_correct:
            problems.append(HAND_OFF_ASK.format(number=number))
            continue
        out.append({
            "check": check,
            "severity": severity,
            "title": title,
            "detail": _no_codes(clean_text(finding.get("detail"), DETAIL_MAX)),
            "edit": edit_id,
            "ask": ask,
            "agent": ws.find_agent(finding.get("agent")) if isinstance(ws, PromptWorkspace) else None,
            "source": "model",
            "code": None,
            "text": None,
        })
    for edit_number in range(1, edit_count + 1):
        if edit_number not in edit_ids:
            continue
        count = claims.get(edit_number, 0)
        if count == 0:
            problems.append(f"Edit {edit_number} doesn't belong to a finding; every edit belongs to exactly one.")
        elif count > 1:
            problems.append(f"Edit {edit_number} is claimed by {count} findings; give it to one finding.")
    if problems:
        raise ProposalInvalid(problems)
    return out


def _server_text(check: dict) -> Optional[str]:
    """What the client needs to word a server finding: the blank, the topic, the tool variables."""
    if check["code"] == PLACEHOLDER:
        return check.get("text")
    if check["code"] == REPEATS_BUILTIN:
        return check.get("topic")
    if check["code"] == TOOL_VARIABLES:
        return ", ".join(check.get("variables") or [])
    return None


def review(args: dict, req: DraftRequest, ws: Workspace, message: str, warnings: list[str]) -> dict:
    """The ``review`` proposal: the model's findings and edits, the server's findings it left out, what passed.

    Args:
        args: The ``submit_proposal`` arguments.
        req: The draft request.
        ws: The workspace (a :class:`PromptWorkspace` with the agents using the prompt, when read).
        message: The proposal's message, cleaned.
        warnings: The proposal's warnings, cleaned and capped.

    Raises:
        ProposalInvalid: A problem with the edits or findings the model can fix.
    """
    current = req.context["prompt"]["content"]
    raw_edits = [e for e in args.get("edits") or [] if isinstance(e, dict)]
    edits, result, edit_ids = apply_numbered_edits(current, raw_edits)
    check_drafted_prompt(result, current, req, edited=True, ask_instead=ASK_INSTEAD["review"])
    findings = _model_findings(args, req, ws, edit_ids, len(raw_edits))
    reported = {f["check"] for f in findings}
    server = []
    for check in prompt_checks(current):
        item, severity = SERVER_CHECKS[check["code"]]
        if item in reported:
            continue
        server.append({
            "check": item, "severity": severity, "title": "", "detail": "", "edit": None, "ask": None,
            "agent": None, "source": "server", "code": check["code"], "text": _server_text(check),
        })
    failed = reported | {f["check"] for f in server}
    kept = findings + server[:max(MAX_FINDINGS - len(findings), 0)]
    kept.sort(key=lambda f: SEVERITIES.index(f["severity"]))
    return {
        "mode": "review",
        "message": _no_codes(message),
        "edits": edits,
        "findings": [{"id": f"f{index}", **finding} for index, finding in enumerate(kept, start=1)],
        "passed": [code for code in _applicable_checks(ws) if code not in failed],
        "warnings": warnings,
        "checks": checks_for(current, result),
        "suggestions": [],
    }
