"""The docs site's list of curated MCP presets, generated from the catalog.

The docs render the preset table on the Connectors page from
``docs/data/mcp-presets.json``, a copy of what the files under
``docsgpt/connectors/presets/mcp/`` say. Adding a preset is then one new file
there and no edit to a docs page::

    python -m docsgpt.connectors.reference --write

``--check`` exits non-zero when the checked-in file is stale. The "Generated
docs" workflow runs ``--write`` on ``main`` after a merge, so a pull request
never carries the file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

DATA_PATH = Path("docs") / "data" / "mcp-presets.json"


def build_presets() -> list[dict[str, Any]]:
    """The presets as the docs list them.

    Returns:
        One entry per preset, by name, with only what the docs table shows.
    """
    from docsgpt.connectors import catalog

    presets = [definition for definition in catalog.all_definitions() if definition.publisher == "preset"]
    return [
        {
            "key": preset.key,
            "name": preset.name,
            "description": preset.description,
            "category": preset.category,
            "sign_in": "oauth" if preset.auth_kind == "mcp_oauth" else "none",
            "capabilities": list(preset.capabilities),
            "mcp_url": preset.mcp_url,
            "docs_url": preset.docs_url,
        }
        for preset in sorted(presets, key=lambda preset: (preset.name.casefold(), preset.key))
    ]


def render_presets() -> str:
    """The data file's text: two-space indent, trailing newline."""
    return json.dumps(build_presets(), indent=2, ensure_ascii=False) + "\n"


def data_path(root: Optional[Path] = None) -> Path:
    """Where the data file lives in a checkout; ``root`` defaults to the repository root."""
    if root is None:
        root = Path(__file__).resolve().parents[2]
    return root / DATA_PATH


def main(argv: Optional[list[str]] = None) -> int:
    """Write, check or print the data file.

    Args:
        argv: Command-line arguments; ``sys.argv[1:]`` when None.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true", help="write the file into the docs tree")
    action.add_argument("--check", action="store_true", help="exit 1 if the checked-in file is stale")
    args = parser.parse_args(argv)

    rendered = render_presets()
    path = data_path()
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        print(f"wrote {path}")
        return 0
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != rendered:
            print(f"{path} is stale; run: python -m docsgpt.connectors.reference --write", file=sys.stderr)
            return 1
        print(f"{path} is up to date")
        return 0
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
