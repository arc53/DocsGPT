"""API mode with the ``decide`` protocol: wire shapes, batching, retries, the breaker, keys, lanes, identity and
the timing a server reports or this side measures. Every server is a ``MockTransport``; nothing leaves the test."""

import logging
import threading

import httpx2
import pytest

import docsgpt.decisions as decisions
from docsgpt.core.settings import settings
from docsgpt.decisions import Budget, Q, Request, files, tokens
from docsgpt.decisions.backends import Outcome, http
from docsgpt.decisions.backends.http import DecideBackend, RemoteProfile
from docsgpt.decisions.breaker import Breaker
from docsgpt.decisions.latency import GUARD, SpeedProfile
from docsgpt.decisions.models import V01, V02, version
from docsgpt.decisions.types import Shape

from .fakes import CharTokenizer, FakeClock, FakeDecideServer

NOUL = {"type": "noul", "instructions": "Is it?"}
CHOICE = {"type": "choice", "instructions": "Which?", "criteria": {"zeta": None, "alpha": None, "mid": None}}

#: ``/v1/models`` of DocsGPT's decide-server running v0.2, with its timing profile.
DOCSGPT_ENTRY = {
    "name": V02.id, "revision": V02.revision, "prompt_hash": "78cfb276f93a", "calibration": V02.calibration,
    "runtime": "onnx-int8", "max_state_tokens": 2048, "status": "ready",
    "speed": SpeedProfile(0.01, 0.001, 0.0, overhead=60, threads=4, measured_at=1_700_000_000.0).wire(),
}


def run(backend, requests, lane="hot", seconds=5.0):
    return backend.run(requests, lane, backend._clock() + seconds)


def p(outcome, key="q"):
    assert isinstance(outcome, Outcome), outcome
    return outcome.answers[key]["noul"]


@pytest.mark.unit
class TestWire:
    def test_a_single_state_goes_to_decide_after_one_probe(self, remote):
        server = FakeDecideServer()
        backend = remote(DecideBackend, server)
        (out,) = run(backend, [Request({"text": "hi"}, {"q": NOUL})])
        assert p(out) == pytest.approx(0.7)
        assert server.paths(models=True) == ["/v1/models", "/v1/decide"]
        assert server.log[1]["body"] == {"state": {"text": "hi"}, "questions": {"q": NOUL}}  # no model unless set

    def test_decision_model_is_sent_when_set(self, remote, api):
        api(DECISION_MODEL=V01.id)
        server = FakeDecideServer()
        run(remote(DecideBackend, server), [Request("s", {"q": NOUL})])
        assert server.log[1]["body"]["model"] == V01.id

    def test_batches_split_and_answers_keep_their_order(self, remote, api):
        api(DECISION_BATCH_SIZE=4)
        server = FakeDecideServer(score=lambda state, key: int(state) / 100)
        out = run(remote(DecideBackend, server), [Request(str(i), {"q": NOUL}) for i in range(10)])
        assert [p(o) for o in out] == pytest.approx([i / 100 for i in range(10)])
        sizes = sorted(len(e["body"]["requests"]) for e in server.log if e["path"] == "/v1/decide/batch")
        assert sizes == [2, 4, 4]

    def test_option_order_survives_the_payload_and_the_answer(self, remote):
        server = FakeDecideServer()
        server.script.append(httpx2.Response(200, json={"model": "x", "answers": {"route": {
            "type": "choice", "choice": "mid", "confidence": 0.1,
            "probabilities": {"mid": 0.5, "alpha": 0.3, "zeta": 0.2}}}}))
        (out,) = run(remote(DecideBackend, server), [Request("s", {"route": CHOICE})])
        assert list(server.log[1]["body"]["questions"]["route"]["criteria"]) == ["zeta", "alpha", "mid"]
        assert list(out.answers["route"]["probabilities"]) == ["zeta", "alpha", "mid"]
        assert out.answers["route"]["choice"] == "mid"

    def test_answers_are_rebuilt_in_the_local_shapes(self, remote):
        out, = run(remote(DecideBackend, FakeDecideServer()), [Request("s", {"grade": Q.GRADE})])
        grade = out.answers["grade"]
        assert grade["legend"] == {str(i): level for i, level in enumerate(Q.GRADE["criteria"])}
        assert grade["score"] == pytest.approx(sum(i * v for i, v in enumerate(grade["probabilities"].values())))

    @pytest.mark.parametrize("answer", [
        {"type": "score", "score": 1.0},
        {"type": "noul", "noul": 1.5},
        {"type": "noul", "noul": True},
        {"type": "choice", "choice": "other", "probabilities": {"zeta": 0.2, "alpha": 0.3, "mid": 0.5}},
        {"type": "choice", "choice": "mid", "probabilities": {"zeta": 0.9, "alpha": 0.3, "mid": 0.5}},
        {"type": "choice", "choice": "mid", "probabilities": {"zeta": 0.5, "mid": 0.5}},
    ])
    def test_an_answer_to_another_question_is_a_backend_error(self, remote, answer):
        server = FakeDecideServer()
        key = "route" if answer["type"] == "choice" else "q"
        server.script.append(httpx2.Response(200, json={"model": "x", "answers": {key: answer}}))
        backend = remote(DecideBackend, server)
        assert run(backend, [Request("s", {key: CHOICE if key == "route" else NOUL})]) == ["backend_error"]
        assert not backend._breaker.open

    def test_item_errors_from_the_server(self, remote):
        server = FakeDecideServer()
        server.script.append(lambda body: httpx2.Response(200, json={"responses": [
            {"error": "timeout"}, {"error": "loading"}, {"error": "melted"}, {"error": "bad_item"},
            server.decide(body["requests"][4])]}))
        out = run(remote(DecideBackend, server), [Request(str(i), {"q": NOUL}) for i in range(5)])
        assert out[:4] == ["timeout", "loading", "backend_error", "bad_item"] and p(out[4]) == pytest.approx(0.7)

    def test_a_state_that_does_not_render_is_a_bad_item_and_not_sent(self, remote):
        server = FakeDecideServer()
        out = run(remote(DecideBackend, server), [Request({"x": object()}, {"q": NOUL}), Request("ok", {"q": NOUL})])
        assert out[0] == "bad_item" and p(out[1]) == pytest.approx(0.7)
        assert server.paths() == ["/v1/decide"]


