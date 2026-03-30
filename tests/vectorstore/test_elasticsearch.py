from unittest.mock import MagicMock, Mock, patch

import pytest


def _make_es_store(source_id="test-source"):
    """Helper to create an ElasticsearchStore with mocked deps."""
    # Reset class-level connection
    from application.vectorstore.elasticsearch import ElasticsearchStore

    ElasticsearchStore._es_connection = None

    with patch(
        "application.vectorstore.elasticsearch.settings"
    ) as mock_settings, patch.dict(
        "sys.modules", {"elasticsearch": MagicMock(), "elasticsearch.helpers": MagicMock()}
    ):
        mock_settings.ELASTIC_URL = "http://localhost:9200"
        mock_settings.ELASTIC_USERNAME = "elastic"
        mock_settings.ELASTIC_PASSWORD = "password"
        mock_settings.ELASTIC_CLOUD_ID = None
        mock_settings.ELASTIC_INDEX = "test_index"
        mock_settings.EMBEDDINGS_NAME = "test_model"

        import elasticsearch

        mock_es = MagicMock()
        elasticsearch.Elasticsearch.return_value = mock_es

        store = ElasticsearchStore(
            source_id=source_id,
            embeddings_key="key",
            index_name="test_index",
        )

        return store, mock_es, mock_settings


@pytest.mark.unit
class TestElasticsearchStoreInit:
    def test_source_id_cleaned(self):
        store, _, _ = _make_es_store(source_id="application/indexes/abc123/")
        assert store.source_id == "abc123"

    def test_init_with_url(self):
        store, mock_es, _ = _make_es_store()
        assert store.docsearch is mock_es
        assert store.index_name == "test_index"

    def test_init_with_cloud_id(self):
        from application.vectorstore.elasticsearch import ElasticsearchStore

        ElasticsearchStore._es_connection = None

        with patch(
            "application.vectorstore.elasticsearch.settings"
        ) as mock_settings, patch.dict(
            "sys.modules", {"elasticsearch": MagicMock()}
        ):
            mock_settings.ELASTIC_URL = None
            mock_settings.ELASTIC_CLOUD_ID = "my-cloud-id"
            mock_settings.ELASTIC_USERNAME = "user"
            mock_settings.ELASTIC_PASSWORD = "pass"
            mock_settings.ELASTIC_INDEX = "idx"
            mock_settings.EMBEDDINGS_NAME = "model"

            store = ElasticsearchStore(
                source_id="src", embeddings_key="k", index_name="idx"
            )
            assert store.docsearch is not None

    def test_init_no_url_no_cloud_id_raises(self):
        from application.vectorstore.elasticsearch import ElasticsearchStore

        ElasticsearchStore._es_connection = None

        with patch(
            "application.vectorstore.elasticsearch.settings"
        ) as mock_settings, patch.dict(
            "sys.modules", {"elasticsearch": MagicMock()}
        ):
            mock_settings.ELASTIC_URL = None
            mock_settings.ELASTIC_CLOUD_ID = None
            mock_settings.ELASTIC_INDEX = "idx"
            mock_settings.EMBEDDINGS_NAME = "model"

            with pytest.raises(ValueError, match="provide either"):
                ElasticsearchStore(source_id="src", embeddings_key="k")

    def test_reuses_class_connection(self):
        from application.vectorstore.elasticsearch import ElasticsearchStore

        ElasticsearchStore._es_connection = None

        with patch(
            "application.vectorstore.elasticsearch.settings"
        ) as mock_settings, patch.dict(
            "sys.modules", {"elasticsearch": MagicMock()}
        ):
            mock_settings.ELASTIC_URL = "http://localhost:9200"
            mock_settings.ELASTIC_USERNAME = "user"
            mock_settings.ELASTIC_PASSWORD = "pass"
            mock_settings.ELASTIC_CLOUD_ID = None
            mock_settings.ELASTIC_INDEX = "idx"
            mock_settings.EMBEDDINGS_NAME = "model"

            import elasticsearch

            mock_es = MagicMock()
            elasticsearch.Elasticsearch.return_value = mock_es

            store1 = ElasticsearchStore(source_id="src1", embeddings_key="k")
            store2 = ElasticsearchStore(source_id="src2", embeddings_key="k")

            assert store1.docsearch is store2.docsearch
            elasticsearch.Elasticsearch.assert_called_once()


