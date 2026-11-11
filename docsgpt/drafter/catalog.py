"""What the drafter may read: the caller's workspace, as the agent form's pickers offer it.

Read-only and scoped to the caller. Sources, tools and prompts are the
caller's own plus the ones shared with their teams that they may put on their
own agents (``use`` on a source or prompt, ``use_in_own`` on a tool), the same
rule ``ref_attachable`` applies when an agent is saved. Default and builtin
tools are offered as the agent picker offers them. Nothing here writes: the
list routes are not called because some of them have side effects (the agents
listing upserts the user row).

The workspace is read in two levels, so its size in the prompt does not grow
with what the rows hold. The overview is read once per turn, at the start of
its stream and before the first model call: every id the caller may attach,
and the names and a line of meta of the rows it lists. The detail is read
while the turn runs, one row at a time and only when a read tool asks for it
(:class:`DetailReader`): a prompt's text, a tool's actions, a source's file
tree; each is kept for the rest of the turn. Built-in prompts and tools are in
memory, so theirs is there from the start. The agent recipe's Insights reads
go to the database during the turn too, through its ``insights_reader``. Tool
configs and secrets are never read into it: a tool is its name, description
and actions.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from docsgpt.drafter.fencing import clean_text

logger = logging.getLogger(__name__)

#: Most rows of each kind the overview lists; the rest are counted, not shown. Built-in prompts and tools are
#: listed beside them.
MAX_SOURCES = 100
MAX_TOOLS = 60
MAX_PROMPTS = 50
MAX_MODELS = 30
#: Most actions listed per tool, and characters of one action description.
MAX_ACTIONS = 30
ACTION_DESCRIPTION_CHARS = 300
#: Characters of a name, a tool's description in the overview and in ``get_tool``, and a prompt's full text.
NAME_CHARS = 120
TOOL_BRIEF_CHARS = 100
DESCRIPTION_CHARS = 300
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
    """The caller's workspace as the drafter sees it: an overview of each kind, and the detail read so far.

    Attributes:
        sources: Overview source rows ``{id, name, type?, shared?, status?, tokens?}``.
        tools: Overview tool rows ``{id, name, kind, description?, shared?}``.
        prompts: Overview prompt rows ``{id, name, kind, description?}``.
        models: ``{id, name}`` rows of the models the caller can pick.
        agent: The saved agent being edited ``{id, name, status, agent_type}``, or None.
        policy_editable: Whether the caller may change the agent's guardrails and limits (``edit_policy``, the
            rule the agent update route applies); True for a new agent, which the caller will own.
        attachable: Kind -> every id of it the caller may attach, in listing order, those the overview leaves
            out too.
        hidden: Kind -> rows the overview leaves out.
        own_prompts: Ids of all the caller's own prompts, those the overview leaves out too.
        found: Kind -> id -> the overview row of an id the overview leaves out, kept as each is looked up.
        prompt_texts: Prompt id -> full text (capped), for ``get_prompt``; filled as each is read.
        tool_details: Tool id -> actions with full descriptions, for ``get_tool``; filled as each is read.
        source_files: Source id -> file paths (capped), for ``get_source``; filled as it reads each tree.
        source_file_counts: Source id -> how many files its tree lists, beside ``source_files``.
        reader: Reads the rows and the detail the overview leaves out; None for a workspace built in memory,
            which holds only what it was given.
    """

    sources: list[dict] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    prompts: list[dict] = field(default_factory=list)
    models: list[dict] = field(default_factory=list)
    agent: Optional[dict] = None
    policy_editable: bool = True
    attachable: dict[str, list[str]] = field(default_factory=dict)
    hidden: dict[str, int] = field(default_factory=dict)
    own_prompts: set[str] = field(default_factory=set)
    found: dict[str, dict[str, dict]] = field(default_factory=dict)
    prompt_texts: dict[str, str] = field(default_factory=dict)
    tool_details: dict[str, dict] = field(default_factory=dict)
    source_files: dict[str, list[str]] = field(default_factory=dict)
    source_file_counts: dict[str, int] = field(default_factory=dict)
    reader: Optional["DetailReader"] = None

    def counts(self) -> dict[str, int]:
        """How many of each kind the drafter looked at (the ``reading`` status event)."""
        return {
            "sources": len(self.sources) + self.hidden.get("sources", 0),
            "tools": len(self.tools) + self.hidden.get("tools", 0),
            "prompts": len(self.prompts) + self.hidden.get("prompts", 0),
            "models": len(self.models) + self.hidden.get("models", 0),
        }

    def ids(self, kind: str) -> set[str]:
        """The ids of one kind (``sources``, ``tools``, ``prompts``) the caller may attach, those not listed too."""
        return {str(row["id"]) for row in getattr(self, kind)} | set(self.attachable.get(kind, ()))

    def summary(self) -> dict[str, Any]:
        """The overview that goes into the prompt."""
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
    """The first ``limit`` rows; how many were left out is counted in ``ws.hidden[kind]``."""
    if len(rows) > limit:
        ws.hidden[kind] = len(rows) - limit
        return rows[:limit]
    return rows


def _attachable(resource_type: str, access: Optional[str], switches: Optional[dict]) -> bool:
    """Whether the caller's access to a resource (and its sharing switches) lets them attach it to an agent."""
    from docsgpt.api.user.resource_access import REF_USE_ACTION, allowed_actions

    return REF_USE_ACTION[resource_type] in allowed_actions(resource_type, access, switches)


