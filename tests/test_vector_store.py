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
    Test that asserts that initializing a FaissStore with
    the huggingface sentence transformer below together with the
    index.faiss file in the application/ folder results in a
    dimension mismatch error.
    """
    import os
    from langchain.embeddings import HuggingFaceEmbeddings
    from langchain.docstore.document import Document
    from langchain_community.vectorstores import FAISS

    # Ensure application directory exists
    index_path = os.path.join("application")
    os.makedirs(index_path, exist_ok=True)

    # Create an index.faiss with a different embeddings dimension
    # Use a different embedding model with a smaller dimension
    other_embedding_model = "sentence-transformers/all-MiniLM-L6-v2"  # Dimension 384
    other_embeddings = HuggingFaceEmbeddings(model_name=other_embedding_model)
    # Create some dummy documents
    docs = [Document(page_content="Test document")]
    # Create index using the other embeddings
    other_docsearch = FAISS.from_documents(docs, other_embeddings)
    # Save index to application/
    other_docsearch.save_local(index_path)

    # Now set the EMBEDDINGS_NAME to the one with a different dimension
    settings.EMBEDDINGS_NAME = "huggingface_sentence-transformers/all-mpnet-base-v2"  # Dimension 768
    with pytest.raises(ValueError) as exc_info:
        FaissStore("", None)
    assert "Embedding dimension mismatch" in str(exc_info.value)
