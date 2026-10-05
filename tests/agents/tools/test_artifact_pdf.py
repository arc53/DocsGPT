"""The pdf artifact renderer: script detection, font choice, right-to-left layout and real renders.

The renderer runs in the sandbox, so most tests drive its pure functions with a
``FontSet`` whose coverage is declared by hand. Renders use reportlab's bundled
Bitstream Vera as a stand-in for DejaVu Sans (always present) and reportlab's
built-in CJK fonts (no files). ``test_render_with_the_image_fonts`` renders with
the real image fonts when they are installed (the sandbox image, or a Linux box
with fonts-dejavu-core and fonts-noto-core); point ``DOCSGPT_SANDBOX_FONT_ROOT``
at a copy of an image's ``/usr/share/fonts`` to run it elsewhere.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List

import pytest

pytest.importorskip("reportlab")

from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402

from docsgpt.agents.tools import artifact_pdf  # noqa: E402
from docsgpt.agents.tools.artifact_pdf import (  # noqa: E402
    FontSet,
    break_lines,
    cjk_flavor,
    detect_scripts,
    font_runs,
    load_fonts,
    mirror_brackets,
    render_pdf_spec,
    runs_markup,
    script_of,
)
from docsgpt.sandbox import manifest  # noqa: E402

_VERA_DIR = Path(pdfmetrics.__file__).resolve().parents[1] / "fonts"

# One line per script the production PDFs carried (Persian, Cyrillic, Greek,
# symbols) and the ones users write (Hindi, Arabic, Chinese, Japanese).
MULTI_SCRIPT = {
    "latin": "Quarterly report",
    "cyrillic": "Отчёт за квартал",
    "greek": "Τριμηνιαία αναφορά",
    "symbols": "x − y → z ≤ 5 ≥ 1 ≠ ∞ ✓ €",
    "devanagari": "हिन्दी भाषा में स्वागत है",
    "arabic": "مرحبا بالعالم",
    "persian": "گزارش سه ماهه پیشرفت",
    "chinese": "季度报告",
    "japanese": "四半期レポート",
}


def _forget_renderer_fonts() -> None:
    """Drop every font the renderer registered (``ArtifactSans*``) from reportlab's registry."""
    from reportlab.lib import fonts as rl_fonts

    ours = artifact_pdf.BASE_FAMILY.lower()
    for name in [n for n in pdfmetrics._fonts if n.lower().startswith(ours)]:
        del pdfmetrics._fonts[name]
    for face, font in list(pdfmetrics._dynFaceNames.items()):
        if font.fontName.lower().startswith(ours):
            del pdfmetrics._dynFaceNames[face]
    for key, value in list(rl_fonts._tt2ps_map.items()):
        if key[0].startswith(ours) or value.lower().startswith(ours):
            del rl_fonts._tt2ps_map[key]
    for key in [k for k in rl_fonts._ps2tt_map if k.startswith(ours)]:
        del rl_fonts._ps2tt_map[key]


@pytest.fixture(autouse=True)
def _fresh_font_registry():
    """Run each test without the renderer's fonts and restore the registry after.

    reportlab's registry is process-global: another test in the same worker
    (say an artifact_generator render, which finds DejaVu on a Linux runner)
    may already have bound ``ArtifactSans`` to a different file.
    """
    from reportlab.lib import fonts as rl_fonts

    saved = (
        dict(pdfmetrics._fonts),
        dict(pdfmetrics._dynFaceNames),
        dict(rl_fonts._tt2ps_map),
        dict(rl_fonts._ps2tt_map),
    )
    _forget_renderer_fonts()
    yield
    for current, before in zip(
        (pdfmetrics._fonts, pdfmetrics._dynFaceNames, rl_fonts._tt2ps_map, rl_fonts._ps2tt_map), saved
    ):
        current.clear()
        current.update(before)


def _synthetic_fonts() -> FontSet:
    """A FontSet with hand-declared coverage: B is the base, D draws Devanagari, S draws only ≤."""
    fonts = FontSet({"regular": "B", "bold": "BB", "italic": "BI", "bold_italic": "BBI"})
    latin = set(range(0x20, 0x250))
    for name in ("B", "BB", "BI", "BBI"):
        fonts.add_coverage(name, latin.__contains__)
    deva = set(range(0x0900, 0x0980)) | {ord(c) for c in " (),.0123456789"}
    for name in ("D", "DB"):
        fonts.add_coverage(name, deva.__contains__)
    fonts.add_coverage("S", {ord("≤")}.__contains__)
    fonts.scripts["devanagari"] = ("D", "DB")
    fonts.fallbacks.append("S")
    return fonts


