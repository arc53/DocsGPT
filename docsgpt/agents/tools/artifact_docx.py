"""The ``document`` (.docx) artifact renderer: python-docx driven by the spec as data.

``artifact_generator`` sends this module's source to the sandbox and calls
``render_docx_spec`` there, so the module imports only the standard library at
the top and python-docx inside functions. The API process imports it only in
tests.

A spec has two shapes, and may carry both:

* ``sections`` (the original shape): ``[{"heading", "paragraphs": [str]}]``.
  It renders exactly as it always did: a level-1 heading per section and one
  plain paragraph per string.
* ``blocks``: a flat list of typed blocks, rendered after any sections:
  ``heading`` (levels 1-6), ``paragraph`` (optional Word style and alignment),
  ``list`` (bulleted, or numbered 1., 1.1., 1.1.1. when nested), ``table``
  (header row, optional relative column widths), ``quote``, ``code`` and
  ``page_break``.

Text comes as ``text`` (literal, never parsed) or as ``runs``: a list of plain
strings and ``{"text", "bold", "italic", "underline", "strike", "code",
"link"}`` objects. Runs keep the spec data the schema can check: there is no
markup to parse, so a ``*`` or ``_`` in contract text stays literal.

Footnotes are not supported: python-docx has no API for them, and adding one
means writing the footnotes part, its relationship, content type and separator
notes by hand.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, Optional

# Word paragraph alignments by spec name.
ALIGNMENTS = {"left": "LEFT", "center": "CENTER", "right": "RIGHT", "justify": "JUSTIFY"}
# Hyperlink targets the renderer writes; anything else is drawn as plain text.
LINK_SCHEMES = ("http://", "https://", "mailto:")
# Deepest list level Word numbers (ilvl 0-8).
MAX_LIST_LEVEL = 8
MAX_HEADING_LEVEL = 6
# Bullet glyph per nesting level, repeating.
BULLETS = ("•", "◦", "▪")
CODE_FONT = "Courier New"
LINK_COLOR = "0563C1"
HEADER_FILL = "D9D9D9"

# Characters XML 1.0 does not allow; python-docx refuses text that has them.
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def clean_text(value: Any) -> str:
    """The value as text Word can store: ``None`` is empty, control characters are dropped."""
    if value is None:
        return ""
    return _INVALID_XML.sub("", str(value))


def render_docx_spec(spec_path: str, out_path: str) -> None:
    """Render the spec at ``spec_path`` to a .docx at ``out_path``.

    Args:
        spec_path: A JSON file holding the validated spec.
        out_path: Where the document is written.
    """
    with open(spec_path, encoding="utf-8") as handle:
        spec = json.load(handle)
    build_document(spec).save(out_path)


def build_document(spec: Dict[str, Any]) -> Any:
    """Build the python-docx ``Document`` for a spec.

    Args:
        spec: The validated spec.

    Returns:
        The document, not yet saved.
    """
    from docx import Document

    doc = Document()
    title = spec.get("title")
    if title:
        doc.add_heading(clean_text(title), level=0)
    for section in spec.get("sections") or []:
        heading = section.get("heading")
        if heading:
            doc.add_heading(clean_text(heading), level=1)
        for paragraph in section.get("paragraphs") or []:
            doc.add_paragraph(clean_text(paragraph))
    renderer = _Renderer(doc)
    for block in spec.get("blocks") or []:
        if isinstance(block, dict):
            renderer.block(block)
    return doc


class _Renderer:
    """Adds spec blocks to one document, keeping its list numbering definitions."""

    def __init__(self, doc: Any) -> None:
        self.doc = doc
        self._abstract_ids: Dict[str, int] = {}

    # ---- blocks ----

    def block(self, block: Dict[str, Any]) -> None:
        """Add one block; an unknown type is skipped (the schema already rejects it)."""
        handler = getattr(self, "_" + str(block.get("type") or ""), None)
        if callable(handler) and block.get("type") in _BLOCK_TYPES:
            handler(block)

    def _heading(self, block: Dict[str, Any]) -> None:
        level = _int(block.get("level"), 1)
        paragraph = self.doc.add_heading("", level=min(max(level, 1), MAX_HEADING_LEVEL))
        self._fill(paragraph, block)
        self._align(paragraph, block.get("align"))

    def _paragraph(self, block: Dict[str, Any]) -> None:
        paragraph = self.doc.add_paragraph(style=self._style(block.get("style"), "PARAGRAPH"))
        self._fill(paragraph, block)
        self._align(paragraph, block.get("align"))

    def _quote(self, block: Dict[str, Any]) -> None:
        style = self._style(block.get("style") or "Quote", "PARAGRAPH")
        paragraph = self.doc.add_paragraph(style=style)
        self._fill(paragraph, block, italic=style is None)
        self._align(paragraph, block.get("align"))

    def _code(self, block: Dict[str, Any]) -> None:
        from docx.shared import Pt

        paragraph = self.doc.add_paragraph(style=self._style("No Spacing", "PARAGRAPH"))
        run = paragraph.add_run(clean_text(block.get("text")))
        run.font.name = CODE_FONT
        run.font.size = Pt(9)

    def _page_break(self, block: Dict[str, Any]) -> None:
        self.doc.add_page_break()

    def _list(self, block: Dict[str, Any]) -> None:
        ordered = bool(block.get("ordered"))
        num_id = self._new_num("decimal" if ordered else "bullet", _int(block.get("start"), 1))
        self._items(block.get("items") or [], num_id, 0)

    def _items(self, items: Iterable[Any], num_id: int, level: int) -> None:
        style = self._style("List Paragraph", "PARAGRAPH")
        for item in items:
            entry = item if isinstance(item, dict) else {"text": item}
            paragraph = self.doc.add_paragraph(style=style)
            num_pr = paragraph._p.get_or_add_pPr().get_or_add_numPr()
            num_pr.get_or_add_ilvl().val = min(level, MAX_LIST_LEVEL)
            num_pr.get_or_add_numId().val = num_id
            self._fill(paragraph, entry)
            children = entry.get("items")
            if isinstance(children, list) and children:
                self._items(children, num_id, level + 1)

    def _table(self, block: Dict[str, Any]) -> None:
        headers = block.get("headers") if isinstance(block.get("headers"), list) else []
        rows = [r for r in block.get("rows") or [] if isinstance(r, list)]
        columns = max([len(headers)] + [len(r) for r in rows])
        if columns == 0:
            return
        table = self.doc.add_table(rows=0, cols=columns)
        style = self._style(block.get("style") or "Table Grid", "TABLE")
        if style is not None:
            table.style = style
        if headers:
            cells = table.add_row().cells
            _repeat_header_row(table.rows[-1])
            for index in range(columns):
                cell_value = headers[index] if index < len(headers) else ""
                self._cell(cells[index], cell_value, header=True)
        for row in rows:
            cells = table.add_row().cells
            for index in range(columns):
                self._cell(cells[index], row[index] if index < len(row) else "")
        self._widths(table, block.get("widths"), columns)

    # ---- pieces ----

    def _cell(self, cell: Any, value: Any, header: bool = False) -> None:
        entry = value if isinstance(value, dict) else {"text": value}
        paragraph = cell.paragraphs[0]
        self._fill(paragraph, entry, bold=header)
        self._align(paragraph, entry.get("align"))
        if header:
            _shade(cell, HEADER_FILL)

    def _widths(self, table: Any, widths: Any, columns: int) -> None:
        """Size the columns in proportion to ``widths`` across the page's text width."""
        if not isinstance(widths, list) or len(widths) != columns:
            return
        try:
            weights = [float(w) for w in widths]
        except (TypeError, ValueError):
            return
        if any(w <= 0 for w in weights):
            return
        section = self.doc.sections[-1]
        usable = section.page_width - section.left_margin - section.right_margin
        total = sum(weights)
        table.autofit = False
        for index, weight in enumerate(weights):
            width = int(usable * weight / total)
            for cell in table.columns[index].cells:
                cell.width = width

    def _fill(self, paragraph: Any, entry: Dict[str, Any], bold: bool = False, italic: bool = False) -> None:
        """Write ``runs`` (or else ``text``) into ``paragraph``; ``bold``/``italic`` apply to every run."""
        runs = entry.get("runs")
        if not isinstance(runs, list):
            runs = [clean_text(entry.get("text"))]
        for item in runs:
            fmt = item if isinstance(item, dict) else {"text": item}
            text = clean_text(fmt.get("text"))
            if not text:
                continue
            link = fmt.get("link")
            if isinstance(link, str) and link.lower().startswith(LINK_SCHEMES):
                run = _hyperlink(paragraph, link, text)
            else:
                run = paragraph.add_run(text)
            if fmt.get("bold") or bold:
                run.bold = True
            if fmt.get("italic") or italic:
                run.italic = True
            if fmt.get("underline"):
                run.underline = True
            if fmt.get("strike"):
                run.font.strike = True
            if fmt.get("code"):
                run.font.name = CODE_FONT

    def _align(self, paragraph: Any, align: Any) -> None:
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        name = ALIGNMENTS.get(str(align or "").lower())
        if name:
            paragraph.alignment = getattr(WD_ALIGN_PARAGRAPH, name)

    def _style(self, name: Any, kind: str) -> Optional[Any]:
        """The document style called ``name`` (any case) of ``kind``, else None (Word's default)."""
        from docx.enum.style import WD_STYLE_TYPE

        if not isinstance(name, str) or not name.strip():
            return None
        wanted = name.strip().lower()
        style_type = getattr(WD_STYLE_TYPE, kind)
        for style in self.doc.styles:
            if style.type == style_type and str(style.name or "").lower() == wanted:
                return style
        return None

    # ---- numbering ----

    def _new_num(self, kind: str, start: int) -> int:
        """A fresh ``w:num`` over the shared definition for ``kind``, so each list restarts its count."""
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls

        numbering = self.doc.part.numbering_part.element
        abstract_id = self._abstract_ids.get(kind)
        if abstract_id is None:
            abstract_id = self._add_abstract(numbering, kind)
            self._abstract_ids[kind] = abstract_id
        num = numbering.add_num(abstract_id)
        if start != 1:
            num.append(
                parse_xml(
                    f'<w:lvlOverride {nsdecls("w")} w:ilvl="0"><w:startOverride w:val="{max(start, 0)}"/>'
                    "</w:lvlOverride>"
                )
            )
        return int(num.numId)

    @staticmethod
    def _add_abstract(numbering: Any, kind: str) -> int:
        """Add the abstract numbering for ``kind`` (``decimal`` outline or ``bullet``); return its id."""
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls, qn

        existing = [int(a.get(qn("w:abstractNumId"))) for a in numbering.findall(qn("w:abstractNum"))]
        abstract_id = max(existing, default=-1) + 1
        levels = "".join(_level_xml(kind, level) for level in range(MAX_LIST_LEVEL + 1))
        multi = "multilevel" if kind == "decimal" else "hybridMultilevel"
        abstract = parse_xml(
            f'<w:abstractNum {nsdecls("w")} w:abstractNumId="{abstract_id}">'
            f'<w:multiLevelType w:val="{multi}"/>{levels}</w:abstractNum>'
        )
        # The schema wants every abstractNum ahead of the first num.
        first_num = numbering.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(abstract)
        else:
            numbering.append(abstract)
        return abstract_id


