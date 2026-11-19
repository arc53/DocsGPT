"""What a workflow's agent node keeps of the tools, sources, knowledge folders and model it names when the
workflow changes hands.

An agent node carries raw ids, which the engine resolves as the workflow's owner at run time, dropping a miss
with only a log line. A ref the new owner can't resolve would survive as a ghost: shown in the builder, never
used. So when a workflow is copied to someone (a template adopted) or moved to another owner (a workspace
Move), each ref is checked against a retention policy and removed when the policy says no; the builder then
shows an empty field to fill in. Each caller builds its own policy: :func:`adoption_retention` keeps what the
adopter may use; Move builds its own on top of it, keeping refs that moved with it or that a team shares.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from sqlalchemy import Connection

from docsgpt.agents.default_tools import is_synthesized_tool_id
from docsgpt.api.user.folder_knowledge import owned_source_folders
from docsgpt.api.user.team_sharing import can_access
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

#: The node keys that hold refs. With settings nested under ``config``, flat copies of these are dropped.
REF_KEYS = ("tools", "sources", "folders", "model_id")

NodeTransform = Callable[[str, dict], dict]


def _as_is(kind: str, value: Any) -> Any:
    return value


@dataclass(frozen=True)
class NodeRetention:
    """Which refs an agent node keeps under its new owner.

    Attributes:
        keep_tool: Whether a tool id (after ``resolve``) stays.
        keep_source: Whether a source id (after ``resolve``) stays.
        keep_folders: The knowledge folders that stay, given the node's list, in their order.
        keep_model: Whether a model id (after ``resolve``) stays; a dropped one becomes None.
        resolve: Maps a ref before it is checked, as ``resolve(kind, value)`` with ``kind`` ``tool``,
            ``source`` or ``model``: an old id to the item's uuid, or a model to its swap. Keeps it by default.
    """

    keep_tool: Callable[[str], bool]
    keep_source: Callable[[str], bool]
    keep_folders: Callable[[list], list]
    keep_model: Callable[[str], bool]
    resolve: Callable[[str, Any], Any] = _as_is


def _listed(value: Any) -> list:
    return value if isinstance(value, list) else [value]


def retain_node_refs(node_type: str, config: dict, retention: NodeRetention) -> dict:
    """Apply ``retention`` to an agent node's refs; other nodes are returned as they are.

    Node settings may sit nested under ``config``, as the engine reads them
    (``node.config.get("config", node.config)``); then flat leftovers of the ref keys, which the engine
    ignores but which would carry raw ids along, are dropped. Kept refs keep their order.

    Args:
        node_type: The node's type.
        config: The node config (changed in place).
        retention: What stays.

    Returns:
        ``config``.
    """
    if node_type != "agent":
        return config
    nested = config.get("config")
    cfg = nested if isinstance(nested, dict) else config
    for key, kind, keep in (("tools", "tool", retention.keep_tool), ("sources", "source", retention.keep_source)):
        if cfg.get(key):
            resolved = (retention.resolve(kind, v) for v in _listed(cfg[key]) if v)
            cfg[key] = [str(v) for v in resolved if v and keep(str(v))]
    if cfg.get("folders"):
        cfg["folders"] = retention.keep_folders(_listed(cfg["folders"]))
    if cfg.get("model_id"):
        model_id = retention.resolve("model", cfg["model_id"])
        cfg["model_id"] = model_id if not model_id or retention.keep_model(str(model_id)) else None
    if cfg is not config:
        for key in REF_KEYS:
            config.pop(key, None)
    return config


def node_transform(retention: NodeRetention) -> NodeTransform:
    """A ``(node_type, config) -> config`` transform applying ``retention``, as ``clone_to_user`` takes.

    Args:
        retention: What stays.

    Returns:
        The transform.
    """
    return lambda node_type, config: retain_node_refs(node_type, config, retention)


def adoptable_tool_ids(conn: Connection, user: str, tool_ids: Any) -> list:
    """Keep only tool ids ``user`` can actually run.

    Builtin synthetic ids resolve for everyone; a ``user_tools`` row must be the user's own: the runtime
    resolves tools strictly owner-scoped, so someone else's tool id would just be dropped (with a log line)
    on every run. Filtering when the copy is made shows the gap in the builder instead of at run time.

    Args:
        conn: Open connection.
        user: The new owner.
        tool_ids: Tool ids, in order.

    Returns:
        The kept ids, as strings.
    """
    tools_repo = UserToolsRepository(conn)
    kept = []
    for tid in tool_ids or []:
        tid = str(tid)
        if is_synthesized_tool_id(tid) or (looks_like_uuid(tid) and tools_repo.get_any(tid, user)):
            kept.append(tid)
    return kept


def adoption_retention(conn: Connection, user: Optional[str]) -> NodeRetention:
    """What an adopted template's agent nodes keep: what the adopter may use.

    Their own tools and builtin ones, sources they can open, their own knowledge folders, and catalog
    models or their own custom models.

    Args:
        conn: Open connection.
        user: The adopter (the copy's owner: a person or a team's principal).

    Returns:
        The policy.
    """
    def keep_model(model_id: str) -> bool:
        return not looks_like_uuid(model_id) or UserCustomModelsRepository(conn).get(model_id, user) is not None

    return NodeRetention(
        keep_tool=lambda tool_id: bool(adoptable_tool_ids(conn, user, [tool_id])),
        keep_source=lambda source_id: can_access(conn, "source", source_id, user),
        keep_folders=lambda folders: owned_source_folders(conn, folders, user),
        keep_model=keep_model,
    )


def adoption_node_transform(conn: Connection, user: Optional[str]) -> NodeTransform:
    """The ``clone_to_user`` node transform for adopting a template: :func:`adoption_retention` applied.

    Args:
        conn: Open connection.
        user: The adopter.

    Returns:
        The transform.
    """
    return node_transform(adoption_retention(conn, user))
