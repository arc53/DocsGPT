"""Integration tests for Valkey vector store.

These tests require a running Valkey instance with the valkey-search module loaded.
Run with: podman run -d --name valkey-test -p 6379:6379 valkey/valkey:8.1 --loadmodule /usr/lib/valkey/modules/valkeysearch.so

Skip these tests when Valkey is not available by running:
    pytest -m "not integration"
"""

import os
import uuid

import pytest

VALKEY_HOST = os.environ.get("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.environ.get("VALKEY_PORT", "6379"))


def _valkey_available() -> bool:
    """Check if a Valkey instance is reachable."""
    try:
        from glide_sync import GlideClient, GlideClientConfiguration, NodeAddress

        config = GlideClientConfiguration(
            addresses=[NodeAddress(host=VALKEY_HOST, port=VALKEY_PORT)]
        )
        client = GlideClient.create(config)
        client.ping()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _valkey_available(),
        reason=f"Valkey not available at {VALKEY_HOST}:{VALKEY_PORT}",
    ),
]


class FakeEmbeddings:
    """Deterministic fake embeddings for integration testing."""

    dimension = 4

    def embed_query(self, text: str) -> list:
        """Return a simple hash-based vector."""
        h = hash(text) % 1000
        return [h / 1000.0, (h + 1) / 1000.0, (h + 2) / 1000.0, (h + 3) / 1000.0]

    def embed_documents(self, texts: list) -> list:
        """Embed multiple documents."""
        return [self.embed_query(t) for t in texts]


@pytest.fixture
def valkey_store():
    """Create a ValkeyStore with a unique source_id for test isolation."""
    from unittest.mock import patch

    source_id = f"test-{uuid.uuid4().hex[:8]}"
    index_name = f"test_idx_{uuid.uuid4().hex[:8]}"

    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings"
    ) as mock_get_emb, patch(
        "application.vectorstore.valkey.settings"
    ) as mock_settings:
        mock_get_emb.return_value = FakeEmbeddings()
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.VALKEY_HOST = VALKEY_HOST
        mock_settings.VALKEY_PORT = VALKEY_PORT
        mock_settings.VALKEY_PASSWORD = None
        mock_settings.VALKEY_USE_TLS = False
        mock_settings.VALKEY_INDEX_NAME = index_name
        mock_settings.VALKEY_PREFIX = f"test:{source_id}:"

        from application.vectorstore.valkey import ValkeyStore

        store = ValkeyStore(source_id=source_id, embeddings_key="test")

    yield store

    # Cleanup: delete all test documents and drop the index
    try:
        store.delete_index()
        from glide_sync import ft

        ft.dropindex(store._client, index_name)
    except Exception:
        pass


class TestValkeyIntegrationAddAndSearch:
    def test_add_texts_and_search(self, valkey_store):
        """Test basic add and search flow."""
        texts = [
            "Python is a programming language",
            "Valkey is an in-memory data store",
            "Machine learning uses neural networks",
        ]
        metadatas = [
            {"source": "python.txt"},
            {"source": "valkey.txt"},
            {"source": "ml.txt"},
        ]

        ids = valkey_store.add_texts(texts, metadatas)

        assert len(ids) == 3
        assert all(isinstance(id_, str) for id_ in ids)

        # Search should return results
        results = valkey_store.search("programming language", k=2)
        assert len(results) > 0
        assert all(hasattr(r, "page_content") for r in results)
        assert all(hasattr(r, "metadata") for r in results)

    def test_add_chunk_and_get_chunks(self, valkey_store):
        """Test single chunk add and retrieval."""
        chunk_id = valkey_store.add_chunk(
            "Test document content",
            metadata={"author": "test", "page": 1},
        )

        assert isinstance(chunk_id, str)

        chunks = valkey_store.get_chunks()
        assert len(chunks) == 1
        assert chunks[0]["text"] == "Test document content"
        assert chunks[0]["metadata"]["author"] == "test"

    def test_delete_chunk(self, valkey_store):
        """Test deleting a specific chunk."""
        chunk_id = valkey_store.add_chunk("to be deleted")

        result = valkey_store.delete_chunk(chunk_id)
        assert result is True

        # Verify it's gone
        chunks = valkey_store.get_chunks()
        assert len(chunks) == 0

    def test_delete_nonexistent_chunk(self, valkey_store):
        """Test deleting a chunk that doesn't exist."""
        result = valkey_store.delete_chunk("nonexistent-id")
        assert result is False

    def test_delete_index(self, valkey_store):
        """Test deleting all documents for a source."""
        valkey_store.add_texts(["doc1", "doc2", "doc3"])

        valkey_store.delete_index()

        chunks = valkey_store.get_chunks()
        assert len(chunks) == 0

    def test_save_local_is_noop(self, valkey_store):
        """Test that save_local doesn't raise."""
        assert valkey_store.save_local() is None

    def test_empty_search(self, valkey_store):
        """Test search with no documents returns empty."""
        results = valkey_store.search("anything", k=5)
        assert results == []
