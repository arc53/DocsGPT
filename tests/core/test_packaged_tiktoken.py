"""The packaged cl100k_base ranks file must reach the working tree byte-exact.

``.gitattributes`` marks ``*.tiktoken`` as binary so Git never rewrites its line
endings. That attribute only governs *new* checkouts: a working tree cloned
before the attribute landed keeps its CRLF copy and must be re-checked out, with
the attribute already in place. This test guards the attribute and fails loudly
on a corrupted checkout instead of letting ingestion fail later with an
unrelated-looking checksum error.
"""

import hashlib

from docsgpt.utils import _CL100K_BASE_FILE, _CL100K_BASE_SHA256, num_tokens_from_string

_CHECKOUT_HINT = (
    "Git probably checked the file out with CRLF line endings (core.autocrlf=true on Windows). "
    ".gitattributes marks *.tiktoken binary, which only affects NEW checkouts. To repair an "
    "existing one, first get that attribute into the working tree, then run "
    "`git restore --source=HEAD --worktree -- <file>` (or use a fresh clone). Verify with "
    "`git check-attr text <file>`, which must report `unset` — `auto` means the attribute has "
    "not landed yet and the re-checkout would convert again."
)


def test_the_ranks_file_is_byte_exact() -> None:
    """CRLF conversion changes only this file's digest, never the Git blob."""
    actual = hashlib.sha256(_CL100K_BASE_FILE.read_bytes()).hexdigest()
    assert actual == _CL100K_BASE_SHA256, (
        f"{_CL100K_BASE_FILE} sha256 is {actual}, expected {_CL100K_BASE_SHA256}. {_CHECKOUT_HINT}"
    )


def test_the_packaged_encoding_loads() -> None:
    """Parsers, chunkers and TiktokenCounter all route through this call."""
    assert num_tokens_from_string("hello world") > 0
