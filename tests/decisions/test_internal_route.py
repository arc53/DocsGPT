"""The worker fallback in local mode: the API's internal decision routes, and a Celery worker calling them."""

import threading

import httpx2
import pytest
from flask import Flask
from starlette.testclient import TestClient

import docsgpt.decisions as decisions
from docsgpt.core.settings import settings
from docsgpt.decisions import Budget, Q, server, states, usage
from docsgpt.decisions.backends.http import ApiProcessBackend, DecideBackend
from docsgpt.decisions.backends.vllm import VllmBackend
from docsgpt.decisions.client import DecisionClient
from docsgpt.decisions.models import V02
from docsgpt.decisions.types import Request

from .fakes import FakeBackend, FakeDecideServer, expected_p

KEY = "internal-key"
ROUTES = "/api/internal/decisions"
AUTH = {"X-Internal-Key": KEY}
NOUL = {"type": "noul", "instructions": "Is it?"}


def flask_app():
    from docsgpt.api.internal.routes import internal

    app = Flask(__name__)
    app.register_blueprint(internal)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def api_process(monkeypatch):
    """The API process in local mode, its model a ``FakeBackend``: ``(Flask test client, backend)``."""
    for name, value in {"INTERNAL_KEY": KEY, "DECISION_MODE": "local", "DECISION_BASE_URL": None,
                        "DECISION_MODEL": None, "DECISION_KEY": None, "DECISION_MAX_BATCH_STATES": 128}.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr("docsgpt.celery_init.in_worker", lambda: False)
    backend = FakeBackend()
    decisions.get_decider()._backend = backend
    return flask_app().test_client(), backend


