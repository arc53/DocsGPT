"""Let the model search the knowledge graph itself, one edge at a time.

Graph retrieval normally runs as a ranker: seed a walk from the question,
diffuse mass over a subgraph, hand back the highest-scoring chunks. Measured
across five corpora that never beat plain vector search, because a question
whose answer lives two documents away has nothing in it for the seeding step to
match — the bridging entity is named in the *first* document, not the question.

Exposing the graph as tools removes the guess. The model can look up the
service, read which store it names, then fetch that store's page: the chain
followed deliberately rather than approximated by a diffusion. On a corpus built
so that vector search cannot shortcut the chain, this took two-hop answers from
1/8 to 8/8, against 0.40 for vector and 0.47 for one-shot graph retrieval.

It is not a general win, and is deliberately not a default. On ordinary prose
documentation it *lost* to plain vector search (0.50 against 0.90): it answers
well when a question names an entity and wanders when the question is a task
description. It also costs several model round-trips per answer instead of one.
So it is offered only where a source owner has already chosen search over
prefetch — the per-source exposure setting, or an agentic/research agent — and
suits content that is genuinely chain-structured: runbooks, service catalogues,
infrastructure inventories.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from docsgpt.agents.tools.base import Tool
from docsgpt.core.settings import settings

logger = logging.getLogger(__name__)

GRAPH_TOOL_ID = "graph_search"
MAX_PAGE_CHARS = 1500


class GraphSearchTool(Tool):
    """Entity lookup, relationship traversal and page reads over a source's graph."""

    internal = True

    def __init__(self, config: Dict):
        self.config = config or {}
        self._store = None
        self.retrieved_docs: List[Dict] = []

    # -- plumbing ------------------------------------------------------------
    def _sources(self) -> List[str]:
        source = self.config.get("source") or {}
        active = source.get("active_docs") or []
        if isinstance(active, str):
            active = [active]
        return [str(s) for s in active if s]

    def _get_store(self):
        if self._store is None:
            from docsgpt.graphrag.store import GraphStore

            self._store = GraphStore()
        return self._store

    def _embed(self, text: str) -> Optional[List[float]]:
        try:
            from docsgpt.vectorstore.base import get_embeddings

            return get_embeddings().embed_query(text)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Graph tool could not embed the query: {e}")
            return None

    # -- actions -------------------------------------------------------------
    def execute_action(self, action_name: str, **kwargs):
        if not settings.GRAPHRAG_ENABLED:
            return "The knowledge graph is not enabled for this deployment."
        if not self._sources():
            return "No graph-backed sources are configured."
        try:
            if action_name == "search_entities":
                return self._search_entities(**kwargs)
            if action_name == "get_relationships":
                return self._get_relationships(**kwargs)
            if action_name == "read_entity_pages":
                return self._read_entity_pages(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Graph tool action {action_name} failed: {e}", exc_info=True)
            return "The graph lookup failed."
        return f"Unknown action: {action_name}"

    def _search_entities(self, **kwargs) -> str:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return "Error: 'query' parameter is required."
        limit = max(1, min(int(kwargs.get("k") or 8), 25))

        embedding = self._embed(query)
        if embedding is None:
            return "Entity search is unavailable."

        store = self._get_store()
        lines: List[str] = []
        for source_id in self._sources():
            for row in store.search_nodes_by_embedding(source_id, embedding, k=limit):
                similarity = 1.0 - float(row.get("distance") or 0.0)
                description = (row.get("description") or "").strip()
                suffix = f" — {description[:160]}" if description else ""
                lines.append(f"- {row['name']} (match {similarity:.2f}){suffix}")
        if not lines:
            return f"No entities found for {query!r}."
        return "Entities:\n" + "\n".join(lines[:limit])

    def _get_relationships(self, **kwargs) -> str:
        entity = str(kwargs.get("entity") or "").strip()
        if not entity:
            return "Error: 'entity' parameter is required."

        store = self._get_store()
        lines: List[str] = []
        for source_id in self._sources():
            for edge in store.entity_relationships(source_id, entity):
                relation = edge.get("type") or "related to"
                lines.append(f"- {edge['source']} --{relation}--> {edge['target']}")
        if not lines:
            return (
                f"No relationships found for {entity!r}. Try search_entities first "
                "to get the exact name used in the graph."
            )
        return f"Relationships for {entity!r}:\n" + "\n".join(lines)

    def _read_entity_pages(self, **kwargs) -> str:
        entity = str(kwargs.get("entity") or "").strip()
        if not entity:
            return "Error: 'entity' parameter is required."

        store = self._get_store()
        parts: List[str] = []
        for source_id in self._sources():
            for page in store.entity_pages(source_id, entity):
                metadata = page.get("metadata") or {}
                title = (
                    metadata.get("file_path")
                    or metadata.get("title")
                    or metadata.get("source")
                    or "document"
                )
                text = (page.get("text") or "")[:MAX_PAGE_CHARS]
                doc = {"title": title, "text": text, "source": metadata.get("source", "")}
                if doc not in self.retrieved_docs:
                    self.retrieved_docs.append(doc)
                parts.append(f"--- {title} ---\n{text}")
        if not parts:
            return f"No documents mention {entity!r}."
        return "\n\n".join(parts)

    # -- metadata ------------------------------------------------------------
    def get_actions_metadata(self):
        return [
            {
                "name": "search_entities",
                "description": (
                    "Find named things in the knowledge graph — services, components, "
                    "settings, people — whose names resemble a query. Use this first to "
                    "learn the exact name the graph uses before asking for its "
                    "relationships."
                ),
                "parameters": {
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to look for, e.g. a service or component name.",
                            "filled_by_llm": True,
                            "required": True,
                        },
                        "k": {
                            "type": "integer",
                            "description": "How many entities to return (default 8).",
                            "filled_by_llm": True,
                            "required": False,
                        },
                    }
                },
            },
            {
                "name": "get_relationships",
                "description": (
                    "List what an entity is connected to, as 'source --relation--> target'. "
                    "This is how you answer a question about something the question does not "
                    "name: look up what it points at, then read that thing's pages."
                ),
                "parameters": {
                    "properties": {
                        "entity": {
                            "type": "string",
                            "description": "Exact entity name, as returned by search_entities.",
                            "filled_by_llm": True,
                            "required": True,
                        }
                    }
                },
            },
            {
                "name": "read_entity_pages",
                "description": (
                    "Read the documentation an entity appears in, the page it is about "
                    "first. Use this once you know which entity holds the answer."
                ),
                "parameters": {
                    "properties": {
                        "entity": {
                            "type": "string",
                            "description": "Exact entity name, as returned by search_entities.",
                            "filled_by_llm": True,
                            "required": True,
                        }
                    }
                },
            },
        ]

    def get_config_requirements(self):
        return {}


