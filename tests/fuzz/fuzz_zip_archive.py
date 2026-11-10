"""Fuzz bounded ZIP extraction of untrusted uploads (docsgpt.security.zip_archive).

Archives are built from the input (hostile member names, Unix modes,
encryption flags, nested archives) and then optionally corrupted byte by byte.

Invariants checked on every input:

* member-name normalization never returns an absolute, drive-letter or
  dot-segment path;
* metadata validation and extraction raise nothing but ``ZipExtractionError``,
  and extraction never accepts an archive the metadata check refused;
* a failed extraction leaves the destination as it was and no staging
  directory behind;
* a successful one writes only regular files and directories, all inside
  the destination, within the file-count and byte limits, and never
  replaces a file that was already there.
"""

from __future__ import annotations

import io
import os
import shutil
import stat
import sys
import tempfile
import warnings
import zipfile

import atheris

with atheris.instrument_imports():
    from docsgpt.security import zip_archive

_LIMITS = zip_archive.ZipExtractionLimits(
    max_uncompressed_bytes=64 * 1024,
    max_files=16,
    max_compression_ratio=50,
    max_member_bytes=32 * 1024,
    max_depth=2,
)
_NAME_PARTS = [
    "a", "A", "b.txt", "B.TXT", "..", ".", "", "/", "\\", "//", "C:", "c:\\", "x.zip", "X.ZIP",
    "\x00", "dir/", "ü", "u\u0308", " ", "con", "a (2)", "~", "%2e%2e",
]
_MODES = [
    0,
    stat.S_IFREG | 0o644,
    stat.S_IFDIR | 0o755,
    stat.S_IFLNK | 0o777,
    stat.S_IFIFO | 0o644,
    stat.S_IFCHR | 0o644,
    stat.S_IFSOCK | 0o644,
]
_PREEXISTING = "keep.txt"
# Duplicate member names are wanted here; zipfile warns on each one it writes.
warnings.filterwarnings("ignore", category=UserWarning, module="zipfile")
_ROOT = tempfile.mkdtemp(prefix="fuzz-zip-")


def _member_name(fdp: atheris.FuzzedDataProvider) -> str:
    """A member name stitched from hostile fragments and raw input."""
    pieces = []
    for _ in range(fdp.ConsumeIntInRange(1, 4)):
        if fdp.ConsumeIntInRange(0, 3) == 0:
            pieces.append(fdp.ConsumeUnicodeNoSurrogates(12))
        else:
            pieces.append(fdp.PickValueInList(_NAME_PARTS))
    return fdp.PickValueInList(["", "/"]).join(pieces)


