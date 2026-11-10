"""Fuzz browser-origin parsing (docsgpt.security.origins).

Stored CORS / embed origins and request ``Origin`` headers are compared by
plain string equality, so both sides must land on one canonical form.

Invariants checked on every input:

* ``normalize_origin`` and ``request_origin`` never raise;
* ``canonical_origin`` raises nothing but ``ValueError``;
* every origin returned is ``http(s)://host[:port]`` with no path, query,
  fragment or credentials, and normalizing it again returns it unchanged
  (unless its host carries spaces or control characters);
* an accepted ``canonical_origin`` is a lowercase ASCII host (or bracketed
  IPv6 literal) and is a fixed point of both functions, so a stored entry
  matches the header a browser would send.
"""

from __future__ import annotations

import re
import sys

import atheris

with atheris.instrument_imports():
    from docsgpt.security import origins

# Lenient parsing keeps whatever host urlsplit found; the strict form allows only what a browser sends.
_SHAPE = re.compile(r"https?://[^/?#@]+")
_CANONICAL_SHAPE = re.compile(r"https?://(\[[^\]/?#@\s]+\]|[a-z0-9_-]+(\.[a-z0-9_-]+)*\.?)(:[0-9]+)?")
_SCHEMES = ["http", "https", "HTTPS", "ftp", "", "javascript", "null"]
_HOSTS = [
    "example.com", "Example.COM.", "localhost", "127.0.0.1", "[::1]", "[::ffff:1.2.3.4]", "bücher.example",
    "xn--bcher-kva.example", "*.example.com", "a..b", "-a-.b", "user:pw@host", "[fe80::1%25en0]", "ex ample",
    "é", "ＥＸＡＭＰＬＥ.com", "",
]
_TAILS = ["", "/", "//", "/path", "?q", "#f", ":", ":80", ":443", ":0", ":65535", ":65536", ":-1", ":+80", ": 80", "\\"]


def _origin_text(fdp: atheris.FuzzedDataProvider) -> str:
    """An origin-like string assembled from tricky pieces, or raw input."""
    if fdp.ConsumeIntInRange(0, 3) == 0:
        return fdp.ConsumeUnicodeNoSurrogates(128)
    pieces = [fdp.PickValueInList(_SCHEMES), fdp.PickValueInList(["://", ":/", ":", "//", ":///"])]
    for _ in range(fdp.ConsumeIntInRange(1, 3)):
        if fdp.ConsumeIntInRange(0, 3) == 0:
            pieces.append(fdp.ConsumeUnicodeNoSurrogates(12))
        else:
            pieces.append(fdp.PickValueInList(_HOSTS))
    pieces.append(fdp.PickValueInList(_TAILS))
    if fdp.ConsumeBool():
        pieces.append(fdp.PickValueInList(_TAILS))
    text = "".join(pieces)
    return f" {text}\t" if fdp.ConsumeIntInRange(0, 7) == 0 else text


def _check_origin(origin: str | None, source: str) -> None:
    """An origin is well-shaped and a fixed point of ``normalize_origin``."""
    if origin is None:
        return
    assert _SHAPE.fullmatch(origin), (source, origin)
    if origin != origin.strip() or any(ch < " " or ch == "\x7f" for ch in origin):
        # normalize_origin strips (Unicode) whitespace from the ends of its input,
        # so a garbage host ending in some shortens on a second pass; browsers
        # never send one.
        return
    assert origins.normalize_origin(origin) == origin, (source, origin, origins.normalize_origin(origin))


def TestOneInput(data: bytes) -> None:
    """Run all three parsers on generated origins and compare their answers."""
    fdp = atheris.FuzzedDataProvider(data)
    first = _origin_text(fdp)
    second = _origin_text(fdp)

    normalized = origins.normalize_origin(first)
    _check_origin(normalized, first)

    headers: dict[str, str] = {}
    if fdp.ConsumeBool():
        headers[fdp.PickValueInList(["Origin", "origin"])] = fdp.PickValueInList([first, "null", " null ", ""])
    if fdp.ConsumeBool():
        headers[fdp.PickValueInList(["Referer", "referer"])] = second
    from_request = origins.request_origin(headers)
    _check_origin(from_request, repr(headers))
    assert from_request in (None, origins.normalize_origin(first), origins.normalize_origin(second)), headers

    try:
        canonical = origins.canonical_origin(first)
    except ValueError:
        return
    assert canonical.isascii() and _CANONICAL_SHAPE.fullmatch(canonical), (first, canonical)
    _check_origin(canonical, first)
    assert origins.canonical_origin(canonical) == canonical, (first, canonical)


def main() -> None:
    """Start the fuzzer."""
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
