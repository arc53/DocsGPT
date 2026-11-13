"""The drafter routes: session-only access, config, refusals, and the SSE turn end to end with a fake model."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.drafter.fencing import DATA_GUARD
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.core.settings import settings
from tests.activity.conftest import FakeRedis
from tests.drafter.fakes import calls, FakeLLM, PROPOSAL, QUESTIONS, text as plain, tool_call

MODEL = {"id": "task-model", "display_name": "Task Model", "supports_tools": True}


@pytest.fixture(scope="module")
def flask_app():
    from docsgpt.app import app

    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@contextmanager
def _session(user="alice"):
    with patch("docsgpt.app.handle_auth", return_value={"sub": user}), patch(
        "docsgpt.app.resolve_roles", return_value=["user"]
    ):
        yield


def _pat_claims():
    from docsgpt.api.pat.tokens import expand_scopes, SCOPES

    return {
        "sub": "alice", "auth_method": "pat", "pat_id": "t1", "pat_name": "ci",
        "scopes": sorted(expand_scopes(list(SCOPES))), "resource_filter": {},
    }


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.storage.db.session.db_readonly", _yield):
        yield


def _events(response) -> list[dict]:
    body = response.get_data(as_text=True)
    return [json.loads(chunk[len("data: "):]) for chunk in body.split("\n\n") if chunk.startswith("data: ")]


def _body(*messages, recipe="agent", form=None):
    if not messages:
        messages = ({"role": "user", "content": "A shipping help agent for our website."},)
    return {"recipe": recipe, "messages": list(messages), "context": {"agent_id": None, "form": form or {}}}


def _stream(client, body, fake=None, model=MODEL, user="alice"):
    with _session(user), patch("docsgpt.drafter.service.drafter_model", return_value=model), patch(
        "docsgpt.drafter.runner.build_llm", fake.factory if fake else None
    ):
        # Buffered: the stream runs on a pump thread, so the patches must outlive the whole turn.
        return client.post("/api/drafter/stream", json=body, buffered=True)


def _types(events):
    return [e["type"] if e["type"] != "status" else f"status:{e['step']}" for e in events]


_ROUTES = [("GET", "/api/drafter/config"), ("POST", "/api/drafter/stream"),
           ("POST", f"/api/drafter/turns/{'a' * 32}/cancel")]


@pytest.mark.unit
class TestAccess:
    @pytest.mark.parametrize("method,path", _ROUTES)
    def test_an_access_token_is_refused(self, client, method, path):
        with patch("docsgpt.app.handle_auth", return_value=_pat_claims()):
            response = client.open(path, method=method, json=_body())
        assert response.status_code == 403

    @pytest.mark.parametrize("method,path", _ROUTES)
    def test_no_session_is_401(self, client, method, path):
        with patch("docsgpt.app.handle_auth", return_value=None):
            response = client.open(path, method=method, json=_body())
        assert response.status_code == 401


@pytest.mark.unit
class TestConfig:
    def test_enabled_reports_the_task_model(self, client):
        model = SimpleNamespace(display_name="Claude Haiku", enabled=True,
                                capabilities=SimpleNamespace(supports_tools=True))
        registry = SimpleNamespace(get_model=lambda model_id, user_id=None: model if user_id == "alice" else None)
        with _session(), patch("docsgpt.drafter.model.drafter_model_id", return_value="byom-uuid"), patch(
            "docsgpt.core.model_registry.ModelRegistry.get_instance", return_value=registry
        ):
            response = client.get("/api/drafter/config")
        assert response.status_code == 200
        assert response.get_json() == {
            "enabled": True, "model": {"id": "byom-uuid", "display_name": "Claude Haiku"}, "reason": None,
        }

    def test_no_model(self, client):
        with _session(), patch("docsgpt.drafter.model.drafter_model_id", return_value=None):
            response = client.get("/api/drafter/config")
        assert response.get_json() == {"enabled": False, "model": None, "reason": "no_model"}

    def test_a_model_the_registry_no_longer_knows_is_no_model(self, client):
        registry = SimpleNamespace(get_model=lambda model_id, user_id=None: None)
        with _session(), patch("docsgpt.drafter.model.drafter_model_id", return_value="gone"), patch(
            "docsgpt.core.model_registry.ModelRegistry.get_instance", return_value=registry
        ):
            response = client.get("/api/drafter/config")
        assert response.get_json()["reason"] == "no_model"

    def test_disabled(self, client, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "DRAFTER_ENABLED", False)
        with _session(), patch("docsgpt.drafter.model.drafter_model_id") as resolver:
            response = client.get("/api/drafter/config")
        assert response.get_json() == {"enabled": False, "model": None, "reason": "disabled"}
        resolver.assert_not_called()


@pytest.mark.unit
class TestRefusals:
    def test_disabled(self, client, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "DRAFTER_ENABLED", False)
        response = _stream(client, _body())
        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        assert _events(response) == [
            {"type": "error", "code": "disabled", "message": "Drafting is turned off on this instance."},
            {"type": "end"},
        ]

    def test_no_model(self, client):
        events = _events(_stream(client, _body(), model=None))
        assert [e.get("code") for e in events] == ["no_model", None]

    @pytest.mark.parametrize("body", [
        {"recipe": "nope", "messages": [{"role": "user", "content": "x"}]},
        {"recipe": "agent", "messages": []},
        {"recipe": "agent", "messages": [{"role": "system", "content": "x"}]},
        {"recipe": "agent", "messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "{}"}]},
        {"recipe": "agent", "messages": [{"role": "user", "content": "x" * 9000}]},
        {"recipe": "agent", "messages": [{"role": "user", "content": "x"}], "context": {"form": "nope"}},
        {"recipe": "agent", "messages": [{"role": "user", "content": "x"}], "context": []},
    ])
    def test_bad_request(self, client, body):
        events = _events(_stream(client, body))
        assert events[0]["type"] == "error" and events[0]["code"] == "bad_request"
        assert events[-1] == {"type": "end"}

    def test_rate_limited(self, client):
        with patch("docsgpt.monitors.triggers.rate_limited", return_value=True) as limiter:
            events = _events(_stream(client, _body()))
        assert [e.get("code") for e in events] == ["rate_limited", None]
        limiter.assert_called_once_with("drafter", "alice", 10)

    def test_rate_limit_off_at_zero(self, client, monkeypatch, pg_conn):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "DRAFTER_RATE_LIMIT_PER_MINUTE", 0)
        fake = FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn), patch("docsgpt.monitors.triggers.rate_limited") as limiter:
            _events(_stream(client, _body(), fake))
        limiter.assert_not_called()

    def test_quota(self, client):
        exceeded = SimpleNamespace(to_payload=lambda: {"message": "Usage quota reached (10 of 10 tokens)."})
        with patch("docsgpt.quotas.service.QuotaService.check", return_value=exceeded) as check:
            events = _events(_stream(client, _body()))
        assert events[0] == {"type": "error", "code": "quota", "message": "Usage quota reached (10 of 10 tokens)."}
        check.assert_called_once_with("alice", "direct")


@pytest.mark.unit
class TestStream:
    def test_questions_then_proposal(self, client, pg_conn):
        first = FakeLLM(calls(tool_call("ask_user", QUESTIONS)))
        with _db(pg_conn):
            events = _events(_stream(client, _body(), first))
        assert _types(events) == ["status:reading", "status:reading", "status:drafting", "message", "questions", "end"]
        assert events[1]["counts"] == {"sources": 0, "tools": events[1]["counts"]["tools"], "prompts": 3,
                                       "models": events[1]["counts"]["models"]}
        assert events[3] == {"type": "message", "text": "Two questions before I draft:"}
        questions = events[4]["questions"]
        assert [q["id"] for q in questions] == ["q1", "q2"]
        assert questions[0]["options"] == [
            {"id": "a", "label": "Email support", "input": None, "exclusive": False},
            {"id": "b", "label": "Collect details and stop", "input": None, "exclusive": False},
        ]
        assert questions[1]["multi"] is True and questions[0]["note"] is None
        assert first.built_for[0] == "alice" and first.built_for[1] == "task-model"
        assert first.built_for[2].startswith("drafter:")

        second = FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))
        history = _body(
            {"role": "user", "content": "A shipping help agent for our website."},
            {"role": "assistant", "content": json.dumps({"questions": questions})},
            {"role": "user", "content": "Where should refund requests go? → Email support"},
        )
        with _db(pg_conn):
            events = _events(_stream(client, history, second))
        assert _types(events) == ["status:reading", "status:reading", "status:drafting", "proposal", "end"]
        proposal = events[3]["proposal"]
        assert proposal["fields"] == {
            "name": "Shipping help", "description": "Answers shipping questions.",
            "starters": ["Where is my parcel?"],
        }  # agent_type "classic" equals the empty form's default, so it is left out
        assert proposal["dropped"] == [] and proposal["message"] == "Drafted a shipping help agent."
        sent = second.calls[0]["messages"]
        assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
        assert sent[-1]["content"].endswith("The user's request:\nWhere should refund requests go? → Email support")
        assert DATA_GUARD in sent[-1]["content"]

    def test_read_tool_then_proposal(self, client, pg_conn):
        prompt = PromptsRepository(pg_conn).create("alice", "Support", "You help customers of Meridian.")
        fake = FakeLLM(
            calls(tool_call("get_prompt", {"prompt_id": str(prompt["id"])}, "c1")),
            calls(tool_call("submit_proposal", {
                **PROPOSAL, "fields": {"prompt": {"kind": "existing", "id": str(prompt["id"])}},
            }, "c2")),
        )
        with _db(pg_conn):
            events = _events(_stream(client, _body(), fake))
        assert _types(events) == ["status:reading", "status:reading", "status:drafting", "proposal", "end"]
        assert events[3]["proposal"]["fields"] == {"prompt": {"kind": "existing", "id": str(prompt["id"])}}
        tool_message = fake.calls[1]["messages"][-1]
        assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "c1"
        assert "You help customers of Meridian." in tool_message["content"]
        assert tool_message["content"].endswith(DATA_GUARD)
        offered = [t["function"]["name"] for t in fake.calls[0]["tools"]]
        assert offered == ["get_prompt", "get_source", "get_tool", "ask_user", "submit_proposal"]

    def test_invalid_output_is_corrected_once(self, client, pg_conn):
        bad = {**PROPOSAL, "fields": {"agent_type": "agentic"}}
        fake = FakeLLM(
            calls(tool_call("submit_proposal", bad, "c1")),
            calls(tool_call("submit_proposal", {**PROPOSAL, "fields": {"agent_type": "research"}}, "c2")),
        )
        with _db(pg_conn):
            events = _events(_stream(client, _body(), fake))
        assert _types(events) == ["status:reading", "status:reading", "status:drafting", "proposal", "end"]
        assert events[3]["proposal"]["fields"] == {"agent_type": "research"}
        correction = fake.calls[1]["messages"][-1]
        assert correction["role"] == "tool" and correction["content"].startswith("Not accepted:")

    def test_invalid_output_twice_is_an_error(self, client, pg_conn):
        bad = {**PROPOSAL, "fields": {"agent_type": "agentic"}}
        fake = FakeLLM(calls(tool_call("submit_proposal", bad)), calls(tool_call("submit_proposal", bad)))
        with _db(pg_conn):
            events = _events(_stream(client, _body(), fake))
        assert _types(events) == ["status:reading", "status:reading", "status:drafting", "error", "end"]
        assert events[3]["code"] == "invalid_output"
        assert len(fake.calls) == 2

    def test_model_failure(self, client, pg_conn):
        fake = FakeLLM(RuntimeError("upstream 500"))
        with _db(pg_conn):
            events = _events(_stream(client, _body(), fake))
        assert _types(events) == ["status:reading", "status:reading", "status:drafting", "error", "end"]
        assert events[3]["code"] == "model_error" and "500" not in events[3]["message"]

    def test_a_model_without_tools_answers_json(self, client, pg_conn):
        fake = FakeLLM(plain("```json\n" + json.dumps({"type": "proposal", **PROPOSAL}) + "\n```"))
        with _db(pg_conn):
            events = _events(_stream(client, _body(), fake, model={**MODEL, "supports_tools": False}))
        assert _types(events) == ["status:reading", "status:reading", "status:drafting", "proposal", "end"]
        assert not fake.calls[0]["tools"]
        assert "Answer with exactly one JSON object" in fake.calls[0]["messages"][0]["content"]

    def test_a_plain_reply_after_a_correction_reaches_the_user(self, client, pg_conn):
        fake = FakeLLM(plain("I can only draft agents."), plain("I can only draft agents."))
        with _db(pg_conn):
            events = _events(_stream(client, _body(), fake))
        assert _types(events) == ["status:reading", "status:reading", "status:drafting", "message", "end"]
        assert events[3]["text"] == "I can only draft agents."

    def test_the_turn_writes_no_logs_or_conversations(self, client, pg_conn):
        def counts():
            return {table: pg_conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
                    for table in ("user_logs", "conversations", "conversation_messages", "token_usage")}

        before = counts()
        fake = FakeLLM(calls(tool_call("ask_user", QUESTIONS)))
        with _db(pg_conn), patch("docsgpt.storage.db.session.db_session") as writer:
            _events(_stream(client, _body(), fake))
        writer.assert_not_called()
        assert counts() == before

    def test_the_workspace_is_read_on_the_stream_after_the_reading_status(self, client, pg_conn):
        order = []

        def read(*args, **kwargs):
            order.append("read")
            from docsgpt.drafter.catalog import read_workspace

            return read_workspace(*args, **kwargs)

        fake = FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn), patch("docsgpt.drafter.agent_recipe.read_workspace", side_effect=read), patch(
            "docsgpt.api.user.drafter.routes._frame", side_effect=lambda event: order.append(event["type"]) or (
                f"data: {json.dumps(event)}\n\n")
        ):
            events = _events(_stream(client, _body(), fake))
        assert events[0] == {"type": "status", "step": "reading"}
        assert order[:3] == ["status", "read", "status"]

    def test_a_workspace_that_cant_be_read_ends_the_turn_with_an_error(self, client, pg_conn):
        fake = FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn), patch("docsgpt.drafter.agent_recipe.read_workspace", side_effect=RuntimeError("db")):
            events = _events(_stream(client, _body(), fake))
        assert _types(events) == ["status:reading", "error", "end"]
        assert events[1]["code"] == "model_error" and "workspace could not be read" in events[1]["message"]
        assert fake.calls == []


class _Redis(FakeRedis):
    """The Activity tests' fake Redis, with ``set(nx=True)`` and the sorted-set calls running turns use."""

    def __init__(self) -> None:
        super().__init__()
        self.zsets: dict = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and self._alive(key):
            return None
        return super().set(key, value, ex=ex)

    def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    def zrem(self, key, *members):
        zset = self.zsets.get(key, {})
        for member in members:
            zset.pop(member, None)
        if not zset:
            self.zsets.pop(key, None)

    def zremrangebyscore(self, key, low, high):
        zset = self.zsets.get(key, {})
        for member, score in list(zset.items()):
            if score <= high:
                del zset[member]
        if not zset:
            self.zsets.pop(key, None)

    def zcard(self, key):
        return len(self.zsets.get(key, {}))

    def expire(self, key, seconds):
        return True


