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

import json
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from flask import Flask

from application.api.v1.routes import (
    _extract_bearer_token,
    _get_model_name,
    _lookup_agent,
    v1_bp,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeCollection:
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
    def test_returns_agent_doc(self, monkeypatch):
        app = _build_app()
        agent = {"_id": "agent-1", "key": "key-1", "user": "user-1"}
        fake_col = _FakeCollection([agent])
        fake_mongo = {"testdb": {"agents": fake_col}}

        monkeypatch.setattr("application.api.v1.routes.MongoDB.get_client", lambda: fake_mongo)
        monkeypatch.setattr("application.api.v1.routes.settings.MONGO_DB_NAME", "testdb")

        with app.test_request_context():
            result = _lookup_agent("key-1")
        assert result == agent

    def test_returns_none_when_not_found(self, monkeypatch):
        app = _build_app()
        fake_mongo = {"testdb": {"agents": _FakeCollection([])}}
        monkeypatch.setattr("application.api.v1.routes.MongoDB.get_client", lambda: fake_mongo)
        monkeypatch.setattr("application.api.v1.routes.settings.MONGO_DB_NAME", "testdb")

        with app.test_request_context():
            assert _lookup_agent("missing-key") is None

    def test_returns_none_on_exception(self, monkeypatch):
        app = _build_app()

        def _raise():
            raise RuntimeError("db down")

        monkeypatch.setattr("application.api.v1.routes.MongoDB.get_client", _raise)

        with app.test_request_context():
            assert _lookup_agent("key-1") is None


# ---------------------------------------------------------------------------
# _get_model_name
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetModelName:
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

    def test_missing_messages_returns_400(self, monkeypatch):
        self._patch_mongo(monkeypatch)
        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "test"},
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["type"] == "invalid_request"

    def test_empty_body_returns_400(self, monkeypatch):
        self._patch_mongo(monkeypatch)
        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                data="",
                content_type="application/json",
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 400

    def test_translate_request_exception_returns_400(self, monkeypatch):
        self._patch_mongo(monkeypatch)
        monkeypatch.setattr(
            "application.api.v1.routes.translate_request",
            lambda data, key: (_ for _ in ()).throw(ValueError("bad")),
        )
        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 400

    def test_non_stream_success(self, monkeypatch):
        """Happy path: non-streaming response."""
        self._patch_mongo(monkeypatch)

        internal_data = {"question": "What is Python?", "agent_id": "agent-1"}
        monkeypatch.setattr(
            "application.api.v1.routes.translate_request",
            lambda data, key: internal_data,
        )

        mock_processor = MagicMock()
        mock_processor.decoded_token = {"sub": "user-1"}
        mock_processor.agent_config = {"user_api_key": None}
        mock_processor.conversation_id = "conv-1"
        mock_processor.agent_id = "agent-1"
        mock_processor.model_id = None
        mock_processor.build_agent.return_value = MagicMock()

        monkeypatch.setattr(
            "application.api.v1.routes.StreamProcessor",
            lambda data, token: mock_processor,
        )

        mock_helper = MagicMock()
        mock_helper.check_usage.return_value = None
        mock_helper.process_response_stream.return_value = {
            "conversation_id": "conv-1",
            "answer": "Python is great",
            "sources": [],
            "tool_calls": [],
            "thought": "",
            "error": None,
            "extra": None,
        }
        monkeypatch.setattr(
            "application.api.v1.routes._V1AnswerHelper",
            lambda: mock_helper,
        )

        translated_response = {
            "id": "chatcmpl-conv-1",
            "object": "chat.completion",
            "choices": [{"message": {"role": "assistant", "content": "Python is great"}}],
        }
        monkeypatch.setattr(
            "application.api.v1.routes.translate_response",
            lambda **kwargs: translated_response,
        )

        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "What is Python?"}]},
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["object"] == "chat.completion"

    def test_usage_error_returns_usage_response(self, monkeypatch):
        """When check_usage returns a response, that response is returned."""
        self._patch_mongo(monkeypatch)

        internal_data = {"question": "Hi"}
        monkeypatch.setattr(
            "application.api.v1.routes.translate_request",
            lambda data, key: internal_data,
        )

        mock_processor = MagicMock()
        mock_processor.decoded_token = {"sub": "user-1"}
        mock_processor.agent_config = {"user_api_key": "key"}
        mock_processor.build_agent.return_value = MagicMock()

        monkeypatch.setattr(
            "application.api.v1.routes.StreamProcessor",
            lambda data, token: mock_processor,
        )

        app = _build_app()

        # Build the limit_resp inside an app context so Flask is available
        with app.app_context():
            from flask import make_response, jsonify
            limit_resp = make_response(
                jsonify({"success": False, "message": "Usage limit exceeded"}), 429
            )

        mock_helper = MagicMock()
        mock_helper.check_usage.return_value = limit_resp
        monkeypatch.setattr(
            "application.api.v1.routes._V1AnswerHelper",
            lambda: mock_helper,
        )

        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 429

    def test_value_error_returns_400(self, monkeypatch):
        """ValueError during processing returns 400."""
        self._patch_mongo(monkeypatch)

        internal_data = {"question": "Hi"}
        monkeypatch.setattr(
            "application.api.v1.routes.translate_request",
            lambda data, key: internal_data,
        )

        def _raise(data, token):
            raise ValueError("bad input")

        monkeypatch.setattr(
            "application.api.v1.routes.StreamProcessor",
            _raise,
        )

        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["type"] == "invalid_request"

    def test_generic_exception_returns_500(self, monkeypatch):
        """Unexpected Exception returns 500."""
        self._patch_mongo(monkeypatch)

        internal_data = {"question": "Hi"}
        monkeypatch.setattr(
            "application.api.v1.routes.translate_request",
            lambda data, key: internal_data,
        )

        def _raise(data, token):
            raise RuntimeError("db exploded")

        monkeypatch.setattr(
            "application.api.v1.routes.StreamProcessor",
            _raise,
        )

        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 500
        assert resp.get_json()["error"]["type"] == "server_error"

    def test_tool_actions_missing_conversation_id_returns_400(self, monkeypatch):
        """Continuation mode without conversation_id returns 400."""
        self._patch_mongo(monkeypatch)

        internal_data = {"tool_actions": [{"id": "t1", "result": "ok"}]}
        monkeypatch.setattr(
            "application.api.v1.routes.translate_request",
            lambda data, key: internal_data,
        )

        mock_processor = MagicMock()
        mock_processor.decoded_token = {"sub": "user-1"}
        mock_processor.agent_config = {"user_api_key": None}

        monkeypatch.setattr(
            "application.api.v1.routes.StreamProcessor",
            lambda data, token: mock_processor,
        )

        mock_helper = MagicMock()
        mock_helper.check_usage.return_value = None
        monkeypatch.setattr(
            "application.api.v1.routes._V1AnswerHelper",
            lambda: mock_helper,
        )

        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "continue"}]},
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 400

    def test_non_stream_error_response(self, monkeypatch):
        """When process_response_stream returns an error, return 500."""
        self._patch_mongo(monkeypatch)

        internal_data = {"question": "Hi"}
        monkeypatch.setattr(
            "application.api.v1.routes.translate_request",
            lambda data, key: internal_data,
        )

        mock_processor = MagicMock()
        mock_processor.decoded_token = {"sub": "user-1"}
        mock_processor.agent_config = {"user_api_key": None}
        mock_processor.conversation_id = None
        mock_processor.agent_id = "a"
        mock_processor.model_id = None
        mock_processor.build_agent.return_value = MagicMock()

        monkeypatch.setattr(
            "application.api.v1.routes.StreamProcessor",
            lambda data, token: mock_processor,
        )

        mock_helper = MagicMock()
        mock_helper.check_usage.return_value = None
        mock_helper.process_response_stream.return_value = {
            "conversation_id": None,
            "answer": None,
            "sources": None,
            "tool_calls": [],
            "thought": None,
            "error": "Something went wrong",
            "extra": None,
        }
        monkeypatch.setattr(
            "application.api.v1.routes._V1AnswerHelper",
            lambda: mock_helper,
        )

        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 500

    def test_stream_response_returns_event_stream(self, monkeypatch):
        """Streaming request returns text/event-stream content type."""
        self._patch_mongo(monkeypatch)

        internal_data = {"question": "Hi", "stream": True}
        monkeypatch.setattr(
            "application.api.v1.routes.translate_request",
            lambda data, key: internal_data,
        )

        mock_processor = MagicMock()
        mock_processor.decoded_token = {"sub": "user-1"}
        mock_processor.agent_config = {"user_api_key": None}
        mock_processor.conversation_id = None
        mock_processor.agent_id = "a"
        mock_processor.model_id = None
        mock_processor.build_agent.return_value = MagicMock()

        monkeypatch.setattr(
            "application.api.v1.routes.StreamProcessor",
            lambda data, token: mock_processor,
        )

        mock_helper = MagicMock()
        mock_helper.check_usage.return_value = None
        mock_helper.complete_stream.return_value = iter([
            'data: {"type": "id", "id": "conv-1"}',
            'data: {"type": "answer", "answer": "Hello"}',
        ])
        monkeypatch.setattr(
            "application.api.v1.routes._V1AnswerHelper",
            lambda: mock_helper,
        )

        monkeypatch.setattr(
            "application.api.v1.routes.translate_stream_event",
            lambda event, cid, model: [f"data: {json.dumps({'delta': event})}\n\n"],
        )

        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}], "stream": True},
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type

    def test_no_decoded_token_returns_401(self, monkeypatch):
        """When processor.decoded_token is None/falsy, return 401."""
        self._patch_mongo(monkeypatch)

        internal_data = {"question": "Hi"}
        monkeypatch.setattr(
            "application.api.v1.routes.translate_request",
            lambda data, key: internal_data,
        )

        mock_processor = MagicMock()
        mock_processor.decoded_token = None  # No token
        mock_processor.agent_config = {"user_api_key": None}
        mock_processor.build_agent.return_value = MagicMock()

        monkeypatch.setattr(
            "application.api.v1.routes.StreamProcessor",
            lambda data, token: mock_processor,
        )

        mock_helper = MagicMock()
        mock_helper.check_usage.return_value = None
        monkeypatch.setattr(
            "application.api.v1.routes._V1AnswerHelper",
            lambda: mock_helper,
        )

        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}]},
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 401

    def test_tool_actions_continuation_with_conversation_id(self, monkeypatch):
        """Cover lines 108-123: tool_actions continuation path with conversation_id."""
        self._patch_mongo(monkeypatch)

        tool_actions = [{"id": "t1", "result": "done"}]
        internal_data = {
            "tool_actions": tool_actions,
            "conversation_id": "conv-existing",
        }
        monkeypatch.setattr(
            "application.api.v1.routes.translate_request",
            lambda data, key: internal_data,
        )

        mock_processor = MagicMock()
        mock_processor.decoded_token = {"sub": "user-1"}
        mock_processor.agent_config = {"user_api_key": None}
        mock_processor.conversation_id = "conv-existing"
        mock_processor.agent_id = "agent-1"
        mock_processor.model_id = None
        # resume_from_tool_actions returns 5-tuple
        mock_agent = MagicMock()
        mock_processor.resume_from_tool_actions.return_value = (
            mock_agent,
            [],      # messages
            {},      # tools_dict
            [],      # pending_tool_calls
            tool_actions,  # tool_actions
        )

        monkeypatch.setattr(
            "application.api.v1.routes.StreamProcessor",
            lambda data, token: mock_processor,
        )

        mock_helper = MagicMock()
        mock_helper.check_usage.return_value = None
        mock_helper.process_response_stream.return_value = {
            "conversation_id": "conv-existing",
            "answer": "Continuation answer",
            "sources": [],
            "tool_calls": [],
            "thought": "",
            "error": None,
            "extra": None,
        }
        monkeypatch.setattr(
            "application.api.v1.routes._V1AnswerHelper",
            lambda: mock_helper,
        )

        monkeypatch.setattr(
            "application.api.v1.routes.translate_response",
            lambda **kwargs: {"id": "chatcmpl-cont", "object": "chat.completion"},
        )

        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "continue"}]},
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 200

    def test_stream_response_skips_empty_lines_and_bad_json(self, monkeypatch):
        """Cover lines 217, 222-223: _stream_response skips blank lines and bad JSON."""
        self._patch_mongo(monkeypatch)

        internal_data = {"question": "Hi"}
        monkeypatch.setattr(
            "application.api.v1.routes.translate_request",
            lambda data, key: internal_data,
        )

        mock_processor = MagicMock()
        mock_processor.decoded_token = {"sub": "user-1"}
        mock_processor.agent_config = {"user_api_key": None}
        mock_processor.conversation_id = None
        mock_processor.agent_id = "a"
        mock_processor.model_id = None
        mock_processor.build_agent.return_value = MagicMock()

        monkeypatch.setattr(
            "application.api.v1.routes.StreamProcessor",
            lambda data, token: mock_processor,
        )

        mock_helper = MagicMock()
        mock_helper.check_usage.return_value = None
        mock_helper.complete_stream.return_value = iter([
            "",                               # empty line — should be skipped
            "   ",                            # whitespace-only — should be skipped
            "data: not valid json{{{",        # bad JSON — should be skipped
            'data: {"type": "answer", "answer": "Hi"}',  # valid
        ])
        monkeypatch.setattr(
            "application.api.v1.routes._V1AnswerHelper",
            lambda: mock_helper,
        )

        call_count = {"n": 0}

        def fake_translate(event, cid, model):
            call_count["n"] += 1
            return [f"data: {json.dumps(event)}\n\n"]

        monkeypatch.setattr(
            "application.api.v1.routes.translate_stream_event",
            fake_translate,
        )

        app = _build_app()
        with app.test_client() as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hi"}], "stream": True},
                headers={"Authorization": "Bearer key-1"},
            )
        assert resp.status_code == 200
        # Only 1 valid event should have been translated
        assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# /v1/models — additional edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListModelsExtra:
    def test_missing_auth_header_returns_401(self):
        app = _build_app()
        with app.test_client() as client:
            resp = client.get("/v1/models")
        assert resp.status_code == 401
        assert resp.get_json()["error"]["type"] == "auth_error"

    def test_mongo_exception_returns_500(self, monkeypatch):
        def _raise():
            raise RuntimeError("mongo down")

        monkeypatch.setattr("application.api.v1.routes.MongoDB.get_client", _raise)
        monkeypatch.setattr("application.api.v1.routes.settings.MONGO_DB_NAME", "testdb")

        app = _build_app()
        with app.test_client() as client:
            resp = client.get("/v1/models", headers={"Authorization": "Bearer key-1"})
        assert resp.status_code == 500
        assert resp.get_json()["error"]["type"] == "server_error"

    def test_models_include_created_timestamp_from_date(self, monkeypatch):
        """Cover the branch where createdAt is set."""
        import datetime

        created_dt = datetime.datetime(2024, 1, 15, 12, 0, 0)
        docs = [
            {
                "_id": "agent-1",
                "key": "key-1",
                "user": "user-1",
                "name": "Agent One",
                "createdAt": created_dt,
            }
        ]
        fake_mongo = {"testdb": {"agents": _FakeCollection(docs)}}
        monkeypatch.setattr("application.api.v1.routes.MongoDB.get_client", lambda: fake_mongo)
        monkeypatch.setattr("application.api.v1.routes.settings.MONGO_DB_NAME", "testdb")

        app = _build_app()
        with app.test_client() as client:
            resp = client.get("/v1/models", headers={"Authorization": "Bearer key-1"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"][0]["created"] == int(created_dt.timestamp())
