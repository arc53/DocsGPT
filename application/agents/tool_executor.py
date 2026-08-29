import logging
import re
import uuid
from collections import Counter, OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError

from application.agents.default_tools import (
    BUILTIN_AGENT_TOOLS,
    is_headless_excluded_tool,
    is_synthesized_tool_id,
    resolve_tool_by_id,
    synthesized_default_tools,
)
from application.agents.tools.tool_action_parser import ToolActionParser
from application.agents.tools.tool_manager import ToolManager
from application.guardrails.types import Stage as GuardrailStage, resolve_tool_result
from application.security.encryption import decrypt_credentials
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.tool_call_attempts import (
    ToolCallAttemptsRepository,
)
from application.storage.db.repositories.user_tools import UserToolsRepository
from application.storage.db.repositories.users import UsersRepository
from application.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)


def _is_foreign_key_violation(exc: BaseException) -> bool:
    """Whether ``exc`` is a Postgres FK violation (SQLSTATE 23503)."""
    if not isinstance(exc, IntegrityError):
        return False
    pgcode = getattr(getattr(exc, "orig", None), "sqlstate", None) or getattr(
        getattr(exc, "orig", None), "pgcode", None
    )
    return pgcode == "23503"


# Tightest provider limit on function-call names (OpenAI: ^[a-zA-Z0-9_-]{1,64}$).
_MAX_LLM_NAME_LEN = 64


def _dedupable_tool_names() -> frozenset:
    """Builtin tool names whose duplicate registrations may be collapsed.

    A builtin can resolve through both the default-tool and the builtin-agent
    registry, so the same row can arrive twice under different synthetic ids.
    Only these are safe to collapse — an MCP or user-added tool may
    legitimately appear more than once under a single name.
    """
    from application.core.settings import settings

    return frozenset(BUILTIN_AGENT_TOOLS) | frozenset(getattr(settings, "DEFAULT_CHAT_TOOLS", None) or [])


def _requires_approval(tool: Dict, action: Dict) -> bool:
    """Effective approval gate for one action of a tool row.

    Both sources live on the row: the cached ``actions[].require_approval``
    snapshot and the deployment-level ``config.require_approval`` that
    ``code_executor`` reads.
    """
    if bool(action.get("require_approval")):
        return True
    return bool((tool.get("config") or {}).get("require_approval"))


