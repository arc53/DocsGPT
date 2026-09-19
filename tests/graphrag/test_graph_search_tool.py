"""The graph exposed to an agent as callable tools.

Ranking with a graph never beat vector search in measurement; letting a model
*follow* an edge did, on content where the answer is two documents away. These
tests cover the contract that makes that possible — the tool must return the
relationships verbatim enough for the model to read a name out of them, and
must refuse clearly rather than silently when it has nothing to offer.
"""

from __future__ import annotations

from docsgpt.agents.tools.graph_search import (
    GRAPH_TOOL_ID,
    GraphSearchTool,
    add_graph_search_tool,
    build_graph_tool_entry,
)
from docsgpt.core.settings import settings

SOURCE = {"active_docs": ["src-1"]}


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
                pages=[{"metadata": {"file_path": "quill-store.md"}, "text": "x" * 5000}]
            ),
        )

        result = tool.execute_action("read_entity_pages", entity="Quill")

        assert "--- quill-store.md ---" in result
        assert len(result) < 3000
        # Accumulated so the answer can cite what the walk actually read.
        assert tool.retrieved_docs[0]["title"] == "quill-store.md"

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
        monkeypatch.setattr(
            "docsgpt.agents.tools.graph_search.sources_have_graph", lambda source: False
        )
        tools: dict = {}

        add_graph_search_tool(tools, {"source": SOURCE})

        assert tools == {}

    def test_added_with_its_sentinel_id_and_source_config(self, monkeypatch):
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", True)
        monkeypatch.setattr(
            "docsgpt.agents.tools.graph_search.sources_have_graph", lambda source: True
        )
        tools: dict = {}

        add_graph_search_tool(tools, {"source": SOURCE})

        assert tools[GRAPH_TOOL_ID]["id"] == GRAPH_TOOL_ID
        assert tools[GRAPH_TOOL_ID]["config"]["source"] == SOURCE
