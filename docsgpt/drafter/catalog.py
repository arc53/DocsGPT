"""What the drafter may read: the caller's workspace, as the agent form's pickers offer it.

Read-only and scoped to the caller. Sources, tools and prompts are the
caller's own plus the ones shared with their teams that they may put on their
own agents (``use`` on a source or prompt, ``use_in_own`` on a tool), the same
rule ``ref_attachable`` applies when an agent is saved. Default and builtin
tools are offered as the agent picker offers them. Nothing here writes: the
list routes are not called because some of them have side effects (the agents
listing upserts the user row).

Everything is loaded once, before the draft streams, so the read tools are
plain lookups and the stream never touches the database. Tool configs and
secrets are never read into it: a tool is its name, description and actions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from docsgpt.drafter.fencing import clean_text

logger = logging.getLogger(__name__)

#: Most rows of each kind the drafter reads; the rest are counted, not shown.
MAX_SOURCES = 100
MAX_TOOLS = 60
MAX_PROMPTS = 50
MAX_MODELS = 30
#: Most actions listed per tool, and characters of one action description.
MAX_ACTIONS = 30
ACTION_DESCRIPTION_CHARS = 300
#: Characters of a name, a tool or prompt description, a prompt's preview and full text.
NAME_CHARS = 120
DESCRIPTION_CHARS = 300
PREVIEW_CHARS = 160
PROMPT_CHARS = 12000
#: File paths a source lists for ``get_source``.
MAX_SOURCE_FILES = 50

#: Built-in prompts, by id, with what tells them apart.
PRESET_PROMPTS: dict[str, str] = {
    "default": "Built-in. Answers from the knowledge, falls back to general knowledge and says so.",
    "creative": "Built-in. Like default, and offers ideas, examples and imaginative angles.",
    "strict": "Built-in. Answers only from the knowledge and tools; says what is missing instead of guessing.",
}


@dataclass
class Workspace:
    """The caller's workspace as the drafter sees it.

    Attributes:
        sources: Compact source rows ``{id, name, type, files?, shared?, status?}``.
        tools: Compact tool rows ``{id, name, kind, description?, actions: [{name, description?}]}``.
        prompts: Compact prompt rows ``{id, name, kind, preview?, template?}``.
        models: ``{id, name}`` rows of the models the caller can pick.
        agent: The saved agent being edited ``{id, name, status, agent_type}``, or None.
        policy_editable: Whether the caller may change the agent's guardrails and limits (``edit_policy``, the
            rule the agent update route applies); True for a new agent, which the caller will own.
        prompt_texts: Prompt id -> full text (capped), for ``get_prompt``.
        source_files: Source id -> file paths (capped), for ``get_source``.
        tool_details: Tool id -> actions with full descriptions, for ``get_tool``.
        hidden: Kind -> rows left out over the caps.
        over_cap: Kind -> ids of the rows left out over the caps: not shown to the model, still the caller's.
        own_prompts: Ids of all the caller's own prompts, those over the cap too.
    """

    sources: list[dict] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    prompts: list[dict] = field(default_factory=list)
    models: list[dict] = field(default_factory=list)
    agent: Optional[dict] = None
    policy_editable: bool = True
    prompt_texts: dict[str, str] = field(default_factory=dict)
    source_files: dict[str, list[str]] = field(default_factory=dict)
    tool_details: dict[str, dict] = field(default_factory=dict)
    hidden: dict[str, int] = field(default_factory=dict)
    over_cap: dict[str, set[str]] = field(default_factory=dict)
    own_prompts: set[str] = field(default_factory=set)

    def counts(self) -> dict[str, int]:
        """How many of each kind the drafter looked at (the ``reading`` status event)."""
        return {
            "sources": len(self.sources) + self.hidden.get("sources", 0),
            "tools": len(self.tools) + self.hidden.get("tools", 0),
            "prompts": len(self.prompts) + self.hidden.get("prompts", 0),
            "models": len(self.models) + self.hidden.get("models", 0),
        }

    def ids(self, kind: str) -> set[str]:
        """The ids of one kind (``sources``, ``tools``, ``prompts``) the caller may attach, those over the cap too."""
        return {str(row["id"]) for row in getattr(self, kind)} | self.over_cap.get(kind, set())

    def summary(self) -> dict[str, Any]:
        """The compact catalog that goes into the prompt."""
        out: dict[str, Any] = {
            "sources": self.sources,
            "tools": self.tools,
            "prompts": self.prompts,
            "models": self.models,
        }
        if self.agent:
            out["agent_being_edited"] = self.agent
        if self.hidden:
            out["not_shown"] = dict(self.hidden)
        return out


def _cap(rows: list, limit: int, kind: str, ws: Workspace) -> list:
    """The first ``limit`` rows; how many were left out is counted in ``ws.hidden[kind]``, their ids kept in
    ``ws.over_cap[kind]``."""
    if len(rows) > limit:
        ws.hidden[kind] = len(rows) - limit
        ws.over_cap[kind] = {str(row["id"]) for row in rows[limit:]}
        return rows[:limit]
    return rows


def _attachable(resource_type: str, access: Optional[str], switches: Optional[dict]) -> bool:
    """Whether the caller's access to a resource (and its sharing switches) lets them attach it to an agent."""
    from docsgpt.api.user.resource_access import REF_USE_ACTION, allowed_actions

    return REF_USE_ACTION[resource_type] in allowed_actions(resource_type, access, switches)


