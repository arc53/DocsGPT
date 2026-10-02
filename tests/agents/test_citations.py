"""One ``[n]`` numbering across pre-fetched documents and search-tool hits.

Pre-fetched chunks reach the model as ``<document index="n">`` and the client
shows the answer's sources in that order, so ``[n]`` opens the n-th source.
The search tools used to restart at ``[1]`` on every call, which made a
``[2]`` written after a tool call open the wrong source.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.agents.base import BaseAgent
from docsgpt.agents.citations import citation_key, register_citation
from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.agents.tools.graph_search import GRAPH_TOOL_ID, GraphSearchTool
from docsgpt.agents.tools.internal_search import INTERNAL_TOOL_ID, InternalSearchTool
from docsgpt.core.settings import settings
from docsgpt.retriever.labels import chunk_key


def _doc(n, **extra):
    return {"title": f"doc{n}.pdf", "source": f"doc{n}.pdf", "text": f"text {n}", **extra}


@pytest.mark.unit
class TestRegisterCitation:
    def test_none_registry_means_no_shared_numbering(self):
        assert register_citation(None, _doc(1)) is None

    def test_new_docs_are_appended_and_numbered_in_order(self):
        registry = [_doc(1), _doc(2)]
        assert register_citation(registry, _doc(3)) == 3
        assert register_citation(registry, _doc(4)) == 4
        assert [d["title"] for d in registry] == ["doc1.pdf", "doc2.pdf", "doc3.pdf", "doc4.pdf"]

    def test_a_known_doc_reuses_its_number(self):
        registry = [_doc(1), _doc(2)]
        assert register_citation(registry, _doc(2)) == 2
        assert len(registry) == 2

    def test_identity_ignores_score_and_connector_labels(self):
        # The same chunk reached through another retriever carries other extras.
        registry = [_doc(1, score=0.9, score_kind="cosine")]
        assert register_citation(registry, _doc(1, connector_name="GitHub")) == 1
        assert len(registry) == 1

    def test_key_of_a_non_dict_is_stable(self):
        assert citation_key("raw") == citation_key("raw")

    def test_key_of_an_unhashable_non_dict_is_hashable(self):
        # The merge puts every key in a set.
        hash(citation_key(["raw"]))

    def test_a_trimmed_copy_keeps_its_number(self):
        # A paused turn's sources come back cut to 1000 characters.
        full = "x" * 1500
        registry = [_doc(1), _doc(2, text=full[:1000], chunk_key=chunk_key(full))]
        assert register_citation(registry, _doc(2, text=full, chunk_key=chunk_key(full))) == 2
        assert len(registry) == 2

    def test_a_redacted_copy_keeps_its_number(self):
        # A retrieval guardrail rewrote the pre-fetched text; the tool hit has the original.
        registry = [_doc(1, text="[REDACTED]", chunk_key=chunk_key("text 1"))]
        assert register_citation(registry, _doc(1, chunk_key=chunk_key("text 1"))) == 1
        assert registry[0]["text"] == "[REDACTED]"

    def test_a_doc_without_a_key_matches_one_with_it(self):
        # A source saved before chunk keys meets a fresh hit on the same chunk.
        registry = [_doc(1)]
        assert register_citation(registry, _doc(1, chunk_key=chunk_key("text 1"))) == 1

    def test_same_text_in_another_source_is_another_citation(self):
        registry = [_doc(1, chunk_key=chunk_key("same"))]
        other = {**_doc(2), "chunk_key": chunk_key("same")}
        assert register_citation(registry, other) == 2


def _internal_tool(hits, registry):
    tool = InternalSearchTool({"source": {"active_docs": ["s1"]}, "citation_registry": registry})
    tool._retriever = MagicMock()
    tool._retriever.search.return_value = hits
    return tool


@pytest.mark.unit
class TestInternalSearchNumbering:
    def test_hits_continue_the_prefetched_numbering(self):
        registry = [_doc(1), _doc(2)]
        out = _internal_tool([_doc(3), _doc(4)], registry).execute_action("search", query="q")
        assert "[3] doc3.pdf" in out
        assert "[4] doc4.pdf" in out
        assert "[1]" not in out and "[2]" not in out
        assert len(registry) == 4

    def test_a_second_call_does_not_restart_and_reuses_known_hits(self):
        registry = [_doc(1)]
        tool = _internal_tool([_doc(2), _doc(3)], registry)
        tool.execute_action("search", query="first")
        tool._retriever.search.return_value = [_doc(3), _doc(4)]
        out = tool.execute_action("search", query="second")
        assert "[3] doc3.pdf" in out
        assert "[4] doc4.pdf" in out
        assert [d["title"] for d in registry] == ["doc1.pdf", "doc2.pdf", "doc3.pdf", "doc4.pdf"]

    def test_without_a_registry_labels_are_per_call(self):
        out = _internal_tool([_doc(7), _doc(8)], None).execute_action("search", query="q")
        assert "[1] doc7.pdf" in out
        assert "[2] doc8.pdf" in out

    def test_the_description_the_model_sees_asks_for_n_markers(self):
        from docsgpt.agents.tools.internal_search import build_internal_tool_entry

        entry = build_internal_tool_entry()
        search = next(a for a in entry["actions"] if a["name"] == "search")
        assert "[n]" in search["description"]
        tool_search = InternalSearchTool({}).get_actions_metadata()[0]
        assert "[n]" in tool_search["description"]


@pytest.mark.unit
class TestGraphSearchNumbering:
    def test_pages_are_labelled_from_the_registry(self, monkeypatch):
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", True)
        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
        registry = [_doc(1)]
        tool = GraphSearchTool({"source": {"active_docs": ["src-1"]}, "citation_registry": registry})
        store = MagicMock()
        store.entity_pages.return_value = [{"metadata": {"title": "quill.md", "source": "quill.md"}, "text": "Q"}]
        tool._store = store

        out = tool.execute_action("read_entity_pages", entity="Quill")

        assert "--- [2] quill.md ---" in out
        assert registry[1]["title"] == "quill.md"


def _search_tool_data(tool_id, name):
    return {"name": name, "id": tool_id, "actions": [], "config": {"source": {}}}


@pytest.mark.unit
class TestExecutorHandsToolsTheRegistry:
    def _load(self, executor, name, tool_id):
        with patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            executor._get_or_load_tool(_search_tool_data(tool_id, name), tool_id, "search")
        return manager.return_value.load_tool.call_args.kwargs["tool_config"]

    def test_search_tools_get_the_registry_by_reference(self):
        executor = ToolExecutor(user="u")
        executor.citation_registry = registry = [_doc(1)]
        assert self._load(executor, "internal_search", INTERNAL_TOOL_ID)["citation_registry"] is registry
        assert self._load(executor, "graph_search", GRAPH_TOOL_ID)["citation_registry"] is registry

    def test_other_tools_never_see_it(self):
        executor = ToolExecutor(user="u")
        executor.citation_registry = [_doc(1)]
        config = self._load(executor, "brave", "t1")
        assert "citation_registry" not in config

    def test_a_cached_tool_is_handed_this_turns_registry(self):
        executor = ToolExecutor(user="u")
        cached = SimpleNamespace(config={"citation_registry": [_doc(9)]})
        executor._loaded_tools[f"internal_search:{INTERNAL_TOOL_ID}:u"] = cached
        executor.citation_registry = registry = [_doc(1)]
        tool = executor._get_or_load_tool(
            _search_tool_data(INTERNAL_TOOL_ID, "internal_search"), INTERNAL_TOOL_ID, "search"
        )
        assert tool.config["citation_registry"] is registry

    def test_the_registry_is_never_in_tools_dict(self):
        # tools_dict is saved with a paused turn; a list there would be
        # serialised and come back detached from the agent's sources.
        executor = ToolExecutor(user="u")
        executor.citation_registry = [_doc(1)]
        tool_data = _search_tool_data(INTERNAL_TOOL_ID, "internal_search")
        self._load(executor, "internal_search", INTERNAL_TOOL_ID)
        assert "citation_registry" not in tool_data["config"]


def _agent(retrieved_docs, loaded_tools=None):
    executor = SimpleNamespace(citation_registry=None, _loaded_tools=loaded_tools or {})
    return SimpleNamespace(retrieved_docs=retrieved_docs, tool_executor=executor, user="u")


@pytest.mark.unit
class TestAgentRegistry:
    def test_attach_seeds_the_registry_with_the_prefetched_docs(self):
        docs = [_doc(1), _doc(2)]
        agent = _agent(docs)
        BaseAgent._attach_citation_registry(agent)
        registry = agent.tool_executor.citation_registry
        assert registry == docs
        assert registry is not docs

    def test_attach_without_an_executor_is_a_no_op(self):
        agent = SimpleNamespace(retrieved_docs=[_doc(1)])
        BaseAgent._attach_citation_registry(agent)

    def test_sources_follow_the_numbering_the_model_saw(self):
        # The graph tool ran first and took [2]; internal search took [3].
        # Merging tool by tool would list internal search's hit second.
        internal = SimpleNamespace(retrieved_docs=[_doc(3)])
        graph = SimpleNamespace(retrieved_docs=[_doc(2)])
        agent = _agent(
            [_doc(1)],
            {
                f"internal_search:{INTERNAL_TOOL_ID}:u": internal,
                f"graph_search:{GRAPH_TOOL_ID}:u": graph,
            },
        )
        agent.tool_executor.citation_registry = [_doc(1), _doc(2), _doc(3)]
        agent._search_tool_docs = lambda: BaseAgent._search_tool_docs(agent)

        BaseAgent._collect_internal_sources(agent)

        assert [d["title"] for d in agent.retrieved_docs] == ["doc1.pdf", "doc2.pdf", "doc3.pdf"]

    def test_a_redacted_prefetched_doc_is_not_listed_again_unredacted(self):
        redacted = _doc(1, text="[REDACTED]", chunk_key=chunk_key("text 1"))
        internal = SimpleNamespace(retrieved_docs=[_doc(1, chunk_key=chunk_key("text 1"))])
        agent = _agent([redacted], {f"internal_search:{INTERNAL_TOOL_ID}:u": internal})
        agent._search_tool_docs = lambda: BaseAgent._search_tool_docs(agent)

        BaseAgent._collect_internal_sources(agent)

        assert agent.retrieved_docs == [redacted]

    def test_without_a_registry_the_merge_is_unchanged(self):
        internal = SimpleNamespace(retrieved_docs=[_doc(1), _doc(2)])
        agent = _agent([_doc(1)], {f"internal_search:{INTERNAL_TOOL_ID}:u": internal})
        agent._search_tool_docs = lambda: BaseAgent._search_tool_docs(agent)

        BaseAgent._collect_internal_sources(agent)

        assert [d["title"] for d in agent.retrieved_docs] == ["doc1.pdf", "doc2.pdf"]


@pytest.mark.unit
def test_research_keeps_its_own_numbering():
    from docsgpt.agents.research_agent import ResearchAgent

    agent = _agent([_doc(1)])
    ResearchAgent._attach_citation_registry(agent)
    assert agent.tool_executor.citation_registry is None
