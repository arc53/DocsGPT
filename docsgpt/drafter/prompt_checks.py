"""Checks on a prompt's text that need no model: cheap, deterministic, run as the user types.

``POST /api/check_prompt`` returns them for the prompt editor's hint line, and
the prompt recipe's review hands them to the model (and adds the ones it
leaves out). Each check is a ``code`` the client words in the user's language,
with what it needs to say where: the blank's text and line, the topic of a line
DocsGPT already adds, the tool variables a template runs.

The lists are kept short and precise on purpose: a hint that fires on
ordinary prose ("the delivery date") teaches people to ignore it.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

from docsgpt.drafter.catalog import is_template
from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.prompt_rules import (
    CITATION_MARKER,
    has_boundaries,
    template_parses,
    tool_variable,
    tool_variables,
)

#: Most checks returned.
MAX_CHECKS = 20
#: Most characters of a blank's ``text``.
TEXT_MAX = 80

#: ``code`` values, in the order they are reported.
PLACEHOLDER = "placeholder"
REPEATS_BUILTIN = "repeats_builtin"
TEMPLATE_INVALID = "template_invalid"
TOOL_VARIABLES = "tool_variables"
BOUNDARIES_MISSING = "boundaries_missing"
CITATIONS_MISSING = "citations_missing"
CODES = (PLACEHOLDER, REPEATS_BUILTIN, TEMPLATE_INVALID, TOOL_VARIABLES, BOUNDARIES_MISSING, CITATIONS_MISSING)



@lru_cache(maxsize=1)
def _builtin_tool_variables() -> frozenset:
    """The tool variables DocsGPT's own prompts use: a copy of a built-in keeps them, so they aren't news."""
    from docsgpt.prompts.composer import compose_preset, PRESET_VARIANTS

    return frozenset(usage for preset in PRESET_VARIANTS for usage in tool_variables(compose_preset(preset)))


# Text no blank is looked for in: template syntax, and code (inline or fenced) the prompt shows as an example.
# Where each masked span starts; ``_masked`` finds where it ends, by hand, so many unclosed ``{{`` stay linear.
_MASK_OPENER = re.compile(r"\{\{|\{%|\{#|```|~~~|`[^`\n]+`")
#: A template opener's closer. One with no closer after it isn't masked: the text reads on as plain prose.
_TEMPLATE_CLOSERS = {"{{": "}}", "{%": "%}", "{#": "#}"}

# ``[support email]``: not a markdown link (``[text](url)``, ``[text][ref]``, ``[ref]: url``), a citation (``[1]``)
# or a checkbox (``[ ]``, ``[x]``).
_BRACKET = re.compile(r"(?<![\]\\!])\[([^\[\]\n]{2,60})\](?![(\[:])")
# ``<company name>``: no ``=`` (a tag's attribute) or ``/`` (a closing tag, a URL) or ``@`` (an address).
_ANGLE = re.compile(r"<([^<>\n=/@\"']{2,60})>")
# ``{company}``: one brace each side, in a persona (a template reads ``{{ }}``).
_BRACE = re.compile(r"(?<!\{)\{([^{}\n]{2,60})\}(?!\})")
_MARKER = re.compile(r"\b(?:TODO|TBD|XXX)\b")
# What a blank holds: a few words, starting with a letter.
_BLANK_WORDS = re.compile(r"[^\W\d_][\w .,'&-]*")
#: Tags a prompt names on purpose: DocsGPT's own (``<documents>``, ``<persona>``…) and common HTML.
_KNOWN_TAGS = frozenset({
    "documents", "document", "memory_directory", "persona", "attached_file", "attached_files", "knowledge",
    "source", "url", "content", "a", "b", "i", "u", "p", "br", "hr", "em", "strong", "code", "pre", "li", "ul",
    "ol", "table", "thead", "tbody", "tr", "td", "th", "div", "span", "img", "sup", "sub", "details", "summary",
    "kbd", "mark", "small", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
})

# Lines a persona doesn't need because DocsGPT adds them (``COMPOSER_SUMMARY``): common English phrasings only.
_BUILTIN_TOPICS: tuple[tuple[str, re.Pattern], ...] = tuple((topic, re.compile("|".join(patterns), re.I)) for
                                                            topic, patterns in (
    ("date", (
        r"\btoday['’]?s date\b",
        r"\bthe current date\b",
        r"\bthe date today\b",
        r"\bwhat (?:day|date) it is\b",
    )),
    ("citations", (
        r"\bcite (?:your |the |its |all |relevant |each |every )?(?:sources?|documents?|references?)\b",
        r"\balways cite\b",
        r"\b(?:include|add|provide|give|use) (?:\w+ ){0,2}citations\b",
        r"\breference your sources\b",
    )),
    ("formatting", (
        r"\buse markdown\b",
        r"\b(?:format|formatted|write|answer|respond|reply)(?: \w+){0,3} (?:in|with|using) markdown\b",
        r"\b(?:use|put (?:any |all )?code in) (?:fenced |markdown )?code blocks?\b",
    )),
    ("data_guard", (
        r"\bdata,? (?:and )?not (?:as )?instructions\b",
        r"\btreat (?:the |all |any |retrieved |provided )*(?:documents?|context|content|tool results?|search "
        r"results?) as data\b",
        r"\b(?:ignore|never follow|don['’]?t follow|do not follow) (?:any )?(?:instructions|directions|commands)"
        r"(?: \w+){0,2} (?:in|inside|within|from) (?:the |any |retrieved |provided )*(?:documents?|context|"
        r"sources?|tool results?|search results?|retrieved content)\b",
    )),
))
# A line that says *not* to do it ("Never use markdown") isn't a repeat.
_NEGATION = re.compile(r"\b(?:no|not|never|don['’]?t|do not|without|avoid)\b", re.I)
_CLAUSE_END = re.compile(r"[.!?;:\n]")


def _masked(text: str) -> str:
    """``text`` with template syntax and code blanked out, keeping every offset and line break.

    Masks ``{{ … }}``, ``{% … %}``, ``{# … #}``, inline code, and fenced code (an unclosed fence runs to the
    end). Linear in the text: once a closer is missing after one opener it is missing after every later one.
    """
    parts: list[str] = []
    done = pos = 0
    missing: set[str] = set()
    while (match := _MASK_OPENER.search(text, pos)) is not None:
        start, opener = match.start(), match.group(0)
        closer = _TEMPLATE_CLOSERS.get(opener)
        if closer is not None:
            found = -1 if closer in missing else text.find(closer, start + 2)
            if found < 0:
                missing.add(closer)
                pos = start + 1
                continue
            end = found + 2
        elif opener in ("```", "~~~"):
            found = text.find(opener, start + 3)
            end = len(text) if found < 0 else found + 3
        else:
            end = match.end()
        parts.append(text[done:start])
        parts.append(re.sub(r"[^\n]", " ", text[start:end]))
        done = pos = end
    parts.append(text[done:])
    return "".join(parts)


def _line(text: str, offset: int) -> int:
    """The 1-based line ``offset`` falls on."""
    return text.count("\n", 0, offset) + 1


def _blank_words(inner: str) -> bool:
    """Whether a bracket's inside reads like a blank to fill (``support email``), not a number or a symbol."""
    inner = inner.strip()
    return bool(inner) and len(inner.split()) <= 6 and bool(_BLANK_WORDS.fullmatch(inner))


