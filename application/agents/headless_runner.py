"""Shared headless agent runner used by webhooks and scheduled runs."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from application.agents.agent_creator import AgentCreator
from application.agents.tool_executor import ToolExecutor
from application.api.answer.services.prompt_renderer import (
    PromptRenderer,
    format_docs_for_prompt,
    prompt_embeds_documents,
    resolve_prompt_skeleton,
)
from application.api.answer.services.stream_processor import get_prompt
from application.core.settings import settings
from application.retriever.retriever_creator import RetrieverCreator
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.session import db_readonly

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


def run_agent_headless(
    agent_config: Dict[str, Any],
    query: str,
    *,
    tool_allowlist: Optional[Iterable[str]] = None,
    model_id_override: Optional[str] = None,
    endpoint: str = "headless",
    chat_history: Optional[List[Dict[str, Any]]] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run an agent with no live client; returns a structured outcome dict."""
    from application.core.model_utils import (
        get_api_key_for_provider,
        get_default_model_id,
        get_provider_from_model_id,
        validate_model_id,
    )
    from application.utils import calculate_doc_token_budget

    owner = _resolve_owner(agent_config)
    if not owner:
        raise ValueError("Agent config is missing user_id; cannot run headless.")
    decoded_token = {"sub": owner}

    retriever_kind = agent_config.get("retriever", "classic")
    source_id = agent_config.get("source_id") or agent_config.get("source")
    source_active: Any = {}
    if source_id:
        with db_readonly() as conn:
            src_row = SourcesRepository(conn).get(str(source_id), owner)
        if src_row:
            source_active = str(src_row["id"])
            retriever_kind = src_row.get("retriever", retriever_kind)
    source = {"active_docs": source_active}
    chunks = int(agent_config.get("chunks", 2) or 2)
    prompt_id = agent_config.get("prompt_id", "default")
    user_api_key = agent_config.get("key")
    agent_id = _resolve_agent_id(agent_config)
    agent_type = agent_config.get("agent_type", "classic")
    json_schema = agent_config.get("json_schema")
    raw_prompt, persona = resolve_prompt_skeleton(
        get_prompt(prompt_id), prompt_id, agent_type
    )
    prompt = raw_prompt

    candidate_model = model_id_override or agent_config.get("default_model_id") or ""
    if candidate_model and validate_model_id(candidate_model, user_id=owner):
        model_id = candidate_model
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

    retriever = RetrieverCreator.create_retriever(
        retriever_kind,
        source=source,
        chat_history=chat_history or [],
        prompt=prompt,
        chunks=chunks,
        doc_token_limit=doc_token_limit,
        model_id=model_id,
        user_api_key=user_api_key,
        agent_id=agent_id,
        decoded_token=decoded_token,
    )
    retrieved_docs: List[Dict[str, Any]] = []
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
    )
    if conversation_id:
        tool_executor.conversation_id = str(conversation_id)

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
    if agent_type == "workflow":
        agent_kwargs.update(_workflow_kwargs(agent_config, owner))
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
        # ``application/logging.py`` so an error carrying no message is still
        # truthy instead of reading as "ok".
        if event.get("type") == "error":
            stream_error = str(event.get("error") or "")[:500] or "unspecified"
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