def _vera_table() -> List[Dict[str, str]]:
    """A PDF_FONTS-shaped table whose base family is reportlab's bundled Vera."""
    return [{"script": "base", "regular": str(_VERA_DIR / "Vera.ttf"), "bold": str(_VERA_DIR / "VeraBd.ttf")}]


def _pdf_fonts(path: Path) -> List[str]:
    """Return the BaseFont names of every font a PDF's pages use."""
    from pypdf import PdfReader

    names = []
    for page in PdfReader(str(path)).pages:
        for font in page["/Resources"]["/Font"].values():
            names.append(str(font.get_object()["/BaseFont"]).lstrip("/"))
    return names


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def _render(tmp_path: Path, spec: dict, table=(), font_dir=None, monkeypatch=None) -> Path:
    spec_path = tmp_path / "spec.json"
    out_path = tmp_path / "out.pdf"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    if monkeypatch is not None:
        monkeypatch.setattr(artifact_pdf, "matplotlib_font_dir", lambda: font_dir)
    render_pdf_spec(str(spec_path), str(out_path), table)
    return out_path


# -- Script detection ------------------------------------------------------------


@pytest.mark.parametrize(
    "ch,script",
    [
        ("a", None),
        ("é", None),
        ("Ж", None),
        ("λ", None),
        ("Ա", None),
        ("→", None),
        ("٣", "arabic"),
        ("پ", "arabic"),
        ("ﺍ", "arabic"),
        ("ש", "hebrew"),
        ("ह", "devanagari"),
        ("ি", "bengali"),
        ("த", "tamil"),
        ("ก", "thai"),
        ("中", "han"),
        ("𠀀", "han"),
        ("あ", "kana"),
        ("ｱ", "kana"),
        ("한", "hangul"),
        ("।", None),
        ("॥", None),
        ("。", "cjk"),
        ("Ａ", "cjk"),
    ],
)
def test_script_of(ch, script):
    assert script_of(ch) == script


def test_script_ranges_are_sorted_and_do_not_overlap():
    ranges = artifact_pdf._SCRIPT_RANGES
    for (start, end, _), (next_start, _, _) in zip(ranges, ranges[1:]):
        assert start <= end < next_start


def test_every_script_with_a_range_has_a_font_in_the_manifest():
    """CJK aside (reportlab's CID fonts), a script the renderer detects must have a font in the image."""
    detected = {script for _, _, script in artifact_pdf._SCRIPT_RANGES} - artifact_pdf.CJK_SCRIPTS
    listed = {f["script"] for f in manifest.PDF_FONTS} - {"base", "symbols"}
    assert detected == listed
    assert artifact_pdf.SHAPED_SCRIPTS <= listed
    assert artifact_pdf.RTL_SCRIPTS <= listed


def test_detect_scripts_finds_every_script_in_the_spec():
    assert detect_scripts(MULTI_SCRIPT.values()) == {"devanagari", "arabic", "han", "kana"}
    assert detect_scripts(["plain ASCII", ""]) == set()


@pytest.mark.parametrize(
    "scripts,flavor",
    [
        ({"han"}, "zh"),
        ({"han", "kana"}, "ja"),
        ({"kana"}, "ja"),
        ({"hangul"}, "ko"),
        ({"hangul", "cjk"}, "ko"),
        ({"hangul", "han"}, "zh"),
        ({"cjk"}, "zh"),
    ],
)
def test_cjk_flavor(scripts, flavor):
    assert cjk_flavor(scripts) == flavor


def test_cjk_flavors_follow_each_sentence():
    text = "中文：季度报告。日本語：四半期レポート。한국어 보고서."
    flavors = artifact_pdf.cjk_flavors(text)
    by_char = {ch: flavor for ch, flavor in zip(text, flavors)}
    assert by_char["报"] == "zh" and by_char["文"] == "zh"
    assert by_char["四"] == "ja" and by_char["レ"] == "ja" and by_char["語"] == "ja"
    assert by_char["한"] == "ko"
    assert flavors[text.index("：")] == "zh"
    assert flavors[text.index("：", 5)] == "ja"
    assert by_char[" "] is None and by_char["."] is None
    assert artifact_pdf.cjk_flavors("plain") == [None] * 5
    assert artifact_pdf.cjk_flavors("") == []


def test_direction_comes_from_the_first_strong_character():
    assert artifact_pdf.base_direction("123 سلام world") == "R"
    assert artifact_pdf.base_direction("Version 2 (نسخه)") == "L"
    assert artifact_pdf.base_direction("123 ...") == "L"
    assert artifact_pdf.is_rtl("abc שלום")
    assert not artifact_pdf.is_rtl("abc ∞ 中文")


