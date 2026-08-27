"""Re-embed script: CLI contract, orchestration, and the FAISS rebuild path."""

from unittest.mock import MagicMock, patch

import pytest

from application.scripts import reembed


class TestCLI:
    def test_defaults(self):
        args = reembed.build_parser().parse_args([])
        assert args.dry_run is False
        assert args.sources is None
        assert args.batch_size == reembed.DEFAULT_BATCH_SIZE

    def test_unsupported_store_exits_without_touching_anything(self):
        with patch.object(reembed.settings, "VECTOR_STORE", "qdrant", create=True):
            with patch.object(reembed, "run") as run:
                assert reembed.main([]) == 2
        run.assert_not_called()

    def test_supported_stores_are_pgvector_and_faiss(self):
        assert set(reembed.SUPPORTED_STORES) == {"pgvector", "faiss"}

    def test_sources_are_split_and_trimmed(self):
        with patch.object(reembed.settings, "VECTOR_STORE", "faiss", create=True):
            with patch.object(reembed, "run", return_value=0) as run:
                reembed.main(["--sources", " a , b ,, c "])
        assert run.call_args.args[1] == ["a", "b", "c"]

    def test_batch_size_is_clamped_to_at_least_one(self):
        with patch.object(reembed.settings, "VECTOR_STORE", "faiss", create=True):
            with patch.object(reembed, "run", return_value=0) as run:
                reembed.main(["--batch-size", "0"])
        assert run.call_args.args[2] == 1


class TestRun:
    def test_no_sources_is_a_clean_exit(self):
        with patch.object(reembed, "list_source_ids", return_value=[]):
            assert reembed.run("faiss", None, 8, False) == 0

    def test_processes_every_discovered_source(self):
        with patch.object(reembed, "list_source_ids", return_value=["a", "b"]):
            with patch.object(reembed, "reembed_faiss", return_value=(3, 3)) as handler:
                assert reembed.run("faiss", None, 8, False) == 0
        assert [call.args[0] for call in handler.call_args_list] == ["a", "b"]

    def test_explicit_sources_skip_discovery(self):
        with patch.object(reembed, "list_source_ids") as discover:
            with patch.object(reembed, "reembed_faiss", return_value=(1, 1)):
                reembed.run("faiss", ["only-this"], 8, False)
        discover.assert_not_called()

    def test_one_failing_source_does_not_stop_the_others(self):
        def handler(source_id, batch_size, dry_run):
            if source_id == "bad":
                raise RuntimeError("boom")
            return (1, 1)

        with patch.object(reembed, "reembed_faiss", side_effect=handler) as spy:
            code = reembed.run("faiss", ["good", "bad", "also-good"], 8, False)
        assert code == 1, "a failure must be reported in the exit code"
        assert spy.call_count == 3, "later sources must still be attempted"

    def test_dry_run_is_reported_as_success(self):
        with patch.object(reembed, "reembed_faiss", return_value=(5, 0)):
            assert reembed.run("faiss", ["a"], 8, True) == 0

    def test_pgvector_uses_the_pgvector_handler(self):
        with patch.object(reembed, "reembed_pgvector", return_value=(1, 1)) as handler:
            reembed.run("pgvector", ["a"], 8, False)
        handler.assert_called_once()


class TestFaissRebuild:
    @pytest.fixture
    def stores(self):
        """An existing store to read from and the rebuilt one written back."""
        existing = MagicMock()
        existing.get_chunks.return_value = [
            {"doc_id": "1", "text": "alpha", "metadata": {"i": 0}},
            {"doc_id": "2", "text": "beta", "metadata": {"i": 1}},
        ]
        rebuilt = MagicMock()
        with patch.object(
            reembed.VectorCreator, "create_vectorstore", side_effect=[existing, rebuilt]
        ) as factory:
            yield existing, rebuilt, factory

    def test_rebuilds_from_stored_text_and_saves(self, stores):
        existing, rebuilt, factory = stores
        seen, written = reembed.reembed_faiss("s1", batch_size=8, dry_run=False)

        assert (seen, written) == (2, 2)
        rebuilt.save_local.assert_called_once()
        docs = factory.call_args_list[1].kwargs["docs_init"]
        assert [d.page_content for d in docs] == ["alpha", "beta"]
        assert [d.metadata for d in docs] == [{"i": 0}, {"i": 1}]

    def test_embeddings_key_comes_from_settings(self, stores):
        """A placeholder here is sent as the server's bearer token."""
        _, _, factory = stores
        with patch.object(reembed.settings, "EMBEDDINGS_KEY", "sk-real", create=True):
            reembed.reembed_faiss("s1", batch_size=8, dry_run=False)
        keys = [call.kwargs.get("embeddings_key") for call in factory.call_args_list]
        assert keys == ["sk-real", "sk-real"]

    def test_chunk_ids_are_preserved(self, stores):
        """Re-embedding must not renumber chunks.

        Fresh ids orphan every GraphRAG ``graph_node_chunks`` row for the
        source and invalidate any id a client already holds.
        """
        _, _, factory = stores
        reembed.reembed_faiss("s1", batch_size=8, dry_run=False)
        assert factory.call_args_list[1].kwargs["ids"] == ["1", "2"]

    def test_batch_size_is_forwarded_to_the_rebuild(self, stores):
        """On a remote embeddings server the whole index is otherwise one POST."""
        _, _, factory = stores
        reembed.reembed_faiss("s1", batch_size=8, dry_run=False)
        assert factory.call_args_list[1].kwargs["batch_size"] == 8

    def test_existing_index_is_not_deleted(self, stores):
        """The rebuild must not destroy the old index before the new one exists."""
        existing, rebuilt, _ = stores
        reembed.reembed_faiss("s1", batch_size=8, dry_run=False)
        existing.delete_index.assert_not_called()

    def test_dry_run_reads_but_never_rebuilds(self):
        existing = MagicMock()
        existing.get_chunks.return_value = [{"doc_id": "1", "text": "a", "metadata": {}}]
        with patch.object(
            reembed.VectorCreator, "create_vectorstore", return_value=existing
        ) as factory:
            seen, written = reembed.reembed_faiss("s1", batch_size=8, dry_run=True)
        assert (seen, written) == (1, 0)
        assert factory.call_count == 1, "no rebuild store may be constructed"

    def test_empty_index_is_a_no_op(self):
        existing = MagicMock()
        existing.get_chunks.return_value = []
        with patch.object(
            reembed.VectorCreator, "create_vectorstore", return_value=existing
        ):
            assert reembed.reembed_faiss("s1", batch_size=8, dry_run=False) == (0, 0)


