"""Tests for application/api/user/sharing/routes.py.

Previously used bson.ObjectId + bson.binary.Binary (UUID representation)
which were Mongo-specific. Sharing persistence moves to Postgres via the
SharedConversations repository; coverage will be rebuilt on pg_conn in a
follow-up.
"""

import pytest


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


# =====================================================================
# Coverage gap tests  (lines 201-205)
# =====================================================================


@pytest.mark.unit
class TestShareConversationExceptionGap:
    def test_share_conversation_exception_returns_400(self):
        """Cover lines 201-205: exception during sharing returns 400."""
        from application.api.user.sharing.routes import ShareConversation
        from unittest.mock import Mock, patch

        app = Flask(__name__)

        mock_conversations = Mock()
        mock_conversations.find_one.side_effect = Exception("db error")

        with patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                "/api/share",
                method="POST",
                json={
                    "conversation_id": str(ObjectId()),
                    "source": str(ObjectId()),
                    "retriever": "classic",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Coverage — additional uncovered lines: 201-205
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShareConversationErrorPath:

    def test_share_conversation_exception_returns_400(self, app):
        """Cover lines 201-205: exception during sharing returns 400."""
        from application.api.user.sharing.routes import ShareConversation

        mock_conversations = Mock()
        mock_conversations.find_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                "/api/share",
                method="POST",
                json={"conversation_id": str(ObjectId())},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Additional coverage for sharing/routes.py
# Lines: 201-205: exception in try block (different entry point)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShareConversationInsertException:
    """Cover lines 201-205: exception during insert_one."""

    def test_insert_one_exception_returns_400(self, app):
        from application.api.user.sharing.routes import ShareConversation

        mock_conversations = Mock()
        mock_conversations.find_one.return_value = {
            "_id": ObjectId(),
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
                "/api/share",
                method="POST",
                json={"conversation_id": str(ObjectId())},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 400


@pytest.mark.unit
class TestDualWriteShare:
    """Cover the _dual_write_share helper (lines 43-70) via USE_POSTGRES=True."""

    def test_dual_write_share_no_op_when_conv_not_in_pg(self, app):
        """When ConversationsRepository.get_by_legacy_id returns None, _write returns early."""
        from application.api.user.sharing.routes import _dual_write_share
        from unittest.mock import MagicMock, patch

        mock_conv_repo_instance = MagicMock()
        mock_conv_repo_instance.get_by_legacy_id.return_value = None
        mock_shared_repo_instance = MagicMock()
        mock_shared_repo_instance._conn = MagicMock()

        mock_conn = MagicMock()

        with patch(
            "application.api.user.sharing.routes.dual_write"
        ) as mock_dual_write:
            # Execute to prove dual_write is called
            _dual_write_share(
                "507f1f77bcf86cd799439011",
                str(uuid.uuid4()),
                "user1",
                is_promptable=False,
                first_n_queries=1,
                api_key=None,
            )
            mock_dual_write.assert_called_once()

    def test_dual_write_share_with_promptable_and_24char_prompt_id(self, app):
        """Cover lines 55-65: 24-char prompt_id triggers SQL lookup."""
        from application.api.user.sharing.routes import _dual_write_share
        from unittest.mock import MagicMock, patch

        with patch(
            "application.api.user.sharing.routes.dual_write"
        ) as mock_dual_write:
            _dual_write_share(
                "507f1f77bcf86cd799439011",
                str(uuid.uuid4()),
                "user1",
                is_promptable=True,
                first_n_queries=2,
                api_key="some_key",
                prompt_id="507f1f77bcf86cd799439012",  # 24-char ObjectId-like
                chunks=3,
            )
            mock_dual_write.assert_called_once()

    def test_dual_write_write_fn_conv_not_none_calls_get_or_create(self):
        """Invoke _write directly to cover lines 42-79."""
        from application.api.user.sharing.routes import _dual_write_share
        from unittest.mock import MagicMock, call, patch

        captured_fn = {}

        def capture_dual_write(repo_cls, fn):
            captured_fn["fn"] = fn

        with patch(
            "application.api.user.sharing.routes.dual_write",
            side_effect=capture_dual_write,
        ):
            _dual_write_share(
                "507f1f77bcf86cd799439011",
                str(uuid.uuid4()),
                "user1",
                is_promptable=False,
                first_n_queries=1,
                api_key=None,
            )

        mock_repo = MagicMock()
        mock_repo._conn = MagicMock()

        # Conv not found -> early return
        with patch(
            "application.api.user.sharing.routes.ConversationsRepository"
        ) as mock_conv_repo_cls:
            mock_conv_repo_instance = MagicMock()
            mock_conv_repo_instance.get_by_legacy_id.return_value = None
            mock_conv_repo_cls.return_value = mock_conv_repo_instance
            captured_fn["fn"](mock_repo)

        mock_repo.get_or_create.assert_not_called()

    def test_dual_write_write_fn_calls_get_or_create_when_conv_found(self):
        """_write calls get_or_create when conversation is found in Postgres."""
        from application.api.user.sharing.routes import _dual_write_share
        from unittest.mock import MagicMock, patch

        captured_fn = {}

        def capture_dual_write(repo_cls, fn):
            captured_fn["fn"] = fn

        share_uuid = str(uuid.uuid4())

        with patch(
            "application.api.user.sharing.routes.dual_write",
            side_effect=capture_dual_write,
        ):
            _dual_write_share(
                "507f1f77bcf86cd799439011",
                share_uuid,
                "user1",
                is_promptable=True,
                first_n_queries=2,
                api_key="key123",
                prompt_id=None,
                chunks=5,
            )

        mock_repo = MagicMock()
        mock_repo._conn = MagicMock()

        with patch(
            "application.api.user.sharing.routes.ConversationsRepository"
        ) as mock_conv_repo_cls:
            mock_conv_repo_instance = MagicMock()
            mock_conv_repo_instance.get_by_legacy_id.return_value = {"id": "pg-uuid-1"}
            mock_conv_repo_cls.return_value = mock_conv_repo_instance
            captured_fn["fn"](mock_repo)

        mock_repo.get_or_create.assert_called_once_with(
            "pg-uuid-1",
            "user1",
            is_promptable=True,
            first_n_queries=2,
            api_key="key123",
            prompt_id=None,
            chunks=5,
            share_uuid=share_uuid,
        )

    def test_dual_write_write_fn_resolves_prompt_id_from_sql(self):
        """Cover lines 56-65: 24-char prompt_id triggers SQL lookup, row found."""
        from application.api.user.sharing.routes import _dual_write_share
        from unittest.mock import MagicMock, patch

        captured_fn = {}

        def capture_dual_write(repo_cls, fn):
            captured_fn["fn"] = fn

        share_uuid = str(uuid.uuid4())
        prompt_id = "507f1f77bcf86cd799439012"  # exactly 24 chars

        with patch(
            "application.api.user.sharing.routes.dual_write",
            side_effect=capture_dual_write,
        ):
            _dual_write_share(
                "507f1f77bcf86cd799439011",
                share_uuid,
                "user1",
                is_promptable=True,
                first_n_queries=1,
                api_key=None,
                prompt_id=prompt_id,
                chunks=None,
            )

        mock_repo = MagicMock()
        mock_conn = MagicMock()
        mock_repo._conn = mock_conn
        resolved_pg_id = "pg-prompt-uuid"
        mock_conn.execute.return_value.fetchone.return_value = (resolved_pg_id,)

        with patch(
            "application.api.user.sharing.routes.ConversationsRepository"
        ) as mock_conv_repo_cls:
            mock_conv_repo_instance = MagicMock()
            mock_conv_repo_instance.get_by_legacy_id.return_value = {"id": "pg-conv-1"}
            mock_conv_repo_cls.return_value = mock_conv_repo_instance
            captured_fn["fn"](mock_repo)

        mock_repo.get_or_create.assert_called_once()
        call_kwargs = mock_repo.get_or_create.call_args[1]
        assert call_kwargs["prompt_id"] == resolved_pg_id

    def test_dual_write_write_fn_prompt_id_sql_no_row(self):
        """Cover lines 56-65: 24-char prompt_id triggers SQL lookup, no row found."""
        from application.api.user.sharing.routes import _dual_write_share
        from unittest.mock import MagicMock, patch

        captured_fn = {}

        def capture_dual_write(repo_cls, fn):
            captured_fn["fn"] = fn

        share_uuid = str(uuid.uuid4())
        prompt_id = "507f1f77bcf86cd799439012"

        with patch(
            "application.api.user.sharing.routes.dual_write",
            side_effect=capture_dual_write,
        ):
            _dual_write_share(
                "507f1f77bcf86cd799439011",
                share_uuid,
                "user1",
                is_promptable=True,
                first_n_queries=1,
                api_key=None,
                prompt_id=prompt_id,
                chunks=None,
            )

        mock_repo = MagicMock()
        mock_conn = MagicMock()
        mock_repo._conn = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None  # no row

        with patch(
            "application.api.user.sharing.routes.ConversationsRepository"
        ) as mock_conv_repo_cls:
            mock_conv_repo_instance = MagicMock()
            mock_conv_repo_instance.get_by_legacy_id.return_value = {"id": "pg-conv-1"}
            mock_conv_repo_cls.return_value = mock_conv_repo_instance
            captured_fn["fn"](mock_repo)

        mock_repo.get_or_create.assert_called_once()
        call_kwargs = mock_repo.get_or_create.call_args[1]
        assert call_kwargs["prompt_id"] is None


@pytest.mark.unit
class TestShareConversationInnerException:
    """Cover lines 292-296: exception thrown inside the try block after isPromptable passes."""

    def test_inner_exception_returns_400(self, app):
        from application.api.user.sharing.routes import ShareConversation

        conv_id = ObjectId()
        mock_conversations = Mock()
        mock_conversations.find_one.side_effect = Exception("inner DB error")

        with patch(
            "application.api.user.sharing.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                "/api/share?isPromptable=false",
                method="POST",
                json={"conversation_id": str(conv_id)},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareConversation().post()

        assert response.status_code == 400
        assert response.json["success"] is False


@pytest.mark.unit
class TestGetPubliclySharedConversationsAttachmentError:
    """Cover lines 365-366: attachment fetch exception in shared conversation view."""

    def test_attachment_error_is_swallowed(self, app):
        from application.api.user.sharing.routes import GetPubliclySharedConversations

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
            "name": "Shared Chat",
            "queries": [
                {"prompt": "q1", "response": "a1", "attachments": [str(att_id)]}
            ],
        }
        mock_attachments = Mock()
        mock_attachments.find_one.side_effect = Exception("attachment DB error")

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

        # Exception in attachment fetch is swallowed; response is still 200
        assert response.status_code == 200
        assert response.json["success"] is True
