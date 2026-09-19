"""Chunks as nodes in the walk, and the damping that decides how far mass spreads.

``_rank_chunks`` reads a chunk's score off its entities by summing their PPR
mass, which rewards a chunk for touching *many* entities rather than the right
ones. The passage-node path puts the chunks in the graph instead, so a chunk is
reachable both by being about the question and by being connected to what is.

These tests use a stub store: the ranking is graph arithmetic, and pinning it
against a real database would measure Postgres rather than the ranking.
"""

from __future__ import annotations

import pytest

from docsgpt.retriever.graph_rag import GraphRAGRetriever, _damping


class _StubStore:
    """The two reads the passage path makes, and nothing else."""

    def __init__(self, chunk_links, similarities):
        self._chunk_links = chunk_links
        self._similarities = similarities

    def get_chunk_ids_for_nodes(self, source_id, node_ids):
        return {n: c for n, c in self._chunk_links.items() if n in set(node_ids)}

    def chunk_similarities(self, source_id, chunk_ids, query_embedding):
        return {c: self._similarities.get(c, 0.0) for c in chunk_ids}


def _retriever(chunks=2):
    """A retriever without its constructor — which builds a ClassicRAG, opens
    settings-driven collaborators, and has nothing to do with ranking."""
    retriever = object.__new__(GraphRAGRetriever)
    retriever.chunks = chunks
    return retriever


def _subgraph():
    return {
        "nodes": [
            {"id": "a", "doc_freq": 1},
            {"id": "b", "doc_freq": 1},
            {"id": "hub", "doc_freq": 40},
        ],
        "edges": [
            {"src_node_id": "a", "dst_node_id": "hub", "weight": 1.0},
            {"src_node_id": "b", "dst_node_id": "hub", "weight": 1.0},
        ],
    }


class TestDamping:
    """Each ranking mode runs at the damping it was measured at."""

    def test_passage_walk_keeps_mass_near_the_seeds(self):
        assert _damping(passage_nodes=True) == 0.5

    def test_entity_only_ranking_keeps_the_conventional_value(self):
        assert _damping(passage_nodes=False) == 0.85


class TestPassageNodes:
    def test_ranks_the_chunk_the_question_matches(self, monkeypatch):
        """Two chunks are equally connected; only their own relevance differs,
        so the more relevant one must win."""
        store = _StubStore(
            chunk_links={"a": ["c1"], "b": ["c2"]},
            similarities={"c1": 0.1, "c2": 0.9},
        )

        ranked = _retriever()._rank_chunks_with_passages(
            store, "src", _subgraph(), {"a": 1.0, "b": 1.0}, [0.0] * 4
        )

        assert ranked[0] == "c2"

    def test_a_chunk_reached_only_through_the_graph_still_ranks(self, monkeypatch):
        """The point of the walk: a chunk with no similarity of its own is
        still reachable through the entity the seeds point at."""
        store = _StubStore(
            chunk_links={"a": ["c1"], "b": ["c2"]},
            similarities={"c1": 0.0, "c2": 0.0},
        )

        ranked = _retriever()._rank_chunks_with_passages(
            store, "src", _subgraph(), {"a": 1.0}, [0.0] * 4
        )

        assert set(ranked) == {"c1", "c2"}

    def test_no_linked_chunks_returns_nothing(self):
        store = _StubStore(chunk_links={}, similarities={})

        assert (
            _retriever()._rank_chunks_with_passages(
                store, "src", _subgraph(), {"a": 1.0}, [0.0] * 4
            )
            == []
        )

    def test_over_fetches_past_the_chunk_budget(self, monkeypatch):
        """Same contract as ``_rank_chunks``: candidates exceed the budget so
        chunks with missing text cannot drop the final count below it."""
        links = {"a": [f"c{i}" for i in range(10)]}
        store = _StubStore(
            chunk_links=links,
            similarities={f"c{i}": i / 10 for i in range(10)},
        )

        ranked = _retriever(chunks=2)._rank_chunks_with_passages(
            store, "src", _subgraph(), {"a": 1.0}, [0.0] * 4
        )

        assert len(ranked) == max(2 * 2, 2 + 5)


class TestChunkSimilaritiesGuard:
    """The store call the passage path depends on short-circuits before it
    touches a connection, so an empty subgraph costs no query."""

    @pytest.mark.parametrize(
        "chunk_ids,embedding", [([], [0.1]), (["c1"], []), ([], [])]
    )
    def test_empty_inputs_return_empty(self, chunk_ids, embedding):
        from docsgpt.graphrag.store import GraphStore

        store = object.__new__(GraphStore)

        assert store.chunk_similarities("src", chunk_ids, embedding) == {}
