"""Shared headless agent runner used by webhooks and scheduled runs."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from application.agents.agent_creator import AgentCreator
from application.agents.tool_executor import ToolExecutor
from application.api.answer.services.prompt_renderer import (
    PromptRenderer,
    format_docs_for_prompt,
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
    prompt = get_prompt(prompt_id)

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

    # Render the prompt (Jinja namespaces / legacy {summaries}) so retrieved
    # docs actually reach the model — mirroring StreamProcessor.create_agent.
    try:
        prompt = PromptRenderer().render_prompt(
            prompt_content=prompt,
            user_id=owner,
            docs=retrieved_docs or None,
            docs_together=format_docs_for_prompt(retrieved_docs),
        )
    except Exception as exc:
        logger.warning("Headless prompt rendering failed; using raw prompt: %s", exc)

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

    agent = AgentCreator.create_agent(
        agent_type,
        endpoint=endpoint,
        llm_name=provider or settings.LLM_PROVIDER,
        model_id=model_id,
        api_key=system_api_key,
        agent_id=agent_id,
        user_api_key=user_api_key,
        prompt=prompt,
        chat_history=chat_history or [],
        retrieved_docs=retrieved_docs,
        decoded_token=decoded_token,
        attachments=[],
        json_schema=json_schema,
        tool_executor=tool_executor,
    )
    if conversation_id:
        agent.conversation_id = str(conversation_id)

    answer_full = ""
    thought = ""
    sources_log: List[Dict[str, Any]] = []
    tool_calls: List[Dict[str, Any]] = []
    for event in agent.gen(query=query):
        if not isinstance(event, dict):
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
    error_type = "tool_not_allowed" if denied and not answer_full.strip() else None

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
        "model_id": model_id,
    }
