"""Format retrieved RAG documents for LLM prompts (numbered excerpts, page labels)."""

from typing import Any, Dict, List, Optional


def format_rag_excerpt(doc: Dict[str, Any], index: int) -> str:
    """Single excerpt with stable [N] label and optional page for citations."""
    filename = doc.get("filename") or doc.get("title") or doc.get("source") or "source"
    text = doc.get("text") or ""
    label_parts = [f"[{index}]"]
    page = doc.get("page")
    if page is not None:
        label_parts.append(f"p.{page}")
    header = " ".join(label_parts)
    if isinstance(filename, str) and filename.strip():
        return f"{header} {filename}\n{text}"
    return f"{header}\n{text}"


def build_numbered_docs_together(docs: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """Join retrieved docs with [1] p.N filename headers and a short citation rule."""
    if not docs:
        return None
    eligible: List[Dict[str, Any]] = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        text = d.get("text")
        if not isinstance(text, str):
            continue
        eligible.append(d)
    if not eligible:
        return None
    parts = [format_rag_excerpt(doc, i) for i, doc in enumerate(eligible, start=1)]
    body = "\n\n".join(parts)
    note = (
        "When answering, cite excerpts using bracketed numbers exactly as shown "
        "above (e.g. [1], [2]) at the end of sentences that rely on that excerpt."
    )
    return f"{note}\n\n{body}"
