"""Prompt-injection scanning of a source's chunks as they are indexed, and the summary the sources list shows.

A source is scanned while its own ``guardrails.injection_scan`` is on and the operator's
``DECISION_INJECTION_ENABLED`` switch is. Every worker path that writes chunk text into a vector store scores it
first: an upload, remote or connector ingest and its scheduled syncs batch by batch (FAISS's seed chunk
included), the files a reingest adds, and a re-embedded wiki page. Turning the setting on for a source already
indexed queues a scan of its existing chunks, where the vector store can list them.

Scores go only to ``content_scores`` (``injection_scoring``), never into the vector store: retrieval finds them by
content, and a sync that re-embeds unchanged chunks costs one cache query per batch. Scanning never fails or
retries an ingest: nothing here raises, and a model that is down or loading ends the scan for that run, leaving the
rest of its chunks to be scored when a turn first retrieves them.

The summary (``sources.metadata.injection_scan``) is read from the cache once the index is written, so an ingest
that resumed part-way after an autoretry still counts every chunk.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence

from docsgpt.core.settings import settings
from docsgpt.decisions import Budget
from docsgpt.decisions.features import INJECTION_INGEST
from docsgpt.decisions.types import BACKEND_REASONS
from docsgpt.guardrails import injection_scoring

logger = logging.getLogger(__name__)

#: Chunks scored per call when a source's existing chunks are scanned, so a scan stopped part-way keeps what it
#: scored and the setting is checked again between batches.
BATCH_CHUNKS = 32
#: Hashes looked up per cache query when a summary is computed.
LOOKUP_CHUNK = 1000


def _clean(texts: Iterable[Any]) -> List[str]:
    """The texts as the vector store keeps them (NUL characters dropped), without blank ones."""
    from docsgpt.parser.embedding_pipeline import sanitize_content

    return [sanitize_content(t) for t in texts if isinstance(t, str) and t.strip()]


def scan_enabled(source_id: Any, config: Optional[dict] = None) -> bool:
    """Whether the chunks being written for a source are scanned: its ``injection_scan`` and the switch.

    The setting is read as the ingest will store it: the ``config`` the ingest carries, else the source row's
    own; a source not created yet gets the admin's defaults for new sources under the carried config.

    Args:
        source_id: The source's id.
        config: The ``SourceConfig`` dict the ingest carries, when it carries one.
    """
    if not settings.DECISION_INJECTION_ENABLED:
        return False
    try:
        from docsgpt.storage.db import source_defaults
        from docsgpt.storage.db.repositories.sources import SourcesRepository
        from docsgpt.storage.db.session import db_readonly
        from docsgpt.storage.db.source_config import SourceConfig

        with db_readonly() as conn:
            row = SourcesRepository(conn).get_by_id(str(source_id))
            if row is None:
                effective = source_defaults.seed(conn, config or None)
            else:
                # ``/api/upload_index`` keeps the row's config unless the ingest sends one.
                effective = config or row.get("config")
        return SourceConfig.parse(effective).guardrails.injection_scan
    except Exception:  # noqa: BLE001 - an unreadable setting scans nothing; retrieval scores what is used
        logger.warning("Could not read the prompt-injection scan setting of source %s", source_id, exc_info=True)
        return False


class Scanner:
    """Scores one source's chunks, batch by batch, during one ingest.

    Once the model answers that it is unavailable (down, loading past the background budget, off), the
    scanner stops for the rest of the run and logs it once.
    """

    def __init__(self, source_id: Any):
        self.source_id = str(source_id)
        self.stopped = False
        self.scored = 0

    def __call__(self, texts: Sequence[Any]) -> None:
        """Score ``texts`` into the cache; never raises."""
        if self.stopped:
            return
        texts = _clean(texts)
        if not texts:
            return
        try:
            result = injection_scoring.score(texts, feature=INJECTION_INGEST, budget=Budget.BACKGROUND)
        except Exception:  # noqa: BLE001 - scanning never fails an ingest
            logger.warning("Prompt-injection scan of source %s failed; it stops for this run", self.source_id,
                           exc_info=True)
            self.stopped = True
            return
        self.scored += sum(1 for s in result if s is not None)
        down = next((r for r in result.reasons if r in BACKEND_REASONS), None)
        if down is not None:
            logger.warning(
                "Prompt-injection scan of source %s stopped: the decision model is unavailable (%s). Its other "
                "chunks are scored when a turn retrieves them.", self.source_id, down,
            )
            self.stopped = True

    def all(self, texts: Sequence[Any]) -> None:
        """Score ``texts`` in batches of ``BATCH_CHUNKS``, so the cache keeps what was scored if the model goes."""
        for start in range(0, len(texts), BATCH_CHUNKS):
            self(texts[start:start + BATCH_CHUNKS])


def scanner_for(source_id: Any, config: Optional[dict] = None) -> Optional[Scanner]:
    """A ``Scanner`` for the source when it is scanned (``scan_enabled``), else ``None``."""
    return Scanner(source_id) if scan_enabled(source_id, config) else None


def summarize(texts: Iterable[Any]) -> Optional[Dict[str, Any]]:
    """The scan summary of a source's chunks, read from the cache.

    Returns:
        ``{scorer, scanned, unscored, suspected, high, max_p, at}``: chunks with a cached score and without one,
        those at or above the flag threshold (0.5, ``suspected``, which includes ``high``) and the threshold
        (0.9, ``high``), the highest score and when it was computed (ISO 8601, UTC). ``None`` with no model
        configured.
    """
    from docsgpt.guardrails.checks.model_injection import FLAG_THRESHOLD, THRESHOLD

    scorer = injection_scoring.scorer_id()
    if scorer is None:
        return None
    texts = _clean(texts)
    distinct = list(dict.fromkeys(texts))
    found: Dict[str, float] = {}
    for start in range(0, len(distinct), LOOKUP_CHUNK):
        part = distinct[start:start + LOOKUP_CHUNK]
        for text, score in zip(part, injection_scoring.lookup(part)):
            if score is not None:
                found[text] = score.p
    scores = [found[t] for t in texts if t in found]
    return {
        "scorer": scorer,
        "scanned": len(scores),
        "unscored": len(texts) - len(scores),
        "suspected": sum(1 for p in scores if p >= FLAG_THRESHOLD),
        "high": sum(1 for p in scores if p >= THRESHOLD),
        "max_p": round(max(scores), 4) if scores else None,
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def write_summary(source_id: Any, texts: Iterable[Any]) -> Optional[Dict[str, Any]]:
    """Compute the summary of the source's chunks and store it as ``sources.metadata.injection_scan``.

    Never raises.

    Args:
        source_id: The source's id; the row must exist.
        texts: Every chunk text of the source.

    Returns:
        The summary stored, or ``None`` when none was.
    """
    try:
        summary = summarize(texts)
        if summary is None:
            return None
        from docsgpt.storage.db.repositories.sources import SourcesRepository
        from docsgpt.storage.db.session import db_session

        with db_session() as conn:
            stored = SourcesRepository(conn).set_injection_scan(str(source_id), summary)
        return summary if stored else None
    except Exception:  # noqa: BLE001 - the summary is a display aid
        logger.warning("Could not store the prompt-injection scan summary of source %s", source_id, exc_info=True)
        return None


def lists_chunks() -> bool:
    """Whether the configured vector store can list a source's chunks (every store but Elasticsearch)."""
    from docsgpt.vectorstore.base import BaseVectorStore
    from docsgpt.vectorstore.vector_creator import VectorCreator

    store = VectorCreator.vectorstores.get(str(settings.VECTOR_STORE).lower())
    return store is not None and store.get_chunks is not BaseVectorStore.get_chunks


