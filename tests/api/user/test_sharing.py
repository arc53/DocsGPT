"""Tests for application/api/user/sharing/routes.py.

Routes still use Mongo as primary store (with dual-write to PG).
Tests patch mongo collections directly; no bson imports needed.
"""

import uuid
from unittest.mock import Mock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


def _uuid_binary(u: uuid.UUID) -> Mock:
    """Return a Mock that behaves like a BSON Binary wrapping a UUID.

    The sharing route calls ``doc["uuid"].as_uuid()`` to recover the Python
    UUID object.  This avoids any bson dependency in tests.
    """
    m = Mock()
    m.as_uuid.return_value = u
    return m


def _mock_oid(ts: str = "2025-01-01T00:00:00") -> Mock:
    """Return a Mock that behaves like a BSON ObjectId.

    The sharing route calls ``conversation["_id"].generation_time.isoformat()``
    to get the creation timestamp.  This avoids any bson dependency in tests.
    """
    m = Mock()
    m.__str__ = Mock(return_value=uuid.uuid4().hex[:24])
    m.generation_time.isoformat.return_value = ts
    return m


@pytest.mark.unit
class TestShareConversation:

    def test_shares_non_promptable_conversation(self, app):
        from application.api.user.sharing.routes import ShareConversation

        conv_id = uuid.uuid4().hex[:24]
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
        ), patch(
            "application.api.user.sharing.routes.dual_write",
            Mock(),
        ):
            with app.test_request_context(
                "/api/share?isPromptable=false",
                method="POST",
                json={"conversation_id": conv_id},
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

        conv_id = uuid.uuid4().hex[:24]
        test_uuid = uuid.uuid4()

        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Test Chat",
            "queries": [{"prompt": "hi"}],
        }
        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": _uuid_binary(test_uuid),
            "conversation_id": conv_id,
        }

        with patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ), patch(
            "application.api.user.sharing.routes.dual_write",
            Mock(),
        ):
            with app.test_request_context(
                "/api/share?isPromptable=false",
                method="POST",
                json={"conversation_id": conv_id},
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
            json={"conversation_id": uuid.uuid4().hex[:24]},
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
            json={"conversation_id": uuid.uuid4().hex[:24]},
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
                json={"conversation_id": uuid.uuid4().hex[:24]},
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
        conv_id = uuid.uuid4().hex[:24]

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": _uuid_binary(test_uuid),
            "conversation_id": conv_id,
            "first_n_queries": 2,
            "isPromptable": False,
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": _mock_oid(),
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
        conv_id = uuid.uuid4().hex[:24]

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": _uuid_binary(test_uuid),
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
        conv_id = uuid.uuid4().hex[:24]

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": _uuid_binary(test_uuid),
            "conversation_id": conv_id,
            "first_n_queries": 1,
            "isPromptable": True,
            "api_key": "shared_api_key",
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": _mock_oid(),
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

    def test_handles_string_conversation_id(self, app):
        """Conversation id stored as plain string is handled correctly."""
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        test_uuid = uuid.uuid4()
        conv_id = uuid.uuid4().hex[:24]

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": _uuid_binary(test_uuid),
            "conversation_id": conv_id,
            "first_n_queries": 1,
            "isPromptable": False,
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": _mock_oid(),
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
        conv_id = uuid.uuid4().hex[:24]
        att_id = uuid.uuid4().hex[:24]

        mock_shared = Mock()
        mock_shared.find_one.return_value = {
            "uuid": _uuid_binary(test_uuid),
            "conversation_id": conv_id,
            "first_n_queries": 1,
            "isPromptable": False,
        }
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": _mock_oid(),
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

        conv_id = uuid.uuid4().hex[:24]
        test_uuid = uuid.uuid4()

        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "name": "Test Chat",
            "queries": [{"prompt": "hi"}],
        }
        mock_agents = Mock()
        mock_agents.find_one.return_value = {"key": "existing_api_uuid"}
        mock_shared = Mock()
        mock_shared.find_one.return_value = {"uuid": _uuid_binary(test_uuid)}

        with patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.sharing.routes.agents_collection",
            mock_agents,
        ), patch(
            "application.api.user.sharing.routes.shared_conversations_collections",
            mock_shared,
        ), patch(
            "application.api.user.sharing.routes.dual_write",
            Mock(),
        ):
            with app.test_request_context(
                "/api/share?isPromptable=true",
                method="POST",
                json={
                    "conversation_id": conv_id,
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

        conv_id = uuid.uuid4().hex[:24]

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
        ), patch(
            "application.api.user.sharing.routes.dual_write",
            Mock(),
        ):
            with app.test_request_context(
                "/api/share?isPromptable=true",
                method="POST",
                json={
                    "conversation_id": conv_id,
                    "source": uuid.uuid4().hex[:24],
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

        conv_id = uuid.uuid4().hex[:24]

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
        ), patch(
            "application.api.user.sharing.routes.dual_write",
            Mock(),
        ):
            with app.test_request_context(
                "/api/share?isPromptable=true",
                method="POST",
                json={
                    "conversation_id": conv_id,
                    "source": uuid.uuid4().hex[:24],
                    "retriever": "classic",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 201
        mock_agents.insert_one.assert_called_once()
        mock_shared.insert_one.assert_called_once()


@pytest.mark.unit
class TestShareConversationErrorPath:

    def test_share_conversation_exception_returns_400(self, app):
        """Exception during find_one returns 400."""
        from application.api.user.sharing.routes import ShareConversation

        mock_conversations = Mock()
        mock_conversations.find_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                "/api/share?isPromptable=false",
                method="POST",
                json={"conversation_id": uuid.uuid4().hex[:24]},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 400

    def test_insert_one_exception_returns_400(self, app):
        """Exception during insert_one returns 400."""
        from application.api.user.sharing.routes import ShareConversation

        conv_id = uuid.uuid4().hex[:24]
        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": conv_id,
            "user": "user1",
            "queries": [],
        }
        mock_shared = Mock()
        mock_shared.find_one.return_value = None
        mock_shared.insert_one.side_effect = Exception("Insert failed")

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
                json={"conversation_id": conv_id},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 400
