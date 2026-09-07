"""Persistence for the FAISS docstore, independent of langchain.

A FAISS index is two files: ``index.faiss`` (written by faiss itself) and a
sidecar holding the chunk text plus the row-to-id mapping. Historically that
sidecar was ``index.pkl`` — a pickled
``(InMemoryDocstore, index_to_docstore_id)`` tuple produced by langchain.

Those files are still an active ingress: ``POST /api/upload_index`` accepts
them, and every index written before this change is in that format. So the
legacy sidecar is read forever, via a :class:`CompatUnpickler` that resolves
langchain's symbols onto local stand-ins and refuses everything else — the
previous ``pickle.load`` would execute arbitrary code from an uploaded file.

``index.json`` is the format written going forward. ``index.pkl`` is written
alongside it, byte-compatible with langchain's layout, so an older DocsGPT can
still read an index this version has re-saved.
"""

import io
import json
import pickle
import sys
import types
from contextlib import contextmanager
from typing import Any, Dict, Tuple

# Module paths the legacy pickle references, mapped onto the stand-ins below.
_LEGACY_DOCUMENT_PATHS = (
    ("langchain_core.documents.base", "Document"),
    ("langchain_core.documents", "Document"),
    ("langchain.schema.document", "Document"),
    ("langchain.docstore.document", "Document"),
    ("langchain.schema", "Document"),
)
_LEGACY_DOCSTORE_PATHS = (
    ("langchain_community.docstore.in_memory", "InMemoryDocstore"),
    ("langchain.docstore.in_memory", "InMemoryDocstore"),
)

# The path langchain itself writes, and therefore the one we emit.
_CANONICAL_DOCUMENT_PATH = _LEGACY_DOCUMENT_PATHS[0]
_CANONICAL_DOCSTORE_PATH = _LEGACY_DOCSTORE_PATHS[0]


class LegacyDocument:
    """Stand-in for ``langchain_core.documents.base.Document``.

    langchain's Document is a pydantic v2 model, which pickles as
    ``__newobj__(cls)`` plus a state dict; reconstruction only needs a class
    whose ``__setstate__`` understands that shape.
    """

    __slots__ = ("page_content", "metadata", "id", "type")

    def __init__(self, page_content: str = "", metadata: Dict[str, Any] = None,
                 id: Any = None) -> None:
        self.page_content = page_content
        self.metadata = metadata if metadata is not None else {}
        self.id = id
        self.type = "Document"

    def __setstate__(self, state: Any) -> None:
        fields = state.get("__dict__", state) if isinstance(state, dict) else {}
        self.page_content = fields.get("page_content", "")
        self.metadata = fields.get("metadata") or {}
        self.id = fields.get("id")
        self.type = fields.get("type", "Document")

    def __getstate__(self) -> Dict[str, Any]:
        """Emit pydantic v2's pickle state so langchain can read it back."""
        return {
            "__dict__": {
                "id": self.id,
                "metadata": self.metadata,
                "page_content": self.page_content,
                "type": self.type,
            },
            "__pydantic_extra__": None,
            "__pydantic_fields_set__": {"page_content", "metadata"},
            "__pydantic_private__": None,
        }


class LegacyDocstore:
    """Stand-in for ``langchain_community.docstore.in_memory.InMemoryDocstore``."""

    def __init__(self, _dict: Dict[str, LegacyDocument] = None) -> None:
        self._dict = _dict if _dict is not None else {}

    def __setstate__(self, state: Any) -> None:
        self._dict = state.get("_dict", {}) if isinstance(state, dict) else {}

    def __getstate__(self) -> Dict[str, Any]:
        return {"_dict": self._dict}


class CompatUnpickler(pickle.Unpickler):
    """Unpickler that accepts only the symbols a FAISS sidecar may contain.

    langchain's document and docstore classes resolve to the local stand-ins;
    every other global is refused, so a hostile ``index.pkl`` cannot execute
    code through ``__reduce__``.
    """

    _ALLOWED = {
        **{path: LegacyDocument for path in _LEGACY_DOCUMENT_PATHS},
        **{path: LegacyDocstore for path in _LEGACY_DOCSTORE_PATHS},
    }

    def find_class(self, module: str, name: str):
        mapped = self._ALLOWED.get((module, name))
        if mapped is not None:
            return mapped
        raise pickle.UnpicklingError(
            f"Refusing to load unexpected symbol from FAISS index: {module}.{name}"
        )


