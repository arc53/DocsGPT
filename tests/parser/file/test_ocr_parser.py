"""Native OCR backend: engines, backend/engine resolution, and the PDF/image parsers.

Everything here runs without docling and without a tesseract binary: engines
are faked or their process/HTTP layer is patched. The one test that drives
the real ``tesseract`` binary skips when it is not on PATH.
"""
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import io
import logging
import pytest

pytest.importorskip("pypdfium2")
PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from application.parser.file.base_parser import DocumentParseError  # noqa: E402
from application.parser.file import ocr_parser as op  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class FakeEngine:
    """Records the images it is handed and returns canned text per call."""

    name = "fake"

    def __init__(self, texts=None):
        self.texts = list(texts) if texts is not None else []
        self.calls = []

    def ocr_image(self, image):
        self.calls.append(image.size)
        if self.texts:
            return self.texts.pop(0)
        return "OCR TEXT"


def _text_pdf(
    path: Path, pages: int = 1, text: str = "Hello text layer, plenty of characters here.", lines: int = 1
) -> Path:
    """A born-digital PDF; ``lines`` paragraphs per page make anydoc classify it as text-based."""
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    for index in range(pages):
        for line in range(lines):
            c.drawString(72, 700 - 18 * line, f"{text} page {index + 1} line {line + 1}")
        c.showPage()
    c.save()
    return path


def _image_pdf(path: Path, pages: int = 1) -> Path:
    """A PDF whose pages are pure raster images (no text layer): what a scanner produces."""
    frames = []
    for _ in range(pages):
        img = Image.new("RGB", (300, 400), "white")
        ImageDraw.Draw(img).rectangle((50, 50, 250, 350), outline="black", width=3)
        frames.append(img)
    frames[0].save(str(path), "PDF", save_all=True, append_images=frames[1:])
    return path


def _pdf_page_count(path: Path) -> int:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        return len(pdf)
    finally:
        pdf.close()


@pytest.fixture
def settings():
    from application.core.settings import settings

    return settings


