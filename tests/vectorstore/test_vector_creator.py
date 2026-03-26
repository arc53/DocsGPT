from unittest.mock import patch

import pytest

from application.vectorstore.vector_creator import VectorCreator


@pytest.mark.unit
class TestVectorCreator:
    def test_registered_vectorstores(self):
        assert "faiss" in VectorCreator.vectorstores
        assert "elasticsearch" in VectorCreator.vectorstores
        assert "mongodb" in VectorCreator.vectorstores
        assert "qdrant" in VectorCreator.vectorstores
        assert "milvus" in VectorCreator.vectorstores
        assert "pgvector" in VectorCreator.vectorstores

    def test_create_vectorstore_invalid_type(self):
        with pytest.raises(ValueError, match="No vectorstore class found for type"):
            VectorCreator.create_vectorstore("nonexistent")

    def test_create_vectorstore_case_insensitive(self):
        with patch.object(
            VectorCreator.vectorstores["faiss"], "__init__", return_value=None
        ) as mock_init:
            mock_init.return_value = None
            VectorCreator.create_vectorstore("FAISS", source_id="test", embeddings_key="key")
            mock_init.assert_called_once_with(source_id="test", embeddings_key="key")

    def test_create_vectorstore_passes_args(self):
        with patch.object(
            VectorCreator.vectorstores["mongodb"], "__init__", return_value=None
        ) as mock_init:
            VectorCreator.create_vectorstore(
                "mongodb", source_id="src1", embeddings_key="ek", database="mydb"
            )
            mock_init.assert_called_once_with(
                source_id="src1", embeddings_key="ek", database="mydb"
            )
