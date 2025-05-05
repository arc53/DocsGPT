import os
import logging
from retry import retry
from tqdm import tqdm
from application.core.settings import settings
from application.vectorstore.vector_creator import VectorCreator


@retry(tries=10, delay=60)
def add_text_to_store_with_retry(store, doc, source_id):
    """
    Add a document's text and metadata to the vector store with retry logic.
    Args:
        store: The vector store object.
        doc: The document to be added.
        source_id: Unique identifier for the source.
    """
    try:
        doc.metadata["source_id"] = str(source_id)
        store.add_texts([doc.page_content], metadatas=[doc.metadata])
    except Exception as e:
        logging.error(f"Failed to add document with retry: {e}", exc_info=True)
        raise


def embed_and_store_documents(docs, folder_name, source_id, task_status):
    """
    Embeds documents and stores them in a vector store.

    Args:
        docs (list): List of documents to be embedded and stored.
        folder_name (str): Directory to save the vector store.
        source_id (str): Unique identifier for the source.
        task_status: Task state manager for progress updates.

    Returns:
        None
    """
    # Ensure the folder exists
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    # Initialize vector store
    if settings.VECTOR_STORE == "faiss":
        docs_init = [docs.pop(0)]
        store = VectorCreator.create_vectorstore(
            settings.VECTOR_STORE,
            docs_init=docs_init,
            source_id=folder_name,
            embeddings_key=os.getenv("EMBEDDINGS_KEY"),
        )
    else:
        store = VectorCreator.create_vectorstore(
            settings.VECTOR_STORE,
            source_id=source_id,
            embeddings_key=os.getenv("EMBEDDINGS_KEY"),
        )
        store.delete_index()

    total_docs = len(docs)

    # Process and embed documents
    for idx, doc in tqdm(
        enumerate(docs),
        desc="Embedding 🦖",
        unit="docs",
        total=total_docs,
        bar_format="{l_bar}{bar}| Time Left: {remaining}",
    ):
        try:
            # Update task status for progress tracking
            progress = int(((idx + 1) / total_docs) * 100)
            task_status.update_state(state="PROGRESS", meta={"current": progress})

            # Add document to vector store
            add_text_to_store_with_retry(store, doc, source_id)
        except Exception as e:
            logging.error(f"Error embedding document {idx}: {e}", exc_info=True)
            logging.info(f"Saving progress at document {idx} out of {total_docs}")
            store.save_local(folder_name)
            break

    # Save the vector store
    if settings.VECTOR_STORE == "faiss":
        store.save_local(folder_name)
    logging.info("Vector store saved successfully.")