# ---------------------------------------------------------------------------
# Settings aliases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSettingsAliases:
    def test_legacy_docling_names_still_configure_ocr(self, monkeypatch):
        from application.core.settings import Settings

        monkeypatch.setenv("DOCLING_OCR_ENABLED", "true")
        monkeypatch.setenv("DOCLING_OCR_ATTACHMENTS_ENABLED", "true")
        monkeypatch.setenv("DOCLING_OCR_MIN_CHARS_PER_PAGE", "7")
        loaded = Settings()
        assert loaded.OCR_ENABLED is True
        assert loaded.OCR_ATTACHMENTS_ENABLED is True
        assert loaded.OCR_MIN_CHARS_PER_PAGE == 7

    def test_new_names_and_defaults(self, monkeypatch):
        from application.core.settings import Settings

        for name in (
            "OCR_ENABLED",
            "DOCLING_OCR_ENABLED",
            "OCR_ATTACHMENTS_ENABLED",
            "DOCLING_OCR_ATTACHMENTS_ENABLED",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OCR_ENABLED", "true")
        loaded = Settings()
        assert loaded.OCR_ENABLED is True
        assert loaded.OCR_ATTACHMENTS_ENABLED is False
        assert loaded.OCR_BACKEND == "auto"
        assert loaded.OCR_ENGINE == "tesseract"
        assert loaded.OCR_DEEPSEEK_TIMEOUT == 300.0
        assert loaded.OCR_RENDER_DPI == 200


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolution:
    def test_auto_prefers_docling_when_installed(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "OCR_BACKEND", "auto")
        monkeypatch.setitem(sys.modules, "docling", MagicMock())
        assert op.resolve_ocr_backend() == "docling"

    def test_auto_is_native_without_docling(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "OCR_BACKEND", "auto")
        monkeypatch.setitem(sys.modules, "docling", None)
        assert op.resolve_ocr_backend() == "native"

    def test_native_wins_over_installed_docling(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "OCR_BACKEND", "native")
        monkeypatch.setitem(sys.modules, "docling", MagicMock())
        assert op.resolve_ocr_backend() == "native"

    def test_docling_backend_degrades_to_native_when_missing(self, monkeypatch, settings, caplog):
        monkeypatch.setattr(settings, "OCR_BACKEND", "docling")
        monkeypatch.setitem(sys.modules, "docling", None)
        with caplog.at_level("WARNING"):
            assert op.resolve_ocr_backend() == "native"
        assert "OCR_BACKEND=docling" in caplog.text

    def test_unknown_backend_is_auto(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "OCR_BACKEND", "paddle")
        monkeypatch.setitem(sys.modules, "docling", None)
        assert op.resolve_ocr_backend() == "native"

    @pytest.mark.parametrize("engine", ["tesseract", "deepseek"])
    def test_native_engines_pass_through(self, engine):
        assert op.resolve_native_ocr_engine(engine) == engine

    @pytest.mark.parametrize("engine", ["auto", "ocrmac", "rapidocr", "easyocr", ""])
    def test_docling_only_or_unknown_engines_become_tesseract(self, engine, monkeypatch, settings, caplog):
        monkeypatch.setattr(settings, "OCR_ENGINE", engine)
        with caplog.at_level("WARNING"):
            assert op.resolve_native_ocr_engine(None) == "tesseract"
        if engine:
            assert "tesseract" in caplog.text

    def test_build_engine_from_setting(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "OCR_ENGINE", "deepseek")
        assert isinstance(op.build_native_ocr_engine(), op.DeepseekOcrEngine)
        monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")
        assert isinstance(op.build_native_ocr_engine(), op.TesseractEngine)

    def test_render_dpi_is_clamped(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "OCR_RENDER_DPI", 10)
        assert op.render_dpi() == 72
        monkeypatch.setattr(settings, "OCR_RENDER_DPI", 5000)
        assert op.render_dpi() == 600
        monkeypatch.setattr(settings, "OCR_RENDER_DPI", "nope")
        assert op.render_dpi() == 200


# ---------------------------------------------------------------------------
# Tesseract engine
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTesseractEngine:
    def test_command_uses_ocr_langs_setting(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "OCR_LANGS", "eng+chi_sim")
        assert op.TesseractEngine().command() == [
            "tesseract", "stdin", "stdout", "-l", "eng+chi_sim", "--psm", "3",
        ]

    def test_explicit_languages_override_setting(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "OCR_LANGS", "eng")
        assert op.TesseractEngine(languages=["deu", " fra "]).command()[4] == "deu+fra"

    def test_missing_binary_is_a_typed_error(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        with pytest.raises(op.OcrUnavailableError, match="INSTALL_TESSERACT"):
            op.TesseractEngine().ocr_image(Image.new("RGB", (10, 10)))

    def test_stdin_stdout_roundtrip_is_mocked(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/tesseract")
        seen = {}

        def fake_run(cmd, input=None, capture_output=None, timeout=None, check=None):
            seen["cmd"], seen["input"] = cmd, input
            return subprocess.CompletedProcess(cmd, 0, stdout=b"  recognised words \n", stderr=b"")

        monkeypatch.setattr(subprocess, "run", fake_run)
        text = op.TesseractEngine().ocr_image(Image.new("RGBA", (10, 10)))
        assert text == "recognised words"
        assert seen["cmd"][:3] == ["tesseract", "stdin", "stdout"]
        assert seen["input"].startswith(b"\x89PNG")  # RGBA flattened and PNG-encoded

    def test_cjk_glyph_spaces_are_collapsed(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/tesseract")
        raw = "互相 保密 协议\n本 协议 由 Meridian Components Ltd. 与 深圳 华 芯 于 2026 年 9 月 1 日 签 订 。 各 方\n"
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout=raw.encode("utf-8"), stderr=b""),
        )
        text = op.TesseractEngine().ocr_image(Image.new("RGB", (10, 10)))
        assert text == "互相保密协议\n本协议由 Meridian Components Ltd. 与深圳华芯于 2026 年 9 月 1 日签订。各方"

    def test_collapse_cjk_spaces_leaves_latin_alone(self):
        assert op.collapse_cjk_spaces("hello world 你 好 ok 再 见") == "hello world 你好 ok 再见"

    def test_nonzero_exit_and_timeout_become_parse_errors(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/tesseract")
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a[0], 1, stdout=b"", stderr=b"Error opening data file"),
        )
        with pytest.raises(DocumentParseError, match="Error opening data file"):
            op.TesseractEngine().ocr_image(Image.new("RGB", (10, 10)))

        def timeout(*a, **k):
            raise subprocess.TimeoutExpired(a[0], 5)

        monkeypatch.setattr(subprocess, "run", timeout)
        with pytest.raises(DocumentParseError, match="timed out"):
            op.TesseractEngine(timeout=5).ocr_image(Image.new("RGB", (10, 10)))

    @pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not installed")
    def test_real_binary_reads_rendered_text(self):
        img = Image.new("RGB", (700, 140), "white")
        draw = ImageDraw.Draw(img)
        try:
            from PIL import ImageFont

            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 48)
        except (OSError, ImportError):
            font = None
        draw.text((20, 40), "NATIVE OCR 2026", fill="black", font=font)
        text = op.TesseractEngine(languages=["eng"]).ocr_image(img)
        assert "OCR" in text.upper()


