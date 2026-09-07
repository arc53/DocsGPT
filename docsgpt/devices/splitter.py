"""Compound-command splitter for safety evaluation."""

from __future__ import annotations

import shlex
import re
from typing import List


# Splitters from spec 9.4: &&  ||  ;  |  &  |&  \n
# Order matters: longest first so e.g. ``|&`` doesn't get caught by ``|``.
_SPLITTER_RE = re.compile(r"\|\&|\&\&|\|\||;|\||\&|\n")

# Wrappers stripped before extracting the head token.
_WRAPPERS = frozenset({"timeout", "nice", "nohup", "stdbuf", "xargs", "env"})


def split_command(command: str) -> List[str]:
    """Split a command string on shell connectors.

    Each returned segment is a single "logical" command; the segments are
    independently evaluated against the hard denylist. ``env`` is
    intentionally in ``_WRAPPERS`` ONLY at the head position.

    Args:
        command: Raw shell command string.

    Returns:
        List of trimmed, non-empty segments.
    """
    if not command:
        return []
    parts = _SPLITTER_RE.split(command)
    return [p.strip() for p in parts if p and p.strip()]


def strip_wrappers(segment: str) -> str:
    """Return ``segment`` with leading command wrappers removed.

    ``timeout 30s rm -rf /`` → ``rm -rf /``; ``nice -n 5 rm -rf /`` →
    ``rm -rf /``. Wrappers and their own arguments (e.g. ``timeout 30s``,
    ``nice -n 5``) are dropped so safety checks see the real inner command.
    ``env`` is intentionally left in place so the denylist sees the head
    token rather than env assignments. Returns the original segment when
    there is nothing to strip or on a parse failure.
    """
    if not segment:
        return ""
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        # Unbalanced quotes — let callers fall back to the raw segment.
        return segment
    if not tokens:
        return ""
    i = _wrapper_offset(tokens)
    if i == 0:
        return segment
    return " ".join(tokens[i:])


def _wrapper_offset(tokens: List[str]) -> int:
    """Index of the first non-wrapper token (skipping wrapper args).

    ``env`` is treated as a non-wrapper so it is never stripped.
    """
    i = 0
    while i < len(tokens) and tokens[i] in _WRAPPERS and tokens[i] != "env":
        current = tokens[i]
        i += 1
        if i >= len(tokens):
            break
        # Skip wrapper-specific arguments before the wrapped command.
        if current == "timeout":
            # ``timeout 30`` or ``timeout 30s`` -- skip the duration token.
            if re.match(r"^\d+[smhd]?$", tokens[i]):
                i += 1
        elif current == "nice":
            # ``nice -n 10 cmd`` -- skip ``-n`` and its value.
            if tokens[i].startswith("-n"):
                i += 1
                if i < len(tokens) and re.match(r"^-?\d+$", tokens[i]):
                    i += 1
    return i


def head_token(segment: str) -> str:
    """Extract the head command token from a segment, stripping wrappers.

    ``timeout 30s ls`` → ``ls``. ``env X=Y cmd`` is NOT stripped here.
    """
    if not segment:
        return ""
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        # Unbalanced quotes — fall back to a naive split. Don't crash.
        tokens = segment.split()
    if not tokens:
        return ""
    i = _wrapper_offset(tokens)
    if i >= len(tokens):
        # Segment was only wrappers/args; nothing meaningful to return.
        return tokens[0]
    return tokens[i]


def head_tokens(command: str) -> List[str]:
    """Return the head token of every segment."""
    return [head_token(seg) for seg in split_command(command)]
