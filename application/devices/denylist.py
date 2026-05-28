"""Hard denylist — always triggers a forced prompt, even under ``never``."""

from __future__ import annotations

import re
import shlex
from typing import List, Optional, Tuple

from application.devices.splitter import split_command


# Label/reason for the rm-root wipe, shared by the regex rule and the
# token-based helper so both report identically.
_RM_ROOT_LABEL = "rm -rf /"

# Filesystem-root targets that, with recursive+force, mean a full wipe.
_RM_ROOT_TARGETS = frozenset({"/", "/*"})


# Each entry: (label, compiled regex). Regex is matched against each
# segment's whole text (case-insensitive, after whitespace normalization).
_PATTERNS: List[Tuple[str, re.Pattern]] = [
    (
        _RM_ROOT_LABEL,
        # ``rm`` with recursive+force targeting the filesystem root. Flags
        # (incl. ``--no-preserve-root``) may appear in any order before or
        # after the recursive/force flags; the target must be exactly ``/``
        # or ``/*`` so safe paths (``/tmp/foo``, ``./build``, ``/home/x``)
        # don't match. ``(?:-\S+\s+)*`` absorbs any extra leading options.
        re.compile(
            r"\brm\s+(?:-\S+\s+)*"
            r"(?:-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r"
            r"|--recursive\s+(?:-\S+\s+)*--force|--force\s+(?:-\S+\s+)*--recursive)"
            r"\s+(?:-\S+\s+)*/\*?\s*(?:$|\s)"
        ),
    ),
    (
        "rm -rf ~",
        re.compile(
            r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|-rf|-fr)\s+~"
        ),
    ),
    (
        "rm -rf $HOME",
        re.compile(
            r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|-rf|-fr)\s+\$HOME\b"
        ),
    ),
    (
        "fork bomb",
        re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
    ),
    (
        "dd to block device",
        re.compile(
            r"\bdd\s+.*\bif=/dev/(zero|random|urandom).*\bof=/dev/(sd|nvme|hd|disk|mmcblk)",
            re.DOTALL,
        ),
    ),
    (
        "mkfs",
        re.compile(r"\bmkfs(\.[a-zA-Z0-9]+)?\b"),
    ),
    (
        "shutdown",
        re.compile(r"\bshutdown\b"),
    ),
    (
        "halt",
        re.compile(r"\bhalt\b"),
    ),
    (
        "poweroff",
        re.compile(r"\bpoweroff\b"),
    ),
    (
        "init 0/6",
        re.compile(r"\binit\s+(0|6)\b"),
    ),
    (
        "git push --force",
        # ``--force-with-lease`` is OK; treat ``-f`` short form as denied.
        re.compile(
            r"\bgit\s+push\b.*(--force(?!-with-lease)|--mirror|\s-f(?:\s|$))"
        ),
    ),
]


def _is_rm_root_wipe(segment: str) -> bool:
    """True if ``segment`` is ``rm`` with recursive+force targeting root.

    Token-based so separated flags (``rm -r -f /``, ``rm -f -r /``) and
    bundles (``-rf``, ``-fr``, ``-rfv``) are all caught regardless of order.
    Stays conservative: requires BOTH recursive and force AND a root target
    (``/`` or ``/*``), so safe paths (``/tmp/foo``, ``./build``) and
    single-flag forms (``rm -r /tmp``, ``rm -f /etc/x``) are not denied.

    Args:
        segment: A single shell command segment (no compound connectors).

    Returns:
        ``True`` if the segment is a recursive+force wipe of filesystem root.
    """
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        # Unbalanced quotes — let the regex rules handle it; don't crash.
        return False
    if not tokens or tokens[0] != "rm":
        return False

    recursive = False
    force = False
    targets: List[str] = []
    for tok in tokens[1:]:
        if tok in ("--recursive", "-R"):
            recursive = True
        elif tok == "--force":
            force = True
        elif tok == "--no-preserve-root":
            # A flag, not a target; ignore for target detection.
            continue
        elif tok.startswith("--"):
            # Unknown long option — neither recursive/force nor a target.
            continue
        elif tok.startswith("-") and len(tok) > 1:
            # Short flag bundle, e.g. ``-rf``, ``-fr``, ``-rfv``, ``-r``, ``-f``.
            letters = tok[1:]
            if "r" in letters:
                recursive = True
            if "f" in letters:
                force = True
        else:
            targets.append(tok)

    if not (recursive and force):
        return False
    return any(t in _RM_ROOT_TARGETS for t in targets)


def check_denylist(command: str) -> Optional[str]:
    """Return the matched pattern label if ``command`` hits the hard denylist.

    Splits the command into segments first (see ``splitter.py``) so
    ``echo safe && rm -rf /`` still trips. Returns ``None`` if no segment
    matches.

    Args:
        command: Raw shell command string.

    Returns:
        The human-readable pattern label, or ``None`` if no match.
    """
    if not command:
        return None
    for segment in split_command(command):
        if _is_rm_root_wipe(segment):
            return _RM_ROOT_LABEL
        for label, pattern in _PATTERNS:
            if pattern.search(segment):
                return label
    # Also try matching the whole command as a single string, so a
    # multi-line / unusual-whitespace fork bomb that splits weirdly still
    # gets caught.
    for label, pattern in _PATTERNS:
        if pattern.search(command):
            return label
    return None
