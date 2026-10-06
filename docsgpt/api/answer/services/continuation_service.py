"""Service for saving and restoring tool-call continuation state.

When a stream pauses (tool needs approval or client-side execution),
the full execution state is persisted to Postgres so the client can
resume later by sending tool_actions.
"""

import logging
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy import Connection

from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.conversations import (
    ConversationsRepository,
    MessageUpdateOutcome,
)
from docsgpt.storage.db.repositories.pending_tool_state import (
    PendingToolStateRepository,
)
from docsgpt.storage.db.serialization import coerce_pg_native as _make_serializable
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

# TTL for pending states — auto-cleaned after this period
PENDING_STATE_TTL_SECONDS = 30 * 60  # 30 minutes

# Re-export so the existing tests at tests/api/answer/services/test_continuation_service_pg.py
# can keep importing ``_make_serializable`` from here.
__all__ = [
    "_make_serializable",
    "answered_call_ids",
    "ContinuationNotPendingError",
    "ContinuationService",
    "NOT_PENDING_CODE",
    "NOT_PENDING_MESSAGE",
    "PENDING_STATE_TTL_SECONDS",
    "RETIRED_EXPIRED",
    "RETIRED_MOVED_ON",
    "ResumeInProgressError",
    "retire_paused_message",
]


class ResumeInProgressError(ValueError):
    """Raised when another request already owns a continuation claim."""


# The single wording every route answers this condition with. Handlers render
# this constant rather than ``str(exc)`` so no exception text — and nothing an
# exception might later be constructed from — can reach a response body.
RESUME_IN_PROGRESS_MESSAGE = "Resume already in progress for this conversation."


class ContinuationNotPendingError(ValueError):
    """Raised when tool actions answer a pause that is no longer waiting.

    It was decided, moved past by a new turn, or expired; or the actions name
    calls another pause is waiting on (a stale tab). Nothing was run.
    """


#: What every route answers a decision for a pause that is no longer waiting with.
NOT_PENDING_MESSAGE = "This request is no longer pending."

#: The error code that goes with :data:`NOT_PENDING_MESSAGE`.
NOT_PENDING_CODE = "tool_call_not_pending"

#: A pause retired because the user started a new turn instead of answering it.
RETIRED_MOVED_ON = "moved_on"

#: A pause retired because its TTL ran out before anyone answered it.
RETIRED_EXPIRED = "expired"

#: What the model and the chat read for a call that never ran, by (waiting on the client, why).
_NOT_RUN_TEXT = {
    (False, RETIRED_MOVED_ON): "Not run: the conversation moved on before this call was approved.",
    (False, RETIRED_EXPIRED): "Not run: the approval request expired before anyone answered it.",
    (True, RETIRED_MOVED_ON): "Not run: the conversation moved on before the app ran this call.",
    (True, RETIRED_EXPIRED): "Not run: the request for the app to run this call expired.",
}

#: Statuses of a call still waiting for the user or the client.
_WAITING = frozenset({"awaiting_approval", "requires_client_execution"})

#: Fields of a pending call the chat keeps on a call it shows (device, service).
_SHOWN_PENDING_KEYS = ("device_id", "connector_key", "connector_name", "access", "sent_arguments")


def answered_call_ids(tool_actions: Any) -> List[str]:
    """The call ids a resume request answers, in order (an unusable entry as ``""``, which matches nothing).

    Args:
        tool_actions: The request's ``tool_actions``.

    Returns:
        One id per action.
    """
    return [
        str(action.get("call_id") or "") if isinstance(action, dict) else ""
        for action in tool_actions or []
    ]


def not_run_entry(pending: Mapping[str, Any], reason: str) -> Dict[str, Any]:
    """The message's record of a call its pause was waiting on, which never ran.

    Args:
        pending: The pending call as the pause saved it.
        reason: :data:`RETIRED_MOVED_ON` or :data:`RETIRED_EXPIRED`.

    Returns:
        A ``denied`` tool call carrying ``not_run`` (the reason) and, as its
        result, the sentence later turns replay to the model.
    """
    for_client = pending.get("pause_type") == "requires_client_execution"
    entry: Dict[str, Any] = {
        "tool_name": pending.get("tool_name") or "unknown",
        "call_id": pending.get("call_id"),
        "action_name": pending.get("llm_name") or pending.get("name") or pending.get("action_name"),
        "arguments": pending.get("arguments") or {},
        "result": _NOT_RUN_TEXT[(for_client, reason)],
        "status": "denied",
        "not_run": reason,
    }
    for key in _SHOWN_PENDING_KEYS:
        if pending.get(key):
            entry[key] = pending[key]
    return entry


