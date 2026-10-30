"""A re-embedded source keeps the graph of every chunk whose text did not change.

A sync re-embeds the whole source, so every chunk comes back under a new id.
The graph is carried over by chunk content: unchanged chunks are re-pointed to
their new ids, removed ones are deleted and only new text is extracted. Live
``GraphStore`` on the ephemeral pytest-postgresql cluster; the LLM and the
embeddings are stubbed.
"""

from __future__ import annotations

import json
import uuid

import pytest

import docsgpt.graphrag.extraction as extraction_module
from docsgpt.storage.db.source_config import SourceConfig
from tests.graphrag.test_extraction import _ScriptedLLM, _live_store, stub_embedding  # noqa: F401

ALPHA = "Alpha is a storage engine."
BETA = "Beta replicates Alpha."
GAMMA = "Gamma schedules jobs."
GAMMA_V2 = "Delta replaced Gamma as the scheduler."


def _payload(entities, relationships=()):
    return json.dumps(
        {
            "entities": [{"name": name, "type": "thing", "description": f"{name} desc"} for name in entities],
            "relationships": [
                {"source": src, "target": dst, "type": "uses", "description": "", "weight": 1.0}
                for src, dst in relationships
            ],
        }
    )


SCRIPT = {
    ALPHA: [_payload(["Alpha"])] * 3,
    BETA: [_payload(["Beta", "Alpha"], [("Beta", "Alpha")])] * 3,
    GAMMA: [_payload(["Gamma"])] * 3,
    GAMMA_V2: [_payload(["Delta"])] * 3,
}


def _chunks(**texts_by_id):
    return [{"doc_id": chunk_id, "text": text} for chunk_id, text in texts_by_id.items()]