def _attachable_rows(conn, repo: Any, resource_type: str, user_id: str) -> list[dict]:
    """The id rows of the caller's own ``resource_type`` and the team-shared ones they may attach, newest first.

    Only ids and owners are read (``repo.list_ids_for_user``), for every row: all of them count as the caller's
    to attach, however few the overview lists.
    """
    from docsgpt.api.user.resource_access import settings_many
    from docsgpt.api.user.team_sharing import visible_with_access

    team = visible_with_access(conn, user_id, resource_type)
    rows = repo.list_ids_for_user(user_id, extra_ids=list(team))
    switches = settings_many(conn, resource_type, [r["id"] for r in rows if str(r["user_id"]) != str(user_id)])
    return [
        row for row in rows
        if str(row["user_id"]) == str(user_id)
        or _attachable(resource_type, team.get(row["id"]), switches.get(row["id"]))
    ]


# ---------------------------------------------------------------------------
# Overview rows
# ---------------------------------------------------------------------------


def _source_entry(row: dict, user_id: str) -> dict:
    """A source's overview row: id, cleaned name, type, shared flag, ingest status and token count."""
    entry: dict[str, Any] = {"id": str(row["id"]), "name": clean_text(row.get("name"), NAME_CHARS)}
    if row.get("type"):
        entry["type"] = clean_text(str(row.get("type")), 40)
    if str(row.get("user_id")) != str(user_id):
        entry["shared"] = True
    if row.get("ingest_status"):
        entry["status"] = str(row.get("ingest_status"))
    tokens = str(row.get("tokens") or "")
    if tokens.isdigit() and int(tokens):
        entry["tokens"] = int(tokens)
    return entry


def _tool_entry(row: dict, *, shared: bool = False, kind: Optional[str] = None,
                chars: int = TOOL_BRIEF_CHARS) -> dict:
    """A tool's row: id, cleaned name and kind (``kind`` or the tool's type), description cut to ``chars``,
    shared flag."""
    name = clean_text(row.get("custom_name") or row.get("display_name") or row.get("name"), NAME_CHARS)
    entry: dict[str, Any] = {"id": str(row["id"]), "name": name, "kind": kind or clean_text(row.get("name"), 40)}
    description = clean_text(row.get("description"), chars)
    if description:
        entry["description"] = description
    if shared:
        entry["shared"] = True
    return entry