def _sanitize_tool_prefix(tool_name: Optional[str]) -> str:
    """Reduce a tool name to characters allowed in function-call names."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(tool_name or "")).strip("_")


# Longest string value rendered into a debug log line; longer values (e.g. an
# LLM-authored ``code`` body or an api_tool ``body``) are truncated so the full
# program/secret is never written to logs even at DEBUG level.
_LOG_VALUE_PREVIEW_LEN = 80

# Longest tool result persisted on the message / streamed to the UI. The LLM
# and the ``tool_call_attempts`` journal always receive the full result; this
# only bounds the message JSONB copy. 50 chars hid every real error behind
# "...", making retry storms undiagnosable from the stored conversation.
PERSISTED_RESULT_MAX_LEN = 2000


def truncate_tool_result(value: Any) -> Any:
    """Bound a tool result for persistence/streaming; short values pass through unchanged."""
    text = value if isinstance(value, str) else str(value)
    if len(text) <= PERSISTED_RESULT_MAX_LEN:
        return value
    return f"{text[:PERSISTED_RESULT_MAX_LEN]}..."


# Control characters minus \t \n \r. NULs in particular are rejected by
# Postgres text/jsonb, so one binary-carrying tool result would otherwise
# kill every write lane it fans out to (conversation, activity log,
# tool_call_attempts) at once.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Ceiling on the persisted full copy of a tool result (``result_full`` in
# the conversation row and the ``tool_call_attempts`` result). Generous —
# the LLM copy is bounded separately at TOOL_RESULT_MAX_TOKENS — but a
# ceiling all the same: one uncapped result has reached 634k tokens.
RESULT_FULL_MAX_CHARS = 400_000


def sanitize_tool_result(value: Any) -> Any:
    """Recursively strip NUL/control characters from strings in ``value``.

    Applied once where a tool result enters the executor, so every
    downstream consumer — the LLM copy, the conversation row, the
    ``tool_call_attempts`` journal, the stream event — gets clean text.
    """
    if isinstance(value, str):
        return _CONTROL_CHARS.sub("", value) if _CONTROL_CHARS.search(value) else value
    if isinstance(value, dict):
        return {sanitize_tool_result(k): sanitize_tool_result(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_tool_result(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_tool_result(item) for item in value)
    return value


def bound_result_full(text: str) -> str:
    """Cap the persisted full-result copy at ``RESULT_FULL_MAX_CHARS``."""
    if len(text) <= RESULT_FULL_MAX_CHARS:
        return text
    return (
        text[:RESULT_FULL_MAX_CHARS]
        + f"\n[... tool result truncated at persistence: {len(text)} chars ...]"
    )


def result_status(result: Any) -> str:
    """Derive the persisted status from a tool's result payload.

    Tools report failure in-band (``{"status": "error", ...}`` or an ``error``
    key) while the executor used to stamp every returned result ``completed``,
    so the stored conversation showed failed calls as successes.
    """
    if isinstance(result, dict) and (result.get("status") == "error" or result.get("error")):
        return "error"
    return "completed"


def _redact_args_for_log(args: Any) -> Any:
    """Truncate long string values so a code/body argument never lands in logs in full."""
    if not isinstance(args, dict):
        text = str(args)
        return text if len(text) <= _LOG_VALUE_PREVIEW_LEN else f"{text[:_LOG_VALUE_PREVIEW_LEN]}...(truncated)"
    redacted: Dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > _LOG_VALUE_PREVIEW_LEN:
            redacted[key] = f"{value[:_LOG_VALUE_PREVIEW_LEN]}...(truncated, {len(value)} chars)"
        elif isinstance(value, (dict, list)):
            redacted[key] = f"<{type(value).__name__} omitted>"
        else:
            redacted[key] = value
    return redacted


# ``message_id``s whose ``conversation_messages`` parent has been found
# missing. Every tool-call journal write for such a message FK-fails
# identically, and a long tool loop produces one ERROR *pair* per call — 60
# ERRORs from a single stream in production, the whole api-tier error volume
# for that day. Latch the first failure and log the rest at debug.
# Bounded so a long-lived worker cannot grow this without limit.
_MISSING_PARENTS: "OrderedDict[str, None]" = OrderedDict()
_MISSING_PARENTS_MAX = 256


def _is_missing_parent(message_id: Optional[str]) -> bool:
    return bool(message_id) and message_id in _MISSING_PARENTS


def _note_missing_parent(message_id: Optional[str], exc: BaseException) -> bool:
    """Record a FK failure against ``message_id``. True if newly latched.

    Args:
        message_id: The message the write was scoped to, if any.
        exc: The exception raised by the write.

    Returns:
        True when this is the first sighting for the message (so the caller
        should log loudly), False when already latched or not a FK error.
    """
    if not message_id or not _is_foreign_key_violation(exc):
        return False
    if message_id in _MISSING_PARENTS:
        return False
    _MISSING_PARENTS[message_id] = None
    while len(_MISSING_PARENTS) > _MISSING_PARENTS_MAX:
        _MISSING_PARENTS.popitem(last=False)
    return True


def _journal_key(call_id: str, message_id: Optional[str]) -> str:
    """Namespace the durability-journal key by the per-turn ``message_id``.

    ``tool_call_attempts.call_id`` is a table-wide primary key, but providers
    reuse deterministic ids (e.g. ``functions.create_artifact:0``) across turns
    and users, so distinct calls collide on that PK and the later journal rows
    are silently dropped (``ON CONFLICT DO NOTHING``). Scoping the key by
    ``message_id`` (unique per turn) gives each logical call its own row while a
    genuine retry of the same call within the same turn still dedupes. The raw
    ``call_id`` is left untouched for LLM tool-call/tool-result pairing and the
    UI. Headless attempts with no ``message_id`` keep the raw key (unchanged
    pre-existing behaviour).
    """
    return f"{message_id}:{call_id}" if message_id else call_id


def _record_proposed(
    call_id: str,
    tool_name: str,
    action_name: str,
    arguments: Any,
    *,
    tool_id: Optional[str] = None,
    message_id: Optional[str] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> bool:
    """Insert a ``proposed`` row; swallow infra failures so tool calls
    still run when the journal is unreachable. Returns True iff THIS call
    created the row.

    A duplicate ``call_id`` (LLMs reuse "call_0"-style ids) hits
    ``ON CONFLICT DO NOTHING`` and returns False: the existing row may
    belong to another in-flight request, so callers must not then flip it
    via ``_mark_failed`` / ``_mark_executed``.
    """
    try:
        with db_session() as conn:
            inserted = ToolCallAttemptsRepository(conn).record_proposed(
                _journal_key(call_id, message_id),
                tool_name,
                action_name,
                arguments,
                tool_id=tool_id if tool_id and looks_like_uuid(tool_id) else None,
                message_id=message_id,
                user_id=user_id,
                agent_id=(str(agent_id) if agent_id and looks_like_uuid(str(agent_id)) else None),
            )
        if not inserted:
            logger.warning(
                "tool_call_attempts duplicate call_id=%s; existing row left in place",
                call_id,
                extra={"alert": "tool_call_id_collision", "call_id": call_id},
            )
        return inserted
    except Exception as exc:
        if _note_missing_parent(message_id, exc):
            logger.warning(
                "tool_call_attempts: parent message row %s is gone "
                "(deleted mid-stream); suppressing further journal errors "
                "for this message. First failing call: %s",
                message_id,
                call_id,
            )
        elif _is_missing_parent(message_id):
            logger.debug(
                "tool_call_attempts proposed write skipped for %s "
                "(parent %s already known missing)",
                call_id,
                message_id,
            )
        else:
            logger.exception(
                "tool_call_attempts proposed write failed for %s", call_id
            )
        return False


def _mark_executed(
    call_id: str,
    result: Any,
    *,
    message_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
    proposed_ok: bool = True,
    tool_name: Optional[str] = None,
    action_name: Optional[str] = None,
    arguments: Any = None,
    tool_id: Optional[str] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> None:
    """Flip the row to ``executed``. If ``proposed_ok`` is False (the
    proposed write failed earlier), upsert a fresh row in ``executed`` so
    the reconciler can still see the attempt — without this, the side
    effect would be invisible to the journal. Both paths are scoped to
    the owning ``user_id`` so a reused ``call_id`` can't cross tenants.
    """
    key = _journal_key(call_id, message_id)
    try:
        with db_session() as conn:
            repo = ToolCallAttemptsRepository(conn)
            if proposed_ok:
                updated = repo.mark_executed(
                    key,
                    result,
                    message_id=message_id,
                    artifact_id=artifact_id,
                    user_id=user_id,
                )
                if updated:
                    return
            # Fallback synthesizes the row so the journal isn't lost.
            repo.upsert_executed(
                key,
                tool_name=tool_name or "unknown",
                action_name=action_name or "",
                arguments=arguments if arguments is not None else {},
                result=result,
                tool_id=tool_id if tool_id and looks_like_uuid(tool_id) else None,
                message_id=message_id,
                artifact_id=artifact_id,
                user_id=user_id,
                agent_id=(str(agent_id) if agent_id and looks_like_uuid(str(agent_id)) else None),
            )
    except Exception as exc:
        if _note_missing_parent(message_id, exc) or _is_missing_parent(message_id):
            logger.debug(
                "tool_call_attempts executed write skipped for %s "
                "(parent %s gone)",
                call_id,
                message_id,
            )
        else:
            logger.exception(
                "tool_call_attempts executed write failed for %s", call_id
            )


def _mark_failed(
    call_id: str,
    error: str,
    *,
    message_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    try:
        with db_session() as conn:
            ToolCallAttemptsRepository(conn).mark_failed(
                _journal_key(call_id, message_id), error, user_id=user_id
            )
    except Exception:
        logger.exception("tool_call_attempts failed-write failed for %s", call_id)


class ToolExecutor:
    """Handles tool discovery, preparation, and execution.

    Extracted from BaseAgent to separate concerns and enable tool caching.
    """

    def __init__(
        self,
        user_api_key: Optional[str] = None,
        user: Optional[str] = None,
        decoded_token: Optional[Dict] = None,
        agent_id: Optional[str] = None,
        *,
        headless: bool = False,
        tool_allowlist: Optional[List[str]] = None,
    ):
        self.user_api_key = user_api_key
        self.user = user
        self.decoded_token = decoded_token
        self.agent_id = agent_id
        # Headless mode (scheduled / webhook): no human to resolve a pause,
        # so check_pause returns headless_denied sentinels instead.
        self.headless = bool(headless)
        # Tool-instance ids pre-authorized for headless approval-gated execution.
        self.tool_allowlist: set = {str(x) for x in tool_allowlist} if tool_allowlist else set()
        # Set by BaseAgent._prepare_tools when the agent has tool-stage controls.
        self.guardrail_engine = None
        self.tool_calls: List[Dict] = []
        self._loaded_tools: Dict[str, object] = {}
        # Explicit tool-id scope (workflow agent nodes): when set (even empty),
        # get_tools() resolves EXACTLY these ids — builtin synthetic ids and
        # user_tools rows alike — with no defaults mixed in. None = unscoped.
        self.allowed_tool_ids: Optional[List[str]] = None
        self.conversation_id: Optional[str] = None
        # Set by the workflow engine for agent nodes so run-scoped tools
        # (artifact_generator / code_executor) address artifacts by the
        # workflow run rather than a conversation.
        self.workflow_run_id: Optional[str] = None
        self.message_id: Optional[str] = None
        # The request's own (already user-scoped) chat attachments, stamped onto
        # sandbox tools so a referenced attachment can be lazily bridged to a
        # conversation-scoped artifact at tool-use time.
        self.attachments: List[Dict] = []
        self.client_tools: Optional[List[Dict]] = None
        self._name_to_tool: Dict[str, Tuple[str, str]] = {}
        # Per-NAME failure counts for invented tool names this turn. After
        # ``UNRESOLVABLE_CALL_LIMIT`` the model is handed a directive message
        # instead of the generic error; this is a prompt-level nudge, not a hard
        # bound — the loop bound remains ``MAX_TOOL_ITERATIONS``.
        self._unresolvable_calls: Dict[str, int] = {}
        self._tool_to_name: Dict[Tuple[str, str], str] = {}
        # Filled by the LLMHandler.handle_tool_calls headless loop.
        self.headless_denials: List[Dict] = []

    def get_tools(self) -> Dict[str, Dict]:
        """Load tool configs from DB based on user context.

        If *client_tools* have been set on this executor, they are
        automatically merged into the returned dict.
        """
        if self.allowed_tool_ids is not None:
            tools = self._get_tools_by_ids(self.allowed_tool_ids)
        elif self.user_api_key:
            tools = self._get_tools_by_api_key(self.user_api_key)
        else:
            tools = self._get_user_tools(self.user or "local")
        if self.client_tools:
            self.merge_client_tools(tools, self.client_tools)
        return tools

    def get_enabled_tool_names(self) -> set:
        """Return the set of tool names enabled for this context.

        Authoritative (resolves through :meth:`get_tools`): an agent yields its
        configured ``agents.tools``; an agentless chat yields the user's active
        tools plus the synthesized defaults. Used to gate tool-specific prompt
        sections via the ``tools.enabled`` template namespace.
        """
        return {str(tool["name"]) for tool in self.get_tools().values() if isinstance(tool, dict) and tool.get("name")}

    def _get_tools_by_ids(self, tool_ids: List[str]) -> Dict[str, Dict]:
        """Resolve an explicit tool-id scope — exactly these ids, no defaults.

        Used by workflow agent nodes: the node's configured tools (builtin
        synthetic ids like Artifact/Code Executor/Read Document, or the user's
        ``user_tools`` rows) are the node's WHOLE toolset. An unresolvable id
        is dropped with a warning rather than failing the node.
        """
        if not tool_ids:
            return {}
        with db_readonly() as conn:
            tools_repo = UserToolsRepository(conn)
            tools: List[Dict] = []
            for tid in tool_ids:
                row = resolve_tool_by_id(tid, self.user, user_tools_repo=tools_repo)
                if row is None:
                    logger.warning("tool id %s did not resolve; dropped from scoped toolset", tid)
                    continue
                if self.headless and is_headless_excluded_tool(row.get("name")):
                    continue
                tools.append(row)
        return {str(tool["id"]): tool for tool in tools}

    def _get_tools_by_api_key(self, api_key: str) -> Dict[str, Dict]:
        """Resolve an agent's toolset — exactly ``agents.tools``, no defaults."""
        # Per-operation session: the answer pipeline spans a long-lived
        # generator; wrapping it in a single connection would pin a PG
        # conn for the whole stream. Open, fetch, close.
        with db_readonly() as conn:
            agent_data = AgentsRepository(conn).find_by_key(api_key)
            tool_ids = agent_data.get("tools", []) if agent_data else []
            tools_repo = UserToolsRepository(conn)
            owner = (agent_data.get("user_id") or agent_data.get("user")) if agent_data else None
            tools: List[Dict] = []
            for tid in tool_ids:
                row = resolve_tool_by_id(tid, owner, user_tools_repo=tools_repo)
                if row is None:
                    continue
                # Workflow-only builtins (read_document) never resolve for a
                # chat/scheduled agent — nodes get them via the scoped-id path.
                if row.get("workflow_only"):
                    continue
                # Headless runs (scheduled / webhook) drop chat-only tools
                # like ``scheduler`` so a fire-time LLM can't chain schedules.
                if self.headless and is_headless_excluded_tool(row.get("name")):
                    continue
                tools.append(row)
        return {str(tool["id"]): tool for tool in tools}

    def _get_user_tools(self, user: str = "local") -> Dict[str, Dict]:
        """Resolve an agentless chat's toolset: explicit user tools plus defaults."""
        with db_readonly() as conn:
            user_tools = UserToolsRepository(conn).list_active_for_user(user)
            user_doc = UsersRepository(conn).get(user) if self.agent_id is None else None
        # Headless agentless runs (e.g. scheduled fire) drop chat-only
        # tools (``scheduler``) from explicit user_tools too.
        filtered_user_tools = [
            t for t in user_tools if not (self.headless and is_headless_excluded_tool(t.get("name")))
        ]
        # Index keys (ints) and synthetic uuid5 keys can't collide.
        tools: Dict[str, Dict] = {str(i): tool for i, tool in enumerate(filtered_user_tools)}
        if self.agent_id is None:
            for default_row in synthesized_default_tools(
                user_doc,
                headless=self.headless,
            ):
                tools[str(default_row["id"])] = default_row
        return tools

    def merge_client_tools(self, tools_dict: Dict, client_tools: List[Dict]) -> Dict:
        """Merge client-provided tool definitions into tools_dict.

        Client tools use the standard function-calling format::

            [{"type": "function", "function": {"name": "get_weather",
              "description": "...", "parameters": {...}}}]

        They are stored in *tools_dict* with ``client_side: True`` so that
        :meth:`check_pause` returns a pause signal instead of trying to
        execute them server-side.

        Args:
            tools_dict: The mutable server tools dict (will be modified in place).
            client_tools: List of tool definitions in function-calling format.

        Returns:
            The updated *tools_dict* (same reference, for convenience).
        """
        for i, ct in enumerate(client_tools):
            func = ct.get("function", ct)  # tolerate bare {"name":..} too
            name = func.get("name", f"clienttool{i}")
            tool_id = f"ct{i}"

            tools_dict[tool_id] = {
                "name": name,
                "client_side": True,
                "actions": [
                    {
                        "name": name,
                        "description": func.get("description", ""),
                        "active": True,
                        "parameters": func.get("parameters", {}),
                    }
                ],
            }
        return tools_dict

    def prepare_tools_for_llm(self, tools_dict: Dict) -> List[Dict]:
        """Convert tool configs to LLM function schemas.

        Action names are kept clean for the LLM:
        - Unique action names appear as-is (e.g. ``get_weather``).
        - Duplicate action names are disambiguated with the owning tool's
          name (e.g. ``brave_search``, ``duckduckgo_search``); a numeric
          suffix only breaks ties between same-named tools.
        - Every name is clamped to the 64-character provider limit.

        A reverse mapping is stored in ``_name_to_tool`` so that tool calls
        can be routed back to the correct ``(tool_id, action_name)`` without
        brittle string splitting.
        """
        # Pass 1: collect entries and count action name occurrences
        # (tool_id, tool_name, action_name, action, is_client)
        entries: List[Tuple[str, str, str, Dict, bool]] = []
        name_counts: Counter = Counter()
        # A builtin can arrive twice: once as the user's stored row (keyed by
        # list index in ``_get_user_tools``) and once as the synthesized default
        # (keyed by uuid5). Pass 2 then hands the model two indistinguishable
        # copies with mangled names (``artifact_generator_create_artifact`` +
        # ``…_1``). The two rows are NOT byte-identical — a stored row has been
        # through ``transform_actions``, which stamps ``active``/``filled_by_llm``
        # onto every action — so the key is (tool name, action name).
        #
        # Which copy survives is load-bearing: a stored builtin row CAN carry
        # per-row config even though ``get_config_requirements() == {}``, and
        # ``code_executor`` keeps its approval gate there. Insertion order is
        # the agent's ``tool_ids`` click order on the agent paths, so it must
        # not decide this — stored rows are considered before synthesized ones,
        # and a row that requires approval always beats one that does not. Safe
        # only for builtins; two MCP rows can legitimately share a name and must
        # stay distinct.
        seen_actions: Dict[Tuple[str, str, bool], Tuple[int, bool]] = {}
        dedupable = _dedupable_tool_names()

        # Stable sort: preserves the caller's order within each group.
        ordered_tools = sorted(tools_dict.items(), key=lambda kv: is_synthesized_tool_id(kv[0]))

        for tool_id, tool in ordered_tools:
            is_api = tool["name"] == "api_tool"
            is_client = tool.get("client_side", False)

            if is_api and "actions" not in tool.get("config", {}):
                continue
            if not is_api and "actions" not in tool:
                continue

            actions = tool["config"]["actions"].values() if is_api else tool["actions"]

            for action in actions:
                if not action.get("active", True):
                    continue
                tool_name = tool.get("name", "")
                if tool_name in dedupable:
                    fingerprint = (tool_name, action["name"], is_client)
                    requires_approval = _requires_approval(tool, action)
                    kept = seen_actions.get(fingerprint)
                    if kept is not None:
                        kept_index, kept_approval = kept
                        if requires_approval and not kept_approval:
                            # Never let a duplicate registration drop an
                            # approval gate the user configured.
                            entries[kept_index] = (
                                tool_id,
                                tool_name,
                                action["name"],
                                action,
                                is_client,
                            )
                            seen_actions[fingerprint] = (kept_index, True)
                            logger.debug(
                                "duplicate_tool_registration_promoted",
                                extra={"tool_name": tool_name, "action_name": action["name"]},
                            )
                        else:
                            logger.debug(
                                "duplicate_tool_registration_collapsed",
                                extra={"tool_name": tool_name, "action_name": action["name"]},
                            )
                        continue
                    seen_actions[fingerprint] = (len(entries), requires_approval)
                entries.append((tool_id, tool_name, action["name"], action, is_client))
                name_counts[action["name"]] += 1

        # Pass 2: assign LLM-visible names and build mappings
        self._name_to_tool = {}
        self._tool_to_name = {}
        all_llm_names: set = set()

        result = []
        for tool_id, tool_name, action_name, action, is_client in entries:
            if name_counts[action_name] == 1 and len(action_name) <= _MAX_LLM_NAME_LEN:
                llm_name = action_name
            else:
                # An over-long unique name skips the prefix — it needs
                # truncation, not disambiguation.
                prefix = _sanitize_tool_prefix(tool_name) if name_counts[action_name] > 1 else ""
                base = f"{prefix}_{action_name}" if prefix and not action_name.startswith(f"{prefix}_") else action_name
                base = base[:_MAX_LLM_NAME_LEN]
                # A duplicated bare name stays ambiguous, and a candidate
                # must not steal a unique action's name or one already taken.
                candidate = base
                counter = 1
                while candidate == action_name or candidate in all_llm_names or name_counts.get(candidate, 0) == 1:
                    suffix = f"_{counter}"
                    candidate = base[: _MAX_LLM_NAME_LEN - len(suffix)] + suffix
                    counter += 1
                llm_name = candidate

            all_llm_names.add(llm_name)
            self._name_to_tool[llm_name] = (tool_id, action_name)
            self._tool_to_name[(tool_id, action_name)] = llm_name

            if is_client:
                params = action.get("parameters", {})
            else:
                params = self._build_tool_parameters(action)

            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": llm_name,
                        "description": action.get("description", ""),
                        "parameters": params,
                    },
                }
            )
        return result

    def _build_tool_parameters(self, action: Dict) -> Dict:
        params = {"type": "object", "properties": {}, "required": []}
        for param_type in ["query_params", "headers", "body", "parameters"]:
            if param_type in action and action[param_type].get("properties"):
                if action[param_type].get("additionalProperties") is False:
                    params["additionalProperties"] = False
                for k, v in action[param_type]["properties"].items():
                    if v.get("filled_by_llm", True):
                        params["properties"][k] = {
                            key: value for key, value in v.items() if key not in ("filled_by_llm", "value", "required")
                        }
                        if v.get("required", False):
                            params["required"].append(k)
        return params

    def _guardrail_tool_result(self, result: Any, tool_name: str, action_name: str) -> Any:
        """Scan a tool result before it fans out to the LLM, UI and journal.

        A tool result is untrusted third-party text on the same footing as a
        retrieved document, and it is a common exfiltration path for secrets
        that the calling API happened to echo back.
        """
        engine = getattr(self, "guardrail_engine", None)
        if engine is None or not engine.has_stage(GuardrailStage.TOOL_RESULT):
            return result
        if not isinstance(result, str) or not result:
            return result
        try:
            engine.context.tool_name = tool_name
            engine.context.action_name = action_name
            decision = engine.evaluate(result, GuardrailStage.TOOL_RESULT)
        except Exception:
            logger.exception("Tool-result guardrail failed for %s.%s", tool_name, action_name)
            return result
        return resolve_tool_result(result, decision)

    def check_pause(self, tools_dict: Dict, call, llm_class_name: str) -> Optional[Dict]:
        """Return a pending-action dict (approval / client / headless_denied) or None.

        In headless mode the dict's pause_type is ``headless_denied`` so the
        upstream loop synthesizes a tool result instead of pausing (nothing can
        resume a scheduled / webhook run).
        """
        parser = ToolActionParser(llm_class_name, name_mapping=self._name_to_tool)
        tool_id, action_name, call_args = parser.parse_args(call)
        call_id = getattr(call, "id", None) or str(uuid.uuid4())
        llm_name = getattr(call, "name", "")

        if tool_id is None or action_name is None or tool_id not in tools_dict:
            return None  # Will be handled as error by execute()

        tool_data = tools_dict[tool_id]
        arguments = call_args if isinstance(call_args, dict) else {}

        # Client-side tools
        if tool_data.get("client_side"):
            if self.headless:
                return {
                    "call_id": call_id,
                    "name": llm_name,
                    "tool_name": tool_data.get("name", "unknown"),
                    "tool_id": tool_id,
                    "action_name": action_name,
                    "llm_name": llm_name,
                    "arguments": arguments,
                    "pause_type": "headless_denied",
                    "deny_reason": ("Client-side tools cannot run in headless / scheduled runs."),
                    "error_type": "tool_not_allowed",
                    "thought_signature": getattr(call, "thought_signature", None),
                }
            return {
                "call_id": call_id,
                "name": llm_name,
                "tool_name": tool_data.get("name", "unknown"),
                "tool_id": tool_id,
                "action_name": action_name,
                "llm_name": llm_name,
                "arguments": arguments,
                "pause_type": "requires_client_execution",
                "thought_signature": getattr(call, "thought_signature", None),
            }

        # Approval required
        if tool_data["name"] == "api_tool":
            action_data = tool_data.get("config", {}).get("actions", {}).get(action_name, {})
        else:
            action_data = next(
                (a for a in tool_data.get("actions", []) if a["name"] == action_name),
                {},
            )

        require_approval = bool(action_data.get("require_approval"))
        # ``denylist_forced`` marks a prompt the hard denylist mandates; a
        # headless allowlist must never bypass it (see below).
        denylist_forced = False
        # ``remote_device`` decides per-invocation based on the live device
        # state (``approval_mode``, sticky patterns, allow/denylist). The
        # cached ``user_tools.actions[].require_approval`` snapshot does
        # not reflect later approval-mode changes nor command-level
        # heuristics, so consult the tool directly.
        if tool_data.get("name") == "remote_device":
            require_approval, denylist_forced = self._remote_device_requires_approval(
                tool_data,
                action_name,
                arguments,
            )
        elif tool_data.get("name") == "code_executor":
            # The deployment-level ``config.require_approval`` is authoritative
            # over the cached action snapshot, so consult the tool directly.
            require_approval = (
                self._code_executor_requires_approval(
                    tool_data,
                    action_name,
                    arguments,
                )
                or require_approval
            )

        if require_approval:
            if self.headless:
                tool_row_id = str(tool_data.get("id") or tool_id)
                # A denylist-forced prompt is never pre-authorizable: a
                # scheduled/headless run with the device allowlisted must
                # still be denied a denylisted command. Only non-forced
                # approvals honor the allowlist bypass.
                if tool_row_id in self.tool_allowlist and not denylist_forced:
                    # Pre-authorized for headless execution — fall through.
                    return None
                return {
                    "call_id": call_id,
                    "name": llm_name,
                    "tool_name": tool_data.get("name", "unknown"),
                    "tool_id": tool_id,
                    "action_name": action_name,
                    "llm_name": llm_name,
                    "arguments": arguments,
                    "pause_type": "headless_denied",
                    "deny_reason": ("This tool requires approval and is not in the run's tool_allowlist."),
                    "error_type": "tool_not_allowed",
                    "thought_signature": getattr(call, "thought_signature", None),
                }
            payload = {
                "call_id": call_id,
                "name": llm_name,
                "tool_name": tool_data.get("name", "unknown"),
                "tool_id": tool_id,
                "action_name": action_name,
                "llm_name": llm_name,
                "arguments": arguments,
                "pause_type": "awaiting_approval",
                "thought_signature": getattr(call, "thought_signature", None),
            }
            # Surface the device id so the approval UI can offer a
            # "don't ask again" sticky-pattern action for remote devices.
            if tool_data.get("name") == "remote_device":
                config = tool_data.get("config") or {}
                if config.get("device_id"):
                    payload["device_id"] = config["device_id"]
            return payload

        return None

    def _remote_device_requires_approval(
        self,
        tool_data: Dict,
        action_name: str,
        arguments: Dict,
    ) -> tuple[bool, bool]:
        """Live approval decision for a ``remote_device`` invocation.

        Instantiates ``RemoteDeviceTool`` with the cached config and the
        executor's user context, then asks it to evaluate the command.
        Returns ``(requires_approval, denylist_forced)``. Falls back to a
        denylist-forced prompt on any error so a misconfigured device never
        silently bypasses the prompt — not even via the headless allowlist.
        """
        try:
            from application.agents.tools.remote_device import RemoteDeviceTool

            tool = RemoteDeviceTool(
                config=tool_data.get("config") or {},
                user_id=self.user,
            )
            return tool.preview_decision(action_name, arguments)
        except Exception:
            logger.exception(
                "remote_device preview_decision failed; defaulting to a forced prompt",
            )
            return True, True

    def _code_executor_requires_approval(
        self,
        tool_data: Dict,
        action_name: str,
        arguments: Dict,
    ) -> bool:
        """Live approval decision for a ``code_executor`` invocation.

        Honors the deployment-level ``config.require_approval`` even when the
        cached action snapshot is stale. Fails closed (require approval) on any
        error so a misconfigured tool never silently runs untrusted code.
        """
        try:
            from application.agents.tools.code_executor import CodeExecutorTool

            tool = CodeExecutorTool(
                tool_config=tool_data.get("config") or {},
                user_id=self.user,
            )
            requires_approval, _forced = tool.preview_decision(action_name, arguments)
            return requires_approval
        except Exception:
            logger.exception(
                "code_executor preview_decision failed; defaulting to a prompt",
            )
            return True

    @staticmethod
    def _advertisable_action_names(tools_dict: Dict) -> set:
        """Action names a ``tools_dict`` would expose, mirroring pass 1 of
        :meth:`prepare_tools_for_llm`.

        The model calls ACTION names (``run_code``), never tool names
        (``code_executor``), so a fallback built from ``tool["name"]`` names
        strings that cannot resolve — feeding the very retry loop the
        correctable error exists to break.
        """
        names = set()
        for tool in (tools_dict or {}).values():
            tool = tool or {}
            if tool.get("name") == "api_tool":
                actions = (tool.get("config") or {}).get("actions") or {}
                actions = actions.values() if isinstance(actions, dict) else actions
            else:
                actions = tool.get("actions") or []
            for action in actions:
                if not isinstance(action, dict) or not action.get("active", True):
                    continue
                if action.get("name"):
                    names.add(str(action["name"]))
        return names

    def _available_tool_names(self, tools_dict: Dict, exclude: Optional[str] = None) -> str:
        """Render the names the model can actually call, for a correctable error.

        Prefer the LLM-visible action names assigned by
        :meth:`prepare_tools_for_llm` — those are the strings the model puts in
        a tool call. Fall back to tool names when the mapping has not been built
        (headless paths, tests). Never the internal tool ids: quoting those
        tells the model nothing about what to call instead.

        Narrowed to ``tools_dict`` so a call made with a restricted toolset is
        never told to call something out of scope, and capped: this string is
        returned as a tool RESULT, so it joins the message history and is
        re-sent on every later round. Uncapped, a large MCP fleet turns one
        failed call into kilobytes of prose duplicating the tool schema the
        provider already received.
        """
        scope = set(tools_dict or {})
        names = sorted(
            name
            for (tool_id, _action), name in self._tool_to_name.items()
            if not scope or tool_id in scope
        )
        if not names:
            names = sorted(self._advertisable_action_names(tools_dict or {}))
        names = [str(name) for name in names if name != exclude]
        if len(names) > self.MAX_ADVERTISED_TOOL_NAMES:
            hidden = len(names) - self.MAX_ADVERTISED_TOOL_NAMES
            names = names[: self.MAX_ADVERTISED_TOOL_NAMES] + [f"and {hidden} more"]
        return ", ".join(names) if names else "(none available)"

    # After this many unresolvable calls to the same name, refuse rather than
    # re-run.
    UNRESOLVABLE_CALL_LIMIT = 2

    # Cap on names rendered into a failed-call result; see
    # :meth:`_available_tool_names`.
    MAX_ADVERTISED_TOOL_NAMES = 30

    def execute(self, tools_dict: Dict, call, llm_class_name: str):
        """Execute a tool call. Yields status events, returns (result, call_id)."""
        parser = ToolActionParser(llm_class_name, name_mapping=self._name_to_tool)
        tool_id, action_name, call_args = parser.parse_args(call)
        llm_name = getattr(call, "name", "unknown")

        call_id = getattr(call, "id", None) or str(uuid.uuid4())
        unresolvable = tool_id is None or action_name is None or tool_id not in tools_dict

        # A tool the model invented will never resolve, so re-running it just
        # burns the turn's iteration budget on an identical failure. From the
        # third attempt on, hand back a directive message instead of the generic
        # error. Scoped to an unknown *name*: a registered tool whose arguments
        # merely failed to decode is recoverable, and refusing it would strand a
        # working tool for the rest of the turn.
        #
        # Keyed on the NAME ALONE. Keying on the payload too made the guard a
        # no-op in the case it exists for: told a call failed, a model varies
        # its arguments on the next attempt, minting a fresh counter every
        # round and never reaching the limit. Arguments cannot rescue an
        # unknown name anyway — ``ToolActionParser`` resolves from ``call.name``
        # only — and the "two different malformed bodies" case this used to
        # protect belongs to REGISTERED tools, which the
        # ``llm_name not in self._name_to_tool`` gate already excludes.
        if unresolvable and llm_name not in self._name_to_tool:
            failures = self._unresolvable_calls.get(llm_name, 0)
            # Count before refusing, so the message and the log escalate rather
            # than freezing at the limit for the rest of the turn.
            self._unresolvable_calls[llm_name] = failures + 1
            if failures >= self.UNRESOLVABLE_CALL_LIMIT:
                repeated = (
                    f"'{llm_name}' has already failed {failures} times and will keep "
                    f"failing — it is not a tool that exists. Stop calling it and "
                    f"either use a different tool "
                    f"({self._available_tool_names(tools_dict, exclude=llm_name)}) or answer without one."
                )
                logger.warning(
                    "tool_call_repeated_failure",
                    extra={"llm_tool_name": llm_name, "call_id": call_id, "failures": failures},
                )
                tool_call_data = {
                    "tool_name": "unknown",
                    "call_id": call_id,
                    "action_name": llm_name,
                    "arguments": call_args if isinstance(call_args, dict) else {},
                    "result": repeated,
                    "status": "error",
                }
                # Journal it like the branches below, so a hallucination storm
                # is not under-counted in the analytics used to size it.
                if _record_proposed(
                    call_id,
                    "unknown",
                    llm_name or "unknown",
                    call_args if isinstance(call_args, dict) else {},
                    message_id=self.message_id,
                    user_id=self.user,
                    agent_id=self.agent_id,
                ):
                    _mark_failed(
                        call_id,
                        repeated,
                        message_id=self.message_id,
                        user_id=self.user,
                    )
                yield {"type": "tool_call", "data": {**tool_call_data, "status": "error"}}
                self.tool_calls.append(tool_call_data)
                return repeated, call_id

        if tool_id is None or action_name is None:
            # Say which half actually failed. Reporting a name problem for a
            # registered tool whose arguments were merely malformed is what sent
            # one production investigation down the wrong path.
            name_is_known = llm_name in self._name_to_tool
            parse_reason = (
                "its arguments were not a valid JSON object"
                if name_is_known
                else "the tool name could not be resolved and its arguments were not a JSON object"
            )
            logger.error(
                "tool_call_parse_failed",
                extra={
                    "llm_class_name": llm_class_name,
                    "llm_tool_name": llm_name,
                    "call_id": call_id,
                },
            )

            tool_call_data = {
                "tool_name": "unknown",
                "call_id": call_id,
                "action_name": llm_name,
                "arguments": call_args or {},
                "result": (
                    f"Could not run '{llm_name}': {parse_reason}. "
                    f"Available tools: {self._available_tool_names(tools_dict)}."
                ),
                "status": "error",
            }
            # Journal the malformed call so it still shows up in tool analytics.
            if _record_proposed(
                call_id,
                "unknown",
                llm_name or "unknown",
                call_args if isinstance(call_args, dict) else {},
                message_id=self.message_id,
                user_id=self.user,
                agent_id=self.agent_id,
            ):
                _mark_failed(
                    call_id,
                    tool_call_data["result"],
                    message_id=self.message_id,
                    user_id=self.user,
                )
            yield {"type": "tool_call", "data": {**tool_call_data, "status": "error"}}
            self.tool_calls.append(tool_call_data)
            return tool_call_data["result"], call_id

        if tool_id not in tools_dict:
            logger.error(
                "tool_id_not_found",
                extra={
                    "tool_id": tool_id,
                    "llm_tool_name": llm_name,
                    "call_id": call_id,
                    "available_tool_count": len(tools_dict),
                },
            )

            tool_call_data = {
                "tool_name": "unknown",
                "call_id": call_id,
                "action_name": llm_name,
                "arguments": call_args,
                "result": (
                    f"Could not run '{llm_name}': no such tool. "
                    f"Available tools: {self._available_tool_names(tools_dict)}."
                ),
                "status": "error",
            }
            # Journal the unresolvable call so it still shows up in tool analytics.
            if _record_proposed(
                call_id,
                "unknown",
                llm_name or "unknown",
                call_args if isinstance(call_args, dict) else {},
                message_id=self.message_id,
                user_id=self.user,
                agent_id=self.agent_id,
            ):
                _mark_failed(
                    call_id,
                    tool_call_data["result"],
                    message_id=self.message_id,
                    user_id=self.user,
                )
            yield {"type": "tool_call", "data": {**tool_call_data, "status": "error"}}
            self.tool_calls.append(tool_call_data)
            return tool_call_data["result"], call_id

        tool_call_data = {
            "tool_name": tools_dict[tool_id]["name"],
            "call_id": call_id,
            "action_name": llm_name,
            "arguments": call_args,
        }
        tool_data = tools_dict[tool_id]
        # Surface the device id on remote_device tool-call events so the
        # approval UI can wire up the sticky "don't ask again" button.
        if tool_data.get("name") == "remote_device":
            config = tool_data.get("config") or {}
            if config.get("device_id"):
                tool_call_data["device_id"] = config["device_id"]
        # Journal first so the reconciler sees malformed calls and any
        # subsequent ``_mark_failed`` actually updates a real row.
        proposed_ok = _record_proposed(
            call_id,
            tool_data["name"],
            action_name,
            call_args if isinstance(call_args, dict) else {},
            tool_id=tool_data.get("id"),
            message_id=self.message_id,
            user_id=self.user,
            agent_id=self.agent_id,
        )
        # Defensive guard: a non-dict ``call_args`` (e.g. malformed
        # JSON on the resume path) would crash the param walk below
        # with AttributeError on ``.items()``. Surface a clean error
        # event and flip the journal row to ``failed`` instead of
        # killing the stream.
        if not isinstance(call_args, dict):
            error_message = f"Tool call arguments must be a JSON object, got {type(call_args).__name__}."
            tool_call_data["result"] = error_message
            tool_call_data["arguments"] = {}
            tool_call_data["status"] = "error"
            if proposed_ok:
                _mark_failed(
                    call_id, error_message, message_id=self.message_id, user_id=self.user
                )
            yield {
                "type": "tool_call",
                "data": {**tool_call_data, "status": "error"},
            }
            self.tool_calls.append(tool_call_data)
            return error_message, call_id
        yield {"type": "tool_call", "data": {**tool_call_data, "status": "pending"}}
        action_data = (
            tool_data["config"]["actions"][action_name]
            if tool_data["name"] == "api_tool"
            else next(action for action in tool_data["actions"] if action["name"] == action_name)
        )

        query_params, headers, body, parameters = {}, {}, {}, {}
        param_types = {
            "query_params": query_params,
            "headers": headers,
            "body": body,
            "parameters": parameters,
        }

        for param_type, target_dict in param_types.items():
            if param_type in action_data and action_data[param_type].get("properties"):
                for param, details in action_data[param_type]["properties"].items():
                    if param not in call_args and "value" in details and details["value"]:
                        target_dict[param] = details["value"]
        for param, value in call_args.items():
            for param_type, target_dict in param_types.items():
                if param_type in action_data and param in action_data[param_type].get("properties", {}):
                    target_dict[param] = value

        # Load tool (with caching)
        tool = self._get_or_load_tool(
            tool_data,
            tool_id,
            action_name,
            headers=headers,
            query_params=query_params,
        )

        if tool is None:
            error_message = (
                f"Failed to load tool '{tool_data.get('name')}' (tool_id key={tool_id}): missing 'id' on tool row."
            )
            logger.error(
                "tool_load_failed",
                extra={
                    "tool_name": tool_data.get("name"),
                    "tool_id": tool_id,
                    "action_name": action_name,
                    "call_id": call_id,
                },
            )
            tool_call_data["result"] = error_message
            tool_call_data["status"] = "error"
            if proposed_ok:
                _mark_failed(
                    call_id, error_message, message_id=self.message_id, user_id=self.user
                )
            yield {"type": "tool_call", "data": {**tool_call_data}}
            self.tool_calls.append(tool_call_data)
            return error_message, call_id

        resolved_arguments = (
            {"query_params": query_params, "headers": headers, "body": body}
            if tool_data["name"] == "api_tool"
            else parameters
        )
        try:
            if tool_data["name"] == "api_tool":
                logger.debug(
                    "Executing api: %s with query_params: %s, headers: %s, body: %s",
                    action_name,
                    _redact_args_for_log(query_params),
                    _redact_args_for_log(headers),
                    _redact_args_for_log(body),
                )
                result = tool.execute_action(action_name, **body)
            else:
                logger.debug(
                    "Executing tool: %s with args: %s",
                    action_name,
                    _redact_args_for_log(call_args),
                )
                result = tool.execute_action(action_name, **parameters)
        except Exception as exc:
            if proposed_ok:
                _mark_failed(
                    call_id, str(exc), message_id=self.message_id, user_id=self.user
                )
            raise

        # Single fan-out point: from here ``result`` reaches the LLM copy,
        # the conversation row, tool_call_attempts, and the stream event —
        # sanitize once so every lane gets clean text.
        result = sanitize_tool_result(result)
        result = self._guardrail_tool_result(result, tool_data.get("name", ""), action_name)

        get_artifact_id = getattr(tool, "get_artifact_id", None) if tool_data["name"] != "api_tool" else None

        artifact_id = None
        if callable(get_artifact_id):
            try:
                artifact_id = get_artifact_id(action_name, **parameters)
            except Exception:
                logger.exception(
                    "Failed to extract artifact_id from tool %s for action %s",
                    tool_data["name"],
                    action_name,
                )

        artifact_id = str(artifact_id).strip() if artifact_id is not None else ""
        if artifact_id:
            tool_call_data["artifact_id"] = artifact_id

        # A single call can produce several files (``run_code`` writing more
        # than one). ``artifact_id`` names only the first, which left the rest
        # with no way into the UI, so report the full set with display names.
        get_artifacts = (
            getattr(tool, "get_artifacts", None)
            if tool_data["name"] != "api_tool"
            else None
        )
        if callable(get_artifacts):
            artifacts = []
            try:
                # Normalize inside the guard: a tool returning an unexpected
                # shape must not break the call it just completed.
                artifacts = [
                    {
                        "id": str(a["id"]).strip(),
                        "filename": a.get("filename"),
                        "ref": a.get("ref"),
                    }
                    for a in (get_artifacts(action_name, **parameters) or [])
                    if isinstance(a, dict) and a.get("id")
                ]
            except Exception:
                logger.exception(
                    "Failed to extract artifacts from tool %s for action %s",
                    tool_data["name"],
                    action_name,
                )
            if artifacts:
                tool_call_data["artifacts"] = artifacts
        result_full = bound_result_full(str(result))
        tool_call_data["resolved_arguments"] = resolved_arguments
        tool_call_data["result_full"] = result_full
        tool_call_data["result"] = truncate_tool_result(result_full)
        # A tool that ran but reported failure in-band persists as ``error``,
        # not ``completed`` -- the model saw an error and will likely retry.
        tool_call_data["status"] = result_status(result)

        # Tool side effect has run; flip the journal row so the
        # message-finalize path can later confirm it. If the proposed
        # write failed (DB outage), upsert a fresh row in ``executed`` so
        # the reconciler still sees the side effect.
        _mark_executed(
            call_id,
            result_full,
            message_id=self.message_id,
            artifact_id=artifact_id or None,
            proposed_ok=proposed_ok,
            tool_name=tool_data["name"],
            action_name=action_name,
            arguments=call_args,
            tool_id=tool_data.get("id"),
            user_id=self.user,
            agent_id=self.agent_id,
        )

        stream_tool_call_data = {
            key: value for key, value in tool_call_data.items() if key not in {"result_full", "resolved_arguments"}
        }
        yield {"type": "tool_call", "data": {**stream_tool_call_data}}
        self.tool_calls.append(tool_call_data)

        return result, call_id

    def _get_or_load_tool(
        self,
        tool_data: Dict,
        tool_id: str,
        action_name: str,
        headers: Optional[Dict] = None,
        query_params: Optional[Dict] = None,
    ):
        """Load a tool, using cache when possible."""
        cache_key = f"{tool_data['name']}:{tool_id}:{self.user or ''}"
        if cache_key in self._loaded_tools:
            cached = self._loaded_tools[cache_key]
            # A tool cached on an earlier turn carries that turn's attachments;
            # refresh them so a chat attachment added this turn is bridgeable.
            cached_config = getattr(cached, "config", None)
            if isinstance(cached_config, dict) and self.conversation_id:
                # Refresh unconditionally so a turn with no attachments clears the
                # prior turn's list (no stale carryover within the session).
                cached_config["attachments"] = self.attachments or []
            return cached

        tm = ToolManager(config={})

        if tool_data["name"] == "api_tool":
            action_config = tool_data["config"]["actions"][action_name]
            tool_config = {
                "url": action_config["url"],
                "method": action_config["method"],
                "headers": headers or {},
                "query_params": query_params or {},
            }
            if "body_content_type" in action_config:
                tool_config["body_content_type"] = action_config.get("body_content_type", "application/json")
                tool_config["body_encoding_rules"] = action_config.get("body_encoding_rules", {})
        else:
            tool_config = tool_data["config"].copy() if tool_data["config"] else {}
            # Credentials are PBKDF2-bound to the tool OWNER's sub, not the
            # invoker's. Decrypt with the tool row's user_id so a team member
            # running an owner's shared tool authenticates with the owner's
            # credentials (deliberate delegation — see teams-spec OQ2), and so
            # the long-standing agent-key path (tools resolved by owner) stops
            # silently decrypt-failing. Falls back to self.user for the
            # agentless path where the tool row carries no user_id.
            tool_owner = tool_data.get("user_id") or self.user
            if tool_config.get("encrypted_credentials") and tool_owner:
                if tool_owner != self.user:
                    # Credential delegation: the invoker is running a shared
                    # tool with the owner's secrets. Audit it (the agent-run
                    # authorization upstream is the access boundary).
                    logger.info(
                        "tool_credential_delegation",
                        extra={
                            "invoker": self.user,
                            "tool_owner": tool_owner,
                            "tool_id": str(tool_data.get("id") or tool_id),
                            "tool_name": tool_data.get("name"),
                            "agent_id": self.agent_id,
                        },
                    )
                decrypted = decrypt_credentials(tool_config["encrypted_credentials"], tool_owner)
                tool_config.update(decrypted)
                tool_config["auth_credentials"] = decrypted
                tool_config.pop("encrypted_credentials", None)
            row_id = tool_data.get("id")
            if not row_id:
                logger.error(
                    "tool_missing_row_id",
                    extra={
                        "tool_name": tool_data.get("name"),
                        "tool_id": tool_id,
                        "action_name": action_name,
                    },
                )
                return None
            tool_config["tool_id"] = str(row_id)
            if self.conversation_id:
                tool_config["conversation_id"] = self.conversation_id
                if self.message_id:
                    tool_config["message_id"] = self.message_id
                # Carry the request's own attachments so sandbox tools can
                # lazily bridge a referenced chat attachment (conversation
                # scope only; workflow nodes bridge attachments up front).
                if self.attachments:
                    tool_config["attachments"] = self.attachments
            # Workflow agent nodes run-scope their artifact tools so a short
            # ref (A1) and edit_artifact resolve against the workflow run.
            if self.workflow_run_id:
                tool_config["workflow_run_id"] = self.workflow_run_id
            if tool_data["name"] == "scheduler":
                # Agent-bound: stamp schedules.agent_id. Agentless: the tool
                # falls back to ``origin_conversation_id`` as the schedule's
                # conversation home.
                tool_config["agent_id"] = str(self.agent_id) if self.agent_id else None
            if tool_data["name"] == "mcp_tool":
                tool_config["query_mode"] = True

        tool = tm.load_tool(
            tool_data["name"],
            tool_config=tool_config,
            user_id=self.user,
        )

        # Don't cache api_tool since config varies by action
        if tool_data["name"] != "api_tool":
            self._loaded_tools[cache_key] = tool

        return tool

    # Keys the client needs that are not part of the fixed shape below. They are
    # small and optional, and are copied only when present so an ordinary tool
    # call does not grow null columns in every persisted row.
    _PRESERVED_TOOL_CALL_KEYS = ("artifacts", "device_id")

    def get_truncated_tool_calls(self) -> List[Dict]:
        """Project tool calls into the shape that is streamed and persisted.

        This is what the client reloads, so anything dropped here is live-only
        and vanishes when the conversation is reopened. ``result_full`` and
        ``resolved_arguments`` are shed deliberately — they are the untruncated
        copies this projection exists to remove — but ``artifacts`` and
        ``device_id`` were omitted by oversight, which cost a multi-file
        ``run_code`` all but its first download chip on reload and left the
        remote-device approval UI without the id it keys its sticky action on.
        """
        projected = []
        for tool_call in self.tool_calls:
            entry = {
                "tool_name": tool_call.get("tool_name"),
                "call_id": tool_call.get("call_id"),
                "action_name": tool_call.get("action_name"),
                "arguments": tool_call.get("arguments"),
                "artifact_id": tool_call.get("artifact_id"),
                "result": truncate_tool_result(tool_call.get("result")),
                "status": tool_call.get("status", "completed"),
            }
            for key in self._PRESERVED_TOOL_CALL_KEYS:
                value = tool_call.get(key)
                if value:
                    entry[key] = value
            projected.append(entry)
        return projected
