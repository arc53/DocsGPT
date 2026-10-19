"""``docsgpt decide-server``: the routes, the key, lanes and deadlines, and the API-mode client talking to it."""

import os
import subprocess
import sys
import threading
import time

import httpx2
import pytest
from starlette.testclient import TestClient

from docsgpt.core.settings import settings
from docsgpt.decisions import Q, files, server, tokens
from docsgpt.decisions.backends import Outcome
from docsgpt.decisions.backends.http import DecideBackend
from docsgpt.decisions.backends.onnx import OnnxBackend
from docsgpt.decisions.latency import SpeedProfile
from docsgpt.decisions.models import V01, V02
from docsgpt.decisions.types import Request

from .conftest import load_fixture
from .fakes import CharTokenizer, FakeBackend, FakeEngine

NOUL = {"type": "noul", "instructions": "Is it?"}


def answer(p=0.7):
    return {"q": {"type": "noul", "noul": p}}


@pytest.fixture
def keyless(monkeypatch):
    monkeypatch.setattr(settings, "DECISION_KEY", None)
    monkeypatch.setattr(settings, "DECISION_MODEL", None)
    monkeypatch.setattr(settings, "DECISION_MODEL_REVISION", None)
    monkeypatch.setattr(settings, "DECISION_LOCAL_QUEUE", 32)
    monkeypatch.setattr(settings, "DECISION_BACKGROUND_QUEUE", 8)
    monkeypatch.setattr(settings, "DECISION_MAX_BATCH_STATES", 128)


@pytest.fixture
def app(keyless):
    """``(TestClient, backend)`` over a fake backend; pass ``outcomes`` to script it."""

    def make(backend=None):
        backend = backend or FakeBackend()
        return TestClient(server.create_app(server.DecideService(backend))), backend

    return make


@pytest.mark.unit
class TestKey:
    def test_without_a_key_every_route_is_open(self, app):
        client, _ = app()
        assert client.get("/v1/models").status_code == 200

    def test_with_a_key_every_route_but_health_needs_it(self, app, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_KEY", "decider-key")
        monkeypatch.setattr(settings, "INTERNAL_KEY", "internal-key")
        client, backend = app()
        body = {"state": "x", "questions": {"q": NOUL}}
        for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Bearer internal-key"},
                        {"Authorization": "Basic decider-key"}):
            assert client.get("/v1/models", headers=headers).status_code == 401
            assert client.post("/v1/load", headers=headers).status_code == 401
            assert client.post("/v1/decide", json=body, headers=headers).status_code == 401
            assert client.post("/v1/decide/batch", json={"requests": [body]}, headers=headers).status_code == 401
        assert backend.calls == [] and backend.warmed == 0
        assert client.get("/health").status_code == 200
        good = {"Authorization": "Bearer decider-key"}
        assert client.post("/v1/decide", json=body, headers=good).status_code == 200
        assert client.get("/v1/models", headers={"authorization": "bearer decider-key"}).status_code == 200

    def test_the_key_is_compared_in_constant_time(self, monkeypatch):
        compared = []
        monkeypatch.setattr(server.hmac, "compare_digest", lambda a, b: compared.append((a, b)) or a == b)
        assert server.authorized("Bearer k", "k")
        assert compared == [(b"k", b"k")]

    @pytest.mark.parametrize("host, local", [("127.0.0.1", True), ("localhost", True), ("::1", True),
                                             ("0.0.0.0", False), ("192.168.1.5", False), ("decider", False)])
    def test_loopback(self, host, local):
        assert server.loopback(host) is local


