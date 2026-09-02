"""Trust checks for PDF text extraction.

anydoc silently drops text from fonts it cannot map to Unicode — seen with
non-embedded composite (Type0/CID) fonts relying on predefined CMaps, where
the EN/ZH NDA corpus file loses its whole Chinese column with no error, and
with Adobe-CNS1 fonts in HK legal PDFs where a valid ToUnicode exists but
extraction still fails. These dependency-free checks scan the PDF's raw
objects (including Flate-compressed object streams) so the pipeline can
route such files to a heavier parser, or at least mark the output as
unverified, instead of trusting silent partial text.

Two stages:

* ``check_pdf_fonts`` — pre-flight on the bytes alone: composite fonts
  without an embedded ToUnicode CMap, and whether the PDF declares CJK font
  resources at all.
* ``verify_extraction`` — pre-flight plus the cross-check the font scan
  cannot do: a PDF that declares CJK fonts whose extracted text contains
  almost no CJK characters is not to be trusted.

A flag means "verify or route to a fallback", not "the text is wrong": tools
shipping Adobe's predefined CMaps (docling's parser does) often extract such
files fine. On the benchmark corpus the checks caught both known
silent-drop cases with zero false positives on the other 14 PDFs, and cost
~30 ms per scanned MB (92 ms on a 3 MB, 150-page annual report).
"""
import re
import zlib
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Union

_OBJ = re.compile(rb"\d+\s+\d+\s+obj(.*?)endobj", re.DOTALL)
_TYPE0 = re.compile(rb"/Subtype\s*/Type0")
# The CJK expectation is keyed on CIDSystemInfo /Ordering ALONE — the
# authoritative "this PDF maps text through a CJK character collection"
# signal, present in every known silent-drop case. Matching CJK font *names*
# (SimSun, MS-Gothic, MSungHK, ...) was tried and rejected: Word-exported
# Latin PDFs routinely embed an MS-Gothic subset for a stray full-width
# character (a 150-page English annual report in the benchmark corpus does),
# and substring matching also catches Latin faces like FranklinGothic —
# either way English-only documents would be rerouted to the heavy engine.
_CJK_ORDERING = re.compile(rb"/Ordering\s*\((GB1|CNS1|Japan1|Japan2|KR|Korea1)\)")
# Bytes kept around a Type0 marker found inside a decompressed object
# stream: object streams hold many dicts with no obj/endobj markers, and a
# font dict's keys sit close to its /Subtype entry.
_WINDOW_BEFORE, _WINDOW_AFTER = 200, 800

# Extracted text with fewer CJK characters than this, from a PDF that
# declares CJK fonts, is treated as a silent drop.
_MIN_CJK_CHARS = 10
_CJK_PROBLEM_PREFIX = "PDF declares CJK fonts"

_CJK_RANGES = (
    ("一", "鿿"),  # CJK Unified Ideographs
    ("぀", "ヿ"),  # Hiragana + Katakana
    ("가", "힯"),  # Hangul syllables
)


# Per-stream decompression cap. Flate reaches ~1000:1, so uncapped inflation
# of a crafted (or merely image-heavy) PDF inside the upload cap could balloon
# to gigabytes and OOM the ingest worker. Font dicts and object streams — the
# only things the signals live in — are far smaller than this.
_STREAM_INFLATE_CAP = 4_000_000


def _stream_bodies(raw: bytes) -> Iterator[bytes]:
    """The raw bytes between each ``stream`` / ``endstream`` keyword pair.

    A ``find`` walk rather than a regex: ``stream\\r?\\n(.*?)\\r?\\nendstream``
    misses every stream whose data runs straight into ``endstream`` with no
    EOL (common in the wild), and when it misses one its lazy group scans on
    to the *next* stream's terminator — quadratic on large files (a 10 MB
    file measured 32 s, matching a fifth of its streams) and a merged,
    undecodable body for the rest.
    """
    pos = 0
    while True:
        pos = raw.find(b"stream", pos)
        if pos < 0:
            return
        if raw[max(0, pos - 3):pos] == b"end":
            pos += 6
            continue
        start = pos + 6
        if raw[start:start + 2] == b"\r\n":
            start += 2
        elif raw[start:start + 1] in (b"\n", b"\r"):
            start += 1
        end = raw.find(b"endstream", start)
        if end < 0:
            return
        body = raw[start:end]
        if body.endswith(b"\r\n"):
            body = body[:-2]
        elif body.endswith((b"\n", b"\r")):
            body = body[:-1]
        pos = end + 9
        yield body


def _decompressed_streams(raw: bytes) -> Iterator[bytes]:
    """Each Flate stream in ``raw`` that decompresses, one at a time, capped."""
    for body in _stream_bodies(raw):
        try:
            inflated = zlib.decompressobj().decompress(body, _STREAM_INFLATE_CAP)
        except zlib.error:
            continue
        yield inflated