# ---------------------------------------------------------------------------
# DeepSeek engine
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeepseekEngine:
    def test_defaults_come_from_settings(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "OCR_DEEPSEEK_URL", "http://vllm:8000/v1/chat/completions")
        monkeypatch.setattr(settings, "OCR_DEEPSEEK_MODEL", "deepseek-ai/DeepSeek-OCR")
        monkeypatch.setattr(settings, "OCR_DEEPSEEK_TIMEOUT", 42)
        engine = op.DeepseekOcrEngine()
        assert engine.url.startswith("http://vllm")
        assert engine.model == "deepseek-ai/DeepSeek-OCR"
        assert engine.timeout == 42.0

    def test_payload_is_openai_compatible_with_data_url(self):
        engine = op.DeepseekOcrEngine(url="http://x", model="m", timeout=1)
        payload = engine.payload(Image.new("RGB", (8, 8)))
        assert payload["model"] == "m"
        assert payload["temperature"] == 0
        parts = payload["messages"][0]["content"]
        assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert parts[1]["text"] == op.DEEPSEEK_PROMPT
        assert "<|grounding|>" not in parts[1]["text"]

    def test_success_strips_grounding_markup(self):
        engine = op.DeepseekOcrEngine(url="http://x", model="m", timeout=1)
        response = MagicMock()
        response.json.return_value = {
            "choices": [{"message": {"content": "<|ref|>Title<|/ref|><|det|>[[1, 2, 3, 4]]<|/det|>\n\n| a | b |"}}]
        }
        with patch("requests.post", return_value=response) as post:
            text = engine.ocr_image(Image.new("RGB", (8, 8)))
        assert text == "Title\n\n| a | b |"
        assert post.call_args.kwargs["timeout"] == 1.0
        assert post.call_args.args[0] == "http://x"

    def test_content_parts_list_is_joined(self):
        engine = op.DeepseekOcrEngine(url="http://x", model="m", timeout=1)
        response = MagicMock()
        response.json.return_value = {"choices": [{"message": {"content": [{"type": "text", "text": "ab"}]}}]}
        with patch("requests.post", return_value=response):
            assert engine.ocr_image(Image.new("RGB", (8, 8))) == "ab"

    def test_network_failure_is_a_parse_error_with_hint(self):
        import requests

        engine = op.DeepseekOcrEngine(url="http://x", model="deepseek-ocr:3b", timeout=1)
        with (
            patch("requests.post", side_effect=requests.ConnectionError("refused")),
            pytest.raises(DocumentParseError, match="OCR_DEEPSEEK_URL"),
        ):
            engine.ocr_image(Image.new("RGB", (8, 8)))

    def test_malformed_body_is_a_parse_error(self):
        engine = op.DeepseekOcrEngine(url="http://x", model="m", timeout=1)
        response = MagicMock()
        response.json.return_value = {"error": "model not found"}
        with (
            patch("requests.post", return_value=response),
            pytest.raises(DocumentParseError, match="no chat completion"),
        ):
            engine.ocr_image(Image.new("RGB", (8, 8)))

    def test_clean_output_helper(self):
        raw = "<|grounding|><|ref|>x<|/ref|><|det|>[[0,0,1,1]]<|/det|> y<|end▁of▁sentence|>"
        assert op.clean_deepseek_output(raw) == "x y"


