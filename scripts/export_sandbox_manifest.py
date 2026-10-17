"""Write the runner image's install files from the sandbox manifest.

``docsgpt/sandbox/manifest.py`` lists what the code sandbox holds. The Daytona
snapshot builds from it directly, but the runner's Dockerfile cannot import
Python, so it installs from files generated here into ``deployment/sandbox/``:

* ``requirements.txt``: pinned pip packages
* ``install-system.sh``: Debian packages, font links and the checksum-verified Node.js build
* ``sandbox.env``: variables ``kernel-env.sh`` hands to kernel code
* ``manifest.json``: the manifest as data, for ``smoke_test.py``

Run it after editing the manifest, the way ``scripts/export_requirements.sh``
follows ``uv lock``::

    python scripts/export_sandbox_manifest.py          # rewrite the files
    python scripts/export_sandbox_manifest.py --check  # exit 1 if any is stale (CI)

Only the stdlib is needed; the backend does not have to be installed.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional

_REPO = Path(__file__).resolve().parents[1]


def _load_manifest() -> ModuleType:
    """Load ``docsgpt/sandbox/manifest.py`` by path, without importing the backend package."""
    path = _REPO / "docsgpt" / "sandbox" / "manifest.py"
    spec = importlib.util.spec_from_file_location("_docsgpt_sandbox_manifest", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stale(root: Path, files: Dict[str, str]) -> List[str]:
    """Return the generated paths under ``root`` whose content differs from ``files``."""
    stale = []
    for rel_path, content in files.items():
        target = root / rel_path
        if not target.is_file() or target.read_text() != content:
            stale.append(rel_path)
    return stale


def main(argv: Optional[List[str]] = None) -> int:
    """Write the generated files, or with ``--check`` report the stale ones.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.

    Returns:
        0 on success, 1 when ``--check`` finds a stale file.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail instead of writing when a file is stale")
    parser.add_argument("--root", type=Path, default=_REPO, help="repository root to write under")
    args = parser.parse_args(argv)

    files = _load_manifest().generated_files()
    if args.check:
        stale = _stale(args.root, files)
        for rel_path in stale:
            print(f"stale: {rel_path}", file=sys.stderr)
        if stale:
            print("run: python scripts/export_sandbox_manifest.py", file=sys.stderr)
            return 1
        print(f"{len(files)} generated sandbox files are current")
        return 0

    for rel_path, content in files.items():
        target = args.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        if target.suffix == ".sh":
            target.chmod(0o755)
        print(f"wrote {rel_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