def test_all_text_reads_the_title_and_every_block():
    spec = {"title": "T", "blocks": [{"type": "heading", "text": "H"}, {"type": "paragraph", "text": 5}, "junk"]}
    assert artifact_pdf.all_text(spec) == ["T", "H", "5"]


# -- Font runs ---------------------------------------------------------------------


def test_font_runs_keeps_punctuation_with_the_script_word_it_belongs_to():
    runs = font_runs("Hello हिन्दी (हिन्दी), ok", _synthetic_fonts())
    assert runs == [("B", "Hello "), ("D", "हिन्दी (हिन्दी), "), ("B", "ok")]


def test_font_runs_use_bold_and_italic_faces():
    fonts = _synthetic_fonts()
    assert font_runs("Hi हि", fonts, bold=True) == [("BB", "Hi "), ("DB", "हि")]
    assert font_runs("Hi हि", fonts, bold=True, italic=True) == [("BBI", "Hi "), ("DB", "हि")]
    assert font_runs("Hi", fonts, italic=True) == [("BI", "Hi")]


def test_font_runs_falls_back_to_a_symbol_font_for_what_the_base_lacks():
    assert font_runs("x ≤ y", _synthetic_fonts()) == [("B", "x "), ("S", "≤"), ("B", " y")]


def test_font_runs_drop_invisible_characters_no_font_draws():
    assert font_runs("a​b", _synthetic_fonts()) == [("B", "ab")]


def test_font_runs_keep_a_visible_character_no_font_draws_in_the_base():
    """A glyph nobody has still takes a slot (drawn as missing) rather than vanishing."""
    assert font_runs("a😀b", _synthetic_fonts()) == [("B", "a😀b")]


def test_font_runs_send_a_script_letter_without_a_font_to_the_base():
    assert font_runs("ab ก", _synthetic_fonts()) == [("B", "ab ก")]


def test_font_runs_draw_each_cjk_sentence_in_its_own_font():
    fonts = FontSet()
    fonts.cjk = dict(artifact_pdf.CID_FONTS)
    for name in fonts.cjk.values():
        fonts.add_coverage(name, artifact_pdf._cid_covers)
    runs = font_runs("季度报告。四半期レポート。분기", fonts)
    assert runs == [("STSong-Light", "季度报告。"), ("HeiseiKakuGo-W5", "四半期レポート。"), ("HYGothic-Medium", "분기")]


def test_font_runs_without_a_cid_font_for_the_flavor_use_another():
    fonts = FontSet()
    fonts.cjk = {"ja": "HeiseiKakuGo-W5"}
    fonts.add_coverage("HeiseiKakuGo-W5", artifact_pdf._cid_covers)
    assert font_runs("中文", fonts) == [("HeiseiKakuGo-W5", "中文")]


def test_one_font_per_word():
    assert artifact_pdf._one_font_per_word([("B", "Hello "), ("D", "हिन्दी (हिन्दी), "), ("B", "ok")])
    assert not artifact_pdf._one_font_per_word([("B", "PDF-"), ("D", "फ़ाइल")])
    assert artifact_pdf._one_font_per_word([])


def test_runs_markup_escapes_text_and_tags_other_fonts():
    markup = runs_markup([("B", "a<b & "), ("D", "x>y")], "B")
    assert markup == 'a&lt;b &amp; <font name="D">x&gt;y</font>'


def test_helvetica_base_covers_latin1_only():
    fonts = FontSet()
    assert fonts.face() == "Helvetica" and fonts.face(True, True) == "Helvetica-BoldOblique"
    assert fonts.covers("Helvetica", "é") and fonts.covers("Helvetica", "€")
    assert not fonts.covers("Helvetica", "Ж")
    assert not fonts.covers("Helvetica", "\n")
    assert not fonts.covers("Unknown", "a")


# -- Bidi ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "visual,direction,expected",
    [
        (")test(", "R", "(test)"),
        ("x )a ]b[ c( y", "R", "x (a [b] c) y"),
        ("see (x) now", "L", "see (x) now"),
        ("see (x) now", "R", "see (x) now"),
        ("»مالس«", "R", "«مالس»"),
        ("دروم )۱", "R", "دروم (۱"),
        ("abc )", "R", "abc )"),
        ("abc )", "L", "abc )"),
        (")", "R", "("),
        ("no brackets", "R", "no brackets"),
    ],
)
def test_mirror_brackets(visual, direction, expected):
    assert mirror_brackets(visual, direction) == expected


