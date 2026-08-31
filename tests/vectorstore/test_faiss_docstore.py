"""Tests for the FAISS sidecar formats and the langchain compatibility layer.

Two properties matter here and neither can regress quietly:

1. Indexes written by langchain must stay readable forever — ``POST
   /api/upload_index`` still accepts them, so this is not a one-off migration.
2. The reader must refuse arbitrary pickled globals. The previous
   ``pickle.load`` ran whatever an uploaded ``index.pkl`` told it to.
"""

import io
import pickle
import pickletools

import pytest

from application.vectorstore.faiss_docstore import (
    CompatUnpickler,
    LegacyDocstore,
    LegacyDocument,
    dump_json_sidecar,
    dump_pickle_sidecar,
    load_json_sidecar,
    load_pickle_sidecar,
)

DOCUMENTS = {
    "id-1": {"page_content": "The capital of France is Paris.", "metadata": {"source": "geo.txt"}},
    "id-2": {"page_content": "Postgres is a database.", "metadata": {"source": "db.txt"}},
}
MAPPING = {0: "id-1", 1: "id-2"}


def _emitted_symbols(data: bytes):
    """Return the (module, name) pairs a pickle payload references."""
    strings, symbols = [], []
    for op, arg, _ in pickletools.genops(io.BytesIO(data)):
        if op.name in ("SHORT_BINUNICODE", "BINUNICODE"):
            strings.append(arg)
        if op.name == "STACK_GLOBAL":
            symbols.append((strings[-2], strings[-1]))
    return set(symbols)


@pytest.mark.unit
class TestPickleSidecar:
    def test_round_trip(self):
        documents, mapping = load_pickle_sidecar(dump_pickle_sidecar(DOCUMENTS, MAPPING))
        assert documents == DOCUMENTS
        assert mapping == MAPPING

    def test_written_pickle_references_langchain_paths(self):
        """An older DocsGPT still has langchain, so our output must name it."""
        assert _emitted_symbols(dump_pickle_sidecar(DOCUMENTS, MAPPING)) == {
            ("langchain_core.documents.base", "Document"),
            ("langchain_community.docstore.in_memory", "InMemoryDocstore"),
        }

    def test_dump_does_not_leak_modules(self):
        import sys

        dump_pickle_sidecar(DOCUMENTS, MAPPING)
        assert not [m for m in sys.modules if m.startswith("langchain")]
        assert LegacyDocument.__module__.startswith("application.")
        assert LegacyDocstore.__module__.startswith("application.")

    def test_reads_pydantic_state_shape(self):
        """langchain's Document is a pydantic model; that is the state we get."""
        doc = LegacyDocument.__new__(LegacyDocument)
        doc.__setstate__(
            {
                "__dict__": {
                    "id": None,
                    "metadata": {"a": 1},
                    "page_content": "hello",
                    "type": "Document",
                },
                "__pydantic_extra__": None,
                "__pydantic_fields_set__": {"page_content"},
                "__pydantic_private__": None,
            }
        )
        assert doc.page_content == "hello"
        assert doc.metadata == {"a": 1}

    def test_missing_metadata_becomes_empty_dict(self):
        doc = LegacyDocument.__new__(LegacyDocument)
        doc.__setstate__({"__dict__": {"page_content": "x", "metadata": None}})
        assert doc.metadata == {}

    @pytest.mark.parametrize(
        "module,name",
        [
            ("langchain_core.documents.base", "Document"),
            ("langchain_core.documents", "Document"),
            ("langchain.schema.document", "Document"),
            ("langchain.docstore.document", "Document"),
            ("langchain_community.docstore.in_memory", "InMemoryDocstore"),
            ("langchain.docstore.in_memory", "InMemoryDocstore"),
        ],
    )
    def test_historical_module_paths_resolve(self, module, name):
        """Older langchain releases wrote these classes at different paths."""
        assert CompatUnpickler(io.BytesIO(b"")).find_class(module, name) is not None


@pytest.mark.unit
class TestUnpicklerRefusesArbitraryCode:
    def test_refuses_os_system(self):
        class Exploit:
            def __reduce__(self):
                import os

                return (os.system, ("echo pwned",))

        payload = pickle.dumps(Exploit())
        with pytest.raises(pickle.UnpicklingError, match="Refusing to load"):
            CompatUnpickler(io.BytesIO(payload)).load()

    def test_refuses_subprocess(self):
        class Exploit:
            def __reduce__(self):
                import subprocess

                return (subprocess.Popen, (["true"],))

        with pytest.raises(pickle.UnpicklingError, match="Refusing to load"):
            CompatUnpickler(io.BytesIO(pickle.dumps(Exploit()))).load()

    def test_refuses_unrelated_builtin(self):
        with pytest.raises(pickle.UnpicklingError, match="Refusing to load"):
            CompatUnpickler(io.BytesIO(b"")).find_class("builtins", "eval")

    def test_plain_unpickler_would_have_resolved_it(self):
        """Confirms the guard is load-bearing, not decorative.

        A stock Unpickler hands back ``os.system`` for the same input the
        CompatUnpickler rejects — that resolution is what made the previous
        ``pickle.load`` on uploaded indexes an arbitrary-code-execution path.
        """
        import os

        assert pickle.Unpickler(io.BytesIO(b"")).find_class("os", "system") is os.system
        with pytest.raises(pickle.UnpicklingError, match="Refusing to load"):
            CompatUnpickler(io.BytesIO(b"")).find_class("os", "system")


@pytest.mark.unit
class TestJsonSidecar:
    def test_round_trip(self):
        documents, mapping = load_json_sidecar(dump_json_sidecar(DOCUMENTS, MAPPING))
        assert documents == DOCUMENTS
        assert mapping == MAPPING

    def test_contains_no_pickle(self):
        assert b"langchain" not in dump_json_sidecar(DOCUMENTS, MAPPING)

    def test_row_keys_come_back_as_ints(self):
        _, mapping = load_json_sidecar(dump_json_sidecar(DOCUMENTS, MAPPING))
        assert all(isinstance(row, int) for row in mapping)

    def test_unicode_survives(self):
        documents = {"id": {"page_content": "café — naïve 日本語", "metadata": {}}}
        restored, _ = load_json_sidecar(dump_json_sidecar(documents, {0: "id"}))
        assert restored["id"]["page_content"] == "café — naïve 日本語"

    def test_empty_index(self):
        documents, mapping = load_json_sidecar(dump_json_sidecar({}, {}))
        assert documents == {} and mapping == {}


@pytest.mark.unit
class TestRealLegacyFixture:
    """The index.pkl checked into the repo was written by langchain in 2025."""

    def test_reads_committed_legacy_index(self):
        with open("application/index.pkl", "rb") as f:
            documents, mapping = load_pickle_sidecar(f.read())
        assert len(documents) == 3
        assert len(mapping) == 3
        assert all(d["page_content"] for d in documents.values())
        assert all(d["metadata"].get("title") for d in documents.values())

    def test_legacy_survives_conversion_to_json(self):
        with open("application/index.pkl", "rb") as f:
            documents, mapping = load_pickle_sidecar(f.read())
        restored, restored_mapping = load_json_sidecar(
            dump_json_sidecar(documents, mapping)
        )
        assert restored == documents
        assert restored_mapping == mapping
