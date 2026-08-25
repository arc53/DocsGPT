import pytest
import logging
from unittest.mock import patch, MagicMock

from application.parser.embedding_pipeline import (
    DEFAULT_EMBEDDINGS_BATCH_SIZE,
    EmbeddingPipelineError,
    _resolve_batch_size,
    add_text_to_store_with_retry,
    add_texts_to_store_with_retry,
    assert_index_complete,
    embed_and_store_documents,
    sanitize_content,
)



def test_sanitize_content_removes_nulls():
    content = "This\x00is\x00a\x00test"
    result = sanitize_content(content)
    assert "\x00" not in result
    assert result == "Thisisatest"


def test_sanitize_content_empty_or_none():
    assert sanitize_content("") == ""
    assert sanitize_content(None) is None



def test_add_text_to_store_with_retry_success():
    store = MagicMock()
    doc = MagicMock()
    doc.page_content = "Test content"
    doc.metadata = {}

    add_text_to_store_with_retry(store, doc, "123")

    store.add_texts.assert_called_once_with(
        ["Test content"], metadatas=[{"source_id": "123"}]
    )


@pytest.fixture
def mock_settings(monkeypatch):
    mock_settings = MagicMock()
    monkeypatch.setattr(
        "application.parser.embedding_pipeline.settings", mock_settings
    )
    return mock_settings


@pytest.fixture
def mock_vector_creator(monkeypatch):
    mock_creator = MagicMock()
    monkeypatch.setattr(
        "application.parser.embedding_pipeline.VectorCreator", mock_creator
    )
    return mock_creator



def test_embed_and_store_documents_creates_folder(tmp_path, mock_settings, mock_vector_creator):
    mock_settings.VECTOR_STORE = "faiss"

    docs = [MagicMock(page_content="doc1", metadata={}), MagicMock(page_content="doc2", metadata={})]
    folder_name = tmp_path / "test_store"
    source_id = "xyz"
    task_status = MagicMock()

    mock_store = MagicMock()
    mock_vector_creator.create_vectorstore.return_value = mock_store

    embed_and_store_documents(docs, str(folder_name), source_id, task_status)

    assert folder_name.exists()
    mock_vector_creator.create_vectorstore.assert_called_once()
    mock_store.save_local.assert_called_once_with(str(folder_name))
    task_status.update_state.assert_called()


def test_embed_and_store_documents_non_faiss(tmp_path, mock_settings, mock_vector_creator):
    mock_settings.VECTOR_STORE = "chromadb"

    docs = [MagicMock(page_content="doc1", metadata={}), MagicMock(page_content="doc2", metadata={})]
    folder_name = tmp_path / "chromadb_store"
    source_id = "test123"
    task_status = MagicMock()

    mock_store = MagicMock()
    mock_vector_creator.create_vectorstore.return_value = mock_store

    embed_and_store_documents(docs, str(folder_name), source_id, task_status)

    mock_store.delete_index.assert_called_once()
    task_status.update_state.assert_called()
    assert folder_name.exists()


def test_embed_and_store_documents_progress_band(
    tmp_path, mock_settings, mock_vector_creator
):
    """progress_start/progress_end remap the embed loop into a sub-band
    so an earlier stage (parsing) can own the lower part of the bar.
    """
    mock_settings.VECTOR_STORE = "chromadb"

    docs = [MagicMock(page_content=f"d{i}", metadata={}) for i in range(4)]
    task_status = MagicMock()
    mock_vector_creator.create_vectorstore.return_value = MagicMock()

    embed_and_store_documents(
        docs, str(tmp_path / "store"), "sid", task_status,
        progress_start=50, progress_end=100,
    )

    currents = [
        call.kwargs["meta"]["current"]
        for call in task_status.update_state.call_args_list
        if "meta" in call.kwargs and "current" in call.kwargs["meta"]
    ]
    assert currents, "expected progress updates"
    # Embedding stays in the upper band and tops out at 100.
    assert min(currents) > 50
    assert max(currents) == 100
    assert currents == sorted(currents)


