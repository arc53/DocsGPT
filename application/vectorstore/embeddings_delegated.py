"""Query embedding executed in the Celery worker instead of in the API.

The API embeds every query it serves, so it needs an embedder -- and a local
one costs roughly 800 MB of ONNX Runtime per process. That is the whole
footprint of an API container that otherwise holds no model.

This client keeps the interface (``embed_query``/``embed_documents``/
``dimension``) and moves only the computation: the text goes to the worker over
Celery and the vector comes back. The API pays a broker round trip per query
and no resident model.

Inside a worker there is nothing to delegate to -- dispatching would queue work
behind the task already running and wait on itself -- so a call made while a
task is executing runs locally, on a model this process loads once and caches.
``DOCUMENT_PARSE_QUEUE`` exists for the same reason on the parsing side.

Production deployments should point ``EMBEDDINGS_BASE_URL`` at a real embedding
service instead: that removes the model from *both* processes and costs a
network hop rather than a broker round trip.
"""

from __future__ import annotations

import logging
import time
from typing import Any, List, Optional

from application.core.settings import settings
from application.vectorstore.model_registry import dimension_for

logger = logging.getLogger(__name__)

#: Dispatched by name so the API never imports the task module -- and through
#: it ``application.worker``, which pulls in the whole parsing stack.
EMBED_TASK = "application.vectorstore.embeddings_tasks.embed_texts"

#: How long after a failed dispatch to fail fast instead of waiting out another
#: full ``EMBEDDINGS_DELEGATE_TIMEOUT``. Short enough that a worker restart is
#: picked up within one query, long enough to collapse the retries inside a
#: single retrieval into one timeout rather than one per source.
_FAILURE_COOLDOWN = 30.0

_NO_WORKER_HINT = (
    "Start a worker consuming it, point EMBEDDINGS_BASE_URL at an embedding "
    "service, or set EMBEDDINGS_DELEGATE_TO_WORKER=false to load the model in "
    "this process instead."
)


def _forget(result) -> None:
    """Drop the task's stored vector from the result backend.

    Nothing ever reads it back. The key is ``celery-task-meta-<uuid>``, minted
    per dispatch rather than derived from the text, so a repeated query is a new
    task and a new key -- the value is written once, read once by the ``get()``
    already waiting on it, then dead. Left alone it occupies ~17 KB for
    ``result_expires`` (7 days), in the Redis the broker also runs on.

    Also releases the backend's pub/sub subscription for the task, which
    ``get()`` alone does not.

    Never raises: the vector is already in hand, and a backend that cannot
    delete must not fail the search. On the timeout path the worker may still
    store its result afterwards, leaving one orphaned key -- no worse than not
    forgetting at all, and bounded by the same expiry.
    """
    try:
        result.forget()
    except Exception as exc:  # noqa: BLE001 — cleanup must never fail a query
        logger.debug("Could not forget the embed task result: %s", exc)


def _in_worker() -> bool:
    """True when a Celery task is executing in this process."""
    try:
        from application.celery_init import celery

        return celery.current_worker_task is not None
    except Exception:
        return False


class DelegatedEmbeddings:
    """Embeds by dispatching to the Celery worker, or locally inside one."""

    def __init__(self, embeddings_name: str, embeddings_key: Optional[str] = None) -> None:
        self.embeddings_name = embeddings_name
        self.embeddings_key = embeddings_key
        self._local: Any = None
        self._dimension: Optional[int] = dimension_for(embeddings_name)
        self._failed_at: Optional[float] = None

    def _cooldown_remaining(self) -> float:
        """Seconds left of the fail-fast window after a failed dispatch."""
        if self._failed_at is None:
            return 0.0
        return max(0.0, _FAILURE_COOLDOWN - (time.monotonic() - self._failed_at))

    def _local_embeddings(self):
        """The in-process model, built once, for use inside a worker task."""
        if self._local is None:
            from application.vectorstore.base import build_local_embeddings

            self._local = build_local_embeddings(self.embeddings_name, self.embeddings_key)
        return self._local

    def _dispatch(self, texts: List[str]) -> List[List[float]]:
        """Run the embed task on the worker and wait for its vectors."""
        from application.celery_init import celery

        queue = getattr(settings, "EMBEDDINGS_QUEUE", "embeddings")
        timeout = getattr(settings, "EMBEDDINGS_DELEGATE_TIMEOUT", 60)

        # A missing worker is a property of the deployment, not of this call,
        # so once one dispatch has timed out the next is not worth another full
        # timeout. Without this latch a single retrieval pays the timeout twice
        # -- once in ``fanout.embed_questions``, then again per source when it
        # falls back to letting each store embed its own query.
        remaining = self._cooldown_remaining()
        if remaining > 0:
            raise RuntimeError(
                f"Skipping the embed dispatch: a previous request to the {queue!r} "
                f"queue failed and the {_FAILURE_COOLDOWN}s cooldown has "
                f"{remaining:.0f}s left. {_NO_WORKER_HINT}"
            )

        result = celery.send_task(EMBED_TASK, args=[texts, self.embeddings_name], queue=queue)
        try:
            vectors = result.get(timeout=timeout)
        except Exception as exc:
            self._failed_at = time.monotonic()
            raise RuntimeError(
                f"Embedding request to the Celery worker timed out or failed ({exc}). "
                f"A worker must be consuming the {queue!r} queue for retrieval to "
                f"work. {_NO_WORKER_HINT}"
            ) from exc
        finally:
            _forget(result)
        self._failed_at = None
        return vectors

    def embed_documents(self, documents: List[str]) -> List[List[float]]:
        """Embed a list of texts, preserving order."""
        if not documents:
            return []
        if _in_worker():
            return self._local_embeddings().embed_documents(documents)
        vectors = self._dispatch(list(documents))
        if self._dimension is None and vectors:
            self._dimension = len(vectors[0])
        return vectors

    def embed_query(self, query: str) -> List[float]:
        """Embed a single query string."""
        return self.embed_documents([query])[0]

    @property
    def dimension(self) -> Optional[int]:
        """Vector width, from the registry where possible.

        Falls back to one round trip for a model the registry does not
        describe, and to ``None`` when even that fails -- callers already treat
        an unknown width as "nothing to compare yet" rather than an error.
        """
        if self._dimension is None:
            try:
                self._dimension = len(self.embed_query("dimension probe"))
            except Exception as exc:
                logger.warning("Could not determine embedding width: %s", exc)
                return None
        return self._dimension

    def __call__(self, text):
        if isinstance(text, str):
            return self.embed_query(text)
        elif isinstance(text, list):
            return self.embed_documents(text)
        raise ValueError("Input must be a string or a list of strings")
