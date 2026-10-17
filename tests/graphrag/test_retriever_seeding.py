"""Where the graph walk starts, per the source's graph retrieval options.

Seeding decides more than ranking does — a walk that starts on the wrong nodes
cannot be rescued downstream. The options are per source and live (no
re-ingest), carried on the per-source retrieval config the Dispatcher hands the
retriever, so both the dispatch and how the options are resolved are pinned.

The fallback matters most: relationship seeding reads fact embeddings written
at ingest, and a source built before they were recorded has none. It must keep
retrieving through entity matching rather than returning nothing.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docsgpt.retriever.graph_rag import GraphRAGRetriever
from docsgpt.storage.db.source_config import GraphRetrievalConfig, RetrievalConfig

ENTITY_ROWS = [{"id": "n1", "name": "Quill", "distance": 0.2}]
FACT_ROWS = [
    {"id": "f1", "name": "Alder", "distance": 0.1},
    {"id": "f2", "name": "Quill", "distance": 0.1},
]


class _StubStore:
    def __init__(self, fact_rows=None):
        self.fact_rows = list(FACT_ROWS) if fact_rows is None else fact_rows
        self.calls: list[str] = []

    def seed_nodes_from_facts(self, source_id, query_embedding, fact_limit=5, limit=10):
        self.calls.append("facts")
        return self.fact_rows

    def search_nodes_by_embedding(self, source_id, query_embedding, k=10):
        self.calls.append("entities")
        return list(ENTITY_ROWS)


def _retriever(per_source=None):
    """A retriever without its constructor, which builds a ClassicRAG."""
    retriever = object.__new__(GraphRAGRetriever)
    if per_source is not None:
        retriever.per_source_retrieval = per_source
    return retriever


def _relationships_config():
    return RetrievalConfig(graph={"seed_strategy": "relationships"})


class TestDefaults:
    def test_measured_best_configuration_is_the_default(self):
        options = GraphRetrievalConfig()

        assert options.seed_strategy == "entities"
        assert options.passage_nodes is True
        assert options.blend_vector is True

    def test_a_source_with_no_per_source_config_gets_the_defaults(self):
        assert _retriever()._graph_options("src") == GraphRetrievalConfig()

    def test_existing_retrieval_configs_validate_without_the_new_block(self):
        """Source configs saved before this existed carry no ``graph`` key."""
        config = RetrievalConfig.model_validate({"retriever": "graphrag"})

        assert config.graph == GraphRetrievalConfig()

    @pytest.mark.parametrize(
        "bad", [{"seed_strategy": "vector"}, {"seed_strategy": "union"}, {"damping": 0.5}]
    )
    def test_retired_and_unknown_options_are_rejected(self, bad):
        with pytest.raises(ValidationError):
            GraphRetrievalConfig.model_validate(bad)


class TestEntitySeeding:
    def test_seeds_from_entities_and_never_reads_facts(self):
        store = _StubStore()

        rows = _retriever()._seed_rows(store, "src", [0.0, 0.1])

        assert [r["id"] for r in rows] == ["n1"]
        assert store.calls == ["entities"]


class TestRelationshipSeeding:
    def test_seeds_from_facts_when_the_source_asks_for_it(self):
        store = _StubStore()
        retriever = _retriever({"src": _relationships_config()})

        rows = retriever._seed_rows(store, "src", [0.0, 0.1])

        assert [r["id"] for r in rows] == ["f1", "f2"]
        assert store.calls == ["facts"]

    def test_reads_the_option_from_a_plain_dict_config_too(self):
        store = _StubStore()
        retriever = _retriever({"src": {"graph": {"seed_strategy": "relationships"}}})

        retriever._seed_rows(store, "src", [0.0, 0.1])

        assert store.calls == ["facts"]

    def test_falls_back_to_entities_without_fact_embeddings(self):
        """A source built before fact embeddings were recorded still retrieves."""
        store = _StubStore(fact_rows=[])
        retriever = _retriever({"src": _relationships_config()})

        rows = retriever._seed_rows(store, "src", [0.0, 0.1])

        assert [r["id"] for r in rows] == ["n1"]
        assert store.calls == ["facts", "entities"]

    def test_options_are_per_source(self):
        store = _StubStore()
        retriever = _retriever({"other": _relationships_config()})

        retriever._seed_rows(store, "src", [0.0, 0.1])

        assert store.calls == ["entities"]

    def test_a_malformed_stored_option_falls_back_to_the_defaults(self):
        """A bad value must not take graph retrieval down with it."""
        retriever = _retriever({"src": {"graph": {"seed_strategy": "nonsense"}}})

        assert retriever._graph_options("src") == GraphRetrievalConfig()