@patch("application.parser.embedding_pipeline.add_texts_to_store_with_retry")
def test_embed_and_store_documents_partial_failure_raises(
    mock_add_retry, tmp_path, mock_settings, mock_vector_creator, caplog
):
    """Regression: a per-chunk failure must escape the function so
    Celery's autoretry_for can fire and ``with_idempotency`` doesn't
    cache a partial index as ``completed``. Pre-fix, this branch
    swallowed and returned success.
    """
    mock_settings.VECTOR_STORE = "faiss"

    docs = [
        MagicMock(page_content="good", metadata={}),
        MagicMock(page_content="bad", metadata={}),
    ]
    folder_name = tmp_path / "partial_fail"
    source_id = "id123"
    task_status = MagicMock()

    mock_store = MagicMock()
    mock_vector_creator.create_vectorstore.return_value = mock_store

    # First document succeeds (FAISS init seeds with docs[0]; the loop
    # picks up at idx=1 and raises on the bad chunk). The batch entry point
    # receives a list, and the per-chunk fallback re-runs it one at a time —
    # both go through this mock, so "bad" raises either way.
    def side_effect(store_arg, docs_arg, source_arg):
        if any("bad" in d.page_content for d in docs_arg):
            raise RuntimeError("Embedding failed")
    mock_add_retry.side_effect = side_effect

    with caplog.at_level(logging.ERROR):
        with pytest.raises(EmbeddingPipelineError) as exc_info:
            embed_and_store_documents(
                docs, str(folder_name), source_id, task_status,
            )

    # Original cause is chained via ``raise ... from`` for diagnostics.
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "Error embedding document" in caplog.text
    # Partial save still ran (chunks that did embed are flushed to disk).
    mock_store.save_local.assert_called()


@patch("application.parser.embedding_pipeline.add_texts_to_store_with_retry")
def test_embed_and_store_documents_all_chunks_succeed_no_raise(
    mock_add_retry, tmp_path, mock_settings, mock_vector_creator,
):
    """Happy path: no exception escapes when every chunk succeeds."""
    mock_settings.VECTOR_STORE = "faiss"

    docs = [
        MagicMock(page_content="a", metadata={}),
        MagicMock(page_content="b", metadata={}),
    ]
    mock_store = MagicMock()
    mock_vector_creator.create_vectorstore.return_value = mock_store

    embed_and_store_documents(
        docs, str(tmp_path / "ok"), "id-ok", MagicMock(),
    )
    mock_store.save_local.assert_called()


# ── assert_index_complete ──────────────────────────────────────────────────


def test_assert_index_complete_raises_on_partial(monkeypatch):
    """Worker-level tripwire: chunk-progress with embedded < total raises."""
    fake_repo = MagicMock()
    fake_repo.get_progress.return_value = {
        "embedded_chunks": 4, "total_chunks": 10,
    }
    monkeypatch.setattr(
        "application.parser.embedding_pipeline.IngestChunkProgressRepository",
        lambda conn: fake_repo,
    )
    from contextlib import contextmanager

    @contextmanager
    def _fake_session():
        yield None

    monkeypatch.setattr(
        "application.parser.embedding_pipeline.db_session", _fake_session,
    )
    with pytest.raises(EmbeddingPipelineError, match=r"4/10"):
        assert_index_complete("src-partial")


def test_assert_index_complete_passes_on_full(monkeypatch):
    fake_repo = MagicMock()
    fake_repo.get_progress.return_value = {
        "embedded_chunks": 10, "total_chunks": 10,
    }
    monkeypatch.setattr(
        "application.parser.embedding_pipeline.IngestChunkProgressRepository",
        lambda conn: fake_repo,
    )
    from contextlib import contextmanager

    @contextmanager
    def _fake_session():
        yield None

    monkeypatch.setattr(
        "application.parser.embedding_pipeline.db_session", _fake_session,
    )
    assert_index_complete("src-full")  # no raise