@pytest.mark.unit
class TestFailures:
    def test_a_503_is_retried_once(self, remote):
        server = FakeDecideServer()
        server.script.append(httpx2.Response(503))
        (out,) = run(remote(DecideBackend, server), [Request("s", {"q": NOUL})])
        assert p(out) == pytest.approx(0.7) and server.paths() == ["/v1/decide", "/v1/decide"]

    def test_a_connection_error_is_retried_once_then_fails(self, remote):
        server = FakeDecideServer()
        server.script.extend([httpx2.ConnectError("refused")] * 2)
        backend = remote(DecideBackend, server)
        assert run(backend, [Request("s", {"q": NOUL})]) == ["transport"]
        assert server.paths() == ["/v1/decide", "/v1/decide"]

    def test_no_retry_without_30_percent_of_the_budget_left(self, remote):
        clock = FakeClock()
        server = FakeDecideServer()

        def slow_503(body):
            clock.advance(0.75)
            return httpx2.Response(503)

        server.script.append(slow_503)
        backend = remote(DecideBackend, server, clock=clock)
        assert run(backend, [Request("s", {"q": NOUL})], seconds=1.0) == ["transport"]
        assert server.paths() == ["/v1/decide"]

    def test_retries_are_off_with_zero(self, remote, api):
        api(DECISION_API_RETRIES=0)
        server = FakeDecideServer()
        server.script.append(httpx2.Response(502))
        assert run(remote(DecideBackend, server), [Request("s", {"q": NOUL})]) == ["transport"]
        assert server.paths() == ["/v1/decide"]

    def test_a_timeout_is_not_retried(self, remote):
        server = FakeDecideServer()
        server.script.append(httpx2.ReadTimeout("slow"))
        assert run(remote(DecideBackend, server), [Request("s", {"q": NOUL})]) == ["timeout"]
        assert server.paths() == ["/v1/decide"]

    def test_a_rejected_batch_is_sent_again_item_by_item(self, remote):
        server = FakeDecideServer()
        bad = httpx2.Response(422, json={"detail": "bad"})
        server.script.extend([bad, None, bad, None])  # the batch; then items 0, 1 (refused), 2
        out = run(remote(DecideBackend, server), [Request(str(i), {"q": NOUL}) for i in range(3)])
        assert p(out[0]) == pytest.approx(0.7) and out[1] == "backend_error" and p(out[2]) == pytest.approx(0.7)
        assert server.paths() == ["/v1/decide/batch", "/v1/decide", "/v1/decide", "/v1/decide"]

    def test_a_4xx_is_not_retried_and_does_not_count_against_the_server(self, remote):
        server = FakeDecideServer()
        server.script.extend([httpx2.Response(400)] * 3)
        backend = remote(DecideBackend, server)
        for _ in range(3):
            assert run(backend, [Request("s", {"q": NOUL})]) == ["backend_error"]
        assert server.paths() == ["/v1/decide"] * 3 and not backend._breaker.open

    def test_a_full_queue_answers_queue_full(self, remote):
        server = FakeDecideServer()
        server.script.append(httpx2.Response(429, headers={"Retry-After": "1"}))
        backend = remote(DecideBackend, server)
        assert run(backend, [Request("s", {"q": NOUL})]) == ["queue_full"]
        assert server.paths() == ["/v1/decide"] and not backend._breaker.open

    @pytest.mark.parametrize("response", [
        httpx2.Response(200, text="not json"),
        httpx2.Response(200, json={"responses": [{}]}),
        httpx2.Response(404),
    ])
    def test_a_reply_outside_the_contract_is_a_transport_failure(self, remote, response):
        server = FakeDecideServer()
        server.script.append(response)
        backend = remote(DecideBackend, server)
        assert run(backend, [Request("a", {"q": NOUL}), Request("b", {"q": NOUL})]) == ["transport"] * 2
        assert backend._breaker._count == 1

    def test_an_unreachable_server_fails_the_first_calls_then_opens_the_breaker(self, remote):
        class Down(FakeDecideServer):
            def route(self, path, body):
                raise httpx2.ConnectError("refused")

        server = Down()
        backend = remote(DecideBackend, server)
        assert [run(backend, [Request("s", {"q": NOUL})]) for _ in range(4)] == [["transport"]] * 3 + [["circuit_open"]]
        assert server.paths(models=True) == ["/v1/models"] * 6  # three probes, each retried once
        assert backend.model_info("api").id == V01.id  # still the assumed model

    def test_an_unexpected_error_fails_its_items_not_the_caller(self, remote):
        server = FakeDecideServer()

        def broken(body):
            raise RuntimeError("bug")

        server.script.append(broken)
        out = run(remote(DecideBackend, server), [Request("a", {"q": NOUL})])
        assert out == ["transport"]

    def test_the_deadline_bounds_a_part_still_in_flight(self, remote):
        server = FakeDecideServer()
        release = threading.Event()
        server.gate["hot"] = release
        backend = remote(DecideBackend, server)
        backend._probe()
        try:
            assert run(backend, [Request("s", {"q": NOUL})], seconds=0.05) == ["timeout"]
        finally:
            release.set()