@pytest.mark.unit
class TestElasticsearchStoreSearch:
    def test_search_builds_query(self):
        store, mock_es, mock_settings = _make_es_store()

        mock_emb = Mock()
        mock_emb.embed_query = Mock(return_value=[0.1, 0.2, 0.3])

        with patch.object(store, "_get_embeddings", return_value=mock_emb):
            mock_es.search.return_value = {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "text": "doc1",
                                "metadata": {"source": "file.txt"},
                            }
                        },
                        {
                            "_source": {
                                "text": "doc2",
                                "metadata": {"source": "file2.txt"},
                            }
                        },
                    ]
                }
            }

            results = store.search("query", k=2)

        assert len(results) == 2
        assert results[0].page_content == "doc1"
        assert results[1].metadata == {"source": "file2.txt"}

    def test_search_empty_results(self):
        store, mock_es, _ = _make_es_store()

        mock_emb = Mock()
        mock_emb.embed_query = Mock(return_value=[0.1])

        with patch.object(store, "_get_embeddings", return_value=mock_emb):
            mock_es.search.return_value = {"hits": {"hits": []}}
            results = store.search("query")

        assert results == []


@pytest.mark.unit
class TestElasticsearchStoreAddTexts:
    def test_add_texts(self):
        store, mock_es, mock_settings = _make_es_store()

        mock_emb = Mock()
        mock_emb.embed_documents = Mock(return_value=[[0.1, 0.2], [0.3, 0.4]])

        mock_bulk = Mock(return_value=(2, 0))
        mock_helpers = MagicMock()
        mock_helpers.bulk = mock_bulk

        with patch.object(
            store, "_get_embeddings", return_value=mock_emb
        ), patch.object(
            store, "_create_index_if_not_exists"
        ), patch.dict(
            "sys.modules", {"elasticsearch.helpers": mock_helpers}
        ):
            ids = store.add_texts(
                ["text1", "text2"],
                metadatas=[{"a": 1}, {"b": 2}],
            )

        assert len(ids) == 2

    def test_add_texts_empty_raises(self):
        """Empty texts causes IndexError because code accesses vectors[0] unconditionally."""
        store, _, _ = _make_es_store()

        mock_emb = Mock()
        mock_emb.embed_documents = Mock(return_value=[])

        with patch.object(store, "_get_embeddings", return_value=mock_emb):
            with pytest.raises(IndexError):
                store.add_texts([], metadatas=[])


@pytest.mark.unit
class TestElasticsearchStoreDeleteIndex:
    def test_delete_index_calls_delete_by_query(self):
        store, mock_es, _ = _make_es_store(source_id="src1")

        store.delete_index()

        mock_es.delete_by_query.assert_called_once_with(
            index="test_index",
            query={"match": {"metadata.source_id.keyword": "src1"}},
        )


@pytest.mark.unit
class TestElasticsearchStoreIndex:
    def test_index_returns_mapping(self):
        store, _, _ = _make_es_store()

        mapping = store.index(dims_length=768)

        assert mapping["mappings"]["properties"]["vector"]["type"] == "dense_vector"
        assert mapping["mappings"]["properties"]["vector"]["dims"] == 768
        assert mapping["mappings"]["properties"]["vector"]["similarity"] == "cosine"

    def test_create_index_if_not_exists_existing(self):
        store, mock_es, _ = _make_es_store()
        mock_es.indices.exists.return_value = True

        store._create_index_if_not_exists("test_index", 768)

        mock_es.indices.create.assert_not_called()

    def test_create_index_if_not_exists_new(self):
        store, mock_es, _ = _make_es_store()
        mock_es.indices.exists.return_value = False

        store._create_index_if_not_exists("test_index", 768)

        mock_es.indices.create.assert_called_once()


@pytest.mark.unit
class TestElasticsearchStoreConnectToElasticsearch:
    def test_connect_with_url(self):
        from application.vectorstore.elasticsearch import ElasticsearchStore

        with patch.dict("sys.modules", {"elasticsearch": MagicMock()}):
            import elasticsearch

            mock_es = MagicMock()
            elasticsearch.Elasticsearch.return_value = mock_es

            result = ElasticsearchStore.connect_to_elasticsearch(
                es_url="http://localhost:9200",
                username="user",
                password="pass",
            )
            assert result is mock_es

    def test_connect_with_both_raises(self):
        from application.vectorstore.elasticsearch import ElasticsearchStore

        with patch.dict("sys.modules", {"elasticsearch": MagicMock()}):
            with pytest.raises(ValueError, match="Both es_url and cloud_id"):
                ElasticsearchStore.connect_to_elasticsearch(
                    es_url="http://localhost", cloud_id="cloud-123"
                )

    def test_connect_with_neither_raises(self):
        from application.vectorstore.elasticsearch import ElasticsearchStore

        with patch.dict("sys.modules", {"elasticsearch": MagicMock()}):
            with pytest.raises(ValueError, match="provide either"):
                ElasticsearchStore.connect_to_elasticsearch()

    def test_connect_with_api_key(self):
        from application.vectorstore.elasticsearch import ElasticsearchStore

        with patch.dict("sys.modules", {"elasticsearch": MagicMock()}):
            import elasticsearch

            mock_es = MagicMock()
            elasticsearch.Elasticsearch.return_value = mock_es

            result = ElasticsearchStore.connect_to_elasticsearch(
                es_url="http://localhost:9200",
                api_key="my-api-key",
            )
            assert result is mock_es
