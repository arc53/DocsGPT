"""One numbering for every source an answer cites.

Pre-fetched chunks reach the model as ``<document index="n">`` and the client
shows the answer's sources in that order, so a ``[n]`` the model writes opens
the n-th source. The search tools number their hits from the same list: the
agent seeds a registry with its pre-fetched documents (``ToolExecutor``
holds it, never ``tools_dict``, which is saved with a paused turn), a tool
appends each new hit and labels it with its position, and the agent lists its
sources in registry order.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from docsgpt.retriever.labels import chunk_key


def citation_key(doc: Any) -> Tuple[Any, Any, Any]:
    """Identity of a retrieved chunk across retrievers and tools.

    The same chunk reached through the vector store and through the graph
    carries different extras (score, connector labels), so whole-dict
    equality would give one passage two numbers. The text is compared by its
    ``chunk_key``, taken at retrieval, because a copy's text may have changed
    since: a retrieval guardrail redacts it, and a paused turn's sources come
    back trimmed. A document without a key (saved before keys) hashes its text.

    Args:
        doc: A retrieved document dict.

    Returns:
        tuple: ``(source, title, chunk_key)``; ``(None, None, id(doc))`` for
        anything but a dict.
    """
    if isinstance(doc, dict):
        return (doc.get("source"), doc.get("title"), doc.get("chunk_key") or chunk_key(doc.get("text")))
    return (None, None, id(doc))


def register_citation(registry: Optional[List[Dict]], doc: Dict) -> Optional[int]:
    """Add ``doc`` to the registry if new and return its 1-based number.

    Args:
        registry: The answer's shared source list, or ``None`` when the tool
            runs outside an agent (it then keeps its per-call labels).
        doc: The retrieved document to number.

    Returns:
        int | None: The document's citation number, or ``None`` without a
        registry.
    """
    if registry is None:
        return None
    key = citation_key(doc)
    for index, existing in enumerate(registry):
        if citation_key(existing) == key:
            return index + 1
    registry.append(doc)
    return len(registry)
