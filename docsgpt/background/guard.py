"""The tool-result guardrail for what reaches a model after its turn ended.

A foreground tool result passes ``ToolExecutor._guardrail_tool_result``
before it fans out to the model, the UI and the journal. Background work
reaches a model later, from another thread or process, with no executor
around: a job's final result (the pool thread, the Celery runner and the
sandbox poller all finish through ``jobs.finalize``), and the data a wake
carries (a watch match, a monitor's page or tool output, a webhook body, an
approver's comment). This module runs the same ``tool_result`` stage on
those, with the engine of the agent that will read them, and reduces the
verdict the same way: a block replaces the text with the shared
"withheld" note, a redaction keeps the scrubbed text.

The engine is rebuilt here from the agent row (its ``config.guardrails``
merged with the instance floor), the way a turn of that agent builds it, and
its decisions are recorded against the message the data belongs to. As in
the foreground, a guardrail that raises lets the text through and logs.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text as sql_text

from docsgpt.guardrails.types import Stage, resolve_tool_result

logger = logging.getLogger(__name__)


class _EngineOwner:
    """The agent attributes ``build_engine`` and its judge factory read, for a run with no agent object."""

    def __init__(self, *, user_id: str, agent_id: Optional[str], agent_row: Optional[Dict[str, Any]], config: Any):
        from docsgpt.core.model_utils import (
            get_api_key_for_provider,
            get_default_model_id,
            get_provider_from_model_id,
            validate_model_id,
        )
        from docsgpt.core.settings import settings

        self.guardrails_config = config
        self.user = user_id
        self.agent_id = agent_id
        self.user_api_key = (agent_row or {}).get("key")
        self.request_id = None
        self.retrieved_docs: list = []
        self.decoded_token = {"sub": user_id}
        # A judge check calls a model: the agent's default one, as a headless run of this agent would.
        candidate = (agent_row or {}).get("default_model_id") or ""
        self.model_user_id: Optional[str] = None
        if candidate and validate_model_id(candidate, user_id=user_id):
            model_id = candidate
            self.model_user_id = user_id
        else:
            model_id = get_default_model_id()
        self.model_id = model_id
        self.llm_name = (
            get_provider_from_model_id(model_id, user_id=user_id) if model_id else None
        ) or settings.LLM_PROVIDER
        self.api_key = get_api_key_for_provider(self.llm_name)


def _agent_row(agent_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The agent's ``config``, ``key`` and ``default_model_id``, or None."""
    if not agent_id:
        return None
    from docsgpt.storage.db.session import db_readonly

    with db_readonly() as conn:
        row = conn.execute(
            sql_text("SELECT config, key, default_model_id FROM agents WHERE id = CAST(:id AS uuid)"),
            {"id": str(agent_id)},
        ).fetchone()
    return dict(row._mapping) if row is not None else None


def conversation_agent(conversation_id: Optional[str]) -> Optional[str]:
    """The agent a conversation runs (the one a continuation turn there uses), or None."""
    if not conversation_id:
        return None
    from docsgpt.storage.db.session import db_readonly

    with db_readonly() as conn:
        row = conn.execute(
            sql_text("SELECT agent_id FROM conversations WHERE id = CAST(:id AS uuid)"),
            {"id": str(conversation_id)},
        ).fetchone()
    return str(row[0]) if row is not None and row[0] is not None else None


def engine_for(*, user_id: Optional[str], agent_id: Optional[str]) -> Any:
    """The guardrail engine a turn of this agent runs with, or None when no ``tool_result`` control is active.

    Args:
        user_id: Who the run belongs to.
        agent_id: The agent, or None for an agentless chat (the instance floor still applies).

    Returns:
        A ``GuardrailEngine`` with a ``tool_result`` stage, or None.
    """
    from docsgpt.guardrails.runtime import build_engine, resolve_config

    row = _agent_row(agent_id)
    config = resolve_config((row or {}).get("config") or {})
    if not config.enabled or not config.has_any(Stage.TOOL_RESULT):
        return None
    owner = _EngineOwner(user_id=str(user_id or ""), agent_id=agent_id, agent_row=row, config=config)
    return build_engine(owner)


