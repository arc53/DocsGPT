"""One payer per run: every LLM call a run makes bills the payer fixed when it started."""

from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest

from docsgpt import tracing
from docsgpt.quotas.payer import billed_to, current_run_billing, published_access_payer
from docsgpt.usage import gen_token_usage


class _Repo:
    rows: list = []

    def __init__(self, conn=None):
        pass

    def insert(self, **kwargs):
        _Repo.rows.append(kwargs)


@contextmanager
def _no_db():
    yield None


@pytest.fixture
def rows(monkeypatch):
    _Repo.rows = []
    monkeypatch.setattr("docsgpt.usage.TokenUsageRepository", _Repo)
    monkeypatch.setattr("docsgpt.usage.db_session", _no_db)
    return _Repo.rows


class _LLM:
    """An LLM as a headless run builds it: it runs as the agent's owner."""

    def __init__(self, sub: str = "owner", request_id=None):
        self.decoded_token = {"sub": sub}
        self.user_api_key = "agent-key"
        self.agent_id = "agent-1"
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}
        self._request_id = request_id


@gen_token_usage
def _call(self, model, messages, stream, tools, **kwargs):
    return "an answer"


def _one_call(llm: _LLM) -> None:
    _call(llm, "m", [{"role": "user", "content": "hi"}], False, None)


@pytest.mark.unit
class TestBilledTo:
    def test_a_run_bills_its_payer_not_the_identity_it_runs_as(self, rows):
        with billed_to("setter"):
            _one_call(_LLM("owner"))

        assert rows[0]["user_id"] == "setter"
        # Still the agent's traffic.
        assert (rows[0]["api_key"], rows[0]["agent_id"]) == ("agent-key", "agent-1")

    def test_outside_a_run_the_caller_pays(self, rows):
        _one_call(_LLM("chatting-user"))

        assert rows[0]["user_id"] == "chatting-user"
        assert current_run_billing() is None

    def test_the_calls_of_a_run_are_one_request(self, rows):
        with billed_to("setter") as run:
            _one_call(_LLM())
            _one_call(_LLM())

        assert run.request_id
        assert [row["request_id"] for row in rows] == [run.request_id, run.request_id]

    def test_a_call_that_has_its_own_request_id_keeps_it(self, rows):
        with billed_to("setter"):
            _one_call(_LLM(request_id="chat-turn-1"))

        assert rows[0]["request_id"] == "chat-turn-1"

    def test_the_scope_ends_with_the_run(self, rows):
        with billed_to("setter"):
            pass
        _one_call(_LLM("owner"))

        assert rows[0]["user_id"] == "owner"
        assert rows[0]["request_id"] is None

    def test_work_handed_to_another_thread_bills_the_same_payer(self):
        seen = {}

        def _in_thread():
            seen["payer"] = getattr(current_run_billing(), "payer", None)

        with billed_to("setter"):
            thread = threading.Thread(target=tracing.wrap(_in_thread))
            thread.start()
            thread.join()

        assert seen["payer"] == "setter"


@pytest.mark.unit
class TestPublishedAccessPayer:
    def test_outside_traffic_on_an_agent_bills_its_owner(self):
        assert published_access_payer({"user_id": "owner", "id": "a"}) == "owner"

    def test_the_legacy_row_shape_names_the_owner_as_user(self):
        assert published_access_payer({"user": "owner"}) == "owner"

    def test_no_owner_means_no_payer(self):
        assert published_access_payer({}) is None
