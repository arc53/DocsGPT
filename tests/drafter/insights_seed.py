"""Labelled conversations for the agent gap summary tests, written the way the analytics sweep writes them."""

from __future__ import annotations

import datetime
import uuid
from typing import Optional

from sqlalchemy import text

from docsgpt.analytics import schema
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversation_labels import ConversationLabelsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository


def model_version() -> str:
    from docsgpt.decisions.models import V02, version

    return version(V02)


def agent(conn, owner: str = "owner", **analytics) -> dict:
    """A published agent with its own key, its analytics config as given."""
    return AgentsRepository(conn).create(
        owner, "Shipping help", "published", key=f"key-{uuid.uuid4().hex[:8]}",
        config={"analytics": analytics} if analytics else {},
    )


def message(conn, cid: str, position: int, prompt: str, response: str = "An answer.", *, days_ago: float = 1.0
            ) -> str:
    return conn.execute(
        text(
            """
            INSERT INTO conversation_messages (conversation_id, position, prompt, response, status, timestamp,
                                               updated_at)
            VALUES (CAST(:cid AS uuid), :position, :prompt, :response, 'complete',
                    now() - make_interval(secs => :ago), now() - make_interval(secs => :ago))
            RETURNING CAST(id AS text)
            """
        ),
        {"cid": cid, "position": position, "prompt": prompt, "response": response, "ago": days_ago * 86400},
    ).scalar()


def turn(conn, agent_id: Optional[str], prompt: str = "Where is my parcel?", *, gap: Optional[dict] = None,
         topics: Optional[dict] = None, days_ago: float = 1.0, user: str = "end-user", response: str = "An answer.",
         cid: Optional[str] = None, position: int = 0, api_key: Optional[str] = None) -> tuple[str, str]:
    """One answered question and its ``gap_type`` (and ``topic_effective``) labels; a new conversation unless
    ``cid`` is given.

    Returns:
        ``(conversation id, message id)``.
    """
    if cid is None:
        cid = str(ConversationsRepository(conn).create(user, "c", agent_id=agent_id, api_key=api_key)["id"])
    mid = message(conn, cid, position, prompt, response, days_ago=days_ago)
    at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    base = {"conversation_id": cid, "message_id": mid, "user_id": user, "agent_id": agent_id, "lang": "en",
            "schema_hash": schema.SCHEMA_HASH, "model_version": model_version(), "occurred_at": at}
    rows = [{**base, "level": "turn", "label": "gap_type", "derived": True,
             "probabilities": gap if gap is not None else {"none": 1.0}}]
    if topics is not None:
        rows.append({**base, "level": "message", "label": "topic_effective", "derived": True,
                     "top": max(topics, key=topics.get), "probabilities": topics})
    ConversationLabelsRepository(conn).upsert_many(rows)
    return cid, mid


def reaction(conn, agent_id: Optional[str], cid: str, answered: str, reply: str, label: str, yes: float,
             *, days_ago: float = 1.0, user: str = "end-user") -> None:
    """A yes/no reaction label (``frustrated``, ``asks_human``) of message ``reply`` to the answer of ``answered``."""
    at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    ConversationLabelsRepository(conn).upsert_many([{
        "conversation_id": cid, "message_id": answered, "reply_message_id": reply, "user_id": user,
        "agent_id": agent_id, "level": "reaction", "label": label, "probabilities": {"yes": yes, "no": 1 - yes},
        "lang": "en", "schema_hash": schema.SCHEMA_HASH, "model_version": model_version(), "occurred_at": at,
    }])