def _angle_blank(inner: str, text: str) -> bool:
    """Whether ``<inner>`` is a blank: a few words, or one word that isn't a known tag or one the text closes."""
    if not inner[:1].isalpha() or not _blank_words(inner):
        return False
    if " " in inner.strip():
        return True
    name = inner.strip().lower()
    return name not in _KNOWN_TAGS and f"</{name}>" not in text.lower()


def _placeholders(text: str, scan: str, persona: bool) -> list[dict]:
    """Blanks left in the prompt, one per distinct text, by line."""
    found: list[tuple[int, str]] = []
    for match in _BRACKET.finditer(scan):
        if _blank_words(match.group(1)):
            found.append((match.start(), match.group(0)))
    for match in _ANGLE.finditer(scan):
        if _angle_blank(match.group(1), text):
            found.append((match.start(), match.group(0)))
    if persona:
        for match in _BRACE.finditer(scan):
            if match.group(1)[:1].isalpha() and _blank_words(match.group(1)):
                found.append((match.start(), match.group(0)))
    for match in _MARKER.finditer(scan):
        found.append((match.start(), match.group(0)))
    out: list[dict] = []
    seen: set[str] = set()
    for offset, raw in sorted(found):
        blank = clean_text(text[offset:offset + len(raw)], TEXT_MAX)
        if blank.casefold() in seen:
            continue
        seen.add(blank.casefold())
        out.append({"code": PLACEHOLDER, "text": blank, "line": _line(text, offset)})
    return out


