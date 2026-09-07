"""Check that an image can serve its defaults without any network access.

Exercises the code paths a fresh container hits first, the way the
application does: tiktoken token counting, the chunker's tokenizer for each
baked embedding model, and a FastEmbed embed with each. Run it inside the
image with networking disabled; every check must pass with zero requests::

    docker run --rm --network none arc53/docsgpt:latest \\
        python -m docsgpt.scripts.verify_offline

Exit status is non-zero on the first failure. Models to check default to
the prefetch defaults; pass registry names to check a different set.
"""

from __future__ import annotations

import logging
import socket
import sys
import time
from typing import Callable, List, Optional, Sequence

from docsgpt.core.optional_deps import is_available
from docsgpt.scripts.prefetch_models import DEFAULT_MODELS, TIKTOKEN_ENCODINGS
from docsgpt.vectorstore.model_registry import resolve

logger = logging.getLogger("verify_offline")


def _network_reachable(host: str = "huggingface.co", port: int = 443) -> bool:
    try:
        socket.create_connection((host, port), timeout=2).close()
        return True
    except OSError:
        return False


def _check(name: str, fn: Callable[[], object]) -> bool:
    started = time.time()
    try:
        detail = fn()
    except Exception as exc:  # noqa: BLE001 -- report every failure the same way
        print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
        return False
    print(f"ok    {name}: {detail} ({time.time() - started:.2f}s)")
    return True


def verify(models: Sequence[str]) -> bool:
    """Run every check; return whether all passed."""
    ok = True

    def tiktoken_check(encoding: str) -> Callable[[], object]:
        def run() -> object:
            import tiktoken

            return f"{len(tiktoken.get_encoding(encoding).encode('hello world'))} tokens"

        return run

    for encoding in TIKTOKEN_ENCODINGS:
        ok &= _check(f"tiktoken {encoding}", tiktoken_check(encoding))

    for name in models:
        spec = resolve(name)
        if spec is None or spec.provider != "fastembed":
            print(f"skip  {name}: not a local model")
            continue

        def tokenizer_check(model_name: str = name) -> object:
            from docsgpt.parser.tokenization import get_token_counter

            counter = get_token_counter(model_name)
            if counter.name == "cl100k_base":
                raise RuntimeError("tokenizer missing from the cache; chunking fell back to cl100k")
            return f"{counter.name}, {counter.count('The quick brown fox')} tokens"

        def embed_check(model_name: str = name) -> object:
            from docsgpt.vectorstore.embeddings_local import EmbeddingsWrapper

            vector = EmbeddingsWrapper(model_name).embed_query("hello")
            return f"dimension {len(vector)}"

        ok &= _check(f"tokenizer {name}", tokenizer_check)
        ok &= _check(f"embeddings {name}", embed_check)

    if is_available("docling"):
        ok &= _check("docling PDF conversion", _docling_check)
    else:
        print("skip  docling: not installed (slim image)")

    return ok


# A one-page PDF with a single text run; enough for the layout model to have
# something to look at.
_TINY_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 58>>stream\n"
    b"BT /F1 18 Tf 20 100 Td (Offline verification page) Tj ET\n"
    b"endstream\nendobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


def _docling_check() -> object:
    """Convert a tiny PDF through docling; its models must come from DOCLING_ARTIFACTS_PATH."""
    import os
    import tempfile

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    from docsgpt.parser.file.docling_parser import _apply_inference_settings

    # Same global docling settings the parser applies: torch.compile stays off
    # unless DOCLING_COMPILE_TORCH_MODELS asks for it (it needs a C++ toolchain).
    _apply_inference_settings()
    artifacts = os.environ.get("DOCLING_ARTIFACTS_PATH")
    options = PdfPipelineOptions(artifacts_path=artifacts, do_ocr=False, do_table_structure=True)
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(_TINY_PDF)
        path = handle.name
    try:
        text = converter.convert(path).document.export_to_markdown()
    finally:
        os.unlink(path)
    if "Offline verification" not in text:
        raise RuntimeError(f"unexpected conversion output: {text[:80]!r}")
    return f"models from {artifacts or 'default cache'}, {len(text)} chars"


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        prog="verify-offline", description="Check that the install serves its defaults without network access."
    )
    parser.add_argument(
        "models", nargs="*", help=f"embedding model names or aliases to check (default: {', '.join(DEFAULT_MODELS)})"
    )
    models: List[str] = parser.parse_args(argv).models or list(DEFAULT_MODELS)
    if _network_reachable():
        print("note  network is reachable; run with --network none to prove the offline path")
    else:
        print("note  network unreachable, as intended")
    passed = verify(models)
    print("VERIFY OFFLINE: " + ("PASS" if passed else "FAIL"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