@pytest.mark.unit
class TestBreaker:
    def test_closed_open_half_open(self):
        clock = FakeClock()
        breaker = Breaker(2, 30.0, clock)
        assert breaker.allow() and not breaker.failure() and breaker.allow()
        assert breaker.failure() and breaker.open and not breaker.allow()
        clock.advance(30)
        assert breaker.allow()  # the one trial
        assert not breaker.allow()  # everyone else waits for it
        assert breaker.failure() and not breaker.allow()  # a failed trial opens it again
        clock.advance(30)
        assert breaker.allow() and breaker.success() and not breaker.open
        assert breaker.allow() and breaker.allow()

    def test_a_trial_that_never_reports_frees_the_slot_after_a_cooldown(self):
        clock = FakeClock()
        breaker = Breaker(1, 10.0, clock)
        breaker.failure()
        clock.advance(10)
        assert breaker.allow() and not breaker.allow()
        clock.advance(10)
        assert breaker.allow()

    def test_three_transport_failures_skip_calls_for_the_cooldown(self, remote, spawned):
        clock = FakeClock()
        server = FakeDecideServer()
        backend = remote(DecideBackend, server, clock=clock)
        backend._probe()
        server.script.extend([httpx2.ConnectError("down")] * 6)
        for _ in range(3):
            assert run(backend, [Request("s", {"q": NOUL})]) == ["transport"]
        sent = len(server.log)
        assert run(backend, [Request("s", {"q": NOUL})]) == ["circuit_open"]
        assert len(server.log) == sent
        assert (backend.status, backend.reason) == ("degraded", "circuit_open")
        clock.advance(30)
        server.script.clear()
        assert p(run(backend, [Request("s", {"q": NOUL})])[0]) == pytest.approx(0.7)
        assert backend.status == "ready"
        assert [name for name, _ in spawned].count("decision-api-timing") == 1  # timed again once it closed

    def test_bad_items_do_not_count(self, remote):
        server = FakeDecideServer()
        server.script.extend([httpx2.Response(200, json={"answers": {}})] * 5)
        backend = remote(DecideBackend, server)
        for _ in range(5):
            assert run(backend, [Request("s", {"q": NOUL})]) == ["backend_error"]
        assert not backend._breaker.open


