"""Normalize a command segment to its sticky-approval pattern.

Rule: head + first sub-token (when present), wildcard the rest.
  ``git checkout main -- file.txt``     -> ``git checkout *``
  ``npm install foo bar``               -> ``npm install *``
  ``ls -la /tmp``                       -> ``ls *``
  ``cat /etc/passwd``                   -> ``cat *``

Compound commands are normalized segment-by-segment and rejoined with
`` && ``, so a sticky only matches a command with the same normalized
segment sequence:
  ``ls /tmp && whoami``                 -> ``ls * && whoami``
"""

from __future__ import annotations

import shlex
from typing import Optional

from application.devices.splitter import split_command


# Commands whose first arg is a sub-command (so the pattern is "cmd subcmd *").
_TWO_WORD_HEADS = frozenset(
    {
        "git", "npm", "pnpm", "yarn", "pip", "uv", "poetry", "cargo",
        "docker", "kubectl", "brew", "apt", "apt-get", "dnf", "yum",
        "go", "rustup", "rustc", "make", "gradle", "mvn",
        "systemctl", "service",
    }
)


def normalize_segment(segment: str) -> str:
    """Reduce a segment to its sticky-pattern form.

    Args:
        segment: A single shell command segment (no compound connectors).

    Returns:
        Pattern like ``git checkout *``, ``ls *``, or just ``cat`` if the
        original had no args. Empty string for empty input.
    """
    if not segment or not segment.strip():
        return ""
    try:
        tokens = shlex.split(segment.strip(), posix=True)
    except ValueError:
        tokens = segment.strip().split()
    if not tokens:
        return ""

    head = tokens[0]

    if head in _TWO_WORD_HEADS and len(tokens) >= 2:
        subcmd = tokens[1]
        if len(tokens) > 2:
            return f"{head} {subcmd} *"
        return f"{head} {subcmd}"

    if len(tokens) > 1:
        return f"{head} *"
    return head


def normalize_command(command: str) -> Optional[str]:
    """Normalize an entire command into its joined sticky pattern.

    Every segment is normalized and the results are joined with `` && ``,
    so a compound command's sticky only matches a command with the same
    normalized segment sequence (approving ``ls /tmp && whoami`` won't
    auto-approve ``ls /tmp && rm /tmp/x``). Empty segments are skipped;
    returns ``None`` if there are no non-empty segments.
    """
    if not command:
        return None
    patterns = [
        normalize_segment(segment)
        for segment in split_command(command)
    ]
    patterns = [p for p in patterns if p]
    if not patterns:
        return None
    return " && ".join(patterns)
