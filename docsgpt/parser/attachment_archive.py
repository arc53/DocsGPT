"""Unpack a zip attachment into its member files, within limits.

A zip attached to a chat becomes one attachment per member, each parsed like
a normal upload (``worker.attachment_worker``). This module only lists and
extracts: members are written under a private directory by a generated name,
never by their path inside the archive, so a crafted path cannot escape it.

Limits (``ATTACHMENT_ARCHIVE_*`` settings) apply to the whole tree, nested
archives included:

* an archive whose uncompressed size is out of proportion to its compressed
  size is rejected whole, as a zip bomb;
* members no parser can read (``accept``) are skipped before they count
  toward anything, so a ``.git/objects`` tree cannot use up the file limit;
* members past the member count, the per-file size or the total byte budget
  are skipped;
* every entry, nested archives and skipped ones included, counts toward the
  entry limit, and entries past it are skipped without being read;
* a zip inside the zip is unpacked under its own path (``inner.zip/a.csv``)
  down to the depth limit; deeper ones are skipped;
* unsafe paths, links and encrypted members are skipped.

Every skipped member is reported with a reason, so the model can tell the user
what was left out.
"""

from __future__ import annotations

import lzma
import os
import stat
import uuid
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Callable, List, Optional

from docsgpt.utils import safe_filename

# How each skip reason reads to the user (the zip's index and the manifest).
SKIP_REASON_TEXT = {
    "unsafe_path": "unsafe path",
    "encrypted": "encrypted",
    "unsupported_entry": "not a regular file",
    "unsupported_type": "unsupported file type",
    "too_many_files": "over the file limit",
    "file_too_large": "over the per-file size limit",
    "archive_too_large": "over the size limit",
    "nested_too_deep": "archive nested too deep",
    "corrupt": "damaged",
    "nested_archive_invalid": "unreadable archive",
}
# Skipped members kept with their path; the rest are only counted.
MAX_RECORDED_SKIPS = 100
_COPY_CHUNK_BYTES = 64 * 1024
# Head of a member handed to ``accept`` (the text sniff reads this much).
_HEAD_BYTES = 8192
# Archive tool metadata, not user files.
_JUNK_DIRS = frozenset({"__MACOSX"})
_JUNK_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
# What reading one damaged member can raise: a bad CRC or header
# (BadZipFile), a broken deflate / LZMA / bzip2 stream (zlib.error,
# LZMAError, OSError), a truncated one (EOFError), an unsupported compression
# method (NotImplementedError, a RuntimeError). Each is that member's problem
# only: it is skipped as damaged and the rest of the archive still unpacks.
_MEMBER_READ_ERRORS = (
    zipfile.BadZipFile,
    zlib.error,
    lzma.LZMAError,
    OSError,
    EOFError,
    RuntimeError,
    ValueError,
)


class ArchiveRejectedError(ValueError):
    """The archive as a whole is unreadable or a zip bomb.

    Attributes:
        reason: ``unreadable`` (not a readable zip) or ``zip_bomb``.
    """

    def __init__(self, message: str, reason: str = "unreadable") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ArchiveLimits:
    """Resource ceilings for unpacking one zip attachment.

    Attributes:
        max_members: Files unpacked across the whole tree.
        max_total_bytes: Uncompressed bytes unpacked across the whole tree.
        max_depth: Archive levels unpacked; 1 is the uploaded zip itself.
        max_ratio: Uncompressed-to-compressed ratio that rejects an archive.
        max_entries: Entries looked at across the whole tree, whatever
            becomes of them (nested archives and skipped members included).
        max_member_bytes: Uncompressed size of one member file.
    """

    max_members: int
    max_total_bytes: int
    max_depth: int
    max_ratio: int
    max_entries: int = 5000
    max_member_bytes: int = 100 * 1024 * 1024

    @classmethod
    def from_settings(cls) -> "ArchiveLimits":
        """The limits configured by the ``ATTACHMENT_ARCHIVE_*`` settings."""
        from docsgpt.core.settings import settings

        return cls(
            max_members=int(settings.ATTACHMENT_ARCHIVE_MAX_MEMBERS),
            max_total_bytes=int(settings.ATTACHMENT_ARCHIVE_MAX_BYTES),
            max_depth=int(settings.ATTACHMENT_ARCHIVE_MAX_DEPTH),
            max_ratio=int(settings.ATTACHMENT_ARCHIVE_MAX_RATIO),
            max_entries=int(settings.ATTACHMENT_ARCHIVE_MAX_ENTRIES),
            max_member_bytes=int(settings.UPLOAD_MAX_FILE_BYTES),
        )


