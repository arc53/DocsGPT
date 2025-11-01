import pytest
import logging
from unittest.mock import patch, MagicMock

from application.parser.embedding_pipeline import (
    sanitize_content,
    add_text_to_store_with_retry,
    embed_and_store_documents,
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
def test_embed_and_store_documents_partial_failure(
    mock_add_retry, tmp_path, mock_settings, mock_vector_creator, caplog
):
    mock_settings.VECTOR_STORE = "faiss"

    docs = [MagicMock(page_content="good", metadata={}), MagicMock(page_content="bad", metadata={})]
    folder_name = tmp_path / "partial_fail"
    source_id = "id123"
    task_status = MagicMock()

    mock_store = MagicMock()
    mock_vector_creator.create_vectorstore.return_value = mock_store

    # First document succeeds, second fails
    def side_effect(*args, **kwargs):
        if "bad" in args[1].page_content:
            raise Exception("Embedding failed")
    mock_add_retry.side_effect = side_effect

    with caplog.at_level(logging.ERROR):
        embed_and_store_documents(docs, str(folder_name), source_id, task_status)

    assert "Error embedding document" in caplog.text
    mock_store.save_local.assert_called()


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

