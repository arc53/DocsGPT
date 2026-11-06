"""The model the drafter runs on: the caller's task model."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def drafter_model_id(user_id: Optional[str]) -> Optional[str]:
    """The catalog id of the model a draft for ``user_id`` runs on.

    The task model (the user's choice, else the instance's, else the default
    model) resolved by ``get_task_model_id``. Imported here, at call time, so
    tests patch this one function and the drafter never pins how the task
    model is resolved.

    Args:
        user_id: The caller.

    Returns:
        The model id, or None when no model can run a draft.
    """
    from docsgpt.core.model_utils import get_task_model_id

    model_id = get_task_model_id(user_id)
    return model_id or None


def drafter_model(user_id: Optional[str]) -> Optional[dict]:
    """The drafter's model as the config route reports it.

    Args:
        user_id: The caller, whose custom models resolve too.

    Returns:
        ``{"id", "display_name", "supports_tools"}``, or None when there is no
        model or the registry no longer knows it.
    """
    model_id = drafter_model_id(user_id)
    if not model_id:
        return None
    try:
        from docsgpt.core.model_registry import ModelRegistry

        model = ModelRegistry.get_instance().get_model(model_id, user_id=user_id)
    except Exception:
        logger.warning("drafter: model registry lookup failed", exc_info=True)
        return None
    if model is None or not getattr(model, "enabled", True):
        return None
    capabilities = getattr(model, "capabilities", None)
    return {
        "id": model_id,
        "display_name": getattr(model, "display_name", None) or model_id,
        "supports_tools": bool(getattr(capabilities, "supports_tools", False)),
    }