# ---------------------------------------------------------------------------
# PDF parser
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNativeOcrPdfParser:
    def test_text_layer_pages_are_read_without_ocr(self, tmp_path):
        pdf = _text_pdf(tmp_path / "text.pdf", pages=2)
        engine = FakeEngine()
        parser = op.NativeOcrPdfParser(engine=engine)
        parser.init_parser()

        content = parser.parse_file(pdf)

        assert engine.calls == []
        assert "page 1" in content and "page 2" in content
        assert parser.last_engine == "fake"
        assert parser.get_file_metadata(pdf) == {"parse_engine": "fake", "pdf_pages": 2, "ocr_pages": 0}

    def test_scanned_pages_are_rendered_and_ocrd(self, tmp_path, monkeypatch, settings):
        pdf = _image_pdf(tmp_path / "scan.pdf", pages=2)
        assert _pdf_page_count(pdf) == 2
        monkeypatch.setattr(settings, "OCR_RENDER_DPI", 72)
        engine = FakeEngine(["first page words here", "second page words here"])
        parser = op.NativeOcrPdfParser(engine=engine)

        content = parser.parse_file(pdf)

        assert len(engine.calls) == 2
        assert all(width > 0 and height > 0 for width, height in engine.calls)
        assert content == "first page words here\n\nsecond page words here"
        assert parser.get_file_metadata(pdf)["ocr_pages"] == 2

    def test_render_dpi_scales_the_page_image(self, tmp_path, monkeypatch, settings):
        pdf = _image_pdf(tmp_path / "scan.pdf")
        sizes = {}
        for dpi in (72, 144):
            monkeypatch.setattr(settings, "OCR_RENDER_DPI", dpi)
            engine = FakeEngine(["some words on this page, enough of them"])
            op.NativeOcrPdfParser(engine=engine).parse_file(pdf)
            sizes[dpi] = engine.calls[0]
        assert sizes[144][0] == pytest.approx(sizes[72][0] * 2, abs=2)

    def test_mixed_document_ocrs_only_the_scanned_pages(self, tmp_path, monkeypatch, settings):
        """A text page followed by an image page: the text layer is used where it exists."""
        pytest.importorskip("pypdf")
        from pypdf import PdfWriter

        text_pdf = _text_pdf(tmp_path / "t.pdf")
        image_pdf = _image_pdf(tmp_path / "i.pdf")
        writer = PdfWriter()
        for source in (text_pdf, image_pdf):
            writer.append(str(source))
        mixed = tmp_path / "mixed.pdf"
        with open(mixed, "wb") as handle:
            writer.write(handle)
        monkeypatch.setattr(settings, "OCR_RENDER_DPI", 72)

        engine = FakeEngine(["scanned page words"])
        parser = op.NativeOcrPdfParser(engine=engine)
        content = parser.parse_file(mixed)

        assert len(engine.calls) == 1
        assert "page 1" in content and "scanned page words" in content
        assert parser.get_file_metadata(mixed) == {"parse_engine": "fake", "pdf_pages": 2, "ocr_pages": 1}

    def test_text_parser_takes_fully_text_documents(self, tmp_path):
        pdf = _text_pdf(tmp_path / "text.pdf", pages=2)
        text_parser = MagicMock()
        text_parser.parser_config_set = True
        text_parser.parse_file.return_value = "# structured markdown"
        text_parser.get_file_metadata.return_value = {"x": 1}
        text_parser.last_engine = None
        engine = FakeEngine()

        parser = op.NativeOcrPdfParser(engine=engine, text_parser=text_parser)
        content = parser.parse_file(pdf)

        assert content == "# structured markdown"
        assert engine.calls == []
        text_parser.parse_file.assert_called_once()
        assert parser.get_file_metadata(pdf)["x"] == 1
        assert parser.last_engine == "MagicMock"

    def test_text_parser_is_bypassed_when_any_page_is_scanned(self, tmp_path, monkeypatch, settings):
        pdf = _image_pdf(tmp_path / "scan.pdf")
        monkeypatch.setattr(settings, "OCR_RENDER_DPI", 72)
        text_parser = MagicMock()
        engine = FakeEngine(["enough recognised words to pass the floor"])

        op.NativeOcrPdfParser(engine=engine, text_parser=text_parser).parse_file(pdf)

        text_parser.parse_file.assert_not_called()
        assert len(engine.calls) == 1

    def test_multi_page_scan_that_ocrs_to_nothing_fails_loudly(self, tmp_path, monkeypatch, settings):
        pdf = _image_pdf(tmp_path / "blank.pdf", pages=3)
        monkeypatch.setattr(settings, "OCR_RENDER_DPI", 72)
        monkeypatch.setattr(settings, "OCR_MIN_CHARS_PER_PAGE", 20)
        parser = op.NativeOcrPdfParser(engine=FakeEngine(["", "", ""]))
        with pytest.raises(DocumentParseError, match="produced no text over 3 pages"):
            parser.parse_file(pdf)

    def test_sparse_single_page_is_kept_with_a_warning(self, tmp_path, monkeypatch, settings, caplog):
        pdf = _image_pdf(tmp_path / "logo.pdf")
        monkeypatch.setattr(settings, "OCR_RENDER_DPI", 72)
        monkeypatch.setattr(settings, "OCR_MIN_CHARS_PER_PAGE", 20)
        with caplog.at_level("WARNING"):
            content = op.NativeOcrPdfParser(engine=FakeEngine(["ACME"])).parse_file(pdf)
        assert content == "ACME"
        assert "text-sparse" in caplog.text

    def test_guard_disabled_with_zero_floor(self, tmp_path, monkeypatch, settings):
        pdf = _image_pdf(tmp_path / "blank.pdf", pages=2)
        monkeypatch.setattr(settings, "OCR_RENDER_DPI", 72)
        monkeypatch.setattr(settings, "OCR_MIN_CHARS_PER_PAGE", 0)
        assert op.NativeOcrPdfParser(engine=FakeEngine(["", ""])).parse_file(pdf) == "\n\n"

    def test_engine_failure_propagates_as_parse_error(self, tmp_path, monkeypatch, settings):
        pdf = _image_pdf(tmp_path / "scan.pdf")
        monkeypatch.setattr(settings, "OCR_RENDER_DPI", 72)

        class Broken:
            name = "broken"

            def ocr_image(self, image):
                raise DocumentParseError("engine down")

        with pytest.raises(DocumentParseError, match="engine down"):
            op.NativeOcrPdfParser(engine=Broken()).parse_file(pdf)

    def test_unreadable_file_is_a_parse_error(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not a pdf")
        with pytest.raises(DocumentParseError, match="Failed to open"):
            op.NativeOcrPdfParser(engine=FakeEngine()).parse_file(bad)

    def test_engine_is_built_lazily_from_settings(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "OCR_ENGINE", "deepseek")
        parser = op.NativeOcrPdfParser()
        parser.init_parser()
        assert isinstance(parser.engine, op.DeepseekOcrEngine)
        assert parser.parser_config["engine"] == "deepseek"

    def test_reports_ocr_enabled_for_anydoc_hint(self):
        assert op.NativeOcrPdfParser(engine=FakeEngine()).ocr_enabled is True


# ---------------------------------------------------------------------------
# Image parser
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNativeOcrImageParser:
    def test_single_image(self, tmp_path):
        png = tmp_path / "scan.png"
        Image.new("RGB", (40, 30), "white").save(png)
        engine = FakeEngine(["words from the picture"])
        parser = op.NativeOcrImageParser(engine=engine)

        assert parser.parse_file(png) == "words from the picture"
        assert engine.calls == [(40, 30)]
        assert parser.get_file_metadata(png) == {"parse_engine": "fake", "ocr_pages": 1}

    def test_multi_frame_tiff_ocrs_every_frame(self, tmp_path):
        tiff = tmp_path / "fax.tiff"
        frames = [Image.new("L", (20, 20), 255) for _ in range(3)]
        frames[0].save(tiff, save_all=True, append_images=frames[1:])
        engine = FakeEngine(["one page", "two pages", "three pages"])

        content = op.NativeOcrImageParser(engine=engine).parse_file(tiff)

        assert len(engine.calls) == 3
        assert content == "one page\n\ntwo pages\n\nthree pages"

    def test_multi_frame_that_ocrs_to_nothing_fails(self, tmp_path, monkeypatch, settings):
        tiff = tmp_path / "fax.tiff"
        frames = [Image.new("L", (20, 20), 255) for _ in range(2)]
        frames[0].save(tiff, save_all=True, append_images=frames[1:])
        monkeypatch.setattr(settings, "OCR_MIN_CHARS_PER_PAGE", 20)
        with pytest.raises(DocumentParseError, match="produced no text"):
            op.NativeOcrImageParser(engine=FakeEngine(["", ""])).parse_file(tiff)

    def test_undecodable_image_is_a_parse_error(self, tmp_path):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"nope")
        with pytest.raises(DocumentParseError, match="Failed to OCR"):
            op.NativeOcrImageParser(engine=FakeEngine()).parse_file(bad)


