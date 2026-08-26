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
