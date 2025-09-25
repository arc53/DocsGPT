from .oracle import OracleVectorStore  # Add this

# Assuming a factory exists or add one
def get_vectorstore(embeddings_name="openai_text-embedding-ada-002", embeddings_key=None):
    store_type = os.getenv("VECTOR_STORE", "default")
    if store_type == "oracle":
        return OracleVectorStore(embeddings_name, embeddings_key)
    # Add other stores as needed
    raise ValueError(f"Unsupported vector store: {store_type}")