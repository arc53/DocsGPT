"""The graph exposed to an agent as callable tools.

Ranking with a graph never beat vector search in measurement; letting a model
*follow* an edge did, on content where the answer is two documents away. These
tests cover the contract that makes that possible — the tool must return the
relationships verbatim enough for the model to read a name out of them, and
must refuse clearly rather than silently when it has nothing to offer.
"""

from __future__ import annotations

import pytest

from docsgpt.agents.tools.graph_search import (
    GRAPH_TOOL_ID,
    GraphSearchTool,
    add_graph_search_tool,
    build_graph_tool_entry,
)
from docsgpt.core.settings import settings

SOURCE = {"active_docs": ["src-1"]}


@pytest.fixture(autouse=True)
def _graph_store_is_pgvector(monkeypatch):
    """The graph only exists under pgvector, and CI's default is faiss.

    Set here rather than per test so a case that forgets it fails for its own
    reason instead of the gate; the cases about a different vector store
    override it in the test body.
    """
    monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")


class _StubStore:
    def __init__(self, nodes=None, relationships=None, pages=None):
        self._nodes = nodes or []
        self._relationships = relationships or []
        self._pages = pages or []

    def search_nodes_by_embedding(self, source_id, embedding, k=10):
        return self._nodes[:k]

    def entity_relationships(self, source_id, name, limit=25):
        return self._relationships

    def entity_pages(self, source_id, name, limit=4):
        return self._pages


def _tool(monkeypatch, store, enabled=True):
    monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", enabled)
    monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
    tool = GraphSearchTool({"source": SOURCE})
    tool._store = store
    monkeypatch.setattr(tool, "_embed", lambda text: [0.0, 0.1])
    return tool


class TestGating:
    def test_reports_when_graphs_are_disabled(self, monkeypatch):
        tool = _tool(monkeypatch, _StubStore(), enabled=False)

        assert "not enabled" in tool.execute_action("search_entities", query="x")

    def test_reports_when_no_sources_are_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", True)
        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
        tool = GraphSearchTool({"source": {"active_docs": []}})

        assert "No graph-backed sources" in tool.execute_action(
            "search_entities", query="x"
        )

    def test_unknown_action_is_named(self, monkeypatch):
        tool = _tool(monkeypatch, _StubStore())

        assert "Unknown action" in tool.execute_action("wander")


class TestActions:
    def test_search_entities_lists_names_with_match_strength(self, monkeypatch):
        tool = _tool(
            monkeypatch,
            _StubStore(nodes=[{"name": "Quill", "distance": 0.2, "description": "A store."}]),
        )

        result = tool.execute_action("search_entities", query="quill")

        assert "Quill" in result
        assert "0.80" in result

    def test_search_entities_requires_a_query(self, monkeypatch):
        tool = _tool(monkeypatch, _StubStore())

        assert "required" in tool.execute_action("search_entities", query="  ")

    def test_relationships_are_rendered_as_triples(self, monkeypatch):
        """The model reads the *target* out of this line to take its next step,
        so the target name has to survive rendering intact."""
        tool = _tool(
            monkeypatch,
            _StubStore(
                relationships=[
                    {"source": "Alder", "type": "streams_to", "target": "Quill", "description": ""}
                ]
            ),
        )

        result = tool.execute_action("get_relationships", entity="Alder")

        assert "Alder --streams_to--> Quill" in result

    def test_missing_relationships_suggest_the_next_step(self, monkeypatch):
        """A dead end should point at search_entities rather than stop the agent."""
        tool = _tool(monkeypatch, _StubStore(relationships=[]))

        result = tool.execute_action("get_relationships", entity="Nope")

        assert "search_entities" in result

    def test_pages_are_titled_truncated_and_recorded(self, monkeypatch):
        tool = _tool(
            monkeypatch,
            _StubStore(
                pages=[
                    {
                        "metadata": {"title": "quill-store.md", "source": "quill-store.md"},
                        "text": "x" * 5000,
                    }
                ]
            ),
        )

        result = tool.execute_action("read_entity_pages", entity="Quill")

        assert "--- quill-store.md ---" in result
        # Only what the model reads is truncated.
        assert len(result) < 3000
        # Accumulated so the answer can cite what the walk actually read.
        assert tool.retrieved_docs[0]["title"] == "quill-store.md"
        assert len(tool.retrieved_docs[0]["text"]) == 5000

    def test_page_labels_match_what_the_retrievers_record(self, monkeypatch):
        """A page read here and the same chunk retrieved by internal_search are
        one document. The citation manager keys on (source, title), so labels
        derived differently give the same document two citation numbers."""
        from docsgpt.retriever.labels import labels_from_metadata

        metadata = {"title": "Quill Store", "source": "quill-store.md"}
        text = "Quill is a write-ahead store."
        tool = _tool(monkeypatch, _StubStore(pages=[{"metadata": metadata, "text": text}]))

        tool.execute_action("read_entity_pages", entity="Quill")

        expected = labels_from_metadata(metadata, text, "src-1")
        doc = tool.retrieved_docs[0]
        assert {k: doc[k] for k in ("title", "source", "filename")} == expected
        # The full chunk text, so the doc dedupes against the retriever's copy;
        # only what the model reads is truncated.
        assert doc["text"] == text

    def test_a_page_with_no_metadata_falls_back_to_its_source_id(self, monkeypatch):
        tool = _tool(monkeypatch, _StubStore(pages=[{"metadata": {}, "text": "body"}]))

        tool.execute_action("read_entity_pages", entity="Quill")

        assert tool.retrieved_docs[0]["source"] == "src-1"

    def test_pages_absent_is_stated_plainly(self, monkeypatch):
        tool = _tool(monkeypatch, _StubStore(pages=[]))

        assert "No documents" in tool.execute_action("read_entity_pages", entity="Quill")