def retire_paused_message(conn: Connection, state: Mapping[str, Any], reason: str) -> Optional[str]:
    """Finalize the message of a pause nobody answered, from its saved state and stream journal.

    The message keeps what the turn did: its text so far, every call from
    every approval round (the ones that ran, as they ran), and the calls the
    pause waited on as never run. It becomes ``complete``, the calls that ran
    are confirmed, and the stream order is saved so a reload shows the turn as
    it streamed. A message that is already terminal is left alone.

    Args:
        conn: The transaction to write in (the one that took the pause, when
            there is one, so the two land together).
        state: The ``pending_tool_state`` row that was taken.
        reason: :data:`RETIRED_MOVED_ON` or :data:`RETIRED_EXPIRED`.

    Returns:
        The message id when the message was finalized, else None.
    """
    from docsgpt.api.answer.segments import merge_tool_calls
    from docsgpt.monitors import secret_refs
    from docsgpt.storage.db.repositories.message_events import MessageEventsRepository
    from docsgpt.utils import strip_null_bytes

    agent_config = state.get("agent_config") or {}
    message_id = str(agent_config.get("reserved_message_id") or "")
    if not looks_like_uuid(message_id):
        return None

    partial = MessageEventsRepository(conn).reconstruct_partial(message_id)
    pending = [call for call in state.get("pending_tool_calls") or [] if isinstance(call, dict)]
    earlier = agent_config.get("prior_tool_calls")
    if not isinstance(earlier, list):
        # A pause saved before the calls were carried in its state: the
        # journal has them as they were streamed.
        earlier = [
            call for call in partial["tool_calls"]
            if isinstance(call, dict) and call.get("status") not in _WAITING
        ]
    tool_calls = merge_tool_calls(earlier, [not_run_entry(call, reason) for call in pending])

    response, thought = partial["response"], partial["thought"]
    # The journal was sealed when the paused stream ended; seal again so a
    # secret the owner showed the assistant can never reach the stored row.
    exposed = secret_refs.exposed_values(str(state.get("user_id") or ""))
    if exposed:
        response, thought, tool_calls = secret_refs.redact((response, thought, tool_calls), exposed)

    sources = [dict(doc) for doc in (agent_config.get("retrieved_docs") or partial["sources"] or [])
               if isinstance(doc, dict)]
    for source in sources:
        if isinstance(source.get("text"), str):
            source["text"] = source["text"][:1000]

    metadata: Dict[str, Any] = {"pause_retired": reason}
    if partial["segments"]:
        metadata["segments"] = partial["segments"]
    fields = strip_null_bytes(
        {
            "response": response,
            "thought": thought,
            "sources": sources,
            "tool_calls": tool_calls,
            "metadata": metadata,
            "status": "complete",
        }
    )
    repo = ConversationsRepository(conn)
    outcome = repo.update_message_by_id(message_id, fields, only_if_non_terminal=True)
    if outcome is not MessageUpdateOutcome.UPDATED:
        logger.info(
            "retired pause left message %s as it was (outcome=%s)", message_id, outcome.value,
        )
        return None
    repo.confirm_executed_tool_calls(message_id)
    return message_id


def publish_pause_retired(
    user: str, conversation_id: str, message_id: Optional[str], reason: str
) -> None:
    """Tell the user's tabs a pause is over, so its approval toast and card stop asking.

    Best-effort: a failure is logged.

    Args:
        user: The owner.
        conversation_id: The conversation.
        message_id: The paused message, when known (the toast is matched on it).
        reason: Why: ``decided``, :data:`RETIRED_MOVED_ON` or :data:`RETIRED_EXPIRED`.
    """
    try:
        from docsgpt.events.publisher import publish_user_event

        payload: Dict[str, Any] = {"conversation_id": conversation_id, "reason": reason}
        if message_id:
            payload["message_id"] = str(message_id)
        publish_user_event(
            user, "tool.approval.cleared", payload, scope={"kind": "conversation", "id": conversation_id}
        )
    except Exception:
        logger.exception("publishing tool.approval.cleared (%s) failed", reason)