@dataclass(frozen=True)
class ArchiveMember:
    """One unpacked file.

    Attributes:
        archive_path: Its path inside the archive (``dir/a.csv``,
            ``inner.zip/b.txt`` for a nested archive).
        filename: Its display name, the last path component.
        local_path: Where its bytes were written.
        size: Its size in bytes.
    """

    archive_path: str
    filename: str
    local_path: str
    size: int


@dataclass(frozen=True)
class SkippedMember:
    """A member that was not unpacked.

    Attributes:
        archive_path: Its path inside the archive, made safe to display.
        reason: A key of ``SKIP_REASON_TEXT`` (``unsupported_type`` is
            added by the worker, which knows the parsers).
    """

    archive_path: str
    reason: str


@dataclass
class ArchiveExpansion:
    """What came out of an archive.

    Attributes:
        members: The unpacked files, in archive order.
        skipped: Members left out, with their reasons (at most
            ``MAX_RECORDED_SKIPS``).
        skipped_count: All members left out, recorded or not.
        total_bytes: Bytes unpacked.
        entries: Entries looked at, against ``max_entries``.
    """

    members: List[ArchiveMember] = field(default_factory=list)
    skipped: List[SkippedMember] = field(default_factory=list)
    skipped_count: int = 0
    total_bytes: int = 0
    entries: int = 0

    def skip(self, archive_path: str, reason: str) -> None:
        """Record a member left out."""
        self.skipped_count += 1
        if len(self.skipped) < MAX_RECORDED_SKIPS:
            self.skipped.append(SkippedMember(archive_path=archive_path, reason=reason))


# Whether a member can be parsed: its filename, and a callable returning
# the first bytes of its content (read only when called).
AcceptMember = Callable[[str, Callable[[], bytes]], bool]


def expand_archive(
    path: str, dest_dir: str, limits: ArchiveLimits, accept: Optional[AcceptMember] = None
) -> ArchiveExpansion:
    """Unpack the zip at ``path`` into ``dest_dir``.

    Args:
        path: The uploaded zip.
        dest_dir: An existing private directory for the members' bytes.
        limits: The resource ceilings.
        accept: Whether a member can be parsed, by its filename and head;
            the ones it refuses are skipped as ``unsupported_type`` before
            they count toward the member and byte limits. Every member is
            accepted when omitted.

    Returns:
        The unpacked members and the skipped ones.

    Raises:
        ArchiveRejectedError: The file is not a readable zip, or is a zip bomb.
    """
    expansion = ArchiveExpansion()
    try:
        _expand_into(path, "", 1, os.path.realpath(dest_dir), limits, expansion, accept)
    except ArchiveRejectedError:
        raise
    except (zipfile.LargeZipFile, *_MEMBER_READ_ERRORS) as exc:
        raise ArchiveRejectedError(f"The zip file could not be read: {exc}") from exc
    return expansion


def _display_path(name: str) -> str:
    """A member name made safe to show: no control characters, bounded."""
    cleaned = "".join(ch if ch.isprintable() else "?" for ch in str(name))
    return cleaned[:300] or "?"


def _safe_relative_path(name: str) -> Optional[str]:
    """The member's normalized relative path, or None when it could escape."""
    if not name or "\x00" in name:
        return None
    normalized = name.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if (
        normalized.startswith("/")
        or not parts
        or any(part in ("", ".", "..") for part in parts)
        or parts[0].endswith(":")
    ):
        return None
    return "/".join(parts)


def _is_junk(relative_path: str) -> bool:
    parts = relative_path.split("/")
    return parts[0] in _JUNK_DIRS or parts[-1] in _JUNK_NAMES or parts[-1].startswith("._")


