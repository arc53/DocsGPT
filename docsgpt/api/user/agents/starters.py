"""Agent starters: the questions a new chat with an agent offers.

The owner (or an editor) writes up to :data:`MAX_STARTERS` of them; anyone who
can open a chat with the agent sees them. Stored in ``agents.starters`` as a
JSON array of strings (migration 0061).
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from typing import Any

#: The most starters an agent keeps.
MAX_STARTERS = 4
#: The longest a single starter may be, in characters, after trimming.
MAX_STARTER_LENGTH = 200
#: Control characters a starter may hold inside it; the rest (NUL among them,
#: which Postgres JSONB can't store) are refused.
_ALLOWED_CONTROLS = frozenset("\t\n\r")


class StartersError(ValueError):
    """Raised when a ``starters`` value can't be stored; the message is safe to return."""


def normalize_starters(raw: Any) -> list[str]:
    """Validate and clean an inbound ``starters`` value.

    Each entry is trimmed; empty entries are dropped, and so are later
    duplicates (compared case-insensitively), keeping the first. A multipart
    form sends the list as a JSON-encoded string, which is decoded first.

    Args:
        raw: A list of strings, its JSON encoding, or None/``""`` for none.

    Returns:
        The cleaned starters, in their original order.

    Raises:
        StartersError: When ``raw`` isn't a list (or its JSON), holds an entry
            that isn't a string, holds an entry longer than
            :data:`MAX_STARTER_LENGTH`, holds a control character other than
            a tab or line break (NUL included) or an unpaired surrogate, or keeps
            more than :data:`MAX_STARTERS` entries after cleaning.
    """
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raise StartersError("Starters must be a list of questions")
    if not isinstance(raw, list):
        raise StartersError("Starters must be a list of questions")
    cleaned: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            raise StartersError("Each starter must be text")
        text = entry.strip()
        if not text:
            continue
        if len(text) > MAX_STARTER_LENGTH:
            raise StartersError(f"A starter can be at most {MAX_STARTER_LENGTH} characters")
        if any(unicodedata.category(ch) == "Cc" and ch not in _ALLOWED_CONTROLS for ch in text):
            raise StartersError("A starter can't contain control characters")
        # JSON lets a lone ``\ud800`` through; it has no UTF-8 form, so the write would fail.
        if any(unicodedata.category(ch) == "Cs" for ch in text):
            raise StartersError("A starter can't contain an unpaired surrogate")
        folded = text.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        cleaned.append(text)
    if len(cleaned) > MAX_STARTERS:
        raise StartersError(f"An agent can have at most {MAX_STARTERS} starters")
    return cleaned


def stored_starters(agent: Mapping[str, Any]) -> list[str]:
    """The starters an agent row holds, as a list of strings.

    Args:
        agent: An agent row; older rows read through raw SQL may lack the key.

    Returns:
        The stored starters, ``[]`` when there are none or the value isn't a list.
    """
    value = agent.get("starters")
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, str)]
