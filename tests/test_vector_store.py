"""
Tests regarding the vector store class, including checking
compatibility between different transformers and local vector
stores (index.faiss)
"""
import pytest
from application.vectorstore.faiss import FaissStore
from application.core.settings import settings

def test_init_local_faiss_store_huggingface():
    """
    Test that asserts that trying to initialize a FaissStore with
    the huggingface sentence transformer below together with the
    index.faiss file in the application/ folder results in a
    dimension mismatch error.
    """
    settings.EMBEDDINGS_NAME = "openai_text-embedding-ada-002"
    with pytest.raises(ValueError):
        FaissStore("application/", "", None)