@contextmanager
def _legacy_pickle_names():
    """Expose the stand-ins under langchain's module paths while pickling.

    ``pickle`` records a class by its module and qualified name, and verifies
    the pair resolves before writing it. Registering throwaway modules for the
    duration of the dump is what lets the output reference langchain's paths —
    and therefore stay readable by a DocsGPT that still has langchain — without
    langchain being installed here. Any pre-existing modules are restored.
    """
    installed = []
    for cls, (module_path, attr) in (
        (LegacyDocument, _CANONICAL_DOCUMENT_PATH),
        (LegacyDocstore, _CANONICAL_DOCSTORE_PATH),
    ):
        original_module = cls.__module__
        original_name = cls.__qualname__
        cls.__module__, cls.__qualname__ = module_path, attr

        parts = module_path.split(".")
        for depth in range(1, len(parts) + 1):
            parent = ".".join(parts[:depth])
            if parent not in sys.modules:
                sys.modules[parent] = types.ModuleType(parent)
                installed.append(parent)
        setattr(sys.modules[module_path], attr, cls)
        installed.append((cls, original_module, original_name))
    try:
        yield
    finally:
        for entry in reversed(installed):
            if isinstance(entry, tuple):
                cls, original_module, original_name = entry
                cls.__module__, cls.__qualname__ = original_module, original_name
            else:
                sys.modules.pop(entry, None)


def load_pickle_sidecar(data: bytes) -> Tuple[Dict[str, Dict[str, Any]], Dict[int, str]]:
    """Read a legacy ``index.pkl`` into plain dictionaries.

    Args:
        data: Raw bytes of the pickled ``(docstore, index_to_docstore_id)``.

    Returns:
        ``(documents, index_to_docstore_id)`` where ``documents`` maps a
        chunk id to ``{"page_content": ..., "metadata": ...}`` and the second
        maps a FAISS row number to a chunk id.
    """
    docstore, mapping = CompatUnpickler(io.BytesIO(data)).load()
    documents = {
        doc_id: {
            "page_content": getattr(doc, "page_content", "") or "",
            "metadata": getattr(doc, "metadata", None) or {},
        }
        for doc_id, doc in getattr(docstore, "_dict", {}).items()
    }
    return documents, {int(row): doc_id for row, doc_id in (mapping or {}).items()}


def dump_pickle_sidecar(
    documents: Dict[str, Dict[str, Any]], index_to_docstore_id: Dict[int, str]
) -> bytes:
    """Serialize to the legacy langchain layout, for backward compatibility."""
    docstore = LegacyDocstore(
        {
            doc_id: LegacyDocument(
                page_content=doc.get("page_content", ""),
                metadata=doc.get("metadata") or {},
            )
            for doc_id, doc in documents.items()
        }
    )
    with _legacy_pickle_names():
        return pickle.dumps((docstore, dict(index_to_docstore_id)), protocol=4)


def load_json_sidecar(data: bytes) -> Tuple[Dict[str, Dict[str, Any]], Dict[int, str]]:
    """Read an ``index.json`` sidecar."""
    payload = json.loads(data.decode("utf-8"))
    documents = {
        doc_id: {
            "page_content": doc.get("page_content", "") or "",
            "metadata": doc.get("metadata") or {},
        }
        for doc_id, doc in (payload.get("documents") or {}).items()
    }
    mapping = {
        int(row): doc_id
        for row, doc_id in (payload.get("index_to_docstore_id") or {}).items()
    }
    return documents, mapping


def dump_json_sidecar(
    documents: Dict[str, Dict[str, Any]], index_to_docstore_id: Dict[int, str]
) -> bytes:
    """Serialize to the pickle-free sidecar written going forward."""
    payload = {
        "version": 1,
        "documents": {
            doc_id: {
                "page_content": doc.get("page_content", ""),
                "metadata": doc.get("metadata") or {},
            }
            for doc_id, doc in documents.items()
        },
        "index_to_docstore_id": {
            str(row): doc_id for row, doc_id in index_to_docstore_id.items()
        },
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")
