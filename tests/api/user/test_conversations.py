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
        "application.api.user.conversations.routes.db_session", _yield_conn
    ), patch(
        "application.api.user.conversations.routes.db_readonly", _yield_conn
    ):
        yield


def _seed_conversation(pg_conn, user_id, name="Test Conv"):
    """Create a conversation and return its PG uuid id as str."""
    from application.storage.db.repositories.conversations import (
        ConversationsRepository,
    )
    repo = ConversationsRepository(pg_conn)
    conv = repo.create(user_id, name=name)
    return str(conv["id"])


@pytest.mark.unit
class TestDeleteConversation:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.conversations.routes import DeleteConversation

        with app.test_request_context("/api/delete_conversation?id=abc"):
            from flask import request

            request.decoded_token = None
            response = DeleteConversation().post()

        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.conversations.routes import DeleteConversation

        with app.test_request_context("/api/delete_conversation"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = DeleteConversation().post()

        assert response.status_code == 400


@pytest.mark.unit
class TestDeleteAllConversations:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.conversations.routes import DeleteAllConversations

        with app.test_request_context("/api/delete_all_conversations"):
            from flask import request

            request.decoded_token = None
            response = DeleteAllConversations().get()

        assert response.status_code == 401


@pytest.mark.unit
class TestGetConversations:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.conversations.routes import GetConversations

        with app.test_request_context("/api/get_conversations"):
            from flask import request

            request.decoded_token = None
            response = GetConversations().get()

        assert response.status_code == 401


@pytest.mark.unit
class TestGetSingleConversation:
    pass

    def test_returns_400_missing_id(self, app):
        from application.api.user.conversations.routes import GetSingleConversation

        with app.test_request_context("/api/get_single_conversation"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = GetSingleConversation().get()

        assert response.status_code == 400



@pytest.mark.unit
class TestUpdateConversationName:
    pass

    def test_returns_400_missing_fields(self, app):
        from application.api.user.conversations.routes import UpdateConversationName

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
        from application.api.user.conversations.routes import SubmitFeedback

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
        from application.api.user.conversations.routes import DeleteConversation
        from application.storage.db.repositories.conversations import (
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
        from application.api.user.conversations.routes import DeleteConversation

        with _patch_conversations_db(pg_conn), app.test_request_context(
            f"/api/delete_conversation?id={uuid.uuid4()}"
        ):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = DeleteConversation().post()

        assert response.status_code == 200

    def test_db_error_returns_400(self, app):
        from application.api.user.conversations.routes import DeleteConversation

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.conversations.routes.db_session", _broken
        ), app.test_request_context("/api/delete_conversation?id=abc"):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = DeleteConversation().post()

        assert response.status_code == 400


class TestDeleteAllConversationsHappy:
    def test_deletes_all_conversations(self, app, pg_conn):
        from application.api.user.conversations.routes import (
            DeleteAllConversations,
        )
        from application.storage.db.repositories.conversations import (
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
        from application.api.user.conversations.routes import (
            DeleteAllConversations,
        )

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.conversations.routes.db_session", _broken
        ), app.test_request_context("/api/delete_all_conversations"):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = DeleteAllConversations().get()

        assert response.status_code == 400


class TestGetConversationsHappy:
    def test_returns_list_of_conversations(self, app, pg_conn):
        from application.api.user.conversations.routes import GetConversations

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
        from application.api.user.conversations.routes import GetConversations

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.conversations.routes.db_readonly", _broken
        ), app.test_request_context("/api/get_conversations"):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = GetConversations().get()

        assert response.status_code == 400


class TestGetSingleConversationHappy:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.conversations.routes import (
            GetSingleConversation,
        )

        with app.test_request_context("/api/get_single_conversation?id=x"):
            from flask import request

            request.decoded_token = None
            response = GetSingleConversation().get()

        assert response.status_code == 401

    def test_returns_404_not_found(self, app, pg_conn):
        from application.api.user.conversations.routes import (
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
        from application.api.user.conversations.routes import (
            GetSingleConversation,
        )
        from application.storage.db.repositories.conversations import (
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

    def test_returns_message_with_dict_feedback(self, app, pg_conn):
        from application.api.user.conversations.routes import (
            GetSingleConversation,
        )
        from application.storage.db.repositories.conversations import (
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
        from application.api.user.conversations.routes import (
            GetSingleConversation,
        )

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.conversations.routes.db_readonly", _broken
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
        from application.storage.db.repositories.conversations import (
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
        from application.api.user.conversations.routes import GetMessageTail

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

    def test_shared_user_can_tail(self, app, pg_conn):
        """A user in ``conversations.shared_with`` must be able to tail
        an in-flight placeholder. Without the shared-with predicate
        here, ``get_single_conversation`` lets them load the row but
        the tail-poll silently 404s and the in-flight bubble never
        resolves on the shared user's side.
        """
        from application.api.user.conversations.routes import GetMessageTail
        from application.storage.db.repositories.conversations import (
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
        from application.api.user.conversations.routes import GetMessageTail

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
        from application.api.user.conversations.routes import GetMessageTail
        from application.storage.db.repositories.message_events import (
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
        from application.api.user.conversations.routes import GetMessageTail

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
        from application.api.user.conversations.routes import (
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
        from application.api.user.conversations.routes import (
            UpdateConversationName,
        )
        from application.storage.db.repositories.conversations import (
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
        from application.api.user.conversations.routes import (
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
        from application.api.user.conversations.routes import (
            UpdateConversationName,
        )

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.conversations.routes.db_session", _broken
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
        from application.api.user.conversations.routes import SubmitFeedback

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
        from application.api.user.conversations.routes import SubmitFeedback
        from application.storage.db.repositories.conversations import (
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
        from application.api.user.conversations.routes import SubmitFeedback
        from application.storage.db.repositories.conversations import (
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
        from application.api.user.conversations.routes import SubmitFeedback

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
        from application.api.user.conversations.routes import SubmitFeedback

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.conversations.routes.db_session", _broken
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
