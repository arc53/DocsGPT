"""Render the settings reference page from the ``Settings`` definitions.

The page under ``docs/content/Deploying/Settings-Reference.mdx`` is generated
from the field types, defaults and descriptions in this package, so the model
is the single source of truth. Regenerate it after changing a setting::

    python -m docsgpt.core.settings.reference --write

``--check`` exits non-zero when the checked-in page is stale; the test suite
runs the same comparison.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
import types
import typing
from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import AliasChoices
from pydantic.fields import FieldInfo

from docsgpt.core.paths import home_dir
from docsgpt.core.settings import SETTINGS_GROUPS, Settings

REFERENCE_PATH = Path("docs") / "content" / "Deploying" / "Settings-Reference.mdx"

HOME_PLACEHOLDER = "<DOCSGPT_HOME>"

_HEADER = """\
---
title: Settings Reference
description: Every DocsGPT setting, grouped by domain, with its type, default and purpose.
---

{/* GENERATED FILE. Do not edit by hand: run `python -m docsgpt.core.settings.reference --write`. */}

# Settings Reference

Every setting DocsGPT reads, generated from `docsgpt/core/settings/`. Each one is
an environment variable of the same name, set in `.env` or the process
environment; see [App Configuration](/Deploying/DocsGPT-Settings) for how the
file is found and for worked examples. `<DOCSGPT_HOME>` below is the data home
described there.
"""


def _mdx(text: str) -> str:
    """Escape prose for MDX, where braces open expressions and ``<`` opens JSX."""
    return text.replace("{", "\\{").replace("}", "\\}").replace("<", "&lt;")


def _type_name(annotation: Any) -> str:
    origin = typing.get_origin(annotation)
    if origin in (Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return " | ".join(_type_name(a) for a in args)
    if origin is Literal:
        return " | ".join(json.dumps(v) for v in typing.get_args(annotation))
    if origin is not None:
        name = getattr(origin, "__name__", str(origin))
        args = typing.get_args(annotation)
        return f"{name}[{', '.join(_type_name(arg) for arg in args)}]" if args else name
    return getattr(annotation, "__name__", str(annotation))


def _default_text(field: FieldInfo) -> str:
    value = field.default_factory() if field.default_factory is not None else field.default
    if value is None:
        return "unset"
    if isinstance(value, bool):
        return "`true`" if value else "`false`"
    if isinstance(value, str):
        value = value.replace(str(home_dir()), HOME_PLACEHOLDER)
        return "`\"\"`" if value == "" else f"`{value}`"
    if isinstance(value, (list, dict)):
        return f"`{json.dumps(value)}`"
    return f"`{value}`"


def _constraints(field: FieldInfo) -> list[str]:
    out = []
    for item in field.metadata:
        for attr, symbol in (("gt", ">"), ("ge", ">="), ("lt", "<"), ("le", "<=")):
            if hasattr(item, attr):
                out.append(f"{symbol} {getattr(item, attr)}")
    return out


def _aliases(name: str, field: FieldInfo) -> list[str]:
    alias = field.validation_alias
    if isinstance(alias, AliasChoices):
        return [str(c) for c in alias.choices if str(c) != name]
    if isinstance(alias, str) and alias != name:
        return [alias]
    return []


def _render_field(name: str, field: FieldInfo) -> str:
    facts = [f"Type `{_type_name(field.annotation)}`", f"default {_default_text(field)}"]
    constraints = _constraints(field)
    if constraints:
        # Code spans: a bare ``<=`` in MDX prose is parsed as the start of a JSX tag.
        facts.append("must be " + " and ".join(f"`{c}`" for c in constraints))
    aliases = _aliases(name, field)
    if aliases:
        facts.append("also read from " + ", ".join(f"`{a}`" for a in aliases))
    # The facts are code spans, which MDX leaves alone; only prose needs escaping.
    lines = [f"### `{name}`", "", ", ".join(facts) + "."]
    if field.deprecated:
        note = field.deprecated if isinstance(field.deprecated, str) else "This setting is deprecated."
        lines += ["", f"**Deprecated.** {_mdx(str(note))}"]
    if field.description:
        lines += ["", _mdx(field.description)]
    return "\n".join(lines)


def _group_intro(group: type) -> str:
    doc = inspect.getdoc(group) or ""
    return doc.split("\n\n", 1)[0].replace("\n", " ").strip()


def render_reference() -> str:
    """The full reference page as MDX text."""
    parts = [_HEADER]
    for title, group in SETTINGS_GROUPS:
        parts.append(f"\n## {title}\n")
        intro = _group_intro(group)
        if intro:
            parts.append(_mdx(intro) + "\n")
        for name in group.model_fields:
            parts.append(_render_field(name, Settings.model_fields[name]) + "\n")
    return "\n".join(parts).rstrip("\n") + "\n"


def reference_path(root: Optional[Path] = None) -> Path:
    """Where the generated page lives in a checkout; ``root`` defaults to the repository root."""
    if root is None:
        root = Path(__file__).resolve().parents[3]
    return root / REFERENCE_PATH


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true", help="write the page into the docs tree")
    action.add_argument("--check", action="store_true", help="exit 1 if the checked-in page is stale")
    args = parser.parse_args(argv)

    rendered = render_reference()
    path = reference_path()
    if args.write:
        path.write_text(rendered, encoding="utf-8")
        print(f"wrote {path}")
        return 0
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != rendered:
            print(f"{path} is stale; run: python -m docsgpt.core.settings.reference --write", file=sys.stderr)
            return 1
        print(f"{path} is up to date")
        return 0
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
