import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects.mysql import dialect as mysql_dialect


@pytest.mark.unit
def test_oceanbase_connection_setting_is_opt_in():
    """Only the OceanBase connection is exposed as a setting."""
    from application.core.settings import Settings

    assert Settings.model_fields["OCEANBASE_URI"].default is None
    assert "OCEANBASE_TABLE_NAME" not in Settings.model_fields


class FakeOceanbaseVectorStore:
    """Small stand-in for the optional langchain-oceanbase dependency."""

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.add_texts = MagicMock()
        self.similarity_search_with_score = MagicMock()
        self.obvector = MagicMock()
        self.obvector.engine.dialect = mysql_dialect()
        self.obvector.check_table_exists.return_value = True
        self.primary_field = "id"
        self.text_field = "document"
        self.metadata_field = "metadata"


def _make_store(
    source_id="source-1",
    connection_string=("mysql://root%40tenant:p%40ss@ob.example.com:2883/vectors"),
):
    from application.vectorstore.oceanbase import OceanBaseStore

    embedding = MagicMock(dimension=768)
    settings = SimpleNamespace(
        EMBEDDINGS_NAME="test-embedding",
        OCEANBASE_URI=None,
    )

    with (
        patch("application.vectorstore.oceanbase.settings", settings),
        patch.object(OceanBaseStore, "_get_embeddings", return_value=embedding),
        patch(
            "application.vectorstore.oceanbase._import_oceanbase_vector_store",
            return_value=FakeOceanbaseVectorStore,
        ),
    ):
        store = OceanBaseStore(
            source_id=source_id,
            embeddings_key="key",
            connection_string=connection_string,
        )

    return store, store._docsearch, store._client, embedding


@pytest.mark.unit
class TestOceanBaseStoreInit:
    def test_initializes_langchain_store_with_cosine_and_source_column(self):
        store, backend, _, embedding = _make_store(source_id="application/indexes/source-1/")

        assert store._source_id == "source-1"
        assert backend.init_kwargs["embedding_function"] is embedding
        assert backend.init_kwargs["table_name"] == "docsgpt"
        assert backend.init_kwargs["connection_args"] == {
            "host": "ob.example.com",
            "port": "2883",
            "user": "root@tenant",
            "password": "p@ss",
            "db_name": "vectors",
        }
        assert backend.init_kwargs["vidx_metric_type"] == "cosine"

        extra_columns = backend.init_kwargs["extra_columns"]
        assert len(extra_columns) == 1
        assert extra_columns[0].name == "source_id"
        assert extra_columns[0].nullable is False

    def test_uses_connection_string_from_settings(self):
        from application.vectorstore.oceanbase import OceanBaseStore

        settings = SimpleNamespace(
            EMBEDDINGS_NAME="test-embedding",
            OCEANBASE_URI=("mysql://root%40tenant:secret@127.0.0.1:2881/test"),
        )
        with (
            patch("application.vectorstore.oceanbase.settings", settings),
            patch.object(OceanBaseStore, "_get_embeddings", return_value=MagicMock()),
            patch(
                "application.vectorstore.oceanbase._import_oceanbase_vector_store",
                return_value=FakeOceanbaseVectorStore,
            ),
        ):
            store = OceanBaseStore(source_id="source-1")

        assert store._table_name == "docsgpt"
        assert store._docsearch.init_kwargs["connection_args"]["user"] == "root@tenant"

    def test_missing_connection_string_raises(self):
        from application.vectorstore.oceanbase import OceanBaseStore

        settings = SimpleNamespace(
            EMBEDDINGS_NAME="test-embedding",
            OCEANBASE_URI=None,
        )
        with (
            patch("application.vectorstore.oceanbase.settings", settings),
            pytest.raises(ValueError, match="OceanBase connection string"),
        ):
            OceanBaseStore(source_id="source-1")

    def test_invalid_connection_scheme_raises(self):
        from application.vectorstore.oceanbase import OceanBaseStore

        for connection_string in (
            "oceanbase://user:password@localhost/database",
            "mysql+oceanbase://user:password@localhost/database",
            "postgresql://user:password@localhost/database",
        ):
            with pytest.raises(ValueError, match="Unsupported OceanBase connection"):
                OceanBaseStore._parse_connection_string(connection_string)

    @pytest.mark.parametrize(
        ("connection_string", "message"),
        [
            ("", "must not be empty"),
            ("mysql://user:password@/database", "include a host"),
            ("mysql://localhost/database", "include a user"),
            ("mysql://user:password@localhost", "database name"),
            ("mysql://user:password@localhost/one/two", "database name"),
            ("mysql://user:password@localhost:not-a-port/database", "invalid port"),
            ("mysql://user:password@localhost/database", "include a port"),
        ],
    )
    def test_rejects_malformed_connection_strings(self, connection_string, message):
        from application.vectorstore.oceanbase import OceanBaseStore

        with pytest.raises(ValueError, match=message):
            OceanBaseStore._parse_connection_string(connection_string)

    def test_source_filter_quotes_the_source_id_as_a_sql_literal(self):
        store, _, _, _ = _make_store(source_id="source' OR 1=1 --")

        assert store._source_filter == "source_id = 'source'' OR 1=1 --'"


