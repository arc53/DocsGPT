"""Targeted tests for application/api/answer/services/stream_processor.py.

Tests the ``get_prompt`` helper and simpler StreamProcessor methods against
real ephemeral Postgres.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.answer.services.stream_processor.db_readonly", _yield
    ), patch(
        "application.api.answer.services.stream_processor.db_session", _yield
    ):
        yield


class TestGetPrompt:
    def test_default_preset(self):
        from application.api.answer.services.stream_processor import get_prompt
        got = get_prompt("default")
        assert isinstance(got, str)
        assert len(got) > 0

    def test_creative_preset(self):
        from application.api.answer.services.stream_processor import get_prompt
        got = get_prompt("creative")
        assert isinstance(got, str) and len(got) > 0

    def test_strict_preset(self):
        from application.api.answer.services.stream_processor import get_prompt
        got = get_prompt("strict")
        assert isinstance(got, str) and len(got) > 0

    def test_agentic_default_preset(self):
        from application.api.answer.services.stream_processor import get_prompt
        got = get_prompt("agentic_default")
        assert isinstance(got, str) and len(got) > 0

    def test_none_defaults_to_default(self):
        from application.api.answer.services.stream_processor import get_prompt
        got = get_prompt(None)
        assert isinstance(got, str) and len(got) > 0

    def test_empty_string_defaults_to_default(self):
        from application.api.answer.services.stream_processor import get_prompt
        assert get_prompt("") == get_prompt("default")

    def test_non_string_id_converted(self):
        from application.api.answer.services.stream_processor import get_prompt
        # A UUID object would be stringified; use an int to test the branch
        with pytest.raises(ValueError):
            # Int converts to str "42" which isn't a preset, and will
            # raise ValueError once lookup fails
            get_prompt(42)

    def test_unknown_prompt_id_raises(self, pg_conn):
        from application.api.answer.services.stream_processor import get_prompt
        with _patch_db(pg_conn), pytest.raises(ValueError):
            get_prompt("00000000-0000-0000-0000-000000000000")

    def test_legacy_id_unknown_raises(self, pg_conn):
        from application.api.answer.services.stream_processor import get_prompt
        with _patch_db(pg_conn), pytest.raises(ValueError):
            get_prompt("507f1f77bcf86cd799439011")

    def test_uuid_lookup_returns_content(self, pg_conn):
        from application.api.answer.services.stream_processor import get_prompt
        from application.storage.db.repositories.prompts import (
            PromptsRepository,
        )

        prompt = PromptsRepository(pg_conn).create(
            "u", "myprompt", "custom prompt content",
        )
        with _patch_db(pg_conn):
            got = get_prompt(str(prompt["id"]))
        assert got == "custom prompt content"


class TestStreamProcessorInit:
    def test_basic_init(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        data = {"question": "hi", "conversation_id": "conv-1"}
        token = {"sub": "user-abc"}
        sp = StreamProcessor(data, token)
        assert sp.data == data
        assert sp.decoded_token == token
        assert sp.initial_user_id == "user-abc"
        assert sp.conversation_id == "conv-1"

    def test_init_no_token(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"question": "hi"}, None)
        assert sp.decoded_token is None
        assert sp.initial_user_id is None
        assert sp.conversation_id is None

    def test_init_sets_agent_id_from_data(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        data = {"question": "hi", "agent_id": "agent-xyz"}
        sp = StreamProcessor(data, {"sub": "u"})
        assert sp.agent_id == "agent-xyz"


class TestLoadConversationHistory:
    def test_no_conversation_id_uses_request_history(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        import json as _json

        data = {
            "question": "hi",
            "history": _json.dumps([{"prompt": "a", "response": "b"}]),
        }
        sp = StreamProcessor(data, {"sub": "u"})
        sp._load_conversation_history()
        assert len(sp.history) == 1

    def test_loads_existing_conversation_history(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        user = "u-load-hist"
        repo = ConversationsRepository(pg_conn)
        conv = repo.create(user, name="c")
        conv_id = str(conv["id"])
        repo.append_message(
            conv_id,
            {"prompt": "q1", "response": "r1"},
        )
        repo.append_message(
            conv_id,
            {"prompt": "q2", "response": "r2"},
        )

        sp = StreamProcessor(
            {"question": "x", "conversation_id": conv_id},
            {"sub": user},
        )
        # Also patch conversation_service.get_conversation's DB accessor
        with _patch_db(pg_conn), patch(
            "application.api.answer.services.conversation_service.db_readonly",
        ) as mock_readonly:
            @contextmanager
            def _yield():
                yield pg_conn
            mock_readonly.side_effect = _yield
            sp._load_conversation_history()
        assert len(sp.history) == 2

    def test_unauthorized_conversation_raises(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        repo = ConversationsRepository(pg_conn)
        conv = repo.create("owner-user", name="c")
        sp = StreamProcessor(
            {"question": "hack", "conversation_id": str(conv["id"])},
            {"sub": "hacker"},
        )
        with _patch_db(pg_conn), patch(
            "application.api.answer.services.conversation_service.db_readonly"
        ) as mock_readonly:
            @contextmanager
            def _yield():
                yield pg_conn
            mock_readonly.side_effect = _yield
            with pytest.raises(ValueError):
                sp._load_conversation_history()


class TestHasActiveDocs:
    def test_false_when_no_active_docs(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"question": "q"}, {"sub": "u"})
        sp.source = {}
        sp.all_sources = []
        assert sp._has_active_docs() is False

    def test_true_when_source_active(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"question": "q"}, {"sub": "u"})
        sp.source = {"active_docs": "abc"}
        assert sp._has_active_docs() is True

    def test_false_when_source_empty(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"question": "q"}, {"sub": "u"})
        sp.source = None
        assert sp._has_active_docs() is False

    def test_default_returns_false(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"question": "q"}, {"sub": "u"})
        sp.source = {"active_docs": "default"}
        sp.all_sources = []
        assert sp._has_active_docs() is False


class TestProcessAttachments:
    def test_no_attachments(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"question": "q"}, {"sub": "u"})
        # attachment_ids not set
        with _patch_db(pg_conn):
            sp._process_attachments()
        assert sp.attachments == []

    def test_retrieves_attachments_by_id(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )

        user = "u-atts"
        att = AttachmentsRepository(pg_conn).create(
            user, "doc.txt", "/path",
            content="content here",
            size=100,
        )
        sp = StreamProcessor(
            {"question": "q", "attachments": [str(att["id"])]},
            {"sub": user},
        )
        with _patch_db(pg_conn):
            sp._process_attachments()
        assert len(sp.attachments) == 1
        assert sp.attachments[0]["content"] == "content here"


class TestGetAttachmentsContent:
    def test_empty_list(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"question": "q"}, {"sub": "u"})
        with _patch_db(pg_conn):
            got = sp._get_attachments_content([], "u")
        assert got == []

    def test_skips_missing_attachments(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"question": "q"}, {"sub": "u"})
        with _patch_db(pg_conn):
            got = sp._get_attachments_content(
                ["00000000-0000-0000-0000-000000000000"], "u",
            )
        assert got == []


class TestResolveAgentId:
    def test_returns_agent_id_from_request(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"agent_id": "req-agent"}, {"sub": "u"})
        assert sp._resolve_agent_id() == "req-agent"

    def test_returns_none_if_not_set(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        assert sp._resolve_agent_id() is None


class TestGetAgentKey:
    def test_returns_tuple_for_none_agent_id(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        key, is_shared, tok = sp._get_agent_key(None, "u")
        assert key is None and is_shared is False and tok is None

    def test_raises_for_missing_agent(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        with _patch_db(pg_conn), pytest.raises(Exception):
            sp._get_agent_key(
                "00000000-0000-0000-0000-000000000000", "u",
            )

    def test_returns_key_for_owned_agent(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        from application.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create(
            "owner", "a", "published", key="the-key",
        )
        sp = StreamProcessor({}, {"sub": "owner"})
        with _patch_db(pg_conn):
            key, shared, tok = sp._get_agent_key(str(agent["id"]), "owner")
        assert key == "the-key"
        assert shared is False

    def test_raises_on_unauthorized_access(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        from application.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create(
            "owner", "a", "published", key="k", shared=False,
        )
        sp = StreamProcessor({}, {"sub": "not-owner"})
        with _patch_db(pg_conn), pytest.raises(Exception):
            sp._get_agent_key(str(agent["id"]), "not-owner")


class TestConfigureSource:
    def test_agent_data_with_sources_list(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        sp._agent_data = {
            "sources": [
                {"id": "s1", "retriever": "classic"},
                {"id": "default"},
            ],
        }
        sp._configure_source()
        assert sp.source == {"active_docs": ["s1"]}

    def test_agent_data_with_single_source(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        sp._agent_data = {"source": "src-1", "retriever": "classic"}
        sp._configure_source()
        assert sp.source == {"active_docs": "src-1"}

    def test_agent_data_default_source(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        sp._agent_data = {"source": "default"}
        sp._configure_source()
        assert sp.source == {}

    def test_request_active_docs_used(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"active_docs": "abc"}, {"sub": "u"})
        sp._configure_source()
        assert sp.source == {"active_docs": "abc"}

    def test_request_active_docs_default(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"active_docs": "default"}, {"sub": "u"})
        sp._configure_source()
        assert sp.source == {}

    def test_no_data_empty_source(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        sp._configure_source()
        assert sp.source == {}


class TestConfigureRetriever:
    def test_defaults(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        sp._configure_retriever()
        assert sp.retriever_config["retriever_name"] == "classic"
        assert sp.retriever_config["chunks"] == 2

    def test_agent_overrides(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        sp._agent_data = {"retriever": "hybrid_search", "chunks": 5}
        sp._configure_retriever()
        assert sp.retriever_config["retriever_name"] == "hybrid_search"
        assert sp.retriever_config["chunks"] == 5

    def test_request_overrides_agent(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor(
            {"retriever": "duckdb", "chunks": 7}, {"sub": "u"},
        )
        sp._agent_data = {"retriever": "hybrid_search", "chunks": 5}
        sp._configure_retriever()
        assert sp.retriever_config["retriever_name"] == "duckdb"
        assert sp.retriever_config["chunks"] == 7

    def test_invalid_agent_chunks_falls_back(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        sp._agent_data = {"chunks": "not-a-number"}
        sp._configure_retriever()
        assert sp.retriever_config["chunks"] == 2

    def test_invalid_request_chunks_falls_back(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"chunks": "abc"}, {"sub": "u"})
        sp._configure_retriever()
        assert sp.retriever_config["chunks"] == 2

    def test_isnonedoc_without_api_key_sets_chunks_to_0(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"isNoneDoc": True}, {"sub": "u"})
        sp.agent_key = None
        sp._configure_retriever()
        assert sp.retriever_config["chunks"] == 0


class TestGetPromptContent:
    def test_gets_from_agent_config(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        from application.storage.db.repositories.prompts import (
            PromptsRepository,
        )

        prompt = PromptsRepository(pg_conn).create(
            "u", "p1", "My prompt content",
        )
        sp = StreamProcessor({}, {"sub": "u"})
        sp.agent_config = {"prompt_id": str(prompt["id"])}

        with _patch_db(pg_conn):
            content = sp._get_prompt_content()
        assert content == "My prompt content"

    def test_returns_none_on_missing(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )

        sp = StreamProcessor({}, {"sub": "u"})
        sp.agent_config = {
            "prompt_id": "00000000-0000-0000-0000-000000000000",
        }
        with _patch_db(pg_conn):
            content = sp._get_prompt_content()
        assert content is None

    def test_caches_prompt_content(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        sp._prompt_content = "cached"
        # Even with no agent_config, cached value returned
        assert sp._get_prompt_content() == "cached"


class TestPreFetchDocs:
    def test_skips_when_no_active_docs(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        sp.source = {}
        docs, raw = sp.pre_fetch_docs("question")
        assert docs is None and raw is None

    def test_skips_when_isnonedoc_no_agent(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"isNoneDoc": True}, {"sub": "u"})
        sp.source = {"active_docs": "abc"}  # would normally be active
        sp.agent_id = None
        docs, raw = sp.pre_fetch_docs("q")
        assert docs is None and raw is None

    def test_handles_retriever_exception(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        sp.source = {"active_docs": "src"}
        with patch(
            "application.api.answer.services.stream_processor.StreamProcessor.create_retriever",
            side_effect=RuntimeError("boom"),
        ):
            docs, raw = sp.pre_fetch_docs("q")
        assert docs is None and raw is None


class TestPreFetchTools:
    def test_disabled_globally_returns_none(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "u"})
        with patch(
            "application.api.answer.services.stream_processor.settings.ENABLE_TOOL_PREFETCH",
            False,
        ):
            got = sp.pre_fetch_tools()
        assert got is None

    def test_disabled_per_request(self):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({"disable_tool_prefetch": True}, {"sub": "u"})
        with patch(
            "application.api.answer.services.stream_processor.settings.ENABLE_TOOL_PREFETCH",
            True,
        ):
            got = sp.pre_fetch_tools()
        assert got is None

    def test_no_user_tools_returns_none(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        sp = StreamProcessor({}, {"sub": "no-tools-user"})
        with _patch_db(pg_conn), patch(
            "application.api.answer.services.stream_processor.settings.ENABLE_TOOL_PREFETCH",
            True,
        ):
            got = sp.pre_fetch_tools()
        assert got is None
