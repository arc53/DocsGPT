import os
import logging
from typing import List, Any, Optional, Dict
from retry import retry
from tqdm import tqdm

# Optional: these imports can be swapped or mocked for testing
try:
    from application.core.settings import settings
    from application.vectorstore.vector_creator import VectorCreator
except ImportError:
    # Allow standalone testing without full project dependencies
    class DummySettings:
        VECTOR_STORE = "faiss"
    settings = DummySettings()

    class DummyVectorStore:
        def __init__(self):
            self.texts = []

        def add_texts(self, texts, metadatas=None):
            for text, meta in zip(texts, metadatas or [{}]):
                self.texts.append({"text": text, "metadata": meta})

        def delete_index(self):
            self.texts.clear()

        def save_local(self, folder_name):
            os.makedirs(folder_name, exist_ok=True)
            with open(os.path.join(folder_name, "store.txt"), "w") as f:
                for entry in self.texts:
                    f.write(f"{entry}\n")

    class VectorCreator:
        @staticmethod
        def create_vectorstore(store_type, **kwargs):
            return DummyVectorStore()


# -----------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------

def sanitize_content(content: Optional[str]) -> str:
    """Remove NUL characters that cause vector ingestion failures."""
    return content.replace('\x00', '') if content else ""


@retry(tries=10, delay=60)
def add_text_to_store_with_retry(store: Any, doc: Any, source_id: str) -> None:
    """Add a document's text and metadata to the vector store with retries."""
    try:
        doc.page_content = sanitize_content(getattr(doc, "page_content", ""))
        metadata = getattr(doc, "metadata", {}) or {}
        metadata["source_id"] = str(source_id)

        store.add_texts([doc.page_content], metadatas=[metadata])
        logging.debug(f"✅ Successfully added document to store: {metadata.get('source_id')}")
    except Exception as e:
        logging.error(f"❌ Failed to add document: {e}", exc_info=True)
        raise


# -----------------------------------------------------------
# Main Embedding Function
# -----------------------------------------------------------

def embed_and_store_documents(
    docs: List[Any],
    folder_name: str,
    source_id: str,
    task_status: Optional[Any] = None,
    retries: int = 10,
    retry_delay: int = 60,
) -> None:
    """
    Embed documents and store them in a vector store.
    Includes fault tolerance, retry logic, and progress saving.
    """
    os.makedirs(folder_name, exist_ok=True)
    logging.info(f"📁 Output folder ready: {folder_name}")

    # Early return if there are no documents
    if not docs:
        logging.info("No documents provided to embed. Initializing empty store and exiting.")
        # Create store and save empty state if possible
        store = VectorCreator.create_vectorstore(
            settings.VECTOR_STORE,
            source_id=source_id,
            embeddings_key=os.getenv("EMBEDDINGS_KEY"),
        )
        try:
            store.save_local(folder_name)
            logging.info("✅ Empty vector store saved successfully.")
        except Exception as e:
            logging.critical(f"🔥 Failed to save empty vector store: {e}", exc_info=True)
        return

    # Initialize vector store. For FAISS, the implementation originally popped
    # the first doc out of the list; make this safe if docs is small.
    if settings.VECTOR_STORE == "faiss":
        docs_init = []
        if len(docs) > 0:
            # pop the first doc for any special initialization behavior
            try:
                docs_init = [docs.pop(0)]
            except Exception:
                docs_init = []
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
        # clear any existing index for non-faiss backends
        try:
            store.delete_index()
        except Exception:
            # not all backends may implement delete_index
            logging.debug("store.delete_index() not available for this backend")

    total_docs = len(docs)
    logging.info(f"🚀 Starting embedding process for {total_docs} documents.")

    if total_docs == 0:
        logging.info("No remaining documents to process after initialization.")
    else:
        for idx, doc in tqdm(
            enumerate(docs),
            desc="Embedding 🦖",
            total=total_docs,
            unit="docs",
            bar_format="{l_bar}{bar}| Time Left: {remaining}",
        ):
            try:
                # protect against division by zero by using total_docs which is >0 here
                progress = int(((idx + 1) / total_docs) * 100)
                if task_status:
                    task_status.update_state(state="PROGRESS", meta={"current": progress})

                add_text_to_store_with_retry(store, doc, source_id)
            except Exception as e:
                logging.error(f"⚠️ Error embedding document {idx}: {e}", exc_info=True)
                logging.info(f"Saving progress at document {idx} / {total_docs}...")
                try:
                    store.save_local(folder_name)
                    logging.info("✅ Partial progress saved successfully.")
                except Exception as save_error:
                    logging.critical(f"❌ Failed to save partial progress: {save_error}", exc_info=True)
                break

    # Save final store
    try:
        store.save_local(folder_name)
        logging.info("🎉 Vector store saved successfully.")
    except Exception as e:
        logging.critical(f"🔥 Failed to save final store: {e}", exc_info=True)
        raise OSError(f"Unable to save vector store: {e}") from e


# -----------------------------------------------------------
# Example Usage (for testing)
# -----------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    class DummyDoc:
        def __init__(self, content, meta=None):
            self.page_content = content
            self.metadata = meta or {}

    dummy_docs = [DummyDoc(f"Sample document {i}") for i in range(5)]
    embed_and_store_documents(dummy_docs, "output_vectors", source_id="12345")