def scan(
    engine: Any,
    value: str,
    *,
    tool_name: str,
    action_name: str,
    message_id: Optional[str] = None,
) -> str:
    """Run the ``tool_result`` stage on ``value`` and return what the model may read.

    Mirrors ``ToolExecutor._guardrail_tool_result``, then records the
    decision against ``message_id`` (the turn that started the work).

    Args:
        engine: From :func:`engine_for`; None lets ``value`` through.
        value: The text.
        tool_name: The tool the text came from (the scan context).
        action_name: Its action.
        message_id: The message the decision is recorded against.

    Returns:
        ``value``, the scrubbed text, or the withheld note.
    """
    if engine is None or not isinstance(value, str) or not value:
        return value
    try:
        engine.context.tool_name = tool_name
        engine.context.action_name = action_name
        decision = engine.evaluate(value, Stage.TOOL_RESULT)
    except Exception:
        logger.exception("Background tool-result guardrail failed for %s.%s", tool_name, action_name)
        return value
    recorder = getattr(engine, "recorder", None)
    if recorder is not None and hasattr(recorder, "flush"):
        try:
            recorder.flush(message_id)
        except Exception:
            logger.exception("Recording a background guardrail decision failed")
    return resolve_tool_result(value, decision)


def guard_job_texts(job: Dict[str, Any], *values: Optional[str]) -> Tuple[Optional[str], ...]:
    """A finished job's texts (its result, its last output) as the model, the UI and the journal may see them.

    Args:
        job: The ``background_jobs`` row (``user_id``, ``agent_id``, tool, origin message).
        *values: The texts; None and empty ones pass through.

    Returns:
        The texts after the agent's ``tool_result`` guardrails, in order.
    """
    if not any(isinstance(v, str) and v for v in values):
        return values
    try:
        engine = engine_for(user_id=job.get("user_id"), agent_id=job.get("agent_id"))
    except Exception:
        logger.exception("background job %s: building the guardrail engine failed", job.get("id"))
        return values
    message_id = str(job["origin_message_id"]) if job.get("origin_message_id") else None
    return tuple(
        scan(
            engine,
            value,
            tool_name=str(job.get("tool_name") or ""),
            action_name=str(job.get("action_name") or ""),
            message_id=message_id,
        )
        if isinstance(value, str)
        else value
        for value in values
    )


def guard_payload(
    *,
    user_id: str,
    conversation_id: str,
    source: str,
    payload: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """A wake's untrusted data after the ``tool_result`` guardrails of the agent that will read it.

    The payload is scanned once, as the JSON the model is shown. A redaction
    keeps the payload's shape when the scrubbed JSON still parses, else the
    payload becomes ``{"data": <scrubbed text>}``; a block replaces it with
    ``{"withheld": <note>}``.

    Args:
        user_id: The conversation's owner.
        conversation_id: The conversation the continuation runs in.
        source: The wake source (the scan's action name).
        payload: The data, or None.

    Returns:
        The payload to queue.
    """
    if not payload:
        return payload
    try:
        rendered = json.dumps(payload, ensure_ascii=False, default=str)
        engine = engine_for(user_id=user_id, agent_id=conversation_agent(conversation_id))
    except Exception:
        logger.exception("wake: preparing the guardrail scan failed (%s)", conversation_id)
        return payload
    if engine is None:
        return payload
    guarded = scan(engine, rendered, tool_name="background_event", action_name=source)
    if guarded == rendered:
        return payload
    from docsgpt.guardrails.types import TOOL_RESULT_BLOCKED_NOTE

    if guarded == TOOL_RESULT_BLOCKED_NOTE:
        return {"withheld": guarded}
    try:
        reparsed = json.loads(guarded)
    except (TypeError, ValueError):
        return {"data": guarded}
    return reparsed if isinstance(reparsed, dict) else {"data": guarded}
