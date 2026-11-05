"""Tests for ``docsgpt.parser.document_lines``: documents to numbered-line text.

Real DOCX/XLSX/PDF bytes are built in memory (python-docx, openpyxl,
reportlab) so each format's own reader runs; nothing is mocked except the
configured-parser fallback.
"""

from __future__ import annotations

import io

import pytest

from docsgpt.parser import document_lines
from docsgpt.parser.document_lines import extract_document_lines, number_lines


def _docx_bytes() -> bytes:
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("Supply contract")
    doc.add_paragraph("")
    doc.add_paragraph("3.2. Delivery time — no more than 30 days")
    table = doc.add_table(rows=3, cols=3)
    for row, values in zip(table.rows, (("Item", "Qty", "Price"), ("Bolt", "10", "2.50"), ("Nut", "", "0.20"))):
        for cell, value in zip(row.cells, values):
            cell.text = value
    doc.add_paragraph("Signed by both parties")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _xlsx_bytes() -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws["B2"] = "Item"
    ws["C2"] = "Qty"
    ws["B3"] = "Bolt"
    ws["C3"] = 10.0
    ws["C5"] = 3
    other = wb.create_sheet("Price list")
    other["A1"] = "Total"
    other["B1"] = 12.5
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pdf_bytes() -> bytes:
    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(72, 750, "First page heading")
    pdf.drawString(72, 730, "First page body")
    pdf.showPage()
    pdf.drawString(72, 750, "Second page text")
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


@pytest.mark.unit
def test_docx_keeps_paragraph_and_table_order_with_rows_as_lines():
    out = extract_document_lines(_docx_bytes(), "contract.docx")

    assert "error" not in out
    assert out["lines"] == [
        "Supply contract",
        "3.2. Delivery time — no more than 30 days",
        "Item | Qty | Price",
        "Bolt | 10 | 2.50",
        "Nut |  | 0.20",
        "Signed by both parties",
    ]
    assert out["tables"] == [{"first_line": 3, "last_line": 5, "header": ["Item", "Qty", "Price"]}]


@pytest.mark.unit
def test_xlsx_rows_carry_sheet_and_cell_markers():
    out = extract_document_lines(_xlsx_bytes(), "book.xlsx")

    assert "error" not in out
    assert out["lines"] == [
        "(Sheet1!B2) Item | Qty",
        "(Sheet1!B3) Bolt | 10",
        "(Sheet1!B5)  | 3",
        "('Price list'!A1) Total | 12.5",
    ]
    assert out["tables"] == [
        {"first_line": 1, "last_line": 3, "header": ["Item", "Qty"]},
        {"first_line": 4, "last_line": 4, "header": ["Total", "12.5"]},
    ]


@pytest.mark.unit
def test_pdf_lines_carry_page_markers():
    out = extract_document_lines(_pdf_bytes(), "report.pdf")

    assert "error" not in out
    assert out["lines"] == [
        "(p.1) First page heading",
        "(p.1) First page body",
        "(p.2) Second page text",
    ]
    assert out["tables"] == []


@pytest.mark.unit
def test_scanned_pdf_falls_back_to_the_configured_parser(monkeypatch):
    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.showPage()
    pdf.save()
    calls = []

    def _fake_parse(data, safe_name, suffix):
        calls.append(suffix)
        return "OCR line one\fOCR page two"

    monkeypatch.setattr(document_lines, "_parse_with_configured_parser", _fake_parse)

    out = extract_document_lines(buf.getvalue(), "scan.pdf")

    assert calls == [".pdf"]
    assert out["lines"] == ["(p.1) OCR line one", "(p.2) OCR page two"]


@pytest.mark.unit
def test_plain_text_drops_blank_lines():
    out = extract_document_lines("first\n\n  \nsecond  \r\nthird".encode(), "notes.txt")

    assert out == {"lines": ["first", "second", "third"], "tables": []}


@pytest.mark.unit
def test_text_mime_without_a_known_extension_reads_as_text():
    out = extract_document_lines(b"a\nb", "attachment", mime_type="text/plain")

    assert out["lines"] == ["a", "b"]


@pytest.mark.unit
def test_csv_rows_become_table_lines():
    out = extract_document_lines(b'Item,Qty\n"Bolt, steel",10\n', "items.csv")

    assert out["lines"] == ["Item | Qty", "Bolt, steel | 10"]
    assert out["tables"] == [{"first_line": 1, "last_line": 2, "header": ["Item", "Qty"]}]


@pytest.mark.unit
def test_markdown_tables_from_the_fallback_parser_become_rows(monkeypatch):
    markdown = "# Deck\n\n| Item | Qty |\n|---|---:|\n| Bolt | 10 |\n\nClosing"
    monkeypatch.setattr(document_lines, "_parse_with_configured_parser", lambda data, name, suffix: markdown)

    out = extract_document_lines(b"PK fake", "slides.pptx")

    assert out["lines"] == ["# Deck", "Item | Qty", "Bolt | 10", "Closing"]
    assert out["tables"] == [{"first_line": 2, "last_line": 3, "header": ["Item", "Qty"]}]


@pytest.mark.unit
def test_unsupported_type_is_an_error():
    out = extract_document_lines(b"\x00\x01", "blob.exe")

    assert "unsupported file type" in out["error"]


@pytest.mark.unit
def test_oversized_input_is_an_error(monkeypatch):
    monkeypatch.setattr(document_lines, "_max_input_bytes", lambda: 4)

    out = extract_document_lines(b"0123456789", "notes.txt")

    assert "too large" in out["error"]


@pytest.mark.unit
def test_broken_docx_is_an_error_not_an_exception():
    out = extract_document_lines(b"not a zip", "broken.docx")

    assert out["error"].startswith("could not read")


@pytest.mark.unit
def test_number_lines_prefixes_document_and_line_numbers():
    assert number_lines(3, ["a", "(p.2) b"]) == "[D3:L1] a\n[D3:L2] (p.2) b"


@pytest.mark.unit
def test_xlsx_ignores_a_forged_sheet_dimension(monkeypatch):
    openpyxl = pytest.importorskip("openpyxl")
    import re
    import zipfile

    wb = openpyxl.Workbook()
    wb.active["A1"] = "only"
    buf = io.BytesIO()
    wb.save(buf)
    src = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w") as out:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(rb'<dimension ref="[^"]*"/>', b'<dimension ref="A1:XFD1048576"/>', data)
            out.writestr(item, data)

    converted = []
    real_cell_text = document_lines._cell_text
    monkeypatch.setattr(document_lines, "_cell_text", lambda value: converted.append(value) or real_cell_text(value))

    result = extract_document_lines(out_buf.getvalue(), "forged.xlsx")

    assert result["lines"] == ["(Sheet!A1) only"]
    # Rows are sized from their own cells, not padded to the declared 16,384 columns.
    assert len(converted) == 1
