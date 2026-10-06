"""Shared headless agent runner used by webhooks and scheduled runs."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from docsgpt import tracing
from docsgpt.agents.agent_creator import AgentCreator
from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.api.answer.services.prompt_renderer import (
    PromptRenderer,
    format_docs_for_prompt,
    prompt_embeds_documents,
    prompt_requests_citations,
    resolve_prompt_skeleton,
)
from docsgpt.api.answer.services.stream_processor import (
    WIKI_AGENT_TYPES,
    agent_prompt_id,
    authorized_agent_sources,
    authorized_prompt_id,
    get_prompt,
    internal_search_config,
    per_source_list,
    plan_source_use,
    source_for_docs,
    wiki_tool_config,
)
from docsgpt.core.settings import settings
from docsgpt.guardrails.config import AgentConfig
from docsgpt.quotas.service import QuotaExceededError, QuotaService
from docsgpt.retriever.dispatcher import build_dispatcher
from docsgpt.retriever.retriever_creator import RetrieverCreator
from docsgpt.storage.db.session import db_readonly
from docsgpt.storage.db.source_config import SourceConfig

logger = logging.getLogger(__name__)


def _resolve_owner(agent_config: Dict[str, Any]) -> Optional[str]:
    return agent_config.get("user_id") or agent_config.get("user")


def _resolve_agent_id(agent_config: Dict[str, Any]) -> Optional[str]:
    raw = agent_config.get("id") or agent_config.get("_id")
    return str(raw) if raw else None


def _workflow_kwargs(agent_config: Dict[str, Any], owner: str) -> Dict[str, Any]:
    """Bind a workflow agent to its graph, mirroring ``StreamProcessor``.

    A ``WorkflowAgent`` built without one of these loads no graph and its
    entire run is a single "Failed to load workflow configuration." error, so
    a scheduled or webhook-fired workflow agent never does anything. The PG
    ``agents`` row stores a UUID under ``workflow_id``; the legacy Mongo shape
    used ``workflow``, which also carried an embedded graph.
    """
    kwargs: Dict[str, Any] = {"workflow_owner": owner}
    embedded = agent_config.get("workflow")
    if isinstance(embedded, dict):
        kwargs["workflow"] = embedded
        saved_id = agent_config.get("workflow_id")
        if saved_id:
            kwargs["workflow_id"] = str(saved_id)
        return kwargs
    wf_ref = agent_config.get("workflow_id") or embedded
    if wf_ref:
        kwargs["workflow_id"] = str(wf_ref)
    else:
        logger.warning(
            "Workflow agent %s has no workflow reference; the run will load no graph.",
            _resolve_agent_id(agent_config),
        )
    return kwargs


def _wiki_config(
    conn: Any,
    source_docs: List[Dict[str, Any]],
    decoded_token: Dict[str, Any],
    *,
    outside_caller: bool,
) -> Optional[Dict[str, Any]]:
    """The run's WikiTool config, resolved as for a chat run by the owner.

    A webhook's input comes from whoever holds its URL, and a schedule set
    through the API or from a public link is that caller's, so those runs are
    ``outside_caller``: they edit only when the wiki's owner allows outside
    edits. Nobody can approve a headless write, so no action waits for one.
    """
    try:
        return wiki_tool_config(
            conn, [doc["id"] for doc in source_docs], decoded_token, outside_caller=outside_caller
        )
    except Exception:
        logger.exception("Failed to resolve wiki tool config for a headless run")
        return None


def run_agent_headless(
    agent_config: Dict[str, Any],
    query: str,
    *,
    tool_allowlist: Optional[Iterable[str]] = None,
    model_id_override: Optional[str] = None,
    endpoint: str = "headless",
    chat_history: Optional[List[Dict[str, Any]]] = None,
    conversation_id: Optional[str] = None,
    external_caller: bool = False,
    public_link_caller: bool = False,
    request_id: Optional[str] = None,
    trace_user_id: Optional[str] = None,
    message_id: Optional[str] = None,
    background: Any = None,
) -> Dict[str, Any]:
    """Run an agent with no live client; returns a structured outcome dict.

    The run is recorded as one execution trace under ``endpoint`` as its
    source. ``request_id`` links that trace to the caller's own record (the
    scheduler passes its run id, the webhook worker its task id); it is kept
    off the LLM's token-usage rows, whose request ids drive request counts.
    ``trace_user_id`` owns the trace when the run belongs to someone other
    than the agent's owner (a schedule a user set on a shared agent), so the
    trace is visible wherever that user sees the run; it defaults to the owner.
    ``external_caller`` (a schedule set through the API) and
    ``public_link_caller`` (a schedule a public-link user set) mark a run for
    someone who can't approve for the owner: writes on the owner's accounts
    and credentials then run only when the agent's API write allowlist has
    them, and wiki edits only when the wiki's owner allows outside edits (as
    for a webhook run).

    A continuation turn passes ``message_id``, the id its message will be
    stored with (tool calls are journaled and files attached under it), and
    ``background``, its :class:`~docsgpt.background.context.BackgroundContext`:
    a slow call then becomes a background job and ``check_job`` is offered,
    as in a chat turn. Approval-gated tools stay denied either way.

    Raises:
        QuotaExceededError: If the agent owner's usage quota is exhausted.
    """
    trace = tracing.start_trace(
        source=endpoint,
        request_id=request_id,
        user_id=trace_user_id or _resolve_owner(agent_config),
        agent_id=_resolve_agent_id(agent_config),
        conversation_id=conversation_id,
    )
    status = None
    with tracing.activate(trace):
        try:
            outcome = _run_agent_headless(
                agent_config,
                query,
                tool_allowlist=tool_allowlist,
                model_id_override=model_id_override,
                endpoint=endpoint,
                chat_history=chat_history,
                conversation_id=conversation_id,
                external_caller=external_caller,
                public_link_caller=public_link_caller,
                message_id=message_id,
                background=background,
            )
            if outcome.get("error"):
                status = tracing.STATUS_ERROR
            return outcome
        except BaseException:
            status = tracing.STATUS_ERROR
            raise
        finally:
            tracing.flush(trace, status)


def _run_agent_headless(
    agent_config: Dict[str, Any],
    query: str,
    *,
    tool_allowlist: Optional[Iterable[str]] = None,
    model_id_override: Optional[str] = None,
    endpoint: str = "headless",
    chat_history: Optional[List[Dict[str, Any]]] = None,
    conversation_id: Optional[str] = None,
    external_caller: bool = False,
    public_link_caller: bool = False,
    message_id: Optional[str] = None,
    background: Any = None,
) -> Dict[str, Any]:
    from docsgpt.core.model_utils import (
        get_api_key_for_provider,
        get_default_model_id,
        get_provider_from_model_id,
        validate_model_id,
    )
    from docsgpt.utils import calculate_doc_token_budget

    owner = _resolve_owner(agent_config)
    if not owner:
        raise ValueError("Agent config is missing user_id; cannot run headless.")
    decoded_token = {"sub": owner}
    # An agent run is agent traffic whether or not the agent has a key yet.
    is_agent_run = bool(agent_config.get("key") or _resolve_agent_id(agent_config))
    exceeded = QuotaService.check(owner, "agent" if is_agent_run else "direct")
    if exceeded is not None:
        raise QuotaExceededError(exceeded)

    retriever_kind = agent_config.get("retriever", "classic")
    agent_type = agent_config.get("agent_type", "classic")
    # Every source a chat with this agent searches: the primary and the
    # extras, each owned or team-shared to the owner, else attached by an
    # editor who still qualifies.
    sources_row = dict(agent_config)
    sources_row["source_id"] = agent_config.get("source_id") or agent_config.get("source")
    primary, source_docs = None, []
    wiki_config: Optional[Dict[str, Any]] = None
    if sources_row["source_id"] or sources_row.get("extra_source_ids"):
        with db_readonly() as conn:
            primary, source_docs = authorized_agent_sources(conn, sources_row)
            if agent_type in WIKI_AGENT_TYPES and source_docs:
                wiki_config = _wiki_config(
                    conn,
                    source_docs,
                    decoded_token,
                    outside_caller=external_caller or public_link_caller or endpoint == "webhook",
                )
    if primary:
        retriever_kind = primary.get("retriever") or retriever_kind
    per_source = [
        {"id": str(doc["id"]), "retrieval": SourceConfig.parse(doc.get("config")).retrieval}
        for doc in source_docs
    ]
    source_active: Any = [entry["id"] for entry in per_source] or {}
    source = {"active_docs": source_active}
    # ``chunks=0`` switches retrieval off; only a missing value takes the default.
    raw_chunks = agent_config.get("chunks")
    chunks = 6 if raw_chunks in (None, "") else int(raw_chunks)
    # Runs as the owner: a prompt they can no longer use (revoked grant,
    # deleted) falls back to the default instead of rendering anyway.
    prompt_id = authorized_prompt_id(agent_config.get("prompt_id", "default"), owner, agent_config)
    user_api_key = agent_config.get("key")
    agent_id = _resolve_agent_id(agent_config)
    json_schema = agent_config.get("json_schema")
    # Agentic and research agents render the agentic preset, as in a chat.
    prompt_id = agent_prompt_id(prompt_id, agent_type)
    raw_prompt, persona = resolve_prompt_skeleton(
        get_prompt(prompt_id), prompt_id, agent_type
    )
    prompt = raw_prompt

    candidate_model = model_id_override or agent_config.get("default_model_id") or ""
    model_user_id: Optional[str] = None
    if candidate_model and validate_model_id(candidate_model, user_id=owner):
        model_id = candidate_model
        model_user_id = owner
    else:
        model_id = get_default_model_id()
        if candidate_model:
            logger.warning(
                "Agent %s references unknown model_id %r; falling back to %r",
                agent_id, candidate_model, model_id,
            )
    provider = (
        get_provider_from_model_id(model_id, user_id=owner)
        if model_id
        else settings.LLM_PROVIDER
    )
    system_api_key = get_api_key_for_provider(provider or settings.LLM_PROVIDER)
    doc_token_limit = calculate_doc_token_budget(model_id=model_id, user_id=owner)

    # Sources are used as in a chat turn of this agent type: agentic and
    # research agents search on demand through internal_search, classic
    # agents pre-fetch, and ``agentic_tool`` sources are searched either way.
    use = plan_source_use(agent_type, per_source_list(per_source, "agentic_tool"))
    retrieved_docs: List[Dict[str, Any]] = []
    prefetch_sources = per_source_list(per_source, use.exposure)
    # A pre-fetch scoped to an exposure with no source in it searches nothing.
    if use.prefetch and (use.exposure is None or prefetch_sources):
        retriever_kwargs: Dict[str, Any] = dict(
            source=source if use.exposure is None else source_for_docs([e["id"] for e in prefetch_sources]),
            chat_history=chat_history or [],
            prompt=prompt,
            chunks=chunks,
            doc_token_limit=doc_token_limit,
            model_id=model_id,
            user_api_key=user_api_key,
            agent_id=agent_id,
            decoded_token=decoded_token,
        )
        # Routed per source like a chat's pre-fetch, so each source keeps its
        # own retriever and retrieval settings.
        retriever = build_dispatcher(
            lambda: RetrieverCreator.create_retriever(retriever_kind, **retriever_kwargs),
            sources=prefetch_sources,
            **retriever_kwargs,
        )
        try:
            docs = retriever.search(query)
            if docs:
                retrieved_docs = docs
        except Exception as exc:
            logger.warning("Headless retrieve failed: %s", exc)

    tool_executor = ToolExecutor(
        user_api_key=user_api_key,
        user=owner,
        decoded_token=decoded_token,
        agent_id=agent_id,
        headless=True,
        tool_allowlist=list(tool_allowlist or []),
        external_caller=external_caller,
        public_link_caller=public_link_caller,
        api_write_allowlist=AgentConfig.parse(agent_config.get("config")).api_write_allowlist,
    )
    if conversation_id:
        tool_executor.conversation_id = str(conversation_id)
    if message_id:
        tool_executor.message_id = str(message_id)
    if background is not None:
        tool_executor.background = background

    # Render the prompt (Jinja namespaces / legacy {summaries}) so retrieved
    # docs actually reach the model — mirroring StreamProcessor.create_agent.
    # ``enabled_tools`` gates the tool-specific sections; without it they fail
    # open and a scheduled run is told about tools it does not have.
    try:
        prompt = PromptRenderer().render_prompt(
            prompt_content=raw_prompt,
            user_id=owner,
            docs=retrieved_docs or None,
            docs_together=format_docs_for_prompt(retrieved_docs),
            artifact_parent={"conversation_id": conversation_id},
            enabled_tools=tool_executor.get_enabled_tool_names(),
            persona=persona,
            sources_attached=bool(source_active),
        )
    except Exception as exc:
        logger.warning("Headless prompt rendering failed; using raw prompt: %s", exc)

    agent_kwargs: Dict[str, Any] = {
        "endpoint": endpoint,
        "llm_name": provider or settings.LLM_PROVIDER,
        "model_id": model_id,
        "api_key": system_api_key,
        "agent_id": agent_id,
        "user_api_key": user_api_key,
        "prompt": prompt,
        "chat_history": chat_history or [],
        "retrieved_docs": retrieved_docs,
        "prompt_embeds_documents": prompt_embeds_documents(raw_prompt),
        "prompt_cites_sources": prompt_requests_citations(raw_prompt),
        "sources_were_searched": bool(source_active),
        "decoded_token": decoded_token,
        "attachments": [],
        "json_schema": json_schema,
        "tool_executor": tool_executor,
        # ``agent_config`` here is the agent row; ``config`` is its per-agent
        # behavior contract. A scheduled or webhook run is still a run of this
        # agent, so it carries the same guardrails an interactive turn would.
        "agent_config": agent_config.get("config") or {},
    }
    if wiki_config:
        agent_kwargs["wiki_config"] = wiki_config
    if agent_type == "workflow":
        agent_kwargs.update(_workflow_kwargs(agent_config, owner))
    else:
        retriever_config = internal_search_config(
            agent_type,
            use.agentic_sources,
            per_source,
            source,
            retriever_name=retriever_kind,
            chunks=chunks,
            doc_token_limit=doc_token_limit,
            model_id=model_id,
            model_user_id=model_user_id,
            source_owner_id=owner,
            user_api_key=user_api_key,
            agent_id=agent_id,
            llm_name=provider or settings.LLM_PROVIDER,
            api_key=system_api_key,
            decoded_token=decoded_token,
        )
        if retriever_config is not None:
            agent_kwargs["retriever_config"] = retriever_config
    agent = AgentCreator.create_agent(agent_type, **agent_kwargs)
    if conversation_id:
        agent.conversation_id = str(conversation_id)

    answer_full = ""
    thought = ""
    sources_log: List[Dict[str, Any]] = []
    tool_calls: List[Dict[str, Any]] = []
    stream_error: Optional[str] = None
    steps_completed = 0
    for event in agent.gen(query=query):
        if not isinstance(event, dict):
            continue
        # ``Agent.gen`` reports a failed stream with an error event rather than
        # by raising. Dropping it here (as this loop used to) makes a broken run
        # indistinguishable from one that simply had nothing to say, and the
        # caller records it as a success. Mirrors the sentinel in
        # ``docsgpt/logging.py`` so an error carrying no message is still
        # truthy instead of reading as "ok".
        if event.get("type") == "error":
            stream_error = str(event.get("error") or "")[:500] or "unspecified"
            if event.get("guardrail"):
                # Same rule as the streaming route: a blocked turn must not
                # record what was blocked. A scheduled run has no client to
                # retract from, so the stored result is all there is.
                answer_full = ""
                thought = ""
            continue
        # A workflow's work is its nodes: its tool calls stay in the engine's
        # execution log and its node agents own their LLMs, so neither
        # ``tool_calls`` nor the token tally below sees them. Counting
        # completed steps is the only evidence a quiet workflow ran at all.
        if event.get("type") == "workflow_step":
            if event.get("status") == "completed":
                steps_completed += 1
            continue
        if "answer" in event:
            answer_full += str(event["answer"])
        elif "sources" in event:
            sources_log.extend(event["sources"])
        elif "tool_calls" in event:
            tool_calls.extend(event["tool_calls"])
        elif "thought" in event:
            thought += str(event["thought"])

    denied = list(getattr(tool_executor, "headless_denials", []))
    error: Optional[str] = None
    if denied and not answer_full.strip():
        error_type = "tool_not_allowed"
        blocked = ", ".join(
            str(d.get("tool_name") or d.get("action_name") or "?") for d in denied
        )
        error = f"headless allowlist blocked required tool: {blocked}"[:500]
    elif stream_error:
        error_type = "stream_error"
        error = stream_error
    else:
        error_type = None
    if stream_error:
        logger.warning(
            "Headless run for agent %s failed mid-stream: %s", agent_id, stream_error
        )

    # A guardrail that fired on an unattended run is exactly the event an
    # operator needs to find later, so the journal is written here too.
    try:
        agent.flush_guardrail_audit()
    except Exception:
        logger.exception("Guardrail audit flush failed for headless agent %s", agent_id)

    # Use the LLM accumulator (gen_token_usage / stream_token_usage decorators);
    # current_token_count is a context-size sentinel, not a usage tally.
    llm_usage = getattr(getattr(agent, "llm", None), "token_usage", None) or {}
    prompt_tokens = int(llm_usage.get("prompt_tokens", 0) or 0)
    generated_tokens = int(llm_usage.get("generated_tokens", 0) or 0)

    return {
        "answer": answer_full,
        "thought": thought,
        "sources": sources_log,
        "tool_calls": tool_calls,
        "prompt_tokens": prompt_tokens,
        "generated_tokens": generated_tokens,
        "denied": denied,
        "error_type": error_type,
        "error": error,
        "steps_completed": steps_completed,
        "model_id": model_id,
    }