@pytest.mark.unit
class TestHeaders:
    def test_decision_key_goes_on_every_request(self, remote, api):
        api(DECISION_KEY="decider-key")
        server = FakeDecideServer(DOCSGPT_ENTRY)
        backend = remote(DecideBackend, server)
        backend._probe()
        backend._load()
        run(backend, [Request("s", {"q": NOUL})])
        assert server.paths(models=True) == ["/v1/models", "/v1/load", "/v1/decide"]
        assert {e["headers"]["authorization"] for e in server.log} == {"Bearer decider-key"}

    def test_internal_key_is_never_sent(self, remote):
        server = FakeDecideServer(DOCSGPT_ENTRY)
        backend = remote(DecideBackend, server)
        backend._probe()
        backend._load()
        run(backend, [Request("s", {"q": NOUL})])
        assert settings.INTERNAL_KEY == "internal-key" and len(server.log) == 3
        assert not any("authorization" in e["headers"] for e in server.log)
        assert not any("internal-key" in str(dict(e["headers"])) for e in server.log)

    @pytest.mark.parametrize("url, warned", [
        ("http://decider:7095", False), ("http://localhost:7095", False), ("http://127.0.0.1:7095", False),
        ("http://[::1]:7095", False), ("http://10.0.3.7:7095", False), ("http://192.168.1.20", False),
        ("https://decide.example.com", False), ("http://decide.example.com", True), ("http://8.8.8.8", True),
    ])
    def test_cleartext_to_a_public_host_is_flagged(self, url, warned):
        from docsgpt.decisions.backends.http import cleartext_public

        assert cleartext_public(url) is warned

    @pytest.mark.parametrize("url, bare, credentials", [
        ("http://decider:7095", "http://decider:7095", None),
        ("http://u:p%40ss@decide.example.com:8443/v1", "http://decide.example.com:8443/v1", ("u", "p@ss")),
        ("https://u@[::1]:7095", "https://[::1]:7095", ("u", "")),
    ])
    def test_credentials_leave_the_url(self, url, bare, credentials):
        from docsgpt.decisions.backends.http import without_userinfo

        assert without_userinfo(url) == (bare, credentials)

    def test_url_credentials_go_as_basic_auth_never_in_the_url(self, remote, api):
        api(DECISION_BASE_URL="http://user:secret@decider:7095")
        server = FakeDecideServer(DOCSGPT_ENTRY)
        backend = remote(DecideBackend, server)
        backend._probe()
        assert backend.base_url == "http://decider:7095"
        assert server.log[0]["headers"]["authorization"].startswith("Basic ")

    def test_a_key_over_plain_http_to_a_public_host_warns_once(self, remote, api, caplog):
        api(DECISION_KEY="decider-key", DECISION_BASE_URL="http://user:secret@decide.example.com")
        server = FakeDecideServer(DOCSGPT_ENTRY)
        backend = remote(DecideBackend, server)
        with caplog.at_level(logging.WARNING, logger="docsgpt.decisions.backends.http"):
            backend._probe()
            run(backend, [Request("s", {"q": NOUL})])
        (record,) = [r for r in caplog.records if "plain HTTP" in r.message]
        assert record.args == ("decide.example.com",) and "secret" not in record.getMessage()

    def test_deadline_and_priority(self, remote):
        server = FakeDecideServer()
        run(remote(DecideBackend, server), [Request("s", {"q": NOUL})], lane="background", seconds=2.0)
        headers = server.log[-1]["headers"]
        assert headers["x-decision-priority"] == "background"
        assert 0 < int(headers["x-decision-deadline-ms"]) <= 2000
        assert "x-decision-priority" not in server.log[0]["headers"]  # the probe carries neither

    def test_a_401_is_logged_once_and_refuses_until_a_probe_is_let_in(self, remote, caplog):
        clock = FakeClock()
        server = FakeDecideServer()
        backend = remote(DecideBackend, server, clock=clock)
        backend._probe()
        server.script.extend([httpx2.Response(401)] * 2)
        with caplog.at_level(logging.WARNING, logger="docsgpt.decisions.backends.http"):
            assert run(backend, [Request("s", {"q": NOUL})]) == ["auth"]
            sent = len(server.log)
            assert run(backend, [Request("s", {"q": NOUL})]) == ["auth"]
        assert len(server.log) == sent  # refused without sending
        (said,) = [r.message for r in caplog.records if "refused this process's key" in r.message]
        assert "DECISION_KEY" in said and "INTERNAL_KEY" not in said
        assert (backend.status, backend.reason) == ("unavailable", "auth")
        assert not backend._breaker.open
        clock.advance(30)
        server.script.clear()
        backend._probe()
        assert backend.status == "ready" and p(run(backend, [Request("s", {"q": NOUL})])[0]) == pytest.approx(0.7)


@pytest.mark.unit
class TestLanes:
    def test_background_work_never_takes_a_hot_slot(self, remote):
        server = FakeDecideServer()
        release = threading.Event()
        server.gate["background"] = release
        backend = remote(DecideBackend, server)
        backend._probe()
        result = {}
        sweep = threading.Thread(target=lambda: result.update(out=run(
            backend, [Request(str(i), {"q": NOUL}) for i in range(3)], lane="background")))
        sweep.start()
        try:
            (hot,) = run(backend, [Request("now", {"q": NOUL})], seconds=2.0)
            assert p(hot) == pytest.approx(0.7) and sweep.is_alive()
        finally:
            release.set()
            sweep.join(5)
        assert [p(o) for o in result["out"]] == pytest.approx([0.7] * 3)

    def test_the_client_and_pools_are_built_again_after_a_fork(self, remote, monkeypatch):
        backend = remote(DecideBackend, FakeDecideServer())
        backend._probe()
        client, pools = backend._client, backend._pools
        monkeypatch.setattr("docsgpt.decisions.backends.http.os.getpid", lambda: -1)
        backend._ensure_process()
        assert backend._client is not client and backend._pools["hot"] is not pools["hot"]