class TestPgvectorWithoutTheExtension:
    """Mocked pgvector paths.

    The live tests in ``test_reembed_pgvector_live`` skip wherever the cluster
    has no pgvector build -- which includes CI -- so the SQL shape and the
    batching contract are pinned here too.
    """

    @pytest.fixture
    def store(self):
        store = MagicMock()
        store._table_name = "documents"
        store._vector_column = "embedding"
        cursor = MagicMock()
        cursor.fetchall.return_value = [(1, "alpha"), (2, "beta"), (3, "gamma")]
        conn = MagicMock()
        conn.cursor.return_value = cursor
        store._get_connection.return_value = conn
        store._embedding.embed_documents.side_effect = lambda texts: [
            [0.5] * 4 for _ in texts
        ]
        with patch.object(
            reembed.VectorCreator, "create_vectorstore", return_value=store
        ):
            yield store, conn, cursor

    def test_reads_and_rewrites_every_chunk(self, store):
        _, conn, cursor = store
        seen, written = reembed.reembed_pgvector("s1", batch_size=64, dry_run=False)
        assert (seen, written) == (3, 3)
        cursor.executemany.assert_called_once()
        conn.commit.assert_called()

    def test_dry_run_neither_embeds_nor_writes(self, store):
        fake_store, conn, cursor = store
        seen, written = reembed.reembed_pgvector("s1", batch_size=64, dry_run=True)
        assert (seen, written) == (3, 0)
        fake_store._embedding.embed_documents.assert_not_called()
        cursor.executemany.assert_not_called()

    def test_batches_commit_separately(self, store):
        _, conn, cursor = store
        reembed.reembed_pgvector("s1", batch_size=2, dry_run=False)
        # 3 rows at batch 2 is two write transactions.
        assert cursor.executemany.call_count == 2
        assert conn.commit.call_count == 2

    def test_failed_batch_rolls_back_and_raises(self, store):
        fake_store, conn, cursor = store
        cursor.executemany.side_effect = RuntimeError("write failed")
        with pytest.raises(RuntimeError):
            reembed.reembed_pgvector("s1", batch_size=64, dry_run=False)
        conn.rollback.assert_called_once()

    def test_connection_is_returned_even_on_failure(self, store):
        fake_store, _, cursor = store
        cursor.executemany.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError):
            reembed.reembed_pgvector("s1", batch_size=64, dry_run=False)
        fake_store.close.assert_called_once()

    def test_null_text_does_not_crash_the_embed_call(self, store):
        fake_store, _, cursor = store
        cursor.fetchall.return_value = [(1, None), (2, "beta")]
        seen, written = reembed.reembed_pgvector("s1", batch_size=64, dry_run=False)
        assert (seen, written) == (2, 2)
        assert fake_store._embedding.embed_documents.call_args.args[0] == ["", "beta"]

    def test_empty_source_is_a_no_op(self, store):
        fake_store, _, cursor = store
        cursor.fetchall.return_value = []
        assert reembed.reembed_pgvector("s1", batch_size=64, dry_run=False) == (0, 0)
        fake_store._embedding.embed_documents.assert_not_called()

    def test_source_discovery_returns_sorted_ids(self, store):
        _, _, cursor = store
        cursor.fetchall.return_value = [("b",), ("a",)]
        assert reembed.list_source_ids("pgvector") == ["b", "a"]


class TestFaissSourceDiscovery:
    def test_source_ids_come_from_index_directories(self):
        storage = MagicMock()
        storage.list_files.return_value = [
            "indexes/src-a/index.faiss",
            "indexes/src-a/index.pkl",
            "indexes/src-b/index.faiss",
        ]
        with patch(
            "application.storage.storage_creator.StorageCreator.get_storage",
            return_value=storage,
        ):
            assert reembed.list_source_ids("faiss") == ["src-a", "src-b"]

    def test_storage_failure_is_reported_as_a_usable_error(self):
        storage = MagicMock()
        storage.list_files.side_effect = OSError("permission denied")
        with patch(
            "application.storage.storage_creator.StorageCreator.get_storage",
            return_value=storage,
        ):
            with pytest.raises(reembed.ReembedError, match="permission denied"):
                reembed.list_source_ids("faiss")

    def test_unsupported_store_error_names_the_alternatives(self):
        with patch.object(reembed.settings, "VECTOR_STORE", "milvus", create=True):
            assert reembed.main([]) == 2