@pytest.mark.integration
class TestGraphSync:
    @pytest.fixture
    def store(self, monkeypatch, postgresql):
        store = _live_store(monkeypatch, postgresql.info)
        yield store
        store.close()

    @pytest.fixture
    def source_id(self):
        return str(uuid.uuid4())

    @pytest.fixture
    def llm(self, monkeypatch):
        llm = _ScriptedLLM(SCRIPT)
        monkeypatch.setattr(extraction_module.LLMCreator, "create_llm", staticmethod(lambda *a, **k: llm))
        return llm

    def _sync(self, source_id, chunks, config=None):
        """What the sync's extract_graph run does: carry the graph over, then extract what is left."""
        config = config or SourceConfig()
        to_extract = extraction_module.sync_graph_to_chunks(source_id, chunks, config=config)
        return extraction_module.extract_graph_for_source(
            source_id, "owner-1", chunks, config=config, chunk_ids=to_extract
        )

    def _build(self, source_id, chunks, config=None):
        return extraction_module.extract_graph_for_source(source_id, "owner-1", chunks, config=config or SourceConfig())

    def _links(self, store, source_id, name):
        node = store.get_node_by_normalized(source_id, name)
        if node is None:
            return None
        return sorted(store.get_chunk_ids_for_nodes(source_id, [node["id"]]).get(node["id"], []))

    def _edge_chunks(self, store, source_id):
        conn = store._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT source_chunk_ids FROM graph_edges WHERE source_id = %s;", (source_id,))
            return sorted(json.dumps(row[0]) for row in cursor.fetchall())
        finally:
            cursor.close()
            conn.rollback()

    def test_one_changed_file_extracts_only_its_chunks(self, store, source_id, llm, stub_embedding):  # noqa: F811
        try:
            self._build(source_id, _chunks(a1=ALPHA, b1=BETA, c1=GAMMA))
            llm.calls.clear()

            self._sync(source_id, _chunks(a2=ALPHA, b2=BETA, c2=GAMMA_V2))

            assert llm.calls == [GAMMA_V2]
            assert self._links(store, source_id, "alpha") == ["a2", "b2"]
            assert self._links(store, source_id, "beta") == ["b2"]
            assert self._edge_chunks(store, source_id) == ['["b2"]']
            assert self._links(store, source_id, "gamma") is None
            assert self._links(store, source_id, "delta") == ["c2"]
        finally:
            store.delete_by_source(source_id)

    def test_a_removed_file_deletes_only_its_contributions(self, store, source_id, llm, stub_embedding):  # noqa: F811
        try:
            self._build(source_id, _chunks(a1=ALPHA, b1=BETA, c1=GAMMA))
            llm.calls.clear()

            self._sync(source_id, _chunks(a2=ALPHA, b2=BETA))

            assert llm.calls == []
            assert self._links(store, source_id, "gamma") is None
            assert self._links(store, source_id, "alpha") == ["a2", "b2"]
            assert self._edge_chunks(store, source_id) == ['["b2"]']
        finally:
            store.delete_by_source(source_id)

    def test_an_unchanged_sync_makes_no_extraction_call(self, store, source_id, llm, stub_embedding):  # noqa: F811
        try:
            self._build(source_id, _chunks(a1=ALPHA, b1=BETA, c1=GAMMA))
            llm.calls.clear()

            summary = self._sync(source_id, _chunks(a2=ALPHA, b2=BETA, c2=GAMMA))

            assert llm.calls == []
            assert summary["chunks_processed"] == 0
            assert store.count_nodes(source_id) == 3
            assert self._links(store, source_id, "gamma") == ["c2"]
            assert store.pending_chunks(source_id, ["a2", "b2", "c2"]) == []
        finally:
            store.delete_by_source(source_id)

    def test_a_redelivered_sync_changes_nothing(self, store, source_id, llm, stub_embedding):  # noqa: F811
        try:
            self._build(source_id, _chunks(a1=ALPHA, b1=BETA, c1=GAMMA))
            new = _chunks(a2=ALPHA, b2=BETA, c2=GAMMA_V2)
            self._sync(source_id, new)
            llm.calls.clear()

            self._sync(source_id, new)

            assert llm.calls == []
            assert self._links(store, source_id, "delta") == ["c2"]
            assert self._links(store, source_id, "alpha") == ["a2", "b2"]
        finally:
            store.delete_by_source(source_id)

    def test_duplicate_texts_pair_up_one_to_one(self, store, source_id, llm, stub_embedding):  # noqa: F811
        try:
            self._build(source_id, _chunks(a1=ALPHA, a2=ALPHA))
            llm.calls.clear()

            self._sync(source_id, _chunks(a3=ALPHA, a4=ALPHA, a5=ALPHA))

            # Two copies carry over; the third is new text to this graph.
            assert llm.calls == [ALPHA]
            assert self._links(store, source_id, "alpha") == ["a3", "a4", "a5"]
        finally:
            store.delete_by_source(source_id)

    def test_an_extraction_config_change_rebuilds(self, store, source_id, llm, stub_embedding):  # noqa: F811
        try:
            self._build(source_id, _chunks(a1=ALPHA, b1=BETA))
            llm.calls.clear()
            changed = SourceConfig.parse({"kind": "graphrag", "graph": {"extraction_model": "another-model"}})

            self._sync(source_id, _chunks(a2=ALPHA, b2=BETA), config=changed)

            assert sorted(llm.calls) == sorted([ALPHA, BETA])
            assert self._links(store, source_id, "alpha") == ["a2", "b2"]
            llm.calls.clear()
            # Built under the new config, the next sync is incremental again.
            self._sync(source_id, _chunks(a3=ALPHA, b3=BETA), config=changed)
            assert llm.calls == []
        finally:
            store.delete_by_source(source_id)

    def test_an_embeddings_model_change_rebuilds(self, store, source_id, llm, stub_embedding, monkeypatch):  # noqa: F811
        # Node and fact embeddings come from it: kept chunks would keep vectors of another model.
        from docsgpt.core.settings import settings

        try:
            self._build(source_id, _chunks(a1=ALPHA))
            llm.calls.clear()
            monkeypatch.setattr(settings, "EMBEDDINGS_NAME", "another-embeddings-model")

            self._sync(source_id, _chunks(a2=ALPHA))

            assert llm.calls == [ALPHA]
        finally:
            store.delete_by_source(source_id)

    def test_a_graph_built_before_content_hashes_rebuilds_once(self, store, source_id, llm, stub_embedding):  # noqa: F811
        try:
            self._build(source_id, _chunks(a1=ALPHA, b1=BETA))
            conn = store._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE graph_ingest_progress SET content_hash = NULL, extraction_key = NULL WHERE source_id = %s;",
                (source_id,),
            )
            conn.commit()
            cursor.close()
            llm.calls.clear()

            self._sync(source_id, _chunks(a2=ALPHA, b2=BETA))
            assert sorted(llm.calls) == sorted([ALPHA, BETA])
            llm.calls.clear()

            self._sync(source_id, _chunks(a3=ALPHA, b3=BETA))
            assert llm.calls == []
        finally:
            store.delete_by_source(source_id)
