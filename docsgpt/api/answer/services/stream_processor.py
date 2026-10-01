import datetime
import functools
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set, Tuple, TypeVar

from flask import after_this_request

from docsgpt import tracing
from docsgpt.agents.agent_creator import AgentCreator
from docsgpt.api.answer.services.compression import CompressionOrchestrator
from docsgpt.api.answer.services.compression.token_counter import TokenCounter
from docsgpt.api.answer.services.compression.types import is_compression_summary_row
from docsgpt.api.answer.services.conversation_service import ConversationService
from docsgpt.error import bounded_error_text
from docsgpt.prompts.composer import compose_preset, is_composed_preset
from docsgpt.api.answer.services.prompt_renderer import (
    PromptRenderer,
    format_docs_for_prompt,
    prompt_embeds_documents,
    resolve_prompt_skeleton,
)
from docsgpt.agents.attachment_budget import (
    compute_attachment_budget,
    manifest_estimate,
    plan_attachments,
)
from docsgpt.agents.context_overflow import ContextOverflowError, turn_message_budget
from docsgpt.agents.turn_capabilities import build_turn_capabilities
from docsgpt.core.model_utils import (
    get_api_key_for_provider,
    get_default_model_id,
    get_model_capabilities,
    get_provider_from_model_id,
    get_token_limit,
    validate_model_id,
)
from docsgpt.agents.tools.wiki import apply_resume_caller_rules, outside_edits_allowed
from docsgpt.core.settings import settings
from docsgpt.guardrails.config import AgentConfig
from sqlalchemy import text as sql_text

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_scope import TeamScopeRepository
from docsgpt.api.user.team_sharing import can_access
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.storage.db.source_config import SourceConfig
from docsgpt.retriever.dispatcher import build_dispatcher
from docsgpt.retriever.retriever_creator import RetrieverCreator
from docsgpt.utils import (
    calculate_doc_token_budget,
    limit_chat_history,
)

logger = logging.getLogger(__name__)


def is_external_api_caller(data: Dict[str, Any], decoded_token: Optional[Dict], owner: Optional[str]) -> bool:
    """Whether a request calls an agent with its API key on someone else's behalf.

    Widget and API requests carry the agent's key and run as its owner. The
    owner previewing their own agent in the app sends the key too, but is
    signed in as that owner. In local mode without auth everyone is the same
    user, so there is no one else to tell apart.

    Args:
        data: The request body.
        decoded_token: The caller's token before the key's owner replaces it.
        owner: The agent owner's user id.
    """
    if not data.get("api_key"):
        return False
    caller = (decoded_token or {}).get("sub")
    return not caller or caller != owner


def multimodal_reaches_model(model_id: Optional[str], user_id: Optional[str]) -> bool:
    """Whether a request's multimodal content array is sent to the model as is.

    ``create_agent`` forwards it only to OpenAI-family providers; others get
    the text question, which message building can shorten.

    Args:
        model_id: The turn's model.
        user_id: The BYOM resolution scope.

    Returns:
        True when the array reaches the provider unshortened.
    """
    try:
        from docsgpt.llm.openai import OpenAILLM
        from docsgpt.llm.providers import PROVIDERS_BY_NAME

        provider = (
            get_provider_from_model_id(model_id, user_id=user_id) if model_id else None
        ) or settings.LLM_PROVIDER
        plugin = PROVIDERS_BY_NAME.get(str(provider).lower())
        llm_class = getattr(plugin, "llm_class", None)
        return isinstance(llm_class, type) and issubclass(llm_class, OpenAILLM)
    except Exception:
        return False


def _position(query: Dict[str, Any], fallback: int) -> int:
    """A conversation message's position, else its index in the loaded list."""
    position = query.get("position")
    return position if isinstance(position, int) and not isinstance(position, bool) else fallback


def _clamp_chunks(value: int) -> int:
    """Bound top-k to the range ``RetrievalConfig`` enforces, keeping 0.

    Both the request body and agent config took ``chunks`` unbounded, so a
    caller could ask for an arbitrary number of chunks. ``0`` is preserved
    because callers use it to suppress retrieval entirely
    (``classic_rag.py`` treats 0 as "skip"); negatives collapse to it.
    """
    return max(0, min(int(value), 500))


def get_prompt(prompt_id: str, prompts_collection=None) -> str:
    """Get a prompt by preset name or Postgres ID (UUID or legacy ObjectId).

    The ``prompts_collection`` parameter is retained for backwards
    compatibility with call sites that still pass it positionally; it is
    ignored post-cutover.
    """
    del prompts_collection  # unused — retained for call-site compatibility
    # Callers may pass a ``uuid.UUID`` (from a PG ``prompt_id`` column) or a
    # plain string ("default"/"creative"/legacy ObjectId). Normalise to str
    # so both the preset lookup and the UUID-vs-legacy branching work.
    # ``None`` / empty means "use the default prompt" — agents that never
    # set a custom prompt land here (PG ``agents.prompt_id`` is NULL).
    if prompt_id is None or prompt_id == "":
        prompt_id = "default"
    elif not isinstance(prompt_id, str):
        prompt_id = str(prompt_id)
    # The chat presets are assembled from shared fragments (see
    # ``docsgpt/prompts/composer.py``); only ``reduce`` is still a
    # standalone file.
    if is_composed_preset(prompt_id):
        return compose_preset(prompt_id)

    if prompt_id == "reduce":
        file_path = Path(__file__).resolve().parents[3] / "prompts" / "chat_reduce_prompt.txt"
        try:
            return file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise FileNotFoundError(f"Prompt file not found: {file_path}")
    try:
        with db_readonly() as conn:
            repo = PromptsRepository(conn)
            prompt_doc = None
            if looks_like_uuid(prompt_id):
                prompt_doc = repo.get_for_rendering(prompt_id)
            if prompt_doc is None:
                prompt_doc = repo.get_by_legacy_id(prompt_id)
        if not prompt_doc:
            raise ValueError(f"Prompt with ID {prompt_id} not found")
        return prompt_doc["content"]
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Invalid prompt ID: {prompt_id}") from e


_PROMPT_PRESETS_WITHOUT_ROW = ("reduce",)

# Tools whose approval is decided per call from live state, not the stored
# ``require_approval`` flags (see ``ToolExecutor.check_pause``).
_LIVE_APPROVAL_TOOLS = frozenset({"remote_device", "code_executor"})


def authorized_prompt_id(prompt_id: Any, principal: Optional[str], agent: Optional[dict] = None) -> Any:
    """``prompt_id`` if ``principal`` (or the agent's sponsor) may use it, else ``"default"``.

    Presets pass through. A custom prompt must be owned by ``principal`` or
    reach them through a team grant with ``use`` (checked live). On an agent
    run, a prompt the owner can't use still renders while the editor who
    attached it (its sponsor) qualifies. A revoked, deleted or foreign prompt
    falls back to the default prompt.

    Args:
        prompt_id: The configured prompt (preset name, UUID or legacy id).
        principal: The agent owner for an agent run, else the caller.
        agent: The agent row on an agent run, for its ``resource_sponsors``.

    Returns:
        The prompt id to render.
    """
    if prompt_id is None or prompt_id == "":
        return prompt_id
    pid = str(prompt_id)
    if is_composed_preset(pid) or pid in _PROMPT_PRESETS_WITHOUT_ROW:
        return prompt_id
    from docsgpt.api.user.resource_access import (
        REASON_OWNER_LOST_ACCESS,
        log_stopped,
        ref_access,
    )

    # The same check the agent page's run state uses: the principal, else a
    # live sponsor on the agent.
    holder = {**agent, "user_id": principal} if agent and agent.get("id") else {"user_id": principal}
    try:
        with db_readonly() as conn:
            access = ref_access(conn, "agent", holder, "prompt", pid) if principal else None
    except Exception:
        logger.exception("Prompt access check failed for %s", pid)
        access = None
    if access is not None and access.principal:
        return prompt_id
    log_stopped(
        "agent" if agent else "chat", holder, "prompt", pid,
        access.reason if access is not None else REASON_OWNER_LOST_ACCESS,
    )
    return "default"


def _agent_source_doc(conn: Any, sources_repo: Any, agent: dict, source_id: Any) -> Optional[dict]:
    """The source row an agent may retrieve from, or None.

    Authorized as the owner (owned or team-shared to them), else as the
    editor who attached it while they still qualify. Read unscoped once
    authorized: an owner-scoped read misses a team-shared source.
    """
    from docsgpt.api.user.resource_access import log_stopped, ref_access

    access = ref_access(conn, "agent", agent, "source", str(source_id))
    if not access.principal:
        log_stopped("agent", agent, "source", source_id, access.reason)
        return None
    return sources_repo.get_by_id(str(source_id))


def authorized_agent_sources(conn: Any, agent: dict) -> Tuple[Optional[dict], List[dict]]:
    """The source rows an agent run retrieves from: primary first, then extras.

    Each is authorized like :func:`_agent_source_doc` (the owner, else the
    editor who attached it), and a source listed twice appears once.

    Args:
        conn: An open database connection.
        agent: The ``agents`` row.

    Returns:
        The primary source row (None when unset or not usable) and every
        usable row in run order.
    """
    sources_repo = SourcesRepository(conn)
    primary: Optional[dict] = None
    rows: List[dict] = []
    seen: set = set()
    refs = [(True, agent.get("source_id"))]
    refs.extend((False, sid) for sid in agent.get("extra_source_ids") or [])
    for is_primary, sid_raw in refs:
        if not sid_raw:
            continue
        source_doc = _agent_source_doc(conn, sources_repo, agent, sid_raw)
        if not source_doc or str(source_doc["id"]) in seen:
            continue
        if is_primary:
            primary = source_doc
        seen.add(str(source_doc["id"]))
        rows.append(source_doc)
    return primary, rows


#: Agent types whose model searches sources on demand instead of reading a
#: pre-fetched document block.
SEARCHING_AGENT_TYPES = ("agentic", "research")


def agent_prompt_id(prompt_id: Any, agent_type: Optional[str]) -> Any:
    """The prompt a run of ``agent_type`` renders for ``prompt_id``.

    Agentic and research agents get the agentic variant of a preset (search
    tool guidance instead of a pre-fetched document block); custom prompt
    ids pass through. A missing id is the default preset.
    """
    prompt_id = prompt_id or "default"
    if agent_type in SEARCHING_AGENT_TYPES and prompt_id in ("default", "creative", "strict"):
        return f"agentic_{prompt_id}"
    return prompt_id


def source_exposure(retrieval: Any) -> str:
    """A source's exposure, defaulting to ``prefetch`` (D11)."""
    value = getattr(retrieval, "exposure", None)
    if value is None and isinstance(retrieval, dict):
        value = retrieval.get("exposure")
    return value or "prefetch"


def per_source_list(all_sources: Optional[List[Dict[str, Any]]], exposure: Optional[str] = None) -> list:
    """Each usable source as ``{"id", "retrieval"}``, optionally one exposure only.

    Args:
        all_sources: Source entries carrying ``id`` and ``retrieval``.
        exposure: ``prefetch`` or ``agentic_tool`` to keep only matching
            sources; None keeps them all.
    """
    entries = []
    for entry in all_sources or []:
        sid = entry.get("id")
        if not sid or sid == "default":
            continue
        retrieval = entry.get("retrieval")
        if exposure is not None and source_exposure(retrieval) != exposure:
            continue
        entries.append({"id": str(sid), "retrieval": retrieval})
    return entries


