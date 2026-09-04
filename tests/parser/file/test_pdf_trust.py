"""Tests for the PDF trust checks behind ``PDF_TRUST_CHECK``.

The checks target the two classes where anydoc drops text *silently*:
composite (Type0) fonts without a ToUnicode map, and CJK-declaring PDFs
whose extracted text carries almost no CJK. The scanner is byte-level and
regex-based, so the synthetic fixtures below are minimal PDF fragments, not
well-formed files; the one real fixture is the corpus document that loses
its whole Chinese column in anydoc with no error.
"""
import zlib
from pathlib import Path

from application.parser.file.pdf_trust import (
    check_pdf_fonts,
    verify_extraction,
    verify_pdf_file,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _obj(body: bytes) -> bytes:
    return b"1 0 obj" + body + b"endobj\n"


def _stream(payload: bytes) -> bytes:
    return b"2 0 obj<</Filter/FlateDecode>>stream\n" + zlib.compress(payload) + b"\nendstream endobj\n"


TYPE0_WITH_TOUNICODE = _obj(
    b"<</Type/Font/Subtype/Type0/BaseFont/AAAAAA+Simple/ToUnicode 9 0 R>>"
)
TYPE0_BARE = _obj(b"<</Type/Font/Subtype/Type0/BaseFont/AAAAAA+Bare>>")
SIMPLE_FONT = _obj(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
GB1_ORDERING = _obj(b"<</Registry(Adobe)/Ordering(GB1)/Supplement 5>>")


class TestCheckPdfFonts:
    def test_type0_with_tounicode_not_flagged(self):
        result = check_pdf_fonts(TYPE0_WITH_TOUNICODE)
        assert result["type0"] == 1
        assert result["type0_no_tounicode"] == 0
        assert not result["flagged"]

    def test_type0_without_tounicode_flagged(self):
        result = check_pdf_fonts(TYPE0_BARE)
        assert result["type0_no_tounicode"] == 1
        assert result["flagged"]

    def test_simple_font_not_flagged(self):
        result = check_pdf_fonts(SIMPLE_FONT)
        assert result["type0"] == 0
        assert result["has_fonts"]
        assert not result["flagged"]

    def test_no_fonts_flagged(self):
        result = check_pdf_fonts(_obj(b"<</Type/Page>>"))
        assert not result["has_fonts"]
        assert result["flagged"]

    def test_type0_inside_object_stream_is_seen(self):
        """Object streams hold dicts with no obj markers; the scan must decompress them."""
        data = _stream(b"<</Type/Font/Subtype/Type0/BaseFont/BBBBBB+Packed>>")
        result = check_pdf_fonts(data)
        assert result["type0"] == 1
        assert result["type0_no_tounicode"] == 1
        assert result["flagged"]

    def test_font_inside_object_stream_counts_as_has_fonts(self):
        """A fully-compressed PDF with only simple fonts must not false-positive."""
        data = _stream(b"<</Type/Font/Subtype/TrueType/BaseFont/Arial>>")
        result = check_pdf_fonts(data)
        assert result["has_fonts"]
        assert not result["flagged"]

    def test_cjk_ordering_detected_in_stream(self):
        data = _stream(b"<</Registry(Adobe)/Ordering(CNS1)/Supplement 4>>") + SIMPLE_FONT
        assert check_pdf_fonts(data)["expects_cjk"]

    def test_cjk_font_names_alone_do_not_set_expectation(self):
        """Regression for the Berkshire false positive: Word-exported Latin PDFs
        embed MS-Gothic subsets for stray full-width characters, and substring
        matching also hits FranklinGothic — neither means CJK *content*, and a
        false expectation reroutes a 150-page English report to the heavy
        engine. Only CIDSystemInfo /Ordering may set the expectation."""
        data = _obj(
            b"<</Type/Font/Subtype/TrueType/BaseFont/AKBHWD+MS-Gothic>>"
        ) + _obj(b"<</Type/Font/Subtype/TrueType/BaseFont/KMBGKH+FranklinGothic-Roman>>")
        result = check_pdf_fonts(data)
        assert not result["expects_cjk"]
        assert not result["flagged"]


class TestVerifyExtraction:
    def test_clean_pdf_and_output(self):
        assert verify_extraction(SIMPLE_FONT, "Plain English text.") == []

    def test_bare_type0_reported(self):
        problems = verify_extraction(TYPE0_BARE + SIMPLE_FONT, "some text")
        assert len(problems) == 1
        assert "ToUnicode" in problems[0]

    def test_cjk_expected_but_missing(self):
        problems = verify_extraction(GB1_ORDERING + SIMPLE_FONT, "English only output")
        assert len(problems) == 1
        assert "CJK" in problems[0]

    def test_cjk_expected_and_present(self):
        text = "标题：本协议由双方共同签署生效" # 14 CJK chars
        assert verify_extraction(GB1_ORDERING + SIMPLE_FONT, text) == []

    def test_both_problems_reported(self):
        problems = verify_extraction(TYPE0_BARE + GB1_ORDERING, "english")
        assert len(problems) == 2


class TestRealFixture:
    """The corpus PDF where anydoc silently drops the entire Chinese column."""

    def test_cid_font_nda_is_flagged(self):
        data = (FIXTURES / "nda_en_zh_cid_font.pdf").read_bytes()
        result = check_pdf_fonts(data)
        assert result["type0_no_tounicode"] >= 1
        assert result["expects_cjk"]
        assert result["flagged"]

    def test_cjkless_extraction_reports_both(self):
        data = (FIXTURES / "nda_en_zh_cid_font.pdf").read_bytes()
        problems = verify_extraction(data, "MUTUAL NON-DISCLOSURE AGREEMENT ...")
        assert any("ToUnicode" in p for p in problems)
        assert any("CJK" in p for p in problems)


def test_flate_bomb_streams_are_capped():
    """Flate reaches ~1000:1, so per-stream inflation must be capped — an
    uncapped decompress of a crafted PDF would OOM the ingest worker."""
    from application.parser.file.pdf_trust import _decompressed_streams, _STREAM_INFLATE_CAP

    bomb = _stream(b"\0" * (_STREAM_INFLATE_CAP * 4))
    chunks = list(_decompressed_streams(bomb))
    assert chunks
    assert all(len(chunk) <= _STREAM_INFLATE_CAP for chunk in chunks)
    # The capped scan still completes and reports sanely alongside real objects.
    assert not check_pdf_fonts(SIMPLE_FONT + bomb)["flagged"]


def test_verify_pdf_file_unreadable_trusts_output(tmp_path):
    assert verify_pdf_file(tmp_path / "missing.pdf", "text") == []


# --- stream scanning is a keyword walk, not a regex -----------------------------


class TestStreamWalk:
    def test_stream_without_eol_before_endstream_is_seen(self):
        body = zlib.compress(b"<</Type/Font/Subtype/Type0/BaseFont/X>>")
        data = b"2 0 obj<</Filter/FlateDecode>>stream\n" + body + b"endstream endobj\n"
        assert check_pdf_fonts(data)["type0"] == 1

    def test_undecodable_stream_does_not_swallow_the_next_one(self):
        """A non-Flate (image) stream before a font stream must not merge the two."""
        image = b"3 0 obj<</Filter/DCTDecode>>stream\n\xff\xd8 not zlib at all\nendstream endobj\n"
        font = _stream(b"<</Type/Font/Subtype/Type0/BaseFont/X/ToUnicode 9 0 R>>")
        result = check_pdf_fonts(image + font)
        assert result["type0"] == 1
        assert result["type0_no_tounicode"] == 0

    def test_crlf_streams_decompress(self):
        body = zlib.compress(b"/Ordering (GB1)")
        data = b"2 0 obj<</Filter/FlateDecode>>stream\r\n" + body + b"\r\nendstream endobj\n"
        assert check_pdf_fonts(data)["expects_cjk"] is True

    def test_large_file_with_many_streams_is_linear(self):
        """1000 undecodable streams: the old regex went quadratic here."""
        import time

        chunk = b"9 0 obj<</Length 30>>stream\n" + b"\x00" * 30 + b"endstream endobj\n"
        data = chunk * 1000 + TYPE0_BARE
        started = time.perf_counter()
        result = check_pdf_fonts(data)
        assert time.perf_counter() - started < 1.0
        assert result["type0_no_tounicode"] == 1


class TestObjectWalk:
    def test_bodies_match_the_regex_reference(self):
        """The forward walk yields exactly what ``\\d+\\s+\\d+\\s+obj(.*?)endobj`` did."""
        import re

        from application.parser.file.pdf_trust import _object_bodies

        reference = re.compile(rb"\d+\s+\d+\s+obj(.*?)endobj", re.DOTALL)
        data = (
            TYPE0_BARE
            + b"7 0 obj no terminator here "  # orphan header: body runs to the next endobj
            + SIMPLE_FONT
            + b"junk 12 0 obj<</A/B>>endobj"
            + _stream(b"x")
            + b"99 0 obj trailing orphan"
        )
        assert list(_object_bodies(data)) == [m.group(1) for m in reference.finditer(data)]

    def test_orphan_headers_are_linear(self):
        """Headers with no ``endobj`` after them: the old regex rescanned to EOF for
        each one (2000 in 1 MB took 13.5 s), pinning an ingest worker per upload."""
        import time

        data = TYPE0_BARE + b"1 0 obj\n" * 20_000 + b"\x00" * 500_000
        started = time.perf_counter()
        result = check_pdf_fonts(data)
        assert time.perf_counter() - started < 1.0
        assert result["type0_no_tounicode"] == 1


# --- the CJK cross-check is confirmed against pdfium's text layer --------------


def _latin_pdf(path: Path) -> Path:
    import pytest

    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path))
    c.drawString(72, 700, "Plain English content, nothing else on the page.")
    c.showPage()
    c.save()
    return path


def test_stray_cjk_ordering_without_cjk_text_is_not_flagged(tmp_path):
    """A Quartz-style export declares Japan1 on one unused font: pdfium sees no
    CJK either, so anydoc dropped nothing and the file must not be rerouted."""
    import pytest

    pytest.importorskip("pypdfium2")
    path = _latin_pdf(tmp_path / "latin.pdf")
    with open(path, "ab") as fh:
        fh.write(b"\n% trailing junk\n" + _obj(b"<</Registry(Adobe)/Ordering(Japan1)/Supplement 6>>"))
    markdown = "Plain English content, nothing else on the page."

    # The byte-level check alone still fires...
    assert any(p.startswith("PDF declares CJK fonts") for p in verify_extraction(path.read_bytes(), markdown))
    # ...and the file-level check withdraws it.
    assert [p for p in verify_pdf_file(path, markdown) if p.startswith("PDF declares CJK fonts")] == []


def test_real_cjk_drop_survives_the_cross_check():
    import pytest

    pytest.importorskip("pypdfium2")
    fixture = FIXTURES / "nda_en_zh_cid_font.pdf"
    problems = verify_pdf_file(fixture, "English only, the Chinese column is gone.")
    assert any(p.startswith("PDF declares CJK fonts") for p in problems)