def test_break_lines_fills_lines_and_splits_long_words():
    assert break_lines("aaa bbb ccc", len, 7) == ["aaa bbb", "ccc"]
    assert break_lines("  aaa \n\t bbb  ", len, 20) == ["aaa bbb"]
    assert break_lines("abcdefghij", len, 4) == ["abcd", "efgh", "ij"]
    assert break_lines("x abcdefghij", len, 4) == ["x", "abcd", "efgh", "ij"]
    assert break_lines("", len, 4) == []


def test_long_unbroken_text_lays_out_in_linear_time():
    """A paragraph of digits or one huge Arabic word must not take quadratic time in the sandbox's 60 s."""
    import time

    fonts = _synthetic_fonts()
    started = time.monotonic()
    runs = font_runs("1234567890-" * 3000 + "हि", fonts)
    lines = break_lines("ب" * 20000, len, 80)
    assert time.monotonic() - started < 5
    assert runs[-1] == ("D", "हि") and "".join(chunk for _, chunk in runs).startswith("1234567890-")
    assert len(lines) == 250 and all(len(line) == 80 for line in lines)


def test_fitting_prefix_counts_the_characters_that_fit():
    assert artifact_pdf._fitting_prefix("abcdef", len, 4) == 4
    assert artifact_pdf._fitting_prefix("abcdef", lambda s: 10.0, 4) == 1
    # Characters that fit one by one fit whole, even if the word measured as one string did not.
    assert artifact_pdf._fitting_prefix("abc", lambda s: 1.0, 5) == 3


def test_reshape_arabic_joins_letters_into_presentation_forms():
    pytest.importorskip("arabic_reshaper")
    shaped = artifact_pdf.reshape_arabic("سلام")
    # Seen initial, lam-alef ligature, meem final: no base Arabic letters left.
    assert shaped == "ﺳﻼﻡ"
    persian = artifact_pdf.reshape_arabic("گزارش")
    assert all(0xFB50 <= ord(c) <= 0xFEFF for c in persian)


def test_reshape_arabic_without_the_library_leaves_text_alone(monkeypatch):
    monkeypatch.setitem(sys.modules, "arabic_reshaper", None)
    assert artifact_pdf.reshape_arabic("سلام") == "سلام"


def test_bidi_display_prefers_python_bidi_and_survives_its_absence(monkeypatch):
    pytest.importorskip("bidi")
    assert artifact_pdf._bidi_display() is not None
    monkeypatch.setitem(sys.modules, "bidi", None)
    monkeypatch.setitem(sys.modules, "bidi.algorithm", None)
    assert artifact_pdf._bidi_display() is None


def _helvetica_rtl_fonts() -> FontSet:
    """Helvetica base plus a registered stand-in "arabic" font (Vera) that claims Arabic coverage."""
    fonts = FontSet()
    artifact_pdf._register_ttf("TestArabic", [str(_VERA_DIR / "Vera.ttf")], fonts, False)
    fonts.add_coverage("TestArabic", lambda code: artifact_pdf.script_of(chr(code)) == "arabic" or code == 0x20)
    fonts.scripts["arabic"] = ("TestArabic", "TestArabic")
    return fonts


def test_rtl_markup_reshapes_reorders_and_reports_the_direction():
    pytest.importorskip("arabic_reshaper")
    pytest.importorskip("bidi")
    markup, direction = artifact_pdf.rtl_markup("سلام دنیا", _helvetica_rtl_fonts(), 10, 400)
    assert direction == "R"
    # Display order: the second word comes first, each word's letters reversed.
    dunya = artifact_pdf.reshape_arabic("دنیا")[::-1]
    salam = artifact_pdf.reshape_arabic("سلام")[::-1]
    assert f"{dunya} {salam}" in markup
    assert markup.startswith('<font name="TestArabic">')


def test_rtl_markup_breaks_lines_before_reordering_them():
    pytest.importorskip("arabic_reshaper")
    pytest.importorskip("bidi")
    words = ["یک", "دو", "سه", "چهار", "پنج", "شش"]
    fonts = _helvetica_rtl_fonts()
    one_word = max(pdfmetrics.stringWidth(artifact_pdf.reshape_arabic(w), "TestArabic", 10) for w in words)
    width = one_word * 2 + pdfmetrics.stringWidth(" ", "TestArabic", 10) + 1
    markup, _ = artifact_pdf.rtl_markup(" ".join(words), fonts, 10, width)
    lines = markup.split("<br/>")
    assert len(lines) == 3
    # The first line holds the first two words, reordered for display.
    first = artifact_pdf.reshape_arabic("دو")[::-1] + " " + artifact_pdf.reshape_arabic("یک")[::-1]
    assert first in lines[0]