@pytest.mark.unit
class TestServe:
    @pytest.fixture
    def started(self, monkeypatch, keyless):
        runs = []
        monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: runs.append(kwargs))
        monkeypatch.setattr("docsgpt.core.logging_config.setup_logging", lambda: None)
        backend = FakeBackend()
        monkeypatch.setattr(server, "build_backend", lambda device: backend)
        monkeypatch.setattr(settings, "DECISION_PRELOAD", False)
        monkeypatch.setattr(settings, "DECISION_INJECTION_ENABLED", False)
        return runs, backend

    def test_refuses_a_public_bind_without_a_key(self, started, caplog):
        runs, _ = started
        assert server.serve("0.0.0.0", 7095, "cpu") == 2
        assert runs == []
        assert "DECISION_KEY" in caplog.text

    def test_a_public_bind_with_a_key(self, started, monkeypatch):
        runs, backend = started
        monkeypatch.setattr(settings, "DECISION_KEY", "k")
        assert server.serve("0.0.0.0", 7095, "cpu") == 0
        assert runs[0]["host"] == "0.0.0.0" and runs[0]["access_log"] is False
        assert backend.warmed == 0, "nothing loads until a feature calls"

    def test_loopback_needs_no_key(self, started):
        runs, _ = started
        assert server.serve("127.0.0.1", 7095, "cpu") == 0
        assert runs

    @pytest.mark.parametrize("setting, value", [("DECISION_PRELOAD", True),
                                                ("DECISION_INJECTION_ENABLED", True),
                                                ("DECISION_RELEVANCE_ENABLED", True)])
    def test_loads_at_start_when_asked(self, started, monkeypatch, setting, value):
        _, backend = started
        monkeypatch.setattr(settings, setting, value)
        server.serve("127.0.0.1", 7095, "cpu")
        assert backend.warmed == 1

    def test_the_device_defaults_to_the_setting(self, monkeypatch, started):
        devices = []
        monkeypatch.setattr(server, "build_backend", lambda device: devices.append(device) or FakeBackend())
        monkeypatch.setattr(settings, "DECISION_DEVICE", "mps")
        server.serve("127.0.0.1", 7095, None)
        assert devices == ["mps"]

    def test_a_backend_that_cannot_start_is_an_exit_code(self, monkeypatch, started):
        def refuse(device):
            raise server.StartError("no mps here")

        monkeypatch.setattr(server, "build_backend", refuse)
        assert server.serve("127.0.0.1", 7095, "mps") == 2


