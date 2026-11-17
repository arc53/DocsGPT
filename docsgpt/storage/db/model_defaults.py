"""The admin's instance task model (Admin > Defaults > Models).

The task model runs DocsGPT's own jobs rather than a chat: the drafter,
GraphRAG graph extraction and the monitor judge. A user may pick their own in
Settings > General (``users.tool_preferences.task_model_id``); this module
holds the instance's choice for everyone who has not, as one JSON value in
``app_metadata``. It is a built-in model id: custom (BYOM) models belong to one
user and resolve for nobody else. ``docsgpt.core.model_utils.get_task_model_id``
puts the two together with ``TASK_MODEL_ID`` and the default model.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository

logger = logging.getLogger(__name__)

#: ``app_metadata`` key of the stored ``{"task_model_id": ...}`` object.
KEY = "models.defaults"


def _parse(raw: Any) -> Optional[str]:
    """The ``task_model_id`` of a stored value, or ``None`` when there is none or it is unreadable."""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("The stored model defaults are not JSON; the task model falls back")
        return None
    model_id = value.get("task_model_id") if isinstance(value, dict) else None
    return (model_id.strip() or None) if isinstance(model_id, str) else None


def stored_task_model(conn: Connection) -> Optional[str]:
    """The instance task model the admin stored, or ``None`` when none is.

    The id is not checked against the model catalog here; the resolver and
    the admin route do that.

    Args:
        conn: Database connection.
    """
    return _parse(AppMetadataRepository(conn).get(KEY))


def save_task_model(conn: Connection, model_id: Optional[str]) -> Optional[str]:
    """Store ``model_id`` as the instance task model (``None`` clears it) and return it as stored.

    Args:
        conn: Database connection.
        model_id: A built-in model id the caller validated, or ``None``.
    """
    AppMetadataRepository(conn).set(KEY, json.dumps({"task_model_id": model_id}))
    return model_id


def stored_task_models(conn: Connection, user_id: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """The user's and the instance's stored task model, in one round trip.

    Args:
        conn: Database connection.
        user_id: The user whose ``tool_preferences.task_model_id`` to read;
            ``None`` reads only the instance's.

    Returns:
        ``(user_choice, instance_choice)``, each ``None`` when not stored.
    """
    row = conn.execute(
        text(
            """
            SELECT
                (SELECT tool_preferences ->> 'task_model_id' FROM users WHERE user_id = :user_id) AS user_choice,
                (SELECT value FROM app_metadata WHERE key = :key) AS instance_raw
            """
        ),
        {"user_id": user_id, "key": KEY},
    ).fetchone()
    if row is None:
        return None, None
    user_choice = (row[0].strip() or None) if isinstance(row[0], str) and user_id else None
    return user_choice, _parse(row[1])
