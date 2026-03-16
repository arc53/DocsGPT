from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from bson.dbref import DBRef


@pytest.mark.unit
class TestSearchResourceValidation:
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

    def test_returns_error_for_invalid_api_key(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            with flask_app.test_request_context(
                json={"question": "test query", "api_key": "invalid_key"}
            ):
                resource = SearchResource()
                result = resource.post()

                assert result.status_code == 401
                assert "Invalid API key" in result.json["error"]


@pytest.mark.unit
class TestGetSourcesFromApiKey:
    def test_returns_empty_list_when_agent_not_found(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource

        with flask_app.app_context():
            resource = SearchResource()

            result = resource._get_sources_from_api_key("nonexistent_key")

            assert result == []

    def test_returns_source_id_from_dbref(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.core.settings import settings

        with flask_app.app_context():
            source_id = ObjectId()
            agent_id = ObjectId()

            sources_collection = mock_mongo_db[settings.MONGO_DB_NAME]["sources"]
            sources_collection.insert_one(
                {"_id": source_id, "name": "Test Source"}
            )

            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_api_key",
                    "source": DBRef("sources", source_id),
                    "sources": [],
                }
            )

            resource = SearchResource()
            result = resource._get_sources_from_api_key("test_api_key")

            assert len(result) == 1
            assert result[0] == str(source_id)

    def test_returns_multiple_sources_from_sources_array(
        self, mock_mongo_db, flask_app
    ):
        from application.api.answer.routes.search import SearchResource
        from application.core.settings import settings

        with flask_app.app_context():
            source_id_1 = ObjectId()
            source_id_2 = ObjectId()
            agent_id = ObjectId()

            sources_collection = mock_mongo_db[settings.MONGO_DB_NAME]["sources"]
            sources_collection.insert_one({"_id": source_id_1, "name": "Source 1"})
            sources_collection.insert_one({"_id": source_id_2, "name": "Source 2"})

            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_api_key",
                    "sources": [
                        DBRef("sources", source_id_1),
                        DBRef("sources", source_id_2),
                    ],
                }
            )

            resource = SearchResource()
            result = resource._get_sources_from_api_key("test_api_key")

            assert len(result) == 2
            assert str(source_id_1) in result
            assert str(source_id_2) in result

    def test_skips_default_source_in_sources_array(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.core.settings import settings

        with flask_app.app_context():
            source_id = ObjectId()
            agent_id = ObjectId()

            sources_collection = mock_mongo_db[settings.MONGO_DB_NAME]["sources"]
            sources_collection.insert_one({"_id": source_id, "name": "Test Source"})

            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_api_key",
                    "sources": ["default", DBRef("sources", source_id)],
                }
            )

            resource = SearchResource()
            result = resource._get_sources_from_api_key("test_api_key")

            assert len(result) == 1
            assert result[0] == str(source_id)
            assert "default" not in result

    def test_skips_default_source_in_legacy_field(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.core.settings import settings

        with flask_app.app_context():
            agent_id = ObjectId()

            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_api_key",
                    "source": "default",
                    "sources": [],
                }
            )

            resource = SearchResource()
            result = resource._get_sources_from_api_key("test_api_key")

            assert result == []

    def test_falls_back_to_legacy_source_when_sources_empty(
        self, mock_mongo_db, flask_app
    ):
        from application.api.answer.routes.search import SearchResource
        from application.core.settings import settings

        with flask_app.app_context():
            source_id = ObjectId()
            agent_id = ObjectId()

            sources_collection = mock_mongo_db[settings.MONGO_DB_NAME]["sources"]
            sources_collection.insert_one({"_id": source_id, "name": "Test Source"})

            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_api_key",
                    "source": DBRef("sources", source_id),
                    "sources": [],
                }
            )

            resource = SearchResource()
            result = resource._get_sources_from_api_key("test_api_key")

            assert len(result) == 1
            assert result[0] == str(source_id)

    def test_handles_string_source_id(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.core.settings import settings

        with flask_app.app_context():
            agent_id = ObjectId()
            source_id = "custom_source_id"

            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_api_key",
                    "source": source_id,
                    "sources": [],
                }
            )

            resource = SearchResource()
            result = resource._get_sources_from_api_key("test_api_key")

            assert len(result) == 1
            assert result[0] == source_id


