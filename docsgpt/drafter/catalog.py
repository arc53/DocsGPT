"""What the drafter may read: the caller's workspace, as the agent form's pickers offer it.

Read-only and scoped to the caller. Sources, tools and prompts are the
caller's own plus the ones shared with their teams that they may put on their
own agents (``use`` on a source or prompt, ``use_in_own`` on a tool), the same
rule ``ref_attachable`` applies when an agent is saved. That is Personal; in a
team workspace (the agent being edited is a team's, or the request names the
team) they are the team's own items only, since a team agent may hold nothing
else, and Personal never offers a team's items. Default and builtin
tools are offered as the agent picker offers them. Nothing here writes: the
list routes are not called because some of them have side effects (the agents
listing upserts the user row).

The workspace is read in levels, so its size in the prompt grows neither with
how many rows the caller has nor with what they hold. The overview is read
once per turn, at the start of its stream and before the first model call:
every id the caller may attach, and the names and a line of meta of the few
rows it lists (what the form uses, then the newest). The rest is read while
the turn runs, only when a read tool asks for it (:class:`DetailReader`), and
kept for the rest of the turn: the rows the overview leaves out
(``list_workspace``: :func:`find_rows`), and one row's detail: a prompt's
text, a tool's actions, a source's file tree. Built-in prompts and tools are
in memory, so theirs is there from the start. The agent recipe's Insights reads
go to the database during the turn too, through its ``insights_reader``. Tool
configs and secrets are never read into it: a tool is its name, description
and actions.

The agent recipe also lists the knowledge folders the caller may attach
(:func:`load_folders`): the whole tree and its filings are read with the
overview in two queries, so ``list_workspace`` and ``get_folder`` answer
them from memory. The other recipes never read them.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Optional

from docsgpt.drafter.fencing import clean_text

logger = logging.getLogger(__name__)

#: Most rows of each kind the overview lists: what the form already uses, then the newest. The rest are counted,
#: not shown, so the overview stays the same size however large the workspace is. Built-in prompts and tools are
#: listed beside them.
MAX_SOURCES = 25
MAX_TOOLS = 20
MAX_PROMPTS = 15
MAX_MODELS = 30
#: Knowledge folders the agent recipe's overview lists (the form's first, then the largest), and the sources and
#: subfolders ``get_folder`` names; the rest are counted.
MAX_FOLDERS = 15
MAX_FOLDER_SOURCES = 30
MAX_SUBFOLDERS = 30
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
#: The kinds ``list_workspace`` lists, and the words of a query it matches rows by.
KINDS = ("sources", "tools", "prompts")
QUERY_TERMS = 8
#: The agent recipe's extra kind: the knowledge folders the caller may attach (:func:`load_folders`). Not the
#: Insights topic folders the agent recipe calls ``folders``.
FOLDER_KIND = "folders"
#: Characters of a knowledge folder's path (the names of the folders above it).
PATH_CHARS = 200

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
        owner_id: The team's principal whose items the workspace offers, or None for Personal.
        agent: The saved agent being edited ``{id, name, status, agent_type}``, or None.
        policy_editable: Whether the caller may change the agent's guardrails and limits (``edit_policy``, the
            rule the agent update route applies); True for a new agent, which the caller will own.
        attachable: Kind -> every id of it the caller may attach, in listing order, those the overview leaves
            out too.
        hidden: Kind -> rows the overview leaves out.
        own_prompts: Ids of all the caller's own prompts, those the overview leaves out too.
        found: Kind -> id -> the overview row of an id the overview leaves out, kept as each is looked up.
        listings: Kind -> every overview row of it the caller may attach, for ``list_workspace``; filled on the
            first ask.
        prompt_texts: Prompt id -> full text (capped), for ``get_prompt``; filled as each is read.
        tool_details: Tool id -> actions with full descriptions, for ``get_tool``; filled as each is read.
        source_files: Source id -> file paths (capped), for ``get_source``; filled as it reads each tree.
        source_file_counts: Source id -> how many files its tree lists, beside ``source_files``.
        reader: Reads the rows and the detail the overview leaves out; None for a workspace built in memory,
            which holds only what it was given.
        folder_rows: Overview rows of the knowledge folders ``{id, name, path?, sources}``; only the agent recipe
            reads them (:func:`load_folders`), and only its workspace puts them in the summary.
        folder_tree: The tree those rows come from, for ``get_folder``; None when the folders weren't read.
    """

    sources: list[dict] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    prompts: list[dict] = field(default_factory=list)
    models: list[dict] = field(default_factory=list)
    owner_id: Optional[str] = None
    agent: Optional[dict] = None
    policy_editable: bool = True
    attachable: dict[str, list[str]] = field(default_factory=dict)
    hidden: dict[str, int] = field(default_factory=dict)
    own_prompts: set[str] = field(default_factory=set)
    found: dict[str, dict[str, dict]] = field(default_factory=dict)
    listings: dict[str, list[dict]] = field(default_factory=dict)
    prompt_texts: dict[str, str] = field(default_factory=dict)
    tool_details: dict[str, dict] = field(default_factory=dict)
    source_files: dict[str, list[str]] = field(default_factory=dict)
    source_file_counts: dict[str, int] = field(default_factory=dict)
    reader: Optional["DetailReader"] = None
    folder_rows: list[dict] = field(default_factory=list)
    folder_tree: Optional["FolderTree"] = None

    def counts(self) -> dict[str, int]:
        """How many of each kind the drafter looked at (the ``reading`` status event)."""
        return {
            "sources": len(self.sources) + self.hidden.get("sources", 0),
            "tools": len(self.tools) + self.hidden.get("tools", 0),
            "prompts": len(self.prompts) + self.hidden.get("prompts", 0),
            "models": len(self.models) + self.hidden.get("models", 0),
        }

    def ids(self, kind: str) -> set[str]:
        """The ids of one kind (``sources``, ``tools``, ``prompts``, ``folders``) the caller may attach, those not
        listed too."""
        return {str(row["id"]) for row in _rows(self, kind)} | set(self.attachable.get(kind, ()))

    def folder_sources(self, folder_id: str) -> list[str]:
        """Every source one of the caller's knowledge folders feeds (:func:`subtree_sources`)."""
        return subtree_sources(self, folder_id)

    def partial(self) -> bool:
        """Whether the overview leaves out sources, tools or prompts of the caller's (``list_workspace`` lists
        them)."""
        return any(self.hidden.get(kind) for kind in KINDS)

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


