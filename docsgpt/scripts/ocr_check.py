"""Check that the configured OCR engine answers before anything is ingested.

Sends one page through the engine the native backend would use — a
generated sample, or the first page of ``--file`` — and prints the endpoint,
the time taken, the recognised text and the token usage, or the failure and
the setting to fix::

    docsgpt ocr-check
    docsgpt ocr-check --engine deepseek --file scan.pdf

Exit status is 0 when the engine read the page, 1 otherwise. The API key is
never printed.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

# The sample page. A number and a word no model would invent unprompted, so
# "recognised" means the engine read the image rather than guessed.
SAMPLE_LINES = ("DocsGPT OCR check", "Invoice 4721 total 58.90")
_SAMPLE_TOKENS = ("ocr", "4721")


def sample_image():
    """A white page with ``SAMPLE_LINES`` in large black type."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=56)
    image = Image.new("RGB", (1100, 260), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(SAMPLE_LINES):
        draw.text((50, 50 + index * 90), line, fill="black", font=font)
    return image


def sample_recognised(text: str) -> bool:
    """Whether ``text`` contains what the sample page says."""
    lowered = (text or "").lower()
    return all(token in lowered for token in _SAMPLE_TOKENS)


def _load_page(path: Path):
    """The first page of a PDF (rendered as the native backend would) or an image file."""
    from docsgpt.parser.file.ocr_parser import _render_page, fit_to_pixel_budget, render_dpi

    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            page = pdf[0]
            try:
                return _render_page(page, render_dpi())
            finally:
                page.close()
        finally:
            pdf.close()
    from PIL import Image

    with Image.open(path) as image:
        return fit_to_pixel_budget(image).copy()


def _build_engine(engine_name: str):
    from docsgpt.parser.file.ocr_parser import DeepseekOcrEngine, TesseractEngine

    if engine_name == "deepseek":
        engine = DeepseekOcrEngine()
        print(f"endpoint  {engine.endpoint.describe()}")
        if engine.endpoint.hosted:
            print("note      a hosted provider: every scanned page is sent to it")
        return engine
    engine = TesseractEngine()
    print(f"engine    tesseract {' '.join(engine.command()[3:])}")
    return engine


def main(argv: Optional[Sequence[str]] = None) -> int:
    from docsgpt.core.settings import settings
    from docsgpt.parser.file.base_parser import DocumentParseError
    from docsgpt.parser.file.ocr_parser import resolve_native_ocr_engine, resolve_ocr_backend

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        prog="docsgpt ocr-check",
        description="Send one page to the configured OCR engine and report what came back.",
    )
    parser.add_argument(
        "--engine",
        choices=("tesseract", "deepseek"),
        help="engine to check (default: OCR_ENGINE as the native backend runs it)",
    )
    parser.add_argument("--file", type=Path, help="an image or PDF to OCR instead of the generated sample")
    args = parser.parse_args(argv)

    engine_name = resolve_native_ocr_engine(args.engine)
    print(f"ocr       OCR_ENABLED={settings.OCR_ENABLED} OCR_ATTACHMENTS_ENABLED={settings.OCR_ATTACHMENTS_ENABLED}")
    print(f"backend   {resolve_ocr_backend()} (OCR_BACKEND={settings.OCR_BACKEND}); checking engine {engine_name}")
    if not settings.OCR_ENABLED and not settings.OCR_ATTACHMENTS_ENABLED:
        print("note      OCR_ENABLED and OCR_ATTACHMENTS_ENABLED are both off; ingestion will not OCR until one is on")

    engine = _build_engine(engine_name)
    try:
        image = _load_page(args.file) if args.file else sample_image()
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        print(f"error     could not read {args.file}: {exc}")
        print("OCR CHECK: FAIL")
        return 1

    started = time.monotonic()
    try:
        text = engine.ocr_image(image)
    except DocumentParseError as exc:
        print(f"error     {exc}")
        print("OCR CHECK: FAIL")
        return 1
    elapsed = time.monotonic() - started

    print(f"time      {elapsed:.1f}s for one page")
    usage = engine.usage() if hasattr(engine, "usage") else {}
    if usage.get("requests"):
        print(
            f"usage     {usage['requests']} request(s), {usage['prompt_tokens']} prompt / "
            f"{usage['completion_tokens']} completion tokens"
        )
    snippet = " ".join((text or "").split())
    print(f"text      {snippet[:300] or '(nothing)'}")
    passed = bool(snippet) if args.file else sample_recognised(text)
    if not passed and not args.file:
        print(f"error     the sample says {' / '.join(SAMPLE_LINES)!r}; the engine did not read it")
    print("OCR CHECK: " + ("PASS" if passed else "FAIL"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
