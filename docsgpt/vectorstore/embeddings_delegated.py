"""Query embedding executed in the Celery worker instead of in the API.

The API embeds every query it serves, so it needs an embedder -- and a local
one costs roughly 800 MB of ONNX Runtime per process. That is the whole
footprint of an API container that otherwise holds no model.

This client keeps the interface (``embed_query``/``embed_documents``/
``dimension``) and moves only the computation: the text goes to the worker over
Celery and the vector comes back. The API pays a broker round trip per query
and no resident model.

Inside a worker there is nothing to delegate to -- dispatching would queue work
behind the task already running and wait on itself -- so a call made anywhere in
a worker process, including from a thread a task started, runs locally, on a
model this process loads once and caches.
``DOCUMENT_PARSE_QUEUE`` exists for the same reason on the parsing side.

Production deployments should point ``EMBEDDINGS_BASE_URL`` at a real embedding
service instead: that removes the model from *both* processes and costs a
network hop rather than a broker round trip.
"""

from __future__ import annotations

import logging
import threading
import time

#LRU store fo query-embedding cache
from collections import OrderedDict

#Tuple for query-embedding-cache type hints
from typing import Any, List, Optional, Tuple

from docsgpt.core.settings import settings
from docsgpt.vectorstore.model_registry import dimension_for

logger = logging.getLogger(__name__)

#: Dispatched by name so the API never imports the task module -- and through
#: it ``docsgpt.worker``, which pulls in the whole parsing stack.
EMBED_TASK = "docsgpt.vectorstore.embeddings_tasks.embed_texts"

#: How long after a failed dispatch to fail fast instead of waiting out another
#: full ``EMBEDDINGS_DELEGATE_TIMEOUT``. Short enough that a worker restart is
#: picked up within one query, long enough to collapse the retries inside a
#: single retrieval into one timeout rather than one per source.
_FAILURE_COOLDOWN = 30.0

#: How long a caller waits for the outcome of the dispatch already in flight
#: before giving up on its own. Only applies while the worker is unproven --
#: once one dispatch has succeeded, every caller goes straight to the broker.
#: Comfortably above a healthy round trip (~60 ms on a prefork worker) and far
#: below ``EMBEDDINGS_DELEGATE_TIMEOUT``, which is the point.
_PROBE_WAIT = 2.0

#: How long a successful query embedding is reused without another broker
#: round trip. Embeddings are deterministic per (model, key, text), so a short
#: TTL only risks serving a vector computed seconds ago -- while retries,
#: polls, and shared rephrased queries otherwise each pay a full dispatch.
_QUERY_CACHE_TTL = 60.0

