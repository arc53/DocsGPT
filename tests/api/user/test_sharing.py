import uuid
from unittest.mock import Mock, patch

import pytest
from bson import ObjectId
from bson.binary import Binary, UuidRepresentation
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@pytest.mark.unit
class TestShareConversation:

    def test_shares_non_promptable_conversation(self, app):
        from application.api.user.sharing.routes import ShareConversation

        conv_id = ObjectId()
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Test Chat",
            "queries": [{"prompt": "hi"}],
        }
        mock_shared = Mock()
        mock_shared.find_one.return_value = None
        mock_shared.insert_one.return_value = Mock()

        with patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ):
            with app.test_request_context(
                "/api/share?isPromptable=false",
                method="POST",
                json={"conversation_id": str(conv_id)},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 201
        assert response.json["success"] is True
        assert "identifier" in response.json
        mock_shared.insert_one.assert_called_once()

    def test_returns_existing_shared_link(self, app):
        from application.api.user.sharing.routes import ShareConversation

        conv_id = ObjectId()
        test_uuid = uuid.uuid4()
        binary_uuid = Binary.from_uuid(test_uuid, UuidRepresentation.STANDARD)

        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Test Chat",
            "queries": [{"prompt": "hi"}],
        }
        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": binary_uuid,
            "conversation_id": conv_id,
        }

        with patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ):
            with app.test_request_context(
                "/api/share?isPromptable=false",
                method="POST",
                json={"conversation_id": str(conv_id)},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 200
        assert response.json["identifier"] == str(test_uuid)

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sharing.routes import ShareConversation

        with app.test_request_context(
            "/api/share?isPromptable=false",
            method="POST",
            json={"conversation_id": str(ObjectId())},
        ):
            from flask import request

            request.decoded_token = None
            response = ShareConversation().post()

        assert response.status_code == 401

    def test_returns_400_missing_conversation_id(self, app):
        from application.api.user.sharing.routes import ShareConversation

        with app.test_request_context(
            "/api/share?isPromptable=false",
            method="POST",
            json={},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = ShareConversation().post()

        assert response.status_code == 400

    def test_returns_400_missing_isPromptable(self, app):
        from application.api.user.sharing.routes import ShareConversation

        with app.test_request_context(
            "/api/share",
            method="POST",
            json={"conversation_id": str(ObjectId())},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = ShareConversation().post()

        assert response.status_code == 400
        assert "isPromptable" in response.json["message"]

    def test_returns_404_conversation_not_found(self, app):
        from application.api.user.sharing.routes import ShareConversation

        mock_conversations = Mock()
        mock_conversations.find_one.return_value = None

        with patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                "/api/share?isPromptable=false",
                method="POST",
                json={"conversation_id": str(ObjectId())},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 404


@pytest.mark.unit
class TestGetPubliclySharedConversations:

    def test_returns_shared_conversation(self, app):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        test_uuid = uuid.uuid4()
        binary_uuid = Binary.from_uuid(test_uuid, UuidRepresentation.STANDARD)
        conv_id = ObjectId()

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": binary_uuid,
            "conversation_id": conv_id,
            "first_n_queries": 2,
            "isPromptable": False,
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Shared Chat",
            "queries": [
                {"prompt": "q1", "response": "a1"},
                {"prompt": "q2", "response": "a2"},
                {"prompt": "q3", "response": "a3"},
            ],
        }

        with patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ), patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                f"/api/shared_conversation/{test_uuid}"
            ):
                response = GetPubliclySharedConversations().get(str(test_uuid))

        assert response.status_code == 200
        assert response.json["success"] is True
        assert response.json["title"] == "Shared Chat"
        assert len(response.json["queries"]) == 2

    def test_returns_404_not_found(self, app):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        test_uuid = uuid.uuid4()
        mock_shared = Mock()
        mock_shared.find_one.return_value = None

        with patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ):
            with app.test_request_context(
                f"/api/shared_conversation/{test_uuid}"
            ):
                response = GetPubliclySharedConversations().get(str(test_uuid))

        assert response.status_code == 404

    def test_returns_404_conversation_deleted(self, app):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        test_uuid = uuid.uuid4()
        binary_uuid = Binary.from_uuid(test_uuid, UuidRepresentation.STANDARD)
        conv_id = ObjectId()

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": binary_uuid,
            "conversation_id": conv_id,
            "first_n_queries": 1,
            "isPromptable": False,
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = None

        with patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ), patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                f"/api/shared_conversation/{test_uuid}"
            ):
                response = GetPubliclySharedConversations().get(str(test_uuid))

        assert response.status_code == 404

    def test_includes_api_key_when_promptable(self, app):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        test_uuid = uuid.uuid4()
        binary_uuid = Binary.from_uuid(test_uuid, UuidRepresentation.STANDARD)
        conv_id = ObjectId()

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": binary_uuid,
            "conversation_id": conv_id,
            "first_n_queries": 1,
            "isPromptable": True,
            "api_key": "shared_api_key",
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Chat",
            "queries": [{"prompt": "q1", "response": "a1"}],
        }

        with patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ), patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                f"/api/shared_conversation/{test_uuid}"
            ):
                response = GetPubliclySharedConversations().get(str(test_uuid))

        assert response.status_code == 200
        assert response.json["api_key"] == "shared_api_key"

    def test_handles_dbref_conversation_id(self, app):
        from bson.dbref import DBRef
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        test_uuid = uuid.uuid4()
        binary_uuid = Binary.from_uuid(test_uuid, UuidRepresentation.STANDARD)
        conv_id = ObjectId()

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": binary_uuid,
            "conversation_id": DBRef("conversations", conv_id),
            "first_n_queries": 1,
            "isPromptable": False,
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Chat",
            "queries": [{"prompt": "q1", "response": "a1"}],
        }

        with patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ), patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                f"/api/shared_conversation/{test_uuid}"
            ):
                response = GetPubliclySharedConversations().get(str(test_uuid))

        assert response.status_code == 200
        mock_conversations.find_one.assert_called_once_with({"_id": conv_id})

    def test_handles_dict_oid_conversation_id(self, app):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        test_uuid = uuid.uuid4()
        binary_uuid = Binary.from_uuid(test_uuid, UuidRepresentation.STANDARD)
        conv_id = ObjectId()

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": binary_uuid,
            "conversation_id": {"$id": {"$oid": str(conv_id)}},
            "first_n_queries": 1,
            "isPromptable": False,
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Chat",
            "queries": [{"prompt": "q1", "response": "a1"}],
        }

        with patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ), patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                f"/api/shared_conversation/{test_uuid}"
            ):
                response = GetPubliclySharedConversations().get(str(test_uuid))

        assert response.status_code == 200

    def test_handles_dict_id_string_conversation_id(self, app):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        test_uuid = uuid.uuid4()
        binary_uuid = Binary.from_uuid(test_uuid, UuidRepresentation.STANDARD)
        conv_id = ObjectId()

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": binary_uuid,
            "conversation_id": {"$id": str(conv_id)},
            "first_n_queries": 1,
            "isPromptable": False,
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Chat",
            "queries": [{"prompt": "q1", "response": "a1"}],
        }

        with patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ), patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                f"/api/shared_conversation/{test_uuid}"
            ):
                response = GetPubliclySharedConversations().get(str(test_uuid))

        assert response.status_code == 200

    def test_handles_dict_underscore_id_conversation_id(self, app):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        test_uuid = uuid.uuid4()
        binary_uuid = Binary.from_uuid(test_uuid, UuidRepresentation.STANDARD)
        conv_id = ObjectId()

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": binary_uuid,
            "conversation_id": {"_id": str(conv_id)},
            "first_n_queries": 1,
            "isPromptable": False,
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Chat",
            "queries": [{"prompt": "q1", "response": "a1"}],
        }

        with patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ), patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                f"/api/shared_conversation/{test_uuid}"
            ):
                response = GetPubliclySharedConversations().get(str(test_uuid))

        assert response.status_code == 200

    def test_handles_string_conversation_id(self, app):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        test_uuid = uuid.uuid4()
        binary_uuid = Binary.from_uuid(test_uuid, UuidRepresentation.STANDARD)
        conv_id = ObjectId()

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": binary_uuid,
            "conversation_id": str(conv_id),
            "first_n_queries": 1,
            "isPromptable": False,
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Chat",
            "queries": [{"prompt": "q1", "response": "a1"}],
        }

        with patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ), patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                f"/api/shared_conversation/{test_uuid}"
            ):
                response = GetPubliclySharedConversations().get(str(test_uuid))

        assert response.status_code == 200

    def test_resolves_attachments_in_shared(self, app):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        test_uuid = uuid.uuid4()
        binary_uuid = Binary.from_uuid(test_uuid, UuidRepresentation.STANDARD)
        conv_id = ObjectId()
        att_id = ObjectId()

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": binary_uuid,
            "conversation_id": conv_id,
            "first_n_queries": 1,
            "isPromptable": False,
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Chat",
            "queries": [
                {"prompt": "q1", "response": "a1", "attachments": [str(att_id)]}
            ],
        }
        mock_attachments = Mock()
        mock_attachments.find_one.return_value = {
            "_id": att_id,
            "filename": "file.pdf",
        }

        with patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ), patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.sharing.routes.attachments_collection",
            mock_attachments,
        ):
            with app.test_request_context(
                f"/api/shared_conversation/{test_uuid}"
            ):
                response = GetPubliclySharedConversations().get(str(test_uuid))

        assert response.status_code == 200
        assert response.json["queries"][0]["attachments"][0]["fileName"] == "file.pdf"

    def test_handles_general_exception(self, app):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        mock_shared = Mock()
        mock_shared.find_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ):
            with app.test_request_context(
                f"/api/shared_conversation/{uuid.uuid4()}"
            ):
                response = GetPubliclySharedConversations().get(str(uuid.uuid4()))

        assert response.status_code == 400