def _build_zip(fdp: atheris.FuzzedDataProvider, depth: int) -> bytes:
    """Serialize an archive whose members are chosen by the input."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for _ in range(fdp.ConsumeIntInRange(0, 5)):
            info = zipfile.ZipInfo(_member_name(fdp))
            info.external_attr = fdp.PickValueInList(_MODES) << 16
            info.compress_type = fdp.PickValueInList([zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
            if depth < 2 and fdp.ConsumeIntInRange(0, 5) == 0:
                payload = _build_zip(fdp, depth + 1)
            elif fdp.ConsumeBool():
                payload = bytes([fdp.ConsumeIntInRange(0, 255)]) * fdp.ConsumeIntInRange(0, 40000)
            else:
                payload = fdp.ConsumeBytes(fdp.ConsumeIntInRange(0, 64))
            try:
                archive.writestr(info, payload)
            except (ValueError, UnicodeError):
                continue
            if fdp.ConsumeIntInRange(0, 15) == 0:
                # Claim encryption after the fact; the payload stays plain.
                archive.filelist[-1].flag_bits |= 0x1
    return buffer.getvalue()


def _corrupt(fdp: atheris.FuzzedDataProvider, blob: bytes) -> bytes:
    """Overwrite a few bytes of ``blob`` at offsets the input picks."""
    if not blob:
        return blob
    mutable = bytearray(blob)
    for _ in range(fdp.ConsumeIntInRange(0, 4)):
        mutable[fdp.ConsumeIntInRange(0, len(mutable) - 1)] = fdp.ConsumeIntInRange(0, 255)
    return bytes(mutable)


def _snapshot(root: str) -> dict[str, bytes | None]:
    """Relative path -> contents (``None`` for directories) of everything under ``root``."""
    seen: dict[str, bytes | None] = {}
    for current, directories, files in os.walk(root):
        for name in directories:
            seen[os.path.relpath(os.path.join(current, name), root)] = None
        for name in files:
            path = os.path.join(current, name)
            with open(path, "rb") as handle:
                seen[os.path.relpath(path, root)] = handle.read()
    return seen


def _check_member_paths(fdp: atheris.FuzzedDataProvider) -> None:
    """Member-name normalization never yields a path that escapes the extraction root."""
    name = _member_name(fdp)
    try:
        normalized = zip_archive._safe_member_path(name)
    except zip_archive.ZipExtractionError:
        return
    if not normalized:
        return  # "." or "./": the extraction root itself, which extraction never overwrites.
    parts = normalized.split("/")
    assert "\\" not in normalized and "\x00" not in normalized, (name, normalized)
    assert not normalized.startswith("/") and not parts[0].endswith(":"), (name, normalized)
    assert all(part not in ("", ".", "..") for part in parts), (name, normalized)


def TestOneInput(data: bytes) -> None:
    """Extract one generated archive and check the destination afterwards."""
    fdp = atheris.FuzzedDataProvider(data)
    _check_member_paths(fdp)

    blob = fdp.ConsumeBytes(4096) if fdp.ConsumeIntInRange(0, 7) == 0 else _build_zip(fdp, 0)
    blob = _corrupt(fdp, blob) if fdp.ConsumeBool() else blob
    preexisting = fdp.ConsumeBool()

    work = tempfile.mkdtemp(dir=_ROOT)
    try:
        source = os.path.join(work, "upload.zip")
        with open(source, "wb") as handle:
            handle.write(blob)
        destination = os.path.join(work, "out")
        if preexisting:
            os.makedirs(destination)
            with open(os.path.join(destination, _PREEXISTING), "wb") as handle:
                handle.write(b"original")
        before = _snapshot(destination) if preexisting else None

        try:
            zip_archive.validate_zip_archive(source, _LIMITS)
            metadata_ok = True
        except zip_archive.ZipExtractionError:
            metadata_ok = False

        try:
            budget = zip_archive.extract_zip_safely(source, destination, _LIMITS)
        except zip_archive.ZipExtractionError:
            if preexisting:
                assert _snapshot(destination) == before, "failed extraction changed the destination"
            else:
                assert not os.path.lexists(destination), "failed extraction left a destination behind"
            assert sorted(os.listdir(work)) == sorted(["upload.zip"] + (["out"] if preexisting else [])), (
                os.listdir(work)
            )
            return

        assert metadata_ok, "extraction accepted an archive whose metadata validation failed"
        assert sorted(os.listdir(work)) == ["out", "upload.zip"], os.listdir(work)
        real_root = os.path.realpath(destination)
        files = 0
        total = 0
        for current, directories, names in os.walk(destination):
            for name in directories + names:
                path = os.path.join(current, name)
                mode = os.lstat(path).st_mode
                assert stat.S_ISREG(mode) or stat.S_ISDIR(mode), path
                assert os.path.commonpath((real_root, os.path.realpath(path))) == real_root, path
            for name in names:
                files += 1
                total += os.path.getsize(os.path.join(current, name))
        if preexisting:
            files -= 1
            total -= len(b"original")
            with open(os.path.join(destination, _PREEXISTING), "rb") as handle:
                assert handle.read() == b"original", "extraction replaced an existing file"
        assert files <= _LIMITS.max_files and files <= budget.files, (files, budget)
        assert total <= _LIMITS.max_uncompressed_bytes and total <= budget.uncompressed_bytes, (total, budget)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    """Start the fuzzer."""
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