class TestWiring:
    def test_entry_exposes_every_action(self):
        entry = build_graph_tool_entry()

        assert {a["name"] for a in entry["actions"]} == {
            "search_entities",
            "get_relationships",
            "read_entity_pages",
        }
        assert all(action["active"] for action in entry["actions"])

    def test_not_added_when_graphs_are_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", False)
        monkeypatch.setattr(
            "docsgpt.agents.tools.graph_search.sources_have_graph", lambda source: True
        )
        tools: dict = {}

        add_graph_search_tool(tools, {"source": SOURCE})

        assert tools == {}

    def test_not_added_when_the_sources_have_no_graph(self, monkeypatch):
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", True)
        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
        monkeypatch.setattr(
            "docsgpt.agents.tools.graph_search.sources_have_graph", lambda source: False
        )
        tools: dict = {}

        add_graph_search_tool(tools, {"source": SOURCE})

        assert tools == {}

    def test_added_with_its_sentinel_id_and_source_config(self, monkeypatch):
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", True)
        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
        monkeypatch.setattr(
            "docsgpt.agents.tools.graph_search.sources_have_graph", lambda source: True
        )
        tools: dict = {}

        add_graph_search_tool(tools, {"source": SOURCE})

        assert tools[GRAPH_TOOL_ID]["id"] == GRAPH_TOOL_ID
        assert tools[GRAPH_TOOL_ID]["config"]["source"] == SOURCE


class TestPlumbing:
    def test_a_single_source_id_and_empty_entries_are_accepted(self):
        tool = GraphSearchTool({"source": {"active_docs": "src-1"}})
        assert tool._sources() == ["src-1"]

        tool = GraphSearchTool({"source": {"active_docs": ["src-1", "", None]}})
        assert tool._sources() == ["src-1"]

    def test_the_store_is_built_once_and_reused(self, monkeypatch):
        built = []
        monkeypatch.setattr(
            "docsgpt.graphrag.store.GraphStore", lambda: built.append(object()) or built[-1]
        )
        tool = GraphSearchTool({"source": SOURCE})

        assert tool._get_store() is tool._get_store()
        assert len(built) == 1

    def test_an_embedding_failure_makes_entity_search_unavailable(self, monkeypatch):
        def _broken_embeddings():
            raise RuntimeError("no model")

        monkeypatch.setattr("docsgpt.vectorstore.base.get_embeddings", _broken_embeddings)
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", True)
        tool = GraphSearchTool({"source": SOURCE})
        tool._store = _StubStore()

        assert tool.execute_action("search_entities", query="quill") == "Entity search is unavailable."

    def test_no_matching_entities_is_stated_plainly(self, monkeypatch):
        tool = _tool(monkeypatch, _StubStore())

        assert "No entities found" in tool.execute_action("search_entities", query="quill")

    def test_a_failing_store_is_reported_not_raised(self, monkeypatch):
        class _BrokenStore(_StubStore):
            def entity_relationships(self, source_id, name, limit=25):
                raise RuntimeError("connection lost")

        tool = _tool(monkeypatch, _BrokenStore())

        assert tool.execute_action("get_relationships", entity="Quill") == "The graph lookup failed."


