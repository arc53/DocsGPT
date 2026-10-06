"""Concurrent first use of the process-wide singletons on the request path.

Each test releases several threads together at a barrier while the
singleton's construction is slowed down, so the threads overlap inside it.
A singleton built twice hands different requests different objects: two
sandbox managers keep two session registries (a sandbox opened in the losing
one is never reaped and the session cap undercounts), and two embedding
models are loaded side by side.
"""

from __future__ import annotations

import threading
import time
from typing import List

import pytest

THREADS = 8
DELAY_SECONDS = 0.2


def _together(target) -> List[object]:
    """Run ``target`` on ``THREADS`` threads released together; return results."""
    barrier = threading.Barrier(THREADS)
    results: List[object] = []
    errors: List[BaseException] = []
    lock = threading.Lock()

    def worker():
        barrier.wait()
        try:
            value = target()
        except BaseException as exc:  # noqa: BLE001 - reported below
            with lock:
                errors.append(exc)
            return
        with lock:
            results.append(value)

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
    assert len(results) == THREADS
    return results


@pytest.mark.unit
def test_sandbox_manager_is_built_once_under_concurrent_first_use(monkeypatch):
    from docsgpt.sandbox import sandbox_creator as sc

    built: List[int] = []

    def slow_backend(cls, type_name):
        built.append(1)
        time.sleep(DELAY_SECONDS)
        return object()

    monkeypatch.setattr(sc.SandboxCreator, "create_backend", classmethod(slow_backend))
    sc.SandboxCreator.reset()
    try:
        managers = _together(sc.SandboxCreator.get_manager)
    finally:
        sc.SandboxCreator.reset()

    assert len({id(m) for m in managers}) == 1
    assert len(built) == 1, f"backend built {len(built)} times"


@pytest.mark.unit
def test_embeddings_model_is_loaded_once_under_concurrent_first_use(monkeypatch):
    from docsgpt.vectorstore import base as vs_base

    loaded: List[int] = []

    def slow_create(name, *args, **kwargs):
        loaded.append(1)
        time.sleep(DELAY_SECONDS)
        return object()

    monkeypatch.setattr(vs_base.settings, "EMBEDDINGS_BASE_URL", None)
    monkeypatch.setattr(vs_base.EmbeddingsSingleton, "_create_instance", staticmethod(slow_create))
    monkeypatch.setattr(vs_base.EmbeddingsSingleton, "_instances", {})

    instances = _together(lambda: vs_base.EmbeddingsSingleton.get_instance("some-model"))

    assert len({id(i) for i in instances}) == 1
    assert len(loaded) == 1, f"model loaded {len(loaded)} times"


@pytest.mark.unit
def test_remote_embeddings_client_is_built_once_under_concurrent_first_use(monkeypatch):
    from docsgpt.vectorstore import base as vs_base

    built: List[int] = []

    class SlowRemote:
        def __init__(self, **kwargs):
            built.append(1)
            time.sleep(DELAY_SECONDS)

    monkeypatch.setattr(vs_base.settings, "EMBEDDINGS_BASE_URL", "http://embeddings.local")
    monkeypatch.setattr(vs_base, "RemoteEmbeddings", SlowRemote)
    monkeypatch.setattr(vs_base.EmbeddingsSingleton, "_instances", {})

    instances = _together(lambda: vs_base.EmbeddingsSingleton.get_instance("some-model"))

    assert len({id(i) for i in instances}) == 1
    assert len(built) == 1, f"client built {len(built)} times"
