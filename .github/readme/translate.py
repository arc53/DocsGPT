#!/usr/bin/env python3
"""Keep the README translations in .github/readme/ in step with README.md.

Each translation starts with a marker naming the README.md commit it was made
from. When README.md moves on, the DocsGPT translation agent gets the diff and
the current translation and returns the whole updated document, so wording
fixes made by hand survive. A missing file, an unknown marker or ``--full``
gets a fresh translation instead. The script owns everything structural: the
language bar, the marker and the relative links, which it rewrites so they
resolve from this folder. Run by .github/workflows/readme-translations.yml.
Standard library only.

    DOCSGPT_README_AGENT_KEY=... python .github/readme/translate.py
    python .github/readme/translate.py --languages de,ja --full
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

REPO = Path(__file__).resolve().parents[2]
FOLDER = Path(__file__).resolve().parent
DEFAULT_URL = "https://gptcloud.arc53.com"
KEY_ENV = "DOCSGPT_README_AGENT_KEY"
REQUEST_TIMEOUT = 900
ATTEMPTS = 2


@dataclass(frozen=True)
class Language:
    label: str
    name: str


LANGUAGES: dict[str, Language] = {
    "de": Language("Deutsch", "German"),
    "es": Language("Español", "Spanish"),
    "ja": Language("日本語", "Japanese"),
    "ru": Language("Русский", "Russian"),
    "zh-CN": Language("简体中文", "Simplified Chinese"),
    "zh-TW": Language("繁體中文", "Traditional Chinese"),
}

BAR_START = "<!-- languages:start -->"
BAR_END = "<!-- languages:end -->"
PLACEHOLDER = "<!-- languages -->"
BAR_RE = re.compile(re.escape(BAR_START) + r".*?" + re.escape(BAR_END), re.DOTALL)
MARKER_RE = re.compile(r"\A<!-- Translated from README\.md at commit ([0-9a-f]{7,40})\b[^\n]*-->\n")
# Link targets in Markdown (``](target)``) and HTML (``src="target"``, ``href="target"``).
LINK_RE = re.compile(r'(?<=\]\()[^)\s]+|(?<=src=")[^"]+|(?<=href=")[^"]+')
NON_RELATIVE_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*:|#|/)")
URL_RE = re.compile(r"https?://[^\s)\"'<>`]+")
HEADING_RE = re.compile(r"^#{1,6}\s")
PREFIX = "../../"


class TranslationError(Exception):
    """The agent could not be reached or its answer was unusable."""


@dataclass
class Result:
    text: str
    changed: bool
    notes: str = ""
    mode: str = "current"


# --- Language bar -----------------------------------------------------------


def language_bar(current: str) -> str:
    """Return the language bar for README.md (``"en"``) or one translation.

    Args:
        current: ``"en"`` for README.md, else a key of ``LANGUAGES``.

    Returns:
        The bar between its start and end markers, current language in bold.
    """
    entries = [("en", "English")] + [(code, lang.label) for code, lang in LANGUAGES.items()]
    links = []
    for code, label in entries:
        if code == current:
            links.append(f"<strong>{label}</strong>")
            continue
        if current == "en":
            href = f".github/readme/README.{code}.md"
        elif code == "en":
            href = f"{PREFIX}README.md"
        else:
            href = f"README.{code}.md"
        links.append(f'<a href="{href}">{label}</a>')
    body = " |\n  ".join(links)
    return f'{BAR_START}\n<p align="center">\n  {body}\n</p>\n{BAR_END}'


def strip_bar(text: str) -> str:
    """Replace the language bar with the placeholder the agent keeps in place."""
    return BAR_RE.sub(lambda _: PLACEHOLDER, text)


def insert_bar(text: str, code: str) -> str:
    """Replace the placeholder with the bar for ``code``."""
    return text.replace(PLACEHOLDER, language_bar(code))


def set_readme_bar(text: str) -> str:
    """Bring README.md's own language bar up to date with ``LANGUAGES``."""
    return BAR_RE.sub(lambda _: language_bar("en"), text)