@pytest.mark.unit
class TestBuildBackend:
    def test_cpu_is_onnx_with_v02(self, keyless):
        backend = server.build_backend("cpu")
        assert isinstance(backend, OnnxBackend) and backend.spec is V02 and backend.status == "idle"

    def test_torch_devices_need_the_extra(self, keyless, monkeypatch):
        monkeypatch.setattr("docsgpt.core.optional_deps.is_available", lambda module: False)
        with pytest.raises(server.StartError, match="decisions-torch"):
            server.build_backend("mps")

    def test_an_unknown_model_is_refused(self, keyless, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_MODEL", "someone/else")
        with pytest.raises(server.StartError, match="DECISION_MODEL"):
            server.build_backend("cpu")


@pytest.mark.unit
class TestRoutes:
    def test_health_answers_before_any_load(self, keyless):
        backend = OnnxBackend(V02, open_engine=lambda b: pytest.fail("health must not load the model"))
        client = TestClient(server.create_app(server.DecideService(backend)))
        response = client.get("/health")
        assert response.status_code == 200 and response.json() == {"status": "ok", "model": "idle"}

    def test_models_reports_identity_status_and_speed(self, app):
        client, backend = app()
        backend.status, backend.profile = "ready", SpeedProfile(0.01, 0.001, 1e-7, overhead=60, threads=4)
        (entry,) = client.get("/v1/models").json()["models"]
        assert entry["name"] == V02.id and entry["revision"] == V02.revision
        assert entry["prompt_hash"] == "78cfb276f93a" and entry["calibration"] == V02.calibration
        assert entry["runtime"] == "onnx-int8" and entry["max_state_tokens"] == 2048
        assert entry["status"] == "ready" and entry["speed"] == backend.profile.wire()

    def test_models_before_the_load_has_no_speed(self, app):
        client, _ = app()
        (entry,) = client.get("/v1/models").json()["models"]
        assert entry["status"] == "idle" and entry["speed"] is None

    def test_load_starts_the_load(self, app):
        client, backend = app()
        response = client.post("/v1/load")
        assert response.status_code == 202 and backend.warmed == 1

    def test_decide(self, app):
        client, backend = app()
        response = client.post("/v1/decide", json={"state": {"text": "x"}, "questions": {"q": NOUL}})
        assert response.status_code == 200
        assert response.json() == {"model": V02.id, "answers": answer(), "usage": {"input_tokens": 12,
                                                                                  "output_tokens": 0}}
        (requests, lane, _), = backend.calls
        assert requests == [Request({"text": "x"}, {"q": NOUL})] and lane == "hot"

    @pytest.mark.parametrize("body", [{"questions": {"q": NOUL}}, {"state": "x", "questions": {}},
                                      {"state": "x", "questions": {"Bad Key": NOUL}},
                                      {"state": "x", "questions": {"q": {"type": "score", "criteria": ["a"]}}}])
    def test_a_malformed_request_is_422(self, app, body):
        client, backend = app()
        response = client.post("/v1/decide", json=body)
        assert response.status_code == 422 and response.json()["error"] == "bad_item"
        assert backend.calls == []

    def test_a_body_that_is_not_json_is_400(self, app):
        client, _ = app()
        assert client.post("/v1/decide", content=b"{", headers={"content-type": "application/json"}).status_code == 400

    def test_another_model_is_refused_per_item(self, app):
        client, _ = app()
        body = {"state": "x", "questions": {"q": NOUL}, "model": V01.id}
        assert client.post("/v1/decide", json=body).json() == {"error": "wrong_model"}
        body["model"] = V02.id.upper()
        assert "answers" in client.post("/v1/decide", json=body).json()

    def test_an_item_the_backend_could_not_answer(self, app):
        client, _ = app(FakeBackend(outcomes=["loading"]))
        response = client.post("/v1/decide", json={"state": "x", "questions": {"q": NOUL}})
        assert response.status_code == 200 and response.json() == {"error": "loading"}

    def test_batch_keeps_order_and_isolates_items(self, app):
        client, backend = app(FakeBackend(outcomes=[Outcome(answer(0.1), 1, 0, False, 5), "timeout"]))
        good = {"state": "x", "questions": {"q": NOUL}}
        body = {"requests": [good, {"state": "y"}, good]}
        response = client.post("/v1/decide/batch", json=body)
        assert response.status_code == 200
        assert response.json()["responses"] == [
            {"model": V02.id, "answers": answer(0.1), "usage": {"input_tokens": 5, "output_tokens": 0}},
            {"error": "bad_item"},
            {"error": "timeout"},
        ]
        (requests, _, _), = backend.calls
        assert len(requests) == 2

    @pytest.mark.parametrize("body", [{}, {"requests": []}, {"requests": "x"}, [1]])
    def test_batch_without_requests_is_422(self, app, body):
        client, _ = app()
        assert client.post("/v1/decide/batch", json=body).status_code == 422

    def test_batch_over_the_limit_is_422(self, app, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_MAX_BATCH_STATES", 2)
        client, backend = app()
        good = {"state": "x", "questions": {"q": NOUL}}
        assert client.post("/v1/decide/batch", json={"requests": [good] * 3}).status_code == 422
        assert backend.calls == []


@pytest.mark.unit
class TestLanes:
    def test_the_priority_header_picks_the_lane(self, app):
        client, backend = app()
        body = {"state": "x", "questions": {"q": NOUL}}
        client.post("/v1/decide", json=body, headers={"X-Decision-Priority": "background"})
        client.post("/v1/decide", json=body, headers={"X-Decision-Priority": "hot"})
        client.post("/v1/decide", json=body, headers={"X-Decision-Priority": "anything"})
        client.post("/v1/decide", json=body)
        assert [lane for _, lane, _ in backend.calls] == ["background", "hot", "hot", "hot"]

    def test_the_deadline_header_is_time_left(self, app, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_HOT_TIMEOUT", 3.0)
        client, backend = app()
        body = {"state": "x", "questions": {"q": NOUL}}
        before = time.monotonic()
        client.post("/v1/decide", json=body, headers={"X-Decision-Deadline-Ms": "250"})
        client.post("/v1/decide", json=body)
        client.post("/v1/decide", json=body, headers={"X-Decision-Deadline-Ms": "soon"})
        after = time.monotonic()
        short, default, unreadable = (deadline for _, _, deadline in backend.calls)
        assert before + 0.25 <= short <= after + 0.25
        assert before + 3.0 <= default <= after + 3.0 and before + 3.0 <= unreadable <= after + 3.0

    def test_a_late_state_is_a_timeout_item(self, keyless):
        backend = OnnxBackend(V02, open_engine=lambda b: FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json")))
        backend.warm()
        end = time.monotonic() + 5
        while backend.status == "loading" and time.monotonic() < end:
            time.sleep(0.005)
        client = TestClient(server.create_app(server.DecideService(backend)))
        good = {"state": "x", "questions": {"q": NOUL}}
        response = client.post("/v1/decide/batch", json={"requests": [good, good]},
                               headers={"X-Decision-Deadline-Ms": "0"})
        assert response.json()["responses"] == [{"error": "timeout"}, {"error": "timeout"}]

    def test_a_full_lane_is_429_with_retry_after(self, app):
        client, _ = app(FakeBackend(outcomes=["queue_full"]))
        response = client.post("/v1/decide", json={"state": "x", "questions": {"q": NOUL}})
        assert response.status_code == 429 and response.headers["retry-after"] == "1"
        good = {"state": "x", "questions": {"q": NOUL}}
        assert client.post("/v1/decide/batch", json={"requests": [good]}).status_code == 429

    def test_more_calls_than_the_lane_queue_get_429_without_a_thread(self, app, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_BACKGROUND_QUEUE", 1)
        client, backend = app()
        release, inside = threading.Event(), threading.Event()

        def blocking(requests, lane, deadline):
            inside.set()
            release.wait(5)
            return [Outcome(answer(), 1, 0, False, 1) for _ in requests]

        backend.run = blocking
        body = {"state": "x", "questions": {"q": NOUL}}
        headers = {"X-Decision-Priority": "background"}
        first = threading.Thread(target=lambda: client.post("/v1/decide", json=body, headers=headers))
        first.start()
        assert inside.wait(5)
        try:
            assert client.post("/v1/decide", json=body, headers=headers).status_code == 429
            assert client.post("/v1/decide", json=body).status_code == 200  # the hot lane is free
        finally:
            release.set()
            first.join(5)


@pytest.mark.unit
class TestWithTheClient:
    """The API-mode client (``backends.http.DecideBackend``) against this server, through the ASGI app."""

    @pytest.fixture
    def pair(self, api, spawned, keyless, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "DECISION_KEY", "shared-key")
        monkeypatch.setattr(files, "ensure_tokenizer", lambda spec: tmp_path / "tokenizer.json")
        monkeypatch.setattr("docsgpt.decisions.vendor.arc_decide_onnx._Tokenizer", lambda path: CharTokenizer())
        backend = FakeBackend()
        backend.status, backend.profile = "ready", SpeedProfile(0.01, 0.001, 0.0, overhead=60, threads=4)
        asgi = TestClient(server.create_app(server.DecideService(backend)))

        def forward(request: httpx2.Request) -> httpx2.Response:
            reply = asgi.request(request.method, request.url.path, content=request.content,
                                 headers=dict(request.headers))
            return httpx2.Response(reply.status_code, headers=dict(reply.headers), content=reply.content)

        client = DecideBackend(transport=httpx2.MockTransport(forward))
        yield client, backend
        client.close()
        tokens.reset()

    def test_identity_speed_and_answers(self, pair):
        client, backend = pair
        client._first_use()
        assert client.spec is V02 and client.runtime == "onnx-int8"
        assert client.profile.server.wire() == backend.profile.wire()
        assert backend.warmed == 1, "the first use asks the server to load"
        out = client.run([Request("x", {"relevant": Q.RELEVANT}), Request("y", {"relevant": Q.RELEVANT})],
                         "background", client._clock() + 5)
        assert all(isinstance(o, Outcome) for o in out)
        assert out[0].answers["relevant"]["type"] == "noul"
        (requests, lane, _), = backend.calls
        assert len(requests) == 2 and lane == "background"

    def test_server_side_item_errors_keep_their_reason(self, pair):
        client, backend = pair
        backend.outcomes = ["loading", "timeout"]
        out = client.run([Request("x", {"relevant": Q.RELEVANT}), Request("y", {"relevant": Q.RELEVANT})],
                         "hot", client._clock() + 5)
        assert out == ["loading", "timeout"]


@pytest.mark.unit
def test_the_server_imports_no_app_no_faiss_and_no_torch(tmp_path):
    """It runs beside faiss-free code only, and on the CPU it works with torch missing altogether."""
    code = (
        "import sys\n"
        "class NoTorch:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('torch', 'transformers'):\n"
        "            raise ImportError(name)\n"
        "sys.meta_path.insert(0, NoTorch())\n"
        "from docsgpt.decisions import server\n"
        "import docsgpt.decisions.backends.torch\n"
        "server.create_app(server.DecideService(server.build_backend('cpu')))\n"
        "print(sorted(m for m in ('torch', 'transformers', 'faiss', 'flask', 'docsgpt.app', 'onnxruntime')"
        " if m in sys.modules))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         env={**os.environ, "DOCSGPT_HOME": str(tmp_path), "DECISION_MODEL": ""})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"