def test_rtl_markup_mirrors_brackets_and_keeps_ltr_paragraphs_ltr():
    pytest.importorskip("arabic_reshaper")
    pytest.importorskip("bidi")
    fonts = _helvetica_rtl_fonts()
    markup, direction = artifact_pdf.rtl_markup("سلام (test)", fonts, 10, 400)
    assert direction == "R" and "(test)" in markup
    markup, direction = artifact_pdf.rtl_markup("Version 2 (سلام) released", fonts, 10, 400)
    assert direction == "L"
    assert markup.startswith("Version 2 (")
    assert markup.endswith(") released")


def test_rtl_markup_drops_zwnj_after_joining():
    """ZWNJ stops the join in می‌دهد; once reshaped, Noto would draw it as a visible bar."""
    pytest.importorskip("arabic_reshaper")
    pytest.importorskip("bidi")
    markup, _ = artifact_pdf.rtl_markup("می\u200cدهد \u200f", _helvetica_rtl_fonts(), 10, 400)
    assert "\u200c" not in markup and "\u200f" not in markup
    # The meem before the ZWNJ stays in its non-joining (initial) form.
    assert "\ufee3" in markup


def test_strip_format_characters():
    assert artifact_pdf.strip_format_characters("a\u200cb\u200dc\u200e\u00add") == "abcd"


def test_rtl_markup_without_python_bidi_keeps_logical_order(monkeypatch):
    monkeypatch.setattr(artifact_pdf, "_bidi_display", lambda: None)
    monkeypatch.setattr(artifact_pdf, "reshape_arabic", lambda text: text)
    markup, direction = artifact_pdf.rtl_markup("سلام دنیا", _helvetica_rtl_fonts(), 10, 400)
    assert direction == "R"
    assert "سلام دنیا" in markup


# -- Paragraph styles -------------------------------------------------------------


def _styles(fonts: FontSet):
    return artifact_pdf.build_styles(fonts)


def test_build_styles_point_every_style_at_the_base_family():
    fonts = FontSet({"regular": "R", "bold": "Bd", "italic": "It", "bold_italic": "BdIt"})
    styles = _styles(fonts)
    assert styles["BodyText"][0].fontName == "R"
    assert styles["Title"][0].fontName == "Bd"
    assert styles["Heading1"][0].fontName == "Bd"
    assert styles["Heading3"][0].fontName == "BdIt"
    assert styles["Bullet"][0].fontName == "R"
    assert styles["Heading3"][1:] == (True, True)


def test_paragraph_for_right_aligns_rtl_body_text_but_keeps_a_centered_title():
    pytest.importorskip("bidi")
    fonts = _helvetica_rtl_fonts()
    styles = _styles(fonts)
    body = artifact_pdf.paragraph_for("سلام دنیا", styles["BodyText"][0], fonts, 400, False)
    assert body.style.alignment == TA_RIGHT
    title = artifact_pdf.paragraph_for("سلام دنیا", styles["Title"][0], fonts, 400, True)
    assert title.style.alignment == TA_CENTER
    ltr = artifact_pdf.paragraph_for("Hello (سلام)", styles["BodyText"][0], fonts, 400, False)
    assert ltr.style.alignment == TA_LEFT


def test_paragraph_for_breaks_cjk_text_anywhere():
    fonts = FontSet()
    styles = _styles(fonts)
    paragraph = artifact_pdf.paragraph_for("中文测试", styles["BodyText"][0], fonts, 400, False)
    assert paragraph.style.wordWrap == "CJK"


def test_paragraph_for_shapes_complex_scripts_when_supported(monkeypatch):
    fonts = FontSet()
    fonts.shaping = True
    styles = _styles(fonts)
    paragraph = artifact_pdf.paragraph_for("हिन्दी", styles["BodyText"][0], fonts, 400, False)
    assert getattr(paragraph.style, "shaping", 0) == 1
    fonts.shaping = False
    paragraph = artifact_pdf.paragraph_for("हिन्दी", styles["BodyText"][0], fonts, 400, False)
    assert not getattr(paragraph.style, "shaping", 0)