def _file_paths(structure: Any) -> list[str]:
    """File paths of a ``directory_structure`` tree, in stored order, capped."""
    from docsgpt.parser.remote.website_tree import tree_leaves

    try:
        leaves = tree_leaves(structure)
    except Exception:
        return []
    return [clean_text(path, 200) for path, _ in leaves[:MAX_SOURCE_FILES]]


def load_sources(conn, user_id: str, ws: Workspace) -> None:
    """Fill ``ws.sources``: the caller's own sources and the team-shared ones they may use."""
    from docsgpt.api.user.resource_access import settings_many
    from docsgpt.api.user.team_sharing import visible_with_access
    from docsgpt.parser.remote.website_tree import count_pages
    from docsgpt.storage.db.repositories.sources import SourcesRepository

    team = visible_with_access(conn, user_id, "source")
    rows = SourcesRepository(conn).list_for_user(user_id, extra_ids=list(team))
    shared_ids = [str(r["id"]) for r in rows if str(r.get("user_id")) != str(user_id)]
    switches = settings_many(conn, "source", shared_ids)
    out: list[dict] = []
    for row in rows:
        sid = str(row["id"])
        shared = str(row.get("user_id")) != str(user_id)
        if shared and not _attachable("source", team.get(sid), switches.get(sid)):
            continue
        entry: dict[str, Any] = {"id": sid, "name": clean_text(row.get("name"), NAME_CHARS)}
        if row.get("type"):
            entry["type"] = clean_text(str(row.get("type")), 40)
        structure = row.get("directory_structure")
        if isinstance(structure, dict) and structure:
            entry["files"] = count_pages(structure)
            ws.source_files[sid] = _file_paths(structure)
        if shared:
            entry["shared"] = True
        if row.get("ingest_status"):
            entry["status"] = str(row.get("ingest_status"))
        out.append(entry)
    ws.sources = _cap(out, MAX_SOURCES, "sources", ws)


def _injection_flagged(action: dict) -> bool:
    """Whether an MCP action's text was scored as a likely prompt injection."""
    from docsgpt.guardrails.checks.model_injection import FLAG_THRESHOLD

    score = action.get("injection")
    if not isinstance(score, dict):
        return False
    try:
        return float(score.get("p")) >= FLAG_THRESHOLD
    except (TypeError, ValueError):
        return False