def _cjk_chars(text: str, up_to: int) -> int:
    """Count CJK characters in ``text``, stopping once ``up_to`` is reached."""
    count = 0
    for char in text:
        for low, high in _CJK_RANGES:
            if low <= char <= high:
                count += 1
                break
        if count >= up_to:
            break
    return count


def check_pdf_fonts(data: bytes) -> Dict[str, Union[int, bool]]:
    """Pre-flight font scan of a PDF's bytes.

    Args:
        data: The complete PDF file contents.

    Returns:
        Dict with ``type0`` (composite fonts seen), ``type0_no_tounicode``
        (those without an embedded ToUnicode CMap), ``expects_cjk`` (the PDF
        declares CJK font resources), ``has_fonts``, and ``flagged`` — True
        when extraction should not be trusted unverified.
    """
    type0 = bare = 0
    expects_cjk = bool(_CJK_ORDERING.search(data))
    has_fonts = b"/Font" in data

    def count_font(unit: bytes) -> None:
        """One analysis unit holding a Type0 font dict."""
        nonlocal type0, bare
        type0 += 1
        if b"/ToUnicode" not in unit:
            bare += 1

    for match in _OBJ.finditer(data):
        body = match.group(1)
        if _TYPE0.search(body):
            count_font(body)
    # Each decompressed stream is scanned for every signal in one pass and
    # then dropped; nothing inflated is retained past its loop iteration.
    for stream in _decompressed_streams(data):
        expects_cjk = expects_cjk or bool(_CJK_ORDERING.search(stream))
        has_fonts = has_fonts or b"/Font" in stream
        for type0_match in _TYPE0.finditer(stream):
            start = type0_match.start()
            count_font(stream[max(0, start - _WINDOW_BEFORE): start + _WINDOW_AFTER])
    return {
        "type0": type0,
        "type0_no_tounicode": bare,
        "expects_cjk": expects_cjk,
        "has_fonts": has_fonts,
        "flagged": bare > 0 or not has_fonts,
    }


def verify_extraction(data: bytes, markdown: str) -> List[str]:
    """Reasons the extracted ``markdown`` of the PDF ``data`` shouldn't be trusted.

    Combines the pre-flight font scan with the post-conversion cross-check it
    cannot do alone: fonts with a valid ToUnicode that the converter
    nevertheless failed to extract still show up as missing CJK output.

    Args:
        data: The complete PDF file contents.
        markdown: The text a converter extracted from it.

    Returns:
        Human-readable problem strings; empty when the output looks sound.
    """
    problems: List[str] = []
    result = check_pdf_fonts(data)
    if result["type0_no_tounicode"]:
        problems.append(
            f"{result['type0_no_tounicode']} composite (Type0) font(s) carry no "
            "ToUnicode map; extracted text may silently omit glyphs"
        )
    elif not result["has_fonts"]:
        problems.append(
            "no font resources detected; text extraction cannot be verified"
        )
    if result["expects_cjk"]:
        cjk = _cjk_chars(markdown, _MIN_CJK_CHARS)
        if cjk < _MIN_CJK_CHARS:
            problems.append(
                f"{_CJK_PROBLEM_PREFIX} but the extracted text contains only "
                f"{cjk} CJK character(s)"
            )
    return problems


def _text_layer_cjk_chars(file: Path, up_to: int) -> Optional[int]:
    """CJK characters in the text layer as pypdfium2 reads it, stopping at ``up_to``.

    pdfium ships Adobe's predefined CMaps, so it is an independent reference
    for whether the document *has* CJK text to lose. None when pypdfium2 is
    unavailable or the file cannot be read that way.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    try:
        pdf = pdfium.PdfDocument(str(file))
    except Exception:  # noqa: BLE001 - a reference probe, not a parse
        return None
    count = 0
    try:
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_bounded()
                finally:
                    textpage.close()
            finally:
                page.close()
            count += _cjk_chars(text, up_to - count)
            if count >= up_to:
                break
    except Exception:  # noqa: BLE001
        return None
    finally:
        pdf.close()
    return count


def verify_pdf_file(file: Path, markdown: str) -> List[str]:
    """``verify_extraction`` for a file on disk; unreadable files trust the output.

    The CJK cross-check is confirmed against pdfium's own text layer: a
    stray ``/Ordering (Japan1)`` in an otherwise Latin document (a 48-page
    Quartz export in the corpus carries one among 258 Identity fonts) is not
    a dropped Chinese column, and must not send the file to a full docling
    re-parse.
    """
    try:
        data = Path(file).read_bytes()
    except OSError:
        return []
    problems = verify_extraction(data, markdown)
    if any(problem.startswith(_CJK_PROBLEM_PREFIX) for problem in problems):
        reference = _text_layer_cjk_chars(Path(file), _MIN_CJK_CHARS)
        if reference is not None and reference < _MIN_CJK_CHARS:
            problems = [p for p in problems if not p.startswith(_CJK_PROBLEM_PREFIX)]
    return problems
