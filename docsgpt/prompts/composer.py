"""Compose the chat presets from shared fragments at load time.

The six presets (3 tones x 2 retrieval modes) used to be six near-identical
files: only the ``## Answering`` section differed, so every edit to the shared
prose had to land six times and silently drifted when it didn't. Each preset is
now assembled from single-source fragments under ``prompts/fragments/``.

Composition happens **here, at load time**, not through Jinja ``{% include %}``:

* ``TemplateEngine`` runs a ``SandboxedEnvironment`` with no loader, so adding
  one would open a file-read surface reachable from user-authored templates.
* ``StreamProcessor._get_required_tool_actions`` parses the *raw* prompt text to
  decide which tools to pre-execute. With template inheritance the child file
  would not contain ``{{ tools.memory.memory_view }}``, so memory prefetch would
  silently stop working. Composing first keeps that parser seeing the whole
  prompt.

The composed output is byte-identical to the presets this replaced; the
``tests/test_prompt_composer.py`` goldens pin that.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

FRAGMENTS_DIR = Path(__file__).resolve().parent / "fragments"

# Section order of every composed preset. ``answering`` is the only slot that
# varies; the rest are shared verbatim. There is deliberately no tool-usage
# section: per-tool policy lives in each tool's action ``description``, so it
# is sent only when the tool is actually attached and cannot drift from the
# schema. Cross-tool arbitration stays in ``answering``.
_SECTION_ORDER: Tuple[str, ...] = (
    "identity.txt",
    "persona.txt",
    None,  # answering — resolved per (mode, tone)
    "formatting.txt",
    "boundaries.txt",
    "platform.txt",
    "memory.txt",
    "attachments.txt",
)

# preset id -> (retrieval mode, tone)
PRESET_VARIANTS: Dict[str, Tuple[str, str]] = {
    "default": ("classic", "default"),
    "creative": ("classic", "creative"),
    "strict": ("classic", "strict"),
    "agentic_default": ("agentic", "default"),
    "agentic_creative": ("agentic", "creative"),
    "agentic_strict": ("agentic", "strict"),
}

_cache: Dict[str, str] = {}


def _read(relative: str) -> str:
    """Read one fragment.

    Args:
        relative: Path relative to the fragments directory.

    Returns:
        str: The fragment's raw text.
    """
    return (FRAGMENTS_DIR / relative).read_text(encoding="utf-8")


def is_composed_preset(preset_id: str) -> bool:
    """Return True when ``preset_id`` is one this module composes."""
    return preset_id in PRESET_VARIANTS


def compose_preset(preset_id: str) -> str:
    """Assemble a preset from its fragments.

    Args:
        preset_id: One of the keys in :data:`PRESET_VARIANTS`.

    Returns:
        str: The complete prompt template, ready for the Jinja renderer.

    Raises:
        KeyError: If ``preset_id`` is not a composed preset.
    """
    cached = _cache.get(preset_id)
    if cached is not None:
        return cached

    mode, tone = PRESET_VARIANTS[preset_id]
    parts: List[str] = []
    for section in _SECTION_ORDER:
        parts.append(
            _read(f"answering/{mode}_{tone}.txt") if section is None else _read(section)
        )
    composed = "".join(parts)
    _cache[preset_id] = composed
    return composed