def _negated(scan: str, start: int) -> bool:
    """Whether the clause a match starts in says not to, before the match ("Never use markdown")."""
    clause_start = max((m.end() for m in _CLAUSE_END.finditer(scan, 0, start)), default=0)
    return bool(_NEGATION.search(scan, clause_start, start))


def _first_match(pattern: re.Pattern, scan: str) -> Optional[int]:
    """The offset of the first match of ``pattern`` that isn't negated, or None."""
    for match in pattern.finditer(scan):
        if not _negated(scan, match.start()):
            return match.start()
    return None


def _repeats(text: str, scan: str) -> list[dict]:
    """Lines of a persona that repeat what DocsGPT adds, one per topic at its first line, by line."""
    out: list[dict] = []
    for topic, pattern in _BUILTIN_TOPICS:
        offset = _first_match(pattern, scan)
        if offset is not None:
            out.append({"code": REPEATS_BUILTIN, "topic": topic, "line": _line(text, offset)})
    return sorted(out, key=lambda check: check["line"])


def edit_problems(before: str, after: str, how: str) -> list[str]:
    """What a change to a saved prompt must not do, as problems for the model: blanks it adds, and the retrieved
    documents' marker it drops.

    A blank the prompt already had isn't blamed on the change. Dropping the last ``{summaries}`` (or another
    documents variable) moves the documents out of the prompt the author placed them in.

    Args:
        before: The prompt's text before the change.
        after: Its text after.
        how: What the model should do instead of a blank, e.g. "Ask the user for it with ask_user".

    Returns:
        One sentence per problem; empty when the change is fine.
    """
    from docsgpt.api.answer.services.prompt_renderer import prompt_embeds_documents

    problems: list[str] = []
    had = {check["text"].casefold() for check in prompt_checks(before) if check["code"] == PLACEHOLDER}
    added = [check["text"] for check in prompt_checks(after)
             if check["code"] == PLACEHOLDER and check["text"].casefold() not in had]
    if added:
        problems.append(f"The change adds the blank {', '.join(added)}: never leave placeholders in a prompt. "
                        f"{how}, or write around it (e.g. \"point them to the support team\").")
    if prompt_embeds_documents(before) and not prompt_embeds_documents(after):
        problems.append("Keep {summaries} (or another documents variable such as {{ source.summaries }}): it is "
                        "where DocsGPT puts the retrieved documents, not a placeholder.")
    return problems


def prompt_checks(content: str) -> list[dict]:
    """The model-free checks on a prompt's text.

    Args:
        content: The prompt as the editor holds it.

    Returns:
        At most :data:`MAX_CHECKS` checks, in :data:`CODES` order and then by line:

        - ``{"code": "placeholder", "text": "[support email]", "line": 4}``: a blank left in
          (``[…]``, ``<…>``, ``{…}`` in a persona, ``TODO``/``TBD``/``XXX``);
        - ``{"code": "repeats_builtin", "topic": "date" | "citations" | "formatting" | "data_guard", "line": n}``:
          a persona line DocsGPT already adds;
        - ``{"code": "template_invalid"}``: the template syntax doesn't parse;
        - ``{"code": "tool_variables", "variables": ["{{ tools.x.y }}"]}``: tools a template runs before every
          message (informational), leaving out the ones DocsGPT's built-in prompts use;
        - ``{"code": "boundaries_missing"}`` / ``{"code": "citations_missing"}``: a template without the
          Boundaries section, or without ``{{ source.citation_rules }}``.
    """
    if not isinstance(content, str) or not content.strip():
        return []
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    template = is_template(text)
    scan = _masked(text)
    checks = _placeholders(text, scan, persona=not template)
    if not template:
        checks += _repeats(text, scan)
    else:
        if not template_parses(text):
            checks.append({"code": TEMPLATE_INVALID})
        variables = sorted(tool_variables(text) - _builtin_tool_variables(),
                           key=lambda usage: (usage[0], usage[1] or ""))
        if variables:
            checks.append({"code": TOOL_VARIABLES, "variables": [tool_variable(usage) for usage in variables]})
        if not has_boundaries(text):
            checks.append({"code": BOUNDARIES_MISSING})
        if CITATION_MARKER not in text:
            checks.append({"code": CITATIONS_MISSING})
    return checks[:MAX_CHECKS]
