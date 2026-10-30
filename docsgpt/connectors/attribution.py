"""Which connector a retrieved chunk came from, for "From Google Drive" citations.

Only the connector's key and display name are attached, never the account
behind the connection, so shared conversations show the same attribution
without revealing whose Drive it was. A chunk also carries its file's link in
the service (``url``) while its source's ``retrieval.show_links`` is on.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text

from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.session import db_readonly
from docsgpt.storage.db.source_config import SourceConfig

logger = logging.getLogger(__name__)


def connector_labels(source_ids: list[str]) -> dict[str, dict]:
    """``{source_id: {"connector_key", "connector_name", "show_links"}}`` for synced sources.

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
                    "SELECT s.id AS source_id, s.config AS source_config, cs.* FROM sources s "
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
            "show_links": SourceConfig.parse(data.get("source_config")).retrieval.show_links,
        }
    return labels


def _web_link(value: Any) -> Optional[str]:
    """``value`` when it is an http(s) address, else ``None``."""
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return value
    return None


class ConnectorLabelCache:
    """Per-search memo so each source is looked up once."""

    def __init__(self) -> None:
        self._labels: dict[str, dict] = {}

    def for_source(self, source_id: Optional[str], metadata: Optional[dict] = None) -> dict:
        """The connector labels of a chunk from ``source_id``, plus its ``metadata`` link when shown."""
        if not source_id:
            return {}
        key = str(source_id)
        if key not in self._labels:
            self._labels[key] = connector_labels([key]).get(key, {})
        found = self._labels[key]
        labels = {k: v for k, v in found.items() if k != "show_links"}
        url = _web_link((metadata or {}).get("url")) if found.get("show_links") else None
        if url:
            labels["url"] = url
        return labels
