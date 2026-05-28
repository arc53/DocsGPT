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
    head = tokens[0]
    # Strip leading wrappers; stop at the first non-wrapper. ``timeout 30s ls``
    # has token[0] = ``timeout`` and token[1] = ``30s``; ``ls`` is at [2].
    i = 0
    while head in _WRAPPERS and head != "env":
        # ``env`` is special — leave it unstripped so the denylist sees the
        # real head token.
        current = tokens[i]
        i += 1
        if i >= len(tokens):
            break
        # Skip wrapper-specific arguments before the wrapped command.
        if current == "timeout":
            # ``timeout 30`` or ``timeout 30s`` -- skip the duration token.
            if re.match(r"^\d+[smhd]?$", tokens[i]):
                i += 1
                if i >= len(tokens):
                    break
        elif current == "nice":
            # ``nice -n 10 cmd`` -- skip ``-n`` and its value.
            if tokens[i].startswith("-n"):
                i += 1
                if i < len(tokens) and re.match(r"^-?\d+$", tokens[i]):
                    i += 1
                if i >= len(tokens):
                    break
        head = tokens[i]
    return head


def head_tokens(command: str) -> List[str]:
    """Return the head token of every segment."""
    return [head_token(seg) for seg in split_command(command)]
