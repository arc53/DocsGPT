from unittest.mock import Mock, patch

import pytest
from bson import ObjectId
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@pytest.mark.unit
class TestDeleteConversation:

    def test_deletes_conversation(self, app):
        from application.api.user.conversations.routes import DeleteConversation

        conv_id = ObjectId()
        mock_collection = Mock()

        with patch(
            "application.api.user.conversations.routes.conversations_collection",
            mock_collection,
        ):
            with app.test_request_context(f"/api/delete_conversation?id={conv_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = DeleteConversation().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        mock_collection.delete_one.assert_called_once_with(
            {"_id": conv_id, "user": "user1"}
        )

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

    def test_deletes_all_for_user(self, app):
        from application.api.user.conversations.routes import DeleteAllConversations

        mock_collection = Mock()

        with patch(
            "application.api.user.conversations.routes.conversations_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/delete_all_conversations"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = DeleteAllConversations().get()

        assert response.status_code == 200
        mock_collection.delete_many.assert_called_once_with({"user": "user1"})

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.conversations.routes import DeleteAllConversations

        with app.test_request_context("/api/delete_all_conversations"):
            from flask import request

            request.decoded_token = None
            response = DeleteAllConversations().get()

        assert response.status_code == 401


@pytest.mark.unit
class TestGetConversations:

    def test_returns_conversations(self, app):
        from application.api.user.conversations.routes import GetConversations

        conv_id = ObjectId()
        mock_cursor = Mock()
        mock_cursor.sort.return_value.limit.return_value = [
            {
                "_id": conv_id,
                "name": "Test Chat",
                "agent_id": "agent1",
                "is_shared_usage": False,
            }
        ]
        mock_collection = Mock()
        mock_collection.find.return_value = mock_cursor

        with patch(
            "application.api.user.conversations.routes.conversations_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/get_conversations"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetConversations().get()

        assert response.status_code == 200
        data = response.json
        assert len(data) == 1
        assert data[0]["id"] == str(conv_id)
        assert data[0]["name"] == "Test Chat"

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.conversations.routes import GetConversations

        with app.test_request_context("/api/get_conversations"):
            from flask import request

            request.decoded_token = None
            response = GetConversations().get()

        assert response.status_code == 401


@pytest.mark.unit
class TestGetSingleConversation:

    def test_returns_conversation(self, app):
        from application.api.user.conversations.routes import GetSingleConversation

        conv_id = ObjectId()
        mock_conv_collection = Mock()
        mock_conv_collection.find_one.return_value = {
            "_id": conv_id,
            "name": "Chat",
            "queries": [{"prompt": "hi", "response": "hello"}],
            "agent_id": "agent1",
        }

        with patch(
            "application.api.user.conversations.routes.conversations_collection",
            mock_conv_collection,
        ):
            with app.test_request_context(
                f"/api/get_single_conversation?id={conv_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetSingleConversation().get()

        assert response.status_code == 200
        assert response.json["queries"] == [{"prompt": "hi", "response": "hello"}]
        assert response.json["agent_id"] == "agent1"

    def test_returns_404_not_found(self, app):
        from application.api.user.conversations.routes import GetSingleConversation

        mock_collection = Mock()
        mock_collection.find_one.return_value = None

        with patch(
            "application.api.user.conversations.routes.conversations_collection",
            mock_collection,
        ):
            with app.test_request_context(
                f"/api/get_single_conversation?id={ObjectId()}"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetSingleConversation().get()

        assert response.status_code == 404

    def test_returns_400_missing_id(self, app):
        from application.api.user.conversations.routes import GetSingleConversation

        with app.test_request_context("/api/get_single_conversation"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = GetSingleConversation().get()

        assert response.status_code == 400

    def test_resolves_attachments(self, app):
        from application.api.user.conversations.routes import GetSingleConversation

        conv_id = ObjectId()
        att_id = ObjectId()
        mock_conv_collection = Mock()
        mock_conv_collection.find_one.return_value = {
            "_id": conv_id,
            "name": "Chat",
            "queries": [
                {"prompt": "hi", "response": "hello", "attachments": [str(att_id)]}
            ],
        }
        mock_att_collection = Mock()
        mock_att_collection.find_one.return_value = {
            "_id": att_id,
            "filename": "doc.pdf",
        }

        with patch(
            "application.api.user.conversations.routes.conversations_collection",
            mock_conv_collection,
        ), patch(
            "application.api.user.conversations.routes.attachments_collection",
            mock_att_collection,
        ):
            with app.test_request_context(
                f"/api/get_single_conversation?id={conv_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetSingleConversation().get()

        assert response.status_code == 200
        attachments = response.json["queries"][0]["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["fileName"] == "doc.pdf"


@pytest.mark.unit
class TestUpdateConversationName:

    def test_updates_name(self, app):
        from application.api.user.conversations.routes import UpdateConversationName

        conv_id = ObjectId()
        mock_collection = Mock()

        with patch(
            "application.api.user.conversations.routes.conversations_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/update_conversation_name",
                method="POST",
                json={"id": str(conv_id), "name": "New Name"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateConversationName().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        mock_collection.update_one.assert_called_once()

    def test_returns_400_missing_fields(self, app):
        from application.api.user.conversations.routes import UpdateConversationName

        with app.test_request_context(
            "/api/update_conversation_name",
            method="POST",
            json={"id": str(ObjectId())},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = UpdateConversationName().post()

        assert response.status_code == 400


@pytest.mark.unit
class TestSubmitFeedback:

    def test_submits_positive_feedback(self, app):
        from application.api.user.conversations.routes import SubmitFeedback

        conv_id = ObjectId()
        mock_collection = Mock()

        with patch(
            "application.api.user.conversations.routes.conversations_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/feedback",
                method="POST",
                json={
                    "feedback": "like",
                    "conversation_id": str(conv_id),
                    "question_index": 0,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = SubmitFeedback().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        call_args = mock_collection.update_one.call_args
        assert "$set" in call_args[0][1]

    def test_removes_feedback_when_null(self, app):
        from application.api.user.conversations.routes import SubmitFeedback

        conv_id = ObjectId()
        mock_collection = Mock()

        with patch(
            "application.api.user.conversations.routes.conversations_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/feedback",
                method="POST",
                json={
                    "feedback": None,
                    "conversation_id": str(conv_id),
                    "question_index": 0,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = SubmitFeedback().post()

        assert response.status_code == 200
        call_args = mock_collection.update_one.call_args
        assert "$unset" in call_args[0][1]

    def test_returns_400_missing_fields(self, app):
        from application.api.user.conversations.routes import SubmitFeedback

        with app.test_request_context(
            "/api/feedback",
            method="POST",
            json={"feedback": "like"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = SubmitFeedback().post()

        assert response.status_code == 400
