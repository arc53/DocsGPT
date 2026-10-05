import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@contextmanager
def _patch_conversations_db(conn):
    @contextmanager
    def _yield_conn():
        yield conn

    with patch(
        "docsgpt.api.user.conversations.routes.db_session", _yield_conn
    ), patch(
        "docsgpt.api.user.conversations.routes.db_readonly", _yield_conn
    ):
        yield


def _seed_conversation(pg_conn, user_id, name="Test Conv"):
    """Create a conversation and return its PG uuid id as str."""
    from docsgpt.storage.db.repositories.conversations import (
        ConversationsRepository,
    )
    repo = ConversationsRepository(pg_conn)
    conv = repo.create(user_id, name=name)
    return str(conv["id"])


@pytest.mark.unit
class TestDeleteConversation:
    pass

    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.conversations.routes import DeleteConversation

        with app.test_request_context("/api/delete_conversation?id=abc"):
            from flask import request

            request.decoded_token = None
            response = DeleteConversation().post()

        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from docsgpt.api.user.conversations.routes import DeleteConversation

        with app.test_request_context("/api/delete_conversation"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = DeleteConversation().post()

        assert response.status_code == 400


@pytest.mark.unit
class TestDeleteAllConversations:
    pass

    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.conversations.routes import DeleteAllConversations

        with app.test_request_context("/api/delete_all_conversations"):
            from flask import request

            request.decoded_token = None
            response = DeleteAllConversations().get()

        assert response.status_code == 401


@pytest.mark.unit
class TestGetConversations:
    pass

    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.conversations.routes import GetConversations

        with app.test_request_context("/api/get_conversations"):
            from flask import request

            request.decoded_token = None
            response = GetConversations().get()

        assert response.status_code == 401


@pytest.mark.unit
class TestGetSingleConversation:
    pass

    def test_returns_400_missing_id(self, app):
        from docsgpt.api.user.conversations.routes import GetSingleConversation

        with app.test_request_context("/api/get_single_conversation"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = GetSingleConversation().get()

        assert response.status_code == 400



@pytest.mark.unit
class TestUpdateConversationName:
    pass

    def test_returns_400_missing_fields(self, app):
        from docsgpt.api.user.conversations.routes import UpdateConversationName

        with app.test_request_context(
            "/api/update_conversation_name",
            method="POST",
            json={"id": str(uuid.uuid4().hex[:24])},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = UpdateConversationName().post()

        assert response.status_code == 400


@pytest.mark.unit
class TestSubmitFeedback:
    pass

    def test_returns_400_missing_fields(self, app):
        from docsgpt.api.user.conversations.routes import SubmitFeedback

        with app.test_request_context(
            "/api/feedback",
            method="POST",
            json={"feedback": "LIKE"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = SubmitFeedback().post()

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Happy-path tests exercising real PG via the ephemeral pg_conn fixture.
# ---------------------------------------------------------------------------


class TestDeleteConversationHappy:
    def test_deletes_existing_conversation(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import DeleteConversation
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "user-del"
        conv_id = _seed_conversation(pg_conn, user)

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/delete_conversation?id={conv_id}"
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = DeleteConversation().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        # Gone
        assert ConversationsRepository(pg_conn).get_any(conv_id, user) is None

    def test_delete_nonexistent_still_returns_200(self, app, pg_conn):
        """get_any returns None, so delete is a no-op but endpoint succeeds."""
        from docsgpt.api.user.conversations.routes import DeleteConversation

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/delete_conversation?id={uuid.uuid4()}"
        ):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = DeleteConversation().post()

        assert response.status_code == 200

    def test_db_error_returns_400(self, app):
        from docsgpt.api.user.conversations.routes import DeleteConversation

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.conversations.routes.db_session", _broken
        ), app.test_request_context("/api/delete_conversation?id=abc"):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = DeleteConversation().post()

        assert response.status_code == 400


class TestDeleteAllConversationsHappy:
    def test_deletes_all_conversations(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import (
            DeleteAllConversations,
        )
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "user-delall"
        _seed_conversation(pg_conn, user, name="a")
        _seed_conversation(pg_conn, user, name="b")

        with _patch_conversations_db(pg_conn), app.test_request_context(
            "/api/delete_all_conversations"
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = DeleteAllConversations().get()

        assert response.status_code == 200
        assert ConversationsRepository(pg_conn).list_for_user(user) == []

    def test_db_error_returns_400(self, app):
        from docsgpt.api.user.conversations.routes import (
            DeleteAllConversations,
        )

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.conversations.routes.db_session", _broken
        ), app.test_request_context("/api/delete_all_conversations"):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = DeleteAllConversations().get()

        assert response.status_code == 400


class TestGetConversationsHappy:
    def test_returns_list_of_conversations(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import GetConversations

        user = "user-list"
        c1 = _seed_conversation(pg_conn, user, name="one")
        c2 = _seed_conversation(pg_conn, user, name="two")

        with _patch_conversations_db(pg_conn), app.test_request_context(
            "/api/get_conversations"
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = GetConversations().get()

        assert response.status_code == 200
        ids = {c["id"] for c in response.json}
        assert c1 in ids and c2 in ids
        # agent_id, is_shared_usage, shared_token keys present
        for c in response.json:
            assert "agent_id" in c
            assert "is_shared_usage" in c
            assert "shared_token" in c

    def test_db_error_returns_400(self, app):
        from docsgpt.api.user.conversations.routes import GetConversations

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.conversations.routes.db_readonly", _broken
        ), app.test_request_context("/api/get_conversations"):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = GetConversations().get()

        assert response.status_code == 400


class TestGetSingleConversationHappy:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.conversations.routes import (
            GetSingleConversation,
        )

        with app.test_request_context("/api/get_single_conversation?id=x"):
            from flask import request

            request.decoded_token = None
            response = GetSingleConversation().get()

        assert response.status_code == 401

    def test_returns_404_not_found(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import (
            GetSingleConversation,
        )

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/get_single_conversation?id={uuid.uuid4()}"
        ):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = GetSingleConversation().get()

        assert response.status_code == 404

    def test_returns_conversation_with_messages(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import (
            GetSingleConversation,
        )
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "user-get"
        conv_id = _seed_conversation(pg_conn, user, name="chat")
        # Append a message
        ConversationsRepository(pg_conn).append_message(
            conv_id,
            {
                "prompt": "hi",
                "response": "hello",
                "thought": None,
                "sources": [],
                "tool_calls": [],
                "timestamp": None,
                "model_id": None,
            },
        )

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/get_single_conversation?id={conv_id}"
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = GetSingleConversation().get()

        assert response.status_code == 200
        data = response.json
        assert isinstance(data["queries"], list)
        assert data["queries"][0]["prompt"] == "hi"
        assert data["queries"][0]["response"] == "hello"

    def test_returns_the_saved_segment_order(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import (
            GetSingleConversation,
        )
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "user-seg"
        conv_id = _seed_conversation(pg_conn, user, name="seg")
        order = [
            {"kind": "text", "length": 3},
            {"kind": "tool", "call_id": "c1"},
            {"kind": "text", "length": 2},
        ]
        repo = ConversationsRepository(pg_conn)
        repo.append_message(conv_id, {"prompt": "p", "response": "abcde", "metadata": {"segments": order}})
        repo.append_message(conv_id, {"prompt": "p2", "response": "r"})

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/get_single_conversation?id={conv_id}"
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = GetSingleConversation().get()

        queries = response.json["queries"]
        assert queries[0]["segments"] == order
        assert queries[1]["segments"] is None

    def test_returns_message_with_dict_feedback(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import (
            GetSingleConversation,
        )
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "user-fb"
        conv_id = _seed_conversation(pg_conn, user, name="fb")
        repo = ConversationsRepository(pg_conn)
        repo.append_message(conv_id, {"prompt": "p", "response": "r"})
        repo.set_feedback(
            conv_id, 0, {"text": "like", "timestamp": "2024-01-01T00:00:00Z"}
        )

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/get_single_conversation?id={conv_id}"
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = GetSingleConversation().get()

        assert response.status_code == 200
        q = response.json["queries"][0]
        assert q["feedback"] == "like"
        assert q["feedback_timestamp"] == "2024-01-01T00:00:00Z"

    def test_db_error_returns_400(self, app):
        from docsgpt.api.user.conversations.routes import (
            GetSingleConversation,
        )

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.conversations.routes.db_readonly", _broken
        ), app.test_request_context("/api/get_single_conversation?id=abc"):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = GetSingleConversation().get()

        assert response.status_code == 400


@pytest.mark.unit
class TestGetMessageTail:
    """Tail-poll endpoint (``GET /api/messages/<id>/tail``) used by the
    frontend to recover a placeholder/streaming row after a refresh.
    """

    def _seed_in_flight_message(self, pg_conn, owner_user_id):
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        conv_id = _seed_conversation(pg_conn, owner_user_id, name="streaming chat")
        repo = ConversationsRepository(pg_conn)
        msg = repo.reserve_message(
            conv_id,
            prompt="what's happening?",
            placeholder_response=(
                "Response was terminated prior to completion, try regenerating."
            ),
            request_id=str(uuid.uuid4()),
            status="streaming",
        )
        return conv_id, str(msg["id"])

    def test_owner_can_tail(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import GetMessageTail

        owner = "user-owner"
        _, msg_id = self._seed_in_flight_message(pg_conn, owner)

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/messages/{msg_id}/tail"
        ):
            from flask import request

            request.decoded_token = {"sub": owner}
            response = GetMessageTail().get(msg_id)

        assert response.status_code == 200
        assert response.json["status"] == "streaming"
        assert response.json["message_id"] == msg_id

    def test_failed_tail_carries_the_error_code(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import GetMessageTail
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        owner = "user-owner-failed"
        _, msg_id = self._seed_in_flight_message(pg_conn, owner)
        ConversationsRepository(pg_conn).update_message_by_id(
            msg_id,
            {
                "status": "failed",
                "metadata": {
                    "error": "This message is too large for the model.",
                    "error_code": "context_length_exceeded",
                    "error_params": {"needed_tokens": 300000, "available_tokens": 200000},
                },
            },
        )

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/messages/{msg_id}/tail"
        ):
            from flask import request

            request.decoded_token = {"sub": owner}
            response = GetMessageTail().get(msg_id)

        assert response.status_code == 200
        assert response.json["status"] == "failed"
        assert response.json["error"] == "This message is too large for the model."
        assert response.json["error_code"] == "context_length_exceeded"
        assert response.json["error_params"] == {"needed_tokens": 300000, "available_tokens": 200000}

    def test_shared_user_can_tail(self, app, pg_conn):
        """A user in ``conversations.shared_with`` must be able to tail
        an in-flight placeholder. Without the shared-with predicate
        here, ``get_single_conversation`` lets them load the row but
        the tail-poll silently 404s and the in-flight bubble never
        resolves on the shared user's side.
        """
        from docsgpt.api.user.conversations.routes import GetMessageTail
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        owner = "user-owner-shared"
        shared_user = "user-shared"
        conv_id, msg_id = self._seed_in_flight_message(pg_conn, owner)
        ConversationsRepository(pg_conn).add_shared_user(conv_id, shared_user)

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/messages/{msg_id}/tail"
        ):
            from flask import request

            request.decoded_token = {"sub": shared_user}
            response = GetMessageTail().get(msg_id)

        assert response.status_code == 200
        assert response.json["message_id"] == msg_id

    def test_non_member_gets_404(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import GetMessageTail

        owner = "user-owner-private"
        intruder = "user-intruder"
        _, msg_id = self._seed_in_flight_message(pg_conn, owner)

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/messages/{msg_id}/tail"
        ):
            from flask import request

            request.decoded_token = {"sub": intruder}
            response = GetMessageTail().get(msg_id)

        assert response.status_code == 404

    def test_streaming_row_returns_partial_from_journal(self, app, pg_conn):
        """Mid-stream rows must rebuild from message_events, not return the placeholder."""
        from docsgpt.api.user.conversations.routes import GetMessageTail
        from docsgpt.storage.db.repositories.message_events import (
            MessageEventsRepository,
        )

        owner = "user-tail-partial"
        _, msg_id = self._seed_in_flight_message(pg_conn, owner)
        events_repo = MessageEventsRepository(pg_conn)
        events_repo.record(msg_id, 0, "message_id", {"type": "message_id"})
        events_repo.record(msg_id, 1, "answer", {"type": "answer", "answer": "Hello"})
        events_repo.record(msg_id, 2, "answer", {"type": "answer", "answer": ", world"})
        events_repo.record(
            msg_id, 3, "source", {"type": "source", "source": [{"id": "s1"}]}
        )

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/messages/{msg_id}/tail"
        ):
            from flask import request

            request.decoded_token = {"sub": owner}
            response = GetMessageTail().get(msg_id)

        assert response.status_code == 200
        assert response.json["status"] == "streaming"
        assert response.json["response"] == "Hello, world"
        assert response.json["sources"] == [{"id": "s1"}]
        assert "terminated prior to completion" not in (
            response.json["response"] or ""
        )

    def test_streaming_row_with_empty_journal_returns_empty_response(
        self, app, pg_conn
    ):
        """Empty journal returns empty response, not the placeholder."""
        from docsgpt.api.user.conversations.routes import GetMessageTail

        owner = "user-tail-empty"
        _, msg_id = self._seed_in_flight_message(pg_conn, owner)

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/messages/{msg_id}/tail"
        ):
            from flask import request

            request.decoded_token = {"sub": owner}
            response = GetMessageTail().get(msg_id)

        assert response.status_code == 200
        assert response.json["status"] == "streaming"
        assert response.json["response"] == ""


class TestUpdateConversationNameHappy:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.conversations.routes import (
            UpdateConversationName,
        )

        with app.test_request_context(
            "/api/update_conversation_name",
            method="POST",
            json={"id": "x", "name": "n"},
        ):
            from flask import request

            request.decoded_token = None
            response = UpdateConversationName().post()

        assert response.status_code == 401

    def test_renames_conversation(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import (
            UpdateConversationName,
        )
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "user-rename"
        conv_id = _seed_conversation(pg_conn, user, name="old")

        with _patch_conversations_db(pg_conn), app.test_request_context(
            "/api/update_conversation_name",
            method="POST",
            json={"id": conv_id, "name": "new"},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = UpdateConversationName().post()

        assert response.status_code == 200
        got = ConversationsRepository(pg_conn).get_any(conv_id, user)
        assert got["name"] == "new"

    def test_rename_nonexistent_still_returns_200(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import (
            UpdateConversationName,
        )

        with _patch_conversations_db(pg_conn), app.test_request_context(
            "/api/update_conversation_name",
            method="POST",
            json={"id": str(uuid.uuid4()), "name": "n"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = UpdateConversationName().post()

        assert response.status_code == 200

    def test_db_error_returns_400(self, app):
        from docsgpt.api.user.conversations.routes import (
            UpdateConversationName,
        )

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.conversations.routes.db_session", _broken
        ), app.test_request_context(
            "/api/update_conversation_name",
            method="POST",
            json={"id": "x", "name": "n"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = UpdateConversationName().post()

        assert response.status_code == 400


class TestSubmitFeedbackHappy:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.conversations.routes import SubmitFeedback

        with app.test_request_context(
            "/api/feedback",
            method="POST",
            json={
                "feedback": "like",
                "question_index": 0,
                "conversation_id": "x",
            },
        ):
            from flask import request

            request.decoded_token = None
            response = SubmitFeedback().post()

        assert response.status_code == 401

    def test_submits_feedback(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import SubmitFeedback
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "user-fb1"
        conv_id = _seed_conversation(pg_conn, user, name="fb")
        ConversationsRepository(pg_conn).append_message(
            conv_id, {"prompt": "p", "response": "r"}
        )

        with _patch_conversations_db(pg_conn), app.test_request_context(
            "/api/feedback",
            method="POST",
            json={
                "feedback": "LIKE",  # uppercase normalized to lowercase
                "question_index": 0,
                "conversation_id": conv_id,
            },
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = SubmitFeedback().post()

        assert response.status_code == 200
        msgs = ConversationsRepository(pg_conn).get_messages(conv_id)
        fb = msgs[0].get("feedback")
        assert fb and fb.get("text") == "like"

    def test_none_feedback_allowed(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import SubmitFeedback
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "user-fb-none"
        conv_id = _seed_conversation(pg_conn, user)
        ConversationsRepository(pg_conn).append_message(
            conv_id, {"prompt": "p", "response": "r"}
        )

        with _patch_conversations_db(pg_conn), app.test_request_context(
            "/api/feedback",
            method="POST",
            json={
                "feedback": None,
                "question_index": 0,
                "conversation_id": conv_id,
            },
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = SubmitFeedback().post()

        assert response.status_code == 200

    def test_returns_404_for_missing_conversation(self, app, pg_conn):
        from docsgpt.api.user.conversations.routes import SubmitFeedback

        with _patch_conversations_db(pg_conn), app.test_request_context(
            "/api/feedback",
            method="POST",
            json={
                "feedback": "like",
                "question_index": 0,
                "conversation_id": str(uuid.uuid4()),
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = SubmitFeedback().post()

        assert response.status_code == 404

    def test_db_error_returns_400(self, app):
        from docsgpt.api.user.conversations.routes import SubmitFeedback

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.conversations.routes.db_session", _broken
        ), app.test_request_context(
            "/api/feedback",
            method="POST",
            json={
                "feedback": "like",
                "question_index": 0,
                "conversation_id": "x",
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = SubmitFeedback().post()

        assert response.status_code == 400


@pytest.mark.unit
class TestSubmitFeedbackWithApiKey:
    """api_key callers carry no JWT."""

    def _seed_agent_with_key(self, pg_conn, owner, key):
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        return AgentsRepository(pg_conn).create(owner, "widget", "published", key=key)

    def _post(self, app, pg_conn, payload):
        from docsgpt.api.user.conversations.routes import SubmitFeedback

        with _patch_conversations_db(pg_conn), app.test_request_context("/api/feedback", method="POST", json=payload):
            from flask import request

            request.decoded_token = None
            return SubmitFeedback().post()

    def test_valid_key_rates_its_own_conversation(self, app, pg_conn):
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        owner, key = "owner-fb-key", "agent-key-ok"
        self._seed_agent_with_key(pg_conn, owner, key)
        repo = ConversationsRepository(pg_conn)
        conv_id = str(repo.create(owner, name="via widget", api_key=key)["id"])
        repo.append_message(conv_id, {"prompt": "p", "response": "r"})

        response = self._post(
            app,
            pg_conn,
            {
                "feedback": "LIKE",
                "question_index": 0,
                "conversation_id": conv_id,
                "api_key": key,
            },
        )

        assert response.status_code == 200
        fb = repo.get_messages(conv_id)[0].get("feedback")
        assert fb and fb.get("text") == "like"

    def test_key_cannot_rate_owner_conversation_it_did_not_create(self, app, pg_conn):
        from docsgpt.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        owner, key = "owner-fb-scope", "agent-key-scope"
        self._seed_agent_with_key(pg_conn, owner, key)
        # Owner's conversation, not created with the key.
        conv_id = _seed_conversation(pg_conn, owner, name="owner private")
        ConversationsRepository(pg_conn).append_message(conv_id, {"prompt": "p", "response": "r"})

        response = self._post(
            app,
            pg_conn,
            {
                "feedback": "LIKE",
                "question_index": 0,
                "conversation_id": conv_id,
                "api_key": key,
            },
        )

        assert response.status_code == 404

    def test_unknown_key_is_unauthorized(self, app, pg_conn):
        conv_id = _seed_conversation(pg_conn, "owner-fb-bad")

        response = self._post(
            app,
            pg_conn,
            {
                "feedback": "LIKE",
                "question_index": 0,
                "conversation_id": conv_id,
                "api_key": "no-such-key",
            },
        )

        assert response.status_code == 401


def _call_get_conversations(app, pg_conn, user, query=""):
    from docsgpt.api.user.conversations.routes import GetConversations

    with _patch_conversations_db(pg_conn), app.test_request_context(
        f"/api/get_conversations{query}"
    ):
        from flask import request

        request.decoded_token = {"sub": user}
        response = GetConversations().get()
    assert response.status_code == 200
    assert isinstance(response.json, list)
    return response.json


def _seed_dated(pg_conn, user, count, dates):
    """Seed ``count`` conversations, the i-th dated ``dates(i)``."""
    from sqlalchemy import text

    ids = []
    for i in range(count):
        cid = _seed_conversation(pg_conn, user, name=f"c{i}")
        pg_conn.execute(
            text("UPDATE conversations SET date = :d WHERE id = CAST(:id AS uuid)"),
            {"d": dates(i), "id": cid},
        )
        ids.append(cid)
    return ids


def _expected_order(pg_conn, user):
    from sqlalchemy import text

    rows = pg_conn.execute(
        text(
            "SELECT id::text FROM conversations WHERE user_id = :u "
            "AND visibility = 'listed' ORDER BY date DESC, id DESC"
        ),
        {"u": user},
    ).fetchall()
    return [r[0] for r in rows]


class TestGetConversationsPaging:
    def test_default_returns_30_newest_with_date(self, app, pg_conn):
        import datetime as dt

        user = "user-page-default"
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        _seed_dated(pg_conn, user, 35, lambda i: base + dt.timedelta(minutes=i))

        items = _call_get_conversations(app, pg_conn, user)

        assert [c["id"] for c in items] == _expected_order(pg_conn, user)[:30]
        assert set(items[0]) == {
            "id", "name", "agent_id", "is_shared_usage", "shared_token", "date",
        }
        parsed = dt.datetime.fromisoformat(items[0]["date"])
        assert parsed == base + dt.timedelta(minutes=34)

    def test_limit_is_clamped(self, app, pg_conn):
        import datetime as dt

        user = "user-page-clamp"
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        _seed_dated(pg_conn, user, 105, lambda i: base + dt.timedelta(seconds=i))

        assert len(_call_get_conversations(app, pg_conn, user, "?limit=5")) == 5
        assert len(_call_get_conversations(app, pg_conn, user, "?limit=0")) == 1
        assert len(_call_get_conversations(app, pg_conn, user, "?limit=-3")) == 1
        assert len(_call_get_conversations(app, pg_conn, user, "?limit=500")) == 100

    def test_pages_through_all_exactly_once_with_equal_timestamps(self, app, pg_conn):
        import datetime as dt
        from urllib.parse import urlencode

        user = "user-page-walk"
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        # 70 rows, many sharing a timestamp (groups of 7) so page
        # boundaries land inside a tie group.
        _seed_dated(pg_conn, user, 70, lambda i: base + dt.timedelta(minutes=i // 7))
        hidden = _seed_conversation(pg_conn, user, name="hidden")
        from sqlalchemy import text

        pg_conn.execute(
            text("UPDATE conversations SET visibility = 'hidden' WHERE id = CAST(:id AS uuid)"),
            {"id": hidden},
        )

        seen = []
        page = _call_get_conversations(app, pg_conn, user)
        assert len(page) == 30
        while page:
            seen.extend(c["id"] for c in page)
            last = page[-1]
            query = "?" + urlencode(
                {"limit": 30, "before": last["date"], "before_id": last["id"]}
            )
            page = _call_get_conversations(app, pg_conn, user, query)

        assert seen == _expected_order(pg_conn, user)
        assert len(seen) == len(set(seen)) == 70
        assert hidden not in seen

    def test_accepts_z_suffix_cursor(self, app, pg_conn):
        import datetime as dt

        user = "user-page-z"
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        ids = _seed_dated(pg_conn, user, 3, lambda i: base + dt.timedelta(minutes=i))

        items = _call_get_conversations(
            app, pg_conn, user,
            f"?before=2026-01-01T00:02:00Z&before_id={ids[2]}",
        )
        assert [c["id"] for c in items] == [ids[1], ids[0]]

    @pytest.mark.parametrize(
        "query",
        [
            "?limit=abc",
            "?before=not-a-date&before_id=00000000-0000-0000-0000-000000000000",
            "?before=2026-01-01T00:00:00Z&before_id=not-a-uuid",
            "?before=2026-01-01T00:00:00Z",
            "?before_id=00000000-0000-0000-0000-000000000000",
            "?before=&before_id=",
            "?limit=&before=99999-99-99",
        ],
    )
    def test_bad_params_are_ignored(self, app, pg_conn, query):
        import datetime as dt

        user = "user-page-bad"
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        _seed_dated(pg_conn, user, 32, lambda i: base + dt.timedelta(minutes=i))

        items = _call_get_conversations(app, pg_conn, user, query)
        assert [c["id"] for c in items] == _expected_order(pg_conn, user)[:30]
