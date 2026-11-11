"""Split the suite across CI jobs: ``pytest --shard 2/3`` runs the second third.

A shard is a set of test files. Files, not tests, are dealt out, so a module's
fixtures are built in one job only. Every job collects the same tests and
deals them the same way (largest file first, each to the lightest shard so
far), so the shards are disjoint, cover the suite and hold about the same
number of tests without any job knowing what the others did.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable


def parse_shard(value: str) -> tuple[int, int]:
    """Read ``--shard``'s ``INDEX/TOTAL``.

    Args:
        value: The option as given, such as ``"2/3"``.

    Returns:
        The one-based shard index and the number of shards.

    Raises:
        ValueError: The value is not ``INDEX/TOTAL`` with ``1 <= INDEX <= TOTAL``.
    """
    try:
        index, total = (int(part) for part in value.split("/"))
    except ValueError:
        raise ValueError(f"--shard takes INDEX/TOTAL such as 2/3, not {value!r}") from None
    if not 1 <= index <= total:
        raise ValueError(f"--shard {value}: INDEX must be between 1 and TOTAL")
    return index, total


def assign_shards(files: Iterable[str], total: int) -> dict[str, int]:
    """Deal test files out to shards of about equal test counts.

    Args:
        files: The file of each collected test, one entry per test.
        total: The number of shards.

    Returns:
        The one-based shard of every file.
    """
    counts = Counter(files)
    loads = [0] * total
    shards: dict[str, int] = {}
    # Largest first; ties (and so the whole deal) are settled by name.
    for file, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lightest = min(range(total), key=lambda shard: (loads[shard], shard))
        loads[lightest] += count
        shards[file] = lightest + 1
    return shards
