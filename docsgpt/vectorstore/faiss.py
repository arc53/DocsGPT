import hashlib
import io
import logging
import os
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


def _check_json_sidecar(
    storage: Any, json_path: str, ntotal: int, index_sha256: str,
) -> Tuple[Optional[Dict[str, Dict[str, Any]]], Optional[Dict[int, str]], Optional[str], Optional[str]]:
    """Read a stored index.json and check whether it pairs with the stored index.

    The one rule for whether the json pairs, used by the loader and by a save
    choosing its write order (``_stored_sidecar``), so the two can't disagree.

    Args:
        storage: The storage backend.
        json_path: The index.json's storage path.
        ntotal: The stored index's row count.
        index_sha256: The stored index's fingerprint.

    Returns:
        ``(documents, mapping, recorded_sha256, problem)``: ``problem`` is
        ``None`` when the json pairs; the first three are ``None`` when it
        can't be read.
    """
    try:
        documents, mapping, recorded = load_json_sidecar_with_fingerprint(storage.get_file(json_path).read())
    except Exception as error:  # noqa: BLE001 - the pickle may still be good
        return None, None, None, f"unreadable: {error}"
    return documents, mapping, recorded, _sidecar_mismatch(ntotal, mapping, recorded, index_sha256)


# Which sidecar pairs with the stored index.faiss after each file of a save is
# written, by the save's order. A pickle is checked on its row count alone, so
# it must never be replaced while the loader would pick it; index.json names
# its index, so a stale one is passed over. Pickle-first suits a stored index
# whose index.json names it: that json stays good until index.faiss changes,
# and by then the new pickle is in place. JSON-first suits one read through
# its pickle (no index.json, or one naming another index): the new json names
# the new index, so the old pickle is still the one read until index.faiss
# changes, and the old pickle goes last.
_SAVE_ORDERS = {
    JSON_SIDECAR: ((PICKLE_SIDECAR, JSON_SIDECAR), (FAISS_INDEX, PICKLE_SIDECAR), (JSON_SIDECAR, JSON_SIDECAR)),
    PICKLE_SIDECAR: ((JSON_SIDECAR, PICKLE_SIDECAR), (FAISS_INDEX, JSON_SIDECAR), (PICKLE_SIDECAR, JSON_SIDECAR)),
}


def _store_in_pairing_order(
    storage: Any,
    directory: str,
    payloads: Dict[str, bytes],
    paired: str,
    on_written: Optional[Callable[[str], None]] = None,
) -> None:
    """Store index.faiss and both sidecars in an order that no stop between two writes can pair wrongly.

    Args:
        storage: The storage backend.
        directory: The index's storage folder.
        payloads: The bytes of each of the three files, by file name.
        paired: The sidecar that pairs with the stored index.faiss now, ``index.json`` or ``index.pkl``.
        on_written: Called after each write with the sidecar that pairs with the stored index from then on.
    """
    for name, paired_after in _SAVE_ORDERS[paired]:
        storage.save_file(io.BytesIO(payloads[name]), f"{directory}/{name}")
        if on_written is not None:
            on_written(paired_after)


def _stored_sidecar(storage: Any, directory: str) -> str:
    """Choose the sidecar that currently pairs with an index before replacing it.

    A JSON file can survive an interrupted upload while naming an older
    index. Preserve the pickle in that case, as the loader does
    (``_check_json_sidecar``). An index that can't be read pairs with
    nothing, so it never stops the save that replaces it.

    Args:
        storage: The storage backend.
        directory: The index's storage folder.

    Returns:
        The sidecar to preserve until the new index is stored.
    """
    json_path = f"{directory}/{JSON_SIDECAR}"
    index_path = f"{directory}/{FAISS_INDEX}"
    if not storage.file_exists(json_path) or not storage.file_exists(index_path):
        return PICKLE_SIDECAR
    try:
        index_bytes = storage.get_file(index_path).read()
        index = _dependable_faiss_import().deserialize_index(np.frombuffer(index_bytes, dtype=np.uint8))
    except Exception:  # noqa: BLE001 - an unreadable index is about to be replaced
        return PICKLE_SIDECAR
    problem = _check_json_sidecar(storage, json_path, index.ntotal, hashlib.sha256(index_bytes).hexdigest())[3]
    return JSON_SIDECAR if problem is None else PICKLE_SIDECAR