@pytest.mark.unit
class TestRoutes:
    @pytest.mark.parametrize("headers", [{}, {"X-Internal-Key": "wrong"}, {"Authorization": f"Bearer {KEY}"}])
    def test_need_the_internal_key(self, api_process, headers):
        client, backend = api_process
        assert client.get(f"{ROUTES}/v1/models", headers=headers).status_code == 401
        assert client.post(f"{ROUTES}/v1/decide", json={"state": "s", "questions": {"q": NOUL}},
                           headers=headers).status_code == 401
        assert backend.calls == []

    def test_refused_when_no_internal_key_is_configured(self, api_process, monkeypatch):
        client, _ = api_process
        monkeypatch.setattr(settings, "INTERNAL_KEY", None)
        assert client.get(f"{ROUTES}/v1/models", headers=AUTH).status_code == 401

    @pytest.mark.parametrize("method, path, body", [
        ("GET", "/v1/models", None),
        ("POST", "/v1/decide", {"state": "s", "questions": {"q": NOUL}}),
        ("POST", "/v1/decide", {"state": "s", "questions": {"q": {"type": "nope"}}}),
        ("POST", "/v1/decide", {"state": "s", "questions": {"q": NOUL}, "model": "someone/else"}),
        ("POST", "/v1/decide/batch", {"requests": [{"state": "a", "questions": {"q": NOUL}}, {"nope": 1},
                                                   {"state": "b", "questions": {"q": NOUL}}]}),
        ("POST", "/v1/decide/batch", {"requests": []}),
        ("POST", "/v1/decide", "not json"),
    ])
    def test_answer_as_decide_server_does(self, api_process, method, path, body):
        client, backend = api_process
        sidecar = TestClient(server.create_app(server.DecideService(backend)))
        kwargs = {"content": body} if isinstance(body, str) else {"json": body}
        theirs = sidecar.request(method, path, **kwargs)
        ours = client.open(f"{ROUTES}{path}", method=method, headers=AUTH,
                           **({"data": body} if isinstance(body, str) else {"json": body}))
        assert (ours.status_code, ours.get_json()) == (theirs.status_code, theirs.json())

    def test_lane_and_deadline_come_from_the_headers(self, api_process):
        client, backend = api_process
        reply = client.post(f"{ROUTES}/v1/decide", json={"state": "s", "questions": {"q": NOUL}},
                            headers={**AUTH, "X-Decision-Priority": "background", "X-Decision-Deadline-Ms": "1500"})
        assert reply.status_code == 200
        (_, lane, deadline), = backend.calls
        assert lane == "background" and 1.0 < deadline - server.time.monotonic() <= 1.5

    def test_a_full_lane_is_429_with_retry_after(self, api_process):
        client, backend = api_process
        backend.outcomes = ["queue_full"]
        reply = client.post(f"{ROUTES}/v1/decide", json={"state": "s", "questions": {"q": NOUL}}, headers=AUTH)
        assert reply.status_code == 429 and reply.headers["Retry-After"] == str(server.RETRY_AFTER_S)

    def test_load_starts_the_load_without_waiting(self, api_process):
        client, backend = api_process
        reply = client.post(f"{ROUTES}/v1/load", headers=AUTH)
        assert reply.status_code == 202 and reply.get_json() == {"status": "idle"} and backend.warmed == 1

    def test_calls_are_neither_counted_nor_traced_here(self, api_process, monkeypatch):
        """The worker's client records its own call; recording it here too would count it twice."""
        def refuse(*args, **kwargs):
            raise AssertionError("the internal route recorded a decision call")

        monkeypatch.setattr(usage, "count", refuse)
        monkeypatch.setattr("docsgpt.tracing.span", refuse)
        client, _ = api_process
        reply = client.post(f"{ROUTES}/v1/decide/batch", json={"requests": [{"state": "s", "questions": {"q": NOUL}}]},
                            headers=AUTH)
        assert reply.status_code == 200 and reply.get_json()["responses"][0]["answers"]["q"]["noul"] == 0.7

    @pytest.mark.parametrize("mode, url", [("none", None), ("api", "http://decider:7095")])
    def test_without_a_model_here_every_route_is_unavailable_and_nothing_loads(self, api_process, monkeypatch,
                                                                                mode, url):
        client, _ = api_process
        monkeypatch.setattr(settings, "DECISION_MODE", mode)
        monkeypatch.setattr(settings, "DECISION_BASE_URL", url)
        decisions.get_decider()._backend = None
        for method, path in [("GET", "/v1/models"), ("POST", "/v1/load"), ("POST", "/v1/decide"),
                             ("POST", "/v1/decide/batch")]:
            reply = client.open(f"{ROUTES}{path}", method=method, headers=AUTH,
                                json={"state": "s", "questions": {"q": NOUL}})
            assert reply.status_code == 503 and reply.get_json()["error"] == "unavailable"
        assert decisions.get_decider()._backend is None


@pytest.fixture
def worker(monkeypatch):
    """A Celery task process in local mode; ``DECISION_KEY`` is set to show it is not what the API gets."""
    for name, value in {"INTERNAL_KEY": KEY, "DECISION_MODE": None, "DECISION_BASE_URL": None,
                        "DECISION_MODEL": None, "DECISION_KEY": "decider-key", "API_URL": "http://api:7091",
                        "WORKER_API_URL": None}.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr("docsgpt.celery_init.in_worker", lambda: True)
    built = []
    yield built
    for backend in built:
        backend.close()


