import os
import logging
from typing import List, Any
from retry import retry
from tqdm import tqdm
from application.core.settings import settings
from application.vectorstore.vector_creator import VectorCreator


def sanitize_content(content: str) -> str:
    """
    Remove NUL characters that can cause vector store ingestion to fail.
    
    Args:
        content (str): Raw content that may contain NUL characters
        
    Returns:
        str: Sanitized content with NUL characters removed
    """
    if not content:
        return content
    return content.replace('\x00', '')


@retry(tries=10, delay=60)
def add_text_to_store_with_retry(store: Any, doc: Any, source_id: str) -> None:
    """Add a document's text and metadata to the vector store with retry logic.
    
    Args:
        store: The vector store object.
        doc: The document to be added.
        source_id: Unique identifier for the source.
        
    Raises:
        Exception: If document addition fails after all retry attempts.
    """
    try:
        # Sanitize content to remove NUL characters that cause ingestion failures
        doc.page_content = sanitize_content(doc.page_content)
        
        doc.metadata["source_id"] = str(source_id)
        store.add_texts([doc.page_content], metadatas=[doc.metadata])
    except Exception as e:
        logging.error(f"Failed to add document with retry: {e}", exc_info=True)
        raise


def embed_and_store_documents(docs: List[Any], folder_name: str, source_id: str, task_status: Any) -> None:
    """Embeds documents and stores them in a vector store.

    Args:
        docs: List of documents to be embedded and stored.
        folder_name: Directory to save the vector store.
        source_id: Unique identifier for the source.
        task_status: Task state manager for progress updates.

    Returns:
        None
        
    Raises:
        OSError: If unable to create folder or save vector store.
        Exception: If vector store creation or document embedding fails.
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
            source_id=source_id,
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
            try:
                store.save_local(folder_name)
                logging.info("Progress saved successfully")
            except Exception as save_error:
                logging.error(f"CRITICAL: Failed to save progress: {save_error}", exc_info=True)
                # Continue without breaking to attempt final save
            break

    # Save the vector store
    if settings.VECTOR_STORE == "faiss":
        try:
            store.save_local(folder_name)
            logging.info("Vector store saved successfully.")
        except Exception as e:
            logging.error(f"CRITICAL: Failed to save final vector store: {e}", exc_info=True)
            raise OSError(f"Unable to save vector store to {folder_name}: {e}") from e
    else:
        logging.info("Vector store saved successfully.")
