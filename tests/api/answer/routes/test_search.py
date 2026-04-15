from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestSearchResourceValidation:
    pass

    def test_returns_error_when_question_missing(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            with flask_app.test_request_context(
                json={"api_key": "test_key"}
            ):
                resource = SearchResource()
                result = resource.post()

                assert result.status_code == 400
                assert "question" in result.json["error"]

    def test_returns_error_when_api_key_missing(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            with flask_app.test_request_context(
                json={"question": "test query"}
            ):
                resource = SearchResource()
                result = resource.post()

                assert result.status_code == 400
                assert "api_key" in result.json["error"]



@pytest.mark.unit
class TestGetSourcesFromApiKey:
    pass

    def test_returns_source_id_via_patched_method(self, mock_mongo_db, flask_app):
        """Test that _get_sources_from_api_key can return multiple sources via patch."""
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            resource = SearchResource()

            with patch.object(resource, "_get_sources_from_api_key", return_value=["src1", "src2"]):
                result = resource._get_sources_from_api_key("any_key")

            assert len(result) == 2
            assert "src1" in result
            assert "src2" in result



@pytest.mark.unit
class TestSearchVectorstores:
    pass

    def test_returns_empty_when_no_source_ids(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            resource = SearchResource()

            result = resource._search_vectorstores("test query", [], 5)

            assert result == []

    def test_skips_empty_source_ids(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            resource = SearchResource()

            with patch(
                "application.api.answer.routes.search.VectorCreator.create_vectorstore"
            ) as mock_create:
                mock_vectorstore = MagicMock()
                mock_vectorstore.search.return_value = []
                mock_create.return_value = mock_vectorstore

                result = resource._search_vectorstores("test query", ["", "  "], 5)

                mock_create.assert_not_called()
                assert result == []

    def test_returns_search_results(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            resource = SearchResource()

            mock_doc = {
                "text": "Test content",
                "page_content": "Test content",
                "metadata": {
                    "title": "Test Title",
                    "source": "/path/to/doc",
                },
            }

            with patch(
                "application.api.answer.routes.search.VectorCreator.create_vectorstore"
            ) as mock_create:
                mock_vectorstore = MagicMock()
                mock_vectorstore.search.return_value = [mock_doc]
                mock_create.return_value = mock_vectorstore

                result = resource._search_vectorstores("test query", ["source_id"], 5)

                assert len(result) == 1
                assert result[0]["text"] == "Test content"
                assert result[0]["title"] == "Test Title"
                assert result[0]["source"] == "/path/to/doc"

    def test_handles_langchain_document_format(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            resource = SearchResource()

            mock_doc = MagicMock()
            mock_doc.page_content = "Langchain content"
            mock_doc.metadata = {"title": "LC Title", "source": "/lc/path"}

            with patch(
                "application.api.answer.routes.search.VectorCreator.create_vectorstore"
            ) as mock_create:
                mock_vectorstore = MagicMock()
                mock_vectorstore.search.return_value = [mock_doc]
                mock_create.return_value = mock_vectorstore

                result = resource._search_vectorstores("test query", ["source_id"], 5)

                assert len(result) == 1
                assert result[0]["text"] == "Langchain content"
                assert result[0]["title"] == "LC Title"

    def test_respects_chunks_limit(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            resource = SearchResource()

            mock_docs = [
                {"text": f"Content {i}", "metadata": {"title": f"Title {i}"}}
                for i in range(10)
            ]

            with patch(
                "application.api.answer.routes.search.VectorCreator.create_vectorstore"
            ) as mock_create:
                mock_vectorstore = MagicMock()
                mock_vectorstore.search.return_value = mock_docs
                mock_create.return_value = mock_vectorstore

                result = resource._search_vectorstores("test query", ["source_id"], 3)

                assert len(result) == 3

    def test_deduplicates_results(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            resource = SearchResource()

            duplicate_text = "Duplicate content " * 20
            mock_docs = [
                {"text": duplicate_text, "metadata": {"title": "Title 1"}},
                {"text": duplicate_text, "metadata": {"title": "Title 2"}},
                {"text": "Unique content", "metadata": {"title": "Title 3"}},
            ]

            with patch(
                "application.api.answer.routes.search.VectorCreator.create_vectorstore"
            ) as mock_create:
                mock_vectorstore = MagicMock()
                mock_vectorstore.search.return_value = mock_docs
                mock_create.return_value = mock_vectorstore

                result = resource._search_vectorstores("test query", ["source_id"], 5)

                assert len(result) == 2

    def test_handles_vectorstore_error_gracefully(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            resource = SearchResource()

            with patch(
                "application.api.answer.routes.search.VectorCreator.create_vectorstore"
            ) as mock_create:
                mock_create.side_effect = Exception("Vectorstore error")

                result = resource._search_vectorstores("test query", ["source_id"], 5)

                assert result == []

    def test_uses_filename_as_title_fallback(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            resource = SearchResource()

            mock_doc = {
                "text": "Content without title",
                "metadata": {"filename": "document.pdf"},
            }

            with patch(
                "application.api.answer.routes.search.VectorCreator.create_vectorstore"
            ) as mock_create:
                mock_vectorstore = MagicMock()
                mock_vectorstore.search.return_value = [mock_doc]
                mock_create.return_value = mock_vectorstore

                result = resource._search_vectorstores("test query", ["source_id"], 5)

                assert result[0]["title"] == "document.pdf"

    def test_uses_content_snippet_as_title_last_resort(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            resource = SearchResource()

            mock_doc = {
                "text": "Content without any title metadata at all",
                "metadata": {},
            }

            with patch(
                "application.api.answer.routes.search.VectorCreator.create_vectorstore"
            ) as mock_create:
                mock_vectorstore = MagicMock()
                mock_vectorstore.search.return_value = [mock_doc]
                mock_create.return_value = mock_vectorstore

                result = resource._search_vectorstores("test query", ["source_id"], 5)

                assert "Content without any title" in result[0]["title"]
                assert result[0]["title"].endswith("...")


@pytest.mark.unit
class TestSearchEndpoint:
    pass


# ---------------------------------------------------------------------------
# Real-PG tests for SearchResource.
# ---------------------------------------------------------------------------

from contextlib import contextmanager


@contextmanager
def _patch_search_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.answer.routes.search.db_readonly", _yield
    ):
        yield


class TestSearchResourcePgConn:
    def test_invalid_api_key_returns_401(self, pg_conn, flask_app):
        from application.api.answer.routes.search import SearchResource

        with _patch_search_db(pg_conn), flask_app.app_context():
            with flask_app.test_request_context(
                json={"question": "q", "api_key": "does-not-exist"},
            ):
                result = SearchResource().post()
        assert result.status_code == 401

    def test_no_sources_returns_empty(self, pg_conn, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.storage.db.repositories.agents import AgentsRepository

        AgentsRepository(pg_conn).create(
            "u", "a", "published", key="no-src-key",
        )
        with _patch_search_db(pg_conn), flask_app.app_context():
            with flask_app.test_request_context(
                json={"question": "q", "api_key": "no-src-key"},
            ):
                result = SearchResource().post()
        assert result.status_code == 200
        assert result.json == []

    def test_search_returns_results(self, pg_conn, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.sources import (
            SourcesRepository,
        )

        src = SourcesRepository(pg_conn).create("src", user_id="u")
        AgentsRepository(pg_conn).create(
            "u", "a", "published",
            key="search-key",
            source_id=str(src["id"]),
        )

        fake_vs = MagicMock()
        fake_vs.search.return_value = [
            {"text": "answer text", "metadata": {"title": "Doc"}},
        ]

        with _patch_search_db(pg_conn), patch(
            "application.api.answer.routes.search.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ), flask_app.app_context():
            with flask_app.test_request_context(
                json={"question": "q", "api_key": "search-key"},
            ):
                result = SearchResource().post()
        assert result.status_code == 200
        assert len(result.json) == 1

    def test_search_uses_extra_source_ids(self, pg_conn, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.sources import (
            SourcesRepository,
        )

        src1 = SourcesRepository(pg_conn).create("s1", user_id="u")
        src2 = SourcesRepository(pg_conn).create("s2", user_id="u")
        AgentsRepository(pg_conn).create(
            "u", "a", "published",
            key="extra-key",
            extra_source_ids=[str(src1["id"]), str(src2["id"])],
        )

        fake_vs = MagicMock()
        fake_vs.search.return_value = [
            {"text": "one", "metadata": {"title": "A"}},
        ]
        with _patch_search_db(pg_conn), patch(
            "application.api.answer.routes.search.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ), flask_app.app_context():
            with flask_app.test_request_context(
                json={"question": "q", "api_key": "extra-key", "chunks": 4},
            ):
                result = SearchResource().post()
        assert result.status_code == 200

    def test_search_exception_returns_500(self, pg_conn, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.sources import (
            SourcesRepository,
        )

        src = SourcesRepository(pg_conn).create("src", user_id="u")
        AgentsRepository(pg_conn).create(
            "u", "a", "published",
            key="err-key",
            source_id=str(src["id"]),
        )

        with _patch_search_db(pg_conn), patch(
            "application.api.answer.routes.search.SearchResource._get_sources_from_api_key",
            side_effect=RuntimeError("boom"),
        ), flask_app.app_context():
            with flask_app.test_request_context(
                json={"question": "q", "api_key": "err-key"},
            ):
                result = SearchResource().post()
        assert result.status_code == 500


class TestGetSourcesFromApiKeyPg:
    def test_empty_for_unknown_key(self, pg_conn, flask_app):
        from application.api.answer.routes.search import SearchResource

        with _patch_search_db(pg_conn), flask_app.app_context():
            got = SearchResource()._get_sources_from_api_key("nope")
        assert got == []

    def test_returns_extra_source_ids(self, pg_conn, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.sources import (
            SourcesRepository,
        )

        src = SourcesRepository(pg_conn).create("s", user_id="u")
        AgentsRepository(pg_conn).create(
            "u", "a", "published",
            key="sources-key",
            extra_source_ids=[str(src["id"])],
        )
        with _patch_search_db(pg_conn), flask_app.app_context():
            got = SearchResource()._get_sources_from_api_key("sources-key")
        assert got == [str(src["id"])]

    def test_falls_back_to_single_source(self, pg_conn, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.sources import (
            SourcesRepository,
        )

        src = SourcesRepository(pg_conn).create("s", user_id="u")
        AgentsRepository(pg_conn).create(
            "u", "a", "published",
            key="single-key",
            source_id=str(src["id"]),
        )
        with _patch_search_db(pg_conn), flask_app.app_context():
            got = SearchResource()._get_sources_from_api_key("single-key")
        assert got == [str(src["id"])]