def source_for_docs(doc_ids: list) -> Dict[str, Any]:
    """A retriever ``source`` dict scoped to ``doc_ids``."""
    return {"active_docs": doc_ids} if doc_ids else {}


class SourceUse(NamedTuple):
    """How one run uses its agent's sources.

    Attributes:
        prefetch: Whether documents are pre-fetched into the prompt.
        exposure: The exposure pre-fetch is scoped to; None means every source.
        agentic_sources: The sources the ``internal_search`` tool is scoped
            to; None gives an agentic or research agent every source and a
            classic agent no search tool.
    """

    prefetch: bool
    exposure: Optional[str]
    agentic_sources: Optional[list]


def plan_source_use(agent_type: Optional[str], agentic_sources: list) -> SourceUse:
    """Decide pre-fetch and the search tool's scope from the ``agentic_tool`` sources (D11).

    With no source opted into ``agentic_tool``, agentic and research agents
    pre-fetch nothing and search every source on demand, while classic
    agents pre-fetch every source and get no search tool. Otherwise both
    pre-fetch the ``prefetch`` subset and search the ``agentic_tool`` subset.
    """
    if agentic_sources:
        return SourceUse(True, "prefetch", agentic_sources)
    if agent_type in SEARCHING_AGENT_TYPES:
        return SourceUse(False, None, None)
    return SourceUse(True, None, None)


def internal_search_config(
    agent_type: Optional[str],
    agentic_sources: Optional[list],
    all_sources: Optional[List[Dict[str, Any]]],
    source: Dict[str, Any],
    **settings_: Any,
) -> Optional[Dict[str, Any]]:
    """The ``retriever_config`` that gives a run its ``internal_search`` tool, or None.

    Args:
        agent_type: The agent's type.
        agentic_sources: ``SourceUse.agentic_sources``.
        all_sources: Every source entry of the run.
        source: The run's retriever ``source`` dict, used when the tool
            covers every source.
        **settings_: Retriever, model and identity fields passed through to
            the tool (``retriever_name``, ``chunks``, ``agent_id``, ...).
    """
    if agent_type not in SEARCHING_AGENT_TYPES and not agentic_sources:
        return None
    if agentic_sources is not None:
        tool_sources = agentic_sources
        tool_source = source_for_docs([entry["id"] for entry in tool_sources])
    else:
        tool_sources = per_source_list(all_sources)
        tool_source = source
    return {"source": tool_source, "sources": tool_sources, **settings_}


def _wiki_write_owner(conn: Any, source_id: str, caller: str) -> Optional[str]:
    """The owner id to write a wiki source as, when ``caller`` may edit it."""
    from docsgpt.api.user.resource_access import resolve

    ra = resolve(conn, "source", source_id, caller)
    return ra.owner_id if ra is not None and ra.can("edit") else None


#: Agent types that build a tools_dict and so can carry the Wiki tool.
WIKI_AGENT_TYPES = ("classic", "agentic", "research")


def wiki_tool_config(
    conn: Any,
    source_ids: List[Any],
    decoded_token: Optional[Dict[str, Any]],
    *,
    outside_caller: bool = False,
    approval_required: bool = False,
) -> Optional[Dict[str, Any]]:
    """The WikiTool config for the first wiki source the caller may edit, or None.

    A source qualifies when its ``kind`` is ``wiki`` and the token's user may
    ``edit`` it (owner or team editor; viewers get no tool), resolved live
    through ``resource_access``. One writable wiki per run: the scan stops at
    the first match.

    Args:
        conn: An open database connection.
        source_ids: The run's source ids, in run order.
        decoded_token: The principal the run acts as.
        outside_caller: The run is for someone other than that principal
            (API key, widget, webhook); it edits only when the wiki's owner
            allows outside edits, otherwise it gets only ``wiki_view``.
        approval_required: Every write waits for the caller's approval.
    """
    caller = (decoded_token or {}).get("sub")
    if not caller:
        return None
    repo = SourcesRepository(conn)
    for sid in source_ids:
        if not sid or sid == "default":
            continue
        sid = str(sid)
        owner = _wiki_write_owner(conn, sid, caller)
        if not owner:
            continue
        source_doc = repo.get_any(sid, owner)
        if not source_doc or SourceConfig.parse(source_doc.get("config")).kind != "wiki":
            continue
        return {
            "source_id": str(source_doc["id"]),
            "source_owner_id": owner,
            "decoded_token": decoded_token,
            "user": caller,
            "outside_caller": outside_caller,
            "writes_allowed": not outside_caller or outside_edits_allowed(source_doc),
            "approval_required": approval_required,
        }
    return None


T = TypeVar("T")


def _traced_setup(method: Callable[..., T]) -> Callable[..., T]:
    """Run a request-setup method inside the request's execution trace.

    Agent setup does real work worth seeing in the trace -- pre-fetch
    retrieval, history compression -- before ``complete_stream`` runs, so
    the trace is started here, in the request thread, and handed on.
    """

    @functools.wraps(method)
    def wrapper(self: "StreamProcessor", *args: Any, **kwargs: Any) -> T:
        trace = getattr(self, "trace", None)
        if trace is None:
            trace = tracing.start_trace(source=getattr(self, "trace_source", "stream"))
            self.trace = trace
        with tracing.activate(trace):
            try:
                return method(self, *args, **kwargs)
            finally:
                if trace is not None:
                    decoded = getattr(self, "decoded_token", None)
                    trace.bind(
                        request_id=getattr(self, "request_id", None),
                        user_id=decoded.get("sub") if isinstance(decoded, dict) else None,
                        agent_id=getattr(self, "agent_id", None),
                    )

    return wrapper


def flush_trace_after_request(processor: "StreamProcessor") -> None:
    """Write ``processor``'s setup trace when the request ends, unless it was claimed.

    Registered on the current request with ``after_this_request``; the hook
    always hands the response back unchanged and never raises.

    Args:
        processor: The request's processor.
    """

    @after_this_request
    def _flush(response: Any) -> Any:
        try:
            processor.flush_unclaimed_trace()
        except Exception:
            logger.warning("Could not write an unclaimed request trace", exc_info=True)
        return response