# ---------------------------------------------------------------------------
# Extractor-map wiring (bulk.py)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractorWiring:
    def test_legacy_map_without_ocr_is_unchanged(self):
        from application.parser.file.bulk import _legacy_file_extractor

        extractor = _legacy_file_extractor()
        assert type(extractor[".pdf"]).__name__ == "PDFParser"
        assert type(extractor[".png"]).__name__ == "ImageParser"
        assert ".tiff" not in extractor

    def test_legacy_map_with_ocr_uses_native_parsers(self):
        from application.parser.file.bulk import _legacy_file_extractor

        extractor = _legacy_file_extractor(ocr_enabled=True)
        assert isinstance(extractor[".pdf"], op.NativeOcrPdfParser)
        assert extractor[".pdf"].text_parser is None
        for suffix in op.IMAGE_SUFFIXES:
            assert isinstance(extractor[suffix], op.NativeOcrImageParser)

    def test_ocr_without_docling_reaches_native_under_anydoc(self, monkeypatch):
        pytest.importorskip("anydoc")
        from application.parser.file.anydoc_parser import AnydocParser
        from application.parser.file.bulk import get_default_file_extractor

        monkeypatch.setitem(sys.modules, "docling", None)
        extractor = get_default_file_extractor(engine="anydoc", ocr_enabled=True)

        assert isinstance(extractor[".pdf"], AnydocParser)
        assert isinstance(extractor[".pdf"].fallback_parser, op.NativeOcrPdfParser)
        assert isinstance(extractor[".png"], op.NativeOcrImageParser)

    def test_ocr_without_docling_reaches_native_under_docling_engine(self, monkeypatch):
        from application.parser.file.bulk import get_default_file_extractor

        monkeypatch.setitem(sys.modules, "docling", None)
        extractor = get_default_file_extractor(engine="docling", ocr_enabled=True)
        assert isinstance(extractor[".pdf"], op.NativeOcrPdfParser)
        assert isinstance(extractor[".jpg"], op.NativeOcrImageParser)

    def test_ocr_off_without_docling_keeps_legacy(self, monkeypatch):
        from application.parser.file.bulk import get_default_file_extractor

        monkeypatch.setitem(sys.modules, "docling", None)
        extractor = get_default_file_extractor(engine="docling", ocr_enabled=False)
        assert type(extractor[".pdf"]).__name__ == "PDFParser"
        assert type(extractor[".png"]).__name__ == "ImageParser"

    def test_native_backend_with_docling_installed_wraps_docling_for_text_pdfs(self, monkeypatch, settings):
        pytest.importorskip("docling")
        from application.parser.file.bulk import get_default_file_extractor
        from application.parser.file.docling_parser import DoclingPDFParser

        monkeypatch.setattr(settings, "OCR_BACKEND", "native")
        extractor = get_default_file_extractor(engine="docling", ocr_enabled=True)

        pdf_parser = extractor[".pdf"]
        assert isinstance(pdf_parser, op.NativeOcrPdfParser)
        assert isinstance(pdf_parser.text_parser, DoclingPDFParser)
        assert pdf_parser.text_parser.ocr_enabled is False
        assert isinstance(extractor[".png"], op.NativeOcrImageParser)
        # docling still owns what anydoc/native cannot read.
        assert type(extractor[".vtt"]).__name__ == "DoclingVTTParser"

    def test_native_backend_under_anydoc_keeps_docling_reroute_for_trust_check(self, monkeypatch, settings):
        pytest.importorskip("anydoc")
        pytest.importorskip("docling")
        from application.parser.file.anydoc_parser import _is_docling_backed
        from application.parser.file.bulk import get_default_file_extractor

        monkeypatch.setattr(settings, "OCR_BACKEND", "native")
        extractor = get_default_file_extractor(engine="anydoc", ocr_enabled=True)

        fallback = extractor[".pdf"].fallback_parser
        assert isinstance(fallback, op.NativeOcrPdfParser)
        assert _is_docling_backed(fallback) is True

    def test_auto_backend_with_docling_installed_is_unchanged(self, monkeypatch, settings):
        pytest.importorskip("docling")
        from application.parser.file.bulk import get_default_file_extractor

        monkeypatch.setattr(settings, "OCR_BACKEND", "auto")
        extractor = get_default_file_extractor(engine="docling", ocr_enabled=True)
        assert type(extractor[".pdf"]).__name__ == "DoclingPDFParser"
        assert extractor[".pdf"].ocr_enabled is True
        assert type(extractor[".png"]).__name__ == "DoclingImageParser"

    def test_anydoc_scan_hint_names_new_setting(self, tmp_path):
        pytest.importorskip("anydoc")
        from application.parser.file.anydoc_parser import AnydocParser

        fallback = MagicMock()
        fallback.parser_config_set = True
        fallback.parse_file.return_value = ""
        fallback.ocr_enabled = False
        parser = AnydocParser(fallback_parser=fallback)
        pdf = _image_pdf(tmp_path / "scan.pdf")
        with pytest.raises(DocumentParseError, match="OCR_ENABLED=true"):
            parser.parse_file(pdf)