_BLOCK_TYPES = frozenset({"heading", "paragraph", "list", "table", "quote", "code", "page_break"})


def _level_xml(kind: str, level: int) -> str:
    """One ``w:lvl``: 1., 1.1., 1.1.1. for ``decimal``; a bullet glyph for ``bullet``."""
    if kind == "decimal":
        text = "".join(f"%{i + 1}." for i in range(level + 1))
        hanging = 360 + 180 * level
        fmt = "decimal"
        font = ""
    else:
        text = BULLETS[level % len(BULLETS)]
        hanging = 360
        fmt = "bullet"
        font = '<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:hint="default"/></w:rPr>'
    left = 720 * (level + 1)
    return (
        f'<w:lvl w:ilvl="{level}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/>'
        f'<w:lvlText w:val="{text}"/><w:lvlJc w:val="left"/>'
        f'<w:pPr><w:ind w:left="{left}" w:hanging="{min(hanging, left)}"/></w:pPr>{font}</w:lvl>'
    )


def _hyperlink(paragraph: Any, url: str, text: str) -> Any:
    """Append an external hyperlink holding one run of ``text``; return that run for formatting."""
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import RGBColor

    rel_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), rel_id)
    run = paragraph.add_run(text)
    run.font.color.rgb = RGBColor.from_string(LINK_COLOR)
    run.underline = True
    # add_run put the run in the paragraph; moving it into the hyperlink keeps its formatting.
    hyperlink.append(run._r)
    paragraph._p.append(hyperlink)
    return run


def _repeat_header_row(row: Any) -> None:
    """Mark a table row as the header Word repeats on every page."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tr_pr = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)


def _shade(cell: Any, fill: str) -> None:
    """Give a table cell a solid background."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shading)


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