@pytest.mark.unit
class TestWorker:
    @pytest.mark.parametrize("worker_url, root", [
        (None, "http://api:7091"), ("http://127.0.0.1:7091/", "http://127.0.0.1:7091"),
    ])
    def test_calls_the_api_where_its_other_calls_go(self, worker, monkeypatch, worker_url, root):
        monkeypatch.setattr(settings, "WORKER_API_URL", worker_url)
        backend = decisions.get_decider()._new_backend()
        worker.append(backend)
        assert isinstance(backend, ApiProcessBackend) and backend.base_url == root + ROUTES

    def test_sends_the_internal_key_and_never_the_decision_key(self, worker):
        backend = ApiProcessBackend()
        worker.append(backend)
        headers = backend._headers("background", backend._clock() + 2)
        assert headers["X-Internal-Key"] == KEY and "Authorization" not in headers
        assert headers["X-Decision-Priority"] == "background"

    def test_status_says_calls_go_to_the_api_and_nothing_loads(self, worker):
        status = decisions.status()
        assert (status["mode"], status["status"], status["runtime"], status["available"]) == (
            "local", "idle", "api-process", True)
        assert decisions.get_decider()._backend is None

    @pytest.mark.parametrize("protocol, cls", [("decide", DecideBackend), ("vllm", VllmBackend)])
    def test_api_mode_never_sends_the_internal_key(self, worker, api, remote, monkeypatch, protocol, cls):
        api(DECISION_PROTOCOL=protocol, DECISION_KEY="decider-key")
        monkeypatch.setattr("docsgpt.celery_init.in_worker", lambda: True)
        built = decisions.get_decider()._new_backend()
        worker.append(built)
        assert type(built) is cls and built.base_url == "http://decider:7095"
        headers = built._headers("hot", built._clock() + 1)
        assert headers["Authorization"] == "Bearer decider-key" and "X-Internal-Key" not in headers
        if protocol == "decide":
            sidecar = FakeDecideServer()
            decisions.get_decider()._backend = remote(DecideBackend, sidecar)
            assert decisions.decide("s", {"q": NOUL}, feature="test", budget=Budget.hot(2.0)) is not None
            assert sidecar.log and not any("x-internal-key" in e["headers"] for e in sidecar.log)
            assert not any(KEY in str(dict(e["headers"])) for e in sidecar.log)


@pytest.mark.unit
class TestEndToEnd:
    """A worker's client, through the API's internal routes (a Flask test client), to the API process's own
    ``OnnxBackend`` over a fake engine."""

    @pytest.fixture
    def pair(self, local, worker, spawned, monkeypatch):
        monkeypatch.setattr(settings, "INTERNAL_KEY", KEY)
        monkeypatch.setattr(settings, "DECISION_CACHE_SIZE", 0)
        flask = flask_app().test_client()
        inside_api = threading.local()
        # One test process plays both sides: it is the worker except while a request is inside the API.
        monkeypatch.setattr("docsgpt.celery_init.in_worker", lambda: not getattr(inside_api, "on", False))
        sent = []

        def forward(request: httpx2.Request) -> httpx2.Response:
            sent.append((request.url.path, dict(request.headers)))
            inside_api.on = True
            try:
                reply = flask.open(request.url.path, method=request.method, data=request.content,
                                   headers=dict(request.headers))
            finally:
                inside_api.on = False
            return httpx2.Response(reply.status_code, content=reply.data,
                                   headers={"content-type": reply.content_type})

        assert isinstance(DecisionClient()._new_backend(), ApiProcessBackend)
        client = DecisionClient()
        client._backend = ApiProcessBackend(transport=httpx2.MockTransport(forward))
        worker.append(client._backend)
        return client, sent

    def test_answers_come_from_the_api_process(self, pair):
        client, sent = pair
        res = client.decide(states.text("hello"), {"injection": Q.INJECTION}, feature="test",
                            budget=Budget.hot(2.0))
        assert res is not None
        assert res.p("injection") == pytest.approx(expected_p('{\n  "text": "hello"\n}', Q.INJECTION))
        assert (res.model.id, res.model.mode, res.model.runtime) == (V02.id, "local", "api-process:onnx-int8")
        assert [path for path, _ in sent] == [f"{ROUTES}/v1/models", f"{ROUTES}/v1/decide"]
        assert all(h["x-internal-key"] == KEY and "authorization" not in h for _, h in sent)

    def test_a_batch_is_counted_once_by_the_worker(self, pair):
        client, sent = pair
        batch = client.decide_batch([Request("a", {"q": NOUL}), Request("b", {"q": NOUL})], feature="test",
                                    budget=Budget.background(5.0))
        assert batch.status == "ok" and all(isinstance(d.answers["q"]["noul"], float) for d in batch)
        assert sent[-1][0] == f"{ROUTES}/v1/decide/batch" and sent[-1][1]["x-decision-priority"] == "background"
        assert [row[0] for row in usage._counts.values()] == [1]