def test_paragraph_for_does_not_shape_a_word_drawn_in_two_fonts():
    """reportlab shapes a word with its first run's font: a word split across fonts must stay unshaped."""
    fonts = FontSet()
    artifact_pdf._register_ttf("TestDeva", [str(_VERA_DIR / "VeraIt.ttf")], fonts, False)
    fonts.add_coverage("TestDeva", lambda code: 0x0900 <= code < 0x0980 or code in (0x200C, 0x200D))
    fonts.scripts["devanagari"] = ("TestDeva", "TestDeva")
    fonts.shaping = True
    styles = _styles(fonts)
    mixed = artifact_pdf.paragraph_for("PDF-हिन्दी", styles["BodyText"][0], fonts, 400, False)
    assert not getattr(mixed.style, "shaping", 0)
    alone = artifact_pdf.paragraph_for("PDF हिन्दी\u200d", styles["BodyText"][0], fonts, 400, False)
    assert getattr(alone.style, "shaping", 0) == 1
    # HarfBuzz reads ZWJ; the unshaped fallback drops it.
    assert "\u200d" in alone.text
    assert "\u200d" not in mixed.text


def test_paragraph_for_draws_unshaped_when_shaping_fails(monkeypatch):
    from reportlab.platypus import Paragraph

    original = Paragraph.wrap

    def wrap(self, *args, **kwargs):
        if getattr(self.style, "shaping", 0):
            raise RuntimeError("shaping broke")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Paragraph, "wrap", wrap)
    fonts = FontSet()
    fonts.shaping = True
    paragraph = artifact_pdf.paragraph_for("हिन्दी", _styles(fonts)["BodyText"][0], fonts, 400, False)
    assert not getattr(paragraph.style, "shaping", 0)


def test_shaping_supported_needs_uharfbuzz(monkeypatch):
    from reportlab.pdfbase import ttfonts

    monkeypatch.setattr(ttfonts, "uharfbuzz", None, raising=False)
    assert artifact_pdf.shaping_supported() is False
    monkeypatch.setattr(ttfonts, "uharfbuzz", object(), raising=False)
    assert artifact_pdf.shaping_supported() is hasattr(ttfonts, "shapeFragWord")


def test_shaping_supported_without_reportlab(monkeypatch):
    monkeypatch.setitem(sys.modules, "reportlab.pdfbase", None)
    assert artifact_pdf.shaping_supported() is False


# -- Font loading ---------------------------------------------------------------------


def test_load_fonts_without_any_font_file_falls_back_to_helvetica(tmp_path):
    fonts = load_fonts([{"script": "base", "regular": str(tmp_path / "nope.ttf"), "bold": ""}], set(), str(tmp_path))
    assert fonts.base == artifact_pdf._HELVETICA
    assert fonts.scripts == {} and fonts.fallbacks == []


def test_load_fonts_registers_the_base_family_and_its_markup_mapping(tmp_path):
    from reportlab.lib.fonts import tt2ps

    shutil.copy(_VERA_DIR / "VeraIt.ttf", tmp_path / "DejaVuSans-Oblique.ttf")
    fonts = load_fonts(_vera_table(), set(), str(tmp_path))
    assert fonts.base == {
        "regular": "ArtifactSans",
        "bold": "ArtifactSans-Bold",
        "italic": "ArtifactSans-Italic",
        # No bold oblique anywhere: bold stands in.
        "bold_italic": "ArtifactSans-Bold",
    }
    assert tt2ps("ArtifactSans", 1, 0) == "ArtifactSans-Bold"
    assert tt2ps("ArtifactSans", 0, 1) == "ArtifactSans-Italic"
    assert fonts.covers("ArtifactSans", "a") and not fonts.covers("ArtifactSans", "ह")


def test_load_fonts_takes_a_base_face_from_the_fallback_dir(tmp_path):
    """The image lacks a face: matplotlib's bundled DejaVu (here a stand-in dir) supplies it."""
    shutil.copy(_VERA_DIR / "Vera.ttf", tmp_path / "DejaVuSans.ttf")
    shutil.copy(_VERA_DIR / "VeraBd.ttf", tmp_path / "DejaVuSans-Bold.ttf")
    table = [{"script": "base", "regular": "/missing/DejaVuSans.ttf", "bold": "/missing/DejaVuSans-Bold.ttf"}]
    fonts = load_fonts(table, set(), str(tmp_path))
    assert fonts.base["regular"] == "ArtifactSans" and fonts.base["bold"] == "ArtifactSans-Bold"
    assert fonts.base["italic"] == "ArtifactSans"


def test_load_fonts_skips_a_file_reportlab_cannot_load(tmp_path):
    image, fallback, empty = (tmp_path / name for name in ("image", "fallback", "empty"))
    for directory in (image, fallback, empty):
        directory.mkdir()
    broken = image / "DejaVuSans.ttf"
    broken.write_bytes(b"not a font")
    table = [{"script": "base", "regular": str(broken), "bold": ""}]
    shutil.copy(_VERA_DIR / "Vera.ttf", fallback / "DejaVuSans.ttf")
    assert load_fonts(table, set(), str(fallback)).base["regular"] == "ArtifactSans"
    assert load_fonts(table, set(), str(empty)).base == artifact_pdf._HELVETICA


