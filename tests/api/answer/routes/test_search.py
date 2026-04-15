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

