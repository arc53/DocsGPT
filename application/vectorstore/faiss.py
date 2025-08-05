import os
import tempfile
import io

from langchain_community.vectorstores import FAISS

from application.core.settings import settings
from application.parser.schema.base import Document
from application.vectorstore.base import BaseVectorStore
from application.storage.storage_creator import StorageCreator


def get_vectorstore(path: str) -> str:
    if path:
        vectorstore = f"indexes/{path}"
    else:
        vectorstore = "indexes"
    return vectorstore


class FaissStore(BaseVectorStore):
    def __init__(self, source_id: str, embeddings_key: str, docs_init=None):
        super().__init__()
        self.source_id = source_id
        self.path = get_vectorstore(source_id)
        self.embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        self.storage = StorageCreator.get_storage()

        try:
            if docs_init:
                self.docsearch = FAISS.from_documents(docs_init, self.embeddings)
            else:
                with tempfile.TemporaryDirectory() as temp_dir:
                    faiss_path = f"{self.path}/index.faiss"
                    pkl_path = f"{self.path}/index.pkl"

                    if not self.storage.file_exists(
                        faiss_path
                    ) or not self.storage.file_exists(pkl_path):
                        raise FileNotFoundError(
                            f"Index files not found in storage at {self.path}"
                        )

                    faiss_file = self.storage.get_file(faiss_path)
                    pkl_file = self.storage.get_file(pkl_path)

                    local_faiss_path = os.path.join(temp_dir, "index.faiss")
                    local_pkl_path = os.path.join(temp_dir, "index.pkl")

                    with open(local_faiss_path, "wb") as f:
                        f.write(faiss_file.read())

                    with open(local_pkl_path, "wb") as f:
                        f.write(pkl_file.read())

                    self.docsearch = FAISS.load_local(
                        temp_dir, self.embeddings, allow_dangerous_deserialization=True
                    )
        except Exception as e:
            raise Exception(f"Error loading FAISS index: {str(e)}")

        self.assert_embedding_dimensions(self.embeddings)

    def search(self, *args, **kwargs):
        return self.docsearch.similarity_search(*args, **kwargs)

    def add_texts(self, *args, **kwargs):
        return self.docsearch.add_texts(*args, **kwargs)

    def _save_to_storage(self):
        """
        Save the FAISS index to storage using temporary directory pattern.
        Works consistently for both local and S3 storage.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            self.docsearch.save_local(temp_dir)

            faiss_path = os.path.join(temp_dir, "index.faiss")
            pkl_path = os.path.join(temp_dir, "index.pkl")

            with open(faiss_path, "rb") as f_faiss:
                faiss_data = f_faiss.read()

            with open(pkl_path, "rb") as f_pkl:
                pkl_data = f_pkl.read()

            storage_path = get_vectorstore(self.source_id)
            self.storage.save_file(io.BytesIO(faiss_data), f"{storage_path}/index.faiss")
            self.storage.save_file(io.BytesIO(pkl_data), f"{storage_path}/index.pkl")

        return True

    def save_local(self, path=None):
        if path:
            os.makedirs(path, exist_ok=True)
            self.docsearch.save_local(path)

        self._save_to_storage()

        return True

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
        """Add a new chunk and save to storage."""
        metadata = metadata or {}
        doc = Document(text=text, extra_info=metadata).to_langchain_format()
        doc_id = self.docsearch.add_documents([doc])
        self._save_to_storage()
        return doc_id



    def delete_chunk(self, chunk_id):
        """Delete a chunk and save to storage."""
        self.delete_index([chunk_id])
        self._save_to_storage()
        return True