def _tool_actions(row: dict) -> list[dict]:
    """A tool's active actions as ``{name, description?, parameters?}``; never a URL, header or value."""
    raw = row.get("actions") or []
    if row.get("name") == "api_tool":
        config_actions = (row.get("config") or {}).get("actions")
        if isinstance(config_actions, dict):
            raw = list(config_actions.values())
    out: list[dict] = []
    for action in raw if isinstance(raw, list) else []:
        if not isinstance(action, dict) or action.get("active") is False:
            continue
        name = clean_text(action.get("name"), 80)
        if not name:
            continue
        item: dict[str, Any] = {"name": name}
        if _injection_flagged(action):
            item["description_withheld"] = True
        else:
            description = clean_text(action.get("description"), ACTION_DESCRIPTION_CHARS)
            if description:
                item["description"] = description
            params = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
            props = params.get("properties") if isinstance(params.get("properties"), dict) else {}
            names = [clean_text(str(p), 60) for p, spec in props.items()
                     if not isinstance(spec, dict) or spec.get("filled_by_llm", True) is not False]
            if names:
                item["parameters"] = names[:15]
        out.append(item)
        if len(out) >= MAX_ACTIONS:
            break
    return out


def _tool_entry(row: dict, *, shared: bool = False, kind: Optional[str] = None) -> dict:
    """A tool's catalog row: id, cleaned name and kind (``kind`` or the tool's type), description, shared flag."""
    name = clean_text(row.get("custom_name") or row.get("display_name") or row.get("name"), NAME_CHARS)
    entry: dict[str, Any] = {"id": str(row["id"]), "name": name, "kind": kind or clean_text(row.get("name"), 40)}
    description = clean_text(row.get("description"), DESCRIPTION_CHARS)
    if description:
        entry["description"] = description
    if shared:
        entry["shared"] = True
    return entry


def load_tools(conn, user_id: str, ws: Workspace) -> None:
    """Fill ``ws.tools`` the way the classic agent picker lists them, without configs or secrets."""
    from docsgpt.agents.default_tools import (
        builtin_agent_tools_for_management,
        default_tools_for_management,
        is_server_attached_tool,
        WORKFLOW_ONLY_BUILTINS,
    )
    from docsgpt.api.user.resource_access import settings_many
    from docsgpt.api.user.team_sharing import visible_with_access
    from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
    from docsgpt.storage.db.repositories.users import UsersRepository

    repo = UserToolsRepository(conn)
    own = repo.list_for_user(user_id)
    own_ids = {str(r["id"]) for r in own}
    team = visible_with_access(conn, user_id, "tool")
    shared_rows = repo.list_by_ids([tid for tid in team if tid not in own_ids])
    switches = settings_many(conn, "tool", [str(r["id"]) for r in shared_rows])
    rows: list[tuple[dict, bool, Optional[str]]] = [(r, False, None) for r in own]
    for row in shared_rows:
        tid = str(row["id"])
        if _attachable("tool", team.get(tid), switches.get(tid)):
            rows.append((row, True, None))
    seen: set[str] = set()
    for row in default_tools_for_management(UsersRepository(conn).get(user_id)):
        rows.append((row, False, "built-in"))
        seen.add(str(row["id"]))
    for row in builtin_agent_tools_for_management():
        if str(row["id"]) in seen or row.get("name") in WORKFLOW_ONLY_BUILTINS:
            continue
        rows.append((row, False, "built-in"))
    out: list[dict] = []
    for row, shared, kind in rows:
        if is_server_attached_tool(row.get("name")):
            continue
        entry = _tool_entry(row, shared=shared, kind=kind)
        actions = _tool_actions(row)
        entry["actions"] = [a["name"] for a in actions]
        ws.tool_details[entry["id"]] = {**entry, "actions": actions}
        out.append(entry)
    ws.tools = _cap(out, MAX_TOOLS, "tools", ws)


def is_template(content: str) -> bool:
    """Whether a prompt is rendered as a template (verbatim, without the composer's sections).

    The rule of ``resolve_prompt_skeleton``: any ``{{ }}``, or a legacy
    ``{summaries}`` marker. Anything else is a persona the composer wraps.
    """
    from docsgpt.api.answer.services.prompt_renderer import prompt_embeds_documents

    return bool(content) and (("{{" in content and "}}" in content) or prompt_embeds_documents(content))


