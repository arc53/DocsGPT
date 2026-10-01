"""Unpack a zip attachment into its member files, within limits.

A zip attached to a chat becomes one attachment per member, each parsed like
a normal upload (``worker.attachment_worker``). This module only lists and
extracts: members are written under a private directory by a generated name,
never by their path inside the archive, so a crafted path cannot escape it.

Limits (``ATTACHMENT_ARCHIVE_*`` settings) apply to the whole tree, nested
archives included:

* an archive whose uncompressed size is out of proportion to its compressed
  size is rejected whole, as a zip bomb;
* members past the member count or the total byte budget are skipped;
* a zip inside the zip is unpacked under its own path (``inner.zip/a.csv``)
  down to the depth limit; deeper ones are skipped;
* unsafe paths, links and encrypted members are skipped.

Every skipped member is reported with a reason, so the model can tell the user
what was left out.
"""

from __future__ import annotations

import os
import stat
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import List, Optional

from docsgpt.utils import safe_filename

# How each skip reason reads to the user (the zip's index and the manifest).
SKIP_REASON_TEXT = {
    "unsafe_path": "unsafe path",
    "encrypted": "encrypted",
    "unsupported_entry": "not a regular file",
    "unsupported_type": "unsupported file type",
    "too_many_files": "over the file limit",
    "archive_too_large": "over the size limit",
    "nested_too_deep": "archive nested too deep",
    "corrupt": "damaged",
    "nested_archive_invalid": "unreadable archive",
}
# Skipped members kept with their path; the rest are only counted.
MAX_RECORDED_SKIPS = 100
_COPY_CHUNK_BYTES = 64 * 1024
# Archive tool metadata, not user files.
_JUNK_DIRS = frozenset({"__MACOSX"})
_JUNK_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})


class ArchiveRejectedError(ValueError):
    """The archive as a whole is unreadable or a zip bomb."""


@dataclass(frozen=True)
class ArchiveLimits:
    """Resource ceilings for unpacking one zip attachment.

    Attributes:
        max_members: Files unpacked across the whole tree.
        max_total_bytes: Uncompressed bytes unpacked across the whole tree.
        max_depth: Archive levels unpacked; 1 is the uploaded zip itself.
        max_ratio: Uncompressed-to-compressed ratio that rejects an archive.
    """

    max_members: int
    max_total_bytes: int
    max_depth: int
    max_ratio: int

    @classmethod
    def from_settings(cls) -> "ArchiveLimits":
        """The limits configured by the ``ATTACHMENT_ARCHIVE_*`` settings."""
        from docsgpt.core.settings import settings

        return cls(
            max_members=int(settings.ATTACHMENT_ARCHIVE_MAX_MEMBERS),
            max_total_bytes=int(settings.ATTACHMENT_ARCHIVE_MAX_BYTES),
            max_depth=int(settings.ATTACHMENT_ARCHIVE_MAX_DEPTH),
            max_ratio=int(settings.ATTACHMENT_ARCHIVE_MAX_RATIO),
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
    """

    members: List[ArchiveMember] = field(default_factory=list)
    skipped: List[SkippedMember] = field(default_factory=list)
    skipped_count: int = 0
    total_bytes: int = 0

    def skip(self, archive_path: str, reason: str) -> None:
        """Record a member left out."""
        self.skipped_count += 1
        if len(self.skipped) < MAX_RECORDED_SKIPS:
            self.skipped.append(SkippedMember(archive_path=archive_path, reason=reason))


def expand_archive(path: str, dest_dir: str, limits: ArchiveLimits) -> ArchiveExpansion:
    """Unpack the zip at ``path`` into ``dest_dir``.

    Args:
        path: The uploaded zip.
        dest_dir: An existing private directory for the members' bytes.
        limits: The resource ceilings.

    Returns:
        The unpacked members and the skipped ones.

    Raises:
        ArchiveRejectedError: The file is not a readable zip, or is a zip bomb.
    """
    expansion = ArchiveExpansion()
    try:
        _expand_into(path, "", 1, os.path.realpath(dest_dir), limits, expansion)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError) as exc:
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
            f"{label} exceeds the {limits.max_ratio}:1 compression ratio limit and looks like a zip bomb."
        )


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
) -> None:
    with zipfile.ZipFile(source, "r") as archive:
        _check_ratio(archive, limits, "The zip file" if not prefix else f"The nested archive {prefix.rstrip('/')}")
        for info in archive.infolist():
            if info.is_dir():
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
            if not is_nested and len(expansion.members) >= limits.max_members:
                expansion.skip(archive_path, "too_many_files")
                continue
            if expansion.total_bytes + int(info.file_size) > limits.max_total_bytes:
                expansion.skip(archive_path, "archive_too_large")
                continue
            filename = relative.rsplit("/", 1)[-1]
            target = os.path.join(dest_dir, f"{uuid.uuid4().hex}_{safe_filename(filename)}")
            try:
                complete = _extract_member(archive, info, target)
            except (zipfile.BadZipFile, OSError, RuntimeError, ValueError, EOFError):
                complete = False
            if not complete:
                if os.path.exists(target):
                    os.unlink(target)
                expansion.skip(archive_path, "corrupt")
                continue
            expansion.total_bytes += int(info.file_size)
            if is_nested:
                try:
                    _expand_into(target, archive_path + "/", depth + 1, dest_dir, limits, expansion)
                except zipfile.BadZipFile:
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
