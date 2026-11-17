"""The prompt edit engine: checks a model's ``{find, replace, reason}`` edits against a prompt and applies them,
checks the text a change makes, and names what the change does to the prompt's mode.

Shared by the prompt recipe (improve and review, ``docsgpt/drafter/prompt_recipe.py``) and the agent recipe (edits
to the agent's own prompt, a new prompt in its place).
"""

from __future__ import annotations

from typing import Sequence

from docsgpt.drafter.catalog import is_template
from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.prompt_checks import edit_problems
from docsgpt.drafter.prompt_rules import (
    CITATION_MARKER,
    has_boundaries,
    TEMPLATE_PROBLEM,
    template_parses,
    tool_variables_problem,
)
from docsgpt.drafter.recipe import DraftRequest, ProposalInvalid

#: Most characters of a prompt the drafter writes.
CONTENT_MAX = 20000
#: Most edits one proposal sends, and characters of a reason (an edit's, or a written prompt's).
MAX_EDITS = 20
REASON_MAX = 300
#: What a change that needs a detail only the user knows does instead of a blank, by mode.
ASK_INSTEAD = {"improve": "Ask the user for it with ask_user", "review": "Give its finding an ask instead"}

#: ``checks`` codes, in the order they are reported.
CHECK_TO_TEMPLATE = "to_template"
CHECK_TO_PERSONA = "to_persona"
CHECK_BOUNDARIES_REMOVED = "boundaries_removed"
CHECK_CITATIONS_REMOVED = "citations_removed"


def checks_for(before: str, after: str) -> list[str]:
    """What a change does to a prompt that the user should know, as ``checks`` codes.

    Args:
        before: The prompt's text before the change ('' for a new prompt).
        after: Its text after.

    Returns:
        Codes, in a fixed order: a switch into or out of template mode, and
        the Boundaries or citation rules taken out of a template.
    """
    was, now = is_template(before), is_template(after)
    out: list[str] = []
    if now and not was:
        out.append(CHECK_TO_TEMPLATE)
    if was and not now:
        out.append(CHECK_TO_PERSONA)
    if now and has_boundaries(before) and not has_boundaries(after):
        out.append(CHECK_BOUNDARIES_REMOVED)
    if now and CITATION_MARKER in before and CITATION_MARKER not in after:
        out.append(CHECK_CITATIONS_REMOVED)
    return out


def _occurrences(content: str, find: str) -> list[int]:
    """Start offsets of ``find`` in ``content``, overlapping matches included (stops at two)."""
    starts: list[int] = []
    index = content.find(find)
    while index != -1 and len(starts) < 2:
        starts.append(index)
        index = content.find(find, index + 1)
    return starts


def _clean_replacement(text: str) -> str:
    """An edit's ``replace`` cleaned as :func:`clean_text` cleans text, keeping the spaces and line breaks around
    it, which place the change in the prompt."""
    core = text.strip()
    if not core:
        return "".join(ch for ch in text if ch in " \t\n")
    start = text.index(core[0])
    lead = "".join(ch for ch in text[:start] if ch in " \t\n")
    trail = "".join(ch for ch in text[start + len(core):] if ch in " \t\n")
    return lead + clean_text(core, len(core)) + trail


def apply_edits(content: str, edits: list[dict]) -> tuple[list[dict], str]:
    """Check edits against ``content`` and apply them (:func:`apply_numbered_edits` without the numbering).

    Args:
        content: The current prompt.
        edits: ``{find, replace, reason}`` dicts from the model.

    Returns:
        ``(edits, result)``.

    Raises:
        ProposalInvalid: As :func:`apply_numbered_edits`.
    """
    out, result, _ = apply_numbered_edits(content, edits)
    return out, result


