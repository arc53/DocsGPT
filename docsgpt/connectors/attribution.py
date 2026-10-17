"""Which connector a retrieved chunk came from, for "From Google Drive" citations.

Only the connector's key and display name are attached, never the account
behind the connection, so shared conversations show the same attribution
without revealing whose Drive it was.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text

from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)


def connector_labels(source_ids: list[str]) -> dict[str, dict]:
    """``{source_id: {"connector_key", "connector_name"}}`` for synced sources.

    Sources that do not come from a connection are left out. Never raises:
    attribution is decoration, and a lookup failure must not break an answer.
    """
    from docsgpt.connectors import service

    ids = [str(i) for i in source_ids if i and looks_like_uuid(str(i))]
    if not ids:
        return {}
    try:
        with db_readonly() as conn:
            rows = conn.execute(
                text(
                    "SELECT s.id AS source_id, cs.* FROM sources s "
                    "JOIN connector_sessions cs ON cs.id = s.connection_id "
                    "WHERE s.id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": ids},
            ).fetchall()
    except Exception:
        logger.warning("connector attribution lookup failed", exc_info=True)
        return {}
    labels = {}
    for row in rows:
        data = dict(row._mapping)
        public = service.serialize_connection({**data, "id": data["id"]})
        labels[str(data["source_id"])] = {
            "connector_key": public["connector_key"],
            "connector_name": public["name"],
        }
    return labels


class ConnectorLabelCache:
    """Per-search memo so each source is looked up once."""

    def __init__(self) -> None:
        self._labels: dict[str, dict] = {}

    def for_source(self, source_id: Optional[str]) -> dict:
        if not source_id:
            return {}
        key = str(source_id)
        if key not in self._labels:
            self._labels[key] = connector_labels([key]).get(key, {})
        return self._labels[key]