def list_texts(store: Any) -> Optional[List[str]]:
    """Every chunk text of a source's vector store, or ``None`` when it cannot list them or the listing failed."""
    try:
        chunks = store.get_chunks()
    except Exception:  # noqa: BLE001 - no listing, no summary
        logger.warning("Could not list chunks for the prompt-injection scan summary", exc_info=True)
        return None
    if chunks is None:
        return None
    return [c.get("text") or "" for c in chunks if isinstance(c, dict)]


def refresh_summary(source_id: Any, store: Any) -> Optional[Dict[str, Any]]:
    """Store the summary over every chunk the source's vector store lists; nothing when it cannot list them."""
    texts = list_texts(store)
    return write_summary(source_id, texts) if texts is not None else None


def start_backfill(source_id: Any) -> str:
    """Queue a scan of a source's chunks already indexed, after its owner turned scanning on.

    Returns:
        ``queued``, or ``lazy`` when the store cannot list chunks (or the task could not be queued): its chunks
        are then scored as turns retrieve them.
    """
    try:
        if not lists_chunks():
            return "lazy"
        from docsgpt.api.user.tasks import scan_source_injection

        scan_source_injection.delay(str(source_id))
    except Exception:  # noqa: BLE001 - the scan is an extra; retrieval still scores what it uses
        logger.warning("Could not queue the prompt-injection scan of source %s", source_id, exc_info=True)
        return "lazy"
    return "queued"


def scan_source(source_id: Any) -> Dict[str, Any]:
    """The background scan of a source's indexed chunks, then its summary.

    Stops between batches when the source's setting (or the switch) was turned off meanwhile, and when the
    model is unavailable.

    Returns:
        ``{"status", "chunks", "scored"}``: ``off``, ``unsupported`` (the store lists no chunks),
        ``stopped`` or ``scanned``.
    """
    if not scan_enabled(source_id):
        return {"status": "off", "chunks": 0, "scored": 0}
    from docsgpt.vectorstore.vector_creator import VectorCreator

    store = VectorCreator.create_vectorstore(
        settings.VECTOR_STORE, source_id=str(source_id), embeddings_key=settings.EMBEDDINGS_KEY,
    )
    texts = list_texts(store)
    if texts is None:
        return {"status": "unsupported", "chunks": 0, "scored": 0}
    scanner = Scanner(source_id)
    status = "scanned"
    for start in range(0, len(texts), BATCH_CHUNKS):
        if start and not scan_enabled(source_id):
            status = "stopped"
            break
        scanner(texts[start:start + BATCH_CHUNKS])
        if scanner.stopped:
            status = "stopped"
            break
    write_summary(source_id, texts)
    return {"status": status, "chunks": len(texts), "scored": scanner.scored}
