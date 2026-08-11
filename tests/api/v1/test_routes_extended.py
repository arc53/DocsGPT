"""Extended unit tests for application/api/v1/routes.py.

Covers:
  - _extract_bearer_token helper
  - _lookup_agent helper (happy path + exception)
  - _get_model_name helper
  - /v1/chat/completions: auth error, missing messages, translate error,
    non-stream success, stream success, ValueError, generic Exception,
    tool_actions continuation path (missing conversation_id),
    usage_error path
  - /v1/models: missing auth, mongo exception path, with createdAt timestamp
"""


from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from application.api.v1.routes import (
    _extract_bearer_token,
    _get_model_name,
    v1_bp,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeCollection:
    pass

    def __init__(self, docs):
        self.docs = list(docs)

    def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    def find(self, query):
        return [d for d in self.docs if all(d.get(k) == v for k, v in query.items())]


def _build_app():
    app = Flask(__name__)
    app.register_blueprint(v1_bp)
    return app


# ---------------------------------------------------------------------------
# _extract_bearer_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractBearerToken:
    pass

    def test_returns_token_from_bearer_header(self):
        app = _build_app()
        with app.test_request_context(headers={"Authorization": "Bearer my-api-key"}):
            assert _extract_bearer_token() == "my-api-key"

    def test_returns_none_when_no_authorization_header(self):
        app = _build_app()
        with app.test_request_context():
            assert _extract_bearer_token() is None

    def test_returns_none_when_not_bearer_scheme(self):
        app = _build_app()
        with app.test_request_context(headers={"Authorization": "Token my-api-key"}):
            assert _extract_bearer_token() is None

    def test_strips_whitespace(self):
        app = _build_app()
        with app.test_request_context(headers={"Authorization": "Bearer  spaced-key  "}):
            assert _extract_bearer_token() == "spaced-key"


# ---------------------------------------------------------------------------
# _lookup_agent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLookupAgent:
    pass




# ---------------------------------------------------------------------------
# _get_model_name
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetModelName:
    pass

    def test_returns_agent_name_when_agent_has_name(self):
        assert _get_model_name({"name": "My Agent"}, "api-key") == "My Agent"

    def test_falls_back_to_api_key_when_agent_has_no_name(self):
        assert _get_model_name({"user": "u"}, "api-key") == "api-key"

    def test_returns_api_key_when_no_agent(self):
        assert _get_model_name(None, "api-key") == "api-key"


# ---------------------------------------------------------------------------
# /v1/chat/completions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestChatCompletions:
    pass

    def _make_mongo(self, key="key-1", user="user-1"):
        agent = {"_id": "agent-1", "key": key, "user": user}
        fake_col = _FakeCollection([agent])
        return {"testdb": {"agents": fake_col}}

    def _patch_mongo(self, monkeypatch, mongo=None):
        if mongo is None:
            mongo = self._make_mongo()
        monkeypatch.setattr("application.api.v1.routes.MongoDB.get_client", lambda: mongo)
        monkeypatch.setattr("application.api.v1.routes.settings.MONGO_DB_NAME", "testdb")

    def test_missing_auth_returns_401(self):
        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
            )
        assert resp.status_code == 401
        assert resp.get_json()["error"]["type"] == "auth_error"















# ---------------------------------------------------------------------------
# /v1/models — additional edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListModelsExtra:
    pass

    def test_missing_auth_header_returns_401(self):
        app = _build_app()
        with app.test_client() as client:
            resp = client.get("/v1/models")
        assert resp.status_code == 401
        assert resp.get_json()["error"]["type"] == "auth_error"


# ---------------------------------------------------------------------------
# Tests using the ephemeral pg_conn fixture against real PG
# ---------------------------------------------------------------------------


@contextmanager
def _patch_v1_db(conn):
    from application.storage.db.repositories.agents import AgentsRepository

    if AgentsRepository(conn).find_by_key("x") is None:
        AgentsRepository(conn).create("u-test", "Test Agent", "published", key="x")

    @contextmanager
    def _yield():
        yield conn

    with patch("application.api.v1.routes.db_readonly", _yield):
        yield


