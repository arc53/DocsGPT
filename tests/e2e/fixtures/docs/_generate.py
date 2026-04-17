#!/usr/bin/env python3
"""Regenerate e2e fixture documents.

Do not edit generated fixtures by hand. Run this script.

Usage (from repo root):
    .venv/bin/python tests/e2e/fixtures/docs/_generate.py

The script is deterministic and idempotent: running it twice produces
byte-identical output. No dates, UUIDs, or randomness are included in any
fixture. Content is intentionally stable so chunk-level assertions in e2e
specs remain reliable across runs.

Stdlib only. If ``reportlab`` is available we could use it for ``small.pdf``,
but we prefer the raw-bytes path to keep the fixture byte-stable regardless
of reportlab version drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# PDF helpers (raw bytes)
# ---------------------------------------------------------------------------


def _escape_pdf_text(text: str) -> str:
    """Escape characters that are special inside a PDF literal string."""
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _build_minimal_pdf(body_lines: list[str], extra_bytes: bytes = b"") -> bytes:
    """Build a valid single-page PDF containing ``body_lines`` of Helvetica text.

    Structure (5 objects + catalog/pages/page/font/contents):

        1 0 obj  Catalog
        2 0 obj  Pages
        3 0 obj  Page
        4 0 obj  Font (Helvetica)
        5 0 obj  Contents stream

    ``extra_bytes`` are injected as a PDF comment block right after the
    header. PDF comments (lines beginning with ``%`` up to EOL) are legal
    anywhere outside streams/strings and are treated as whitespace by every
    compliant parser. This is how we pad ``oversize.pdf`` without breaking
    validity.
    """
    # Build the content stream (page drawing instructions).
    # 72pt = 1 inch. Letter page = 612 x 792.
    y = 740
    stream_parts = ["BT", "/F1 12 Tf"]
    for i, line in enumerate(body_lines):
        if i == 0:
            stream_parts.append(f"72 {y} Td")
        else:
            stream_parts.append("0 -16 Td")
        stream_parts.append(f"({_escape_pdf_text(line)}) Tj")
    stream_parts.append("ET")
    content_stream = ("\n".join(stream_parts) + "\n").encode("ascii")

    # Build each object's bytes.
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Length " + str(len(content_stream)).encode("ascii") + b" >>\n"
            b"stream\n" + content_stream + b"endstream"
        ),
    ]

    out = bytearray()
    out += b"%PDF-1.4\n"
    # Binary marker comment recommended by the PDF spec for "binary" PDFs.
    out += b"%\xe2\xe3\xcf\xd3\n"

    if extra_bytes:
        out += extra_bytes

    offsets: list[int] = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("ascii")
        out += body
        out += b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")

    out += b"trailer\n"
    out += f"<< /Size {len(objs) + 1} /Root 1 0 R >>\n".encode("ascii")
    out += b"startxref\n"
    out += f"{xref_offset}\n".encode("ascii")
    out += b"%%EOF\n"

    return bytes(out)


# ---------------------------------------------------------------------------
# Fixture generators
# ---------------------------------------------------------------------------


SMALL_PDF_LINES = [
    "The Unicode Consortium was founded in January 1991.",
    "Its mission is to enable people around the world to use computers in any language.",
    "The consortium maintains the Unicode Standard, a text-encoding specification.",
    "Unicode assigns a unique code point to every character across modern scripts.",
    "Today the standard covers more than one hundred forty thousand characters.",
]


README_MD = """# Introduction to UTF-8 Encoding

UTF-8 is a variable-width character encoding capable of representing every
character in the Unicode standard. It was designed as a backward-compatible
replacement for ASCII, and it has become the dominant encoding for text on
the web and in most modern file formats.

## How UTF-8 Works

UTF-8 encodes each Unicode code point as one to four bytes. The number of
bytes used depends on the numeric value of the code point. Characters in the
ASCII range use a single byte identical to the ASCII byte, which is why any
valid ASCII text is also a valid UTF-8 text. Higher code points use a lead
byte that signals how many continuation bytes follow, and continuation bytes
always begin with the bit pattern ten.

The design has a number of useful properties. Byte boundaries cannot be
mistaken for character boundaries, because continuation bytes never look like
lead bytes. A corrupted or truncated stream can be resynchronised by scanning
forward to the next byte that is not a continuation byte. Sorting UTF-8
strings lexicographically by byte value produces the same order as sorting by
Unicode code point.

## Example

Below is a short Python snippet that encodes and decodes a UTF-8 string.

```python
text = "hello"
data = text.encode("utf-8")
again = data.decode("utf-8")
assert again == text
```

## Key Advantages

- Compact for Latin-script text, because ASCII characters use only one byte.
- Self-synchronising, which makes error recovery straightforward.
- A strict superset of ASCII, so legacy ASCII tools handle it gracefully.
- Well supported by every major programming language and operating system.
- Avoids the byte-order ambiguity that affects UTF-16 and UTF-32.