@pytest.fixture
def redis(monkeypatch):
    fake = _Redis()
    monkeypatch.setattr("docsgpt.drafter.service._turn_store", lambda: fake)
    return fake


def _turn_ids(redis) -> list[str]:
    """The ids of the turns running now (``drafter:turn:<user>:<id>``; a stop adds ``:stop``)."""
    return [key.rsplit(":", 1)[1] for key in redis.kv if not key.endswith(":stop")]


@pytest.mark.unit
class TestCancel:
    def _cancel(self, client, turn_id, user="alice"):
        with _session(user):
            return client.post(f"/api/drafter/turns/{turn_id}/cancel")

    def test_the_turn_id_comes_first_and_is_forgotten_at_the_end(self, client, pg_conn, redis):
        seen = []

        class Recording(FakeLLM):
            def gen_stream(self, *args, **kwargs):
                seen.extend(_turn_ids(redis))
                return super().gen_stream(*args, **kwargs)

        fake = Recording(calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn):
            events = _events(_stream(client, _body(), fake))
        assert _types(events) == ["turn", "status:reading", "status:reading", "status:drafting", "proposal", "end"]
        assert seen == [events[0]["id"]] and redis.kv == {}

    def test_a_cancelled_turn_makes_no_further_model_calls(self, client, pg_conn, redis):
        from docsgpt.drafter.service import cancel_turn

        class Cancelling(FakeLLM):
            def gen_stream(self, *args, **kwargs):
                [turn_id] = _turn_ids(redis)
                assert cancel_turn("alice", turn_id) is True
                return super().gen_stream(*args, **kwargs)

        fake = Cancelling(calls(tool_call("get_prompt", {"prompt_id": "default"})),
                          calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn):
            events = _events(_stream(client, _body(), fake))
        assert _types(events) == ["turn", "status:reading", "status:reading", "status:drafting", "end"]
        assert len(fake.calls) == 1

    def test_the_owner_cancels_their_turn(self, client, redis):
        from docsgpt.drafter.service import start_turn, turn_cancelled

        turn_id = start_turn("alice")
        response = self._cancel(client, turn_id)
        assert response.status_code == 202 and turn_cancelled("alice", turn_id)

    def test_another_user_cannot_stop_the_turn(self, client, redis):
        from docsgpt.drafter.service import start_turn, turn_cancelled

        turn_id = start_turn("alice")
        # Bob's stop is kept under Bob's name, so it reaches no turn of Alice's.
        assert self._cancel(client, turn_id, user="bob").status_code == 202
        assert not turn_cancelled("alice", turn_id)

    def test_a_malformed_turn_id_is_not_found(self, client, redis):
        assert self._cancel(client, "not-a-turn").status_code == 404

    def test_the_panel_names_its_turn(self, client, pg_conn, redis):
        fake = FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn):
            events = _events(_stream(client, {**_body(), "turn_id": "d" * 32}, fake))
        assert events[0] == {"type": "turn", "id": "d" * 32}
        assert _types(events) == ["turn", "status:reading", "status:reading", "status:drafting", "proposal", "end"]

    @pytest.mark.parametrize("turn_id", ["nope", "D" * 32, 7, None])
    def test_a_malformed_turn_id_gets_one_of_the_servers(self, client, pg_conn, redis, turn_id):
        fake = FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn):
            events = _events(_stream(client, {**_body(), "turn_id": turn_id}, fake))
        assert events[0]["type"] == "turn" and events[0]["id"] != turn_id
        assert len(events[0]["id"]) == 32 and int(events[0]["id"], 16) >= 0

    def test_a_turn_stopped_before_it_starts_makes_no_model_calls(self, client, pg_conn, redis):
        # The panel's Stop can reach the server before the stream's first event, or before the stream itself.
        assert self._cancel(client, "e" * 32).status_code == 202
        fake = FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn):
            events = _events(_stream(client, {**_body(), "turn_id": "e" * 32}, fake))
        # Stopped before it started: nothing is read and no model is called.
        assert _types(events) == ["turn", "end"]
        assert fake.calls == [] and redis.kv == {}

    def test_a_refused_read_still_frees_the_turns_place(self, client, pg_conn, redis):
        from docsgpt.drafter.recipe import BadDraftRequest

        with _db(pg_conn), patch("docsgpt.drafter.agent_recipe.read_workspace",
                                 side_effect=BadDraftRequest("Agent not found")):
            events = _events(_stream(client, _body(), FakeLLM()))
        assert _types(events) == ["turn", "status:reading", "error", "end"]
        assert events[2]["code"] == "bad_request" and redis.kv == {} and redis.zsets == {}

    def test_another_users_early_stop_does_not_reach_the_turn(self, client, pg_conn, redis):
        assert self._cancel(client, "f" * 32, user="bob").status_code == 202
        fake = FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn):
            events = _events(_stream(client, {**_body(), "turn_id": "f" * 32}, fake))
        assert _types(events) == ["turn", "status:reading", "status:reading", "status:drafting", "proposal", "end"]

    def test_two_running_turns_never_share_an_id(self, redis):
        from docsgpt.drafter.service import cancel_turn, start_turn, turn_cancelled

        first = start_turn("alice", "a" * 32)
        second = start_turn("alice", "a" * 32)
        assert first == "a" * 32 and second not in (None, first)
        assert cancel_turn("alice", second) is True
        assert turn_cancelled("alice", second) and not turn_cancelled("alice", first)

    def test_without_redis_the_turn_runs_and_cancel_is_unavailable(self, client, pg_conn):
        fake = FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn):
            events = _events(_stream(client, _body(), fake))
        assert _types(events) == ["status:reading", "status:reading", "status:drafting", "proposal", "end"]
        assert self._cancel(client, "c" * 32).status_code == 503

    def test_a_cancel_store_that_fails_never_fails_the_turn(self, client, pg_conn, redis, monkeypatch):
        def broken(*args, **kwargs):
            raise ConnectionError("redis went away")

        fake = FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn):
            monkeypatch.setattr(redis, "exists", broken)
            monkeypatch.setattr(redis, "delete", broken)
            events = _events(_stream(client, _body(), fake))
        assert _types(events) == ["turn", "status:reading", "status:reading", "status:drafting", "proposal", "end"]


