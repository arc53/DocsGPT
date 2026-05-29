import hashlib
import hmac
import io
import logging
import os
import tempfile

from langchain_community.vectorstores import FAISS

from application.core.settings import settings
from application.parser.schema.base import Document
from application.storage.storage_creator import StorageCreator
from application.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)


def get_vectorstore(path: str) -> str:
    """Build a safe local path for a FAISS index.

    Args:
        path: Source identifier provided by the caller.

    Returns:
        The validated vectorstore path rooted under ``indexes``.

    Raises:
        ValueError: If ``path`` escapes the ``indexes`` directory.
    """
    base_dir = "indexes"
    if not path:
        return base_dir

    normalized = str(path).strip()
    if "\\" in normalized:
        raise ValueError("Invalid source_id path")

    candidate = os.path.normpath(os.path.join(base_dir, normalized))
    base_abs = os.path.abspath(base_dir)
    candidate_abs = os.path.abspath(candidate)

    if not candidate_abs.startswith(base_abs + os.sep) and candidate_abs != base_abs:
        raise ValueError("Invalid source_id path")

    return candidate


def _integrity_key() -> bytes:
    """Derive an HMAC key for FAISS pickle integrity verification.

    The key is derived from ``ENCRYPTION_SECRET_KEY`` (also used for at-rest
    encryption elsewhere) so that signatures stay valid as long as the
    deployment secret does not change. A domain separator is included so the
    key cannot be confused with other uses of the same secret.
    """
    secret = (settings.ENCRYPTION_SECRET_KEY or "").encode("utf-8")
    return hashlib.sha256(b"docsgpt|faiss-pickle-integrity|v1|" + secret).digest()


def _compute_signature(data: bytes) -> str:
    return hmac.new(_integrity_key(), data, hashlib.sha256).hexdigest()


def _verify_pickle_integrity(pkl_bytes: bytes, storage, sig_storage_path: str) -> None:
    """Verify HMAC signature for a FAISS ``index.pkl`` blob before loading.

    The signature file ``index.pkl.sig`` contains a hex-encoded HMAC-SHA256 of
    the pickle bytes. If a signature is present, it MUST match. If no
    signature is present (legacy index written before this protection was
    added), a Trust-On-First-Use signature is created from the current bytes
    and a warning is emitted; subsequent loads are then verified strictly.

    This blocks the CWE-502 attack where a tampered ``index.pkl`` in storage
    would execute arbitrary code via :func:`pickle.load`, by ensuring the
    bytes have not been modified since they were last signed by this process.
    """
    expected = _compute_signature(pkl_bytes)

    if storage.file_exists(sig_storage_path):
        with storage.get_file(sig_storage_path) as sig_file:
            stored = sig_file.read().decode("utf-8", errors="replace").strip()
        if not hmac.compare_digest(stored, expected):
            raise ValueError(
                "FAISS index integrity check failed: signature mismatch for "
                f"{sig_storage_path}. Refusing to deserialize potentially "
                "tampered pickle data."
            )
        return

    # Legacy index without a signature: TOFU — sign the current bytes so any
    # future tampering is detected, and warn loudly.
    logger.warning(
        "No integrity signature found for %s; creating one now (trust-on-"
        "first-use). If this index was modified by an untrusted party, "
        "rebuild it from source.",
        sig_storage_path,
    )
    try:
        storage.save_file(io.BytesIO(expected.encode("utf-8")), sig_storage_path)
    except Exception as exc:  # pragma: no cover - storage backend dependent
        logger.error("Failed to persist FAISS integrity signature: %s", exc)


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
                    sig_path = f"{self.path}/index.pkl.sig"

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

                    pkl_bytes = pkl_file.read()

                    # CWE-502 mitigation: verify HMAC integrity of the pickle
                    # blob before handing it to FAISS.load_local, which calls
                    # pickle.load with allow_dangerous_deserialization=True.
                    _verify_pickle_integrity(pkl_bytes, self.storage, sig_path)

                    with open(local_pkl_path, "wb") as f:
                        f.write(pkl_bytes)

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

            # Write the integrity signature alongside the pickle so that
            # subsequent loads can detect tampering.
            signature = _compute_signature(pkl_data).encode("utf-8")
            self.storage.save_file(
                io.BytesIO(signature), f"{storage_path}/index.pkl.sig"
            )

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