def build_graph_tool_entry() -> Dict:
    """The synthetic ``tools_dict`` entry for the graph tool."""
    tool = GraphSearchTool({})
    actions = []
    for action in tool.get_actions_metadata():
        entry = dict(action)
        entry["active"] = True
        actions.append(entry)
    return {"name": "graph_search", "actions": actions}


def sources_have_graph(source: Dict) -> bool:
    """Whether any active source actually has a graph to search."""
    active = source.get("active_docs") or []
    if isinstance(active, str):
        active = [active]
    if not active:
        return False
    try:
        from docsgpt.graphrag.store import GraphStore

        counts = GraphStore().count_nodes_many([str(a) for a in active])
        return any(count > 0 for count in counts.values())
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Could not check for graphs: {e}")
        return False


def add_graph_search_tool(tools_dict: Dict, retriever_config: Dict) -> None:
    """Add the graph tool when the agent's search-tool sources include a graph.

    No setting of its own: ``retriever_config`` already carries exactly the
    sources the agent may *search* — the ones a source owner exposed as a
    search tool, or every source for an agentic/research agent — so the graph
    tool follows that same per-source exposure choice. A graph source left at
    ``prefetch`` in a classic agent is used for ranking only.
    """
    if not settings.GRAPHRAG_ENABLED:
        return
    source = retriever_config.get("source") or {}
    if not source.get("active_docs") or not sources_have_graph(source):
        return

    entry = build_graph_tool_entry()
    # The executor resolves tools by ``id``; this one is synthetic (no DB row).
    entry["id"] = GRAPH_TOOL_ID
    entry["config"] = {"source": source}
    tools_dict[GRAPH_TOOL_ID] = entry


def build_graph_tool_config(source: Dict, **_ignored: Any) -> Dict:
    """Config for :class:`GraphSearchTool` — it only needs the source ids."""
    return {"source": source}
