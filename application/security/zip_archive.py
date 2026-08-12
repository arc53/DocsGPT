"""Safe, bounded extraction for untrusted ZIP archives."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath


_COPY_CHUNK_BYTES = 64 * 1024
_MAX_MEMBER_NAME_BYTES = 4096
_MAX_MEMBER_DEPTH = 64


class ZipExtractionError(ValueError):
    """Raised when a ZIP is invalid or exceeds an extraction safety limit."""


@dataclass(frozen=True)
class ZipExtractionLimits:
    """Resource ceilings for one extraction tree."""

    max_uncompressed_bytes: int
    max_files: int
    max_compression_ratio: int
    max_member_bytes: int | None = None
    max_depth: int = 3


@dataclass
class ZipExtractionBudget:
    """Cumulative resources reserved across nested archives."""

    uncompressed_bytes: int = 0
    files: int = 0


@dataclass(frozen=True)
class _ValidatedMember:
    info: zipfile.ZipInfo
    relative_path: str


def _collision_safe_member_path(
    relative_path: str,
    assignments: dict[tuple[tuple[str, ...], str], str],
    occupied_names: dict[tuple[str, ...], set[str]],
) -> str:
    """Map case-colliding member components to stable, portable names."""
    original_parent: tuple[str, ...] = ()
    assigned_parent: tuple[str, ...] = ()
    assigned_parts: list[str] = []
    for component in relative_path.split("/"):
        assignment_key = (original_parent, component)
        assigned_component = assignments.get(assignment_key)
        if assigned_component is None:
            used = occupied_names.setdefault(assigned_parent, set())
            assigned_component = component
            suffix = 2
            stem, extension = os.path.splitext(component)
            while assigned_component.casefold() in used:
                assigned_component = f"{stem} ({suffix}){extension}"
                suffix += 1
            assignments[assignment_key] = assigned_component
            used.add(assigned_component.casefold())
        assigned_parts.append(assigned_component)
        original_parent += (component,)
        assigned_parent += (assigned_component,)
    return "/".join(assigned_parts)


def _safe_member_path(name: str) -> str:
    """Normalize a ZIP member name and reject paths escaping extraction."""
    if not name or "\x00" in name:
        raise ZipExtractionError("ZIP contains an invalid empty member name")
    if len(name.encode("utf-8", errors="surrogatepass")) > _MAX_MEMBER_NAME_BYTES:
        raise ZipExtractionError("ZIP member name exceeds the safety limit")

    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    parts = path.parts
    if (
        path.is_absolute()
        or normalized.startswith("//")
        or any(part in {"", ".", ".."} for part in parts)
        or (parts and parts[0].endswith(":"))
    ):
        raise ZipExtractionError(f"ZIP contains a path traversal attempt: {name}")
    if len(parts) > _MAX_MEMBER_DEPTH:
        raise ZipExtractionError("ZIP member path is nested too deeply")
    return "/".join(parts)


def _reject_special_member(info: zipfile.ZipInfo) -> None:
    """Reject symlinks and device-like Unix entries."""
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise ZipExtractionError(f"ZIP contains a special file: {info.filename}")
    if info.flag_bits & 0x1:
        raise ZipExtractionError("Encrypted ZIP members are not supported")


def _validate_members(
    archive: zipfile.ZipFile,
    limits: ZipExtractionLimits,
    budget: ZipExtractionBudget,
) -> tuple[list[_ValidatedMember], int, int]:
    members: list[_ValidatedMember] = []
    seen_paths: dict[str, bool] = {}
    component_assignments: dict[tuple[tuple[str, ...], str], str] = {}
    occupied_names: dict[tuple[str, ...], set[str]] = {}
    added_bytes = 0
    added_files = 0
    added_compressed_bytes = 0

    for info in archive.infolist():
        relative_path = _safe_member_path(info.filename)
        is_directory = info.is_dir()
        prior_is_directory = seen_paths.get(relative_path)
        if prior_is_directory is not None and not (
            prior_is_directory and is_directory
        ):
            raise ZipExtractionError(f"ZIP contains a duplicate path: {info.filename}")
        seen_paths[relative_path] = is_directory
        _reject_special_member(info)
        extraction_path = _collision_safe_member_path(
            relative_path, component_assignments, occupied_names
        )

        if is_directory:
            members.append(_ValidatedMember(info=info, relative_path=extraction_path))
            continue

        added_files += 1
        added_bytes += int(info.file_size)
        added_compressed_bytes += int(info.compress_size)
        if limits.max_member_bytes and info.file_size > limits.max_member_bytes:
            raise ZipExtractionError(
                "ZIP member exceeds the "
                f"{limits.max_member_bytes}-byte per-file limit"
            )
        if budget.files + added_files > limits.max_files:
            raise ZipExtractionError(
                f"ZIP contains too many files (>{limits.max_files})"
            )
        if budget.uncompressed_bytes + added_bytes > limits.max_uncompressed_bytes:
            raise ZipExtractionError(
                "ZIP extraction exceeds the "
                f"{limits.max_uncompressed_bytes}-byte expansion limit"
            )

        members.append(_ValidatedMember(info=info, relative_path=extraction_path))

    if added_bytes:
        if added_compressed_bytes <= 0:
            raise ZipExtractionError("ZIP has an invalid compression ratio")
        ratio = added_bytes / added_compressed_bytes
        if ratio > limits.max_compression_ratio:
            raise ZipExtractionError(
                "ZIP exceeds the "
                f"{limits.max_compression_ratio}:1 compression ratio limit"
            )

    return members, added_bytes, added_files


def validate_zip_archive(
    zip_path: str | os.PathLike[str],
    limits: ZipExtractionLimits,
    budget: ZipExtractionBudget | None = None,
) -> None:
    """Validate central-directory metadata without extracting any content."""
    active_budget = budget or ZipExtractionBudget()
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            _validate_members(archive, limits, active_budget)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ZipExtractionError(f"Invalid or corrupted ZIP file: {exc}") from exc


def _extract_archive_into(
    zip_path: str | os.PathLike[str],
    destination_root: str,
    limits: ZipExtractionLimits,
    budget: ZipExtractionBudget,
) -> list[str]:
    """Extract one validated archive into a private staging directory."""
    extracted_files: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as archive:
        members, added_bytes, added_files = _validate_members(
            archive, limits, budget
        )

        # Reserve declared resources before decompression so nested callers
        # cannot reset the allowance between layers.
        budget.uncompressed_bytes += added_bytes
        budget.files += added_files

        for member in members:
            target = os.path.realpath(
                os.path.join(destination_root, *member.relative_path.split("/"))
            )
            try:
                inside_destination = (
                    os.path.commonpath((destination_root, target))
                    == destination_root
                )
            except ValueError as exc:
                raise ZipExtractionError(
                    f"ZIP contains a path traversal attempt: {member.info.filename}"
                ) from exc
            if not inside_destination:
                raise ZipExtractionError(
                    "ZIP contains a path traversal attempt: "
                    f"{member.info.filename}"
                )
            if member.info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            if os.path.lexists(target):
                raise ZipExtractionError(
                    f"ZIP member would overwrite an existing path: {member.info.filename}"
                )

            os.makedirs(os.path.dirname(target), exist_ok=True)
            written = 0
            with archive.open(member.info, "r") as source, open(target, "xb") as output:
                while True:
                    chunk = source.read(_COPY_CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > member.info.file_size:
                        raise ZipExtractionError(
                            "ZIP member expanded past its declared size: "
                            f"{member.info.filename}"
                        )
                    output.write(chunk)
            if written != member.info.file_size:
                raise ZipExtractionError(
                    f"ZIP member size did not match metadata: {member.info.filename}"
                )
            extracted_files.append(target)
    return extracted_files


def _extract_tree_into(
    zip_path: str | os.PathLike[str],
    destination_root: str,
    limits: ZipExtractionLimits,
    budget: ZipExtractionBudget,
    depth: int,
) -> None:
    """Extract an archive and recursively expand nested ``.zip`` members."""
    extracted_files = _extract_archive_into(
        zip_path, destination_root, limits, budget
    )
    for extracted_path in extracted_files:
        if not extracted_path.lower().endswith(".zip"):
            continue
        if not zipfile.is_zipfile(extracted_path):
            continue
        if depth >= limits.max_depth:
            raise ZipExtractionError(
                f"ZIP nesting exceeds the {limits.max_depth}-level limit"
            )
        parent = os.path.dirname(extracted_path)
        stem = os.path.splitext(os.path.basename(extracted_path))[0] or "archive"
        occupied_names = {name.casefold() for name in os.listdir(parent)}
        nested_name = stem
        suffix = 2
        while nested_name.casefold() in occupied_names:
            nested_name = f"{stem} ({suffix})"
            suffix += 1
        nested_root = os.path.join(parent, nested_name)
        os.makedirs(nested_root)
        _extract_tree_into(
            extracted_path,
            nested_root,
            limits,
            budget,
            depth + 1,
        )
        os.remove(extracted_path)


def _commit_staging(staging_root: str, destination_root: str) -> None:
    """Commit a complete staging tree, rolling back an interrupted merge."""
    if not os.path.lexists(destination_root):
        os.replace(staging_root, destination_root)
        return
    if not os.path.isdir(destination_root):
        raise ZipExtractionError("ZIP extraction destination is not a directory")

    staged_directories: list[tuple[str, str]] = []
    staged_files: list[tuple[str, str]] = []
    for root, directories, files in os.walk(staging_root):
        relative_root = os.path.relpath(root, staging_root)
        destination_directory = (
            destination_root
            if relative_root == "."
            else os.path.join(destination_root, relative_root)
        )
        for directory in directories:
            source = os.path.join(root, directory)
            target = os.path.join(destination_directory, directory)
            if os.path.lexists(target) and not os.path.isdir(target):
                raise ZipExtractionError(
                    "ZIP member would overwrite an existing path"
                )
            staged_directories.append((source, target))
        for filename in files:
            source = os.path.join(root, filename)
            target = os.path.join(destination_directory, filename)
            if os.path.lexists(target):
                raise ZipExtractionError(
                    "ZIP member would overwrite an existing path"
                )
            staged_files.append((source, target))

    created_directories: list[str] = []
    moved_files: list[str] = []
    try:
        for _, target in staged_directories:
            if not os.path.isdir(target):
                os.makedirs(target)
                created_directories.append(target)
        for source, target in staged_files:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(source, target)
            moved_files.append(target)
    except Exception:
        for target in reversed(moved_files):
            try:
                os.remove(target)
            except OSError:
                pass
        for target in reversed(created_directories):
            try:
                os.rmdir(target)
            except OSError:
                pass
        raise


def extract_zip_safely(
    zip_path: str | os.PathLike[str],
    extract_to: str | os.PathLike[str],
    limits: ZipExtractionLimits,
    budget: ZipExtractionBudget | None = None,
) -> ZipExtractionBudget:
    """Transactionally extract a ZIP tree under cumulative resource limits.

    Nested ``.zip`` members are expanded inside a private staging directory.
    The destination is changed only after every layer has passed validation
    and extraction, so a corrupt member cannot leave partial content behind.
    """
    active_budget = budget or ZipExtractionBudget()
    destination_root = os.path.realpath(extract_to)
    destination_parent = os.path.dirname(destination_root)
    staging_root: str | None = None

    try:
        os.makedirs(destination_parent, exist_ok=True)
        staging_root = tempfile.mkdtemp(
            prefix=".zip-extract-", dir=destination_parent
        )
        _extract_tree_into(zip_path, staging_root, limits, active_budget, depth=0)
        _commit_staging(staging_root, destination_root)
    except ZipExtractionError:
        raise
    except (
        OSError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as exc:
        raise ZipExtractionError(f"Unable to extract ZIP safely: {exc}") from exc
    finally:
        if staging_root is not None:
            shutil.rmtree(staging_root, ignore_errors=True)

    return active_budget


def safe_zip_error_message(error: BaseException | str, max_chars: int = 512) -> str:
    """Return a bounded, single-line representation safe for logs and JSON."""
    raw = str(error)
    escaped = "".join(
        f"\\x{ord(character):02x}"
        if ord(character) < 32 or 127 <= ord(character) <= 159
        else character
        for character in raw
    )
    if len(escaped) > max_chars:
        return f"{escaped[: max_chars - 3]}..."
    return escaped
