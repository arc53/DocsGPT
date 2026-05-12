"""Deterministic source-id derivation for idempotent ingest.

Lives here (not in ``application/worker.py``) so both the HTTP route
(``application/api/user/sources/upload.py``) and the Celery worker
can import it without the route pulling the worker module's Celery
dependency tree into the API process at import time.

Pinned namespace is load-bearing — re-rolling it would mint different
``source_id``s for the same idempotency keys across deploys, defeating
the retry-resume contract that the rest of the ingest pipeline relies
on (see ``application/api/user/idempotency.py``).
"""

from __future__ import annotations

import uuid

# DO NOT CHANGE. See module docstring.
DOCSGPT_INGEST_NAMESPACE = uuid.UUID("fa25d5d1-398b-46df-ac89-8d1c360b9bea")


def derive_source_id(idempotency_key) -> uuid.UUID:
    """``uuid5(NS, key)`` when a key is supplied; ``uuid4()`` otherwise.

    A non-string / empty key falls back to ``uuid4()`` so the caller
    always gets a fresh id rather than a TypeError mid-route.
    """
    if isinstance(idempotency_key, str) and idempotency_key:
        return uuid.uuid5(DOCSGPT_INGEST_NAMESPACE, idempotency_key)
    return uuid.uuid4()