def _special_reason(info: zipfile.ZipInfo) -> Optional[str]:
    """Why a member cannot be unpacked as a plain file, if it cannot."""
    if info.flag_bits & 0x1:
        return "encrypted"
    file_type = stat.S_IFMT(info.external_attr >> 16)
    if file_type not in (0, stat.S_IFREG):
        return "unsupported_entry"
    return None


def _check_ratio(archive: zipfile.ZipFile, limits: ArchiveLimits, label: str) -> None:
    files = [info for info in archive.infolist() if not info.is_dir()]
    declared = sum(int(info.file_size) for info in files)
    compressed = sum(int(info.compress_size) for info in files)
    if declared and (compressed <= 0 or declared / compressed > limits.max_ratio):
        raise ArchiveRejectedError(
            f"{label} exceeds the {limits.max_ratio}:1 compression ratio limit and looks like a zip bomb.",
            reason="zip_bomb",
        )


def _read_head(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """The first ``_HEAD_BYTES`` of a member's content."""
    with archive.open(info, "r") as source:
        return source.read(_HEAD_BYTES)


def _extract_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: str) -> bool:
    """Copy one member to ``target``, never past its declared size."""
    written = 0
    with archive.open(info, "r") as source, open(target, "xb") as output:
        while True:
            chunk = source.read(_COPY_CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > info.file_size:
                return False
            output.write(chunk)
    return written == info.file_size


def _expand_into(
    source: str,
    prefix: str,
    depth: int,
    dest_dir: str,
    limits: ArchiveLimits,
    expansion: ArchiveExpansion,
    accept: Optional[AcceptMember],
) -> None:
    with zipfile.ZipFile(source, "r") as archive:
        _check_ratio(archive, limits, "The zip file" if not prefix else f"The nested archive {prefix.rstrip('/')}")
        for info in archive.infolist():
            if info.is_dir():
                continue
            expansion.entries += 1
            if expansion.entries > limits.max_entries:
                expansion.skip(prefix + _display_path(info.filename), "too_many_files")
                continue
            relative = _safe_relative_path(info.filename)
            if relative is None:
                expansion.skip(prefix + _display_path(info.filename), "unsafe_path")
                continue
            if _is_junk(relative):
                continue
            archive_path = prefix + relative
            reason = _special_reason(info)
            if reason:
                expansion.skip(archive_path, reason)
                continue
            is_nested = relative.lower().endswith(".zip")
            if is_nested and depth >= limits.max_depth:
                expansion.skip(archive_path, "nested_too_deep")
                continue
            filename = relative.rsplit("/", 1)[-1]
            if not is_nested:
                if int(info.file_size) > limits.max_member_bytes:
                    expansion.skip(archive_path, "file_too_large")
                    continue
                if accept is not None:
                    try:
                        accepted = accept(filename, lambda: _read_head(archive, info))
                    except _MEMBER_READ_ERRORS:
                        expansion.skip(archive_path, "corrupt")
                        continue
                    if not accepted:
                        expansion.skip(archive_path, "unsupported_type")
                        continue
                if len(expansion.members) >= limits.max_members:
                    expansion.skip(archive_path, "too_many_files")
                    continue
            if expansion.total_bytes + int(info.file_size) > limits.max_total_bytes:
                expansion.skip(archive_path, "archive_too_large")
                continue
            target = os.path.join(dest_dir, f"{uuid.uuid4().hex}_{safe_filename(filename)}")
            try:
                complete = _extract_member(archive, info, target)
            except _MEMBER_READ_ERRORS:
                complete = False
            if not complete:
                if os.path.exists(target):
                    os.unlink(target)
                expansion.skip(archive_path, "corrupt")
                continue
            expansion.total_bytes += int(info.file_size)
            if is_nested:
                try:
                    _expand_into(target, archive_path + "/", depth + 1, dest_dir, limits, expansion, accept)
                except ArchiveRejectedError:
                    # A zip bomb anywhere in the tree rejects the whole upload.
                    raise
                except (zipfile.LargeZipFile, *_MEMBER_READ_ERRORS):
                    expansion.skip(archive_path, "nested_archive_invalid")
                finally:
                    os.unlink(target)
                continue
            expansion.members.append(
                ArchiveMember(
                    archive_path=archive_path,
                    filename=filename,
                    local_path=target,
                    size=int(info.file_size),
                )
            )
