import hashlib
import io
import logging
import os
import tempfile
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np

from docsgpt.core.settings import settings
from docsgpt.storage.storage_creator import StorageCreator
from docsgpt.vectorstore.base import BaseVectorStore
from docsgpt.vectorstore.document_class import Document
from docsgpt.vectorstore.faiss_docstore import (
    dump_json_sidecar,
    dump_pickle_sidecar,
    load_json_sidecar_with_fingerprint,
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


def _sidecar_mismatch(
    ntotal: int, mapping: Dict[int, str], recorded_sha256: Optional[str], index_sha256: str,
) -> Optional[str]:
    """Why a sidecar doesn't belong to the index it sits beside, or ``None`` when it does.

    Args:
        ntotal: The index's row count.
        mapping: The sidecar's row-to-id mapping.
        recorded_sha256: The index fingerprint the sidecar was saved with, if it records one.
        index_sha256: The stored index's fingerprint.

    Returns:
        The reason, or ``None``.
    """
    if recorded_sha256 is not None and recorded_sha256 != index_sha256:
        return "was saved with another index.faiss"
    if len(mapping) != ntotal or sorted(mapping) != list(range(ntotal)):
        return f"lists {len(mapping)} rows, the index holds {ntotal}"
    return None


class FaissStore(BaseVectorStore):
    """Vector store backed by a local FAISS index.

    Holds a flat L2 index plus an in-memory docstore mapping chunk ids to
    their text and metadata, persisted through :class:`StorageCreator`.
    """

    # Ranks by L2 distance (lower is better), not cosine — so the number here
    # is NOT comparable to the ``score_threshold`` the other stores honour,
    # and must not be shown as one.
    score_kind = "l2_distance"

    def __init__(
        self,
        source_id: str,
        embeddings_key: str,
        docs_init=None,
        embedding_texts=None,
        ids=None,
        batch_size=None,
        skip_dimension_check: bool = False,
    ):
        """Open or build one source's FAISS index.

        Args:
            source_id: Source whose index to open.
            embeddings_key: API key handed to the embeddings provider.
            docs_init: Documents to build a fresh index from. Loads the stored
                index instead when omitted.
            embedding_texts: Optional bounded text used only to compute vectors;
                full document text is still stored in the sidecar.
            ids: Chunk ids to keep when building. Generated when omitted.
            batch_size: Documents per embed call when building.
            skip_dimension_check: Open an index whose width does not match the
                configured model. Only for a caller that is about to replace
                that index, such as the re-embed script, which otherwise cannot
                read the chunks it needs to rebuild from.
        """
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
                self._build_from_documents(
                    docs_init,
                    embedding_texts=embedding_texts,
                    ids=ids,
                    batch_size=batch_size,
                )
            else:
                self._load_from_storage()
        except Exception as e:
            raise Exception(f"Error loading FAISS index: {str(e)}")

        if not skip_dimension_check:
            self.assert_embedding_dimensions(self.embeddings)

    # -- Construction ----------------------------------------------------

    def _build_from_documents(
        self, docs_init, embedding_texts=None, ids=None, batch_size=None
    ) -> None:
        """Create a fresh index seeded with ``docs_init``.

        Args:
            docs_init: Documents to embed.
            embedding_texts: Optional text used only for embedding. Must align
                one-to-one with ``docs_init``; full document text is stored.
            ids: Chunk ids to keep. Generated when omitted, which renumbers
                every chunk and orphans anything referencing the old ids.
            batch_size: Documents per embed call. Without it the whole index
                goes out in one call, which a remote embeddings server rejects
                or times out on.
        """
        texts, metadatas = [], []
        for doc in docs_init:
            texts.append(getattr(doc, "page_content", None) or getattr(doc, "text", "") or "")
            metadatas.append(getattr(doc, "metadata", None) or getattr(doc, "extra_info", None) or {})

        inputs = list(embedding_texts) if embedding_texts is not None else texts
        if len(inputs) != len(texts):
            raise ValueError("embedding_texts must match docs_init length")

        faiss = _dependable_faiss_import()
        ids = list(ids) if ids else None
        step = batch_size if batch_size and batch_size > 0 else len(texts)
        for start in range(0, len(texts), max(1, step)):
            stop = start + max(1, step)
            vectors = self.embeddings.embed_documents(inputs[start:stop])
            if self.index is None:
                self.index = faiss.IndexFlatL2(len(vectors[0]))
            self._append(
                texts[start:stop],
                metadatas[start:stop],
                vectors,
                ids[start:stop] if ids else None,
            )

    def _load_from_storage(self) -> None:
        """Load the index and a sidecar that belongs to it, preferring JSON over the pickle.

        The files are saved one after another, so a save that stopped part
        way, or a sync's upload (``index.faiss`` and ``index.pkl`` only), can
        leave a sidecar from another save beside the index. A sidecar is used
        only when its rows are the index's rows (``0..ntotal-1``) and, for a
        JSON one that records it, the index's SHA-256 is the one it was saved
        with; the pickle is tried when the JSON one doesn't match.

        Raises:
            FileNotFoundError: The index or every sidecar is missing.
            ValueError: No sidecar matches the index; reading it would give
                one chunk's text for another's vector.
        """
        faiss = _dependable_faiss_import()
        faiss_path = f"{self.path}/{FAISS_INDEX}"
        json_path = f"{self.path}/{JSON_SIDECAR}"
        pickle_path = f"{self.path}/{PICKLE_SIDECAR}"

        if not self.storage.file_exists(faiss_path):
            raise FileNotFoundError(f"Index files not found in storage at {self.path}")

        candidates = []
        if self.storage.file_exists(json_path):
            candidates.append((json_path, load_json_sidecar_with_fingerprint))
        if self.storage.file_exists(pickle_path):
            candidates.append((pickle_path, lambda data: (*load_pickle_sidecar(data), None)))
        if not candidates:
            raise FileNotFoundError(f"Index files not found in storage at {self.path}")

        index_bytes = self.storage.get_file(faiss_path).read()
        with tempfile.TemporaryDirectory() as temp_dir:
            local_faiss = os.path.join(temp_dir, FAISS_INDEX)
            with open(local_faiss, "wb") as f:
                f.write(index_bytes)
            self.index = faiss.read_index(local_faiss)
        fingerprint = hashlib.sha256(index_bytes).hexdigest()

        problems = []
        for sidecar, loader in candidates:
            name = sidecar.rsplit("/", 1)[-1]
            try:
                documents, mapping, recorded = loader(self.storage.get_file(sidecar).read())
            except Exception as error:  # noqa: BLE001 - the other sidecar may still be good
                problems.append(f"{name} unreadable: {error}")
                continue
            problem = _sidecar_mismatch(self.index.ntotal, mapping, recorded, fingerprint)
            if problem is not None:
                problems.append(f"{name} {problem}")
                continue
            if problems:
                logger.warning("FAISS index at %s: %s; loaded %s instead", self.path, "; ".join(problems), name)
            self.documents, self.index_to_docstore_id = documents, mapping
            return
        raise ValueError(
            f"The FAISS index at {self.path} is out of step with its sidecar ({'; '.join(problems)}); "
            f"sync or re-ingest the source to rebuild it"
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

    def _embed_in_batches(self, texts: List[str]) -> List[List[float]]:
        """Embed ``texts`` in ``EMBEDDINGS_BATCH_SIZE`` slices, as ingest does.

        Args:
            texts: The texts to embed.

        Returns:
            One vector per text, in order.
        """
        # Imported here: the embedding pipeline imports the vector stores.
        from docsgpt.parser.embedding_pipeline import _resolve_batch_size

        step = _resolve_batch_size()
        vectors: List[List[float]] = []
        for start in range(0, len(texts), step):
            vectors.extend(self.embeddings.embed_documents(texts[start:start + step]))
        return vectors

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
        self,
        question: str,
        k: int = 4,
        *args,
        query_vector: Optional[List[float]] = None,
        **kwargs,
    ) -> List[Tuple[Document, float]]:
        """Same search as :meth:`search`, pairing each hit with its L2 distance.

        Args:
            query_vector: Precomputed embedding of ``question``; when given the
                store skips embedding the query itself.
        """
        # FAISS has no relevance-threshold knob; drop it so the per-source
        # score_threshold is safely ignored rather than crashing the forward.
        kwargs.pop("score_threshold", None)
        if self.index is None or self.index.ntotal == 0:
            return []

        if query_vector is None:
            query_vector = self.embeddings.embed_query(question)
        vector = np.array([query_vector], dtype=np.float32)
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
        """Embed and append ``texts`` to the index.

        The texts go to the embeddings provider in ``EMBEDDINGS_BATCH_SIZE``
        slices: a long page's chunks in one request would pass a remote
        provider's per-request limits. Every slice is embedded before any row
        is added, so a failed slice adds nothing.
        """
        texts = list(texts)
        if not texts:
            return []
        metadatas = list(metadatas or [{} for _ in texts])
        vectors = self._embed_in_batches(texts)
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

    def _own_metadata(self, metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """A copy of chunk metadata whose ``source_id`` is this index's source.

        Metadata from the chunk API is the caller's; as in the other stores, it
        cannot move a chunk to another source.

        Args:
            metadata: The chunk's metadata as given.

        Returns:
            The metadata, ``source_id`` set to this store's (left as given when
            the store has none).
        """
        own = dict(metadata or {})
        source_id = str(self.source_id or "").replace("docsgpt/indexes/", "").rstrip("/")
        if source_id:
            own["source_id"] = source_id
        return own

    def add_chunk(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Add a new chunk and save to storage; its ``source_id`` is this index's source."""
        ids = self.add_texts([text], [self._own_metadata(metadata)])
        self._save_to_storage()
        return ids[0]

    def add_chunks(self, texts: List[str], metadatas: Optional[List[Dict[str, Any]]] = None) -> List[str]:
        """Add several chunks and save to storage once.

        Each save rewrites the whole index, so adding a page one chunk at a
        time would rewrite it once per chunk. All the texts are embedded
        before any is added, so a failed embed adds nothing; a failed save
        takes the chunks back out (``_save_or_undo``).

        Args:
            texts: The chunks' texts.
            metadatas: Their metadata, one dict per text; ``source_id`` is
                this index's source whatever it says.

        Returns:
            The new chunks' ids, in order.
        """
        texts = list(texts)
        if not texts:
            return []
        metadatas = list(metadatas) if metadatas is not None else [{} for _ in texts]
        ids = self.add_texts(texts, [self._own_metadata(metadata) for metadata in metadatas])
        self._save_or_undo(lambda: self.delete_index(ids))
        return ids

    def update_chunk(self, chunk_id: str, text: str, metadata: Dict[str, Any]) -> str:
        """Replace a chunk in place, keeping its id and its place in the docstore.

        The new vector is computed before anything changes, so a failed embed
        leaves the chunk as it was. Its old row is removed from the index and
        the new vector appended; the row mapping is renumbered to match, and
        the docstore entry is replaced where it stands so :meth:`get_chunks`
        keeps its order. Saved to storage once.

        A failed save puts the chunk back as it was (``_save_or_undo``).

        Args:
            chunk_id: Id of the chunk to replace.
            text: The chunk's new text.
            metadata: The chunk's complete new metadata; ``source_id`` is
                this index's source whatever it says.

        Returns:
            ``chunk_id``, unchanged.

        Raises:
            KeyError: If ``chunk_id`` is not in this index.
            ValueError: If the new vector's width does not match the index.
        """
        if chunk_id not in self.documents:
            raise KeyError(f"Chunk id not found in index: {chunk_id}")
        rows_by_id = {doc_id: row for row, doc_id in self.index_to_docstore_id.items()}
        if chunk_id not in rows_by_id:
            raise KeyError(f"Chunk id has no row in the FAISS index: {chunk_id}")

        vector = np.array(self.embeddings.embed_documents([text]), dtype=np.float32)
        if vector.ndim != 2 or vector.shape != (1, self.index.d):
            raise ValueError(
                f"Embedding for chunk {chunk_id} has shape {vector.shape}, "
                f"expected (1, {self.index.d})"
            )

        old_vector = self.index.reconstruct(rows_by_id[chunk_id]).reshape(1, -1)
        old_document = self.documents[chunk_id]
        self._replace_vector(chunk_id, vector)
        self.documents[chunk_id] = {
            "page_content": text,
            "metadata": self._own_metadata(metadata),
        }

        def undo() -> None:
            self._replace_vector(chunk_id, old_vector)
            self.documents[chunk_id] = old_document

        self._save_or_undo(undo)
        return chunk_id

    def _replace_vector(self, chunk_id: str, vector: np.ndarray) -> None:
        """Swap one chunk's vector, renumbering the rows to match.

        Args:
            chunk_id: A chunk with a row in the index.
            vector: Its new vector, shape ``(1, d)``.
        """
        row = next(r for r, doc_id in self.index_to_docstore_id.items() if doc_id == chunk_id)
        self.index.remove_ids(np.array([row], dtype=np.int64))
        self.index.add(np.asarray(vector, dtype=np.float32))
        # remove_ids compacts the index and add appends, so the edited chunk's
        # vector is now the last row; renumber as delete_index does.
        remaining = [
            doc_id
            for current_row, doc_id in sorted(self.index_to_docstore_id.items())
            if current_row != row
        ]
        self.index_to_docstore_id = dict(enumerate(remaining + [chunk_id]))

    def delete_chunk(self, chunk_id: str) -> bool:
        """Delete a chunk and save to storage."""
        if chunk_id not in self.documents:
            raise ValueError(f"Chunk ids not found in index: {[chunk_id]}")
        self.delete_chunks([chunk_id])
        return True

    def delete_chunks(self, chunk_ids: Iterable[str]) -> int:
        """Delete several chunks and save to storage once.

        Each save rewrites the whole index, so deleting a page (or a folder of
        pages) one chunk at a time would rewrite it once per chunk. A failed
        save puts the chunks back (``_save_or_undo``), so a caller listing the
        store again sees them still there.

        Args:
            chunk_ids: Ids to delete; ones not in the index are ignored.

        Returns:
            How many were deleted.
        """
        present = list(dict.fromkeys(cid for cid in chunk_ids if cid in self.documents))
        if not present:
            return 0
        rows_by_id = {doc_id: row for row, doc_id in self.index_to_docstore_id.items()}
        removed = [
            (doc_id, self.index.reconstruct(rows_by_id[doc_id]), self.documents[doc_id]) for doc_id in present
        ]
        documents_before = dict(self.documents)
        self.delete_index(present)

        def undo() -> None:
            self._append(
                [document["page_content"] for _, _, document in removed],
                [document["metadata"] for _, _, document in removed],
                [vector for _, vector, _ in removed],
                [doc_id for doc_id, _, _ in removed],
            )
            # Back in their places in the docstore, so get_chunks keeps its order.
            self.documents = documents_before

        self._save_or_undo(undo)
        return len(present)

    # -- Persistence -----------------------------------------------------

    def _save_or_undo(self, undo: Callable[[], None]) -> None:
        """Save, or undo the change in memory and try to put storage back, raising the save's error.

        A save that stopped part way may have stored some of the files; saving
        the undone index again stores the previous state whole when storage
        lets it. When it doesn't, the files still never pair wrongly: the JSON
        sidecar is written last and names its index (``_save_to_storage``).

        Args:
            undo: Puts the loaded index back as it was before the change.

        Raises:
            Exception: Whatever the save raised.
        """
        try:
            self._save_to_storage()
        except Exception:
            undo()
            try:
                self._save_to_storage()
            except Exception:  # noqa: BLE001 - the first error is the one to report
                logger.error(
                    "Could not store the FAISS index of source %s again after a failed save; "
                    "it is read back from whichever whole save its files hold",
                    self.source_id, exc_info=True,
                )
            raise

    def _write_index_files(self, directory: str) -> None:
        """Write index.faiss plus both sidecars into ``directory``.

        The JSON sidecar records the SHA-256 of the ``index.faiss`` written
        with it (see ``_load_from_storage``).
        """
        faiss = _dependable_faiss_import()
        os.makedirs(directory, exist_ok=True)
        index_path = os.path.join(directory, FAISS_INDEX)
        faiss.write_index(self.index, index_path)
        digest = hashlib.sha256()
        with open(index_path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                digest.update(block)
        with open(os.path.join(directory, JSON_SIDECAR), "wb") as f:
            f.write(dump_json_sidecar(self.documents, self.index_to_docstore_id, digest.hexdigest()))
        with open(os.path.join(directory, PICKLE_SIDECAR), "wb") as f:
            f.write(dump_pickle_sidecar(self.documents, self.index_to_docstore_id))

    def _save_to_storage(self) -> bool:
        """Persist the index through the configured storage backend.

        Each file is replaced atomically by the backend, but the three are
        written one after another, so a save can stop between them. The order
        makes every such stop readable: ``index.pkl``, then ``index.faiss``,
        then ``index.json``, which names the index it belongs to and so marks
        the save complete. Stopped before the index: the old index and the old
        JSON still match. Stopped after it: the old JSON names another index,
        and the new pickle beside the new index is read instead.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            self._write_index_files(temp_dir)
            storage_path = get_vectorstore(self.source_id)
            for name in (PICKLE_SIDECAR, FAISS_INDEX, JSON_SIDECAR):
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
        """Check the index width matches the embedding model's width.

        This used to run only when ``EMBEDDINGS_NAME`` was mpnet, so every
        other model skipped the check entirely -- exactly the models most
        likely to differ from an index built earlier. It now runs for any
        model that reports a width.
        """
        word_embedding_dimension = getattr(embeddings, "dimension", None)
        if word_embedding_dimension is None:
            # A remote model of unknown width reports None until its first
            # call; there is nothing to compare yet.
            return
        if self.index is None:
            return
        if word_embedding_dimension != self.index.d:
            raise ValueError(
                f"Embedding dimension mismatch: {settings.EMBEDDINGS_NAME} produces "
                f"{word_embedding_dimension}-dim vectors but this FAISS index is "
                f"{self.index.d}-dim. The index was built with a different "
                f"embedding model; re-embed it with "
                f"`python -m docsgpt.scripts.reembed` or point "
                f"EMBEDDINGS_NAME back at the original model."
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