# ---------------------------------------------------------------------------
# Mixed documents: page probe + page-subset OCR
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScannedPageProbe:
    def test_indices_of_pages_without_text_layer(self, tmp_path):
        pytest.importorskip("pypdf")
        from pypdf import PdfWriter

        text_pdf = _text_pdf(tmp_path / "t.pdf", pages=2)
        image_pdf = _image_pdf(tmp_path / "i.pdf")
        writer = PdfWriter()
        writer.append(str(text_pdf))
        writer.append(str(image_pdf))
        writer.append(str(text_pdf))
        mixed = tmp_path / "mixed.pdf"
        with open(mixed, "wb") as handle:
            writer.write(handle)

        assert op.scanned_page_indices(mixed) == [2]
        assert op.text_layer_counts(mixed)[2] == 0

    def test_all_text_gives_empty_list(self, tmp_path):
        assert op.scanned_page_indices(_text_pdf(tmp_path / "t.pdf", pages=3)) == []

    def test_unreadable_file_gives_empty_list(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"nope")
        assert op.scanned_page_indices(bad) == []

    def test_ocr_pages_renders_only_requested_pages(self, tmp_path, monkeypatch, settings):
        pdf = _image_pdf(tmp_path / "scan.pdf", pages=3)
        monkeypatch.setattr(settings, "OCR_RENDER_DPI", 72)
        engine = FakeEngine(["page three", "page one"])
        parser = op.NativeOcrPdfParser(engine=engine)

        texts = parser.ocr_pages(pdf, [2, 0, 99])

        assert texts == {2: "page three", 0: "page one"}
        assert len(engine.calls) == 2
        assert parser.last_engine == "fake"


@pytest.mark.unit
class TestAnydocMixedDocuments:
    """anydoc converts a text PDF with scanned pages and silently skips them; OCR fills them in."""

    @pytest.fixture
    def mixed_pdf(self, tmp_path):
        pytest.importorskip("pypdf")
        from pypdf import PdfWriter

        text_pdf = _text_pdf(tmp_path / "t.pdf", pages=2, text="Digital text page with enough characters", lines=25)
        image_pdf = _image_pdf(tmp_path / "i.pdf")
        writer = PdfWriter()
        writer.append(str(text_pdf))
        writer.append(str(image_pdf))
        mixed = tmp_path / "mixed.pdf"
        with open(mixed, "wb") as handle:
            writer.write(handle)
        return mixed

    def test_scanned_page_is_ocrd_and_appended(self, mixed_pdf, monkeypatch, settings):
        pytest.importorskip("anydoc")
        from application.parser.file.anydoc_parser import AnydocParser

        monkeypatch.setattr(settings, "OCR_RENDER_DPI", 72)
        engine = FakeEngine(["SCANNED PAGE WORDS"])
        fallback = op.NativeOcrPdfParser(engine=engine)
        parser = AnydocParser(fallback_parser=fallback)

        content = parser.parse_file(mixed_pdf)

        assert "Digital text page" in content
        assert content.rstrip().endswith("SCANNED PAGE WORDS")
        assert len(engine.calls) == 1  # only the scanned page was rendered
        assert parser.last_engine == "anydoc"
        assert parser.get_file_metadata(mixed_pdf) == {"ocr_pages": 1}

    def test_no_ocr_fallback_keeps_text_pages_only(self, mixed_pdf):
        pytest.importorskip("anydoc")
        from application.parser.file.anydoc_parser import AnydocParser
        from application.parser.file.docs_parser import PDFParser

        parser = AnydocParser(fallback_parser=PDFParser())
        content = parser.parse_file(mixed_pdf)

        assert "Digital text page" in content
        assert parser.get_file_metadata(mixed_pdf) == {}

    def test_fallback_with_ocr_off_is_not_used(self, mixed_pdf):
        pytest.importorskip("anydoc")
        from application.parser.file.anydoc_parser import AnydocParser

        fallback = MagicMock()
        fallback.ocr_enabled = False
        parser = AnydocParser(fallback_parser=fallback)
        parser.parse_file(mixed_pdf)
        fallback.ocr_pages.assert_not_called()

    def test_ocr_failure_keeps_text_pages(self, mixed_pdf, caplog):
        pytest.importorskip("anydoc")
        from application.parser.file.anydoc_parser import AnydocParser

        fallback = MagicMock()
        fallback.ocr_enabled = True
        fallback.parser_config_set = True
        fallback.ocr_pages.side_effect = DocumentParseError("engine down")
        parser = AnydocParser(fallback_parser=fallback)

        with caplog.at_level("WARNING"):
            content = parser.parse_file(mixed_pdf)

        assert "Digital text page" in content
        assert "skipping that page" in caplog.text
        assert parser.get_file_metadata(mixed_pdf) == {}

    def test_all_text_document_never_probes_ocr(self, tmp_path):
        pytest.importorskip("anydoc")
        from application.parser.file.anydoc_parser import AnydocParser

        pdf = _text_pdf(tmp_path / "t.pdf", pages=2, text="Digital text page with enough characters", lines=25)
        fallback = MagicMock()
        fallback.ocr_enabled = True
        parser = AnydocParser(fallback_parser=fallback)
        parser.parse_file(pdf)
        fallback.ocr_pages.assert_not_called()


