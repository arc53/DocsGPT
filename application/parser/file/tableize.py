"""Reconstruct typographic tables in anydoc's PDF Markdown output.

anydoc converts PDFs straight to Markdown with no document model, so tables
drawn with dot leaders or bare whitespace alignment (financial statements,
tables of contents) come out as flat text lines — values intact, structure
lost. This post-processor detects runs of such lines and rewrites them as
GFM tables: the lightweight alternative to a table-structure model for this
layout family. (The robust fix is upstream in anydoc's Rust PDF code, where
glyph x-positions exist; this is the recoverable-downstream version.)

Deliberately conservative — a run converts only when it has at least
``min_rows`` consecutive lines that each parse as ``label [leaders]
numeric-columns`` with the *same* column count; anything else passes through
untouched. Gated by ``ANYDOC_TABLEIZE`` (off by default) and applied only to
anydoc's own PDF output, never to docling's.
"""
import re
from typing import List, Optional, Tuple

# label ...... 1,234 (56) — dot-leader row
_LEADER = re.compile(r"^(.*?)\s*\.{3,}\s*(.+)$")
# numeric-ish token: $ 1,234 / (30) / 83,431 / 12.5% / —
_NUM_TOKEN = re.compile(r"\$?\(?-?\d[\d,.]*\)?%?|—")
# row without leaders: label text, then a trailing run of numeric tokens
_TRAILING = re.compile(r"^(.*?[^\s\d,.])\s+([\d$(].*)$")


def _merge_currency(tokens: List[str]) -> List[str]:
    """Join a free-standing ``$`` onto the number that follows it."""
    out: List[str] = []
    for token in tokens:
        if out and out[-1] == "$":
            out[-1] = "$" + token
        else:
            out.append(token)
    return out


def _parse_row(line: str) -> Optional[Tuple[str, List[str]]]:
    """``(label, values)`` when the line looks like a typographic table row, else None."""
    match = _LEADER.match(line) or _TRAILING.match(line)
    if not match:
        return None
    label, rest = match.group(1).strip(" ."), match.group(2)
    values = _merge_currency(rest.split())
    if not values or not all(_NUM_TOKEN.fullmatch(v.lstrip("$")) for v in values):
        return None
    if not label or _NUM_TOKEN.fullmatch(label):
        return None
    return label, values


def tableize(markdown: str, min_rows: int = 3) -> str:
    """Rewrite runs of typographic table rows in ``markdown`` as GFM tables.

    Args:
        markdown: Converter output to post-process.
        min_rows: Minimum consecutive, same-width rows for a run to convert.

    Returns:
        ``markdown`` with qualifying runs rewritten; everything else verbatim.
    """
    out: List[str] = []
    run: List[Tuple[str, List[str], str]] = []  # (label, values, original line)

    def flush() -> None:
        nonlocal run
        widths = {len(values) for _, values, _ in run}
        if len(run) >= min_rows and len(widths) == 1:
            ncols = widths.pop()
            out.append("")
            # GFM needs a header row; an empty one keeps invented labels out
            # of the indexed text (they would otherwise be embedded as content).
            out.append("|" + "   |" * (ncols + 1))
            out.append("|" + " --- |" * (ncols + 1))
            for label, values, _ in run:
                # Only the label can carry a '|' (values are numeric tokens);
                # unescaped it would add a cell and mis-column the row.
                cells = [label.replace("|", "\\|")] + values
                out.append("| " + " | ".join(cells) + " |")
            out.append("")
        else:
            out.extend(original for _, _, original in run)
        run = []

    for line in markdown.splitlines():
        parsed = _parse_row(line.strip()) if line.strip() else None
        if parsed:
            run.append((*parsed, line))
        else:
            if run:
                flush()
            out.append(line)
    if run:
        flush()
    return "\n".join(out)
