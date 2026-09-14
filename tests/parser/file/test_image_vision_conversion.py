"""Re-encoding images the model providers reject (TIFF, BMP) as PNG.

Chat attachments reach vision models as the stored file itself. OpenAI and
Anthropic accept png/jpeg/webp/gif only, so a TIFF fax or a BMP screenshot has
to be re-encoded before it can be sent at all.
"""

import io

import pytest
from PIL import Image

from docsgpt.parser.file.base_parser import DocumentParseError
from docsgpt.parser.file.image_parser import (
    VISION_CONVERTIBLE_MIME_TYPES,
    convert_image_to_png,
)


def _encoded(fmt, frames=1, size=(40, 24)):
    """An in-memory image of ``frames`` pages, each a different red level."""
    images = [Image.new("RGB", size, color=(i * 60, 20, 200)) for i in range(frames)]
    buf = io.BytesIO()
    if frames > 1:
        images[0].save(buf, format=fmt, save_all=True, append_images=images[1:])
    else:
        images[0].save(buf, format=fmt)
    buf.seek(0)
    return buf


@pytest.mark.unit
class TestConvertImageToPng:
    def test_tiff_becomes_png(self):
        png, frames = convert_image_to_png(_encoded("TIFF"))

        decoded = Image.open(io.BytesIO(png))
        assert decoded.format == "PNG"
        assert decoded.size == (40, 24)
        assert frames == 1

    def test_multi_page_tiff_keeps_the_first_page_and_reports_the_count(self):
        png, frames = convert_image_to_png(_encoded("TIFF", frames=3))

        decoded = Image.open(io.BytesIO(png)).convert("RGB")
        assert frames == 3
        assert decoded.getpixel((0, 0))[0] == 0  # page one's red level

    def test_bmp_becomes_png(self):
        png, frames = convert_image_to_png(_encoded("BMP"))

        assert Image.open(io.BytesIO(png)).format == "PNG"
        assert frames == 1

    def test_palette_tiff_is_stored_as_rgb_png(self):
        buf = io.BytesIO()
        Image.new("RGB", (40, 24), color=(0, 204, 51)).convert("P").save(buf, format="TIFF")
        buf.seek(0)

        png, _ = convert_image_to_png(buf)

        decoded = Image.open(io.BytesIO(png))
        assert decoded.mode == "RGB"
        assert decoded.getpixel((0, 0)) == (0, 204, 51)

    def test_unreadable_bytes_raise_a_parse_error(self):
        with pytest.raises(DocumentParseError):
            convert_image_to_png(io.BytesIO(b"not an image"))

    def test_image_over_the_pixel_limit_is_refused_before_decoding(self, monkeypatch):
        # A deflate TIFF under 1 MB can decode to over a gigabyte, so the
        # dimensions in the header are checked before any pixel data is read.
        from PIL import TiffImagePlugin

        from docsgpt.parser.file import image_parser

        def decode(*args, **kwargs):
            raise AssertionError("pixel data was decoded")

        monkeypatch.setattr(image_parser, "MAX_CONVERTIBLE_PIXELS", 500)
        monkeypatch.setattr(TiffImagePlugin.TiffImageFile, "load", decode)

        with pytest.raises(DocumentParseError, match="40×24"):
            convert_image_to_png(_encoded("TIFF"))

    def test_decompression_bomb_refusal_is_a_parse_error(self, monkeypatch):
        # Pillow refuses images over twice MAX_IMAGE_PIXELS with an error that
        # is not an OSError; it must fail the upload like any unreadable image.
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

        with pytest.raises(DocumentParseError):
            convert_image_to_png(_encoded("TIFF"))

    def test_only_formats_the_providers_reject_are_converted(self):
        assert {"image/tiff", "image/bmp"} <= VISION_CONVERTIBLE_MIME_TYPES
        assert not (
            {"image/png", "image/jpeg", "image/webp", "image/gif"}
            & VISION_CONVERTIBLE_MIME_TYPES
        )