class _Status(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


@pytest.mark.unit
class TestModelAuth:
    """A key the provider refuses is remembered for Settings; the next good turn with that model forgets it."""

    @pytest.fixture(autouse=True)
    def _instance_model(self, monkeypatch):
        monkeypatch.setattr("docsgpt.core.model_utils.get_task_model_id", lambda user_id: "instance-model")

    def test_a_refused_key_is_model_auth_and_remembered(self, client, pg_conn, redis):
        from docsgpt.drafter.service import model_failure

        with _db(pg_conn):
            events = _events(_stream(client, _body(), FakeLLM(_Status(401))))
        error = next(e for e in events if e["type"] == "error")
        assert error["code"] == "model_auth"
        assert model_failure("alice", "task-model")["code"] == "model_auth"
        assert model_failure(None, "task-model") is None, "not the instance's model"

    def test_the_instance_model_failing_is_remembered_for_the_instance(self, client, pg_conn, redis):
        from docsgpt.drafter.service import model_failure

        model = {**MODEL, "id": "instance-model"}
        with _db(pg_conn):
            _events(_stream(client, _body(), FakeLLM(_Status(403)), model=model))
        assert model_failure(None, "instance-model")["code"] == "model_auth"

    def test_a_good_turn_with_that_model_forgets_it(self, client, pg_conn, redis):
        from docsgpt.drafter.service import model_failure, record_model_failure

        record_model_failure("alice", "task-model", "model_auth")
        with _db(pg_conn):
            _events(_stream(client, _body(), FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))))
        assert model_failure("alice", "task-model") is None

    def test_other_failures_are_not_remembered(self, client, pg_conn, redis):
        from docsgpt.drafter.service import model_failure

        with _db(pg_conn):
            _events(_stream(client, _body(), FakeLLM(_Status(500))))
        assert model_failure("alice", "task-model") is None


