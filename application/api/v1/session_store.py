"""Short-lived correlation for chat-completions clients.

OpenAI's chat-completions schema has no conversation id. Coding clients such
as OpenCode do send stable session headers, though, so map those opaque values
to DocsGPT conversations without storing or logging the raw client id.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from application.cache import get_redis_instance
from application.core.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class V1Session:
    """A hashed Redis key for one agent/client/prompt namespace."""

    key: str


def _instruction_fingerprint(messages: list[dict[str, Any]]) -> str:
    instructions = [
        {"role": item.get("role"), "content": item.get("content")}
        for item in messages
        if item.get("role") in ("system", "developer")
    ]
    encoded = json.dumps(instructions, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def identify_session(
    headers: Mapping[str, str], data: dict[str, Any], agent_id: str
) -> Optional[V1Session]:
    """Build a privacy-preserving correlation key when the client supplies one."""
    raw = (
        headers.get("X-DocsGPT-Session-ID")
        or (data.get("docsgpt") or {}).get("session_id")
        or headers.get("X-Session-ID")
        or headers.get("X-Session-Id")
        or headers.get("X-Session-Affinity")
    )
    if not raw:
        return None
    prompt = _instruction_fingerprint(data.get("messages") or [])
    digest = hashlib.sha256(f"{agent_id}\0{raw}\0{prompt}".encode("utf-8")).hexdigest()
    return V1Session(key=f"v1:session:{digest}")


def load_conversation(session: Optional[V1Session]) -> Optional[str]:
    """Resolve a session key, degrading cleanly when Redis is unavailable."""
    if session is None:
        return None
    client = get_redis_instance()
    if client is None:
        return None
    try:
        value = client.get(session.key)
        return value.decode("utf-8") if isinstance(value, bytes) else value
    except Exception:
        logger.warning("Unable to load v1 session correlation", exc_info=True)
        return None


def save_conversation(session: Optional[V1Session], conversation_id: Optional[str]) -> None:
    """Store a session mapping with a bounded lifetime."""
    if session is None or not conversation_id or conversation_id == "None":
        return
    client = get_redis_instance()
    if client is None:
        return
    try:
        client.set(
            session.key,
            str(conversation_id),
            ex=settings.V1_SESSION_TTL_SECONDS,
        )
    except Exception:
        logger.warning("Unable to save v1 session correlation", exc_info=True)


def delete_conversation(session: Optional[V1Session]) -> None:
    """Delete a stale session mapping, degrading cleanly without Redis."""
    if session is None:
        return
    client = get_redis_instance()
    if client is None:
        return
    try:
        client.delete(session.key)
    except Exception:
        logger.warning("Unable to delete v1 session correlation", exc_info=True)