def test_a_name_bound_to_another_file_gets_a_fresh_one(tmp_path):
    """The sandbox kernel outlives a render, and reportlab keeps the first file registered under a name."""
    first = load_fonts(_vera_table(), set(), str(tmp_path))
    again = load_fonts(_vera_table(), set(), str(tmp_path))
    assert again.base == first.base
    other = tmp_path / "DejaVuSans.ttf"
    shutil.copy(_VERA_DIR / "VeraBI.ttf", other)
    moved = load_fonts([{"script": "base", "regular": str(other), "bold": ""}], set(), str(tmp_path))
    assert moved.base["regular"] == "ArtifactSans-2"
    assert pdfmetrics.getFont("ArtifactSans-2").face.filename == str(other)


def test_load_fonts_loads_only_the_scripts_the_document_uses(tmp_path):
    table = _vera_table() + [
        {"script": "arabic", "regular": str(_VERA_DIR / "Vera.ttf"), "bold": str(_VERA_DIR / "VeraBd.ttf")},
        {"script": "thai", "regular": str(_VERA_DIR / "Vera.ttf"), "bold": ""},
        {"script": "hebrew", "regular": str(tmp_path / "missing.ttf"), "bold": ""},
        {"script": "symbols", "regular": str(_VERA_DIR / "VeraIt.ttf"), "bold": ""},
    ]
    fonts = load_fonts(table, {"arabic", "thai", "hebrew"}, str(tmp_path))
    assert fonts.scripts["arabic"] == ("ArtifactSans-arabic", "ArtifactSans-arabic-Bold")
    # No bold file: the regular face stands in.
    assert fonts.scripts["thai"] == ("ArtifactSans-thai", "ArtifactSans-thai")
    assert "hebrew" not in fonts.scripts
    assert fonts.fallbacks == ["ArtifactSans-symbols0"]
    assert "devanagari" not in load_fonts(table, {"arabic"}, str(tmp_path)).scripts


def test_load_fonts_marks_only_complex_script_fonts_shapable(tmp_path, monkeypatch):
    from reportlab.pdfbase import ttfonts

    monkeypatch.setattr(artifact_pdf, "shaping_supported", lambda: True)
    # Distinct faces: reportlab hands a second registration of a face the first font object.
    table = _vera_table() + [
        {"script": "devanagari", "regular": str(_VERA_DIR / "VeraIt.ttf"), "bold": ""},
        {"script": "arabic", "regular": str(_VERA_DIR / "VeraBI.ttf"), "bold": ""},
    ]
    fonts = load_fonts(table, {"devanagari", "arabic"}, str(tmp_path))
    assert fonts.shaping
    # reportlab turns shapable off by itself when uharfbuzz is missing.
    harfbuzz = bool(getattr(ttfonts, "uharfbuzz", None))
    assert pdfmetrics.getFont("ArtifactSans-devanagari").shapable is harfbuzz
    assert pdfmetrics.getFont("ArtifactSans").shapable is harfbuzz
    # Right-to-left text is reordered before reportlab sees it; HarfBuzz must not reorder it again.
    assert pdfmetrics.getFont("ArtifactSans-arabic").shapable is False


@pytest.mark.parametrize("scripts", [{"han"}, {"kana"}, {"hangul"}, {"cjk"}])
def test_load_fonts_registers_reportlab_cid_fonts_for_cjk(tmp_path, scripts):
    fonts = load_fonts([], scripts, str(tmp_path))
    assert fonts.cjk == artifact_pdf.CID_FONTS
    for name in fonts.cjk.values():
        assert fonts.covers(name, "中") and fonts.covers(name, "a") and not fonts.covers(name, "ж")
    assert load_fonts([], {"arabic"}, str(tmp_path)).cjk == {}


def test_matplotlib_font_dir_points_inside_matplotlib(monkeypatch, tmp_path):
    from types import SimpleNamespace

    monkeypatch.setattr(artifact_pdf, "find_spec", lambda name: SimpleNamespace(origin=str(tmp_path / "__init__.py")))
    assert artifact_pdf.matplotlib_font_dir() == os.path.join(str(tmp_path), "mpl-data", "fonts", "ttf")
    monkeypatch.setattr(artifact_pdf, "find_spec", lambda name: None)
    assert artifact_pdf.matplotlib_font_dir() is None

    def broken(name):
        raise ValueError("no spec")

    monkeypatch.setattr(artifact_pdf, "find_spec", broken)
    assert artifact_pdf.matplotlib_font_dir() is None


