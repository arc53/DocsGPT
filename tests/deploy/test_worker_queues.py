"""Every shipped worker that names its queues must still take ingests.

A worker started without ``-Q`` consumes every queue in ``task_queues``. One
started with an explicit list consumes only that list, so a list that names
``docsgpt`` but not the ingest queue would leave every upload sitting in Redis
with nothing to run it, and nothing would report it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Shipped files that start a worker with an explicit queue list.
SHIPPED = sorted(
    [
        *ROOT.glob("deployment/**/*.yaml"),
        *ROOT.glob("deployment/**/*.yml"),
        ROOT / ".devcontainer" / "devc-welcome.md",
        ROOT / "scripts" / "e2e" / "up.sh",
    ]
)

# ``-Q docsgpt,parsing`` on a command line, or ``"-Q", "docsgpt,parsing"`` in a
# JSON-style argv list.
QUEUE_LIST = re.compile(r"""-Q["']?\s*,?\s*["']?([\w.-]+(?:,[\w.-]+)*)""")


def _queue_lists() -> Iterator:
    for path in SHIPPED:
        if not path.is_file():
            continue
        for match in QUEUE_LIST.finditer(path.read_text(encoding="utf-8")):
            queues = match.group(1).split(",")
            if "docsgpt" in queues:
                yield pytest.param(queues, id=f"{path.relative_to(ROOT)}:{','.join(queues)}")


@pytest.mark.unit
def test_shipped_files_name_their_queues() -> None:
    """Guard the guard: if the pattern stops matching, the test below checks nothing."""
    assert len(list(_queue_lists())) >= 5


@pytest.mark.unit
@pytest.mark.parametrize("queues", list(_queue_lists()))
def test_a_worker_on_the_default_queue_also_takes_ingests(queues: list[str]) -> None:
    from docsgpt.core.settings import settings

    assert settings.INGEST_QUEUE in queues