@pytest.mark.unit
class TestShareConversationPromptable:

    def test_promptable_with_existing_api_key_and_existing_share(self, app):
        from application.api.user.sharing.routes import ShareConversation

        conv_id = ObjectId()
        test_uuid = uuid.uuid4()
        binary_uuid = Binary.from_uuid(test_uuid, UuidRepresentation.STANDARD)

        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Test Chat",
            "queries": [{"prompt": "hi"}],
        }
        mock_agents = Mock()
        mock_agents.find_one.return_value = {"key": "existing_api_uuid"}
        mock_shared = Mock()
        mock_shared.find_one.return_value = {"uuid": binary_uuid}

        with patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.sharing.routes.agents_collection",
            mock_agents,
        ), patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ):
            with app.test_request_context(
                "/api/share?isPromptable=true",
                method="POST",
                json={
                    "conversation_id": str(conv_id),
                    "prompt_id": "default",
                    "chunks": "3",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 200
        assert response.json["identifier"] == str(test_uuid)

    def test_promptable_with_existing_api_key_new_share(self, app):
        from application.api.user.sharing.routes import ShareConversation

        conv_id = ObjectId()

        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Test Chat",
            "queries": [{"prompt": "hi"}],
        }
        mock_agents = Mock()
        mock_agents.find_one.return_value = {"key": "existing_api_uuid"}
        mock_shared = Mock()
        mock_shared.find_one.return_value = None

        with patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.sharing.routes.agents_collection",
            mock_agents,
        ), patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ):
            with app.test_request_context(
                "/api/share?isPromptable=true",
                method="POST",
                json={
                    "conversation_id": str(conv_id),
                    "source": str(ObjectId()),
                    "retriever": "classic",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 201
        mock_shared.insert_one.assert_called_once()

    def test_promptable_creates_new_api_key(self, app):
        from application.api.user.sharing.routes import ShareConversation

        conv_id = ObjectId()

        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Test Chat",
            "queries": [{"prompt": "hi"}],
        }
        mock_agents = Mock()
        mock_agents.find_one.return_value = None
        mock_shared = Mock()

        with patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.sharing.routes.agents_collection",
            mock_agents,
        ), patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ):
            with app.test_request_context(
                "/api/share?isPromptable=true",
                method="POST",
                json={
                    "conversation_id": str(conv_id),
                    "source": str(ObjectId()),
                    "retriever": "classic",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 201
        mock_agents.insert_one.assert_called_once()
        mock_shared.insert_one.assert_called_once()