# -- Rendering ----------------------------------------------------------------------


def test_render_without_fonts_still_writes_a_helvetica_pdf(tmp_path, monkeypatch):
    spec = {"title": "Report", "blocks": [{"type": "paragraph", "text": "Plain text & <tags>"}]}
    out = _render(tmp_path, spec, table=(), font_dir=str(tmp_path), monkeypatch=monkeypatch)
    assert {name.split("+")[-1] for name in _pdf_fonts(out)} <= {"Helvetica", "Helvetica-Bold"}
    assert "Plain text & <tags>" in _pdf_text(out)


def test_render_embeds_the_base_family_and_cid_fonts(tmp_path, monkeypatch):
    spec = {
        "title": "Report 中文",
        "blocks": [
            {"type": "heading", "text": "Section", "level": 2},
            {"type": "heading", "text": "Sub", "level": 3},
            {"type": "paragraph", "text": "Latin text then 季度报告 and 四半期レポート"},
            {"type": "heading", "text": "x", "level": "junk"},
        ],
    }
    out = _render(tmp_path, spec, table=_vera_table(), font_dir=str(tmp_path), monkeypatch=monkeypatch)
    names = {name.split("+")[-1] for name in _pdf_fonts(out)}
    assert "BitstreamVeraSans-Roman" in names
    assert "BitstreamVeraSans-Bold" in names
    assert "HeiseiKakuGo-W5" in names
    text = _pdf_text(out)
    assert "Latin text then" in text and "季度报告" in text and "四半期レポート" in text


def test_render_reads_the_spec_as_data(tmp_path, monkeypatch, capfd):
    payload = "<b>not bold</b> & \"</para>\" '''__import__('os').system('echo PWNED')'''"
    spec = {"title": payload, "blocks": [{"type": "paragraph", "text": payload}]}
    out = _render(tmp_path, spec, table=_vera_table(), font_dir=str(tmp_path), monkeypatch=monkeypatch)
    assert "PWNED" not in capfd.readouterr().out
    assert "<b>not bold</b>" in _pdf_text(out)


def _image_font_table() -> List[Dict[str, str]]:
    """PDF_FONTS with paths under DOCSGPT_SANDBOX_FONT_ROOT (default: the real /usr/share/fonts)."""
    root = os.environ.get("DOCSGPT_SANDBOX_FONT_ROOT", "/usr/share/fonts")
    table = []
    for entry in manifest.PDF_FONTS:
        moved = dict(entry)
        for role in ("regular", "bold"):
            if entry[role]:
                moved[role] = entry[role].replace("/usr/share/fonts", root, 1)
        table.append(moved)
    return table


_IMAGE_FONTS = _image_font_table()
_HAVE_IMAGE_FONTS = all(
    os.path.isfile(e["regular"]) for e in _IMAGE_FONTS if e["script"] in ("base", "arabic", "devanagari")
)


@pytest.mark.skipif(not _HAVE_IMAGE_FONTS, reason="DejaVu and Noto fonts from the sandbox image are not installed")
def test_render_with_the_image_fonts(tmp_path, monkeypatch):
    pytest.importorskip("arabic_reshaper")
    pytest.importorskip("bidi")
    spec = {
        "title": "Multi-script report",
        "blocks": [{"type": "heading", "text": "Scripts", "level": 1}]
        + [{"type": "paragraph", "text": text} for text in MULTI_SCRIPT.values()],
    }
    out = _render(tmp_path, spec, table=_IMAGE_FONTS, font_dir=str(tmp_path), monkeypatch=monkeypatch)
    names = {name.split("+")[-1] for name in _pdf_fonts(out)}
    assert {"DejaVuSans", "DejaVuSans-Bold", "NotoSansDevanagari-Regular", "NotoSansArabic-Regular"} <= names
    # Each sentence picks its CJK font: the Chinese line STSong, the one with kana HeiseiKakuGo.
    assert {"STSong-Light", "HeiseiKakuGo-W5"} <= names
    text = unicodedata.normalize("NFC", _pdf_text(out))
    for key in ("latin", "cyrillic", "greek", "chinese", "japanese"):
        assert MULTI_SCRIPT[key] in text, key
    for symbol in "−→≤≥≠∞✓€":
        assert symbol in text, symbol
    # Arabic is stored as joined presentation forms in display order; extractors
    # put the letters of a word back in reading order.
    marhaba = artifact_pdf.reshape_arabic("مرحبا")
    assert marhaba in text or marhaba[::-1] in text
    # Shaped Devanagari maps conjunct glyphs to private-use code points, so only
    # the simple letters come back out.
    assert "ह" in text
