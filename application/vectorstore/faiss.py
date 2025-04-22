import os
import tempfile
import logging

from langchain_community.vectorstores import FAISS

from application.core.settings import settings
from application.parser.schema.base import Document
from application.vectorstore.base import BaseVectorStore
from application.storage.storage_creator import StorageCreator


def get_vectorstore_path(source_id: str) -> str:
    if source_id:
        clean_id = source_id.replace("application/indexes/", "").rstrip("/")
        return f"indexes/{clean_id}"
    else:
        return "indexes"

class FaissStore(BaseVectorStore):
    def __init__(self, source_id: str, embeddings_key: str, docs_init=None):
        super().__init__()
        self.source_id = source_id
        self.storage = StorageCreator.get_storage()
        self.storage_path = get_vectorstore_path(source_id)
        self.embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)

        try:
            if docs_init:
                self.docsearch = FAISS.from_documents(docs_init, self.embeddings)
            else:
                if self.storage.__class__.__name__ == "LocalStorage":
                    # For local storage, we can use the path directly
                    local_path = self.storage._get_full_path(self.storage_path)
                    self.docsearch = FAISS.load_local(
                        local_path, self.embeddings, allow_dangerous_deserialization=True
                    )
                else:
                    # For non-local storage (S3, etc.), download files to temp directory first
                    self.docsearch = self._load_from_remote_storage()
        except Exception as e:
            logging.error(f"Error initializing FAISS store: {e}")
            raise

        self.assert_embedding_dimensions(self.embeddings)

    def search(self, *args, **kwargs):
        return self.docsearch.similarity_search(*args, **kwargs)

    def add_texts(self, *args, **kwargs):
        return self.docsearch.add_texts(*args, **kwargs)

    def save_local(self, folder_path=None):
        path_to_use = folder_path or self.storage_path

        if folder_path or self.storage.__class__.__name__ == "LocalStorage":
            # If it's a local path or temp dir, save directly
            local_path = path_to_use
            if self.storage.__class__.__name__ == "LocalStorage" and not folder_path:
                local_path = self.storage._get_full_path(path_to_use)

            os.makedirs(os.path.dirname(local_path) if os.path.dirname(local_path) else local_path, exist_ok=True)

            self.docsearch.save_local(local_path)

            if folder_path and self.storage.__class__.__name__ != "LocalStorage":
                self._upload_index_to_remote(folder_path)
        else:
            # For remote storage, save to temp dir first, then upload
            with tempfile.TemporaryDirectory() as temp_dir:
                self.docsearch.save_local(temp_dir)
                self._upload_index_to_remote(temp_dir)

    def delete_index(self, *args, **kwargs):
        return self.docsearch.delete(*args, **kwargs)

    def assert_embedding_dimensions(self, embeddings):
        """Check that the word embedding dimension of the docsearch index matches the dimension of the word embeddings used."""
        if (
            settings.EMBEDDINGS_NAME
            == "huggingface_sentence-transformers/all-mpnet-base-v2"
        ):
            word_embedding_dimension = getattr(embeddings, "dimension", None)
            if word_embedding_dimension is None:
                raise AttributeError(
                    "'dimension' attribute not found in embeddings instance."
                )

            docsearch_index_dimension = self.docsearch.index.d
            if word_embedding_dimension != docsearch_index_dimension:
                raise ValueError(
                    f"Embedding dimension mismatch: embeddings.dimension ({word_embedding_dimension}) != docsearch index dimension ({docsearch_index_dimension})"
                )

    def get_chunks(self):
        chunks = []
        if self.docsearch:
            for doc_id, doc in self.docsearch.docstore._dict.items():
                chunk_data = {
                    "doc_id": doc_id,
                    "text": doc.page_content,
                    "metadata": doc.metadata,
                }
                chunks.append(chunk_data)
        return chunks

    def add_chunk(self, text, metadata=None):
        metadata = metadata or {}
        doc = Document(text=text, extra_info=metadata).to_langchain_format()
        doc_id = self.docsearch.add_documents([doc])
        self.save_local()
        return doc_id

    def delete_chunk(self, chunk_id):
        self.delete_index([chunk_id])
        self.save_local()
        return True

    def _load_from_remote_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # Check if both index files exist in remote storage
                faiss_path = f"{self.storage_path}/index.faiss"
                pkl_path = f"{self.storage_path}/index.pkl"

                if not self.storage.file_exists(faiss_path) or not self.storage.file_exists(pkl_path):
                    raise FileNotFoundError(f"FAISS index files not found at {self.storage_path}")

                # Download both files to temp directory
                faiss_file = self.storage.get_file(faiss_path)
                pkl_file = self.storage.get_file(pkl_path)

                local_faiss_path = os.path.join(temp_dir, "index.faiss")
                local_pkl_path = os.path.join(temp_dir, "index.pkl")

                with open(local_faiss_path, 'wb') as f:
                    f.write(faiss_file.read())

                with open(local_pkl_path, 'wb') as f:
                    f.write(pkl_file.read())

                # Load the index from the temp directory
                return FAISS.load_local(
                    temp_dir, self.embeddings, allow_dangerous_deserialization=True
                )
            except Exception as e:
                logging.error(f"Error loading FAISS index from remote storage: {e}")
                raise

    def _upload_index_to_remote(self, local_folder):
        try:
            # Get paths to the index files
            local_faiss_path = os.path.join(local_folder, "index.faiss")
            local_pkl_path = os.path.join(local_folder, "index.pkl")

            remote_faiss_path = f"{self.storage_path}/index.faiss"
            remote_pkl_path = f"{self.storage_path}/index.pkl"

            # Upload both files to remote storage
            with open(local_faiss_path, 'rb') as f:
                self.storage.save_file(f, remote_faiss_path)

            with open(local_pkl_path, 'rb') as f:
                self.storage.save_file(f, remote_pkl_path)

            logging.info(f"Successfully uploaded FAISS index to {self.storage_path}")
        except Exception as e:
            logging.error(f"Error uploading FAISS index to remote storage: {e}")
            raise