def load_prompts(conn, user_id: str, ws: Workspace) -> None:
    """Fill ``ws.prompts``: the built-in prompts, the caller's own, and the team-shared ones they may use."""
    from docsgpt.api.user.resource_access import settings_many
    from docsgpt.api.user.team_sharing import visible_with_access
    from docsgpt.prompts.composer import compose_preset
    from docsgpt.storage.db.repositories.prompts import PromptsRepository

    out: list[dict] = []
    for preset, note in PRESET_PROMPTS.items():
        out.append({"id": preset, "name": preset, "kind": "built-in", "preview": note, "template": True})
        ws.prompt_texts[preset] = clean_text(compose_preset(preset), PROMPT_CHARS)
    repo = PromptsRepository(conn)
    own = repo.list_for_user(user_id)
    own_ids = {str(p["id"]) for p in own}
    ws.own_prompts = own_ids
    team = visible_with_access(conn, user_id, "prompt")
    shared = repo.list_by_ids([pid for pid in team if pid not in own_ids])
    switches = settings_many(conn, "prompt", [str(p["id"]) for p in shared])
    rows = [(p, False) for p in own]
    rows += [(p, True) for p in shared if _attachable("prompt", team.get(str(p["id"])), switches.get(str(p["id"])))]
    for row, is_shared in rows:
        pid = str(row["id"])
        content = row.get("content") or ""
        entry: dict[str, Any] = {
            "id": pid,
            "name": clean_text(row.get("name"), NAME_CHARS),
            "kind": "team" if is_shared else "own",
            "preview": clean_text(" ".join(content.split()), PREVIEW_CHARS),
        }
        if is_template(content):
            entry["template"] = True
        ws.prompt_texts[pid] = clean_text(content, PROMPT_CHARS)
        out.append(entry)
    ws.prompts = _cap(out, MAX_PROMPTS + len(PRESET_PROMPTS), "prompts", ws)


def load_models(user_id: str, ws: Workspace) -> None:
    """Fill ``ws.models`` with the models the caller can pick (names only)."""
    try:
        from docsgpt.core.model_registry import ModelRegistry

        models = ModelRegistry.get_instance().get_enabled_models(user_id=user_id)
    except Exception:
        logger.warning("drafter: could not list models", exc_info=True)
        models = []
    rows = [{"id": str(m.id), "name": clean_text(m.display_name or m.id, NAME_CHARS)} for m in models]
    ws.models = _cap(rows, MAX_MODELS, "models", ws)


def load_agent(conn, user_id: str, agent_id: Optional[str], ws: Workspace) -> None:
    """Fill ``ws.agent`` with the saved agent being edited, when the caller may open its edit page.

    Sets ``ws.policy_editable``: an agent id the caller can't open leaves it False.
    """
    from docsgpt.api.user.resource_access import resolve
    from docsgpt.storage.db.repositories.agents import AgentsRepository

    if not agent_id or not isinstance(agent_id, str):
        return
    ws.policy_editable = False
    ra = resolve(conn, "agent", agent_id, user_id)
    if ra is None or not ra.can("view"):
        return
    row = AgentsRepository(conn).get_any(ra.resource_id, ra.owner_id)
    if not row:
        return
    ws.policy_editable = ra.can("edit_policy")
    ws.agent = {
        "id": str(row["id"]),
        "name": clean_text(row.get("name"), NAME_CHARS),
        "status": str(row.get("status") or ""),
        "agent_type": str(row.get("agent_type") or ""),
    }


def load_workspace(user_id: str, *, agent_id: Optional[str] = None) -> Workspace:
    """Read the caller's workspace in one read-only transaction.

    Args:
        user_id: The caller (``decoded_token["sub"]``).
        agent_id: The agent being edited, if any.

    Returns:
        The workspace.
    """
    from docsgpt.storage.db.session import db_readonly

    ws = Workspace()
    with db_readonly() as conn:
        load_sources(conn, user_id, ws)
        load_tools(conn, user_id, ws)
        load_prompts(conn, user_id, ws)
        load_agent(conn, user_id, agent_id, ws)
    load_models(user_id, ws)
    return ws