# --- Links ------------------------------------------------------------------


def _is_fence(line: str) -> bool:
    return re.sub(r"^[\s>]*", "", line).startswith(("```", "~~~"))


def _outside_fences(text: str) -> Iterable[tuple[str, bool]]:
    """Yield each line with whether it lies outside fenced code (fence lines count as inside)."""
    inside = False
    for line in text.splitlines(keepends=True):
        if _is_fence(line):
            inside = not inside
            yield line, False
        else:
            yield line, not inside


def _is_relative(target: str) -> bool:
    return not NON_RELATIVE_RE.match(target)


def _map_links(text: str, change: Callable[[str], str]) -> str:
    out = []
    for line, prose in _outside_fences(text):
        if prose:
            line = LINK_RE.sub(lambda m: change(m.group(0)) if _is_relative(m.group(0)) else m.group(0), line)
        out.append(line)
    return "".join(out)


def rewrite_links(text: str) -> str:
    """Point relative link targets written for the repository root at it from .github/readme/."""
    return _map_links(text, lambda target: PREFIX + target)


def unrewrite_links(text: str) -> str:
    """Undo ``rewrite_links`` so the agent sees the same targets as in README.md."""
    return _map_links(text, lambda target: target.removeprefix(PREFIX))


def relative_targets(text: str) -> list[str]:
    """Return the relative link targets outside fenced code, in order."""
    found = []
    for line, prose in _outside_fences(text):
        if prose:
            found.extend(t for t in LINK_RE.findall(line) if _is_relative(t))
    return found


# --- Marker -----------------------------------------------------------------


def with_marker(body: str, sha: str) -> str:
    """Prefix ``body`` with the marker naming the README.md commit it was translated from."""
    return (
        f"<!-- Translated from README.md at commit {sha} by .github/workflows/readme-translations.yml. "
        f"Fix wording here; change structure in README.md. -->\n{body}"
    )


def parse_marker(text: str) -> Optional[str]:
    match = MARKER_RE.match(text)
    return match.group(1) if match else None


def strip_marker(text: str) -> str:
    return MARKER_RE.sub("", text, count=1)


def render(code: str, translated: str, sha: str) -> str:
    """Turn the agent's text (placeholder, root-relative links) into the committed file."""
    return with_marker(insert_bar(rewrite_links(translated), code), sha)


def agent_form(committed: str) -> str:
    """Reverse ``render``: the committed file as the agent should see it."""
    return unrewrite_links(strip_bar(strip_marker(committed)))


# --- Validation -------------------------------------------------------------


def _urls(text: str) -> Counter:
    return Counter(url.rstrip(".,;:!?") for url in URL_RE.findall(text))


def _fences(text: str) -> int:
    return sum(1 for line in text.splitlines() if _is_fence(line))


def _headings(text: str) -> int:
    return sum(1 for line, prose in _outside_fences(text) if prose and HEADING_RE.match(line))


def _difference(label: str, expected: Counter, got: Counter) -> list[str]:
    errors = [f"{label} missing or changed: {item}" for item in sorted((expected - got).elements())]
    errors += [f"{label} not in README.md: {item}" for item in sorted((got - expected).elements())]
    return errors


def validate(source: str, translated: str) -> list[str]:
    """Compare the structure of a translation with its source.

    Args:
        source: README.md with the bar replaced by the placeholder.
        translated: The agent's translation, in the same form.

    Returns:
        One line per problem; empty when the translation keeps the structure.
    """
    errors = []
    if translated.count(PLACEHOLDER) != source.count(PLACEHOLDER):
        errors.append(f"The {PLACEHOLDER} placeholder must appear exactly once, where it is in README.md.")
    if _fences(translated) != _fences(source):
        errors.append(f"README.md has {_fences(source)} code fence lines, the translation {_fences(translated)}.")
    if _headings(translated) != _headings(source):
        errors.append(f"README.md has {_headings(source)} Markdown headings, the translation {_headings(translated)}.")
    errors += _difference("URL", _urls(source), _urls(translated))
    errors += _difference("Relative link", Counter(relative_targets(source)), Counter(relative_targets(translated)))
    return errors