@pytest.mark.unit
class TestIdentity:
    def test_arcd_serve_is_taken_as_the_registry_model(self, remote, caplog):
        with caplog.at_level(logging.INFO, logger="docsgpt.decisions.backends.http"):
            backend = remote(DecideBackend, FakeDecideServer())
            backend._probe()
            backend._probe()
        info = backend.model_info("api")
        assert (info.id, info.runtime, info.mode, info.version) == (V01.id, "remote", "api", version(V01))
        assert sum("does not report its model" in r.message for r in caplog.records) == 1

    def test_docsgpt_server_reports_its_model(self, remote):
        backend = remote(DecideBackend, FakeDecideServer(DOCSGPT_ENTRY))
        backend._probe()
        info = backend.model_info("api")
        assert (info.id, info.revision, info.runtime) == (V02.id, V02.revision, "onnx-int8")
        assert info.version == "arc53/arc-decide-0.4b-v0.2/p78cfb276f93a/cc3bc72ff6907"

    def test_a_new_calibration_changes_the_version(self, remote):
        backend = remote(DecideBackend, FakeDecideServer({**DOCSGPT_ENTRY, "calibration": "abc123abc123"}))
        backend._probe()
        assert backend.model_info("api").version == "arc53/arc-decide-0.4b-v0.2/p78cfb276f93a/cabc123abc123"

    @pytest.mark.parametrize("entry, wanted", [
        ({**DOCSGPT_ENTRY, "prompt_hash": "000000000000"}, None),
        ({**DOCSGPT_ENTRY, "name": "someone/else"}, None),
        (DOCSGPT_ENTRY, V01.id),
    ])
    def test_a_model_this_client_cannot_use_is_refused(self, remote, api, entry, wanted):
        api(DECISION_MODEL=wanted)
        server = FakeDecideServer(entry)
        backend = remote(DecideBackend, server)
        assert run(backend, [Request("s", {"q": NOUL})]) == ["wrong_model"]
        assert server.paths() == [] and (backend.status, backend.reason) == ("unavailable", "wrong_model")

    def test_the_servers_own_status_shows(self, remote):
        backend = remote(DecideBackend, FakeDecideServer({**DOCSGPT_ENTRY, "status": "loading", "speed": None}))
        assert backend.status == "idle"
        backend._probe()
        assert backend.status == "loading"

    def test_probes_repeat_every_probe_seconds(self, remote, spawned):
        clock = FakeClock()
        backend = remote(DecideBackend, FakeDecideServer(), clock=clock)
        run(backend, [Request("s", {"q": NOUL})])
        clock.advance(29)
        run(backend, [Request("s", {"q": NOUL})])
        assert "decision-api-probe" not in [name for name, _ in spawned]
        clock.advance(1)
        run(backend, [Request("s", {"q": NOUL})])
        run(backend, [Request("s", {"q": NOUL})])
        assert [name for name, _ in spawned].count("decision-api-probe") == 1


@pytest.fixture
def char_tokenizer(monkeypatch, tmp_path):
    """The tokenizer API mode fetches, as one token per character."""
    monkeypatch.setattr(files, "ensure_tokenizer", lambda spec: tmp_path / "tokenizer.json")
    monkeypatch.setattr("docsgpt.decisions.vendor.arc_decide_onnx._Tokenizer", lambda path: CharTokenizer())
    yield
    tokens.reset()