@pytest.mark.unit
class TestOceanBaseStoreWrites:
    def test_add_texts_adds_source_isolation_and_returns_ids(self):
        store, backend, _, _ = _make_store()
        backend.add_texts.side_effect = lambda *args, **kwargs: kwargs["ids"]

        metadata = {"source": "guide.md", "source_id": "untrusted"}
        ids = store.add_texts(["hello"], [metadata])

        assert len(ids) == 1
        call = backend.add_texts.call_args
        assert call.args == (["hello"], [{"source": "guide.md", "source_id": "source-1"}])
        assert call.kwargs["extras"] == [{"source_id": "source-1"}]
        assert call.kwargs["ids"] == ids
        assert metadata["source_id"] == "untrusted"

    def test_add_texts_raises_if_langchain_swallows_a_partial_batch(self):
        store, backend, _, _ = _make_store()
        backend.add_texts.return_value = []

        with pytest.raises(RuntimeError, match="inserted 0 of 1"):
            store.add_texts(["hello"], [{}])

    def test_add_chunk_delegates_to_add_texts(self):
        store, _, _, _ = _make_store()

        with patch.object(store, "add_texts", return_value=["chunk-1"]) as add_texts:
            chunk_id = store.add_chunk("hello", {"source": "guide.md"})

        assert chunk_id == "chunk-1"
        add_texts.assert_called_once_with(["hello"], [{"source": "guide.md"}])

    def test_add_texts_validates_empty_and_mismatched_inputs(self):
        store, _, _, _ = _make_store()

        assert store.add_texts([]) == []
        with pytest.raises(ValueError, match="metadatas"):
            store.add_texts(["one", "two"], [{}])
        with pytest.raises(ValueError, match="ids"):
            store.add_texts(["one"], [{}], ids=["one", "two"])
        with pytest.raises(ValueError, match="reserves extras"):
            store.add_texts(["one"], [{}], extras=[{}])


@pytest.mark.unit
class TestOceanBaseStoreSearch:
    def test_converts_cosine_distance_and_applies_similarity_threshold(self):
        store, backend, _, _ = _make_store()
        backend.similarity_search_with_score.return_value = [
            (
                SimpleNamespace(id="near", page_content="near", metadata={"source": "a.md"}),
                0.10,
            ),
            (
                SimpleNamespace(id="far", page_content="far", metadata={"source": "b.md"}),
                0.40,
            ),
        ]

        results = store.search_with_scores("question", k=5, score_threshold=0.85)

        assert len(results) == 1
        assert results[0][0].page_content == "near"
        assert results[0][0].metadata == {"source": "a.md"}
        assert results[0][1] == pytest.approx(0.90)

        call = backend.similarity_search_with_score.call_args
        assert call.args == ("question", 5)
        assert call.kwargs["distance_threshold"] == pytest.approx(0.15)
        assert "source_id" in call.kwargs["fltr"]
        assert "source-1" in call.kwargs["fltr"]

    def test_search_returns_documents_without_scores(self):
        store, _, _, _ = _make_store()
        expected = [
            (
                SimpleNamespace(page_content="near", metadata={}, id="near"),
                0.9,
            )
        ]

        with patch.object(store, "search_with_scores", return_value=expected):
            results = store.search("question", k=1)

        assert [document.page_content for document in results] == ["near"]

    def test_search_reserves_filter_for_source_isolation_and_skips_missing_distance(self):
        store, backend, _, _ = _make_store()
        backend.similarity_search_with_score.return_value = [
            (SimpleNamespace(page_content="missing", metadata={}, id=None), None),
            (SimpleNamespace(page_content="found", metadata={}, id=None), 0.25),
        ]

        results = store.search_with_scores("question", fltr="document IS NOT NULL")

        assert [(document.page_content, score) for document, score in results] == [("found", 0.75)]
        applied_filter = backend.similarity_search_with_score.call_args.kwargs["fltr"]
        assert applied_filter == store._source_filter

    def test_search_short_circuits_for_non_positive_k_or_missing_table(self):
        store, backend, client, _ = _make_store()

        assert store.search_with_scores("question", k=0) == []

        client.check_table_exists.return_value = False
        assert store.search_with_scores("question", k=2) == []
        backend.similarity_search_with_score.assert_not_called()