# --- Agent ------------------------------------------------------------------


def parse_reply(content: str) -> tuple[str, str]:
    """Return ``(markdown, notes)`` from the agent's JSON answer."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"\A```[a-zA-Z]*\n|\n?```\Z", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TranslationError(f"The answer is not JSON ({exc.msg}).") from exc
    if not isinstance(data, dict) or not isinstance(data.get("markdown"), str) or not data["markdown"].strip():
        raise TranslationError('The answer must be a JSON object with a non-empty "markdown" string.')
    notes = data.get("notes")
    markdown = data["markdown"] if data["markdown"].endswith("\n") else data["markdown"] + "\n"
    return markdown, notes.strip() if isinstance(notes, str) else ""


def build_message(code: str, source: str, current: Optional[str] = None, diff: Optional[str] = None) -> str:
    """Compose the request for one language; ``current`` and ``diff`` switch to update mode."""
    lang = LANGUAGES[code]
    mode = "update" if current is not None else "full"
    parts = [f"Target language: {lang.name} ({code})", f"Mode: {mode}", ""]
    if mode == "update":
        parts.append(
            "README.md changed as the diff shows. Update the current translation to match the new README.md and "
            "return the whole document. Keep the wording of unchanged parts as it is."
        )
        parts += ["", "<readme_diff>", diff or "", "</readme_diff>", "", "<current_translation>", current or ""]
        parts += ["</current_translation>", ""]
    else:
        parts += [f"Translate README.md into {lang.name} and return the whole document.", ""]
    parts += ["<readme>", source, "</readme>"]
    return "\n".join(parts)


def make_agent(url: str, key: Optional[str], timeout: int = REQUEST_TIMEOUT) -> Callable[[str], str]:
    """Return a function that sends one message to the agent and returns its answer."""

    def ask(message: str) -> str:
        if not key:
            raise TranslationError(f"{KEY_ENV} is not set.")
        body = json.dumps(
            {"model": "docsgpt", "messages": [{"role": "user", "content": message}], "stream": False}
        ).encode("utf-8")
        request = urllib.request.Request(
            url.rstrip("/") + "/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    data = json.load(response)
                return data["choices"][0]["message"]["content"] or ""
            except urllib.error.HTTPError as exc:
                if exc.code < 500 or attempt == 2:
                    raise TranslationError(f"The agent answered HTTP {exc.code}.") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise TranslationError(f"The agent could not be reached ({exc}).") from exc
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise TranslationError("The agent's response has no message content.") from exc
            time.sleep(15 * (attempt + 1))
        raise AssertionError("unreachable")

    return ask


def translate_language(
    code: str,
    readme: str,
    sha: str,
    current: Optional[str],
    load_source: Callable[[str], Optional[str]],
    agent: Callable[[str], str],
    full: bool = False,
) -> Result:
    """Bring one translation up to date with README.md.

    Args:
        code: A key of ``LANGUAGES``.
        readme: README.md as committed, language bar included.
        sha: The commit README.md was last changed in.
        current: The committed translation, or None when there is none.
        load_source: Returns README.md as it was at a commit, or None if unknown.
        agent: Sends one message to the translation agent and returns its answer.
        full: Translate from scratch even when an update would do.

    Returns:
        The file to commit, whether it differs from ``current``, the agent's notes and the mode used.

    Raises:
        TranslationError: The agent failed or its answer stayed invalid after a retry.
    """
    source = strip_bar(readme)
    message = build_message(code, source)
    mode = "full"
    if current is not None and not full:
        body = agent_form(current)
        old_sha = parse_marker(current)
        old_readme = load_source(old_sha) if old_sha and old_sha != sha else None
        if old_sha == sha or (old_readme is not None and strip_bar(old_readme) == source):
            text = render(code, body, sha)
            return Result(text, text != current, mode="current")
        if old_readme is not None:
            diff = "".join(
                difflib.unified_diff(
                    strip_bar(old_readme).splitlines(keepends=True),
                    source.splitlines(keepends=True),
                    "README.md (translated)",
                    "README.md (now)",
                )
            )
            message = build_message(code, source, body, diff)
            mode = "update"

    problems: list[str] = []
    for _ in range(ATTEMPTS):
        prompt = message
        if problems:
            prompt += "\n\nYour previous answer was rejected:\n" + "\n".join(f"- {p}" for p in problems)
            prompt += "\nReturn the whole document again with these fixed."
        try:
            markdown, notes = parse_reply(agent(prompt))
        except TranslationError as exc:
            problems = [str(exc)]
            continue
        problems = validate(source, markdown)
        if not problems:
            return Result(render(code, markdown, sha), True, notes, mode)
    raise TranslationError("; ".join(problems))


# --- Command line -----------------------------------------------------------


def _git(*args: str) -> Optional[str]:
    try:
        return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _summary(results: dict[str, Result], failures: dict[str, str]) -> str:
    lines = ["| Language | Result | Notes from the agent |", "|---|---|---|"]
    for code in LANGUAGES:
        label = LANGUAGES[code].label
        if code in failures:
            lines.append(f"| {label} | failed: {failures[code]} | |")
        elif code in results:
            result = results[code]
            outcome = {"full": "translated", "update": "updated"}.get(result.mode, "marker moved")
            outcome = outcome if result.changed else "already current"
            notes = result.notes.replace("\n", " ").replace("|", "\\|")
            lines.append(f"| {label} | {outcome} | {notes} |")
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--languages", default=",".join(LANGUAGES), help="comma-separated codes (default: all)")
    parser.add_argument("--full", action="store_true", help="translate from scratch instead of updating")
    parser.add_argument("--summary", type=Path, help="write a Markdown summary table here")
    args = parser.parse_args(argv)

    codes = [code.strip() for code in args.languages.split(",") if code.strip()]
    unknown = [code for code in codes if code not in LANGUAGES]
    if unknown:
        parser.error(f"unknown language(s): {', '.join(unknown)}; choose from {', '.join(LANGUAGES)}")

    readme_path = REPO / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    if BAR_START not in readme:
        print(f"README.md has no {BAR_START} ... {BAR_END} block for the language bar.", file=sys.stderr)
        return 2
    if set_readme_bar(readme) != readme:
        readme = set_readme_bar(readme)
        readme_path.write_text(readme, encoding="utf-8")
        print("README.md: language bar updated")

    sha = (_git("log", "-1", "--format=%H", "--", "README.md") or "").strip()
    if not sha:
        print("Could not find the commit README.md was last changed in.", file=sys.stderr)
        return 2
    agent = make_agent(os.environ.get("DOCSGPT_URL") or DEFAULT_URL, os.environ.get(KEY_ENV))

    def run(code: str) -> Result:
        path = FOLDER / f"README.{code}.md"
        current = path.read_text(encoding="utf-8") if path.exists() else None
        return translate_language(
            code, readme, sha, current, lambda rev: _git("show", f"{rev}:README.md"), agent, full=args.full
        )

    results: dict[str, Result] = {}
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(codes)) as pool:
        futures = {code: pool.submit(run, code) for code in codes}
        for code, future in futures.items():
            try:
                results[code] = future.result()
            except TranslationError as exc:
                failures[code] = str(exc)

    for code, result in results.items():
        if result.changed:
            (FOLDER / f"README.{code}.md").write_text(result.text, encoding="utf-8")
        print(f"{code}: {result.mode if result.changed else 'already current'}")
    for code, error in failures.items():
        print(f"{code}: failed: {error}", file=sys.stderr)
    if args.summary:
        args.summary.write_text(_summary(results, failures), encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
