"""Resolve whether an answer is persisted and whether it lists in the sidebar.

Persistence (is a row written at all?) and visibility (does it show in the
owner's sidebar?) are separate decisions. Conversations persist by default
everywhere, and visibility defaults to ``hidden`` for every caller: only an
explicit request-level ``visibility: "listed"`` — which the first-party UI
sends on normal chats — puts a conversation in the owner's sidebar. The
legacy ``save_conversation`` flag no longer affects either decision, so
API/OpenAI-compatible clients that still send it (its old meaning was
"persist this conversation") can't list rows into the agent owner's sidebar.
"""

from typing import Any, Optional, Tuple

VISIBILITY_LISTED = "listed"
VISIBILITY_HIDDEN = "hidden"


def resolve_persistence(
    *,
    visibility_flag: Optional[Any] = None,
    persist_flag: Optional[bool] = None,
) -> Tuple[bool, str]:
    """Resolve ``(should_persist, visibility)`` for an answer request.

    Args:
        visibility_flag: Request-level ``visibility`` value. Only the exact
            string ``"listed"`` opts the conversation into the owner's
            sidebar; anything else (including ``None``) stays hidden.
        persist_flag: Explicit persistence opt-out (``False`` to skip writing
            a row, e.g. stateless tool rounds that would orphan one). ``None``
            keeps the always-persist default.

    Returns:
        ``(should_persist, visibility)`` where ``visibility`` is
        ``"listed"`` or ``"hidden"``.
    """
    should_persist = True if persist_flag is None else bool(persist_flag)
    visibility = (
        VISIBILITY_LISTED
        if visibility_flag == VISIBILITY_LISTED
        else VISIBILITY_HIDDEN
    )
    return should_persist, visibility