@pytest.mark.unit
def test_response_usage_reports_cumulative_turn_totals():
    from types import SimpleNamespace

    from application.api.v1.routes import _response_usage

    # Multi-round tool turns must report the accumulator's turn total,
    # not the final round's provider snapshot.
    agent = SimpleNamespace(
        llm=SimpleNamespace(
            _last_usage={
                "prompt_tokens": 5,
                "completion_tokens": 1,
                "total_tokens": 6,
            },
            token_usage={"prompt_tokens": 30, "generated_tokens": 12},
        )
    )
    assert _response_usage(agent) == {
        "prompt_tokens": 30,
        "completion_tokens": 12,
        "total_tokens": 42,
    }


@pytest.mark.unit
class TestLookupAgentHappy:
    def test_returns_agent_for_valid_key(self, pg_conn):
        from application.api.v1.routes import _lookup_agent
        from application.storage.db.repositories.agents import AgentsRepository

        AgentsRepository(pg_conn).create("u1", "Test", "published", key="k-ok")

        with _patch_v1_db(pg_conn):
            got = _lookup_agent("k-ok")
        assert got is not None
        assert got["key"] == "k-ok"

    def test_returns_none_when_not_found(self, pg_conn):
        from application.api.v1.routes import _lookup_agent

        with _patch_v1_db(pg_conn):
            got = _lookup_agent("nope")
        assert got is None

    def test_returns_none_on_exception(self):
        from application.api.v1.routes import _lookup_agent

        @contextmanager
        def _broken():
            raise RuntimeError("db down")
            yield

        with patch("application.api.v1.routes.db_readonly", _broken):
            got = _lookup_agent("k")
        assert got is None


