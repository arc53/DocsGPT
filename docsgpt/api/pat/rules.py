"""What a personal access token may call: the scope and resource rule table.

Authorization for PATs is central and deny by default. ``RULES`` maps a Flask
route (its rule string and method) to the scope it needs; a PAT request to a
route that is not listed is refused, so a new endpoint is unreachable by token
until someone classifies it here. ``tests/api/test_pat_rules.py`` fails when a
registered route is in neither ``RULES`` nor ``DENIED``.

A token may also carry a resource filter (``{"agents": [ids]}``). For a
restricted family the rule must be able to prove the request stays inside the
allowlist: it names where the id travels (``ids``), or declares that the route
filters its own listing (``listing``), or delegates to the route
(``in_route``). Anything else, creation included, is refused. ``refs`` cover
ids of *other* families a route accepts (an agent update naming a source), and
``blocked_by`` closes routes whose rows hang off a family the rule cannot see
(a schedule belongs to an agent).

Session (JWT) callers never pass through here.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from docsgpt.api.pat.tokens import is_pat

VIEW, QUERY, JSON, FORM, BODY = "view", "query", "json", "form", "body"

Locator = tuple[str, str]


@dataclass(frozen=True)
class Rule:
    """Requirement for one route+method. ``scopes`` is any-of; empty means any valid token."""

    scopes: tuple[str, ...] = ()
    family: Optional[str] = None
    ids: tuple[Locator, ...] = ()
    refs: tuple[tuple[str, Locator], ...] = ()
    listing: bool = False
    open: bool = False
    in_route: bool = False
    blocked_by: tuple[str, ...] = ()
    check: Optional[Callable[[Any, dict, Optional[str]], Optional[str]]] = None


def _rule(scope: Optional[str] = None, *ids: Locator, any_of: tuple[str, ...] = (), **kwargs) -> Rule:
    scopes = any_of or ((scope,) if scope else ())
    family = kwargs.pop("family", None)
    if family is None and scope:
        family = scope.partition(":")[0]
    return Rule(scopes=scopes, family=family, ids=tuple(ids), **kwargs)


#: Scopes that admit a token to message replay. Shared by the Flask tail route
#: below and its ASGI sibling GET /api/messages/<id>/events (docsgpt/api/async_sse.py),
#: which sits outside this table.
MESSAGE_REPLAY_SCOPES = ("conversations:read", "chat:run")

_ALL_FAMILIES = ("agents", "sources", "prompts", "tools", "workflows")
_WORKFLOW_CONTENT_FAMILIES = ("sources", "tools", "prompts")
# A route reached through an agent id can prove the agent; nothing else about it.
_NON_AGENT_FAMILIES = ("sources", "prompts", "tools", "workflows")

# Ids of other families that agent create/update accept in their JSON-or-form body.
_AGENT_BODY_REFS = (
    ("sources", (BODY, "source")),
    ("sources", (BODY, "sources")),
    ("prompts", (BODY, "prompt_id")),
    ("tools", (BODY, "tools")),
    ("workflows", (BODY, "workflow")),
)


def _conversation_agent_id(conversation_id: str, user_id: Optional[str]) -> tuple[bool, str]:
    """``(found, agent_id)`` for a conversation the user can reach; ``agent_id`` is "" when it has none."""
    from docsgpt.storage.db.repositories.conversations import ConversationsRepository
    from docsgpt.storage.db.session import db_readonly

    if not user_id:
        return False, ""
    try:
        with db_readonly() as conn:
            row = ConversationsRepository(conn).get_any(str(conversation_id), user_id)
    except Exception:
        return False, ""
    if not row:
        return False, ""
    return True, str(row.get("agent_id") or "")


def _chat_check(request, resource_filter: dict, user_id: Optional[str]) -> Optional[str]:
    """Keep a restricted token's chat traffic inside its allowlists.

    An agent brings its own sources, prompt and tools, which this table cannot
    see, so a restricted token must name an allowed agent. The one exception is
    a token restricted on sources only, which may chat against allowed sources
    directly. Everything that could swap in another agent or another set of
    resources is refused: an agent ``api_key``, an inline workflow, and a
    ``conversation_id`` that belongs to a different agent (the server would
    otherwise continue, append to, or resume tool calls of that conversation).

    Chat executes tools: an agent's own, or the user's defaults when there is
    no agent. Neither can be held to a tools allowlist from here, so a token
    restricted on tools cannot chat at all.
    """
    body = _json_body(request)
    if "tools" in resource_filter:
        return "A token restricted to specific tools cannot use chat endpoints"
    if body.get("api_key"):
        return "A restricted token cannot chat with an agent API key; pass agent_id"
    if body.get("workflow"):
        # An inline workflow graph (builder preview) can reference any resource.
        return "A restricted token cannot run an inline workflow"
    agent_ids = _as_ids(body.get("agent_id"))
    if "agents" in resource_filter:
        if len(agent_ids) != 1:
            return "This token is restricted to specific agents; pass agent_id"
        # the agent id itself is verified through ``refs``
    elif set(resource_filter) - {"sources"}:
        return "Restrict this token to specific agents to use chat endpoints"
    elif agent_ids:
        return "This token is restricted to specific sources and cannot run agents"
    conversation_id = body.get("conversation_id")
    if conversation_id:
        found, conversation_agent = _conversation_agent_id(conversation_id, user_id)
        expected = agent_ids[0] if agent_ids else ""
        if not found or _canonical(conversation_agent) != _canonical(expected):
            return "This conversation does not belong to the agent this token may use"
    return None


def _agent_body_check(request, resource_filter: dict, user_id: Optional[str]) -> Optional[str]:
    """A workflow pulls in its own sources, tools and prompts, which a reference check cannot see.

    A token restricted on any of those may attach a workflow to an agent only
    when it is also restricted on workflows, so the workflow is one its owner
    chose (``refs`` then verifies the id).
    """
    if "workflows" in resource_filter or not set(resource_filter) & {"sources", "tools", "prompts"}:
        return None
    if _read(request, (BODY, "workflow")):
        return "A token restricted to specific sources, tools or prompts cannot attach a workflow to an agent"
    return None


_CHAT = dict(
    family=None,
    refs=(
        ("agents", (JSON, "agent_id")),
        ("sources", (JSON, "active_docs")),
        ("prompts", (JSON, "prompt_id")),
        ("workflows", (JSON, "workflow_id")),
    ),
    check=_chat_check,
)

RULES: dict[tuple[str, str], Rule] = {
    # Identity and public metadata: any valid token.
    ("/api/user/me", "GET"): _rule(open=True),
    ("/api/health", "GET"): _rule(open=True),
    ("/api/config", "GET"): _rule(open=True),
    # Agents
    ("/api/get_agent", "GET"): _rule("agents:read", (QUERY, "id")),
    ("/api/get_agents", "GET"): _rule("agents:read", listing=True),
    ("/api/pinned_agents", "GET"): _rule("agents:read"),
    ("/api/shared_agents", "GET"): _rule("agents:read"),
    ("/api/template_agents", "GET"): _rule("agents:read", open=True),
    ("/api/export_agent", "GET"): _rule("agents:read", (QUERY, "id")),
    ("/api/guardrails/catalog", "GET"): _rule("agents:read", open=True),
    ("/api/guardrails/events", "GET"): _rule("agents:read", (QUERY, "agent_id")),
    ("/api/guardrails/summary", "GET"): _rule("agents:read", (QUERY, "agent_id")),
    ("/api/agents/folders/", "GET"): _rule("agents:read", open=True),
    ("/api/agents/folders/<string:folder_id>", "GET"): _rule("agents:read"),
    ("/api/create_agent", "POST"): _rule("agents:write", refs=_AGENT_BODY_REFS, check=_agent_body_check),
    ("/api/update_agent/<string:agent_id>", "PUT"): _rule(
        "agents:write", (VIEW, "agent_id"), refs=_AGENT_BODY_REFS, check=_agent_body_check
    ),
    ("/api/delete_agent", "DELETE"): _rule("agents:write", (QUERY, "id")),
    ("/api/adopt_agent", "POST"): _rule("agents:write"),
    ("/api/pin_agent", "POST"): _rule("agents:write", (QUERY, "id")),
    ("/api/remove_shared_agent", "DELETE"): _rule("agents:write", (QUERY, "id")),
    ("/api/share_agent", "PUT"): _rule("agents:write", (JSON, "id")),
    ("/api/import_agent/plan", "POST"): _rule("agents:write", in_route=True),
    ("/api/import_agent", "POST"): _rule("agents:write", in_route=True),
    ("/api/agents/folders/", "POST"): _rule("agents:write"),
    ("/api/agents/folders/<string:folder_id>", "PUT"): _rule("agents:write"),
    ("/api/agents/folders/<string:folder_id>", "DELETE"): _rule("agents:write"),
    ("/api/agents/folders/move_agent", "POST"): _rule("agents:write", (JSON, "agent_id")),
    ("/api/agents/folders/bulk_move", "POST"): _rule("agents:write", (JSON, "agent_ids")),
    ("/api/regenerate_agent_key/<string:agent_id>", "POST"): _rule("agents:keys", (VIEW, "agent_id")),
    ("/api/agent_webhook", "GET"): _rule("agents:keys", (QUERY, "id")),
    # Schedules hang off an agent, and a schedule runs that agent with a free-form
    # instruction and stores the output. The agent id proves the agent and nothing
    # else, so tokens restricted on any other family are kept out; routes that
    # carry only a schedule id prove nothing and are closed to every restricted token.
    ("/api/agents/<string:agent_id>/schedules", "GET"): _rule(
        "schedules:read", refs=(("agents", (VIEW, "agent_id")),), blocked_by=_NON_AGENT_FAMILIES
    ),
    ("/api/agents/<string:agent_id>/schedules", "POST"): _rule(
        "schedules:write", refs=(("agents", (VIEW, "agent_id")),), blocked_by=_NON_AGENT_FAMILIES
    ),
    ("/api/schedules/<string:schedule_id>", "GET"): _rule("schedules:read", blocked_by=_ALL_FAMILIES),
    ("/api/schedules/<string:schedule_id>/runs", "GET"): _rule("schedules:read", blocked_by=_ALL_FAMILIES),
    ("/api/schedules/<string:schedule_id>/runs/<string:run_id>", "GET"): _rule(
        "schedules:read", blocked_by=_ALL_FAMILIES
    ),
    ("/api/schedules/<string:schedule_id>", "PUT"): _rule("schedules:write", blocked_by=_ALL_FAMILIES),
    ("/api/schedules/<string:schedule_id>", "PATCH"): _rule("schedules:write", blocked_by=_ALL_FAMILIES),
    ("/api/schedules/<string:schedule_id>", "DELETE"): _rule("schedules:write", blocked_by=_ALL_FAMILIES),
    ("/api/schedules/<string:schedule_id>/run", "POST"): _rule("schedules:write", blocked_by=_ALL_FAMILIES),
    # Sources
    ("/api/sources", "GET"): _rule("sources:read", listing=True),
    # Counted and paged in SQL, so it cannot be narrowed here; restricted tokens use /api/sources.
    ("/api/sources/paginated", "GET"): _rule("sources:read"),
    ("/api/directory_structure", "GET"): _rule("sources:read", (QUERY, "id")),
    ("/api/get_chunks", "GET"): _rule("sources:read", (QUERY, "id")),
    ("/api/sources/<string:source_id>/wiki/pages", "GET"): _rule("sources:read", (VIEW, "source_id")),
    ("/api/sources/<string:source_id>/wiki/page", "GET"): _rule("sources:read", (VIEW, "source_id")),
    ("/api/sources/<string:source_id>/graph", "GET"): _rule("sources:read", (VIEW, "source_id")),
    ("/api/sources/<string:source_id>/graph/node/<string:node_id>", "GET"): _rule(
        "sources:read", (VIEW, "source_id")
    ),
    # Ingestion and attachment extraction both report through this poll.
    ("/api/task_status", "GET"): _rule(any_of=("sources:read", "sources:write", "chat:run"), open=True),
    ("/api/upload", "POST"): _rule("sources:write"),
    ("/api/remote", "POST"): _rule("sources:write"),
    ("/api/sources/wiki", "POST"): _rule("sources:write"),
    ("/api/delete_old", "GET"): _rule("sources:write", (QUERY, "source_id")),
    ("/api/manage_sync", "POST"): _rule("sources:write", (JSON, "source_id")),
    ("/api/sync_source", "POST"): _rule("sources:write", (JSON, "source_id")),
    ("/api/sources/reingest", "POST"): _rule("sources:write", (JSON, "source_id")),
    ("/api/manage_source_files", "POST"): _rule("sources:write", (FORM, "source_id")),
    ("/api/sources/<string:source_id>/config", "PATCH"): _rule("sources:write", (VIEW, "source_id")),
    ("/api/sources/<string:source_id>/wiki/page", "PUT"): _rule("sources:write", (VIEW, "source_id")),
    ("/api/sources/<string:source_id>/wiki/convert", "POST"): _rule("sources:write", (VIEW, "source_id")),
    ("/api/sources/<string:source_id>/graphrag/enable", "POST"): _rule(
        "sources:write", (VIEW, "source_id")
    ),
    ("/api/add_chunk", "POST"): _rule("sources:write", (JSON, "id")),
    ("/api/update_chunk", "PUT"): _rule("sources:write", (JSON, "id")),
    ("/api/delete_chunk", "DELETE"): _rule("sources:write", (QUERY, "id")),
    # Prompts
    ("/api/get_prompts", "GET"): _rule("prompts:read", listing=True),
    ("/api/get_single_prompt", "GET"): _rule("prompts:read", (QUERY, "id")),
    ("/api/create_prompt", "POST"): _rule("prompts:write"),
    ("/api/update_prompt", "POST"): _rule("prompts:write", (JSON, "id")),
    ("/api/delete_prompt", "POST"): _rule("prompts:write", (JSON, "id")),
    # Tools
    ("/api/available_tools", "GET"): _rule("tools:read", open=True),
    ("/api/get_tools", "GET"): _rule("tools:read", listing=True),
    ("/api/create_tool", "POST"): _rule("tools:write"),
    ("/api/parse_spec", "POST"): _rule("tools:write", open=True),
    ("/api/update_tool", "POST"): _rule("tools:write", (JSON, "id")),
    ("/api/update_tool_config", "POST"): _rule("tools:write", (JSON, "id")),
    ("/api/update_tool_actions", "POST"): _rule("tools:write", (JSON, "id")),
    ("/api/update_tool_status", "POST"): _rule("tools:write", (JSON, "id")),
    ("/api/delete_tool", "POST"): _rule("tools:write", (JSON, "id")),
    ("/api/mcp_server/test", "POST"): _rule("tools:write", open=True),
    ("/api/mcp_server/save", "POST"): _rule("tools:write", (JSON, "id")),
    # Models
    ("/api/models", "GET"): _rule(any_of=("models:read", "chat:run"), open=True),
    ("/api/user/models", "GET"): _rule("models:read"),
    ("/api/user/models/<string:model_id>", "GET"): _rule("models:read"),
    ("/api/user/models", "POST"): _rule("models:write"),
    ("/api/user/models/<string:model_id>", "PATCH"): _rule("models:write"),
    ("/api/user/models/<string:model_id>", "DELETE"): _rule("models:write"),
    ("/api/user/models/test", "POST"): _rule("models:write"),
    ("/api/user/models/<string:model_id>/test", "POST"): _rule("models:write"),
    # Workflows
    # A workflow graph names sources, tools and prompts inside its nodes, out of reach of ``refs``.
    ("/api/workflows", "POST"): _rule("workflows:write", blocked_by=_WORKFLOW_CONTENT_FAMILIES),
    ("/api/workflows/<string:workflow_id>", "GET"): _rule("workflows:read", (VIEW, "workflow_id")),
    ("/api/workflows/<string:workflow_id>", "PUT"): _rule(
        "workflows:write", (VIEW, "workflow_id"), blocked_by=_WORKFLOW_CONTENT_FAMILIES
    ),
    ("/api/workflows/<string:workflow_id>", "DELETE"): _rule("workflows:write", (VIEW, "workflow_id")),
    # Conversations and analytics span every agent and carry cited source text and tool
    # output, so they are closed to every restricted token.
    ("/api/get_conversations", "GET"): _rule("conversations:read", blocked_by=_ALL_FAMILIES),
    ("/api/search_conversations", "GET"): _rule("conversations:read", blocked_by=_ALL_FAMILIES),
    ("/api/get_single_conversation", "GET"): _rule("conversations:read", blocked_by=_ALL_FAMILIES),
    # A message cannot be tied to an allowlist from here, so any restricted token is kept out.
    ("/api/messages/<string:message_id>/tail", "GET"): _rule(
        any_of=MESSAGE_REPLAY_SCOPES, family=None, blocked_by=_ALL_FAMILIES
    ),
    ("/api/delete_conversation", "POST"): _rule("conversations:write", blocked_by=_ALL_FAMILIES),
    ("/api/delete_all_conversations", "GET"): _rule("conversations:write", blocked_by=_ALL_FAMILIES),
    ("/api/update_conversation_name", "POST"): _rule("conversations:write", blocked_by=_ALL_FAMILIES),
    ("/api/feedback", "POST"): _rule("conversations:write", blocked_by=_ALL_FAMILIES),
    ("/api/get_message_analytics", "POST"): _rule("analytics:read", blocked_by=_ALL_FAMILIES),
    ("/api/get_token_analytics", "POST"): _rule("analytics:read", blocked_by=_ALL_FAMILIES),
    ("/api/get_feedback_analytics", "POST"): _rule("analytics:read", blocked_by=_ALL_FAMILIES),
    ("/api/get_tool_analytics", "POST"): _rule("analytics:read", blocked_by=_ALL_FAMILIES),
    ("/api/get_schedule_analytics", "POST"): _rule("analytics:read", blocked_by=_ALL_FAMILIES),
    ("/api/get_user_logs", "POST"): _rule("analytics:read", blocked_by=_ALL_FAMILIES),
    # Teams (read only)
    ("/api/teams", "GET"): _rule("teams:read"),
    ("/api/teams/<string:team_id>", "GET"): _rule("teams:read"),
    ("/api/teams/<string:team_id>/members", "GET"): _rule("teams:read"),
    ("/api/teams/<string:team_id>/grants", "GET"): _rule("teams:read"),
    ("/api/resource_shares", "GET"): _rule("teams:read"),
    # Chat
    ("/api/answer", "POST"): _rule("chat:run", **_CHAT),
    ("/stream", "POST"): _rule("chat:run", **_CHAT),
    ("/api/search", "POST"): _rule("chat:run", **_CHAT),
    ("/api/store_attachment", "POST"): _rule("chat:run", family=None),
    ("/api/sources/<string:source_id>/search", "POST"): _rule(
        "chat:run", family=None, refs=(("sources", (VIEW, "source_id")),)
    ),
}

#: Routes a PAT may never call, by exact rule string ("*" = every method) or prefix.
#: Token management, admin, login flows and interactive OAuth handshakes need a
#: signed-in session; the rest have no scope yet. Listing them keeps the
#: classification test honest: a new route must land here or in ``RULES``.
DENIED: dict[str, tuple[str, ...]] = {
    "/": ("*",),
    "/api/user/tokens": ("*",),
    "/api/user/tokens/<string:token_id>": ("*",),
    "/api/generate_token": ("*",),
    "/api/combine": ("*",),
    "/api/download": ("*",),
    "/api/upload_index": ("*",),
    "/api/share": ("*",),
    "/api/shared_agent": ("*",),
    "/api/shared_conversation/<string:identifier>": ("*",),
    "/api/webhooks/agents/<string:webhook_token>": ("*",),
    "/api/images/<string:agent_id>/<string:capability>": ("*",),
    "/api/mcp_server/callback": ("*",),
    "/api/mcp_server/auth_status": ("*",),
    "/api/artifact/<artifact_id>": ("*",),
    "/api/artifacts": ("*",),
    "/api/artifacts/<artifact_id>": ("*",),
    "/api/artifacts/<artifact_id>/restore": ("*",),
    "/api/artifacts/<artifact_id>/versions/<int:version>": ("*",),
    "/api/stt": ("*",),
    "/api/stt/live/start": ("*",),
    "/api/stt/live/chunk": ("*",),
    "/api/stt/live/finish": ("*",),
    "/api/tts": ("*",),
    "/api/teams": ("POST",),
    "/api/teams/<string:team_id>": ("PUT", "DELETE"),
    "/api/teams/<string:team_id>/members": ("POST",),
    "/api/teams/<string:team_id>/members/<string:member_id>": ("*",),
    "/api/teams/<string:team_id>/grants": ("POST", "DELETE"),
    "/api/teams/<string:team_id>/transfer_owner": ("*",),
    "/swagger.json": ("*",),
}
DENIED_PREFIXES = (
    "/api/admin/",
    "/api/auth/oidc/",
    "/api/connectors/",
    "/api/devices",
    "/scim/",
    "/static/",
    "/swaggerui/",
    "/v1/",
)


def is_denied(rule: str, method: str) -> bool:
    if rule.startswith(DENIED_PREFIXES):
        return True
    methods = DENIED.get(rule)
    return bool(methods) and ("*" in methods or method in methods)


def _json_body(request) -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _as_ids(value: Any) -> list[str]:
    """Flatten whatever a route accepts as ids: a string, a JSON-encoded or plain list, or an ``{id}`` dict."""
    if value is None or value == "":
        return []
    if isinstance(value, dict):
        return _as_ids(value.get("id") or value.get("_id") or value.get("workflow_id"))
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            out.extend(_as_ids(item))
        return out
    text = str(value).strip()
    if text[:1] in "[{":
        try:
            return _as_ids(json.loads(text))
        except ValueError:
            return [text]
    return [text]


def _read(request, locator: Locator) -> list[str]:
    where, key = locator
    if where == VIEW:
        return _as_ids((request.view_args or {}).get(key))
    if where == QUERY:
        return _as_ids(request.args.get(key))
    if where == JSON:
        return _as_ids(_json_body(request).get(key))
    if where == FORM:
        return _as_ids(request.form.get(key))
    # BODY: routes that accept JSON or a multipart form interchangeably.
    if request.is_json:
        return _as_ids(_json_body(request).get(key))
    return _as_ids(request.form.get(key))


def _canonical(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        return value


def _all_allowed(ids: Iterable[str], allowed: Iterable[str]) -> bool:
    allowlist = {_canonical(a) for a in allowed}
    return all(_canonical(i) in allowlist for i in ids)


def authorize(request, decoded_token: dict) -> Optional[tuple[dict, int]]:
    """Check a PAT request against the table. ``None`` allows; otherwise ``(body, status)``."""
    url_rule = getattr(request, "url_rule", None)
    if url_rule is None:
        # Routing failed (unknown path or wrong method): no view will run, so
        # let Flask answer 404/405 instead of masking it with a 403.
        return None
    rule = RULES.get((url_rule.rule, request.method))
    if rule is None:
        return (
            {
                "success": False,
                "error": "not_available_to_tokens",
                "message": "This endpoint cannot be called with a personal access token",
            },
            403,
        )
    granted = set(decoded_token.get("scopes") or [])
    if rule.scopes and not granted.intersection(rule.scopes):
        return (
            {
                "success": False,
                "error": "insufficient_scope",
                "message": f"Token lacks the required scope: {' or '.join(rule.scopes)}",
                "required_scope": rule.scopes[0],
            },
            403,
        )
    resource_filter = decoded_token.get("resource_filter") or {}
    if not resource_filter:
        return None
    reason = _check_resources(request, rule, resource_filter, decoded_token.get("sub"))
    if reason is None:
        return None
    return ({"success": False, "error": "resource_not_allowed", "message": reason}, 403)


def _check_resources(request, rule: Rule, resource_filter: dict, user_id: Optional[str] = None) -> Optional[str]:
    for family in rule.blocked_by:
        if family in resource_filter:
            return f"This endpoint is not available to a token restricted to specific {family}"
    if rule.check is not None:
        reason = rule.check(request, resource_filter, user_id)
        if reason:
            return reason
    for family, locator in rule.refs:
        if family not in resource_filter:
            continue
        ids = _read(request, locator)
        if ids and not _all_allowed(ids, resource_filter[family]):
            return f"Token is not allowed to use one of the referenced {family}"
    family = rule.family
    if family is None or family not in resource_filter or rule.open or rule.listing or rule.in_route:
        return None
    ids = [i for locator in rule.ids for i in _read(request, locator)]
    if not ids:
        return f"This token is restricted to specific {family} and cannot use this endpoint"
    if not _all_allowed(ids, resource_filter[family]):
        return f"Token is not allowed to access this resource ({family})"
    return None


def allowed_ids(request, family: str) -> Optional[set[str]]:
    """The caller's allowlist for ``family``, or ``None`` when unrestricted (or not a PAT).

    Used by listing routes (``listing=True``) and by ``in_route`` handlers.
    """
    decoded = getattr(request, "decoded_token", None)
    if not is_pat(decoded):
        return None
    ids = (decoded.get("resource_filter") or {}).get(family)
    if ids is None:
        return None
    return {_canonical(str(i)) for i in ids}


def filter_listing(request, family: str, items: list, key: str = "id") -> list:
    """Drop rows outside the caller's allowlist. Rows without a UUID id (built-in presets) are kept."""
    allowed = allowed_ids(request, family)
    if allowed is None:
        return items
    kept = []
    for item in items:
        value = str(item.get(key, ""))
        if not _is_uuid(value) or _canonical(value) in allowed:
            kept.append(item)
    return kept


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def may_see_agent_keys(request) -> bool:
    """False for a token without ``agents:keys``: it must not receive a plaintext agent API key.

    Create, first publish and adopt all mint a key and used to return it, which
    handed a deploy token a secret that outlives the token's own revocation.
    """
    decoded = getattr(request, "decoded_token", None)
    if not is_pat(decoded):
        return True
    return "agents:keys" in (decoded.get("scopes") or [])


def mask_agent_key(key: Optional[str]) -> str:
    return f"{key[:4]}...{key[-4:]}" if key else ""
