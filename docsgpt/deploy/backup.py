"""The archive ``docsgpt backup`` writes and ``docsgpt restore`` reads.

One gzipped tar holds a SQL dump of the database, a tar per data volume, and a
manifest saying which version and image the backup came from. The settings file
is left out unless it is asked for: it holds the secrets.

``postgres_data`` is not tarred, because the dump is the database backup and a
copy of a running data directory would be a torn one. Caddy's volumes are left
out too: they hold certificates it obtains again on the next start.
"""

from __future__ import annotations

import io
import json
import tarfile
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Optional

from docsgpt.deploy.docker import DeployError

FORMAT = 1
MANIFEST = "manifest.json"
DUMP = "database.sql"
SETTINGS = "settings.env"
VOLUME_DIR = "volumes"
DATA_VOLUMES = ("indexes", "inputs", "vectors")


def archive_name(when: datetime) -> str:
    """The file name for a backup taken at ``when``."""
    return f"docsgpt-{when.strftime('%Y%m%d-%H%M%S')}.tar.gz"


def volume_member(name: str) -> str:
    """Where a volume's tar sits inside the archive."""
    return f"{VOLUME_DIR}/{name}.tar"


def write_archive(
    path: Path,
    *,
    dump: Path,
    volume_tars: Mapping[str, Path],
    manifest: Mapping[str, object],
    settings: Optional[Path] = None,
) -> None:
    """Write the backup archive; the manifest is added last so a truncated file has none."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        archive.add(dump, arcname=DUMP)
        for name, tar_path in sorted(volume_tars.items()):
            archive.add(tar_path, arcname=volume_member(name))
        if settings is not None:
            archive.add(settings, arcname=SETTINGS)
        body = json.dumps(dict(manifest), indent=2).encode("utf-8")
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(body)
        info.mtime = int(time.time())
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(body))


def read_manifest(path: Path) -> dict:
    """The archive's manifest, or a DeployError naming what is wrong with the file."""
    if not path.is_file():
        raise DeployError(f"{path} does not exist")
    try:
        with tarfile.open(path, "r:gz") as archive:
            member = archive.extractfile(MANIFEST)
            if member is None:
                raise KeyError(MANIFEST)
            manifest = json.loads(member.read().decode("utf-8"))
    except (tarfile.TarError, KeyError, ValueError, OSError) as exc:
        raise DeployError(f"{path} is not a DocsGPT backup: {exc}") from exc
    if not isinstance(manifest, dict) or "volumes" not in manifest:
        raise DeployError(f"{path} is not a DocsGPT backup: its manifest is missing what to restore")
    return manifest


def extract(path: Path, destination: Path) -> None:
    """Unpack the archive into ``destination`` (data filter: no paths outside it, no devices)."""
    with tarfile.open(path, "r:gz") as archive:
        archive.extractall(destination, filter="data")


def _parts(version: str) -> tuple[int, ...]:
    numbers = []
    for chunk in str(version).split("."):
        digits = "".join(character for character in chunk if character.isdigit())
        numbers.append(int(digits) if digits else 0)
    return tuple(numbers)


def check_version(manifest: Mapping[str, object], current: str, force: bool) -> None:
    """Refuse a backup from a newer DocsGPT: its data may not fit this version's schema."""
    taken_with = str(manifest.get("version") or "")
    if force or not taken_with:
        return
    if _parts(taken_with) > _parts(current):
        raise DeployError(
            f"this backup is from DocsGPT {taken_with}, newer than the installed {current}. "
            "Upgrade first with `docsgpt upgrade`, or pass --force to restore it anyway."
        )
