"""Snapshot the REST API's Swagger document for the docs site.

The docs site renders its REST API reference (``docs/content/API/reference.mdx``)
from ``docs/data/swagger.json``, a checked-in copy of what a running instance
serves at ``/swagger.json``. Regenerate it after changing a route::

    python -m docsgpt.api.reference --write

``--check`` exits non-zero when the checked-in snapshot is stale; the test
suite and CI run the same comparison.

The snapshot is the flask-restx document with sorted keys and nothing that
depends on the host serving it. Each operation also says how a personal access
token may call it, from the rule table in ``docsgpt/api/pat/rules.py``:
``x-pat-scopes`` lists the scopes that admit a token (any one of them; an empty
list means any valid token), and ``x-pat-denied: true`` marks an operation no
token may call.

Building the document imports ``docsgpt.app`` but never touches a database:
the import-time bootstrap (``AUTO_CREATE_DB``, ``AUTO_MIGRATE``,
``AUTO_VECTOR_SCHEMA``) is switched off unless the environment already sets it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

SNAPSHOT_PATH = Path("docs") / "data" / "swagger.json"

_METHODS = ("get", "put", "post", "delete", "patch", "head", "options")

# Keys flask-restx fills from the request or app config of whoever serves it.
_HOST_KEYS = ("host", "schemes")


def _flask_app():
    """The Flask app, imported without the database bootstrap."""
    for name in ("AUTO_CREATE_DB", "AUTO_MIGRATE", "AUTO_VECTOR_SCHEMA"):
        os.environ.setdefault(name, "false")
    from docsgpt.app import app

    return app


def _pat_access(rule: Optional[str], method: str) -> dict[str, Any]:
    """The token annotation for one operation: its scopes, or that tokens are refused.

    Args:
        rule: The Flask rule string behind the Swagger path, or None if none matched.
        method: The HTTP method, any case.

    Returns:
        ``{"x-pat-scopes": [...]}`` or ``{"x-pat-denied": True}``.
    """
    from docsgpt.api.pat import rules

    method = method.upper()
    if rule is None or rules.is_denied(rule, method):
        return {"x-pat-denied": True}
    found = rules.RULES.get((rule, method))
    if found is None:
        # Deny by default: a route missing from the table is refused to tokens.
        return {"x-pat-denied": True}
    return {"x-pat-scopes": sorted(found.scopes)}


def build_spec() -> dict[str, Any]:
    """The Swagger document as the snapshot stores it.

    Returns:
        The flask-restx Swagger 2.0 document without host-specific keys, with
        every operation annotated for personal access tokens.
    """
    from flask_restx.swagger import extract_path

    from docsgpt.api import api

    app = _flask_app()
    with app.test_request_context("/"):
        # A JSON round trip detaches the document from flask-restx's cached copy.
        spec = json.loads(json.dumps(api.__schema__))
    for key in _HOST_KEYS:
        spec.pop(key, None)

    rules_by_path = {extract_path(rule.rule): rule.rule for rule in app.url_map.iter_rules()}
    for path, item in spec.get("paths", {}).items():
        rule = rules_by_path.get(path)
        for method, operation in item.items():
            if method in _METHODS and isinstance(operation, dict):
                operation.update(_pat_access(rule, method))
    return spec


def render_spec() -> str:
    """The snapshot file's text: sorted keys, two-space indent, trailing newline."""
    return json.dumps(build_spec(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def snapshot_path(root: Optional[Path] = None) -> Path:
    """Where the snapshot lives in a checkout; ``root`` defaults to the repository root."""
    if root is None:
        root = Path(__file__).resolve().parents[2]
    return root / SNAPSHOT_PATH


def main(argv: Optional[list[str]] = None) -> int:
    """Write, check or print the snapshot.

    Args:
        argv: Command-line arguments; ``sys.argv[1:]`` when None.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true", help="write the snapshot into the docs tree")
    action.add_argument("--check", action="store_true", help="exit 1 if the checked-in snapshot is stale")
    args = parser.parse_args(argv)

    rendered = render_spec()
    path = snapshot_path()
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        print(f"wrote {path}")
        return 0
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != rendered:
            print(f"{path} is stale; run: python -m docsgpt.api.reference --write", file=sys.stderr)
            return 1
        print(f"{path} is up to date")
        return 0
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