# ---------------------------------------------------------------------------
# Render budget: an oversized MediaBox must not become a multi-GB bitmap
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRenderBudget:
    def test_letter_page_is_not_clamped(self):
        assert op.render_scale(612, 792, 200) == pytest.approx(200 / 72)

    def test_pdf_maximum_page_is_clamped_to_the_budget(self):
        scale = op.render_scale(14400, 14400, 200)
        assert scale < 200 / 72
        assert (14400 * scale) * (14400 * scale) <= op._MAX_RENDER_PIXELS * 1.001

    def test_huge_page_renders_within_budget(self, tmp_path, caplog):
        """A 14400x14400 pt blank page (the PDF maximum, a few hundred bytes)
        would be 40000x40000 px = 6 GiB at 200 dpi without the cap."""
        pytest.importorskip("pypdf")
        import pypdfium2 as pdfium
        from pypdf import PdfWriter

        path = tmp_path / "huge.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=14400, height=14400)
        with open(path, "wb") as fh:
            writer.write(fh)

        pdf = pdfium.PdfDocument(str(path))
        try:
            page = pdf[0]
            try:
                with caplog.at_level(logging.WARNING, logger="application.parser.file.ocr_parser"):
                    image = op._render_page(page, 200)
            finally:
                page.close()
        finally:
            pdf.close()
        assert image.width * image.height <= op._MAX_RENDER_PIXELS * 1.001
        assert "stay within" in caplog.text


# ---------------------------------------------------------------------------
# Scanned-page probe: thin text layers count only over an image
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScannedPageProbeImageGate:
    def _cover_and_figure_pdf(self, path: Path) -> Path:
        pytest.importorskip("reportlab")
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        c = canvas.Canvas(str(path), pagesize=letter)
        # Page 1: a short title and nothing else — not a scan, nothing to OCR.
        c.setFont("Helvetica", 36)
        c.drawString(72, 500, "Annual Report 2025")
        c.showPage()
        # Page 2: a page number under a full-page raster figure — a scan with a stamp.
        img = Image.new("RGB", (300, 400), "white")
        ImageDraw.Draw(img).rectangle((50, 50, 250, 350), outline="black", width=3)
        c.drawImage(ImageReader(img), 72, 150, width=450, height=600)
        c.setFont("Helvetica", 10)
        c.drawString(300, 60, "17")
        c.showPage()
        # Page 3: ordinary text.
        c.setFont("Helvetica", 12)
        c.drawString(72, 700, "A full paragraph of ordinary body text that anydoc reads directly.")
        c.showPage()
        c.save()
        return path

    def test_short_text_page_without_image_is_not_scanned(self, tmp_path):
        path = self._cover_and_figure_pdf(tmp_path / "cover.pdf")
        counts = op.text_layer_counts(path)
        assert 0 < counts[0] < op.DEFAULT_TEXT_LAYER_MIN_CHARS
        assert 0 < counts[1] < op.DEFAULT_TEXT_LAYER_MIN_CHARS
        assert op.scanned_page_indices(path) == [1]

    def test_pages_with_no_text_at_all_still_count(self, tmp_path):
        assert op.scanned_page_indices(_image_pdf(tmp_path / "scan.pdf", pages=2)) == [0, 1]


# ---------------------------------------------------------------------------
# Second-pass fixes: language packs, alpha, animations, image budget, errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTesseractLanguagePacks:
    def test_missing_pack_with_exit_zero_is_a_typed_error(self, monkeypatch):
        """tesseract drops a missing pack, exits 0 and OCRs with the rest — that must not pass silently."""
        monkeypatch.setattr(op.shutil, "which", lambda name: "/usr/bin/tesseract")

        def fake_run(cmd, input=None, capture_output=None, timeout=None, check=None):
            return subprocess.CompletedProcess(
                cmd, 0, stdout=b"English only\n",
                stderr=b"Error opening data file /usr/share/tessdata/chi_sim.traineddata\n",
            )

        monkeypatch.setattr(op.subprocess, "run", fake_run)
        engine = op.TesseractEngine(languages=["eng", "chi_sim"])
        with pytest.raises(op.OcrUnavailableError, match="chi_sim"):
            engine.ocr_image(Image.new("RGB", (10, 10), "white"))

    def test_list_langs_is_parsed(self, monkeypatch):
        op.tesseract_languages.cache_clear()
        monkeypatch.setattr(op.shutil, "which", lambda name: "/usr/bin/tesseract")

        def fake_run(cmd, capture_output=None, timeout=None, check=None):
            return subprocess.CompletedProcess(
                cmd, 0, stdout=b"List of available languages in /usr/share/tessdata/ (3):\nchi_sim\neng\nosd\n", stderr=b""
            )

        monkeypatch.setattr(op.subprocess, "run", fake_run)
        try:
            assert op.tesseract_languages() == frozenset({"chi_sim", "eng", "osd"})
        finally:
            op.tesseract_languages.cache_clear()


