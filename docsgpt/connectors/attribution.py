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


def source_names(source_ids: list[str]) -> dict[str, str]:
    """``{source_id: name}`` for every source, uploaded or synced.

    The model is told which knowledge a chunk came from, so a question that
    names a source ("Summarize test-1") can be matched to its chunks, whose
    own labels are file names. Never raises, like :func:`connector_labels`.
    """
    ids = [str(i) for i in source_ids if i and looks_like_uuid(str(i))]
    if not ids:
        return {}
    try:
        with db_readonly() as conn:
            rows = conn.execute(
                text("SELECT id, name FROM sources WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": ids},
            ).fetchall()
    except Exception:
        logger.warning("source name lookup failed", exc_info=True)
        return {}
    return {str(row.id): row.name for row in rows if row.name}


# Chunk keys only the model sees. ``source_name`` (what the owner called the
# knowledge) is not secret; it is prompt-only metadata the client does not
# use, so it is left out of what leaves the server.
PROMPT_ONLY_KEYS = frozenset({"source_name"})


def client_sources(docs: Any) -> Any:
    """Retrieved chunks as they may leave the server: in a stream, a response or a stored turn.

    Args:
        docs: The chunks a retrieval or an agent produced.

    Returns:
        A new list of copies without :data:`PROMPT_ONLY_KEYS`, so the caller's
        chunks keep them for the prompt. Anything but a list is returned as is.
    """
    if not isinstance(docs, list):
        return docs
    return [
        {key: value for key, value in doc.items() if key not in PROMPT_ONLY_KEYS} if isinstance(doc, dict) else doc
        for doc in docs
    ]


def _web_link(value: Any) -> Optional[str]:
    """``value`` when it is an http(s) address, else ``None``."""
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return value
    return None


class ConnectorLabelCache:
    """Per-search memo so each source is looked up once."""

    def __init__(self) -> None:
        self._labels: dict[str, dict] = {}

    def _look_up(self, keys: list[str]) -> None:
        """Fetch the labels and names of ``keys`` with one query each and cache them."""
        labels = connector_labels(keys)
        names = source_names(keys)
        for key in keys:
            found = dict(labels.get(key, {}))
            if names.get(key):
                found["source_name"] = names[key]
            self._labels[key] = found

    def prefetch(self, source_ids: list[Any]) -> None:
        """Look up every source a retrieval is about to label, in one batch.

        Without it each source costs two queries when its first chunk is
        labelled. Sources already cached are skipped; :meth:`for_source`
        remains the fallback for any this misses. Never raises.

        Args:
            source_ids: The sources whose chunks are about to be labelled.
        """
        keys = list(dict.fromkeys(str(i) for i in source_ids or () if i and str(i) not in self._labels))
        if not keys:
            return
        try:
            self._look_up(keys)
        except Exception:
            logger.warning("source label prefetch failed", exc_info=True)

    def for_source(self, source_id: Optional[str], metadata: Optional[dict] = None) -> dict:
        """The labels of a chunk from ``source_id``: its source's name, the connector, and its link when shown."""
        if not source_id:
            return {}
        key = str(source_id)
        if key not in self._labels:
            self._look_up([key])
        found = self._labels[key]
        labels = {k: v for k, v in found.items() if k != "show_links"}
        url = _web_link((metadata or {}).get("url")) if found.get("show_links") else None
        if url:
            labels["url"] = url
        return labels
