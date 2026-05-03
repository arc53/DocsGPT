import pytest
import logging
from unittest.mock import patch, MagicMock

from application.parser.embedding_pipeline import (
    EmbeddingPipelineError,
    add_text_to_store_with_retry,
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


@patch("application.parser.embedding_pipeline.add_text_to_store_with_retry")
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
    # picks up at idx=1 and raises on the bad chunk).
    def side_effect(*args, **kwargs):
        if "bad" in args[1].page_content:
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


@patch("application.parser.embedding_pipeline.add_text_to_store_with_retry")
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