@pytest.mark.unit
class TestFirstUse:
    def test_docsgpt_server_loads_and_reports_its_speed(self, remote, spawned, char_tokenizer):
        server = FakeDecideServer(DOCSGPT_ENTRY)
        backend = remote(DecideBackend, server)
        backend.warm()
        backend.warm()
        assert [name for name, _ in spawned] == ["decision-api-start"]
        spawned[0][1]()
        assert server.paths(models=True) == ["/v1/models", "/v1/load"]  # timed by the server, not through it
        assert backend.profile.server is not None and backend.profile.report()["measured_by"] == "server"
        assert tokens.count_tokens("abc") == 3

    def test_a_cold_server_is_followed_until_it_is_ready(self, remote, spawned, char_tokenizer, monkeypatch):
        monkeypatch.setattr(http, "LOAD_POLL_S", (0.0,))
        server = FakeDecideServer({**DOCSGPT_ENTRY, "status": "idle", "speed": None})
        states = iter([("idle", None), ("loading", None), ("ready", DOCSGPT_ENTRY["speed"])])

        def models(path, body, route=server.route):
            if path == "/v1/models":
                server.entry["status"], server.entry["speed"] = next(states, ("ready", DOCSGPT_ENTRY["speed"]))
            return route(path, body)

        server.route = models
        backend = remote(DecideBackend, server)
        backend.warm()
        spawned[0][1]()
        assert server.paths(models=True) == ["/v1/models", "/v1/load", "/v1/models", "/v1/models"]
        assert backend.status == "ready" and backend.profile.report()["measured_by"] == "server"

    def test_following_stops_when_the_server_gives_up_or_goes_away(self, remote, spawned, monkeypatch):
        monkeypatch.setattr(http, "LOAD_POLL_S", (0.0,))
        released = FakeDecideServer({**DOCSGPT_ENTRY, "status": "idle", "reason": "nothing_fits", "speed": None})
        backend = remote(DecideBackend, released)
        backend._probe()
        backend._follow_load()
        assert released.paths(models=True) == ["/v1/models"]
        gone = FakeDecideServer({**DOCSGPT_ENTRY, "status": "loading", "speed": None})
        backend = remote(DecideBackend, gone)
        backend._probe()
        gone.route = lambda path, body: httpx2.Response(500)
        backend._follow_load()
        assert gone.paths(models=True).count("/v1/models") == 2 and backend.status == "loading"

    def test_warm_follows_a_server_still_loading_after_the_retry_window(self, remote, spawned, api):
        api(DECISION_LOAD_RETRY_SECONDS=60)
        clock = FakeClock()
        backend = remote(DecideBackend, FakeDecideServer({**DOCSGPT_ENTRY, "status": "loading", "speed": None}),
                         clock=clock)
        backend.warm()
        backend._probe()
        backend.warm()
        clock.advance(60)
        backend.warm()
        assert [name for name, _ in spawned] == ["decision-api-start", "decision-api-load"]

    def test_a_server_down_at_first_use_is_probed_and_asked_to_load_again(
            self, remote, spawned, char_tokenizer, monkeypatch, api):
        api(DECISION_PROBE_SECONDS=30)
        monkeypatch.setattr(http, "LOAD_POLL_S", (0.0,))
        clock = FakeClock()
        server = FakeDecideServer({**DOCSGPT_ENTRY, "status": "idle", "speed": None})
        backend = remote(DecideBackend, server, clock=clock)
        server.route = lambda path, body, route=server.route: (httpx2.Response(503) if path == "/v1/models"
                                                               else route(path, body))
        backend.warm()
        spawned[0][1]()  # the server is not up yet: no answer, so no load request
        backend.warm()
        assert len(spawned) == 1 and "/v1/load" not in server.paths()
        del server.route
        states = iter([("idle", None)])

        def models(path, body, route=server.route):
            if path == "/v1/models":
                server.entry["status"], server.entry["speed"] = next(states, ("ready", DOCSGPT_ENTRY["speed"]))
            return route(path, body)

        server.route = models
        clock.advance(30)
        backend.warm()  # an auto feature asking again: the whole first use runs again
        assert [name for name, _ in spawned] == ["decision-api-start", "decision-api-start"]
        spawned[1][1]()
        assert "/v1/load" in server.paths() and backend.status == "ready"

    def test_following_an_idle_server_asks_it_to_load(self, remote, spawned, api, monkeypatch):
        api(DECISION_LOAD_RETRY_SECONDS=60)
        monkeypatch.setattr(http, "LOAD_POLL_S", (0.0,))
        clock = FakeClock()
        server = FakeDecideServer({**DOCSGPT_ENTRY, "status": "idle", "speed": None})
        backend = remote(DecideBackend, server, clock=clock)
        backend.warm()
        backend._probe()  # answered (say by a call), idle, and never asked to load
        clock.advance(60)
        backend.warm()
        assert [name for name, _ in spawned] == ["decision-api-start", "decision-api-load"]
        server.entry["status"] = "ready"
        spawned[1][1]()
        assert server.paths() == ["/v1/load"]

    def test_arcd_serve_is_timed_through_the_endpoint(self, remote, spawned, char_tokenizer):
        server = FakeDecideServer()
        backend = remote(DecideBackend, server)
        backend.warm()
        spawned[0][1]()
        assert server.paths(models=True) == ["/v1/models"] + ["/v1/decide"] * 4  # no load route asked
        report = backend.profile.report()
        assert report["measured_by"] == "client" and report["threads"] is None
        assert backend.profile.c >= 0 and backend.profile.a >= 0 and backend.profile.overhead > 0
        bodies = [e["body"] for e in server.log if e["path"] == "/v1/decide"]
        assert len(bodies[0]["state"]) < len(bodies[3]["state"]) and set(bodies[3]["questions"]) == {
            "relevant", "relevant:again"}

    def test_a_failed_timing_leaves_auto_unmeasured(self, remote, spawned, char_tokenizer):
        server = FakeDecideServer()
        backend = remote(DecideBackend, server)
        backend._probe()
        backend._load_tokenizer()
        server.script.append(httpx2.Response(422))
        backend._time()
        assert backend.profile is None

    def test_a_server_not_up_at_first_use_is_timed_once_a_probe_answers(self, remote, spawned, char_tokenizer):
        server = FakeDecideServer()
        backend = remote(DecideBackend, server)
        server.route = lambda path, body, route=server.route: (httpx2.Response(503) if path == "/v1/models"
                                                               else route(path, body))
        backend.warm()
        spawned[0][1]()  # first use: the probe fails, so nothing is timed
        assert backend.profile is None and backend._timed_at is None
        del server.route
        backend._probe()
        backend.warm()
        assert [name for name, _ in spawned] == ["decision-api-start", "decision-api-timing"]
        spawned[1][1]()
        assert backend.profile is not None and backend.profile.report()["measured_by"] == "client"

    def test_a_failed_tokenizer_is_fetched_again_after_the_retry_window(self, remote, spawned, monkeypatch):
        clock = FakeClock()
        backend = remote(DecideBackend, FakeDecideServer(), clock=clock)

        def offline(spec):
            raise files.FilesUnavailable("offline", "HF_HUB_OFFLINE is set")

        monkeypatch.setattr(files, "ensure_tokenizer", offline)
        backend.warm()
        backend._load_tokenizer()
        assert backend._tokenizer_failed[0] == "offline" and backend.status == "idle"  # decide needs no tokenizer
        backend.warm()
        clock.advance(300)
        backend.warm()
        assert [name for name, _ in spawned] == ["decision-api-start", "decision-tokenizer"]

    def test_counts_and_truncation_come_from_this_side(self, remote, char_tokenizer):
        backend = remote(DecideBackend, FakeDecideServer())
        (before,) = run(backend, [Request("x" * 3000, {"q": NOUL})])
        assert (before.truncated, before.input_tokens) == (False, 7)  # the server's count until the tokenizer loads
        backend._load_tokenizer()
        (after,) = run(backend, [Request("x" * 3000, {"q": NOUL})])
        prefix, (suffix,), _ = backend.encode(Request("x" * 3000, {"q": NOUL}))
        assert "x" * 2048 + " ...[truncated]" in tokens.decode(prefix) and "x" * 2049 not in tokens.decode(prefix)
        assert after.truncated and after.input_tokens == len(prefix) + len(suffix)


