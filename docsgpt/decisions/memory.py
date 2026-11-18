"""The load-time memory guard: refuse to load the decision model where it could get the process OOM-killed.

Headroom is the limit minus ``anon + active_file``, not minus ``memory.current``: the latter counts page cache the
kernel would reclaim, which made the cgroup counters useless for this when the model was measured. Inactive file
pages are reclaimable and left out; active ones are counted, to stay conservative. Without a cgroup limit the
host's ``MemAvailable`` is used, and where neither exists (macOS) there is no check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

MB = 1024 * 1024
# cgroup v1 reports "no limit" as a page-rounded LONG_MAX
_NO_LIMIT = 1 << 60


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _stat(path: Path) -> dict[str, int]:
    text = _read(path) or ""
    out = {}
    for line in text.splitlines():
        name, _, value = line.partition(" ")
        if value.strip().isdigit():
            out[name] = int(value)
    return out


def _cgroup_headroom(root: Path) -> Optional[int]:
    v2 = root / "sys/fs/cgroup"
    limit = _read(v2 / "memory.max")
    if limit is not None:
        if not limit.isdigit():  # "max"
            return None
        stat = _stat(v2 / "memory.stat")
        return int(limit) - stat.get("anon", 0) - stat.get("active_file", 0)
    v1 = root / "sys/fs/cgroup/memory"
    limit = _read(v1 / "memory.limit_in_bytes")
    if limit is None or not limit.isdigit() or int(limit) >= _NO_LIMIT:
        return None
    stat = _stat(v1 / "memory.stat")
    return int(limit) - stat.get("total_rss", 0) - stat.get("total_active_file", 0)


def _available(root: Path) -> Optional[int]:
    for line in (_read(root / "proc/meminfo") or "").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    return None


def headroom_mb(root: Path = Path("/")) -> Optional[float]:
    """Memory this process could still take, in MB: the tighter of its cgroup's headroom and the host's.

    Args:
        root: Filesystem root to read ``/sys`` and ``/proc`` under (tests point it at a fake tree).

    Returns:
        The headroom, or ``None`` where it cannot be measured.
    """
    known = [b for b in (_cgroup_headroom(root), _available(root)) if b is not None]
    return min(known) / MB if known else None
