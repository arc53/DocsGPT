"""The archive ``docsgpt backup`` writes and ``docsgpt restore`` reads.

One gzipped tar holds a SQL dump of the database, a tar per data volume, and a
manifest saying which version and image the backup came from. The settings file
is left out unless it is asked for: it holds the secrets.

``postgres_data`` is not tarred, because the dump is the database backup and a
copy of a running data directory would be a torn one. Caddy's volumes are left
out too: they hold certificates it obtains again on the next start. When user
accounts are on, the Keycloak database in the same Postgres is dumped beside
the main one (``databases/keycloak.sql``), and the manifest lists it.
"""

from __future__ import annotations

import io
import json
import os
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
# Databases besides the main one that a backup may hold, each dumped on its own.
EXTRA_DATABASES = ("keycloak",)


def archive_name(when: datetime) -> str:
    """The file name for a backup taken at ``when``."""
    return f"docsgpt-{when.strftime('%Y%m%d-%H%M%S')}.tar.gz"


def volume_member(name: str) -> str:
    """Where a volume's tar sits inside the archive."""
    return f"{VOLUME_DIR}/{name}.tar"


def database_member(name: str) -> str:
    """Where the dump of one of the :data:`EXTRA_DATABASES` sits inside the archive."""
    return f"databases/{name}.sql"


def write_archive(
    path: Path,
    *,
    dump: Path,
    volume_tars: Mapping[str, Path],
    manifest: Mapping[str, object],
    settings: Optional[Path] = None,
    databases: Optional[Mapping[str, Path]] = None,
) -> None:
    """Write the backup archive; the manifest is added last so a truncated file has none."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # 0600 from the start: the dump is the install's data, and --with-settings adds its secrets.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "wb") as handle, tarfile.open(fileobj=handle, mode="w:gz") as archive:
        archive.add(dump, arcname=DUMP)
        for name, tar_path in sorted(volume_tars.items()):
            archive.add(tar_path, arcname=volume_member(name))
        for name, dump_path in sorted((databases or {}).items()):
            archive.add(dump_path, arcname=database_member(name))
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


def validate(path: Path, manifest: Mapping[str, object]) -> list[str]:
    """The volumes to restore, once the archive is known to hold everything it declares.

    Checked before the stack is stopped: a damaged or hand-made archive must fail while DocsGPT is
    still running, not after ``docker compose down``. Only the volumes a backup is made of are
    accepted, so a manifest cannot name ``postgres_data`` and have it emptied on the way in.
    """
    volumes = manifest.get("volumes")
    if not isinstance(volumes, list) or not all(isinstance(name, str) for name in volumes):
        raise DeployError(f"{path} is not a DocsGPT backup: its manifest does not list the volumes it holds")
    unsupported = sorted(set(volumes) - set(DATA_VOLUMES))
    if unsupported:
        raise DeployError(
            f"{path} names volumes that are not part of a backup: {', '.join(unsupported)}. "
            f"A DocsGPT backup holds {', '.join(DATA_VOLUMES)}."
        )
    databases = extra_databases(path, manifest)
    required = [DUMP, *(volume_member(name) for name in volumes), *(database_member(name) for name in databases)]
    try:
        with tarfile.open(path, "r:gz") as archive:
            present = {member.name for member in archive.getmembers() if member.isfile()}
    except (tarfile.TarError, OSError) as exc:
        raise DeployError(f"{path} is not a DocsGPT backup: {exc}") from exc
    missing = [name for name in required if name not in present]
    if missing:
        raise DeployError(f"{path} is missing {', '.join(missing)}, so there is nothing to restore from")
    return list(volumes)


def extra_databases(path: Path, manifest: Mapping[str, object]) -> list[str]:
    """The databases besides the main one that the archive holds, as its manifest lists them.

    Only the :data:`EXTRA_DATABASES` are accepted, so a manifest cannot name the main database
    (or ``postgres``) and have it replaced on the way in. Backups from before these existed list
    none.
    """
    databases = manifest.get("databases", [])
    if not isinstance(databases, list) or not all(isinstance(name, str) for name in databases):
        raise DeployError(f"{path} is not a DocsGPT backup: its manifest does not list the databases it holds")
    unsupported = sorted(set(databases) - set(EXTRA_DATABASES))
    if unsupported:
        raise DeployError(
            f"{path} names databases that are not part of a backup: {', '.join(unsupported)}. "
            f"Besides the main one, a DocsGPT backup may hold {', '.join(EXTRA_DATABASES)}."
        )
    return list(databases)


def check_volume_tar(name: str, path: Path) -> None:
    """Read a volume tar through, so a damaged one is found before any volume is replaced."""
    try:
        with tarfile.open(path, "r:*") as archive:
            for _ in archive:
                pass
    except (tarfile.TarError, OSError) as exc:
        raise DeployError(f"the {name} volume in this backup is damaged: {exc}") from exc


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