def _prompt_entry(row: dict, user_id: str) -> dict:
    """A prompt's overview row: id, cleaned name, and whether it is the caller's own or a team's."""
    return {"id": str(row["id"]), "name": clean_text(row.get("name"), NAME_CHARS),
            "kind": "own" if str(row.get("user_id")) == str(user_id) else "team"}


def _file_paths(structure: Any) -> list[str]:
    """File paths of a ``directory_structure`` tree, in stored order, capped."""
    from docsgpt.parser.remote.website_tree import tree_leaves

    try:
        leaves = tree_leaves(structure)
    except Exception:
        return []
    return [clean_text(path, 200) for path, _ in leaves[:MAX_SOURCE_FILES]]


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


def is_template(content: str) -> bool:
    """Whether a prompt is rendered as a template (verbatim, without the composer's sections).

    The rule of ``resolve_prompt_skeleton``: any ``{{ }}``, or a legacy
    ``{summaries}`` marker. Anything else is a persona the composer wraps.
    """
    from docsgpt.api.answer.services.prompt_renderer import prompt_embeds_documents

    return bool(content) and (("{{" in content and "}}" in content) or prompt_embeds_documents(content))


# ---------------------------------------------------------------------------
# Detail, read on demand
# ---------------------------------------------------------------------------


@contextmanager
def _reading(conn: Any = None) -> Iterator[Any]:
    """``conn``, or a read-only connection of its own when there is none."""
    if conn is not None:
        yield conn
        return
    from docsgpt.storage.db.session import db_readonly

    with db_readonly() as own:
        yield own


class DetailReader:
    """Reads what the overview leaves out, while the turn runs: overview rows by id and one row's detail.

    It checks no access: the functions below ask it only for ids the workspace holds as the caller's to attach
    (:func:`row_of`). Each read opens a read-only connection of its own unless it is handed one.
    """

    def __init__(self, user_id: str) -> None:
        """Read for ``user_id``: a row another user owns is marked shared."""
        self.user_id = str(user_id)

    def rows(self, kind: str, ids: list[str], conn: Any = None) -> list[dict]:
        """The overview rows of the ``kind`` rows ``ids`` names, newest first; built-in ids have none here."""
        from docsgpt.storage.db.repositories.prompts import PromptsRepository
        from docsgpt.storage.db.repositories.sources import SourcesRepository
        from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

        with _reading(conn) as c:
            if kind == "sources":
                return [_source_entry(row, self.user_id) for row in SourcesRepository(c).list_brief(ids)]
            if kind == "tools":
                return [_tool_entry(row, shared=str(row["user_id"]) != self.user_id)
                        for row in UserToolsRepository(c).list_brief(ids)]
            return [_prompt_entry(row, self.user_id) for row in PromptsRepository(c).list_brief(ids)]

    def prompt_text(self, prompt_id: str, conn: Any = None) -> Optional[str]:
        """A saved prompt's whole text as stored; None when there is no such prompt."""
        from docsgpt.storage.db.repositories.prompts import PromptsRepository

        with _reading(conn) as c:
            rows = PromptsRepository(c).list_by_ids([prompt_id])
        return (rows[0].get("content") or "") if rows else None

    def tool(self, tool_id: str, conn: Any = None) -> Optional[dict]:
        """A saved tool's row with its actions and full description; None when there is no such tool."""
        from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

        with _reading(conn) as c:
            rows = UserToolsRepository(c).list_by_ids([tool_id])
        if not rows:
            return None
        entry = _tool_entry(rows[0], shared=str(rows[0].get("user_id")) != self.user_id, chars=DESCRIPTION_CHARS)
        return {**entry, "actions": _tool_actions(rows[0])}

    def source_tree(self, source_id: str, conn: Any = None) -> Any:
        """A source's ``directory_structure``; None when it has none."""
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        with _reading(conn) as c:
            return SourcesRepository(c).get_directory_structure(source_id)