class ContinuationService:
    """Manages pending tool-call state in Postgres."""

    def __init__(self):
        # No-op constructor retained for call-site compatibility. State
        # lives in Postgres now; each operation opens its own short-lived
        # session rather than holding a connection on the service.
        pass

    def save_state(
        self,
        conversation_id: str,
        user: str,
        messages: List[Dict],
        pending_tool_calls: List[Dict],
        tools_dict: Dict,
        tool_schemas: List[Dict],
        agent_config: Dict,
        client_tools: Optional[List[Dict]] = None,
    ) -> str:
        """Save execution state for later continuation.

        ``conversation_id`` may be a Postgres UUID or the legacy Mongo
        ``ObjectId`` string — the latter is resolved via
        ``conversations.legacy_mongo_id`` to find the matching row.

        Args:
            conversation_id: The conversation this state belongs to.
            user: Owner user ID.
            messages: Full messages array at the pause point.
            pending_tool_calls: Tool calls awaiting client action.
            tools_dict: Serializable tools configuration dict.
            tool_schemas: LLM-formatted tool schemas (agent.tools).
            agent_config: Config needed to recreate the agent on resume.
            client_tools: Client-provided tool schemas for client-side execution.

        Returns:
            The string ID (conversation_id as provided) of the saved state.
        """
        with db_session() as conn:
            conv = ConversationsRepository(conn).get_by_legacy_id(conversation_id)
            if conv is not None:
                pg_conv_id = conv["id"]
            elif looks_like_uuid(conversation_id):
                pg_conv_id = conversation_id
            else:
                # Unresolvable legacy ObjectId — downstream ``CAST AS uuid``
                # would raise and poison the save. Surface the mismatch so
                # the caller can decide (the stream loop in routes/base.py
                # already wraps this in try/except).
                raise ValueError(
                    f"Cannot save continuation state: conversation_id "
                    f"{conversation_id!r} is neither a PG UUID nor a "
                    f"backfilled legacy Mongo id."
                )
            PendingToolStateRepository(conn).save_state(
                pg_conv_id,
                user,
                messages=_make_serializable(messages),
                pending_tool_calls=_make_serializable(pending_tool_calls),
                tools_dict=_make_serializable(tools_dict),
                tool_schemas=_make_serializable(tool_schemas),
                agent_config=_make_serializable(agent_config),
                client_tools=_make_serializable(client_tools) if client_tools else None,
            )

        logger.info(
            f"Saved continuation state for conversation {conversation_id} "
            f"with {len(pending_tool_calls)} pending tool call(s)"
        )
        return conversation_id

    def load_state(
        self, conversation_id: str, user: str
    ) -> Optional[Dict[str, Any]]:
        """Load pending continuation state.

        Returns:
            The state dict, or None if no pending state exists.
        """
        with db_readonly() as conn:
            conv = ConversationsRepository(conn).get_by_legacy_id(conversation_id)
            if conv is not None:
                pg_conv_id = conv["id"]
            elif looks_like_uuid(conversation_id):
                pg_conv_id = conversation_id
            else:
                # Unresolvable legacy ObjectId → no state can exist for it.
                return None
            doc = PendingToolStateRepository(conn).load_state(pg_conv_id, user)
        if not doc:
            return None
        return doc

    def claim_state(
        self, conversation_id: str, user: str, call_ids: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Atomically claim live state or classify an active duplicate.

        Args:
            conversation_id: The conversation.
            user: The owner.
            call_ids: The calls the request answers. When given, only a pause
                waiting on all of them is claimed.

        Returns:
            The claimed state, or None when no pause is waiting.

        Raises:
            ResumeInProgressError: Another request is resuming this pause.
            ContinuationNotPendingError: A pause is waiting, but not on these
                calls (they belong to one that is over).
        """
        with db_session() as conn:
            conv = ConversationsRepository(conn).get_by_legacy_id(conversation_id)
            if conv is not None:
                pg_conv_id = conv["id"]
            elif looks_like_uuid(conversation_id):
                pg_conv_id = conversation_id
            else:
                return None
            repo = PendingToolStateRepository(conn)
            claimed = repo.claim_state(pg_conv_id, user, call_ids)
            if not claimed:
                existing = repo.load_state_any(pg_conv_id, user)
                if existing and existing.get("status") == "resuming":
                    raise ResumeInProgressError(RESUME_IN_PROGRESS_MESSAGE)
                if call_ids is not None and repo.load_state(pg_conv_id, user) is not None:
                    raise ContinuationNotPendingError(NOT_PENDING_MESSAGE)
                return None
        _publish_decided(str(pg_conv_id), user, claimed)
        return claimed

    def delete_state(
        self, conversation_id: str, user: str, message_id: Optional[str] = None,
    ) -> bool:
        """Delete pending state after successful resumption.

        Args:
            conversation_id: The conversation.
            user: The owner.
            message_id: Delete only the pause of this message: a later turn
                may have paused while this one resumed.

        Returns:
            True if a row was deleted.
        """
        with db_session() as conn:
            conv = ConversationsRepository(conn).get_by_legacy_id(conversation_id)
            if conv is not None:
                pg_conv_id = conv["id"]
            elif looks_like_uuid(conversation_id):
                pg_conv_id = conversation_id
            else:
                # Unresolvable legacy ObjectId → nothing to delete.
                return False
            deleted = PendingToolStateRepository(conn).delete_state(pg_conv_id, user, message_id)
        if deleted:
            logger.info(
                f"Deleted continuation state for conversation {conversation_id}"
            )
        return deleted

    def release_claim(self, conversation_id: str, user: str) -> bool:
        """Return a claimed row to ``pending`` after a resume failed.

        Returns:
            True if a claim was released.
        """
        with db_session() as conn:
            conv = ConversationsRepository(conn).get_by_legacy_id(conversation_id)
            if conv is not None:
                pg_conv_id = conv["id"]
            elif looks_like_uuid(conversation_id):
                pg_conv_id = conversation_id
            else:
                return False
            released = PendingToolStateRepository(conn).release_claim(pg_conv_id, user)
        if released:
            logger.info(
                f"Released resume claim for conversation {conversation_id}"
            )
        return released

    def abandon_pending(self, conversation_id: str, user: str) -> Optional[Dict[str, Any]]:
        """Retire the pause a new turn moved past, before that turn reads its history.

        Takes the conversation's pause while it is still ``pending`` and, in
        the same transaction, finalizes its message (see
        :func:`retire_paused_message`), so the new turn's model sees the
        calls that never ran as not run. A decision that claimed the pause
        first keeps it: that approval runs, and nothing is abandoned. Then the
        user's other tabs are told, so the approval stops asking.

        Args:
            conversation_id: The conversation the new turn is in.
            user: The user starting it.

        Returns:
            The retired state, or None when no pause was waiting.
        """
        if not conversation_id or not user:
            return None
        with db_session() as conn:
            conv = ConversationsRepository(conn).get_by_legacy_id(conversation_id)
            if conv is not None:
                pg_conv_id = str(conv["id"])
            elif looks_like_uuid(conversation_id):
                pg_conv_id = str(conversation_id)
            else:
                return None
            state = PendingToolStateRepository(conn).abandon(pg_conv_id, user)
            if state is None:
                return None
            reason = RETIRED_EXPIRED if state.get("expired") else RETIRED_MOVED_ON
            retire_paused_message(conn, state, reason)
        message_id = (state.get("agent_config") or {}).get("reserved_message_id")
        logger.info(
            "retired an unanswered pause in conversation %s (%s)", pg_conv_id, reason,
            extra={"message_id": message_id, "reason": reason},
        )
        publish_pause_retired(user, pg_conv_id, message_id, reason)
        return state

    def mark_resuming(self, conversation_id: str, user: str) -> bool:
        """Flip the pending row to ``resuming`` so a crashed resume can be retried."""
        with db_session() as conn:
            conv = ConversationsRepository(conn).get_by_legacy_id(conversation_id)
            if conv is not None:
                pg_conv_id = conv["id"]
            elif looks_like_uuid(conversation_id):
                pg_conv_id = conversation_id
            else:
                return False
            flipped = PendingToolStateRepository(conn).mark_resuming(
                pg_conv_id, user
            )
        if flipped:
            logger.info(
                f"Marked continuation state as resuming for conversation "
                f"{conversation_id}"
            )
        return flipped


def _publish_decided(conversation_id: str, user: str, state: Dict[str, Any]) -> None:
    """Tell the user's tabs the turn's approval was decided, so its toast stops asking.

    ``tool.approval.required`` was only cleared when a pause failed or
    expired; one the user approved or denied in the chat kept surfacing as a
    toast elsewhere for half an hour. Best-effort: a failure is logged.
    """
    message_id = (state.get("agent_config") or {}).get("reserved_message_id")
    publish_pause_retired(user, conversation_id, message_id, "decided")
