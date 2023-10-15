import pytest
from flask import Flask
from application.error import bad_request, response_error
from application.vectorstore.faiss import FaissStore
from application.core.settings import settings

def test_init_local_faiss_store_huggingface():
    """
    Test that asserts that trying to initialize a FaissStore with
    the huggingface sentence transformer below together with the
    index.faiss file in the application/ folder results in a
    dimension mismatch error.
    """
    settings.EMBEDDINGS_NAME = "huggingface_sentence-transformers/all-mpnet-base-v2"
    with pytest.raises(ValueError):
        FaissStore("application/", "", None)