@pytest.mark.unit
class TestRunningTurns:
    """A user runs at most DRAFTER_MAX_RUNNING_TURNS turns at once; a crashed turn's claim runs out on its own."""

    @pytest.fixture(autouse=True)
    def _cap(self, monkeypatch):
        monkeypatch.setattr(settings, "DRAFTER_MAX_RUNNING_TURNS", 2)

    def test_a_turn_past_the_cap_is_refused_and_an_ended_one_frees_its_place(self, redis):
        from docsgpt.drafter.service import claim_running, end_turn

        assert claim_running("alice", "a" * 32) and claim_running("alice", "b" * 32)
        assert not claim_running("alice", "c" * 32)
        assert set(redis.zsets["drafter:running:alice"]) == {"a" * 32, "b" * 32}
        assert claim_running("bob", "c" * 32)
        end_turn("alice", "a" * 32)
        assert claim_running("alice", "c" * 32)

    def test_a_claim_past_its_life_no_longer_counts(self, redis):
        import time

        from docsgpt.drafter.service import claim_running

        redis.zsets["drafter:running:alice"] = {"a" * 32: time.time() - 1, "b" * 32: time.time() - 1}
        assert claim_running("alice", "c" * 32)
        assert set(redis.zsets["drafter:running:alice"]) == {"c" * 32}

    def test_no_cap_or_no_redis_never_refuses(self, monkeypatch, redis):
        from docsgpt.drafter import service

        monkeypatch.setattr(settings, "DRAFTER_MAX_RUNNING_TURNS", 0)
        assert all(service.claim_running("alice", f"{n:032x}") for n in range(5)) and redis.zsets == {}
        monkeypatch.setattr(settings, "DRAFTER_MAX_RUNNING_TURNS", 1)
        monkeypatch.setattr(service, "_turn_store", lambda: None)
        assert all(service.claim_running("alice", f"{n:032x}") for n in range(5))

    def test_a_failing_store_never_refuses(self, monkeypatch, redis):
        from docsgpt.drafter.service import claim_running

        def broken(*args, **kwargs):
            raise ConnectionError("redis went away")

        monkeypatch.setattr(redis, "zadd", broken)
        assert claim_running("alice", "a" * 32)

    def test_the_stream_refuses_a_turn_past_the_cap_before_any_model_call(self, client, pg_conn, redis,
                                                                         monkeypatch):
        import time

        monkeypatch.setattr(settings, "DRAFTER_MAX_RUNNING_TURNS", 1)
        redis.zsets["drafter:running:alice"] = {"a" * 32: time.time() + 300}
        fake = FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn):
            events = _events(_stream(client, {**_body(), "turn_id": "b" * 32}, fake))
        assert [(e["type"], e.get("code")) for e in events] == [("error", "rate_limited"), ("end", None)]
        assert fake.calls == [] and redis.kv == {}
        assert set(redis.zsets["drafter:running:alice"]) == {"a" * 32}

    def test_a_turn_frees_its_place_when_it_ends(self, client, pg_conn, redis):
        fake = FakeLLM(calls(tool_call("submit_proposal", PROPOSAL)))
        with _db(pg_conn):
            events = _events(_stream(client, _body(), fake))
        assert _types(events)[-2:] == ["proposal", "end"] and redis.zsets == {}

    def test_cancels_past_the_minute_limit_are_a_429(self, client, redis):
        with patch("docsgpt.monitors.triggers.rate_limited", return_value=True) as limiter, _session("alice"):
            response = client.post(f"/api/drafter/turns/{'a' * 32}/cancel")
        assert response.status_code == 429
        from docsgpt.drafter.service import CANCEL_RATE_PER_MINUTE

        limiter.assert_called_once_with("drafter_cancel", "alice", CANCEL_RATE_PER_MINUTE)
