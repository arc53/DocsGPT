"""Resolve whether an answer is persisted and whether it lists in the sidebar.

Persistence (is a row written at all?) and visibility (does it show in the
owner's sidebar?) used to be one decision driven by the request-level
``save_conversation`` flag plus an identity heuristic. They are now separate:
conversations persist by default everywhere, while ``save_conversation`` only
controls sidebar visibility.
"""

from typing import Optional, Tuple

VISIBILITY_LISTED = "listed"
VISIBILITY_HIDDEN = "hidden"


def resolve_persistence(
    *,
    display_flag: Optional[bool],
    api_key: Optional[str] = None,
    is_shared_usage: bool = False,
    persist_flag: Optional[bool] = None,
) -> Tuple[bool, str]:
    """Resolve ``(should_persist, visibility)`` for an answer request.

    Args:
        display_flag: Request-level ``save_conversation`` (``None`` if the
            caller omitted it). Forces visibility on/off when provided.
        api_key: Present for programmatic/agent callers (including the
            OpenAI-compatible ``/v1`` endpoint), absent for first-party
            session users.
        is_shared_usage: True for shared-agent/widget traffic.
        persist_flag: Explicit persistence opt-out (``False`` to skip writing
            a row, e.g. stateless tool rounds that would orphan one). ``None``
            keeps the always-persist default.

    Returns:
        ``(should_persist, visibility)`` where ``visibility`` is
        ``"listed"`` or ``"hidden"``.
    """
    should_persist = True if persist_flag is None else bool(persist_flag)
    # Only genuine first-party interactive turns default to the sidebar.
    default_display = api_key is None and not is_shared_usage
    display = default_display if display_flag is None else bool(display_flag)
    visibility = VISIBILITY_LISTED if display else VISIBILITY_HIDDEN
    return should_persist, visibility
