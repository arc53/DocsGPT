import io
import logging
import os
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from application.core.settings import settings
from application.storage.storage_creator import StorageCreator
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document
from application.vectorstore.faiss_docstore import (
    dump_json_sidecar,
    dump_pickle_sidecar,
    load_json_sidecar,
    load_pickle_sidecar,
)

logger = logging.getLogger(__name__)

# Sidecar holding chunk text and the row->id mapping. ``index.json`` is what
# this version writes; ``index.pkl`` is langchain's historical format, still
# read forever (uploads arrive in it) and still written for backward compat.
JSON_SIDECAR = "index.json"
PICKLE_SIDECAR = "index.pkl"
FAISS_INDEX = "index.faiss"


def _dependable_faiss_import():
    """Import faiss, with a clearer message than the raw ImportError."""
    try:
        import faiss
    except ImportError as e:
        raise ImportError(
            "Could not import faiss. Install it with `pip install faiss-cpu`."
        ) from e
    return faiss


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


class FaissStore(BaseVectorStore):
    """Vector store backed by a local FAISS index.

    Holds a flat L2 index plus an in-memory docstore mapping chunk ids to
    their text and metadata, persisted through :class:`StorageCreator`.
    """

    # Ranks by L2 distance (lower is better), not cosine — so the number here
    # is NOT comparable to the ``score_threshold`` the other stores honour,
    # and must not be shown as one.
    score_kind = "l2_distance"

    def __init__(self, source_id: str, embeddings_key: str, docs_init=None):
        super().__init__()
        self.source_id = source_id
        self.path = get_vectorstore(source_id)
        self.embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        self.storage = StorageCreator.get_storage()

        self.index = None
        self.documents: Dict[str, Dict[str, Any]] = {}
        self.index_to_docstore_id: Dict[int, str] = {}

        try:
            if docs_init:
                self._build_from_documents(docs_init)
            else:
                self._load_from_storage()
        except Exception as e:
            raise Exception(f"Error loading FAISS index: {str(e)}")

        self.assert_embedding_dimensions(self.embeddings)

    # -- Construction ----------------------------------------------------

    def _build_from_documents(self, docs_init) -> None:
        """Create a fresh index seeded with ``docs_init``."""
        texts, metadatas = [], []
        for doc in docs_init:
            texts.append(getattr(doc, "page_content", None) or getattr(doc, "text", "") or "")
            metadatas.append(getattr(doc, "metadata", None) or getattr(doc, "extra_info", None) or {})

        faiss = _dependable_faiss_import()
        vectors = self.embeddings.embed_documents(texts)
        self.index = faiss.IndexFlatL2(len(vectors[0]))
        self._append(texts, metadatas, vectors)

    def _load_from_storage(self) -> None:
        """Load the index and its sidecar, preferring JSON over the pickle."""
        faiss = _dependable_faiss_import()
        faiss_path = f"{self.path}/{FAISS_INDEX}"
        json_path = f"{self.path}/{JSON_SIDECAR}"
        pickle_path = f"{self.path}/{PICKLE_SIDECAR}"

        if not self.storage.file_exists(faiss_path):
            raise FileNotFoundError(f"Index files not found in storage at {self.path}")

        if self.storage.file_exists(json_path):
            sidecar, loader = json_path, load_json_sidecar
        elif self.storage.file_exists(pickle_path):
            sidecar, loader = pickle_path, load_pickle_sidecar
        else:
            raise FileNotFoundError(f"Index files not found in storage at {self.path}")

        with tempfile.TemporaryDirectory() as temp_dir:
            local_faiss = os.path.join(temp_dir, FAISS_INDEX)
            with open(local_faiss, "wb") as f:
                f.write(self.storage.get_file(faiss_path).read())
            self.index = faiss.read_index(local_faiss)

        self.documents, self.index_to_docstore_id = loader(
            self.storage.get_file(sidecar).read()
        )

    # -- Internals -------------------------------------------------------

    def _append(self, texts, metadatas, vectors, ids=None) -> List[str]:
        """Add embedded rows to the index and docstore, returning their ids."""
        ids = list(ids) if ids else [str(uuid.uuid4()) for _ in texts]
        self.index.add(np.array(vectors, dtype=np.float32))
        start = len(self.index_to_docstore_id)
        for offset, (text, metadata, doc_id) in enumerate(zip(texts, metadatas, ids)):
            self.documents[doc_id] = {
                "page_content": text,
                "metadata": dict(metadata or {}),
            }
            self.index_to_docstore_id[start + offset] = doc_id
        return ids

    def _to_document(self, doc_id: str) -> Optional[Document]:
        stored = self.documents.get(doc_id)
        if stored is None:
            return None
        return Document(
            page_content=stored.get("page_content", ""),
            metadata=stored.get("metadata") or {},
        )

    # -- Search ----------------------------------------------------------

    def search(self, question: str, k: int = 4, *args, **kwargs) -> List[Document]:
        """Return the ``k`` nearest chunks for ``question``."""
        return [doc for doc, _ in self.search_with_scores(question, k, *args, **kwargs)]

    def search_with_scores(
        self, question: str, k: int = 4, *args, **kwargs
    ) -> List[Tuple[Document, float]]:
        """Same search as :meth:`search`, pairing each hit with its L2 distance."""
        # FAISS has no relevance-threshold knob; drop it so the per-source
        # score_threshold is safely ignored rather than crashing the forward.
        kwargs.pop("score_threshold", None)
        if self.index is None or self.index.ntotal == 0:
            return []

        vector = np.array([self.embeddings.embed_query(question)], dtype=np.float32)
        distances, rows = self.index.search(vector, min(k, self.index.ntotal))

        results = []
        for distance, row in zip(distances[0], rows[0]):
            if row == -1:
                continue
            doc_id = self.index_to_docstore_id.get(int(row))
            document = self._to_document(doc_id) if doc_id else None
            if document is not None:
                results.append((document, float(distance)))
        return results

    # -- Mutation --------------------------------------------------------

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[dict]] = None,
        *args,
        ids: Optional[List[str]] = None,
        **kwargs,
    ) -> List[str]:
        """Embed and append ``texts`` to the index."""
        texts = list(texts)
        if not texts:
            return []
        metadatas = list(metadatas or [{} for _ in texts])
        vectors = self.embeddings.embed_documents(texts)
        if self.index is None:
            faiss = _dependable_faiss_import()
            self.index = faiss.IndexFlatL2(len(vectors[0]))
        return self._append(texts, metadatas, vectors, ids)

    def delete_index(self, ids: Optional[List[str]] = None, *args, **kwargs):
        """Delete the given chunk ids, or the whole index when ids are omitted."""
        if ids is None:
            faiss = _dependable_faiss_import()
            dimension = self.index.d if self.index is not None else None
            self.index = faiss.IndexFlatL2(dimension) if dimension else None
            self.documents = {}
            self.index_to_docstore_id = {}
            return True

        missing = set(ids) - set(self.documents)
        if missing:
            raise ValueError(f"Chunk ids not found in index: {sorted(missing)}")

        rows_by_id = {doc_id: row for row, doc_id in self.index_to_docstore_id.items()}
        rows_to_drop = {rows_by_id[doc_id] for doc_id in ids}
        self.index.remove_ids(np.array(sorted(rows_to_drop), dtype=np.int64))
        for doc_id in ids:
            self.documents.pop(doc_id, None)

        # remove_ids compacts the index, so the mapping has to be renumbered.
        remaining = [
            doc_id
            for row, doc_id in sorted(self.index_to_docstore_id.items())
            if row not in rows_to_drop
        ]
        self.index_to_docstore_id = dict(enumerate(remaining))
        return True

    def add_chunk(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Add a new chunk and save to storage."""
        ids = self.add_texts([text], [metadata or {}])
        self._save_to_storage()
        return ids[0]

    def delete_chunk(self, chunk_id: str) -> bool:
        """Delete a chunk and save to storage."""
        self.delete_index([chunk_id])
        self._save_to_storage()
        return True

    # -- Persistence -----------------------------------------------------

    def _write_index_files(self, directory: str) -> None:
        """Write index.faiss plus both sidecars into ``directory``."""
        faiss = _dependable_faiss_import()
        os.makedirs(directory, exist_ok=True)
        faiss.write_index(self.index, os.path.join(directory, FAISS_INDEX))
        with open(os.path.join(directory, JSON_SIDECAR), "wb") as f:
            f.write(dump_json_sidecar(self.documents, self.index_to_docstore_id))
        with open(os.path.join(directory, PICKLE_SIDECAR), "wb") as f:
            f.write(dump_pickle_sidecar(self.documents, self.index_to_docstore_id))

    def _save_to_storage(self) -> bool:
        """Persist the index through the configured storage backend."""
        with tempfile.TemporaryDirectory() as temp_dir:
            self._write_index_files(temp_dir)
            storage_path = get_vectorstore(self.source_id)
            for name in (FAISS_INDEX, JSON_SIDECAR, PICKLE_SIDECAR):
                with open(os.path.join(temp_dir, name), "rb") as f:
                    self.storage.save_file(io.BytesIO(f.read()), f"{storage_path}/{name}")
        return True

    def save_local(self, path: Optional[str] = None) -> bool:
        if path:
            self._write_index_files(path)
        self._save_to_storage()
        return True

    # -- Introspection ---------------------------------------------------

    def assert_embedding_dimensions(self, embeddings) -> None:
        """Check the index width matches the embedding model's width."""
        if (
            settings.EMBEDDINGS_NAME
            == "huggingface_sentence-transformers/all-mpnet-base-v2"
        ):
            word_embedding_dimension = getattr(embeddings, "dimension", None)
            if word_embedding_dimension is None:
                raise AttributeError(
                    "'dimension' attribute not found in embeddings instance."
                )
            if self.index is None:
                return
            if word_embedding_dimension != self.index.d:
                raise ValueError(
                    f"Embedding dimension mismatch: embeddings.dimension "
                    f"({word_embedding_dimension}) != docsearch index dimension "
                    f"({self.index.d})"
                )

    def get_chunks(self) -> List[Dict[str, Any]]:
        """Return every chunk held in the index."""
        return [
            {
                "doc_id": doc_id,
                "text": stored.get("page_content", ""),
                "metadata": stored.get("metadata") or {},
            }
            for doc_id, stored in self.documents.items()
        ]
