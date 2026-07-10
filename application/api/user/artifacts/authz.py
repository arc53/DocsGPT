"""Parent-derived authorization helpers for artifact access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from flask import request

from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.artifacts import ArtifactsRepository
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.repositories.shared_conversations import (
    SharedConversationsRepository,
)
from application.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from application.storage.db.session import db_readonly


@dataclass(frozen=True)
class Principal:
    """The resolved caller of an artifact route.

    A decoded JWT is a full *owner* session (``agent_id`` is ``None``). An
    ``api_key`` is a low-trust, publicly-distributed *agent* credential -- it is
    embedded client-side in the widget and accepted from the query string -- so
    it resolves to the owning ``user_id`` but stays **agent-scoped**: it may reach
    an artifact only when the request also carries that artifact's parent
    ``conversation_id`` (the unguessable per-visitor secret), confining it to a
    single conversation rather than the agent's whole corpus, and may not perform
    mutating operations.
    """

    user_id: Optional[str] = None
    agent_id: Optional[str] = None

    @property
    def is_agent_scoped(self) -> bool:
        """True for an api_key (agent) principal that must be confined to its agent."""
        return self.agent_id is not None


def resolve_principal() -> Principal:
    """Resolve the caller to a :class:`Principal`.

    Priority: a decoded JWT (owner session) first, then an ``api_key`` query/form
    param (agent-scoped). An unresolvable caller yields an anonymous principal
    (both fields ``None``) that only a valid ``share_token`` can authorize.
    """
    decoded_token = getattr(request, "decoded_token", None)
    if decoded_token:
        return Principal(user_id=decoded_token.get("sub"))

    api_key = request.args.get("api_key") or request.form.get("api_key")
    if api_key:
        with db_readonly() as conn:
            agent = AgentsRepository(conn).find_by_key(api_key)
        if agent and agent.get("user_id") and agent.get("id"):
            return Principal(user_id=str(agent["user_id"]), agent_id=str(agent["id"]))
    return Principal()


def _shared_row_for(conn, conversation_id, share_token):
    """Return the shared_conversations row iff share_token grants this conversation, else None."""
    if not share_token:
        return None
    shared = SharedConversationsRepository(conn).find_by_uuid(share_token)
    if shared and str(shared.get("conversation_id")) == str(conversation_id):
        return shared
    return None


def user_can_access_conversation(
    conn, conversation_id: str, user_id: Optional[str], share_token: Optional[str]
) -> bool:
    """Allow if the caller owns/shares the conversation, or holds a valid share token.

    Conversation-level gate only. Reuses ``ConversationsRepository.get`` (owner OR
    ``shared_with``) so artifact access tracks message access, and honours a valid
    share token. A share-token caller reaches the conversation here but must still
    be snapshot-scoped per-artifact by the caller (see ``authorize_artifact``): a
    valid token does NOT imply access to every artifact in the conversation.
    """
    if user_id:
        if ConversationsRepository(conn).get(conversation_id, user_id) is not None:
            return True
    return _shared_row_for(conn, conversation_id, share_token) is not None


def authorize_artifact(conn, artifact: dict, principal: Principal) -> bool:
    """Authorize a READ of ``artifact`` for ``principal``; missing parent fails closed.

    A low-trust agent api_key is confined to a single conversation it proves by
    carrying that artifact's parent ``conversation_id`` query param (owner match +
    matching conversation + agent scope) and never inherits share-link access. A
    JWT owner or ``shared_with`` collaborator gets full access to every artifact of
    the parent; a share-token holder is confined to the shared ``first_n_queries``
    snapshot (an artifact whose ``message_id`` is outside it, or NULL, is denied).
    """
    if principal.is_agent_scoped:
        # An agent key is not the owner's session and is embedded in public widget
        # JS, so require the artifact to belong to the owner AND the request to
        # carry the parent conversation_id (the unguessable per-visitor secret):
        # the key alone, without that id, cannot download a known artifact.
        if str(artifact.get("user_id")) != str(principal.user_id):
            return False
        req_conv = request.args.get("conversation_id")
        parent = artifact.get("conversation_id")
        if not req_conv or parent is None or str(parent) != str(req_conv):
            return False
        return ArtifactsRepository(conn).artifact_in_agent_scope(
            str(artifact.get("id")), str(principal.agent_id)
        )

    conversation_id = artifact.get("conversation_id")
    workflow_run_id = artifact.get("workflow_run_id")
    share_token = request.args.get("share_token")

    if conversation_id is not None:
        # Owner or shared_with collaborator: full access to every artifact.
        if principal.user_id and ConversationsRepository(conn).get(
            str(conversation_id), principal.user_id
        ) is not None:
            return True
        # Share-token holder: only artifacts inside the shared first_n_queries snapshot.
        shared = _shared_row_for(conn, str(conversation_id), share_token)
        if shared is None:
            return False
        message_id = artifact.get("message_id")
        if not message_id:
            return False
        first_n = int(shared.get("first_n_queries") or 0)
        return ConversationsRepository(conn).message_in_first_n(
            str(conversation_id), str(message_id), first_n
        )
    if workflow_run_id is not None:
        if not principal.user_id:
            return False
        run = WorkflowRunsRepository(conn).get(str(workflow_run_id))
        return run is not None and run.get("user_id") == principal.user_id
    # No parent row reachable -> deny (e.g. deleted conversation/run).
    return False


def authorize_artifact_write(conn, artifact: dict, principal: Principal) -> bool:
    """Authorize a *mutating* artifact operation (e.g. delete / restore).

    Stricter than :func:`authorize_artifact`: a write requires an authenticated
    *owner* of the parent. Low-trust agent api_keys, share links, and
    ``shared_with`` collaborators inherit read/download access only, so an
    agent-scoped, anonymous, or share-token-only caller is denied -- they can read
    an artifact but never mutate it.
    """
    if principal.is_agent_scoped or not principal.user_id:
        return False
    conversation_id = artifact.get("conversation_id")
    workflow_run_id = artifact.get("workflow_run_id")

    if conversation_id is not None:
        return (
            ConversationsRepository(conn).get_owned(str(conversation_id), principal.user_id)
            is not None
        )
    if workflow_run_id is not None:
        run = WorkflowRunsRepository(conn).get(str(workflow_run_id))
        return run is not None and run.get("user_id") == principal.user_id
    # No parent row reachable -> deny (e.g. deleted conversation/run).
    return False