def row_of(ws: Workspace, kind: str, item_id: str) -> Optional[dict]:
    """The overview row of one of the caller's ``kind`` by id: listed, looked up before, or read now.

    Args:
        ws: The turn's workspace.
        kind: ``sources``, ``tools`` or ``prompts``.
        item_id: The id asked about.

    Returns:
        The row, or None when the id is not the caller's to attach (or its row could not be read).
    """
    for row in getattr(ws, kind):
        if row["id"] == item_id:
            return row
    found = ws.found.setdefault(kind, {})
    if item_id not in found and ws.reader is not None and item_id in ws.attachable.get(kind, ()):
        try:
            found.update({row["id"]: row for row in ws.reader.rows(kind, [item_id])})
        except Exception:
            logger.warning("drafter: could not read a row of the workspace", exc_info=True)
    return found.get(item_id)


def prompt_text(ws: Workspace, prompt_id: str, conn: Any = None) -> Optional[str]:
    """A prompt's text for the model, capped: read on the first ask, then kept.

    Args:
        ws: The turn's workspace.
        prompt_id: A built-in prompt's name or a saved prompt's id.
        conn: A connection to read through, when the caller holds one.

    Returns:
        The text, or None when the prompt is not the caller's to attach or could not be read.
    """
    if prompt_id not in ws.prompt_texts and ws.reader is not None and row_of(ws, "prompts", prompt_id):
        try:
            text = ws.reader.prompt_text(prompt_id, conn)
        except Exception:
            logger.warning("drafter: could not read a prompt's text", exc_info=True)
            return None
        if text is not None:
            ws.prompt_texts[prompt_id] = clean_text(text, PROMPT_CHARS)
    return ws.prompt_texts.get(prompt_id)


def tool_detail(ws: Workspace, tool_id: str) -> Optional[dict]:
    """A tool's row with its actions for ``get_tool``: read on the first ask, then kept.

    Args:
        ws: The turn's workspace.
        tool_id: A built-in or a saved tool's id.

    Returns:
        The detail, or None when the tool is not the caller's to attach or could not be read.
    """
    if tool_id not in ws.tool_details and ws.reader is not None and row_of(ws, "tools", tool_id):
        try:
            detail = ws.reader.tool(tool_id)
        except Exception:
            logger.warning("drafter: could not read a tool's actions", exc_info=True)
            return None
        if detail is not None:
            ws.tool_details[tool_id] = detail
    return ws.tool_details.get(tool_id)


def source_files(ws: Workspace, source_id: str) -> Optional[dict]:
    """``{files?, file_paths}`` of a source for ``get_source``: its tree is read on the first ask, then kept.

    Args:
        ws: The turn's workspace.
        source_id: A source :func:`row_of` knows.

    Returns:
        The file count (when the source has a tree) and up to ``MAX_SOURCE_FILES`` paths; None when the tree
        could not be read.
    """
    from docsgpt.parser.remote.website_tree import count_pages

    if source_id not in ws.source_files and ws.reader is not None:
        try:
            structure = ws.reader.source_tree(source_id)
        except Exception:
            logger.warning("drafter: could not read a source's files", exc_info=True)
            return None
        ws.source_files[source_id] = []
        if isinstance(structure, dict) and structure:
            ws.source_file_counts[source_id] = count_pages(structure)
            ws.source_files[source_id] = _file_paths(structure)
    out: dict[str, Any] = {}
    if source_id in ws.source_file_counts:
        out["files"] = ws.source_file_counts[source_id]
    out["file_paths"] = ws.source_files.get(source_id, [])
    return out


# ---------------------------------------------------------------------------
# The overview, read at the start of the turn
# ---------------------------------------------------------------------------


def _overview(conn, ws: Workspace, kind: str, ids: list[str], limit: int) -> list[dict]:
    """The overview rows of the first ``limit`` of ``ids``; every id counts as the caller's (``ws.attachable``)."""
    ws.attachable[kind] = ids
    shown = _cap(ids, limit, kind, ws)
    return ws.reader.rows(kind, shown, conn) if shown else []


