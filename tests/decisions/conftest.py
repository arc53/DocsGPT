"""Shared fixtures for the decision-model tests: the release files recorded from the Hub at the pinned revisions,
and API mode against a fake server."""

import json
import sys
import time
from pathlib import Path

import pytest

import docsgpt.decisions as decisions
from docsgpt.core.settings import settings
from docsgpt.decisions.backends.http import RemoteBackend
from docsgpt.decisions.backends.onnx import OnnxBackend
from docsgpt.decisions.models import V02
from docsgpt.decisions.vendor.arc_decide import Decider as Release

from .fakes import FakeEngine, fake_torch, stand_in

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "decisions"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def release():
    return load_fixture("release.json")


@pytest.fixture
def serving_v02():
    return load_fixture("arcd_serving-0.4b-v0.2.json")


@pytest.fixture
def serving_v01():
    return load_fixture("arcd_serving-0.6b-v0.1.json")


@pytest.fixture
def questions_json():
    return load_fixture("questions.json")


#: The real ``OnnxBackend._schedule_tick``, for the one test that checks it.
schedule_tick = OnnxBackend._schedule_tick


@pytest.fixture(autouse=True)
def _no_hub(monkeypatch):
    """No decision test downloads anything; tests of the downloader patch ``snapshot_download`` themselves."""

    def refuse(**kwargs):
        raise AssertionError(f"a test tried to download {kwargs.get('repo_id')} from the Hub")

    monkeypatch.setattr("huggingface_hub.snapshot_download", refuse)


@pytest.fixture(autouse=True)
def _no_cpu_timer(monkeypatch):
    """No CPU-budget timer in unit tests: a minute later it would rebuild a stale backend in another test.

    Tests drive ``OnnxBackend._tick`` themselves.
    """
    monkeypatch.setattr(OnnxBackend, "_schedule_tick", lambda self: None)


#: API-mode settings at their defaults, pointed at a fake server; the answer cache is off so every call is sent.
#: ``INTERNAL_KEY`` is set so the tests can show it never leaves the process.
API_SETTINGS = {
    "DECISION_MODE": None, "DECISION_BASE_URL": "http://decider:7095", "DECISION_PROTOCOL": "decide",
    "DECISION_MODEL": None, "DECISION_MODEL_PATH": None, "DECISION_KEY": None, "INTERNAL_KEY": "internal-key",
    "DECISION_BATCH_SIZE": 32, "DECISION_API_RETRIES": 1, "DECISION_BREAKER_FAILURES": 3,
    "DECISION_BREAKER_COOLDOWN": 30.0, "DECISION_PROBE_SECONDS": 30, "DECISION_API_CONCURRENCY": 4,
    "DECISION_BACKGROUND_CONCURRENCY": 1, "DECISION_VLLM_PRIORITY": False, "DECISION_CACHE_SIZE": 0,
    "DECISION_LOAD_RETRY_SECONDS": 300,
}


@pytest.fixture
def api(monkeypatch):
    """Switch to API mode; call the fixture with overrides (``api(DECISION_PROTOCOL="vllm")``)."""

    def configure(**values):
        for name, value in {**API_SETTINGS, **values}.items():
            monkeypatch.setattr(settings, name, value)

    configure()
    return configure


@pytest.fixture
def spawned(monkeypatch):
    """Background jobs of the API backends, recorded instead of run, so each test drives them itself."""
    jobs = []
    monkeypatch.setattr(RemoteBackend, "_spawn", lambda self, job, name: jobs.append((name, job)))
    return jobs


@pytest.fixture
def remote(api, spawned):
    """Build API backends on a fake server's transport; every one is closed after the test."""
    built = []

    def make(cls, server, **kwargs):
        backend = cls(transport=server.transport(), **kwargs)
        built.append(backend)
        return backend

    yield make
    for backend in built:
        backend.close()


@pytest.fixture
def local(monkeypatch):
    """Mode ``local`` (the shipped default) with a client whose backend runs a fake engine."""
    monkeypatch.setattr(settings, "DECISION_MODE", None)
    monkeypatch.setattr(settings, "DECISION_MODEL", None)
    monkeypatch.setattr("docsgpt.celery_init.in_worker", lambda: False)
    engine = FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json"))
    client = decisions.get_decider()
    client._backend = OnnxBackend(V02, open_engine=lambda backend: engine)
    client._backend.warm()
    end = time.monotonic() + 5
    while client._backend.status == "loading" and time.monotonic() < end:
        time.sleep(0.005)
    yield client, engine
    decisions.tokens.reset()


@pytest.fixture
def reference(monkeypatch):
    """The release PyTorch client, unmodified, over the stand-in model and a published ``arcd_serving.json``."""
    monkeypatch.setitem(sys.modules, "torch", fake_torch())
    return lambda serving: stand_in(Release.__new__(Release), serving)