@pytest.mark.unit
class TestProfile:
    def test_a_server_profile_adds_the_round_trip_per_round_of_requests(self):
        server = SpeedProfile(0.01, 0.001, 0.0, overhead=60, threads=4)
        profile = RemoteProfile(round_trip=0.02, batch_size=32, concurrency={"hot": 4, "background": 1},
                                server=server)
        assert profile.predict_s(GUARD) == pytest.approx(server.predict_s(GUARD) + 0.02)
        many = Shape(state_tokens=100, question_tokens=(10,), states=200)
        assert profile.rounds(many) == 2  # 7 batches of 32, 4 at a time
        assert profile.predict_s(many) == pytest.approx(server.predict_s(many) + 0.04)

    def test_a_measured_profile_charges_per_round_and_per_token(self):
        profile = RemoteProfile(round_trip=0.0, batch_size=32, concurrency={"hot": 4, "background": 1},
                                per_question=True, c=0.01, a=0.0001, overhead=50)
        shape = Shape(state_tokens=100, question_tokens=(10,) * 8, lane="background")
        assert profile.rounds(shape) == 8
        assert profile.predict_s(shape) == pytest.approx(8 * 0.01 + 0.0001 * (100 + 50 + 80))


@pytest.mark.unit
class TestClient:
    def test_a_base_url_turns_on_api_mode(self, api):
        assert decisions.get_decider().mode == "api"
        api(DECISION_MODE="local")
        assert decisions.get_decider().mode == "local"

    def test_status_needs_no_network(self, api):
        status = decisions.status()
        assert status["mode"] == "api" and status["status"] == "idle" and status["runtime"] == "remote"
        assert status["model"] == V01.id and decisions.get_decider()._backend is None

    def test_vllm_identity_without_a_backend(self, api):
        api(DECISION_PROTOCOL="vllm")
        info = decisions.model_info()
        assert (info.id, info.runtime, info.mode) == (V01.id, "vllm", "api")

    def test_api_mode_without_a_url_has_no_decider(self, api):
        api(DECISION_MODE="api", DECISION_BASE_URL=None)
        assert decisions.decide_batch([Request("s", {"q": NOUL})], feature="test").reasons == ["no_decider"]
        assert (decisions.status()["status"], decisions.status()["reason"]) == ("unavailable", "no_decider")

    def test_a_worker_calls_the_server(self, api, remote, monkeypatch):
        monkeypatch.setattr("docsgpt.celery_init.in_worker", lambda: True)
        server = FakeDecideServer(DOCSGPT_ENTRY)
        client = decisions.get_decider()
        client._backend = remote(DecideBackend, server)
        res = decisions.decide("s", {"q": NOUL}, feature="test", budget=Budget.hot(2.0))
        assert res.p("q") == pytest.approx(0.7)
        assert (res.model.id, res.model.mode, res.model.runtime) == (V02.id, "api", "onnx-int8")
        assert decisions.status()["speed"]["measured_by"] == "server"

    def test_answers_are_cached_under_the_identity_the_server_reported(self, api, remote):
        api(DECISION_CACHE_SIZE=64)
        server = FakeDecideServer(DOCSGPT_ENTRY)
        client = decisions.get_decider()
        client._backend = remote(DecideBackend, server)
        assert decisions.model_info().id == V01.id  # assumed until the first probe, which the call makes
        first = decisions.decide("s", {"q": NOUL}, feature="test", budget=Budget.hot(2.0))
        again = decisions.decide("s", {"q": NOUL}, feature="test", budget=Budget.hot(2.0))
        assert first.model.id == V02.id and not first.cached
        assert again.cached and again.model.version == first.model.version
        assert server.paths().count("/v1/decide") == 1

    def test_breaker_open_makes_the_batch_unavailable(self, api, remote):
        api(DECISION_BREAKER_FAILURES=1)
        server = FakeDecideServer()
        client = decisions.get_decider()
        client._backend = remote(DecideBackend, server)
        server.script.extend([httpx2.ConnectError("down")] * 2)
        assert decisions.decide_batch([Request("s", {"q": NOUL})], feature="test").reasons == ["transport"]
        batch = decisions.decide_batch([Request("s", {"q": NOUL})] * 2, feature="test")
        assert batch.status == "unavailable" and batch.reasons == ["circuit_open"] * 2
        assert decisions.status()["status"] == "degraded"

    def test_nothing_is_sent_while_every_feature_is_off(self, api, spawned):
        decisions.start()
        assert decisions.get_decider()._backend is None and spawned == []