@pytest.mark.unit
class TestImageNormalisation:
    def test_transparent_background_is_flattened_to_white(self):
        rgba = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        rgba.putpixel((1, 1), (0, 0, 0, 255))  # one black "text" pixel
        flat = Image.open(io.BytesIO(op._png_bytes(rgba)))
        assert flat.mode == "RGB"
        assert flat.getpixel((0, 0)) == (255, 255, 255)
        assert flat.getpixel((1, 1)) == (0, 0, 0)

    def test_palette_transparency_is_flattened(self):
        pal = Image.new("P", (2, 2), 0)
        pal.info["transparency"] = 0
        flat = Image.open(io.BytesIO(op._png_bytes(pal)))
        assert flat.getpixel((0, 0)) == (255, 255, 255)

    def test_oversized_image_is_downscaled_to_the_budget(self, caplog):
        big = Image.new("L", (9000, 9000), 255)
        with caplog.at_level(logging.WARNING, logger="application.parser.file.ocr_parser"):
            small = op.fit_to_pixel_budget(big)
        assert small.width * small.height <= op._MAX_RENDER_PIXELS
        assert "downscaling" in caplog.text

    def test_small_image_is_untouched(self):
        img = Image.new("RGB", (300, 200), "white")
        assert op.fit_to_pixel_budget(img) is img

    def test_animated_gif_ocrs_only_the_first_frame(self, tmp_path):
        frames = [Image.new("RGB", (20, 20), "white") for _ in range(5)]
        gif = tmp_path / "anim.gif"
        frames[0].save(gif, save_all=True, append_images=frames[1:], duration=50, loop=0)
        engine = FakeEngine(["frame text"])
        parser = op.NativeOcrImageParser(engine=engine)
        assert parser.parse_file(gif) == "frame text"
        assert parser.get_file_metadata(gif)["ocr_pages"] == 1

    def test_multi_page_tiff_still_reads_every_frame(self, tmp_path):
        frames = [Image.new("L", (20, 20), 255) for _ in range(3)]
        tiff = tmp_path / "fax.tiff"
        frames[0].save(tiff, save_all=True, append_images=frames[1:])
        parser = op.NativeOcrImageParser(engine=FakeEngine(["a", "b", "c"]))
        assert parser.parse_file(tiff) == "a\n\nb\n\nc"


@pytest.mark.unit
class TestDeepseekErrorShapes:
    def test_non_json_body_is_reported_as_such(self, monkeypatch):
        import requests

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                raise requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)

        monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
        engine = op.DeepseekOcrEngine(url="http://proxy.local/v1/chat/completions", model="m")
        with pytest.raises(DocumentParseError, match="non-JSON body"):
            engine.ocr_image(Image.new("RGB", (5, 5), "white"))


@pytest.mark.unit
def test_delegate_parse_lets_setup_errors_through():
    """A fallback whose dependency is missing is a deployment problem, not a bad file."""
    from application.parser.file.base_parser import BaseParser, delegate_parse

    class _NeedsLib(BaseParser):
        def _init_parser(self):
            raise ImportError("docling is required")

        def parse_file(self, file, errors="ignore"):
            return "never"

    with pytest.raises(ImportError, match="docling is required"):
        delegate_parse(_NeedsLib(), Path("x.pdf"), "ignore")


class TestTextLayerDelegate:
    """``text_layer_delegate`` mirrors ``parse_file``'s delegation decision."""

    def test_every_page_with_text_returns_the_text_parser(self, monkeypatch):
        import pypdfium2 as pdfium

        class _Pdf:
            def close(self):
                pass

        monkeypatch.setattr(pdfium, "PdfDocument", lambda path: _Pdf())
        text_parser = object()
        parser = op.NativeOcrPdfParser(text_parser=text_parser, min_text_chars=20)
        monkeypatch.setattr(parser, "_text_layer_counts", lambda pdf: [50, 60])
        assert parser.text_layer_delegate(Path("x.pdf")) is text_parser

    def test_a_scanned_page_keeps_the_native_path(self, monkeypatch):
        import pypdfium2 as pdfium

        class _Pdf:
            def close(self):
                pass

        monkeypatch.setattr(pdfium, "PdfDocument", lambda path: _Pdf())
        parser = op.NativeOcrPdfParser(text_parser=object(), min_text_chars=20)
        monkeypatch.setattr(parser, "_text_layer_counts", lambda pdf: [50, 3])
        assert parser.text_layer_delegate(Path("x.pdf")) is None

    def test_no_text_parser_or_unreadable_file_is_none(self, tmp_path):
        assert op.NativeOcrPdfParser().text_layer_delegate(Path("x.pdf")) is None
        broken = tmp_path / "broken.pdf"
        broken.write_bytes(b"not a pdf")
        assert op.NativeOcrPdfParser(text_parser=object()).text_layer_delegate(broken) is None