#: Upper bound on cached query vectors per client instance. One entry holds a
#: single vector (~17 KB at 4k dims), so the cap bounds memory to a few MB.
_QUERY_CACHE_MAX = 128

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
    """True anywhere in a Celery worker process -- on any thread, not only the task's."""
    try:
        from docsgpt.celery_init import in_worker

        return in_worker()
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
        # A dispatch has completed successfully, so the worker is known to be
        # consuming the queue and callers need not take turns proving it.
        self._verified = False
        self._probing = False
        self._state_lock = threading.Lock()
        self._probe_done = threading.Event()
        # Successful query vectors by (embeddings_name, embeddings_key, text),
        # each with its monotonic timestamp. Guarded by ``_cache_lock``, kept
        # separate from ``_state_lock`` so cache reads never engage the
        # probe-gate machinery.
        # each client gets its own self._query_cache mapping (model, key, text) → (timestamp, vector), 
        # plus a dedicated self._cache_lock.  
        # The separate lock matters: the existing _state_lock drives the probe/cooldown gate, 
        # and an existing test asserts that lock is
        # untouched on the healthy path — sharing it would have broken that contract
        self._query_cache: "OrderedDict[Tuple[str, Optional[str], str], Tuple[float, List[float]]]" = OrderedDict()
        self._cache_lock = threading.Lock()

    def _cooldown_remaining(self) -> float:
        """Seconds left of the fail-fast window after a failed dispatch."""
        # One load: a concurrent success clearing the latch between two reads
        # would otherwise subtract from None.
        failed_at = self._failed_at
        if failed_at is None:
            return 0.0
        return max(0.0, _FAILURE_COOLDOWN - (time.monotonic() - failed_at))

    def _local_embeddings(self):
        """The in-process model, built once, for use inside a worker task."""
        if self._local is None:
            from docsgpt.vectorstore.base import build_local_embeddings

            self._local = build_local_embeddings(self.embeddings_name, self.embeddings_key)
        return self._local

    def _send(self, texts: List[str], queue: str, timeout: int) -> List[List[float]]:
        """Publish the embed task and wait for its vectors."""
        from docsgpt.celery_init import celery

        result = celery.send_task(EMBED_TASK, args=[texts, self.embeddings_name], queue=queue)
        try:
            vectors = result.get(timeout=timeout)
        except Exception as exc:
            self._failed_at = time.monotonic()
            # Drop the proof with the worker that supplied it. ``_verified``
            # short-circuits ahead of the probe gate, so leaving it set means
            # the gate only ever covers a worker that was never healthy --
            # while the case that actually happens is a healthy one being
            # redeployed or OOM-killed. Every caller would then pay the full
            # timeout, together, on every wave once the cooldown lapses.
            self._verified = False
            raise RuntimeError(
                f"Embedding request to the Celery worker timed out or failed ({exc}). "
                f"A worker must be consuming the {queue!r} queue for retrieval to "
                f"work. {_NO_WORKER_HINT}"
            ) from exc
        finally:
            _forget(result)
        self._failed_at = None
        self._verified = True
        return vectors

    def _cooldown_error(self, queue: str, remaining: float) -> RuntimeError:
        return RuntimeError(
            f"Skipping the embed dispatch: a previous request to the {queue!r} "
            f"queue failed and the {_FAILURE_COOLDOWN}s cooldown has "
            f"{remaining:.0f}s left. {_NO_WORKER_HINT}"
        )

    def _dispatch(self, texts: List[str]) -> List[List[float]]:
        """Run the embed task on the worker and wait for its vectors.

        A missing worker is a property of the deployment, not of this call, so
        at most one caller waits out ``EMBEDDINGS_DELEGATE_TIMEOUT`` to discover
        it. Two guards do that:

        The cooldown latch covers requests arriving *after* a failure -- without
        it a single retrieval pays the timeout twice, once in
        ``fanout.embed_questions`` and again per source when it falls back to
        letting each store embed its own query.

        The probe covers requests already in flight *alongside* the first one,
        which the latch cannot: nothing is latched until that first ``get()``
        returns, so every thread in the opening wave would otherwise block for
        the full timeout at once -- at the shipped 60s and 96 WSGI threads, an
        API that serves nothing at all, health checks included.
        """
        queue = settings.EMBEDDINGS_QUEUE
        timeout = settings.EMBEDDINGS_DELEGATE_TIMEOUT

        remaining = self._cooldown_remaining()
        if remaining > 0:
            raise self._cooldown_error(queue, remaining)

        if self._verified:
            return self._send(texts, queue, timeout)

        with self._state_lock:
            # "send" -- proven while we waited for the lock, just go.
            # "wait" -- another caller is already finding out; don't pay a
            #           second full timeout to learn the same thing.
            # "probe" -- nobody is; this call is the one that finds out.
            role = "send" if self._verified else "wait" if self._probing else "probe"
            if role == "probe":
                self._probing = True
                self._probe_done.clear()

        if role == "probe":
            try:
                return self._send(texts, queue, timeout)
            finally:
                with self._state_lock:
                    self._probing = False
                self._probe_done.set()

        if role == "wait":
            self._probe_done.wait(_PROBE_WAIT)
            remaining = self._cooldown_remaining()
            if remaining > 0:
                raise self._cooldown_error(queue, remaining)
            if not self._verified:
                raise RuntimeError(
                    f"Skipping the embed dispatch: an earlier request to the "
                    f"{queue!r} queue is still unanswered after {_PROBE_WAIT}s, so "
                    f"no worker appears to be consuming it. {_NO_WORKER_HINT}"
                )

        return self._send(texts, queue, timeout)

    def _cache_key(self, text: str) -> Tuple[str, Optional[str], str]:
        """Cache identity for one text under this client's model and key."""
        return (self.embeddings_name, self.embeddings_key, text)

    def _cached_vector(self, text: str) -> Optional[List[float]]:
        """Returns the stored vector for ``text`` on a hit (refreshing its LRU position) or None on a miss/expiry;""" 
        """expired entries are deleted."""
        entry = self._query_cache.get(self._cache_key(text))
        if entry is None:
            return None
        stamped_at, vector = entry
        if time.monotonic() - stamped_at >= _QUERY_CACHE_TTL:
            del self._query_cache[self._cache_key(text)]
            return None
        self._query_cache.move_to_end(self._cache_key(text))
        return vector

    def _remember_vectors(self, texts: List[str], vectors: List[List[float]]) -> None:
        """Cache successfully embedded texts, evicting the oldest first."""
        for text, vector in zip(texts, vectors):
            self._query_cache[self._cache_key(text)] = (time.monotonic(), vector)
            self._query_cache.move_to_end(self._cache_key(text))
            while len(self._query_cache) > _QUERY_CACHE_MAX:
                self._query_cache.popitem(last=False)

    def embed_documents(self, documents: List[str]) -> List[List[float]]:
        """Embed a list of texts, preserving order."""
        if not documents:
            return []
        texts = list(documents)
        with self._cache_lock:
            misses = [t for t in dict.fromkeys(texts) if self._cached_vector(t) is None]
        if _in_worker():
            fresh = self._local_embeddings().embed_documents(misses) if misses else []
        else:
            fresh = self._dispatch(misses) if misses else []
        with self._cache_lock:
            self._remember_vectors(misses, fresh)
            fresh_by_text = dict(zip(misses, fresh))
            vectors = []
            for t in texts:
                vector = fresh_by_text.get(t)
                if vector is None:
                    vector = self._cached_vector(t)
                vectors.append(vector)
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