@pytest.mark.unit
class TestListModelsPgConn:
    def test_invalid_key_returns_401(self, pg_conn):
        app = _build_app()
        with _patch_v1_db(pg_conn):
            with app.test_client() as c:
                resp = c.get(
                    "/v1/models", headers={"Authorization": "Bearer bad"}
                )
        assert resp.status_code == 401

    def test_returns_agent_for_valid_key(self, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository

        app = _build_app()
        repo = AgentsRepository(pg_conn)
        repo.create("u-m", "A1", "published", key="models-key")
        repo.create("u-m", "A2", "published", key="models-key-2")

        with _patch_v1_db(pg_conn):
            with app.test_client() as c:
                resp = c.get(
                    "/v1/models",
                    headers={"Authorization": "Bearer models-key"},
                )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["object"] == "list"
        names = {m["name"] for m in data["data"]}
        assert names == {"A1"}

    def test_db_error_returns_500(self):
        app = _build_app()

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch("application.api.v1.routes.db_readonly", _broken):
            with app.test_client() as c:
                resp = c.get(
                    "/v1/models",
                    headers={"Authorization": "Bearer any"},
                )
        assert resp.status_code == 500


@pytest.mark.unit
class TestChatCompletionsHappyPath:
    """Tests that reach the request-translate / processor code paths."""

    def test_missing_messages_returns_400(self, pg_conn):
        app = _build_app()
        with _patch_v1_db(pg_conn):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={},
                )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["type"] == "invalid_request"

    def test_invalid_api_key_returns_401_before_processing(self, pg_conn):
        app = _build_app()
        with _patch_v1_db(pg_conn):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer invalid"},
                    json={"messages": [{"role": "user", "content": "Hi"}]},
                )
        assert resp.status_code == 401

    def test_model_field_is_accepted_and_ignored(self, pg_conn):
        app = _build_app()
        fake_processor = MagicMock()
        fake_processor.decoded_token = {"sub": "u-test"}
        fake_processor.conversation_id = None
        fake_processor.agent_config = {}
        fake_processor.agent_id = None
        fake_processor.model_id = "m"
        fake_processor.build_agent.return_value = MagicMock()
        fake_helper = MagicMock()
        fake_helper.check_usage.return_value = None
        fake_helper.process_response_stream.return_value = {
            "error": None,
            "conversation_id": "conv-1",
            "answer": "ok",
            "sources": [],
            "tool_calls": [],
            "thought": "",
            "extra": {},
        }
        with _patch_v1_db(pg_conn), patch(
            "application.api.v1.routes.StreamProcessor",
            return_value=fake_processor,
        ), patch(
            "application.api.v1.routes._V1AnswerHelper",
            return_value=fake_helper,
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={
                        "model": "another-agent",
                        "messages": [{"role": "user", "content": "Hi"}],
                    },
                )
        assert resp.status_code == 200

    def test_null_n_is_treated_as_default(self, pg_conn):
        app = _build_app()
        with _patch_v1_db(pg_conn), patch(
            "application.api.v1.routes.translate_request",
            side_effect=ValueError("reached translator"),
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={
                        "n": None,
                        "messages": [{"role": "user", "content": "Hi"}],
                    },
                )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["message"] == "Failed to process request"

    def test_non_object_stream_options_returns_400(self, pg_conn):
        app = _build_app()
        with _patch_v1_db(pg_conn):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={
                        "stream": True,
                        "stream_options": True,
                        "messages": [{"role": "user", "content": "Hi"}],
                    },
                )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["type"] == "invalid_request_error"

    def test_conversation_id_must_belong_to_authenticated_agent(self, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        agents = AgentsRepository(pg_conn)
        first = agents.create("same-owner", "First", "published", key="agent-a")
        agents.create("same-owner", "Second", "published", key="agent-b")
        conversation = ConversationsRepository(pg_conn).create(
            "same-owner", "private", agent_id=str(first["id"])
        )
        app = _build_app()
        with _patch_v1_db(pg_conn):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer agent-b"},
                    json={
                        "model": "ignored",
                        "conversation_id": str(conversation["id"]),
                        "messages": [{"role": "user", "content": "secret?"}],
                    },
                )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "conversation_not_found"

    def test_stale_session_mapping_is_deleted_and_replaced(self, pg_conn):
        app = _build_app()
        fake_processor = MagicMock()
        fake_processor.decoded_token = {"sub": "u-test"}
        fake_processor.conversation_id = None
        fake_processor.agent_config = {}
        fake_processor.agent_id = None
        fake_processor.model_id = "m"
        fake_processor.build_agent.return_value = MagicMock()
        fake_helper = MagicMock()
        fake_helper.check_usage.return_value = None
        fake_helper.process_response_stream.return_value = {
            "error": None,
            "conversation_id": "new-conversation",
            "answer": "ok",
            "sources": [],
            "tool_calls": [],
            "thought": "",
            "extra": {},
        }
        with _patch_v1_db(pg_conn), patch(
            "application.api.v1.routes.load_conversation",
            return_value="deleted-conversation",
        ), patch(
            "application.api.v1.routes._conversation_belongs_to_agent",
            return_value=False,
        ), patch(
            "application.api.v1.routes.delete_conversation",
        ) as delete_mapping, patch(
            "application.api.v1.routes.StreamProcessor",
            return_value=fake_processor,
        ), patch(
            "application.api.v1.routes._V1AnswerHelper",
            return_value=fake_helper,
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={
                        "Authorization": "Bearer x",
                        "X-DocsGPT-Session-ID": "session",
                    },
                    json={"messages": [{"role": "user", "content": "Hi"}]},
                )
        assert resp.status_code == 200
        delete_mapping.assert_called_once()

    def test_duplicate_resume_returns_conflict(self, pg_conn):
        from application.api.answer.services.continuation_service import (
            ResumeInProgressError,
        )

        app = _build_app()
        fake_processor = MagicMock()
        fake_processor.decoded_token = {"sub": "u-test"}
        with _patch_v1_db(pg_conn), patch(
            "application.api.v1.routes.translate_request",
            return_value={
                "conversation_id": "conv-1",
                "tool_actions": [{"call_id": "call-1", "result": "ok"}],
                "messages": [],
            },
        ), patch(
            "application.api.v1.routes._conversation_belongs_to_agent",
            return_value=True,
        ), patch(
            "application.api.v1.routes.StreamProcessor",
            return_value=fake_processor,
        ), patch(
            "application.api.v1.routes.ContinuationService.claim_state",
            side_effect=ResumeInProgressError("Resume already in progress"),
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={"messages": [{"role": "tool", "content": "ok"}]},
                )
        assert resp.status_code == 409
        assert resp.get_json()["error"]["code"] == "resume_in_progress"

    def test_unsupported_n_and_logprobs_are_explicit(self, pg_conn):
        app = _build_app()
        with _patch_v1_db(pg_conn):
            with app.test_client() as c:
                n_response = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={"n": 2, "messages": [{"role": "user", "content": "Hi"}]},
                )
                logprobs_response = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={
                        "logprobs": True,
                        "messages": [{"role": "user", "content": "Hi"}],
                    },
                )
        assert n_response.status_code == 400
        assert logprobs_response.status_code == 400

    def test_translate_error_returns_400(self, pg_conn):
        app = _build_app()
        with _patch_v1_db(pg_conn), patch(
            "application.api.v1.routes.translate_request",
            side_effect=ValueError("bad"),
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={"messages": [{"role": "user", "content": "Hi"}]},
                )
        assert resp.status_code == 400

    def test_tool_actions_missing_conversation_id_returns_400(self, pg_conn):
        app = _build_app()

        def _fake_translate(data, api_key):
            return {
                "question": "",
                "tool_actions": [{"id": "t1", "result": "r"}],
                # missing conversation_id
            }

        with _patch_v1_db(pg_conn), patch(
            "application.api.v1.routes.translate_request",
            side_effect=_fake_translate,
        ), patch(
            "application.api.v1.routes.StreamProcessor",
            return_value=MagicMock(decoded_token={"sub": "u"}),
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={"messages": [{"role": "user", "content": "Hi"}]},
                )
        assert resp.status_code == 400

    def test_processor_value_error_returns_400(self, pg_conn):
        app = _build_app()

        def _fake_translate(data, api_key):
            return {"question": "q"}

        fake_processor = MagicMock()
        fake_processor.build_agent.side_effect = ValueError("boom")

        with _patch_v1_db(pg_conn), patch(
            "application.api.v1.routes.translate_request",
            side_effect=_fake_translate,
        ), patch(
            "application.api.v1.routes.StreamProcessor",
            return_value=fake_processor,
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={"messages": [{"role": "user", "content": "Hi"}]},
                )
        assert resp.status_code == 400

    def test_processor_generic_exception_returns_500(self, pg_conn):
        app = _build_app()

        def _fake_translate(data, api_key):
            return {"question": "q"}

        fake_processor = MagicMock()
        fake_processor.build_agent.side_effect = RuntimeError("boom")

        with _patch_v1_db(pg_conn), patch(
            "application.api.v1.routes.translate_request",
            side_effect=_fake_translate,
        ), patch(
            "application.api.v1.routes.StreamProcessor",
            return_value=fake_processor,
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={"messages": [{"role": "user", "content": "Hi"}]},
                )
        assert resp.status_code == 500

    def test_non_stream_success_path(self, pg_conn):
        app = _build_app()

        def _fake_translate(data, api_key):
            return {"question": "hi", "save_conversation": False}

        fake_processor = MagicMock()
        fake_processor.decoded_token = {"sub": "u"}
        fake_processor.conversation_id = None
        fake_processor.agent_config = {"user_api_key": "k"}
        fake_processor.agent_id = None
        fake_processor.model_id = "m"
        fake_processor.build_agent.return_value = MagicMock()

        def _fake_stream(*a, **kw):
            yield 'data: {"type": "end"}'

        fake_helper = MagicMock()
        fake_helper.check_usage.return_value = None
        fake_helper.complete_stream.side_effect = _fake_stream
        fake_helper.process_response_stream.return_value = {
            "error": None,
            "conversation_id": "conv-1",
            "answer": "hello",
            "sources": [],
            "tool_calls": [],
            "thought": "",
            "extra": {},
        }

        with _patch_v1_db(pg_conn), patch(
            "application.api.v1.routes.translate_request",
            side_effect=_fake_translate,
        ), patch(
            "application.api.v1.routes.StreamProcessor",
            return_value=fake_processor,
        ), patch(
            "application.api.v1.routes._V1AnswerHelper",
            return_value=fake_helper,
        ), patch(
            "application.api.v1.routes.translate_response",
            return_value={"id": "x", "choices": []},
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={"messages": [{"role": "user", "content": "Hi"}]},
                )
        assert resp.status_code == 200

    def test_non_stream_error_in_result_returns_500(self, pg_conn):
        app = _build_app()

        def _fake_translate(data, api_key):
            return {"question": "hi"}

        fake_processor = MagicMock()
        fake_processor.decoded_token = {"sub": "u"}
        fake_processor.conversation_id = None
        fake_processor.agent_config = {}
        fake_processor.agent_id = None
        fake_processor.model_id = "m"
        fake_helper = MagicMock()
        fake_helper.check_usage.return_value = None
        fake_helper.complete_stream.return_value = iter([])
        fake_helper.process_response_stream.return_value = {
            "error": "something went wrong",
            "conversation_id": None,
            "answer": None,
            "sources": None,
            "tool_calls": None,
            "thought": None,
            "extra": None,
        }

        with _patch_v1_db(pg_conn), patch(
            "application.api.v1.routes.translate_request",
            side_effect=_fake_translate,
        ), patch(
            "application.api.v1.routes.StreamProcessor",
            return_value=fake_processor,
        ), patch(
            "application.api.v1.routes._V1AnswerHelper",
            return_value=fake_helper,
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={"messages": [{"role": "user", "content": "Hi"}]},
                )
        assert resp.status_code == 500

    def test_stream_success_returns_sse(self, pg_conn):
        app = _build_app()

        def _fake_translate(data, api_key):
            return {"question": "hi"}

        fake_processor = MagicMock()
        fake_processor.decoded_token = {"sub": "u"}
        fake_processor.conversation_id = "conv-1"
        fake_processor.agent_config = {}
        fake_processor.agent_id = None
        fake_processor.model_id = "m"

        def _fake_helper_complete_stream(**kw):
            yield 'data: {"type": "id", "id": "conv-1"}'
            yield 'data: {"type": "answer", "answer": "hi"}'

        fake_helper = MagicMock()
        fake_helper.check_usage.return_value = None
        fake_helper.complete_stream.side_effect = _fake_helper_complete_stream

        with _patch_v1_db(pg_conn), patch(
            "application.api.v1.routes.translate_request",
            side_effect=_fake_translate,
        ), patch(
            "application.api.v1.routes.StreamProcessor",
            return_value=fake_processor,
        ), patch(
            "application.api.v1.routes._V1AnswerHelper",
            return_value=fake_helper,
        ), patch(
            "application.api.v1.routes.translate_stream_event",
            return_value=["data: chunk\n\n"],
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={
                        "messages": [{"role": "user", "content": "Hi"}],
                        "stream": True,
                    },
                )
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"

    def test_stream_handles_id_prefixed_chunks(self, pg_conn):
        """``complete_stream`` emits ``id: <seq>\\n`` before each
        ``data:`` line. The v1 streaming consumer must skip the id
        header and the informational ``message_id`` event, not silently
        drop every chunk.
        """
        app = _build_app()

        def _fake_translate(data, api_key):
            return {"question": "hi"}

        fake_processor = MagicMock()
        fake_processor.decoded_token = {"sub": "u"}
        fake_processor.conversation_id = "conv-1"
        fake_processor.agent_config = {}
        fake_processor.agent_id = None
        fake_processor.model_id = "m"

        def _fake_helper_complete_stream(**kw):
            # Mirror the new wire format: id-prefixed records, plus
            # the informational message_id event the v1 path doesn't
            # have an analog for.
            yield 'id: 0\ndata: {"type": "message_id", "message_id": "m-1"}\n\n'
            yield 'id: 1\ndata: {"type": "id", "id": "conv-1"}\n\n'
            yield 'id: 2\ndata: {"type": "answer", "answer": "hi"}\n\n'

        translated_chunks: list = []

        def _fake_translate_stream_event(
            event_data, completion_id, model_name, strip_reasoning_leak=False, state=None
        ):
            translated_chunks.append(event_data)
            return ['data: x\n\n']

        fake_helper = MagicMock()
        fake_helper.check_usage.return_value = None
        fake_helper.complete_stream.side_effect = _fake_helper_complete_stream

        with _patch_v1_db(pg_conn), patch(
            "application.api.v1.routes.translate_request",
            side_effect=_fake_translate,
        ), patch(
            "application.api.v1.routes.StreamProcessor",
            return_value=fake_processor,
        ), patch(
            "application.api.v1.routes._V1AnswerHelper",
            return_value=fake_helper,
        ), patch(
            "application.api.v1.routes.translate_stream_event",
            side_effect=_fake_translate_stream_event,
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={
                        "messages": [{"role": "user", "content": "Hi"}],
                        "stream": True,
                    },
                )
                # Drain the response so the generator runs to completion.
                list(resp.iter_encoded())

        assert resp.status_code == 200
        # message_id event is skipped (no v1 analog); id + answer are
        # decoded and forwarded to the translator.
        types_translated = [c.get("type") for c in translated_chunks]
        assert "message_id" not in types_translated
        assert "id" in types_translated
        assert "answer" in types_translated