class TestSourcesHaveGraph:
    """Whether to offer the tool at all: only when some source has a graph."""

    def _patch_counts(self, monkeypatch, counts=None, error=None):
        class _Store:
            def count_nodes_many(self, source_ids):
                if error:
                    raise error
                return {s: counts.get(s, 0) for s in source_ids}

        monkeypatch.setattr("docsgpt.graphrag.store.GraphStore", _Store)

    def test_true_when_any_source_has_nodes(self, monkeypatch):
        from docsgpt.agents.tools.graph_search import sources_have_graph

        self._patch_counts(monkeypatch, {"b": 12})
        assert sources_have_graph({"active_docs": ["a", "b"]}) is True

    def test_false_when_no_source_has_nodes(self, monkeypatch):
        from docsgpt.agents.tools.graph_search import sources_have_graph

        self._patch_counts(monkeypatch, {})
        assert sources_have_graph({"active_docs": "a"}) is False

    def test_false_without_sources_or_when_the_check_fails(self, monkeypatch):
        from docsgpt.agents.tools.graph_search import sources_have_graph

        assert sources_have_graph({"active_docs": []}) is False
        self._patch_counts(monkeypatch, error=RuntimeError("no pgvector"))
        assert sources_have_graph({"active_docs": ["a"]}) is False


class TestGraphsMustBeAvailable:
    """The graph lives in the pgvector store, so the flag alone is not enough.

    With another vector store configured the graph tables are not the ones the
    sources were ingested into; everything else in the app asks
    ``graphrag_available()``, which requires both.
    """

    def test_the_tool_is_not_offered_without_pgvector(self, monkeypatch):
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", True)
        monkeypatch.setattr(settings, "VECTOR_STORE", "faiss")
        monkeypatch.setattr(
            "docsgpt.agents.tools.graph_search.sources_have_graph",
            lambda source: pytest.fail("must not reach the database"),
        )
        tools = {}
        add_graph_search_tool(tools, {"source": SOURCE})
        assert tools == {}

    def test_actions_report_it_rather_than_querying(self, monkeypatch):
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", True)
        monkeypatch.setattr(settings, "VECTOR_STORE", "faiss")
        tool = GraphSearchTool({"source": SOURCE})
        tool._store = _StubStore(nodes=[{"name": "Quill", "distance": 0.1}])

        assert "not enabled" in tool.execute_action("search_entities", query="quill")


class TestPooledConnection:
    """The tool is cached for the whole agent run; its connection must not be."""

    class _ClosingStore(_StubStore):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.closed = 0

        def close(self):
            self.closed += 1

    def test_the_connection_goes_back_after_each_action(self, monkeypatch):
        store = self._ClosingStore(relationships=[{"source": "A", "target": "B", "type": "r"}])
        tool = _tool(monkeypatch, store)

        tool.execute_action("get_relationships", entity="A")

        # Held open, one pooled connection would be pinned across every LLM
        # round trip of the run.
        assert store.closed == 1
        assert tool._store is None

    def test_a_failing_action_still_releases_it(self, monkeypatch):
        class _Broken(self._ClosingStore):
            def entity_relationships(self, source_id, name, limit=25):
                raise RuntimeError("connection lost")

        store = _Broken()
        tool = _tool(monkeypatch, store)

        assert tool.execute_action("get_relationships", entity="A") == "The graph lookup failed."
        assert store.closed == 1
        assert tool._store is None