def test_assert_index_complete_no_op_when_no_progress_row(monkeypatch):
    """Zero-doc validation raises before init → no progress row exists."""
    fake_repo = MagicMock()
    fake_repo.get_progress.return_value = None
    monkeypatch.setattr(
        "application.parser.embedding_pipeline.IngestChunkProgressRepository",
        lambda conn: fake_repo,
    )
    from contextlib import contextmanager

    @contextmanager
    def _fake_session():
        yield None

    monkeypatch.setattr(
        "application.parser.embedding_pipeline.db_session", _fake_session,
    )
    assert_index_complete("src-missing")


def test_assert_index_complete_no_op_when_lookup_fails(monkeypatch, caplog):
    """DB outage during lookup mustn't fail the whole task — log and
    return so the embed function's own raise (Option A) remains the
    primary signal.
    """
    from contextlib import contextmanager

    @contextmanager
    def _broken_session():
        raise RuntimeError("DB unreachable")
        yield  # pragma: no cover

    monkeypatch.setattr(
        "application.parser.embedding_pipeline.db_session", _broken_session,
    )
    with caplog.at_level(logging.WARNING, logger="root"):
        assert_index_complete("src-db-down")  # no raise
    assert any(
        "progress lookup failed" in r.getMessage() for r in caplog.records
    )


def test_embed_and_store_documents_save_fails_raises_oserror(
    tmp_path, mock_settings, mock_vector_creator
):
    mock_settings.VECTOR_STORE = "faiss"

    docs = [MagicMock(page_content="good", metadata={})]
    folder_name = tmp_path / "save_fail"
    source_id = "id789"
    task_status = MagicMock()

    mock_store = MagicMock()
    mock_store.save_local.side_effect = Exception("Disk full")
    mock_vector_creator.create_vectorstore.return_value = mock_store

    with pytest.raises(OSError, match="Unable to save vector store"):
        embed_and_store_documents(docs, str(folder_name), source_id, task_status)



# ── batched embed loop ─────────────────────────────────────────────────────


def test_add_texts_to_store_with_retry_sends_one_call_per_batch():
    """The batch entry point collapses N chunks into a single add_texts."""
    store = MagicMock()
    docs = [MagicMock(page_content=f"c{i}", metadata={}) for i in range(3)]

    add_texts_to_store_with_retry(store, docs, "sid")

    store.add_texts.assert_called_once_with(
        ["c0", "c1", "c2"],
        metadatas=[{"source_id": "sid"}] * 3,
    )


def test_add_texts_to_store_with_retry_sanitizes_and_skips_empty():
    store = MagicMock()
    docs = [MagicMock(page_content="a\x00b", metadata={})]

    add_texts_to_store_with_retry(store, docs, "sid")
    assert store.add_texts.call_args.args[0] == ["ab"]

    store.reset_mock()
    add_texts_to_store_with_retry(store, [], "sid")
    store.add_texts.assert_not_called()


def test_resolve_batch_size_falls_back_on_bad_setting(monkeypatch):
    fake = MagicMock()  # attribute access yields a MagicMock, not an int
    monkeypatch.setattr("application.parser.embedding_pipeline.settings", fake)
    assert _resolve_batch_size() == DEFAULT_EMBEDDINGS_BATCH_SIZE

    fake.EMBEDDINGS_BATCH_SIZE = 0
    assert _resolve_batch_size() == 1  # never below 1
    fake.EMBEDDINGS_BATCH_SIZE = 32
    assert _resolve_batch_size() == 32


