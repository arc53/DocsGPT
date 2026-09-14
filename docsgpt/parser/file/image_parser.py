"""Image parser.

Contains the parser for image files (.png, .jpg, .jpeg, .tiff, .tif, .bmp,
.webp) and the PNG re-encoding for the formats model providers reject.

"""
import io
from pathlib import Path
from typing import BinaryIO, Dict, Tuple, Union

import requests

from docsgpt.core.settings import settings
from docsgpt.parser.file.base_parser import BaseParser, DocumentParseError

# Image types the vision APIs refuse: OpenAI and Anthropic take png, jpeg,
# webp and gif only. A chat attachment in one of these formats is re-encoded
# to PNG before it is stored for the model.
VISION_CONVERTIBLE_MIME_TYPES = frozenset({"image/tiff", "image/bmp", "image/x-ms-bmp"})

# Largest image re-encoded to PNG. A deflate TIFF under 1 MB can declare
# 144 million pixels and take 1.2 GB to convert, while Pillow only warns below
# 179 million. Vision models downscale far below this cap (Anthropic refuses
# more than 8000 px per side), so a larger image gains nothing.
MAX_CONVERTIBLE_PIXELS = 40_000_000


def convert_image_to_png(file_obj: BinaryIO) -> Tuple[bytes, int]:
    """Re-encode the first frame of an image as PNG.

    Args:
        file_obj: Readable binary stream of the source image.

    Returns:
        Tuple[bytes, int]: The PNG bytes, and how many frames (pages) the
        source had. Only the first is kept.

    Raises:
        DocumentParseError: If the bytes are not an image Pillow can decode,
            or the image is larger than ``MAX_CONVERTIBLE_PIXELS``.
    """
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(file_obj) as image:
            # Opening reads only the header; refuse before any pixels decode.
            width, height = image.size
            if width * height > MAX_CONVERTIBLE_PIXELS:
                raise DocumentParseError(
                    f"The image is too large to convert ({width}×{height} pixels; the limit is "
                    f"{MAX_CONVERTIBLE_PIXELS // 1_000_000} million pixels). Resize it and upload it again."
                )
            frames = getattr(image, "n_frames", 1)
            image.seek(0)
            frame = image
            if frame.mode not in ("RGB", "RGBA", "L", "LA"):
                frame = frame.convert("RGBA" if "A" in frame.getbands() else "RGB")
            out = io.BytesIO()
            frame.save(out, format="PNG")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise DocumentParseError(f"Could not read the image: {exc}") from exc
    return out.getvalue(), frames


class ImageParser(BaseParser):
    """Image parser."""

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, list[str]]:
        if settings.PARSE_IMAGE_REMOTE:
            doc2md_service = "https://llm.arc53.com/doc2md"
            # alternatively you can use local vision capable LLM
            with open(file, "rb") as file_loaded:
                files = {'file': file_loaded}
                response = requests.post(doc2md_service, files=files, timeout=100)
                data = response.json()["markdown"]
        else:
            data = ""
        return data