def apply_numbered_edits(content: str, edits: list[dict]) -> tuple[list[dict], str, dict[int, str]]:
    """Check edits against ``content`` and apply them.

    Args:
        content: The current prompt.
        edits: ``{find, replace, reason}`` dicts from the model.

    Returns:
        ``(edits, result, ids)``: the edits that change something, in text order
        with ids ``e1``…, the text with all of them applied, and each model
        edit's position in ``edits`` (1 for the first) -> its id; an edit that
        changes nothing has none.

    Raises:
        ProposalInvalid: Too many edits, a find that doesn't occur exactly
            once, a missing reason, overlapping edits, an empty result, or a
            result over :data:`CONTENT_MAX` that is longer than ``content``.
    """
    if len(edits) > MAX_EDITS:
        raise ProposalInvalid([f"Send at most {MAX_EDITS} edits; merge nearby changes."])
    problems: list[str] = []
    spans: list[tuple[int, int, dict]] = []
    for number, edit in enumerate(edits, start=1):
        find = str(edit.get("find") or "").replace("\r\n", "\n")
        replace = _clean_replacement(str(edit.get("replace") or "").replace("\r\n", "\n"))
        if find == replace:
            continue
        label = f"Edit {number} ({find[:60]!r})"
        if not find:
            problems.append(f"Edit {number}: find can't be empty; anchor an insertion on nearby text.")
            continue
        starts = _occurrences(content, find)
        if not starts:
            problems.append(f"{label}: find was not found in the current prompt; copy it exactly.")
            continue
        if len(starts) > 1:
            count = content.count(find)
            problems.append(f"{label}: find occurs {max(count, 2)} times; quote a longer passage that occurs once.")
            continue
        reason = clean_text(edit.get("reason"), REASON_MAX)
        if not reason:
            problems.append(f"{label}: give a reason.")
            continue
        spans.append((starts[0], starts[0] + len(find), {"find": find, "replace": replace, "reason": reason,
                                                         "_n": number}))
    spans.sort(key=lambda span: span[0])
    for (_, prev_end, prev), (start, _, edit) in zip(spans, spans[1:]):
        if start < prev_end:
            problems.append(
                f"The edits for {prev['find'][:40]!r} and {edit['find'][:40]!r} overlap; merge them into one edit."
            )
    if problems:
        raise ProposalInvalid(problems)
    parts: list[str] = []
    cursor = 0
    out: list[dict] = []
    ids: dict[int, str] = {}
    for index, (start, end, edit) in enumerate(spans, start=1):
        parts.append(content[cursor:start])
        parts.append(edit["replace"])
        cursor = end
        ids[edit["_n"]] = f"e{index}"
        out.append({"id": f"e{index}", "find": edit["find"], "replace": edit["replace"], "reason": edit["reason"]})
    parts.append(content[cursor:])
    result = "".join(parts)
    if not result.strip():
        raise ProposalInvalid(["The edits would leave the prompt empty."])
    if len(result) > CONTENT_MAX and len(result) > len(content):
        # A prompt saved longer than the cap (the prompt routes store any length) may still shrink or stay as long.
        if len(content) > CONTENT_MAX:
            raise ProposalInvalid([f"The prompt is already over {CONTENT_MAX} characters: edits can't make it longer."])
        raise ProposalInvalid([f"The prompt can be at most {CONTENT_MAX} characters."])
    return out, result, ids


def check_drafted_prompt(result: str, previous: str, req: DraftRequest, *, edited: bool,
                         ask_instead: str = "Ask the user for it", earlier: Sequence[str] = ()) -> None:
    """The rules every drafted prompt text follows, in the agent and prompt recipes alike.

    The template syntax must parse. Edits to a prompt whose text didn't parse
    before (a template with a stray ``{%``) leave the user's own mistake in
    place, so it isn't blamed on them; a whole new text is the model's alone:
    it is refused whenever it doesn't parse. It adds no tool variables the user
    didn't ask for, and edits never add a blank or drop the retrieved
    documents' marker (``prompt_checks.edit_problems``).

    Args:
        result: The drafted text.
        previous: The prompt's text before the change; tool variables already in it stay allowed.
        req: The draft request, whose messages may ask for tool variables.
        edited: Whether ``result`` is ``previous`` with edits applied, rather than a whole new text.
        ask_instead: What an edit that needs a detail only the user knows does instead of a blank.
        earlier: What the user wrote before this conversation, which counts as asking for tool variables too.

    Raises:
        ProposalInvalid: The text doesn't parse, adds tool variables the user didn't ask for, or (edits only) adds
            a blank or drops the documents' marker.
    """
    if not template_parses(result) and (not edited or not previous or template_parses(previous)):
        raise ProposalInvalid([TEMPLATE_PROBLEM])
    problem = tool_variables_problem(result, previous, req, earlier)
    if problem:
        raise ProposalInvalid([problem])
    problems = edit_problems(previous, result, ask_instead) if edited else []
    if problems:
        raise ProposalInvalid(problems)