def test_embed_loop_batches_chunks(tmp_path, mock_settings, mock_vector_creator):
    """70 chunks at batch size 32 => 3 add_texts calls, not 70."""
    mock_settings.VECTOR_STORE = "chromadb"
    mock_settings.EMBEDDINGS_BATCH_SIZE = 32

    docs = [MagicMock(page_content=f"d{i}", metadata={}) for i in range(70)]
    store = MagicMock()
    mock_vector_creator.create_vectorstore.return_value = store

    with patch("application.parser.embedding_pipeline._record_progress") as rec:
        embed_and_store_documents(
            docs, str(tmp_path / "s"), "sid", MagicMock(),
        )

    assert store.add_texts.call_count == 3
    assert [len(c.args[0]) for c in store.add_texts.call_args_list] == [32, 32, 6]
    # One checkpoint per batch, and the final one accounts for every chunk.
    assert rec.call_count == 3
    assert rec.call_args.kwargs == {"last_index": 69, "embedded_chunks": 70}


def test_embed_loop_batch_size_one_matches_legacy(
    tmp_path, mock_settings, mock_vector_creator
):
    """batch_size=1 restores the pre-batching one-call-per-chunk behaviour."""
    mock_settings.VECTOR_STORE = "chromadb"
    mock_settings.EMBEDDINGS_BATCH_SIZE = 1

    docs = [MagicMock(page_content=f"d{i}", metadata={}) for i in range(5)]
    store = MagicMock()
    mock_vector_creator.create_vectorstore.return_value = store

    embed_and_store_documents(docs, str(tmp_path / "s"), "sid", MagicMock())

    assert store.add_texts.call_count == 5


def test_poison_chunk_isolated_by_per_chunk_fallback(
    tmp_path, mock_settings, mock_vector_creator
):
    """A batch failure re-runs individually: good chunks land, and the
    reported failure index is the real offender, not the batch head.

    Patches the batch entry point so the ``@retry`` sleeps don't run — the
    fallback, not the retry, is what's under test here.
    """
    mock_settings.VECTOR_STORE = "chromadb"
    mock_settings.EMBEDDINGS_BATCH_SIZE = 32

    docs = [MagicMock(page_content=f"d{i}", metadata={}) for i in range(10)]
    docs[6].page_content = "poison"
    mock_vector_creator.create_vectorstore.return_value = MagicMock()

    def fake_add(store, batch, source_id):
        if any(d.page_content == "poison" for d in batch):
            raise RuntimeError("input too large")

    with patch(
        "application.parser.embedding_pipeline.add_texts_to_store_with_retry",
        side_effect=fake_add,
    ):
        with patch("application.parser.embedding_pipeline._record_progress") as rec:
            with pytest.raises(EmbeddingPipelineError) as exc:
                embed_and_store_documents(
                    docs, str(tmp_path / "s"), "sid", MagicMock(),
                )

    assert "chunk 6/10" in str(exc.value)
    assert isinstance(exc.value.__cause__, RuntimeError)
    # Chunks 0-5 were salvaged one at a time and checkpointed.
    assert rec.call_args_list[-1].kwargs == {"last_index": 5, "embedded_chunks": 6}


def test_batch_only_failure_recovers_via_fallback(
    tmp_path, mock_settings, mock_vector_creator
):
    """When the *batch* is rejected but each chunk is fine on its own (e.g. a
    request-size limit), the fallback completes the ingest without raising."""
    mock_settings.VECTOR_STORE = "chromadb"
    mock_settings.EMBEDDINGS_BATCH_SIZE = 32

    docs = [MagicMock(page_content=f"d{i}", metadata={}) for i in range(4)]
    mock_vector_creator.create_vectorstore.return_value = MagicMock()

    seen = []

    def fake_add(store, batch, source_id):
        seen.append(len(batch))
        if len(batch) > 1:
            raise RuntimeError("payload too large")

    with patch(
        "application.parser.embedding_pipeline.add_texts_to_store_with_retry",
        side_effect=fake_add,
    ):
        embed_and_store_documents(docs, str(tmp_path / "s"), "sid", MagicMock())

    # One rejected batch of 4, then four successful singles.
    assert seen == [4, 1, 1, 1, 1]