UTF-8 is recommended by the Internet Engineering Task Force as the default
encoding for web content, email headers, and most other text-based protocols.
Using it consistently across an application removes an entire class of
encoding-related bugs.
"""


NOTES_TXT = (
    "Notes on multilingual text handling.\n"
    "\n"
    "These notes illustrate a handful of typographic and script considerations\n"
    "that software dealing with international text must keep in mind. The\n"
    "examples intentionally mix several writing systems so that a parser can be\n"
    "exercised end to end.\n"
    "\n"
    "Latin script covers English, French, German, Spanish and many more. The\n"
    "em-dash \u2014 together with the en-dash \u2013 is used for pauses and\n"
    "ranges. Curly quotes such as \u201chello\u201d and \u2018world\u2019 are\n"
    "preferred in polished prose, while straight quotes remain common in\n"
    "source code. An ellipsis character \u2026 compresses three dots into a\n"
    "single glyph.\n"
    "\n"
    "Cyrillic script is used for Russian, Ukrainian, Bulgarian and several\n"
    "other languages. A short sample: \u041f\u0440\u0438\u0432\u0435\u0442,\n"
    "\u043c\u0438\u0440. \u042d\u0442\u043e \u043f\u0440\u043e\u0441\u0442\u043e\u0439\n"
    "\u0442\u0435\u0441\u0442\u043e\u0432\u044b\u0439 \u0442\u0435\u043a\u0441\u0442.\n"
    "\n"
    "CJK ideographs cover written Chinese, Japanese and Korean. A short\n"
    "sample of each: \u4f60\u597d\u4e16\u754c. \u3053\u3093\u306b\u3061\u306f\u4e16\u754c.\n"
    "\uc548\ub155\ud558\uc138\uc694 \uc138\uacc4.\n"
    "\n"
    "Punctuation worth noting includes the middle dot \u00b7, the section sign\n"
    "\u00a7, the pilcrow \u00b6 and the interrobang \u203d. A well-behaved text\n"
    "pipeline preserves each of these exactly, normalises line endings to a\n"
    "single convention, and never silently replaces characters it does not\n"
    "understand.\n"
)


def write_small_pdf(path: Path) -> None:
    path.write_bytes(_build_minimal_pdf(SMALL_PDF_LINES))


def write_readme(path: Path) -> None:
    path.write_text(README_MD, encoding="utf-8")


def write_notes(path: Path) -> None:
    path.write_text(NOTES_TXT, encoding="utf-8")


def write_corrupt_pdf(path: Path) -> None:
    # Header bytes that look like a PDF, then deterministic non-PDF garbage.
    # Do NOT include real PDF objects — this file must fail to parse.
    header = b"%PDF-1.4\n"
    garbage = (
        b"this is intentionally not a valid pdf body -- used for error-path "
        b"testing in the docsgpt e2e suite. no xref table, no objects, no "
        b"trailer. a compliant parser must reject this file.\n"
    ) * 8
    path.write_bytes(header + garbage)


def write_oversize_pdf(path: Path, target_bytes: int = 55 * 1024 * 1024) -> None:
    """Write a valid PDF padded to roughly ``target_bytes`` (default ~55 MB).

    The padding lives inside a PDF comment block placed immediately after the
    header. Comments are legal whitespace in PDF, so the file still parses.
    """
    # Build an unpadded reference PDF to measure overhead. We pad the
    # comment block so that the final file size matches target_bytes exactly.
    reference = _build_minimal_pdf(SMALL_PDF_LINES)
    overhead = len(reference)

    # Reserve space for the comment frame itself: "%" + "\n".
    # Each comment line is at most ~80 chars to stay friendly to parsers.
    # We compute a deterministic filler string of the exact needed length.
    #
    # NOTE: adding ``extra_bytes`` shifts every object offset, but since
    # _build_minimal_pdf recomputes the xref from actual offsets, the final
    # file remains valid. The only subtlety is that xref/startxref digit
    # widths change as the file grows; for a 55 MB file we're well within
    # the 10-digit xref offset format, so no length drift occurs.

    needed = max(0, target_bytes - overhead)
    # Build the filler as repeating 79-char comment lines + newline = 80 bytes.
    line_body = b"%" + b"x" * 78  # 79 bytes of comment content
    line = line_body + b"\n"  # 80 bytes per line
    num_full_lines = needed // len(line)
    remainder = needed - num_full_lines * len(line)

    filler = line * num_full_lines
    if remainder > 0:
        # Pad the tail with a shorter comment line so total byte count matches.
        # remainder is at least 2 here? Not necessarily — but it's always >= 0.
        # Shortest valid comment line is "%\n" (2 bytes). If remainder == 1,
        # we emit one extra byte into a preceding line instead.
        if remainder == 1:
            # Replace the last full line with an 81-byte version.
            if num_full_lines > 0:
                filler = line * (num_full_lines - 1) + b"%" + b"x" * 79 + b"\n"
            else:
                # Degenerate: just drop the last byte from the target.
                filler = b""
        else:
            tail_body_len = remainder - 2  # minus "%" and "\n"
            tail = b"%" + b"x" * tail_body_len + b"\n"
            filler += tail

    blob = _build_minimal_pdf(SMALL_PDF_LINES, extra_bytes=filler)
    path.write_bytes(blob)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    generators = [
        ("small.pdf", write_small_pdf),
        ("readme.md", write_readme),
        ("notes.txt", write_notes),
        ("corrupt.pdf", write_corrupt_pdf),
        ("oversize.pdf", write_oversize_pdf),
    ]

    for name, fn in generators:
        target = FIXTURES_DIR / name
        fn(target)
        size = target.stat().st_size
        print(f"wrote {name:<14} {size:>10} bytes", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