def load_sources(conn, user_id: str, ws: Workspace) -> None:
    """Fill ``ws.sources``: the caller's own sources and the team-shared ones they may use.

    Every source's id is read to decide which the caller may attach; only the listed ones' names, types and
    statuses are read, and no source's file tree: ``get_source`` reads the one it is asked about.
    """
    from docsgpt.storage.db.repositories.sources import SourcesRepository

    rows = _attachable_rows(conn, SourcesRepository(conn), "source", user_id)
    ws.sources = _overview(conn, ws, "sources", [row["id"] for row in rows], MAX_SOURCES)


def load_tools(conn, user_id: str, ws: Workspace) -> None:
    """Fill ``ws.tools`` the way the classic agent picker lists them, without configs, secrets or actions.

    The caller's own and team tools are listed by name and description; ``get_tool`` reads the actions of the
    one it is asked about. Built-in tools are in memory, so every one is listed and its actions are kept.
    """
    from docsgpt.agents.default_tools import (
        builtin_agent_tools_for_management,
        default_tools_for_management,
        is_server_attached_tool,
        WORKFLOW_ONLY_BUILTINS,
    )
    from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
    from docsgpt.storage.db.repositories.users import UsersRepository

    saved = [row["id"] for row in _attachable_rows(conn, UserToolsRepository(conn), "tool", user_id)
             if not is_server_attached_tool(row.get("name"))]
    builtin: dict[str, dict] = {}
    for row in default_tools_for_management(UsersRepository(conn).get(user_id)):
        builtin[str(row["id"])] = row
    for row in builtin_agent_tools_for_management():
        if row.get("name") not in WORKFLOW_ONLY_BUILTINS:
            builtin.setdefault(str(row["id"]), row)
    listed = _overview(conn, ws, "tools", saved, MAX_TOOLS)
    for tool_id, row in builtin.items():
        if is_server_attached_tool(row.get("name")):
            continue
        listed.append(_tool_entry(row, kind="built-in"))
        ws.tool_details[tool_id] = {**_tool_entry(row, kind="built-in", chars=DESCRIPTION_CHARS),
                                    "actions": _tool_actions(row)}
        ws.attachable["tools"].append(tool_id)
    ws.tools = listed


def load_prompts(conn, user_id: str, ws: Workspace) -> None:
    """Fill ``ws.prompts``: the built-in prompts, the caller's own, and the team-shared ones they may use.

    Saved prompts are listed by name; ``get_prompt`` reads the text of the one it is asked about. The built-in
    prompts' texts are composed in memory, so they are kept from the start.
    """
    from docsgpt.prompts.composer import compose_preset
    from docsgpt.storage.db.repositories.prompts import PromptsRepository

    presets: list[dict] = []
    for preset, note in PRESET_PROMPTS.items():
        presets.append({"id": preset, "name": preset, "kind": "built-in", "description": note})
        ws.prompt_texts[preset] = clean_text(compose_preset(preset), PROMPT_CHARS)
    rows = _attachable_rows(conn, PromptsRepository(conn), "prompt", user_id)
    ws.own_prompts = {row["id"] for row in rows if str(row["user_id"]) == str(user_id)}
    ws.prompts = presets + _overview(conn, ws, "prompts", [row["id"] for row in rows], MAX_PROMPTS)
    ws.attachable["prompts"] = list(PRESET_PROMPTS) + ws.attachable["prompts"]


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


def read_workspace(conn, user_id: str, agent_id: Optional[str] = None) -> Workspace:
    """Read the overview of the caller's sources, tools and prompts and the agent being edited through ``conn``;
    models are left out.

    Args:
        conn: A read-only connection, for a recipe that reads more in the same transaction.
        user_id: The caller (``decoded_token["sub"]``).
        agent_id: The agent being edited, if any.

    Returns:
        The workspace, without ``models`` (:func:`load_models` fills them).
    """
    ws = Workspace(reader=DetailReader(user_id))
    load_sources(conn, user_id, ws)
    load_tools(conn, user_id, ws)
    load_prompts(conn, user_id, ws)
    load_agent(conn, user_id, agent_id, ws)
    return ws