@pytest.mark.unit
class TestSearchVectorstores:
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
    def test_returns_empty_array_when_no_sources(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.core.settings import settings

        with flask_app.app_context():
            agent_id = ObjectId()

            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_api_key",
                    "source": "default",
                    "sources": [],
                }
            )

            with flask_app.test_request_context(
                json={"question": "test query", "api_key": "test_api_key"}
            ):
                resource = SearchResource()
                result = resource.post()

                assert result.status_code == 200
                assert result.json == []

    def test_returns_search_results_successfully(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.core.settings import settings

        with flask_app.app_context():
            source_id = ObjectId()
            agent_id = ObjectId()

            sources_collection = mock_mongo_db[settings.MONGO_DB_NAME]["sources"]
            sources_collection.insert_one({"_id": source_id, "name": "Test Source"})

            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_api_key",
                    "source": DBRef("sources", source_id),
                    "sources": [],
                }
            )

            mock_doc = {
                "text": "Search result content",
                "metadata": {"title": "Result Title", "source": "/doc/path"},
            }

            with flask_app.test_request_context(
                json={"question": "test query", "api_key": "test_api_key", "chunks": 5}
            ):
                with patch(
                    "application.api.answer.routes.search.VectorCreator.create_vectorstore"
                ) as mock_create:
                    mock_vectorstore = MagicMock()
                    mock_vectorstore.search.return_value = [mock_doc]
                    mock_create.return_value = mock_vectorstore

                    resource = SearchResource()
                    result = resource.post()

                    assert result.status_code == 200
                    assert len(result.json) == 1
                    assert result.json[0]["text"] == "Search result content"
                    assert result.json[0]["title"] == "Result Title"

    def test_uses_default_chunks_value(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.core.settings import settings

        with flask_app.app_context():
            source_id = ObjectId()
            agent_id = ObjectId()

            sources_collection = mock_mongo_db[settings.MONGO_DB_NAME]["sources"]
            sources_collection.insert_one({"_id": source_id, "name": "Test Source"})

            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_api_key",
                    "source": DBRef("sources", source_id),
                    "sources": [],
                }
            )

            with flask_app.test_request_context(
                json={"question": "test query", "api_key": "test_api_key"}
            ):
                with patch(
                    "application.api.answer.routes.search.VectorCreator.create_vectorstore"
                ) as mock_create:
                    mock_vectorstore = MagicMock()
                    mock_vectorstore.search.return_value = []
                    mock_create.return_value = mock_vectorstore

                    resource = SearchResource()
                    resource.post()

                    mock_vectorstore.search.assert_called_once()
                    call_args = mock_vectorstore.search.call_args
                    assert call_args[1]["k"] == 10

    def test_handles_internal_error(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.search import SearchResource
        from application.core.settings import settings

        with flask_app.app_context():
            source_id = ObjectId()
            agent_id = ObjectId()

            sources_collection = mock_mongo_db[settings.MONGO_DB_NAME]["sources"]
            sources_collection.insert_one({"_id": source_id, "name": "Test Source"})

            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_api_key",
                    "source": DBRef("sources", source_id),
                    "sources": [],
                }
            )

            with flask_app.test_request_context(
                json={"question": "test query", "api_key": "test_api_key"}
            ):
                resource = SearchResource()

                with patch.object(
                    resource, "_get_sources_from_api_key"
                ) as mock_get_sources:
                    mock_get_sources.side_effect = Exception("Database error")

                    result = resource.post()

                    assert result.status_code == 500
                    assert "Search failed" in result.json["error"]