@pytest.mark.unit
class TestTokenizerFiles:
    @pytest.fixture
    def cache(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "DECISION_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(settings, "DECISION_MODEL_PATH", None)
        monkeypatch.setattr(settings, "DECISION_MODEL_REVISION", None)
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        return tmp_path

    def test_only_the_tokenizer_is_fetched_at_the_pin(self, cache, monkeypatch):
        calls = []

        def fake_download(**kwargs):
            calls.append(kwargs)
            (kwargs["local_dir"] / "onnx").mkdir(parents=True)
            (kwargs["local_dir"] / "onnx" / "tokenizer.json").write_text("{}")

        monkeypatch.setattr("huggingface_hub.snapshot_download", fake_download)
        path = files.ensure_tokenizer(V01)
        assert path == cache / V01.id / f"{V01.revision}.tokenizer" / "onnx" / "tokenizer.json" and path.is_file()
        assert calls == [{"repo_id": V01.id, "revision": V01.revision, "allow_patterns": ["onnx/tokenizer.json"],
                          "local_dir": path.parent.parent.with_name(path.parent.parent.name + ".partial")}]
        assert files.local_onnx_dir(V01) is None  # a tokenizer alone never looks like the model
        assert files.ensure_tokenizer(V01) == path and len(calls) == 1

    def test_another_models_download_is_reused(self, cache, monkeypatch):
        shared = cache / V02.id / V02.revision / "onnx"
        shared.mkdir(parents=True)
        (shared / "tokenizer.json").write_text("{}")
        monkeypatch.setattr("huggingface_hub.snapshot_download", lambda **kwargs: pytest.fail("downloaded"))
        assert files.ensure_tokenizer(V01) == shared / "tokenizer.json"

    def test_offline_without_the_file(self, cache, monkeypatch):
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        with pytest.raises(files.FilesUnavailable) as exc:
            files.ensure_tokenizer(V01)
        assert exc.value.reason == "offline"

    def test_a_failed_download(self, cache, monkeypatch):
        def broken(**kwargs):
            raise OSError("no route")

        monkeypatch.setattr("huggingface_hub.snapshot_download", broken)
        with pytest.raises(files.FilesUnavailable) as exc:
            files.ensure_tokenizer(V01)
        assert exc.value.reason == "download"

    def test_model_path(self, cache, monkeypatch):
        (cache / "copy").mkdir()
        (cache / "copy" / "tokenizer.json").write_text("{}")
        monkeypatch.setattr(settings, "DECISION_MODEL_PATH", str(cache / "copy"))
        assert files.ensure_tokenizer(V01) == cache / "copy" / "tokenizer.json"
