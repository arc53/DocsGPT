"""Unit tests for the Valkey vector store implementation."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from glide_sync import RequestError


def _make_store(source_id="test-source", embeddings_key="key"):
    """Helper to create a ValkeyStore with all external deps mocked."""
    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings"
    ) as mock_get_emb, patch(
        "application.vectorstore.valkey.settings"
    ) as mock_settings, patch(
        "application.vectorstore.valkey.ValkeyStore._create_client"
    ) as mock_create_client, patch(
        "application.vectorstore.valkey.ValkeyStore._ensure_index_exists"
    ):
        mock_emb = Mock()
        mock_emb.embed_query = Mock(return_value=[0.1, 0.2, 0.3])
        mock_emb.embed_documents = Mock(return_value=[[0.1, 0.2, 0.3]])
        mock_emb.dimension = 768
        mock_get_emb.return_value = mock_emb

        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.VALKEY_HOST = "localhost"
        mock_settings.VALKEY_PORT = 6379
        mock_settings.VALKEY_PASSWORD = None
        mock_settings.VALKEY_USE_TLS = False
        mock_settings.VALKEY_INDEX_NAME = "docsgpt"
        mock_settings.VALKEY_PREFIX = "doc:"

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        from application.vectorstore.valkey import ValkeyStore

        store = ValkeyStore(source_id=source_id, embeddings_key=embeddings_key)

    return store, mock_client, mock_emb


@pytest.mark.unit
class TestValkeyStoreInit:
    def test_source_id_cleaned(self):
        store, _, _ = _make_store(source_id="application/indexes/abc123/")
        assert store._source_id == "abc123"

    def test_source_id_simple(self):
        store, _, _ = _make_store(source_id="my-source")
        assert store._source_id == "my-source"


@pytest.mark.unit
class TestValkeyStoreTagEscaping:
    """Tests for _escape_tag_value to ensure source_ids with special chars are safe."""

    def test_escape_dots(self):
        from application.vectorstore.valkey import ValkeyStore

        assert ValkeyStore._escape_tag_value("my.source.v2") == r"my\.source\.v2"

    def test_escape_hyphens(self):
        from application.vectorstore.valkey import ValkeyStore

        assert ValkeyStore._escape_tag_value("my-source") == r"my\-source"

    def test_escape_slashes(self):
        from application.vectorstore.valkey import ValkeyStore

        assert ValkeyStore._escape_tag_value("user/docs") == r"user\/docs"

    def test_escape_colons(self):
        from application.vectorstore.valkey import ValkeyStore

        assert ValkeyStore._escape_tag_value("ns:value") == r"ns\:value"

    def test_escape_spaces(self):
        from application.vectorstore.valkey import ValkeyStore

        assert ValkeyStore._escape_tag_value("my source") == r"my\ source"

    def test_escape_pipe(self):
        from application.vectorstore.valkey import ValkeyStore

        assert ValkeyStore._escape_tag_value("a|b") == r"a\|b"

    def test_no_escape_needed(self):
        from application.vectorstore.valkey import ValkeyStore

        assert ValkeyStore._escape_tag_value("simplesource123") == "simplesource123"

    def test_escape_multiple_special_chars(self):
        from application.vectorstore.valkey import ValkeyStore

        result = ValkeyStore._escape_tag_value("a.b-c/d:e")
        assert result == r"a\.b\-c\/d\:e"

    def test_search_uses_escaped_source_id(self):
        """Verify search query contains escaped source_id."""
        store, mock_client, mock_emb = _make_store(source_id="my.source-v2")

        mock_response = [0]

        with patch("application.vectorstore.valkey.ft.search", return_value=mock_response) as mock_ft:
            store.search("query", k=1)

        call_args = mock_ft.call_args
        query_str = call_args[0][2]
        # Should contain escaped version
        assert r"my\.source\-v2" in query_str


@pytest.mark.unit
class TestValkeyStoreSearch:
    def test_search_returns_documents(self):
        store, mock_client, mock_emb = _make_store()

        # ft.search returns [total_count, {key: {field: value}}, ...]
        mock_response = [
            2,
            {b"doc:id1": {b"content": b"hello world", b"source_id": b"test-source", b"metadata": b'{"source": "test.txt"}'}},
            {b"doc:id2": {b"content": b"foo bar", b"source_id": b"test-source", b"metadata": b'{"source": "test2.txt"}'}},
        ]

        with patch("application.vectorstore.valkey.ft.search", return_value=mock_response):
            results = store.search("query", k=2)

        mock_emb.embed_query.assert_called_once_with("query")
        assert len(results) == 2
        assert results[0].page_content == "hello world"
        assert results[0].metadata == {"source": "test.txt"}
        assert results[1].page_content == "foo bar"

    def test_search_returns_empty_on_error(self):
        store, mock_client, _ = _make_store()

        with patch("application.vectorstore.valkey.ft.search", side_effect=RequestError("connection lost")):
            results = store.search("query")
            assert results == []

    def test_search_returns_empty_on_no_results(self):
        store, mock_client, _ = _make_store()

        with patch("application.vectorstore.valkey.ft.search", return_value=[0]):
            results = store.search("query")
            assert results == []

    def test_search_handles_string_fields(self):
        store, mock_client, _ = _make_store()

        mock_response = [
            1,
            {"doc:id1": {"content": "hello", "source_id": "test-source", "metadata": "{}"}},
        ]

        with patch("application.vectorstore.valkey.ft.search", return_value=mock_response):
            results = store.search("query", k=1)

        assert len(results) == 1
        assert results[0].page_content == "hello"

    def test_search_passes_return_fields(self):
        """Verify search specifies return_fields to avoid fetching embeddings."""
        store, mock_client, _ = _make_store()

        with patch("application.vectorstore.valkey.ft.search", return_value=[0]) as mock_ft:
            store.search("query", k=1)

        call_args = mock_ft.call_args
        options = call_args[0][3]
        assert hasattr(options, "return_fields")

    def test_search_caps_k_to_max(self):
        """Verify k is capped at _MAX_SEARCH_K to prevent memory exhaustion."""
        store, mock_client, _ = _make_store()

        with patch("application.vectorstore.valkey.ft.search", return_value=[0]) as mock_ft:
            store.search("query", k=500)

        call_args = mock_ft.call_args
        query_str = call_args[0][2]
        assert "KNN 100" in query_str

    def test_search_floors_k_to_one(self):
        """Verify k is at least 1."""
        store, mock_client, _ = _make_store()

        with patch("application.vectorstore.valkey.ft.search", return_value=[0]) as mock_ft:
            store.search("query", k=0)

        call_args = mock_ft.call_args
        query_str = call_args[0][2]
        assert "KNN 1" in query_str
    def test_add_texts_returns_ids(self):
        store, mock_client, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client.exec = Mock(return_value=["OK", "OK"])

        ids = store.add_texts(["text1", "text2"], [{"a": 1}, {"b": 2}])

        assert len(ids) == 2
        mock_client.exec.assert_called_once()

    def test_add_texts_empty_returns_empty(self):
        store, _, _ = _make_store()
        assert store.add_texts([]) == []

    def test_add_texts_default_metadatas(self):
        store, mock_client, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_client.exec = Mock(return_value=["OK"])

        ids = store.add_texts(["text1"])
        assert len(ids) == 1

    def test_add_texts_raises_on_error(self):
        store, mock_client, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_client.exec = Mock(side_effect=RequestError("write failed"))

        with pytest.raises(RequestError, match="write failed"):
            store.add_texts(["text1"])

    def test_add_texts_stores_correct_fields(self):
        store, mock_client, mock_emb = _make_store(source_id="src1")
        mock_emb.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_client.exec = Mock(return_value=["OK"])

        with patch("application.vectorstore.valkey.Batch") as MockBatch:
            mock_batch_instance = MagicMock()
            MockBatch.return_value = mock_batch_instance

            store.add_texts(["hello"], [{"key": "val"}])

            # Verify the batch was created as non-atomic (pipeline)
            MockBatch.assert_called_once_with(False)

            # Verify hset was called on the batch with correct fields
            call_args = mock_batch_instance.hset.call_args
            key = call_args[0][0]
            fields = call_args[0][1]

            assert key.startswith("doc:")
            assert fields["content"] == "hello"
            assert fields["source_id"] == "src1"
            assert json.loads(fields["metadata"]) == {"key": "val"}
            assert isinstance(fields["embedding"], bytes)


@pytest.mark.unit
class TestValkeyStoreDeleteIndex:
    def test_delete_index_deletes_matching_docs_in_batch(self):
        """Verify delete_index uses batched deletes."""
        store, mock_client, _ = _make_store(source_id="src123")

        mock_response = [
            2,
            {b"doc:id1": {b"content": b"text1"}},
            {b"doc:id2": {b"content": b"text2"}},
        ]

        with patch("application.vectorstore.valkey.ft.search", return_value=mock_response):
            mock_client.delete = Mock(return_value=2)
            store.delete_index()

        # Should batch both keys into one delete call
        mock_client.delete.assert_called_once()
        deleted_keys = mock_client.delete.call_args[0][0]
        assert len(deleted_keys) == 2

    def test_delete_index_paginates_large_sets(self):
        """Verify delete_index paginates when there are more docs than page size."""
        store, mock_client, _ = _make_store(source_id="src123")

        # Simulate two pages: first returns full page, second returns partial
        from application.vectorstore.valkey import _SCAN_PAGE_SIZE

        page1_entries = [
            {f"doc:id{i}".encode(): {b"content": b"text"}} for i in range(_SCAN_PAGE_SIZE)
        ]
        page1_response = [_SCAN_PAGE_SIZE] + page1_entries

        page2_entries = [
            {b"doc:extra1": {b"content": b"text"}},
            {b"doc:extra2": {b"content": b"text"}},
        ]
        page2_response = [2] + page2_entries

        with patch(
            "application.vectorstore.valkey.ft.search", side_effect=[page1_response, page2_response]
        ):
            mock_client.delete = Mock(return_value=1)
            store.delete_index()

        # Should have multiple delete calls due to batching
        total_deleted = sum(
            len(call[0][0]) for call in mock_client.delete.call_args_list
        )
        assert total_deleted == _SCAN_PAGE_SIZE + 2

    def test_delete_index_raises_on_error(self):
        store, mock_client, _ = _make_store()

        with patch("application.vectorstore.valkey.ft.search", side_effect=RequestError("fail")):
            with pytest.raises(RequestError):
                store.delete_index()


@pytest.mark.unit
class TestValkeyStoreSaveLocal:
    def test_save_local_is_noop(self):
        store, _, _ = _make_store()
        assert store.save_local() is None


@pytest.mark.unit
class TestValkeyStoreGetChunks:
    def test_get_chunks(self):
        store, mock_client, _ = _make_store()

        mock_response = [
            2,
            {b"doc:uuid1": {b"content": b"text1", b"source_id": b"test-source", b"metadata": b'{"key": "val"}'}},
            {b"doc:uuid2": {b"content": b"text2", b"source_id": b"test-source", b"metadata": b"{}"}},
        ]

        with patch("application.vectorstore.valkey.ft.search", return_value=mock_response):
            chunks = store.get_chunks()

        assert len(chunks) == 2
        assert chunks[0] == {"doc_id": "uuid1", "text": "text1", "metadata": {"key": "val"}}
        assert chunks[1] == {"doc_id": "uuid2", "text": "text2", "metadata": {}}

    def test_get_chunks_returns_empty_on_error(self):
        store, mock_client, _ = _make_store()

        with patch("application.vectorstore.valkey.ft.search", side_effect=RequestError("fail")):
            assert store.get_chunks() == []

    def test_get_chunks_uses_return_fields(self):
        """Verify get_chunks specifies return_fields to skip embedding blobs."""
        store, mock_client, _ = _make_store()

        with patch("application.vectorstore.valkey.ft.search", return_value=[0]) as mock_ft:
            store.get_chunks()

        call_args = mock_ft.call_args
        options = call_args[0][3]
        assert hasattr(options, "return_fields")


@pytest.mark.unit
class TestValkeyStoreAddChunk:
    def test_add_chunk(self):
        store, mock_client, mock_emb = _make_store(source_id="src1")
        mock_emb.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_client.hset = Mock(return_value=3)

        chunk_id = store.add_chunk("hello", metadata={"key": "val"})

        assert isinstance(chunk_id, str)
        assert len(chunk_id) > 0
        mock_client.hset.assert_called_once()

    def test_add_chunk_raises_on_empty_embedding(self):
        store, _, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = []

        with pytest.raises(ValueError, match="Could not generate embedding"):
            store.add_chunk("text")

    def test_add_chunk_includes_source_id_in_metadata(self):
        store, mock_client, mock_emb = _make_store(source_id="src1")
        mock_emb.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_client.hset = Mock(return_value=3)

        store.add_chunk("hello", metadata={"key": "val"})

        call_args = mock_client.hset.call_args
        fields = call_args[0][1]
        metadata = json.loads(fields["metadata"])
        assert metadata["source_id"] == "src1"
        assert metadata["key"] == "val"


@pytest.mark.unit
class TestValkeyStoreDeleteChunk:
    def test_delete_chunk_success(self):
        store, mock_client, _ = _make_store()
        mock_client.delete = Mock(return_value=1)

        result = store.delete_chunk("uuid-123")
        assert result is True
        mock_client.delete.assert_called_once_with(["doc:uuid-123"])

    def test_delete_chunk_not_found(self):
        store, mock_client, _ = _make_store()
        mock_client.delete = Mock(return_value=0)

        result = store.delete_chunk("nonexistent")
        assert result is False

    def test_delete_chunk_returns_false_on_error(self):
        store, mock_client, _ = _make_store()
        mock_client.delete = Mock(side_effect=RequestError("fail"))

        result = store.delete_chunk("uuid-123")
        assert result is False


@pytest.mark.unit
class TestValkeyStoreCreateClient:
    """Tests for password handling in _create_client."""

    def test_password_none_skips_credentials(self):
        """When VALKEY_PASSWORD is None, no credentials should be passed."""
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings"
        ) as mock_get_emb, patch(
            "application.vectorstore.valkey.settings"
        ) as mock_settings, patch(
            "application.vectorstore.valkey.GlideClientConfiguration"
        ) as mock_config_cls, patch(
            "application.vectorstore.valkey.GlideClient"
        ) as mock_glide_cls, patch(
            "application.vectorstore.valkey.ValkeyStore._ensure_index_exists"
        ):
            mock_emb = Mock()
            mock_emb.dimension = 768
            mock_get_emb.return_value = mock_emb
            mock_settings.EMBEDDINGS_NAME = "test"
            mock_settings.VALKEY_HOST = "localhost"
            mock_settings.VALKEY_PORT = 6379
            mock_settings.VALKEY_PASSWORD = None
            mock_settings.VALKEY_USE_TLS = False
            mock_settings.VALKEY_INDEX_NAME = "docsgpt"
            mock_settings.VALKEY_PREFIX = "doc:"
            mock_glide_cls.create = Mock(return_value=MagicMock())

            from application.vectorstore.valkey import ValkeyStore

            ValkeyStore(source_id="test", embeddings_key="key")

            # Verify no credentials kwarg
            config_call_kwargs = mock_config_cls.call_args[1]
            assert "credentials" not in config_call_kwargs

    def test_empty_string_password_skips_credentials(self):
        """When VALKEY_PASSWORD is empty string, no credentials should be passed."""
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings"
        ) as mock_get_emb, patch(
            "application.vectorstore.valkey.settings"
        ) as mock_settings, patch(
            "application.vectorstore.valkey.GlideClientConfiguration"
        ) as mock_config_cls, patch(
            "application.vectorstore.valkey.GlideClient"
        ) as mock_glide_cls, patch(
            "application.vectorstore.valkey.ValkeyStore._ensure_index_exists"
        ):
            mock_emb = Mock()
            mock_emb.dimension = 768
            mock_get_emb.return_value = mock_emb
            mock_settings.EMBEDDINGS_NAME = "test"
            mock_settings.VALKEY_HOST = "localhost"
            mock_settings.VALKEY_PORT = 6379
            mock_settings.VALKEY_PASSWORD = ""
            mock_settings.VALKEY_USE_TLS = False
            mock_settings.VALKEY_INDEX_NAME = "docsgpt"
            mock_settings.VALKEY_PREFIX = "doc:"
            mock_glide_cls.create = Mock(return_value=MagicMock())

            from application.vectorstore.valkey import ValkeyStore

            ValkeyStore(source_id="test", embeddings_key="key")

            # Verify no credentials kwarg
            config_call_kwargs = mock_config_cls.call_args[1]
            assert "credentials" not in config_call_kwargs

    def test_non_empty_password_sets_credentials(self):
        """When VALKEY_PASSWORD has a value, credentials should be passed."""
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings"
        ) as mock_get_emb, patch(
            "application.vectorstore.valkey.settings"
        ) as mock_settings, patch(
            "application.vectorstore.valkey.GlideClientConfiguration"
        ) as mock_config_cls, patch(
            "application.vectorstore.valkey.GlideClient"
        ) as mock_glide_cls, patch(
            "application.vectorstore.valkey.ValkeyStore._ensure_index_exists"
        ), patch(
            "application.vectorstore.valkey.ServerCredentials"
        ) as mock_creds:
            mock_emb = Mock()
            mock_emb.dimension = 768
            mock_get_emb.return_value = mock_emb
            mock_settings.EMBEDDINGS_NAME = "test"
            mock_settings.VALKEY_HOST = "localhost"
            mock_settings.VALKEY_PORT = 6379
            mock_settings.VALKEY_PASSWORD = "secret123"
            mock_settings.VALKEY_USE_TLS = False
            mock_settings.VALKEY_INDEX_NAME = "docsgpt"
            mock_settings.VALKEY_PREFIX = "doc:"
            mock_glide_cls.create = Mock(return_value=MagicMock())

            from application.vectorstore.valkey import ValkeyStore

            ValkeyStore(source_id="test", embeddings_key="key")

            # Verify credentials kwarg was passed
            config_call_kwargs = mock_config_cls.call_args[1]
            assert "credentials" in config_call_kwargs
            mock_creds.assert_called_once_with(password="secret123")


@pytest.mark.unit
class TestValkeyStoreSchemaConfig:
    """Tests for configurable distance metric, vector type, and algorithm."""

    def test_resolve_distance_metric_cosine(self):
        from application.vectorstore.valkey import ValkeyStore

        from glide_sync import DistanceMetricType

        assert ValkeyStore._resolve_distance_metric("cosine") == DistanceMetricType.COSINE

    def test_resolve_distance_metric_l2(self):
        from application.vectorstore.valkey import ValkeyStore

        from glide_sync import DistanceMetricType

        assert ValkeyStore._resolve_distance_metric("l2") == DistanceMetricType.L2

    def test_resolve_distance_metric_ip(self):
        from application.vectorstore.valkey import ValkeyStore

        from glide_sync import DistanceMetricType

        assert ValkeyStore._resolve_distance_metric("ip") == DistanceMetricType.IP

    def test_resolve_distance_metric_invalid_falls_back(self):
        from application.vectorstore.valkey import ValkeyStore

        from glide_sync import DistanceMetricType

        assert ValkeyStore._resolve_distance_metric("invalid") == DistanceMetricType.COSINE

    def test_resolve_distance_metric_case_insensitive(self):
        from application.vectorstore.valkey import ValkeyStore

        from glide_sync import DistanceMetricType

        assert ValkeyStore._resolve_distance_metric("COSINE") == DistanceMetricType.COSINE
        assert ValkeyStore._resolve_distance_metric("L2") == DistanceMetricType.L2

    def test_resolve_vector_type_float32(self):
        from application.vectorstore.valkey import ValkeyStore

        from glide_sync import VectorType

        assert ValkeyStore._resolve_vector_type("float32") == VectorType.FLOAT32

    def test_resolve_vector_type_invalid_falls_back(self):
        from application.vectorstore.valkey import ValkeyStore

        from glide_sync import VectorType

        assert ValkeyStore._resolve_vector_type("float64") == VectorType.FLOAT32

    def test_resolve_vector_algorithm_hnsw(self):
        from application.vectorstore.valkey import ValkeyStore

        from glide_sync import VectorAlgorithm

        assert ValkeyStore._resolve_vector_algorithm("hnsw") == VectorAlgorithm.HNSW

    def test_resolve_vector_algorithm_flat(self):
        from application.vectorstore.valkey import ValkeyStore

        from glide_sync import VectorAlgorithm

        assert ValkeyStore._resolve_vector_algorithm("flat") == VectorAlgorithm.FLAT

    def test_resolve_vector_algorithm_invalid_falls_back(self):
        from application.vectorstore.valkey import ValkeyStore

        from glide_sync import VectorAlgorithm

        assert ValkeyStore._resolve_vector_algorithm("annoy") == VectorAlgorithm.HNSW


@pytest.mark.unit
class TestValkeyStoreClose:
    """Tests for client resource cleanup."""

    def test_close_calls_client_close(self):
        store, mock_client, _ = _make_store()

        store.close()

        mock_client.close.assert_called_once()
        assert store._client is None

    def test_close_is_idempotent(self):
        store, mock_client, _ = _make_store()

        store.close()
        store.close()  # second call should not raise

        mock_client.close.assert_called_once()

    def test_close_handles_exception(self):
        store, mock_client, _ = _make_store()
        mock_client.close = Mock(side_effect=Exception("already closed"))

        # Should not raise
        store.close()
        assert store._client is None

    def test_context_manager_calls_close(self):
        store, mock_client, _ = _make_store()

        store.__enter__()
        store.__exit__(None, None, None)

        mock_client.close.assert_called_once()
        assert store._client is None


@pytest.mark.unit
class TestValkeyStoreEnsureIndex:
    """Tests for _ensure_index_exists with FLAT algorithm path."""

    def test_ensure_index_flat_algorithm(self):
        """Verify FLAT algorithm path creates index without error."""
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings"
        ) as mock_get_emb, patch(
            "application.vectorstore.valkey.settings"
        ) as mock_settings, patch(
            "application.vectorstore.valkey.ValkeyStore._create_client"
        ) as mock_create_client, patch(
            "application.vectorstore.valkey.ft"
        ) as mock_ft:
            mock_emb = Mock()
            mock_emb.dimension = 128
            mock_get_emb.return_value = mock_emb

            mock_settings.EMBEDDINGS_NAME = "test"
            mock_settings.VALKEY_HOST = "localhost"
            mock_settings.VALKEY_PORT = 6379
            mock_settings.VALKEY_PASSWORD = None
            mock_settings.VALKEY_USE_TLS = False
            mock_settings.VALKEY_INDEX_NAME = "test_idx"
            mock_settings.VALKEY_PREFIX = "doc:"
            mock_settings.VALKEY_DISTANCE_METRIC = "l2"
            mock_settings.VALKEY_VECTOR_TYPE = "float32"
            mock_settings.VALKEY_VECTOR_ALGORITHM = "flat"

            mock_client = MagicMock()
            mock_create_client.return_value = mock_client

            from application.vectorstore.valkey import ValkeyStore

            # This should not raise — exercises the FLAT branch
            ValkeyStore(source_id="test", embeddings_key="key")

            # Verify ft.create was called with the schema
            mock_ft.create.assert_called_once()

    def test_ensure_index_already_exists_is_silent(self):
        """Verify 'already exists' error is handled gracefully."""
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings"
        ) as mock_get_emb, patch(
            "application.vectorstore.valkey.settings"
        ) as mock_settings, patch(
            "application.vectorstore.valkey.ValkeyStore._create_client"
        ) as mock_create_client, patch(
            "application.vectorstore.valkey.ft"
        ) as mock_ft:
            mock_emb = Mock()
            mock_emb.dimension = 768
            mock_get_emb.return_value = mock_emb

            mock_settings.EMBEDDINGS_NAME = "test"
            mock_settings.VALKEY_HOST = "localhost"
            mock_settings.VALKEY_PORT = 6379
            mock_settings.VALKEY_PASSWORD = None
            mock_settings.VALKEY_USE_TLS = False
            mock_settings.VALKEY_INDEX_NAME = "test_idx"
            mock_settings.VALKEY_PREFIX = "doc:"
            mock_settings.VALKEY_DISTANCE_METRIC = "cosine"
            mock_settings.VALKEY_VECTOR_TYPE = "float32"
            mock_settings.VALKEY_VECTOR_ALGORITHM = "hnsw"

            mock_client = MagicMock()
            mock_create_client.return_value = mock_client

            # Simulate "Index already exists" error (must be RequestError)
            mock_ft.create.side_effect = RequestError("Index already exists")

            from application.vectorstore.valkey import ValkeyStore

            # Should not raise
            store = ValkeyStore(source_id="test", embeddings_key="key")
            assert store is not None

    def test_ensure_index_unknown_error_raises(self):
        """Verify non-'already exists' errors are re-raised."""
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings"
        ) as mock_get_emb, patch(
            "application.vectorstore.valkey.settings"
        ) as mock_settings, patch(
            "application.vectorstore.valkey.ValkeyStore._create_client"
        ) as mock_create_client, patch(
            "application.vectorstore.valkey.ft"
        ) as mock_ft:
            mock_emb = Mock()
            mock_emb.dimension = 768
            mock_get_emb.return_value = mock_emb

            mock_settings.EMBEDDINGS_NAME = "test"
            mock_settings.VALKEY_HOST = "localhost"
            mock_settings.VALKEY_PORT = 6379
            mock_settings.VALKEY_PASSWORD = None
            mock_settings.VALKEY_USE_TLS = False
            mock_settings.VALKEY_INDEX_NAME = "test_idx"
            mock_settings.VALKEY_PREFIX = "doc:"
            mock_settings.VALKEY_DISTANCE_METRIC = "cosine"
            mock_settings.VALKEY_VECTOR_TYPE = "float32"
            mock_settings.VALKEY_VECTOR_ALGORITHM = "hnsw"

            mock_client = MagicMock()
            mock_create_client.return_value = mock_client

            mock_ft.create.side_effect = Exception("Connection refused")

            from application.vectorstore.valkey import ValkeyStore

            with pytest.raises(Exception, match="Connection refused"):
                ValkeyStore(source_id="test", embeddings_key="key")
