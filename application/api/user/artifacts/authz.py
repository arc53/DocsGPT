"""Parent-derived authorization helpers for artifact access."""

from __future__ import annotations

from typing import Optional

from flask import request

from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.repositories.shared_conversations import (
    SharedConversationsRepository,
)
from application.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from application.storage.db.session import db_readonly


def resolve_authenticated_user() -> Optional[str]:
    """Resolve the caller to a user id via decoded JWT ``sub`` or api_key→owner."""
    decoded_token = getattr(request, "decoded_token", None)
    if decoded_token:
        return decoded_token.get("sub")

    api_key = request.args.get("api_key") or request.form.get("api_key")
    if api_key:
        with db_readonly() as conn:
            agent = AgentsRepository(conn).find_by_key(api_key)
        if agent:
            return agent.get("user_id")
    return None


def user_can_access_conversation(
    conn, conversation_id: str, user_id: Optional[str], share_token: Optional[str]
) -> bool:
    """Allow if the caller owns/shares the conversation, or holds a valid share token.

    Reuses ``ConversationsRepository.get`` (owner OR ``shared_with``) so artifact
    access tracks message access; a publicly shared link inherits download access
    via its share token (see ``SharedConversationsRepository.find_by_uuid``).
    """
    if user_id:
        if ConversationsRepository(conn).get(conversation_id, user_id) is not None:
            return True
    if share_token:
        shared = SharedConversationsRepository(conn).find_by_uuid(share_token)
        if shared and str(shared.get("conversation_id")) == str(conversation_id):
            return True
    return False


def authorize_artifact(conn, artifact: dict, user_id: Optional[str]) -> bool:
    """Authorize an artifact by resolving its parent; missing parent fails closed."""
    conversation_id = artifact.get("conversation_id")
    workflow_run_id = artifact.get("workflow_run_id")
    share_token = request.args.get("share_token")

    if conversation_id is not None:
        return user_can_access_conversation(
            conn, str(conversation_id), user_id, share_token
        )
    if workflow_run_id is not None:
        if not user_id:
            return False
        run = WorkflowRunsRepository(conn).get(str(workflow_run_id))
        return run is not None and run.get("user_id") == user_id
    # No parent row reachable -> deny (e.g. deleted conversation/run).
    return False