def store_uploaded_index(storage: Any, directory: str, index_bytes: bytes, pickle_bytes: bytes) -> None:
    """Store an index.faiss and index.pkl a worker built, with an index.json naming that index.faiss.

    The json is built here from the pickle, so a reader can tell the stored
    files belong together whatever the worker sent, and the files go in an
    order that a stop part way leaves readable (``_SAVE_ORDERS``). A stored
    index with no index.json is assumed to pair with its pickle, as the
    loader assumes.

    Args:
        storage: The storage backend.
        directory: The index's storage folder (``indexes/<source_id>``).
        index_bytes: The uploaded index.faiss.
        pickle_bytes: The uploaded index.pkl.

    Raises:
        ValueError: The pickle is not a FAISS sidecar; nothing was stored.
    """
    try:
        documents, mapping = load_pickle_sidecar(pickle_bytes)
    except Exception as error:  # noqa: BLE001 - any failure to read it means the upload is unusable
        raise ValueError(f"{PICKLE_SIDECAR} is not a FAISS sidecar: {error}") from error
    payloads = {
        FAISS_INDEX: index_bytes,
        PICKLE_SIDECAR: pickle_bytes,
        JSON_SIDECAR: dump_json_sidecar(documents, mapping, hashlib.sha256(index_bytes).hexdigest()),
    }
    paired = _stored_sidecar(storage, directory)
    _store_in_pairing_order(storage, directory, payloads, paired)