def _rows(ws: Workspace, kind: str) -> list[dict]:
    """The overview rows of one kind (``folders`` are ``folder_rows``: an agent workspace's ``folders`` are topic
    folders)."""
    return ws.folder_rows if kind == FOLDER_KIND else getattr(ws, kind)


def lists_folders(ws: Workspace) -> bool:
    """Whether the overview lists knowledge folders (shown or counted in ``not_shown``): a tree whose folders hold
    no source the caller may attach, or only agents, lists none."""
    return bool(ws.folder_rows or ws.hidden.get(FOLDER_KIND))


def kinds(ws: Workspace) -> tuple[str, ...]:
    """The kinds ``list_workspace`` lists in this workspace: knowledge folders only when the overview lists some
    (:func:`lists_folders`)."""
    return KINDS + (FOLDER_KIND,) if lists_folders(ws) else KINDS


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


def _attachable_rows(conn, repo: Any, resource_type: str, user_id: str, owner_id: Optional[str] = None) -> list[dict]:
    """The id rows of the caller's own ``resource_type`` and the team-shared ones they may attach, newest first.

    Only ids and owners are read (``repo.list_ids_for_user``), for every row: all of them count as the caller's
    to attach, however few the overview lists. With ``owner_id`` a team's principal, the rows are that team's own
    (every member may use them); Personal leaves out any team's item, even one a stale grant names.
    """
    from docsgpt.api.user.resource_access import settings_many
    from docsgpt.api.user.team_sharing import visible_with_access
    from docsgpt.workspaces.principal import is_principal_id

    if is_principal_id(owner_id):
        return repo.list_ids_for_user(owner_id)
    team = visible_with_access(conn, user_id, resource_type)
    rows = [
        row for row in repo.list_ids_for_user(user_id, extra_ids=list(team))
        if not is_principal_id(row.get("user_id"))
    ]
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
        kind: ``sources``, ``tools``, ``prompts`` or ``folders``.
        item_id: The id asked about.

    Returns:
        The row, or None when the id is not the caller's to attach (or its row could not be read).
    """
    for row in _rows(ws, kind):
        if row["id"] == item_id:
            return row
    found = ws.found.setdefault(kind, {})
    # Every folder row is read with the tree, so a folder id is never read again.
    if item_id not in found and ws.reader is not None and kind != FOLDER_KIND \
            and item_id in ws.attachable.get(kind, ()):
        try:
            found.update({row["id"]: row for row in ws.reader.rows(kind, [item_id])})
        except Exception:
            logger.warning("drafter: could not read a row of the workspace", exc_info=True)
    return found.get(item_id)


def listing(ws: Workspace, kind: str) -> list[dict]:
    """Every overview row of one kind the caller may attach, in the overview's order: read on the first ask,
    then kept.

    A kind the overview lists whole is answered from it; otherwise the saved rows are read once (names and
    meta only) and the built-in ones, which the overview always lists, keep their place beside them.

    Args:
        ws: The turn's workspace.
        kind: One of :data:`KINDS`.

    Returns:
        The rows.

    Raises:
        Exception: The rows could not be read; nothing is kept, so a later ask reads again.
    """
    if kind not in ws.listings:
        rows = list(_rows(ws, kind))
        if ws.reader is not None and ws.hidden.get(kind):
            builtin = [row for row in rows if row.get("kind") == "built-in"]
            in_memory = {row["id"] for row in builtin}
            saved = ws.reader.rows(kind, [item for item in ws.attachable.get(kind, ()) if item not in in_memory])
            ws.found.setdefault(kind, {}).update({row["id"]: row for row in saved})
            rows = builtin + saved if kind == "prompts" else saved + builtin
        ws.listings[kind] = rows
    return ws.listings[kind]


def find_rows(ws: Workspace, kind: str, query: str = "") -> list[dict]:
    """The rows of :func:`listing` a query matches, best first; every row without a query.

    A row matches when its name, description, type, kind or path holds one of the query's words, whatever the
    case.
    Rows holding more of the words come first, then the listing's order.

    Args:
        ws: The turn's workspace.
        kind: One of :data:`KINDS`.
        query: Words to look for; only the first :data:`QUERY_TERMS` distinct ones count.

    Returns:
        The matching rows.
    """
    rows = listing(ws, kind)
    terms = list(dict.fromkeys(query.casefold().split()))[:QUERY_TERMS]
    if not terms:
        return rows
    scored = []
    for index, row in enumerate(rows):
        text = " ".join(str(row.get(key) or "") for key in ("name", "description", "type", "kind", "path")
                        ).casefold()
        score = sum(term in text for term in terms)
        if score:
            scored.append((-score, index))
    return [rows[index] for _, index in sorted(scored)]


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


def _overview(conn, user_id: str, ws: Workspace, kind: str, ids: list[str], limit: int,
              pinned: Iterable[str]) -> list[dict]:
    """The overview rows of ``ids``: the ``pinned`` ones, then the first of the rest until ``limit`` rows are
    listed, newest first. Every id counts as the caller's (``ws.attachable``), listed or not, and the workspace
    gets the reader that reads the rest for ``user_id``."""
    ws.reader = ws.reader or DetailReader(user_id)
    ws.attachable[kind] = ids
    known = set(ids)
    first = {item: None for item in pinned if item in known}
    rest = [item for item in ids if item not in first]
    shown = list(first) + rest[:max(0, limit - len(first))]
    if len(shown) < len(ids):
        ws.hidden[kind] = len(ids) - len(shown)
    return ws.reader.rows(kind, shown, conn) if shown else []


def load_sources(
    conn, user_id: str, ws: Workspace, pinned: Iterable[str] = (), owner_id: Optional[str] = None,
) -> None:
    """Fill ``ws.sources``: the caller's own sources and the team-shared ones they may use (a team's: its own).

    Every source's id is read to decide which the caller may attach; only the listed ones' names, types and
    statuses are read, and no source's file tree: ``get_source`` reads the one it is asked about.
    """
    from docsgpt.storage.db.repositories.sources import SourcesRepository

    rows = _attachable_rows(conn, SourcesRepository(conn), "source", user_id, owner_id)
    ws.sources = _overview(conn, owner_id or user_id, ws, "sources", [row["id"] for row in rows], MAX_SOURCES,
                           pinned)


def load_tools(
    conn, user_id: str, ws: Workspace, pinned: Iterable[str] = (), owner_id: Optional[str] = None,
) -> None:
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

    saved = [row["id"] for row in _attachable_rows(conn, UserToolsRepository(conn), "tool", user_id, owner_id)
             if not is_server_attached_tool(row.get("name"))]
    builtin: dict[str, dict] = {}
    for row in default_tools_for_management(UsersRepository(conn).get(user_id)):
        builtin[str(row["id"])] = row
    for row in builtin_agent_tools_for_management():
        if row.get("name") not in WORKFLOW_ONLY_BUILTINS:
            builtin.setdefault(str(row["id"]), row)
    listed = _overview(conn, owner_id or user_id, ws, "tools", saved, MAX_TOOLS, pinned)
    for tool_id, row in builtin.items():
        if is_server_attached_tool(row.get("name")):
            continue
        listed.append(_tool_entry(row, kind="built-in"))
        ws.tool_details[tool_id] = {**_tool_entry(row, kind="built-in", chars=DESCRIPTION_CHARS),
                                    "actions": _tool_actions(row)}
        ws.attachable["tools"].append(tool_id)
    ws.tools = listed


def load_prompts(
    conn, user_id: str, ws: Workspace, pinned: Iterable[str] = (), owner_id: Optional[str] = None,
) -> None:
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
    rows = _attachable_rows(conn, PromptsRepository(conn), "prompt", user_id, owner_id)
    owner = owner_id or user_id
    ws.own_prompts = {row["id"] for row in rows if str(row["user_id"]) == str(owner)}
    ws.prompts = presets + _overview(conn, owner, ws, "prompts", [row["id"] for row in rows], MAX_PROMPTS, pinned)
    ws.attachable["prompts"] = list(PRESET_PROMPTS) + ws.attachable["prompts"]


def load_models(user_id: str, ws: Workspace) -> None:
    """Fill ``ws.models`` with the models the caller can pick (names only).

    In a team (``ws.owner_id``) these are the built-ins and the team's own models, as ``/api/models`` lists them
    there: a team item saves only models its owner owns, so the caller's personal ones are never offered.
    """
    owner = ws.owner_id or user_id
    try:
        from docsgpt.core.model_registry import ModelRegistry

        models = ModelRegistry.get_instance().get_enabled_models(user_id=owner)
    except Exception:
        logger.warning("drafter: could not list models", exc_info=True)
        models = []
    if owner != user_id:
        models = [model for model in models if getattr(model, "source", None) != "user"]
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


# ---------------------------------------------------------------------------
# Knowledge folders (the agent recipe's ``folders`` kind)
# ---------------------------------------------------------------------------


@dataclass
class FolderTree:
    """The knowledge folder tree of the workspace's owner, as :func:`load_folders` read it.

    Attributes:
        names: Folder id -> cleaned name, for every folder of the tree.
        parents: Folder id -> its parent's id, or None at the top.
        children: Folder id -> its direct subfolders' ids, by name.
        filed: Folder id -> the sources filed straight into it that the caller may attach, newest first.
    """

    names: dict[str, str] = field(default_factory=dict)
    parents: dict[str, Optional[str]] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=dict)
    filed: dict[str, list[str]] = field(default_factory=dict)

    def above(self, folder_id: str) -> list[str]:
        """The folders above ``folder_id``, its parent first; a corrupt cycle stops the walk."""
        out: list[str] = []
        parent = self.parents.get(folder_id)
        while parent in self.names and parent != folder_id and parent not in out:
            out.append(parent)
            parent = self.parents.get(parent)
        return out


def load_folders(conn, user_id: str, ws: Workspace, pinned: Iterable[str] = (),
                 owner_id: Optional[str] = None) -> None:
    """Fill ``ws.folder_rows``: the knowledge folders the caller may attach to an agent of this workspace.

    The attach rule of :func:`attachable_folders`: the caller's own tree in Personal, the team principal's in a
    team (``owner_id``). The tree and its source filings are read in two queries, however large; every count is
    worked out from them. A row is ``{id, name, path?, sources}``: ``path`` names the folders above it (so two
    folders of one name can be told apart) and ``sources`` counts the sources the caller may attach that are filed
    anywhere in its subtree, which is what a new agent of theirs reads through it. Every folder counts as
    attachable (``get_folder`` reads any of them), but only those holding a source are listed, largest first,
    after the ``pinned`` ones (the form's), which are listed whatever they hold; the rest past :data:`MAX_FOLDERS`
    are counted in ``ws.hidden`` and reached with ``list_workspace``. Needs ``ws``'s sources read first.

    Args:
        conn: Open connection.
        user_id: The caller.
        ws: The workspace to fill.
        pinned: Folder ids listed first whatever the cap; ones the caller may not attach are left out.
        owner_id: The workspace's team principal, or None for Personal.
    """
    from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
    from docsgpt.workspaces.principal import is_principal_id

    owner = owner_id if is_principal_id(owner_id) else user_id
    tree = FolderTree()
    for row in FoldersRepository(conn).list_for_user(owner):
        fid = str(row["id"]).lower()
        tree.names[fid] = clean_text(row.get("name"), NAME_CHARS)
        tree.parents[fid] = str(row["parent_id"]).lower() if row.get("parent_id") else None
    for fid in sorted(tree.names, key=lambda f: (tree.names[f].casefold(), f)):
        if tree.parents[fid] in tree.names:
            tree.children.setdefault(tree.parents[fid], []).append(fid)
    order = {sid: i for i, sid in enumerate(ws.attachable.get("sources", ()))}
    for sid, fid in FolderItemsRepository(conn).filings(owner, "source").items():
        sid, fid = sid.lower(), fid.lower()
        if sid in order and fid in tree.names:
            tree.filed.setdefault(fid, []).append(sid)
    held: dict[str, set[str]] = {}
    for fid, sids in tree.filed.items():
        sids.sort(key=order.__getitem__)
        for holder in [fid] + tree.above(fid):
            held.setdefault(holder, set()).update(sids)
    rows: dict[str, dict] = {}
    for fid, name in tree.names.items():
        row: dict[str, Any] = {"id": fid, "name": name}
        path = " / ".join(tree.names[f] for f in reversed(tree.above(fid)))
        if path:
            row["path"] = clean_text(path, PATH_CHARS)
        row["sources"] = len(held.get(fid, ()))
        rows[fid] = row
    first = [fid for fid in dict.fromkeys(str(p).lower() for p in pinned) if fid in rows]
    # Largest first, then by where it sits: a parent before its subfolders, which hold no more than it.
    rest = sorted((fid for fid in rows if rows[fid]["sources"] and fid not in first),
                  key=lambda f: (-rows[f]["sources"], [tree.names[a].casefold() for a in reversed(tree.above(f))]
                                 + [tree.names[f].casefold()]))
    listing = [rows[fid] for fid in first + rest]
    shown = listing[:len(first)] + listing[len(first):][:max(0, MAX_FOLDERS - len(first))]
    if len(shown) < len(listing):
        ws.hidden[FOLDER_KIND] = len(listing) - len(shown)
    ws.attachable[FOLDER_KIND] = list(rows)
    ws.found[FOLDER_KIND] = rows
    ws.listings[FOLDER_KIND] = listing
    ws.folder_rows = shown
    ws.folder_tree = tree


def subtree_sources(ws: Workspace, folder_id: str) -> list[str]:
    """The sources the caller may attach filed anywhere in one of their knowledge folders' subtree: the folder's
    own first, then each level down; empty when :func:`load_folders` didn't list it as attachable."""
    tree = ws.folder_tree
    if tree is None or folder_id not in tree.names:
        return []
    out: list[str] = []
    level, seen = [folder_id], {folder_id}
    while level:
        for fid in level:
            out.extend(sid for sid in tree.filed.get(fid, ()) if sid not in out)
        level = [child for fid in level for child in tree.children.get(fid, ()) if child not in seen]
        seen.update(level)
    return out


def source_rows(ws: Workspace, source_ids: Iterable[str], conn: Any = None) -> dict[str, dict]:
    """The overview rows of those of ``source_ids`` the caller may attach, by id; the ones the overview leaves
    out are read in one query and kept in ``ws.found``, so ``get_source`` reads them like listed ones.

    Raises:
        Exception: The rows could not be read.
    """
    allowed = ws.ids("sources")
    known = {str(row["id"]): row for row in ws.sources}
    known.update(ws.found.get("sources", {}))
    wanted = [sid for sid in dict.fromkeys(source_ids) if sid in allowed]
    unread = [sid for sid in wanted if sid not in known]
    if unread and ws.reader is not None:
        rows = {row["id"]: row for row in ws.reader.rows("sources", unread, conn)}
        ws.found.setdefault("sources", {}).update(rows)
        known.update(rows)
    return {sid: known[sid] for sid in wanted if sid in known}


def folder_detail(ws: Workspace, folder_id: str) -> Optional[dict]:
    """``get_folder``'s answer for a knowledge folder the caller may attach: its row, the sources it feeds
    (``ws.folder_sources``) and its direct subfolders.

    ``{id, name, path?, sources: [{id, name}], more_sources?, subfolders: [{id, name, sources}], more_subfolders?}``,
    up to :data:`MAX_FOLDER_SOURCES` sources and :data:`MAX_SUBFOLDERS` subfolders named.

    Args:
        ws: The turn's workspace.
        folder_id: The folder's id, lower-case.

    Returns:
        The detail, or None when the folder is not one the caller may attach here.

    Raises:
        Exception: The sources' rows could not be read.
    """
    row = row_of(ws, FOLDER_KIND, folder_id)
    if row is None or ws.folder_tree is None:
        return None
    sources = ws.folder_sources(folder_id)
    named = source_rows(ws, sources[:MAX_FOLDER_SOURCES])
    out: dict[str, Any] = {key: row[key] for key in ("id", "name", "path") if key in row}
    out["sources"] = [{"id": sid, "name": named[sid].get("name")} for sid in sources if sid in named]
    if len(sources) > len(out["sources"]):
        out["more_sources"] = len(sources) - len(out["sources"])
    children = ws.folder_tree.children.get(folder_id, [])
    rows = ws.found.get(FOLDER_KIND, {})
    out["subfolders"] = [{"id": c, "name": rows[c]["name"], "sources": rows[c]["sources"]}
                         for c in children[:MAX_SUBFOLDERS]]
    if len(children) > MAX_SUBFOLDERS:
        out["more_subfolders"] = len(children) - MAX_SUBFOLDERS
    return out


def attachable_folders(conn, user_id: str, folder_ids: Iterable[Any], owner_id: Optional[str] = None) -> list[str]:
    """The ids among ``folder_ids`` the caller may attach to an agent of this workspace, lower-case, in order.

    The rule a save applies (``folder_knowledge.unattachable_folder``): the caller's own knowledge folders in
    Personal; in a team workspace (``owner_id`` the team's principal) the team's own tree, whoever filed into it.

    Args:
        conn: Open connection.
        user_id: The caller.
        folder_ids: Folder ids; anything that isn't one is left out.
        owner_id: The workspace's team principal, or None for Personal.

    Returns:
        list[str]: The attachable ids.
    """
    from docsgpt.api.user.folder_knowledge import holder_owned_folders, owned_source_folders
    from docsgpt.workspaces.principal import is_principal_id

    if is_principal_id(owner_id):
        return holder_owned_folders(conn, folder_ids, owner_id)
    return owned_source_folders(conn, folder_ids, user_id)


def workspace_owner(conn, user_id: str, agent_id: Optional[str] = None, *,
                    team_id: Optional[str] = None) -> Optional[str]:
    """Whose items the catalogue offers: a team's principal in a team workspace, None in Personal.

    The agent being edited decides when there is one (a route about one item goes by the item's workspace).
    Otherwise ``team_id`` does when given, else the request's workspace header; a refused or missing one reads
    as Personal, which offers the caller nothing of any team's.

    Args:
        conn: Open connection.
        user_id: The caller.
        agent_id: The agent being edited, if any.
        team_id: The team the request was made in, read while it was open: the drafter reads the workspace
            on its stream's thread, where the request's header is gone. The caller's membership is checked
            by :func:`read_workspace`.

    Returns:
        Optional[str]: The team's principal, or None for Personal.
    """
    from flask import has_request_context

    from docsgpt.api.user.resource_access import resolve
    from docsgpt.workspaces.context import WorkspaceError, current_workspace
    from docsgpt.workspaces.principal import principal_id

    if agent_id and isinstance(agent_id, str):
        ra = resolve(conn, "agent", agent_id, user_id)
        if ra is not None:
            return ra.owner_id if ra.is_team_item else None
    if team_id:
        return principal_id(str(team_id))
    if not has_request_context():
        return None
    try:
        workspace = current_workspace(conn)
    except WorkspaceError:
        return None
    return workspace.owner_id if workspace.is_team else None


def read_workspace(conn, user_id: str, agent_id: Optional[str] = None, *,
                   pinned: Optional[dict[str, list[str]]] = None,
                   owner_id: Optional[str] = None, team_id: Optional[str] = None) -> Workspace:
    """Read the overview of the caller's sources, tools and prompts and the agent being edited through ``conn``;
    models are left out.

    Args:
        conn: A read-only connection, for a recipe that reads more in the same transaction.
        user_id: The caller (``decoded_token["sub"]``).
        agent_id: The agent being edited, if any.
        pinned: Kind -> ids the overview lists whatever its caps (what the form already uses, which the model
            is given by id only); an id the caller may not attach is still left out.
        owner_id: A team's principal to read that team's workspace; by default :func:`workspace_owner` decides.
            A caller who is not in that team reads Personal instead.
        team_id: The team the request was made in, for a read after the request (see :func:`workspace_owner`).

    Returns:
        The workspace, without ``models`` (:func:`load_models` fills them).
    """
    from docsgpt.workspaces.principal import is_principal_id, team_of_principal
    from docsgpt.workspaces.roles import team_role_for

    pinned = pinned or {}
    if owner_id is None:
        owner_id = workspace_owner(conn, user_id, agent_id, team_id=team_id)
    if not is_principal_id(owner_id) or team_role_for(conn, user_id, team_of_principal(owner_id)) is None:
        # Never a team's items to someone outside it, whoever asked for them.
        owner_id = None
    ws = Workspace(owner_id=owner_id)
    load_sources(conn, user_id, ws, pinned.get("sources", ()), owner_id)
    load_tools(conn, user_id, ws, pinned.get("tools", ()), owner_id)
    load_prompts(conn, user_id, ws, pinned.get("prompts", ()), owner_id)
    load_agent(conn, user_id, agent_id, ws)
    return ws