@pytest.mark.unit
class TestOceanBaseStoreChunks:
    def test_get_chunks_uses_pyobvector_and_decodes_metadata(self):
        store, _, client, _ = _make_store()
        client.get.return_value = [("chunk-1", "hello", json.dumps({"source": "guide.md"}))]

        chunks = store.get_chunks()

        assert chunks == [
            {
                "doc_id": "chunk-1",
                "text": "hello",
                "metadata": {"source": "guide.md"},
            }
        ]
        assert client.get.call_args.kwargs["output_column_name"] == [
            "id",
            "document",
            "metadata",
        ]

    def test_delete_chunk_checks_source_before_deleting(self):
        store, _, client, _ = _make_store()

        with (
            patch.object(store, "_get_matching_ids", return_value=["chunk-1"]) as get_ids,
            patch.object(store, "_delete_ids") as delete_ids,
        ):
            deleted = store.delete_chunk("chunk-1")

        assert deleted is True
        get_ids.assert_called_once_with(ids=["chunk-1"], limit=1)
        delete_ids.assert_called_once_with(["chunk-1"])
        client.delete.assert_not_called()

    def test_delete_chunks_by_source_path_deletes_by_condition_and_returns_rowcount(self):
        store, _, _, _ = _make_store()
        path_condition = MagicMock()
        source_condition = MagicMock()

        with (
            patch.object(store, "_metadata_source_condition", return_value=path_condition),
            patch.object(store, "_source_condition", return_value=source_condition),
            patch.object(store, "_delete_where", return_value=2) as delete_where,
        ):
            count = store.delete_chunks_by_source_path("guide.md")

        assert count == 2
        delete_where.assert_called_once_with(source_condition, path_condition)

    def test_delete_chunks_by_source_path_returns_zero_when_nothing_deleted(self):
        store, _, _, _ = _make_store()

        with patch.object(store, "_delete_where", return_value=0):
            count = store.delete_chunks_by_source_path("guide.md")

        assert count == 0

    def test_matching_ids_and_delete_ids_use_source_conditions(self):
        store, _, client, _ = _make_store()
        source_condition = MagicMock()
        client.get.return_value = [("chunk-1",), (None,), ()]

        with patch.object(store, "_source_condition", return_value=source_condition):
            matching_ids = store._get_matching_ids(
                ids=["chunk-1"],
                limit=1,
                extra_conditions=[MagicMock()],
            )
            store._delete_ids(matching_ids)
            store._delete_ids([])

        assert matching_ids == ["chunk-1"]
        assert client.get.call_args.kwargs["ids"] == ["chunk-1"]
        assert client.get.call_args.kwargs["n_limits"] == 1
        client.delete.assert_called_once_with(
            table_name="docsgpt",
            ids=["chunk-1"],
            where_clause=[source_condition],
        )

    def test_missing_table_makes_chunk_operations_noops(self):
        store, _, client, _ = _make_store()
        client.check_table_exists.return_value = False

        assert store.get_chunks() == []
        assert store.delete_chunk("chunk-1") is False
        assert store.delete_chunks_by_source_path("guide.md") == 0
        store.delete_index()
        client.get.assert_not_called()
        client.delete.assert_not_called()

    def test_delete_index_only_deletes_the_current_source(self):
        store, _, client, _ = _make_store()
        source_condition = MagicMock()

        with patch.object(store, "_source_condition", return_value=source_condition):
            store.delete_index()

        client.delete.assert_called_once_with(
            table_name="docsgpt",
            where_clause=[source_condition],
        )