def delete_stored_index(storage: Any, directory: str) -> None:
    """Delete a source's stored index files that exist.

    Args:
        storage: The storage backend.
        directory: The index's storage folder (``indexes/<source_id>``).
    """
    for name in (JSON_SIDECAR, PICKLE_SIDECAR, FAISS_INDEX):
        path = f"{directory}/{name}"
        if storage.file_exists(path):
            storage.delete_file(path)


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
        # The sidecar that pairs with the stored index.faiss (index.json or
        # index.pkl), which picks the next save's order; None until known.
        self._paired_sidecar: Optional[str] = None

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
        way can leave a sidecar from another save beside the index. A sidecar
        is used only when its rows are the index's rows (``0..ntotal-1``) and,
        for a JSON one that records it, the index's SHA-256 is the one it was
        saved with; the pickle is tried when the JSON one doesn't match. A
        save's order keeps the pickle that pairs in place (``_SAVE_ORDERS``).

        Nothing locks out a save while this reads, so the index read can be
        older than a sidecar read after it. Once, the files are read again:
        when index.json names another index.faiss, and when an index.json
        appears while an index with none was read (a save began meanwhile, and
        its pickle may be the one just read).

        Raises:
            FileNotFoundError: The index or every sidecar is missing.
            ValueError: No sidecar matches the index; reading it would give
                one chunk's text for another's vector.
        """
        for attempt in range(2):
            if self._load_stored_pair(retry_allowed=attempt == 0):
                return

    def _load_stored_pair(self, retry_allowed: bool) -> bool:
        """One attempt of :meth:`_load_from_storage`.

        Args:
            retry_allowed: Report a read that raced a save instead of settling for the pickle.

        Returns:
            True when loaded, False when the files should be read again.

        Raises:
            FileNotFoundError: The index or every sidecar is missing.
            ValueError: No sidecar matches the index.
        """
        faiss = _dependable_faiss_import()
        faiss_path = f"{self.path}/{FAISS_INDEX}"
        json_path = f"{self.path}/{JSON_SIDECAR}"
        pickle_path = f"{self.path}/{PICKLE_SIDECAR}"

        if not self.storage.file_exists(faiss_path):
            raise FileNotFoundError(f"Index files not found in storage at {self.path}")
        index_bytes = self.storage.get_file(faiss_path).read()
        index = faiss.deserialize_index(np.frombuffer(index_bytes, dtype=np.uint8))
        fingerprint = hashlib.sha256(index_bytes).hexdigest()

        problems = []
        had_json = self.storage.file_exists(json_path)
        if had_json:
            documents, mapping, recorded, problem = _check_json_sidecar(
                self.storage, json_path, index.ntotal, fingerprint,
            )
            if problem is None:
                self._take_loaded(index, documents, mapping, JSON_SIDECAR, problems)
                return True
            if retry_allowed and recorded is not None and recorded != fingerprint:
                return False
            problems.append(f"{JSON_SIDECAR} {problem}")

        if not self.storage.file_exists(pickle_path):
            if not had_json:
                raise FileNotFoundError(f"Index files not found in storage at {self.path}")
        else:
            try:
                documents, mapping = load_pickle_sidecar(self.storage.get_file(pickle_path).read())
            except Exception as error:  # noqa: BLE001 - reported with the json's problem below
                documents = None
                problems.append(f"{PICKLE_SIDECAR} unreadable: {error}")
            if retry_allowed and not had_json and self.storage.file_exists(json_path):
                return False
            if documents is not None:
                problem = _sidecar_mismatch(index.ntotal, mapping, None, fingerprint)
                if problem is None:
                    self._take_loaded(index, documents, mapping, PICKLE_SIDECAR, problems)
                    return True
                problems.append(f"{PICKLE_SIDECAR} {problem}")
        raise ValueError(
            f"The FAISS index at {self.path} is out of step with its sidecar ({'; '.join(problems)}); "
            f"sync or re-ingest the source to rebuild it"
        )

    def _take_loaded(
        self,
        index: Any,
        documents: Dict[str, Dict[str, Any]],
        mapping: Dict[int, str],
        sidecar: str,
        problems: List[str],
    ) -> None:
        """Keep a loaded index and the sidecar that pairs with it.

        Args:
            index: The FAISS index read.
            documents: The sidecar's chunks.
            mapping: The sidecar's row-to-id mapping.
            sidecar: Which sidecar it was, ``index.json`` or ``index.pkl``.
            problems: Why the sidecars tried before it were passed over.
        """
        if problems:
            logger.warning("FAISS index at %s: %s; loaded %s instead", self.path, "; ".join(problems), sidecar)
        self.index, self.documents, self.index_to_docstore_id = index, documents, mapping
        self._paired_sidecar = sidecar

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
        """Delete a chunk and save to storage; False when this index has no such chunk."""
        return self.delete_chunks([chunk_id]) == 1

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
        lets it. When it doesn't, the files still never pair wrongly: each save
        writes its files in the order that keeps a pairing sidecar beside the
        stored index, chosen from where the last write left them
        (``_save_to_storage``).

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

    def _index_payloads(self) -> Dict[str, bytes]:
        """The bytes of index.faiss and both sidecars, by file name.

        The JSON sidecar records the SHA-256 of the ``index.faiss`` bytes beside
        it (see ``_load_from_storage``).
        """
        index_bytes = _dependable_faiss_import().serialize_index(self.index).tobytes()
        return {
            FAISS_INDEX: index_bytes,
            JSON_SIDECAR: dump_json_sidecar(
                self.documents, self.index_to_docstore_id, hashlib.sha256(index_bytes).hexdigest(),
            ),
            PICKLE_SIDECAR: dump_pickle_sidecar(self.documents, self.index_to_docstore_id),
        }

    def _save_to_storage(self) -> bool:
        """Persist the index through the configured storage backend, in ``_SAVE_ORDERS``.

        Which sidecar pairs is tracked across the writes, so a save retried
        after a failure picks its order from where the failure left the files.
        """
        storage_path = get_vectorstore(self.source_id)
        paired = self._paired_sidecar
        if paired is None:
            paired = _stored_sidecar(self.storage, storage_path)
        payloads = self._index_payloads()

        def written(now_paired: str) -> None:
            self._paired_sidecar = now_paired

        _store_in_pairing_order(self.storage, storage_path, payloads, paired, on_written=written)
        return True

    def _write_index_files(self, directory: str) -> None:
        """Write index.faiss plus both sidecars into the local folder ``directory``."""
        os.makedirs(directory, exist_ok=True)
        for name, payload in self._index_payloads().items():
            with open(os.path.join(directory, name), "wb") as f:
                f.write(payload)

    def save_local(self, path: Optional[str] = None) -> bool:
        """Store the index, and when ``path`` is given also write its files into that local folder."""
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