class StreamProcessor:
    def __init__(
        self,
        request_data: Dict[str, Any],
        decoded_token: Optional[Dict[str, Any]],
        trace_source: str = "stream",
        *,
        external_caller: bool = False,
    ):
        """Bind a request to its processor.

        Args:
            request_data: The request body.
            decoded_token: The caller's token; ``/v1`` passes the agent owner's.
            trace_source: The entry point the trace is stored under.
            external_caller: Set by the server for requests authenticated by
                an agent's API key whose token is the owner's (``/v1``), so
                the run keeps the key holder's write limits. Never read from
                the request body.
        """
        # Legacy attribute retained as None for any external callers that
        # introspect the processor; all DB access uses per-op connections.
        self.prompts_collection = None
        self.data = request_data
        self.decoded_token = decoded_token
        self.external_caller = bool(external_caller)
        self.initial_user_id = (
            self.decoded_token.get("sub") if self.decoded_token is not None else None
        )
        self.conversation_id = self.data.get("conversation_id")
        self.source = {}
        self.all_sources = []
        self.attachments = []
        # Rows of files attached on earlier turns (no text), in upload order.
        self.earlier_attachments: List[Dict[str, Any]] = []
        self.history = []
        self.retrieved_docs = []
        self.agent_config = {}
        self.retriever_config = {}
        self.is_shared_usage = False
        self.shared_token = None
        # Set by _get_agent_key: the caller reaches the agent only through its
        # public link (not its owner, no team grant).
        self.public_link_usage = False
        self.agent_id = self.data.get("agent_id")
        # Set by _get_agent_key once access checks pass; read for keyless runs.
        self._authorized_agent_row: Optional[Dict[str, Any]] = None
        self.agent_key = None
        self.model_id: Optional[str] = None
        # BYOM-resolution scope, set by _validate_and_set_model.
        self.model_user_id: Optional[str] = None
        # WAL placeholder id pulled from continuation state on resume.
        self.reserved_message_id: Optional[str] = None
        # Carried through resumes so multi-pause runs keep one request_id.
        self.request_id: Optional[str] = None
        # The request's execution trace, started by the first traced setup
        # step and handed to ``complete_stream``; ``trace_source`` names the
        # entry point it is stored under.
        self.trace: Optional[tracing.Trace] = None
        self.trace_source = trace_source
        self.conversation_service = ConversationService()
        self.compression_orchestrator = CompressionOrchestrator(
            self.conversation_service
        )
        self.prompt_renderer = PromptRenderer()
        self._prompt_content: Optional[str] = None
        self._persona: Optional[str] = None
        self._required_tool_actions: Optional[Dict[str, Set[Optional[str]]]] = None
        self.compressed_summary: Optional[str] = None
        self.compressed_summary_tokens: int = 0
        # When the conversation's history was last compressed (DB point or
        # one made this turn); the agent stamps it on the turn's metadata.
        self.last_compression_at: Optional[Any] = None
        self._agent_data: Optional[Dict[str, Any]] = None

    def initialize(self):
        """Initialize all required components for processing"""
        self._configure_agent()
        self._validate_and_set_model()
        self._configure_source()
        self._configure_retriever()
        # Attachments first: the history load sizes the turn (fit check,
        # compression threshold) with them.
        self._process_attachments()
        self._load_conversation_history()

    def handoff_trace(self) -> Optional[tracing.Trace]:
        """Hand the setup trace to a streaming ``complete_stream``.

        The stream writes the trace when it ends, after the view has
        returned; marking the hand-off stops :meth:`flush_unclaimed_trace`
        from writing it first.

        Returns:
            The trace to pass as ``complete_stream(trace=...)``.
        """
        self._trace_handed_off = True
        return getattr(self, "trace", None)

    def flush_unclaimed_trace(self) -> None:
        """Write the setup trace of a request that ended before streaming.

        A request refused after setup started (unauthorized, over its usage
        limit, a resume conflict, a setup error) still records what ran,
        marked ``error``. A trace the request already wrote, or handed to a
        stream, is left alone. Routes arrange this with
        :func:`flush_trace_after_request`.
        """
        if not getattr(self, "_trace_handed_off", False):
            tracing.flush(getattr(self, "trace", None), tracing.STATUS_ERROR)

    @_traced_setup
    def build_agent(self, question: str):
        """One call to go from request data to a ready-to-run agent.

        Combines initialize(), pre_fetch_docs(), pre_fetch_tools(), and
        create_agent() into a single convenience method. The request id is
        minted first so pre-fetch retrieval and its side-channel LLM calls
        share it with the rest of the turn. It is always generated here, never
        taken from the request body: request quotas count distinct request
        ids, so a client-chosen id would let every call count as one.

        A request with neither a token nor an agent API key has nobody to run
        for: nothing is set up (no pre-fetch runs the agent's tools), None is
        returned and the route answers 401.
        """
        if not self.decoded_token and not self.data.get("api_key"):
            return None
        if not getattr(self, "request_id", None):
            self.request_id = str(uuid.uuid4())
        self.initialize()

        agent_type = self.agent_config.get("agent_type", "classic")

        # Sources by exposure (D11), decided the same way for a headless run:
        # see ``plan_source_use``.
        _, agentic_sources = self._exposure_partition()
        use = plan_source_use(agent_type, agentic_sources)
        docs_together, docs_list = None, None
        if use.prefetch:
            docs_together, docs_list = self.pre_fetch_docs(question, exposure=use.exposure)
        tools_data = self.pre_fetch_tools()
        return self.create_agent(
            docs_together=docs_together,
            docs=docs_list,
            tools_data=tools_data,
            agentic_sources=use.agentic_sources,
        )

    @_traced_setup
    def build_continuation_from_messages(self, messages, tool_actions):
        """Rebuild a tool continuation from the request messages (STATELESS).

        OpenAI-compatible clients (opencode, etc.) resend the full conversation
        -- system, user, assistant(tool_calls), tool(results) -- but carry no
        conversation_id, so there is no server-side ``pending_tool_state`` to
        load. Reconstruct the agent + continuation context directly from the
        resent messages and return the same tuple as ``resume_from_tool_actions``:
        (agent, messages, tools_dict, pending_tool_calls, tool_actions,
        reasoning_content).
        """
        # Locate the last assistant message that issued tool calls.
        pending_idx = None
        for i in range(len(messages) - 1, -1, -1):
            m = messages[i]
            if m.get("role") == "assistant" and m.get("tool_calls"):
                pending_idx = i
                break
        if pending_idx is None:
            raise ValueError(
                "No assistant message with tool_calls found for continuation"
            )

        pending_tool_calls = []
        for tc in messages[pending_idx].get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments")
            try:
                args = (
                    json.loads(raw_args)
                    if isinstance(raw_args, str)
                    else (raw_args or {})
                )
            except (json.JSONDecodeError, TypeError):
                args = {}
            name = fn.get("name", "")
            pending_tool_calls.append(
                {
                    "call_id": tc.get("id", ""),
                    "name": name,
                    "tool_name": name,
                    "action_name": name,
                    "llm_name": name,
                    "arguments": args,
                }
            )

        # The conversation up to (but not including) the assistant tool_calls;
        # gen_continuation re-appends the assistant message + tool results.
        prior_messages = [dict(m) for m in messages[:pending_idx]]

        # Build a normal agent (config / LLM / client tools), no new question.
        agent = self.build_agent("")
        tools_dict = agent.tool_executor.get_tools()
        # The resent files arrive as attachment rows (the route converted the
        # parts): plan them against the resent messages, with the attachments
        # tool in the round, instead of replaying them raw.
        prepare_resent = getattr(agent, "prepare_resent_attachments", None)
        if callable(prepare_resent):
            prepare_resent(tools_dict, prior_messages)

        return agent, prior_messages, tools_dict, pending_tool_calls, tool_actions, ""

    def _load_conversation_history(self):
        """Load conversation history either from DB or request"""
        if self.conversation_id and self.initial_user_id:
            conversation = self.conversation_service.get_conversation(
                self.conversation_id, self.initial_user_id
            )
            if not conversation:
                raise ValueError("Conversation not found or unauthorized")

            self.earlier_attachments = self._with_request_earlier_attachments(
                self._load_earlier_attachments(conversation)
            )
            # Decide fit before compressing: a turn that cannot fit even with
            # no history fails here, without a compression call.
            self._ensure_turn_fits()

            # Check if compression is enabled and needed
            if settings.ENABLE_CONVERSATION_COMPRESSION:
                self._handle_compression(conversation)
            else:
                # Original behavior - load all history (include metadata if present)
                self.history = [
                    {
                        "prompt": query["prompt"],
                        "response": query["response"],
                        # Carry the persisted thought so _build_messages
                        # re-attaches it as reasoning_content on replay —
                        # DeepSeek thinking mode rejects follow-up turns
                        # whose prior assistant message dropped it.
                        **(
                            {"thought": query["thought"]}
                            if query.get("thought")
                            else {}
                        ),
                        **(
                            {"metadata": query["metadata"]}
                            if "metadata" in query
                            else {}
                        ),
                        **(
                            {"tool_calls": query["tool_calls"]}
                            if query.get("tool_calls")
                            else {}
                        ),
                    }
                    for query in conversation.get("queries", [])
                    if not is_compression_summary_row(query)
                ]
        else:
            self.earlier_attachments = self._with_request_earlier_attachments([])
            self._ensure_turn_fits()
            # model_user_id keeps history trim aligned with the BYOM's
            # actual context window instead of the default 128k.
            self.history = limit_chat_history(
                json.loads(self.data.get("history", "[]")),
                model_id=self.model_id,
                user_id=self.model_user_id,
            )

    def _handle_compression(self, conversation: Dict[str, Any]):
        """Handle conversation compression logic using orchestrator."""
        try:
            # initial_user_id for conversation access; model_user_id
            # for BYOM context-window / provider lookups.
            result = self.compression_orchestrator.compress_if_needed(
                conversation_id=self.conversation_id,
                user_id=self.initial_user_id,
                model_user_id=self.model_user_id,
                model_id=self.model_id,
                decoded_token=self.decoded_token,
                # The turn's own size, its planned attachments included, so
                # an attach-heavy turn compresses the history rather than
                # overflowing next to it.
                current_query_tokens=self._turn_token_estimate(),
            )

            if not result.success:
                logger.error(f"Compression failed: {result.error}, using full history")
                self.history = [
                    {
                        "prompt": query["prompt"],
                        "response": query["response"],
                        **(
                            {"thought": query["thought"]}
                            if query.get("thought")
                            else {}
                        ),
                        **({"metadata": query["metadata"]} if "metadata" in query else {}),
                        **(
                            {"tool_calls": query["tool_calls"]}
                            if query.get("tool_calls")
                            else {}
                        ),
                    }
                    for query in conversation.get("queries", [])
                    if not is_compression_summary_row(query)
                ]
                return

            if result.compressed_summary:
                self.compressed_summary = result.compressed_summary
                self.compressed_summary_tokens = TokenCounter.count_message_tokens(
                    [{"content": result.compressed_summary}]
                )
                logger.info(
                    f"Using compressed summary ({self.compressed_summary_tokens} tokens) "
                    f"+ {len(result.recent_queries)} recent messages"
                    + ("" if result.compression_performed else " (saved compression point)")
                )
            self.last_compression_at = result.last_compression_at

            self.history = result.as_history()
            # Preserve metadata from recent queries (as_history only has prompt/response)
            recent = [
                q
                for q in (result.recent_queries or conversation.get("queries", []))
                if not is_compression_summary_row(q)
            ]
            for i, entry in enumerate(self.history):
                # Match by index from the end of recent queries
                offset = len(recent) - len(self.history)
                qi = offset + i
                if 0 <= qi < len(recent) and "metadata" in recent[qi]:
                    entry["metadata"] = recent[qi]["metadata"]

        except Exception as e:
            logger.error(
                f"Error handling compression, falling back to standard history: {str(e)}",
                exc_info=True,
            )
            self.history = [
                {
                    "prompt": query["prompt"],
                    "response": query["response"],
                    **(
                        {"thought": query["thought"]}
                        if query.get("thought")
                        else {}
                    ),
                    **({"metadata": query["metadata"]} if "metadata" in query else {}),
                    **(
                        {"tool_calls": query["tool_calls"]}
                        if query.get("tool_calls")
                        else {}
                    ),
                }
                for query in conversation.get("queries", [])
            ]

    def _load_earlier_attachments(self, conversation: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Rows of the files attached on the conversation's earlier turns.

        On a retry or an edit (``index`` in the request), only the turns
        before the replaced one count.

        Args:
            conversation: The conversation, with its ``queries``.

        Returns:
            The caller's attachment rows (without their text), in upload
            order; an id seen twice is listed once.
        """
        ids: List[str] = []
        # A retry or an edit at ``index`` replaces that turn and drops every
        # later one: their files are not this conversation's earlier files.
        index = (getattr(self, "data", None) or {}).get("index")
        replaced_from = index if isinstance(index, int) and not isinstance(index, bool) and index >= 0 else None
        for position, query in enumerate(conversation.get("queries") or []):
            if not isinstance(query, dict) or is_compression_summary_row(query):
                continue
            if replaced_from is not None and _position(query, position) >= replaced_from:
                continue
            for attachment_id in query.get("attachments") or []:
                if attachment_id:
                    ids.append(str(attachment_id))
        if not ids:
            return []
        try:
            return self._fetch_attachment_rows(list(dict.fromkeys(ids)))
        except Exception as e:
            logger.error(f"Error loading earlier attachments: {e}", exc_info=True)
            return []

    def _is_v1_request(self) -> bool:
        return getattr(self, "trace_source", None) == "v1"

    def _with_request_earlier_attachments(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """``rows`` plus the files a stateless ``/v1`` client re-sent from earlier messages.

        The route marks the attachment ids of files that first appeared in
        a user message before the last one; the planner then lists them as
        earlier instead of inlining every re-sent file again each turn.

        Args:
            rows: The conversation's own earlier attachment rows.

        Returns:
            The rows, then the request's, each id once.
        """
        if not self._is_v1_request():
            return rows
        requested = [str(i) for i in (self.data or {}).get("earlier_attachments") or [] if i]
        known = {str(r.get("id")) for r in rows if isinstance(r, dict)}
        missing = [i for i in dict.fromkeys(requested) if i not in known]
        if not missing:
            return rows
        try:
            return [*rows, *self._fetch_attachment_rows(missing)]
        except Exception as e:
            logger.error("Error loading the request's earlier attachments: %s", bounded_error_text(e))
            return rows

    def _request_skipped_files(self) -> List[Dict[str, Any]]:
        """Files a ``/v1`` request sent that never became attachment rows, with the reason."""
        if not self._is_v1_request():
            return []
        return [s for s in (self.data or {}).get("skipped_files") or [] if isinstance(s, dict)]

    def _fetch_attachment_rows(self, ids: List[str]) -> List[Dict[str, Any]]:
        """The caller's attachment rows for ``ids``, metadata only."""
        with db_readonly() as conn:
            return AttachmentsRepository(conn).list_for_planning(ids, self.initial_user_id)

    def _window(self) -> int:
        """The turn's model window."""
        try:
            return int(
                get_token_limit(
                    getattr(self, "model_id", None), user_id=getattr(self, "model_user_id", None)
                )
            )
        except Exception:
            return int(settings.DEFAULT_LLM_TOKEN_LIMIT)

    def _multimodal_tokens(self) -> int:
        """Tokens of a multimodal content array that reaches the model unshortened."""
        content = (getattr(self, "data", None) or {}).get("multimodal_content")
        if not isinstance(content, list) or not content:
            return 0
        if not multimodal_reaches_model(
            getattr(self, "model_id", None), getattr(self, "model_user_id", None)
        ):
            return 0
        return TokenCounter.count_message_tokens([{"content": content}])

    def _question_tokens(self) -> int:
        """Tokens of the turn's own message."""
        from docsgpt.utils import num_tokens_from_string

        multimodal = self._multimodal_tokens()
        if multimodal:
            return multimodal
        question = (getattr(self, "data", None) or {}).get("question")
        return num_tokens_from_string(question) if isinstance(question, str) else 0

    def _system_prompt_tokens(self) -> int:
        """Estimated tokens of the system prompt, before rendering."""
        from docsgpt.utils import num_tokens_from_string

        try:
            override = (getattr(self, "data", None) or {}).get("system_prompt_override")
            agent_config = getattr(self, "agent_config", None) or {}
            if agent_config.get("allow_system_prompt_override") and isinstance(override, str):
                return num_tokens_from_string(override)
            prompt = self._get_prompt_content()
            return num_tokens_from_string(prompt) if isinstance(prompt, str) else 0
        except Exception:
            return 0

    def _preliminary_attachment_reserve(self) -> int:
        """Tokens the turn's attachments are expected to take, before the agent plans.

        Uses the planner the agent runs, with what is known before the tools
        are resolved: the model's registry capabilities and the share of the
        window attachments may take. The agent re-plans against the real
        free space once the history is settled.

        Returns:
            The planned content plus manifest, in tokens.
        """
        current = getattr(self, "attachments", None) or []
        earlier = getattr(self, "earlier_attachments", None) or []
        if not current and not earlier:
            return 0
        try:
            window = self._window()
            caps = get_model_capabilities(
                getattr(self, "model_id", None), user_id=getattr(self, "model_user_id", None)
            ) or {}
            capabilities = build_turn_capabilities(
                supported_attachment_types=caps.get("supported_attachment_types") or [],
                tool_calling=bool(caps.get("supports_tools")),
                server_tools={},
                window=window,
                is_v1=getattr(self, "trace_source", None) == "v1",
                sandbox_available=False,
            )
            plan = plan_attachments(
                current,
                capabilities,
                budget=compute_attachment_budget(
                    window=window, share=float(settings.ATTACHMENT_BUDGET_SHARE)
                ),
                earlier=earlier,
                max_native_parts=int(settings.ATTACHMENT_MAX_NATIVE_PARTS),
            )
            return plan.reserved_tokens
        except Exception as e:
            logger.warning(f"Could not estimate the turn's attachments: {e}")
            return 0

    def _turn_token_estimate(self) -> int:
        """The turn's own size for the compression threshold: question plus attachments."""
        try:
            return self._question_tokens() + self._preliminary_attachment_reserve()
        except Exception as e:
            logger.warning(f"Could not size the turn for compression: {e}")
            return 500

    def _ensure_turn_fits(self) -> None:
        """Refuse a turn whose own content cannot fit, before any compression.

        Counts only the turn itself: the system prompt, the attachment
        manifest and the turn's message (a multimodal content array, or the
        plain question). History never counts, since it is compressed or
        pruned. The message gets the budget message building gives it, so a
        message that passes here is never cut later. Files that do not fit
        are planned partial or left out, so they cannot make a turn
        impossible.

        Raises:
            ContextOverflowError: Before any compression or provider call.
        """
        window = self._window()
        file_count = len(getattr(self, "attachments", None) or []) + len(
            getattr(self, "earlier_attachments", None) or []
        )
        fixed = self._system_prompt_tokens() + manifest_estimate(file_count)
        own = self._question_tokens()
        budget = max(turn_message_budget(window, fixed), 0)
        needed = fixed + own
        if needed >= window or own > budget:
            available = min(fixed + budget, window)
            raise ContextOverflowError(
                f"This message needs about {needed:,} tokens, more than the "
                f"model can take for one message ({available:,} of its "
                f"{window:,} tokens), even without any conversation history. "
                f"Shorten the message or send fewer or smaller files.",
                needed_tokens=needed,
                available_tokens=available,
                stage="pre_compression",
            )

    def _process_attachments(self):
        """Process any attachments in the request"""
        attachment_ids = self.data.get("attachments", [])
        self.attachments = self._get_attachments_content(
            attachment_ids, self.initial_user_id
        )

    def _get_attachments_content(self, attachment_ids, user_id):
        if not attachment_ids:
            return []
        attachments = []
        try:
            with db_readonly() as conn:
                repo = AttachmentsRepository(conn)
                for attachment_id in attachment_ids:
                    try:
                        attachment_doc = repo.get_any(str(attachment_id), user_id)
                        if attachment_doc:
                            attachments.append(attachment_doc)
                    except Exception as e:
                        logger.error(
                            f"Error retrieving attachment {attachment_id}: {e}",
                            exc_info=True,
                        )
                # A zip is followed by the files the worker unpacked from it.
                attachments = repo.expand_archives(attachments, user_id)
        except Exception as e:
            logger.error(f"Error opening attachments connection: {e}", exc_info=True)
        return attachments

    def _validate_and_set_model(self):
        """Pick model_id with agent authority on agent-bound chats."""
        from docsgpt.core.model_settings import ModelRegistry

        requested_model = self.data.get("model_id")
        # Caller picks from their own BYOM layer; agent defaults resolve
        # under the owner's layer (shared agents have caller != owner).
        caller_user_id = self.initial_user_id
        owner_user_id = self.agent_config.get("user_id") or caller_user_id

        # Agent-bound: agent's default_model_id wins, body's model_id is dropped.
        agent_bound = self._agent_data is not None
        if agent_bound:
            agent_default_model = self.agent_config.get("default_model_id", "")
            if agent_default_model and validate_model_id(
                agent_default_model, user_id=owner_user_id
            ):
                self.model_id = agent_default_model
                self.model_user_id = owner_user_id
            else:
                self.model_id = get_default_model_id()
                self.model_user_id = None
            return

        if requested_model:
            if not validate_model_id(requested_model, user_id=caller_user_id):
                registry = ModelRegistry.get_instance()
                available_models = [
                    m.id
                    for m in registry.get_enabled_models(user_id=caller_user_id)
                ]
                raise ValueError(
                    f"Invalid model_id '{requested_model}'. "
                    f"Available models: {', '.join(available_models[:5])}"
                    + (
                        f" and {len(available_models) - 5} more"
                        if len(available_models) > 5
                        else ""
                    )
                )
            self.model_id = requested_model
            self.model_user_id = caller_user_id
        else:
            self.model_id = get_default_model_id()
            self.model_user_id = None

    def _get_agent_key(self, agent_id: Optional[str], user_id: Optional[str]) -> tuple:
        """Get API key for agent with access control."""
        if not agent_id:
            return None, False, None
        try:
            with db_readonly() as conn:
                # Lookup without user scoping — access control is done
                # against ``user_id`` / ``shared_with`` / ``shared`` flags
                # below, matching the legacy Mongo semantics.
                repo = AgentsRepository(conn)
                agent = None
                if looks_like_uuid(str(agent_id)):
                    result = conn.execute(
                        sql_text(
                            "SELECT * FROM agents WHERE id = CAST(:id AS uuid)"
                        ),
                        {"id": str(agent_id)},
                    )
                    row = result.fetchone()
                    if row is not None:
                        agent = row_to_dict(row)
                if agent is None:
                    agent = repo.get_by_legacy_id(str(agent_id))
                if agent is None:
                    raise Exception("Agent not found")
                agent_owner = agent.get("user_id")
                is_owner = agent_owner == user_id
                is_shared_with_user = bool(agent.get("shared", False))

                # Team-shared agents are runnable by any member with a grant
                # (viewer is enough to run). Resolved live against team_members
                # on the SAME connection so a revoked grant/membership denies on
                # the next call; resolution failure fails closed. Checked on a
                # public agent too: a teammate there is not a link user.
                is_team_shared = False
                if not is_owner and user_id:
                    try:
                        is_team_shared = TeamScopeRepository(conn).can_read(
                            user_id, "agent", str(agent["id"])
                        )
                    except Exception:
                        logger.error(
                            "team access check failed for agent run", exc_info=True
                        )
                        is_team_shared = False

            if not (is_owner or is_shared_with_user or is_team_shared):
                raise Exception("Unauthorized access to the agent")
            self.public_link_usage = not (is_owner or is_team_shared)
            # Authorized. Keep the row so _configure_agent can run a draft
            # agent, which has key = NULL, from it.
            self._authorized_agent_row = agent
            if is_owner:
                now = datetime.datetime.now(datetime.timezone.utc)
                try:
                    with db_session() as conn:
                        AgentsRepository(conn).update(
                            str(agent["id"]), agent_owner,
                            {"last_used_at": now},
                        )
                except Exception:
                    logger.warning(
                        "Failed to update last_used_at for agent",
                        exc_info=True,
                    )
            return (
                str(agent["key"]) if agent.get("key") else None,
                not is_owner,
                agent.get("shared_token"),
            )
        except Exception as e:
            logger.error(f"Error in get_agent_key: {str(e)}", exc_info=True)
            raise

    def _get_data_from_api_key(self, api_key: str) -> Dict[str, Any]:
        """Resolve agent metadata + the unioned source set for the given key."""
        with db_readonly() as conn:
            agent = AgentsRepository(conn).find_by_key(api_key)
            if not agent:
                raise Exception("Invalid API Key, please generate a new key", 401)
            return self._agent_run_data(conn, agent)

    def _agent_run_data(self, conn: Any, agent: Dict[str, Any]) -> Dict[str, Any]:
        """An agent row as the run reads it: owner identity plus the unioned source set.

        Args:
            conn: An open database connection.
            agent: The authorized ``agents`` row, keyed or a keyless draft.
        """
        # The repo dict uses "user_id" — the streaming path expects
        # a "user" key (legacy Mongo shape) for identity propagation.
        data: Dict[str, Any] = dict(agent)
        data["user"] = agent.get("user_id")

        # Active sources = primary ∪ extras, primary first, deduplicated.
        # ``_configure_source`` ignores an empty ``data["sources"]``,
        # so the primary must appear in the union too — not only in
        # the legacy ``data["source"]`` slot.
        primary, source_docs = authorized_agent_sources(conn, agent)
        # ``sources`` row may have NULL ``retriever``/``chunks`` — fall back to
        # the agent's value (``dict.get`` returns None even when the key
        # exists with value None). The primary's own values win for the agent.
        data["source"] = str(primary["id"]) if primary else None
        if primary:
            if primary.get("retriever"):
                data["retriever"] = primary["retriever"]
            if primary.get("chunks") is not None:
                data["chunks"] = primary["chunks"]
        sources_list: list = [
            {
                "id": str(source_doc["id"]),
                "retriever": source_doc.get("retriever") or "classic",
                "chunks": (
                    source_doc["chunks"] if source_doc.get("chunks") is not None
                    else data.get("chunks", "6")
                ),
                # Per-source behaviour contract (lenient read).
                "retrieval": SourceConfig.parse(source_doc.get("config")).retrieval,
            }
            for source_doc in source_docs
        ]
        data["sources"] = sources_list
        data["default_model_id"] = data.get("default_model_id", "")
        return data

    def _configure_source(self):
        """Configure the source based on agent data.

        The literal string ``"default"`` is a legacy placeholder (older
        clients sent it for "no ingested source") and is normalized to an
        empty source so that no retrieval is attempted.
        """
        if self._agent_data:
            agent_data = self._agent_data

            if agent_data.get("sources") and len(agent_data["sources"]) > 0:
                source_ids = [
                    source["id"]
                    for source in agent_data["sources"]
                    if source.get("id") and source["id"] != "default"
                ]
                if source_ids:
                    self.source = {"active_docs": source_ids}
                else:
                    self.source = {}
                self.all_sources = [
                    s for s in agent_data["sources"] if s.get("id") != "default"
                ]
            elif agent_data.get("source") and agent_data["source"] != "default":
                self.source = {"active_docs": agent_data["source"]}
                # Carry the per-source retrieval contract (lenient read) so this
                # legacy single-source path matches the unioned-sources path and
                # the dispatcher still sees per-source overrides. A
                # missing/invalid id falls back to default config, never crashes.
                owner = agent_data.get("user_id")
                source_doc = None
                try:
                    with db_readonly() as conn:
                        source_doc = SourcesRepository(conn).get(
                            str(agent_data["source"]), owner
                        )
                except Exception:
                    source_doc = None
                self.all_sources = [
                    {
                        "id": agent_data["source"],
                        "retriever": agent_data.get("retriever", "classic"),
                        "retrieval": SourceConfig.parse(
                            (source_doc or {}).get("config")
                        ).retrieval,
                    }
                ]
            else:
                self.source = {}
                self.all_sources = []
            return
        if "active_docs" in self.data:
            active_docs = self.data["active_docs"]
            if active_docs and active_docs != "default":
                # The retriever queries ``self.source["active_docs"]``, so it
                # must carry only the ids the caller may actually read — the
                # authorized set that _load_request_sources resolved, not the
                # raw client input.
                self.all_sources = self._load_request_sources(active_docs)
                allowed = [entry["id"] for entry in self.all_sources]
                if not allowed:
                    self.source = {}
                elif isinstance(active_docs, list):
                    self.source = {"active_docs": allowed}
                else:
                    self.source = {"active_docs": allowed[0]}
            else:
                self.source = {}
                self.all_sources = []
            return
        self.source = {}
        self.all_sources = []

    def _load_request_sources(self, active_docs) -> list:
        """Per-source list (with each source's retrieval config) for a non-agent
        request, so per-source overrides (exposure, chunks, ...) are honored on
        the default chat just like the agent path. Lenient read: a missing or
        inaccessible source falls back to default config and never raises.
        """
        owner = self.initial_user_id
        ids = active_docs if isinstance(active_docs, list) else [active_docs]
        sources = []
        for sid in ids:
            if not sid or sid == "default":
                continue
            # AUTHORIZATION. ``active_docs`` is client-supplied, and the
            # retriever queries ``WHERE source_id = <id>`` with no owner
            # predicate — so an unchecked id read another tenant's documents
            # straight into the answer. The config read below is owner-scoped
            # but was lenient on a miss, which let the id through anyway.
            # ``/api/sources/<id>/search`` and ``/api/get_chunks`` already gate
            # on this helper; the answer path must use the same gate.
            # No principal means no basis to authorize anything, so client-
            # supplied ids are dropped outright. Gating this behind ``if owner``
            # left a bypass: a signed token with no ``sub`` claim skipped the
            # check entirely and streamed the source text back.
            if not owner:
                logger.warning(
                    "Dropping source %s: request has no authenticated principal.",
                    sid,
                )
                continue
            try:
                with db_readonly() as conn:
                    permitted = can_access(conn, "source", str(sid), owner)
            except Exception:
                # Fail closed: a check we could not complete is not permission
                # to read someone's documents.
                logger.warning("Access check failed for source %s; dropping it.", sid)
                continue
            if not permitted:
                logger.warning(
                    "Dropping source %s from request: %s has no access.", sid, owner
                )
                continue

            # Config is best-effort: a blip here must not drop an authorized
            # source, it just falls back to the default retrieval config.
            # Read unscoped — ``can_access`` has already passed, and the
            # owner-scoped read misses for a team grantee, silently costing
            # them the source's configured chunks/exposure.
            source_doc = None
            try:
                with db_readonly() as conn:
                    source_doc = SourcesRepository(conn).get_by_id(str(sid))
            except Exception:
                source_doc = None
            sources.append(
                {
                    "id": sid,
                    "retrieval": SourceConfig.parse(
                        (source_doc or {}).get("config")
                    ).retrieval,
                }
            )
        return sources

    def _has_active_docs(self) -> bool:
        """Return True if a real document source is configured for retrieval."""
        active_docs = self.source.get("active_docs") if self.source else None
        if not active_docs:
            return False
        if active_docs == "default":
            return False
        return True

    def _resolve_agent_id(self) -> Optional[str]:
        """Resolve agent_id from request, then fall back to conversation context."""
        request_agent_id = self.data.get("agent_id")
        if request_agent_id:
            return str(request_agent_id)

        if not self.conversation_id or not self.initial_user_id:
            return None

        try:
            conversation = self.conversation_service.get_conversation(
                self.conversation_id, self.initial_user_id
            )
        except Exception:
            return None

        if not conversation:
            return None

        conversation_agent_id = conversation.get("agent_id")
        if conversation_agent_id:
            return str(conversation_agent_id)

        return None

    def _configure_agent(self):
        """Configure the agent based on request data.

        Unified flow: resolve the effective API key, then extract config once.
        """
        agent_id = self._resolve_agent_id()

        self.agent_key, self.is_shared_usage, self.shared_token = self._get_agent_key(
            agent_id, self.initial_user_id
        )
        self.agent_id = str(agent_id) if agent_id else None
        self.agent_config["public_link_caller"] = bool(
            self.agent_id and getattr(self, "public_link_usage", False)
        )

        # Determine the effective API key (explicit > agent-derived)
        effective_key = self.data.get("api_key") or self.agent_key
        # A draft agent has no key yet but is still that agent: its prompt,
        # model, type, sources and tools, read from the row _get_agent_key
        # already authorized.
        draft_row = None if effective_key else getattr(self, "_authorized_agent_row", None)

        if effective_key or draft_row:
            if effective_key:
                self._agent_data = self._get_data_from_api_key(effective_key)
            else:
                with db_readonly() as conn:
                    self._agent_data = self._agent_run_data(conn, draft_row)
            if self._agent_data.get("_id"):
                self.agent_id = str(self._agent_data.get("_id"))

            self.agent_config.update(
                {
                    # The agent runs in its owner's context: its prompt must
                    # be one the owner may use (re-checked on every run).
                    "prompt_id": authorized_prompt_id(
                        self._agent_data.get("prompt_id", "default"),
                        self._agent_data.get("user"),
                        self._agent_data,
                    ),
                    "agent_type": self._agent_data.get("agent_type", settings.AGENT_NAME),
                    "user_api_key": effective_key,
                    "json_schema": self._agent_data.get("json_schema"),
                    "default_model_id": self._agent_data.get("default_model_id", ""),
                    "models": self._agent_data.get("models", []),
                    "allow_system_prompt_override": self._agent_data.get(
                        "allow_system_prompt_override", False
                    ),
                    # Owner identity — _validate_and_set_model reads this to
                    # resolve owner-stored BYOM default_model_id against the
                    # owner's per-user model layer rather than the caller's.
                    "user_id": self._agent_data.get("user"),
                    # Per-agent behavior contract (guardrails). The floor is
                    # applied at agent construction, not here.
                    "config": self._agent_data.get("config") or {},
                }
            )

            # Set identity context
            owner = self._agent_data.get("user")
            self.agent_config["external_api_caller"] = getattr(self, "external_caller", False) or (
                is_external_api_caller(self.data, self.decoded_token, owner)
            )
            self.agent_config["api_write_allowlist"] = AgentConfig.parse(
                self._agent_data.get("config")
            ).api_write_allowlist
            if self.data.get("api_key"):
                # External API key: use the key owner's identity
                self.initial_user_id = self._agent_data.get("user")
                self.decoded_token = {"sub": self._agent_data.get("user")}
            elif self.is_shared_usage:
                # Shared agent: keep the caller's identity
                pass
            else:
                # Owner using their own agent
                self.decoded_token = {"sub": self._agent_data.get("user")}

            # PG row exposes the workflow as ``workflow_id`` (UUID column);
            # legacy Mongo shape used the key ``workflow``. Accept either so
            # API-key-invoked workflow agents bind correctly downstream.
            wf_ref = self._agent_data.get("workflow") or self._agent_data.get(
                "workflow_id"
            )
            if wf_ref:
                self.agent_config["workflow"] = str(wf_ref)
                self.agent_config["workflow_owner"] = self._agent_data.get("user")
        else:
            # No agent — default/workflow configuration.
            agent_type = settings.AGENT_NAME
            if self.data.get("workflow") and isinstance(
                self.data.get("workflow"), dict
            ):
                agent_type = "workflow"
                self.agent_config["workflow"] = self.data["workflow"]
                if isinstance(self.decoded_token, dict):
                    self.agent_config["workflow_owner"] = self.decoded_token.get("sub")
                # A saved workflow id alongside the embedded graph (builder
                # Preview) lets the run persist a ``workflow_runs`` row so its
                # artifacts are listable + authz'd; ownership is re-checked on
                # save, so a forged id for another user's workflow never persists.
                preview_workflow_id = self.data.get("workflow_id")
                if preview_workflow_id:
                    self.agent_config["workflow_id"] = str(preview_workflow_id)

            caller = self.decoded_token.get("sub") if isinstance(self.decoded_token, dict) else None
            self.agent_config.update(
                {
                    "prompt_id": authorized_prompt_id(self.data.get("prompt_id", "default"), caller),
                    "agent_type": agent_type,
                    "user_api_key": None,
                    "json_schema": None,
                    "default_model_id": "",
                }
            )

        # Per-request structured output: a ``response_format`` / ``response_schema``
        # in the request (surfaced by the v1 translator as ``json_schema``) overrides
        # the agent's configured schema for this call. Invalid schemas are ignored
        # downstream by the agent (normalize_json_schema_payload).
        request_json_schema = self.data.get("json_schema")
        if request_json_schema is not None:
            self.agent_config["json_schema"] = request_json_schema
        if self.data.get("json_schema_strict") is not None:
            self.agent_config["json_schema_strict"] = self.data.get("json_schema_strict")
        if self.data.get("json_object"):
            self.agent_config["json_object"] = True
            # An explicit json_object request beats an agent-configured schema
            # (otherwise the configured json_schema would silently override it).
            self.agent_config["json_schema"] = None

    def _configured_source_chunks(self) -> Optional[int]:
        """Return the top-k a source explicitly configured, or None.

        Only an *explicit* ``retrieval.chunks`` counts. A source left at
        defaults returns None so the request body still applies — otherwise
        every unconfigured source would silently clamp callers to the schema
        default.
        """
        from docsgpt.storage.db.source_config import RetrievalConfig

        default_chunks = RetrievalConfig().chunks
        values = {
            _clamp_chunks(entry["retrieval"].chunks)
            for entry in (self.all_sources or [])
            if getattr(entry.get("retrieval"), "chunks", default_chunks) != default_chunks
        }
        if not values:
            return None
        # Several configured sources in one request: the largest wins so no
        # source is under-served by another's tighter setting.
        return max(values)

    def _configure_retriever(self):
        """Assemble retriever config; agent's values are authoritative when bound."""
        # BYOM scope: owner for shared-agent BYOM, caller for own BYOM,
        # None for built-ins. Without ``user_id`` here, the doc budget
        # falls back to settings.DEFAULT_LLM_TOKEN_LIMIT and overfills
        # the upstream context window for any small (e.g. 8k/32k) BYOM.
        doc_token_limit = calculate_doc_token_budget(
            model_id=self.model_id, user_id=self.model_user_id
        )

        retriever_name = "classic"
        chunks = 6

        if self._agent_data is not None:
            # Agent-bound: agent wins, body's retriever/chunks are dropped.
            if self._agent_data.get("retriever"):
                retriever_name = self._agent_data["retriever"]
            if self._agent_data.get("chunks") is not None:
                try:
                    chunks = _clamp_chunks(int(self._agent_data["chunks"]))
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid agent chunks value: {self._agent_data['chunks']}, "
                        "using default value 6"
                    )
        else:
            if "retriever" in self.data:
                retriever_name = self.data["retriever"]
            if "chunks" in self.data:
                try:
                    chunks = _clamp_chunks(int(self.data["chunks"]))
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid request chunks value: {self.data['chunks']}, "
                        "using default value 6"
                    )
            # A source that configured its own retrieval knobs outranks the
            # request body: the owner tuned top-k for that corpus, a client
            # should not be able to override it per call.
            source_chunks = self._configured_source_chunks()
            if source_chunks is not None:
                chunks = source_chunks

        self.retriever_config = {
            "retriever_name": retriever_name,
            "chunks": chunks,
            "doc_token_limit": doc_token_limit,
        }

        # isNoneDoc forces no retrieval on an agentless chat only; an agent,
        # keyed or draft, searches its own sources.
        agent_bound = bool(self.data.get("api_key") or self.agent_key or self._agent_data is not None)
        if not agent_bound and "isNoneDoc" in self.data and self.data["isNoneDoc"]:
            self.retriever_config["chunks"] = 0

    def _build_per_source_list(self, exposure: Optional[str] = None) -> list:
        """Canonical per-source list with each source's resolved retrieval cfg.

        Each entry is ``{"id": str, "retrieval": RetrievalConfig}``. Empty when
        no per-source detail is known (single-source / no-config requests), in
        which case the Dispatcher reduces to the legacy single classic group.

        Args:
            exposure: When set (``prefetch`` / ``agentic_tool``), include only
                sources whose resolved ``retrieval.exposure`` matches; a missing
                config defaults to ``prefetch``. When None, include all sources.
        """
        return per_source_list(self.all_sources, exposure)

    @staticmethod
    def _exposure_of(retrieval) -> str:
        """Resolve a source's exposure, defaulting to ``prefetch`` (D11)."""
        return source_exposure(retrieval)

    def _build_wiki_config(self) -> Optional[Dict[str, Any]]:
        """Resolve the WikiTool config for the first writable wiki source.

        See :func:`wiki_tool_config`. Returns None when no writable wiki
        source is present.

        An API-key or widget run (``outside_caller``) acts as the agent's
        owner, so it gets the edit actions only when the wiki's owner turned
        on ``wiki_outside_edits``; otherwise ``writes_allowed`` is False and
        the tool offers only ``wiki_view``. A public-link visitor runs as
        themselves, so they reach only wikis they may edit anyway; the switch
        doesn't apply to them, but each of their edits waits for their
        approval (``approval_required``), so the agent's prompt or sources
        can't steer the model into changing their wiki unasked.
        """
        if not (self.decoded_token or {}).get("sub"):
            return None
        # Processors built without __init__ (tests, resume helpers) lack these.
        run_config = getattr(self, "agent_config", None) or {}
        outside_caller = bool(
            run_config.get("external_api_caller") or getattr(self, "external_caller", False)
        )
        try:
            with db_readonly() as conn:
                return wiki_tool_config(
                    conn,
                    [entry.get("id") for entry in self.all_sources or []],
                    self.decoded_token,
                    outside_caller=outside_caller,
                    approval_required=bool(run_config.get("public_link_caller")),
                )
        except Exception:
            logger.exception("Failed to resolve wiki tool config")
            return None

    def _source_for_docs(self, doc_ids: list) -> Dict[str, Any]:
        """Build a ClassicRAG-style source dict scoped to ``doc_ids``."""
        return source_for_docs(doc_ids)

    def _exposure_partition(self) -> tuple[list, list]:
        """Split the per-source list into (prefetch, agentic_tool) subsets.

        Honored only by the agentic/research path (D11). When no source carries
        a config, every source defaults to ``prefetch`` so behavior is unchanged.
        """
        prefetch = self._build_per_source_list(exposure="prefetch")
        agentic = self._build_per_source_list(exposure="agentic_tool")
        return prefetch, agentic

    def create_retriever(self, exposure: Optional[str] = None):
        """Build the (dispatching) retriever for pre-fetch.

        When ``exposure`` is given, only the matching subset of sources is
        retrieved and the dispatcher's source list is scoped to it; the global
        ``self.source`` (used as the fallback group) is also narrowed so a
        mixed agentic agent pre-fetches just the ``prefetch`` sources.
        """
        per_source = self._build_per_source_list(exposure=exposure)
        if exposure is not None:
            source = self._source_for_docs([e["id"] for e in per_source])
        else:
            source = self.source
        retriever_kwargs = dict(
            source=source,
            chat_history=self.history,
            prompt=get_prompt(self.agent_config["prompt_id"], self.prompts_collection),
            chunks=self.retriever_config["chunks"],
            doc_token_limit=self.retriever_config.get("doc_token_limit", 50000),
            model_id=self.model_id,
            model_user_id=self.model_user_id,
            user_api_key=self.agent_config["user_api_key"],
            agent_id=self.agent_id,
            decoded_token=self.decoded_token,
            request_id=self.request_id or self.data.get("request_id"),
        )

        def _legacy_classic():
            return RetrieverCreator.create_retriever(
                self.retriever_config["retriever_name"], **retriever_kwargs
            )

        # Dispatcher routes each source to its configured retriever and merges
        # under one shared budget; the kill-switch falls back to the single
        # legacy retriever (PER_SOURCE_RETRIEVAL_ENABLED=False).
        return build_dispatcher(
            _legacy_classic,
            sources=per_source,
            **retriever_kwargs,
        )

    def pre_fetch_docs(
        self, question: str, exposure: Optional[str] = None
    ) -> tuple[Optional[str], Optional[list]]:
        """Pre-fetch documents for template rendering before agent creation.

        ``exposure`` scopes pre-fetch to the matching source subset (D11); when
        None all active docs are retrieved (classic agents, unchanged).
        """
        if self.data.get("isNoneDoc", False) and not self.agent_id:
            logger.info("Pre-fetch skipped: isNoneDoc=True")
            return None, None
        if not self._has_active_docs():
            logger.info("Pre-fetch skipped: no active docs configured")
            return None, None
        if exposure is not None and not self._build_per_source_list(
            exposure=exposure
        ):
            logger.info("Pre-fetch skipped: no %s sources", exposure)
            return None, None
        try:
            retriever = self.create_retriever(exposure=exposure)
            logger.info(
                f"Pre-fetching docs with chunks={retriever.chunks}, doc_token_limit={retriever.doc_token_limit}"
            )
            docs = retriever.search(question)
            logger.info(f"Pre-fetch retrieved {len(docs) if docs else 0} documents")

            if not docs:
                logger.info("Pre-fetch: No documents returned from search")
                return None, None
            self.retrieved_docs = docs

            docs_together = format_docs_for_prompt(docs)

            logger.info(f"Pre-fetch docs_together size: {len(docs_together)} chars")

            return docs_together, docs
        except Exception as e:
            logger.error(f"Failed to pre-fetch docs: {str(e)}", exc_info=True)
            return None, None

    def pre_fetch_tools(self) -> Optional[Dict[str, Any]]:
        """Pre-fetch tool data for template rendering before agent creation.

        Runs the actions the prompt template names on the toolset the agent
        run gets, so a teammate or public-link user renders the owner's
        prompt with the owner's tools, never their own.

        Returns:
            Action results keyed by tool name and tool id, or None when
            nothing was fetched.
        """
        if not settings.ENABLE_TOOL_PREFETCH:
            logger.info(
                "Tool pre-fetching disabled globally via ENABLE_TOOL_PREFETCH setting"
            )
            return None

        if self.data.get("disable_tool_prefetch", False):
            logger.info("Tool pre-fetching disabled for this request")
            return None

        required_tool_actions = self._get_required_tool_actions()
        filtering_enabled = required_tool_actions is not None

        try:
            user_id = self.initial_user_id or "local"
            outside_caller = bool(
                self.agent_config.get("external_api_caller") or self.agent_config.get("public_link_caller")
            )
            # The same toolset the run gets: an agent's own tools (resolved as
            # its owner, or the editor who attached them), else the caller's
            # tools plus defaults. Explicit rows first, so they claim names.
            run_tools = [
                tool for tool in self._run_tool_executor().get_tools().values()
                if isinstance(tool, dict) and not tool.get("client_side")
            ]
            tool_docs = sorted(run_tools, key=lambda tool: bool(tool.get("default")))
            if not tool_docs:
                return None

            tools_data = {}

            for tool_doc in tool_docs:
                tool_name = tool_doc.get("name")
                tool_id = str(tool_doc.get("_id") or tool_doc.get("id"))
                is_default = bool(tool_doc.get("default"))

                if filtering_enabled:
                    required_actions_by_name = required_tool_actions.get(
                        tool_name, set()
                    )
                    required_actions_by_id = required_tool_actions.get(tool_id, set())

                    required_actions = required_actions_by_name | required_actions_by_id

                    if not required_actions:
                        continue
                else:
                    # No template names a default tool, so running its
                    # actions blind would only inject noise.
                    if is_default:
                        continue
                    required_actions = None

                owner = tool_doc.get("user_id")
                if owner and (owner != user_id or outside_caller):
                    # Someone else's tool (a widget or API run carries the
                    # owner's id but isn't the owner): pre-fetch asks nobody,
                    # so only what the run would do without asking.
                    required_actions = self._unasked_actions(tool_doc, required_actions)
                    if not required_actions:
                        continue

                tool_data = self._fetch_tool_data(tool_doc, required_actions)
                if tool_data:
                    # Explicit rows claim the name key; a default tool takes
                    # it only when no explicit row of the same name exists
                    # (explicit rows are processed first).
                    if not is_default:
                        tools_data[tool_name] = tool_data
                    else:
                        tools_data.setdefault(tool_name, tool_data)
                    tools_data[tool_id] = tool_data

            return tools_data if tools_data else None
        except Exception as e:
            logger.warning(f"Failed to pre-fetch tools: {type(e).__name__}")
            return None

    @staticmethod
    def _unasked_actions(
        tool_doc: Dict[str, Any], required_actions: Optional[Set[Optional[str]]]
    ) -> Set[Optional[str]]:
        """The required actions of someone else's tool that run without asking.

        A tool on someone else's connected account runs on their account or
        needs the caller's own connection, a tool that decides approval per
        call (a remote device, the code executor) can't be judged from its
        stored flags, an approval-gated action waits for a person, and a
        write with the owner's credentials needs the owner's say-so;
        pre-fetch has none of these, so all are left out.

        Args:
            tool_doc: The tool row, owned by someone other than the caller.
            required_actions: Action names the template needs; None, or a set
                holding None, means all of them.

        Returns:
            The action names to run, empty when there are none.
        """
        from docsgpt.connectors.permissions import owner_credential_writes, tool_actions

        if tool_doc.get("connection_id") or tool_doc.get("name") in _LIVE_APPROVAL_TOOLS:
            return set()
        owner_writes = set(owner_credential_writes(tool_doc))
        unasked = {
            action.get("name") for action in tool_actions(tool_doc)
            if action.get("name") and action.get("active", True) and not action.get("require_approval")
            and action.get("name") not in owner_writes
        }
        if required_actions is None or None in required_actions:
            return unasked
        return {name for name in required_actions if name in unasked}

    def _run_tool_executor(self):
        """A ``ToolExecutor`` resolving the toolset this turn's agent run gets.

        Returns:
            ToolExecutor: Built with the run's key, user and agent.
        """
        from docsgpt.agents.tool_executor import ToolExecutor

        user = self.decoded_token.get("sub") if self.decoded_token else None
        return ToolExecutor(
            user_api_key=self.agent_config.get("user_api_key"),
            user=user,
            decoded_token=self.decoded_token,
            agent_id=self.agent_id,
        )

    def _enabled_tool_names(self) -> Optional[set]:
        """Resolve the tool names enabled for this turn, for ``tools.enabled`` gating.

        Mirrors the executor the agent will use (same user/agent context), so an
        agent yields its configured tools and an agentless chat yields user tools
        plus defaults. Returns None on failure so the prompt gate fails open
        (keeps the section) rather than hiding guidance when resolution breaks.
        """
        try:
            tool_executor = self._run_tool_executor()
            client_tools = self.data.get("client_tools")
            if client_tools:
                tool_executor.client_tools = client_tools
            return tool_executor.get_enabled_tool_names()
        except Exception:
            logger.warning("Failed to resolve enabled tool names for prompt gating")
            return None

    def _fetch_tool_data(
        self,
        tool_doc: Dict[str, Any],
        required_actions: Optional[Set[Optional[str]]],
    ) -> Optional[Dict[str, Any]]:
        """Fetch and execute tool actions with saved parameters"""
        try:
            from docsgpt.agents.tools.tool_manager import ToolManager

            tool_name = tool_doc.get("name")
            tool_config = tool_doc.get("config", {}).copy()
            tool_config["tool_id"] = str(tool_doc["_id"])

            tool_manager = ToolManager(config={tool_name: tool_config})
            user_id = self.initial_user_id or "local"
            tool = tool_manager.load_tool(tool_name, tool_config, user_id=user_id)

            if not tool:
                logger.debug(f"Tool '{tool_name}' failed to load")
                return None

            tool_actions = tool.get_actions_metadata()
            if not tool_actions:
                logger.debug(f"Tool '{tool_name}' has no actions")
                return None

            saved_actions = tool_doc.get("actions", [])

            include_all_actions = required_actions is None or (
                required_actions and None in required_actions
            )
            allowed_actions: Set[str] = (
                {action for action in required_actions if isinstance(action, str)}
                if required_actions
                else set()
            )

            action_results = {}
            for action_meta in tool_actions:
                action_name = action_meta.get("name")
                if action_name is None:
                    continue
                if (
                    not include_all_actions
                    and allowed_actions
                    and action_name not in allowed_actions
                ):
                    continue

                try:
                    saved_action = None
                    for sa in saved_actions:
                        if sa.get("name") == action_name:
                            saved_action = sa
                            break

                    action_params = action_meta.get("parameters", {})
                    properties = action_params.get("properties", {})

                    kwargs = {}
                    for param_name, param_spec in properties.items():
                        if saved_action:
                            saved_props = saved_action.get("parameters", {}).get(
                                "properties", {}
                            )
                            if param_name in saved_props:
                                param_value = saved_props[param_name].get("value")
                                if param_value is not None:
                                    kwargs[param_name] = param_value
                                    continue

                        if param_name in tool_config:
                            kwargs[param_name] = tool_config[param_name]
                        elif "default" in param_spec:
                            kwargs[param_name] = param_spec["default"]

                    result = tool.execute_action(action_name, **kwargs)
                    action_results[action_name] = result
                except Exception as e:
                    logger.debug(
                        f"Action '{action_name}' execution failed: {type(e).__name__}"
                    )
                    continue

            return action_results if action_results else None

        except Exception as e:
            logger.debug(f"Tool pre-fetch failed for '{tool_name}': {type(e).__name__}")
            return None

    def _get_prompt_content(self) -> Optional[str]:
        """Retrieve and cache the raw prompt content for the current agent configuration."""
        if self._prompt_content is not None:
            return self._prompt_content
        if not isinstance(self.agent_config, dict):
            return None
        # PG ``agents.prompt_id`` is NULL for agents that never chose a
        # prompt; ``agent_prompt_id`` reads that as the default preset, with
        # the agentic swap applied.
        prompt_id = agent_prompt_id(self.agent_config.get("prompt_id"), self.agent_config.get("agent_type"))
        try:
            content = get_prompt(prompt_id, self.prompts_collection)
            self._prompt_content, self._persona = resolve_prompt_skeleton(
                content, prompt_id, self.agent_config.get("agent_type")
            )
        except ValueError as e:
            logger.debug(f"Invalid prompt ID '{prompt_id}': {str(e)}")
            self._prompt_content = None
        except Exception as e:
            logger.debug(f"Failed to fetch prompt '{prompt_id}': {type(e).__name__}")
            self._prompt_content = None
        return self._prompt_content

    def _get_required_tool_actions(self) -> Optional[Dict[str, Set[Optional[str]]]]:
        """Determine which tool actions are referenced in the prompt template"""
        if self._required_tool_actions is not None:
            return self._required_tool_actions

        prompt_content = self._get_prompt_content()
        if prompt_content is None:
            return None

        if "{{" not in prompt_content or "}}" not in prompt_content:
            self._required_tool_actions = {}
            return self._required_tool_actions

        try:
            from docsgpt.templates.template_engine import TemplateEngine

            template_engine = TemplateEngine()
            usages = template_engine.extract_tool_usages(prompt_content)
            self._required_tool_actions = usages
            return self._required_tool_actions
        except Exception as e:
            logger.debug(f"Failed to extract tool usages: {type(e).__name__}")
            self._required_tool_actions = {}
            return self._required_tool_actions

    @_traced_setup
    def resume_from_tool_actions(
        self,
        tool_actions: list,
        conversation_id: str,
        claimed_state: Optional[Dict[str, Any]] = None,
    ):
        """Resume a paused agent from saved continuation state.

        Loads the pending state from MongoDB, recreates the agent with
        the saved configuration, and returns an agent ready to call
        ``gen_continuation()``.

        Args:
            tool_actions: Client-provided actions (approvals / results).
            conversation_id: The conversation being resumed.

        Returns:
            Tuple of (agent, messages, tools_dict, pending_tool_calls,
            tool_actions, reasoning_content). ``reasoning_content`` is
            the reasoning text emitted before the pause; round-tripping
            it back to the model is required by DeepSeek's thinking
            mode and ignored elsewhere.
        """
        from docsgpt.api.answer.services.continuation_service import (
            ContinuationService,
        )
        from docsgpt.agents.agent_creator import AgentCreator
        from docsgpt.agents.tool_executor import ToolExecutor
        from docsgpt.llm.handlers.handler_creator import LLMHandlerCreator
        from docsgpt.llm.llm_creator import LLMCreator

        # Who is resuming, classified from this request alone: the saved state
        # says who paused the turn, but anyone holding the agent's key (a
        # widget key is public) can send the tool actions that resume it.
        request_key = self.data.get("api_key")
        original_token = self.decoded_token
        key_agent = None
        if request_key:
            with db_readonly() as conn:
                key_agent = AgentsRepository(conn).find_by_key(request_key)
        key_owner = (
            (key_agent.get("user_id") or key_agent.get("user")) if key_agent else None
        )
        request_external = bool(getattr(self, "external_caller", False)) or (
            bool(request_key) and is_external_api_caller(self.data, original_token, key_owner)
        )
        request_public_link = False
        named_agent = self.data.get("agent_id")
        if named_agent and not request_key:
            try:
                self._get_agent_key(str(named_agent), self.initial_user_id)
            except Exception as exc:
                raise ValueError("This conversation can't be resumed with that agent") from exc
            request_public_link = bool(getattr(self, "public_link_usage", False))

        # api_key-in-body auth carries no JWT, so initial_user_id is None — but
        # the state was saved under the agent owner. Resolve the owner so the
        # lookup / mark_resuming / delete_state key on the same id. (No-op for
        # v1, which already passes an owner-scoped decoded_token.)
        if self.initial_user_id is None and key_owner:
            self.initial_user_id = key_owner
            self.decoded_token = {"sub": key_owner}

        cont_service = ContinuationService()
        state = claimed_state or cont_service.claim_state(
            conversation_id, self.initial_user_id
        )
        if not state:
            raise ValueError("No pending tool state found for this conversation")

        # A request that names an agent (by key or id) resumes only that
        # agent's turn; the claim goes back so its rightful caller can resume.
        saved_agent = str((state.get("agent_config") or {}).get("agent_id") or "").lower()
        targets = []
        if request_key:
            targets.append(str((key_agent or {}).get("id") or (key_agent or {}).get("_id") or ""))
        if named_agent:
            targets.append(str(named_agent))
        if any(target.lower() != saved_agent or not target for target in targets):
            try:
                cont_service.release_claim(conversation_id, self.initial_user_id)
            except Exception:
                logger.warning("Failed to release a refused resume claim", exc_info=True)
            raise ValueError("This conversation belongs to a different agent")

        messages = state["messages"]
        pending_tool_calls = state["pending_tool_calls"]
        tools_dict = state["tools_dict"]
        tool_schemas = state.get("tool_schemas", [])
        agent_config = state["agent_config"]

        model_id = agent_config.get("model_id")
        # BYOM scope captured at initial dispatch. None for built-ins or
        # caller-owned BYOM where decoded_token['sub'] is already the
        # right scope; non-None for shared-agent owner BYOM where the
        # caller's identity differs from the model owner's.
        model_user_id = agent_config.get("model_user_id")
        llm_name = agent_config.get("llm_name", settings.LLM_PROVIDER)
        api_key = agent_config.get("api_key")
        user_api_key = agent_config.get("user_api_key")
        agent_id = agent_config.get("agent_id")
        prompt = agent_config.get("prompt", "")
        json_schema = agent_config.get("json_schema")
        retriever_config = agent_config.get("retriever_config")

        # Recreate dependencies
        system_api_key = api_key or get_api_key_for_provider(llm_name)
        llm = LLMCreator.create_llm(
            llm_name,
            api_key=system_api_key,
            user_api_key=user_api_key,
            decoded_token=self.decoded_token,
            model_id=model_id,
            agent_id=agent_id,
            model_user_id=model_user_id,
        )
        importer = getattr(llm, "import_responses_state", None)
        if callable(importer):
            importer(agent_config.get("responses_state"))
        llm_handler = LLMHandlerCreator.create_handler(llm_name or "default")
        # Outside if either who paused the turn or who resumes it is.
        resume_external = bool(agent_config.get("external_api_caller")) or request_external
        resume_public_link = bool(agent_config.get("public_link_caller")) or request_public_link
        apply_resume_caller_rules(
            tools_dict, outside_caller=resume_external, public_link_caller=resume_public_link,
        )
        tool_executor = ToolExecutor(
            user_api_key=user_api_key,
            user=self.initial_user_id,
            decoded_token=self.decoded_token,
            agent_id=agent_id,
            external_caller=resume_external,
            public_link_caller=resume_public_link,
            api_write_allowlist=agent_config.get("api_write_allowlist"),
        )
        tool_executor.conversation_id = conversation_id
        # Restore client tools so they stay available for subsequent LLM calls
        saved_client_tools = state.get("client_tools")
        if saved_client_tools:
            tool_executor.client_tools = saved_client_tools
            # Re-merge into tools_dict (they may have been stripped during serialization)
            tool_executor.merge_client_tools(tools_dict, saved_client_tools)

        agent_type = agent_config.get("agent_type", "ClassicAgent")
        # Map class names back to agent creator keys
        type_map = {
            "ClassicAgent": "classic",
            "AgenticAgent": "agentic",
            "ResearchAgent": "research",
            "WorkflowAgent": "workflow",
        }
        agent_key = type_map.get(agent_type, "classic")

        agent_kwargs = {
            "endpoint": "stream",
            "llm_name": llm_name,
            "model_id": model_id,
            "model_user_id": model_user_id,
            "api_key": system_api_key,
            "agent_id": agent_id,
            "user_api_key": user_api_key,
            "prompt": prompt,
            "chat_history": [],
            "decoded_token": self.decoded_token,
            "json_schema": json_schema,
            "llm": llm,
            "llm_handler": llm_handler,
            "tool_executor": tool_executor,
            "is_v1": getattr(self, "trace_source", None) == "v1",
        }

        # Restore the search-tool config on resume. Classic agents carry one
        # only when they had ``agentic_tool`` sources; a default classic agent
        # serializes an empty config (falsy), so its behavior is unchanged.
        if retriever_config and agent_key in ("classic", "agentic", "research"):
            agent_kwargs["retriever_config"] = retriever_config

        # A resumed turn is still the same turn: rebuild it with the guardrails
        # config captured at pause, floor already applied.
        saved_guardrails = agent_config.get("guardrails")
        if saved_guardrails:
            agent_kwargs["agent_config"] = {"guardrails": saved_guardrails}
        agent_kwargs["request_id"] = agent_config.get("request_id")

        # Images an attachments read queued in the paused round: shown after
        # the tool results once the turn resumes.
        saved_reads = agent_config.get("native_reads")
        if saved_reads:
            from docsgpt.agents.tools.attachments import restore_native_reads

            tool_executor.pending_native_parts = restore_native_reads(saved_reads)

        agent = AgentCreator.create_agent(agent_key, **agent_kwargs)
        agent.conversation_id = conversation_id
        agent.initial_user_id = self.initial_user_id
        agent.tools = tool_schemas

        # Store config for the route layer
        self.model_id = model_id
        # Mirror ``model_user_id`` back onto the processor so the route
        # layer (StreamResource) reads the owner scope captured at
        # initial dispatch. Without this, ``processor.model_user_id``
        # stays at the __init__ default (None) and complete_stream
        # falls back to the caller's sub: the post-resume title-LLM
        # save misses the owner's BYOM layer, and any second tool
        # pause persists ``model_user_id=None`` — losing owner scope
        # for every subsequent resume of this conversation.
        self.model_user_id = model_user_id
        self.agent_id = agent_id
        self.agent_config["user_api_key"] = user_api_key
        self.conversation_id = conversation_id
        # Reused on resume so the same WAL row gets finalised and
        # request_id stays consistent across token_usage rows.
        self.reserved_message_id = agent_config.get("reserved_message_id")
        self.request_id = agent_config.get("request_id")

        reasoning_content = agent_config.get("reasoning_content", "")
        return (
            agent,
            messages,
            tools_dict,
            pending_tool_calls,
            tool_actions,
            reasoning_content,
        )

    def create_agent(
        self,
        docs_together: Optional[str] = None,
        docs: Optional[list] = None,
        tools_data: Optional[Dict[str, Any]] = None,
        agentic_sources: Optional[list] = None,
    ):
        """Create and return the configured agent with rendered prompt.

        ``agentic_sources`` (D11) scopes the agentic search tool to the
        ``agentic_tool`` source subset; when None the tool exposes all of the
        agent's sources (today's behavior).
        """
        agent_type = self.agent_config["agent_type"]

        # _get_prompt_content handles the agentic preset swap and caching;
        # it returns None only when the prompt couldn't be fetched (unknown
        # or broken custom ids) — re-fetch strictly so the underlying error
        # surfaces to the caller.
        raw_prompt = self._get_prompt_content()
        if raw_prompt is None:
            raw_prompt = get_prompt(
                self.agent_config.get("prompt_id", "default"),
                self.prompts_collection,
            )
            self._prompt_content = raw_prompt

        # Allow API callers to override the system prompt when the agent
        # has opted in via allow_system_prompt_override.
        # An override replaces the rendered prompt wholesale, so it cannot have
        # interpolated documents no matter what the agent's own prompt says.
        override_used = bool(
            self.agent_config.get("allow_system_prompt_override", False)
            and self.data.get("system_prompt_override")
        )
        if override_used:
            rendered_prompt = self.data["system_prompt_override"]
        else:
            rendered_prompt = self.prompt_renderer.render_prompt(
                prompt_content=raw_prompt,
                user_id=self.initial_user_id,
                request_id=self.data.get("request_id"),
                passthrough_data=self.data.get("passthrough"),
                docs=docs,
                docs_together=docs_together,
                tools_data=tools_data,
                attachments=self.attachments,
                enabled_tools=self._enabled_tool_names(),
                persona=self._persona,
                artifact_parent={"conversation_id": self.conversation_id},
            )

        # Use the user_id that resolved the model so owner-scoped BYOM
        # records dispatch correctly on shared-agent requests.
        model_user_id = getattr(self, "model_user_id", self.initial_user_id)
        provider = (
            get_provider_from_model_id(self.model_id, user_id=model_user_id)
            if self.model_id
            else settings.LLM_PROVIDER
        )
        system_api_key = get_api_key_for_provider(provider or settings.LLM_PROVIDER)

        # Create LLM and handler (dependency injection)
        from docsgpt.llm.llm_creator import LLMCreator
        from docsgpt.llm.handlers.handler_creator import LLMHandlerCreator
        from docsgpt.agents.tool_executor import ToolExecutor

        # Compute backup models: agent's configured models minus the active one.
        # PG agents may carry an explicit ``models: NULL`` (not absent), so
        # ``.get("models", [])`` isn't enough — coerce None → [].
        agent_models = self.agent_config.get("models") or []
        backup_models = [m for m in agent_models if m != self.model_id]

        llm = LLMCreator.create_llm(
            provider or settings.LLM_PROVIDER,
            api_key=system_api_key,
            user_api_key=self.agent_config["user_api_key"],
            decoded_token=self.decoded_token,
            model_id=self.model_id,
            agent_id=self.agent_id,
            backup_models=backup_models,
            # Owner-scope on shared-agent BYOM dispatch.
            model_user_id=model_user_id,
        )
        llm_handler = LLMHandlerCreator.create_handler(
            provider if provider else "default"
        )

        user = self.decoded_token.get("sub") if self.decoded_token else None
        tool_executor = ToolExecutor(
            user_api_key=self.agent_config["user_api_key"],
            user=user,
            decoded_token=self.decoded_token,
            agent_id=self.agent_id,
            external_caller=bool(self.agent_config.get("external_api_caller")),
            public_link_caller=bool(self.agent_config.get("public_link_caller")),
            api_write_allowlist=self.agent_config.get("api_write_allowlist"),
        )
        tool_executor.conversation_id = self.conversation_id
        # Pass client-side tools so they get merged in get_tools()
        client_tools = self.data.get("client_tools")
        if client_tools:
            tool_executor.client_tools = client_tools

        # OpenAI-style image_url content parts are only understood by the
        # OpenAI-family providers; drop multimodal content for others (Google,
        # Anthropic, ...) so a multimodal request degrades to text rather than
        # erroring upstream.
        from docsgpt.llm.openai import OpenAILLM

        request_multimodal = (
            self.data.get("multimodal_content")
            if isinstance(llm, OpenAILLM)
            else None
        )

        agent_kwargs = {
            "endpoint": "stream",
            "llm_name": provider or settings.LLM_PROVIDER,
            "model_id": self.model_id,
            "model_user_id": self.model_user_id,
            "api_key": system_api_key,
            "agent_id": self.agent_id,
            "user_api_key": self.agent_config["user_api_key"],
            "prompt": rendered_prompt,
            "chat_history": self.history,
            "retrieved_docs": self.retrieved_docs,
            "prompt_embeds_documents": (
                False if override_used else prompt_embeds_documents(raw_prompt)
            ),
            "sources_were_searched": self._has_active_docs(),
            "decoded_token": self.decoded_token,
            "attachments": self.attachments,
            "json_schema": self.agent_config.get("json_schema"),
            "json_schema_strict": self.agent_config.get("json_schema_strict", True),
            "json_object": self.agent_config.get("json_object", False),
            "llm_params": self.data.get("llm_params") or {},
            "multimodal_content": request_multimodal,
            "compressed_summary": self.compressed_summary,
            "last_compression_at": self.last_compression_at,
            "llm": llm,
            "llm_handler": llm_handler,
            "tool_executor": tool_executor,
            "agent_config": self.agent_config.get("config") or {},
            "request_id": self.request_id or self.data.get("request_id"),
            "is_v1": getattr(self, "trace_source", None) == "v1",
            # Chat turns budget their files against the window; earlier
            # turns' files are listed, never inlined again.
            "attachment_planning": True,
            "earlier_attachments": self.earlier_attachments,
            "skipped_attachments": self._request_skipped_files(),
        }

        # Wiki tool injection + authz: only for agent types that build a
        # tools_dict (classic/agentic/research), and only when a writable wiki
        # source is present for the principal (viewers get nothing).
        if agent_type in WIKI_AGENT_TYPES:
            wiki_config = self._build_wiki_config()
            if wiki_config:
                agent_kwargs["wiki_config"] = wiki_config

        # Type-specific kwargs
        # D11: agentic/research always carry a retriever_config; classic carries
        # one only when an ``agentic_tool`` subset is supplied, so a default
        # classic agent adds no internal_search tool.
        retriever_config = internal_search_config(
            agent_type,
            agentic_sources,
            self.all_sources,
            self.source,
            retriever_name=self.retriever_config.get("retriever_name", "classic"),
            chunks=self.retriever_config.get("chunks", 6),
            doc_token_limit=self.retriever_config.get("doc_token_limit", 50000),
            model_id=self.model_id,
            model_user_id=self.model_user_id,
            # Agent owner — internal_search resolves the agent's sources as
            # their owner so a team member running a shared agent can read
            # nested-source structure (the sources aren't theirs).
            source_owner_id=self.agent_config.get("user_id"),
            user_api_key=self.agent_config["user_api_key"],
            agent_id=self.agent_id,
            llm_name=provider or settings.LLM_PROVIDER,
            api_key=system_api_key,
            decoded_token=self.decoded_token,
            request_id=self.request_id or self.data.get("request_id"),
        )
        if retriever_config is not None:
            agent_kwargs["retriever_config"] = retriever_config

        elif agent_type == "workflow":
            workflow_config = self.agent_config.get("workflow")
            if isinstance(workflow_config, str):
                agent_kwargs["workflow_id"] = workflow_config
            elif isinstance(workflow_config, dict):
                agent_kwargs["workflow"] = workflow_config
                # Embedded-graph Preview run that names a saved workflow: run the
                # canvas graph but persist the run under the saved id so artifacts
                # parent to a real, ownership-checked ``workflow_runs`` row.
                saved_workflow_id = self.agent_config.get("workflow_id")
                if saved_workflow_id:
                    agent_kwargs["workflow_id"] = saved_workflow_id
            workflow_owner = self.agent_config.get("workflow_owner")
            if workflow_owner:
                agent_kwargs["workflow_owner"] = workflow_owner

        agent = AgentCreator.create_agent(agent_type, **agent_kwargs)

        agent.conversation_id = self.conversation_id
        agent.initial_user_id = self.initial_user_id

        return agent
