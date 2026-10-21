"""Per-agent options of the one-pick ``topic`` question, and the effective topic of a follow-up message.

The options are the owner's topics that don't overlap, then the agent's source folders. Folders are derived from the
agent's sources exactly as arc-decide's training and eval sets did
(``arcd/data/train_analytics.py``: ``_section``, ``doc_sections``; ``arcd/data/sim_convs.py``: ``_title``): a
section is the first directory of a page's path, described by up to five page titles. Bare folder names held topic
near 40% for every model; adding the titles raised it by 13 points.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import PurePosixPath
from typing import Any, Iterator, Optional

from docsgpt.analytics import schema
from docsgpt.analytics.config import TOPIC_DESCRIPTION_UNITS, TOPIC_NAME_CHARS, AnalyticsConfig

#: Path parts that name no section of their own.
SKIPPED_DIRS = ("docs", "content", "src", "en")
ROOT_SECTION = "overview"
#: Page titles shown per section.
TOPIC_TITLES = 5
#: Folders listed for the settings, largest first; far past the 15 a question can offer.
MAX_FOLDERS = 50
#: Reactions that make a message a continuation of the topic before it.
CONTINUATIONS = ("follow-up", "re-ask", "correction or pushback", "clarifies own question")


def section(path: str) -> str:
    """A page's documentation section: the first directory of its path, humanised (``ROOT_SECTION`` at the root)."""
    parts = [p for p in PurePosixPath(path).parts[:-1] if p not in SKIPPED_DIRS]
    head = parts[0] if parts else ROOT_SECTION
    return re.sub(r"^[\d._-]+", "", re.sub(r"[-_]+", " ", head)).strip().lower() or head


def page_title(path: str) -> str:
    """A page's title from its file name: leading digits stripped, ``-_`` turned into spaces, capitalised."""
    stem = PurePosixPath(path).stem.lstrip("0123456789-_.")
    return re.sub(r"[-_]+", " ", stem).strip().capitalize() or path


def _files(node: Any, prefix: str = "") -> Iterator[tuple[str, int]]:
    """``(path, token_count)`` of every file in a ``directory_structure``; a file is a dict with ``token_count``."""
    if not isinstance(node, dict):
        return
    for name, value in node.items():
        if not isinstance(value, dict):
            continue
        path = f"{prefix}/{name}" if prefix else str(name)
        if "token_count" in value:
            try:
                tokens = int(value.get("token_count") or 0)
            except (TypeError, ValueError):
                tokens = 0
            yield path, tokens
        else:
            yield from _files(value, path)


def _structure(source: dict) -> Any:
    structure = source.get("directory_structure")
    if isinstance(structure, str):
        try:
            return json.loads(structure)
        except ValueError:
            return None
    return structure


def _describe(name: str, titles: set[str]) -> str:
    """"Pages such as: " and up to ``TOPIC_TITLES`` titles, sorted; a larger section shows a seeded sample."""
    shown = sorted(titles)
    if len(shown) > TOPIC_TITLES:
        shown = sorted(random.Random(name).sample(shown, TOPIC_TITLES))
    return schema.cap("Pages such as: " + "; ".join(shown), TOPIC_DESCRIPTION_UNITS)


def _shorten(name: str, limit: int) -> str:
    """``name`` cut to ``limit`` characters with "…", on a word boundary when one is in its second half."""
    if len(name) <= limit:
        return name
    cut = name[:limit - 1]
    if not name[limit - 1].isspace():
        space = cut.rfind(" ")
        if space > limit // 2:
            cut = cut[:space]
    return cut.rstrip(" -_,.;:/(") + "…"


def _fitted(names: list[str]) -> dict[str, str]:
    """Each folder name mapped to one of at most ``TOPIC_NAME_CHARS`` characters, so it fits a topic's name.

    A folder is named after a directory or a whole source (an uploaded file's name, often longer), but its name is
    also what the owner hides it by, edits it into and filters Logs on, all capped at ``TOPIC_NAME_CHARS``. A longer
    one is cut; a cut name another folder already has gets " 2", " 3"…, given out in name order so the same sources
    always get the same names.

    Args:
        names: The folder names, unique.

    Returns:
        ``{name: fitted name}``; the fitted names are unique.
    """
    fitted = {name: name for name in names if len(name) <= TOPIC_NAME_CHARS}
    taken = set(fitted.values())
    for name in sorted(n for n in names if n not in fitted):
        short, n = _shorten(name, TOPIC_NAME_CHARS), 1
        while short in taken:
            n += 1
            suffix = f" {n}"
            short = _shorten(name, TOPIC_NAME_CHARS - len(suffix)) + suffix
        fitted[name] = short
        taken.add(short)
    return fitted


def folders(sources: list[dict]) -> list[dict[str, str]]:
    """The folders of an agent's sources, largest first by tokens: ``[{name, description}]``.

    In an agent with several sources, a flat one (every page at its root) is one folder named after the source. A
    name longer than a topic's is cut to fit (see :func:`_fitted`). At most ``MAX_FOLDERS`` are listed.

    Args:
        sources: Source rows with ``name`` and ``directory_structure``.

    Returns:
        The folders, each with its "Pages such as: …" description.
    """
    listed = [(source, list(_files(_structure(source)))) for source in sources]
    listed = [(source, files) for source, files in listed if files]
    sections: dict[str, dict[str, Any]] = {}
    for source, files in listed:
        flat = all(section(path) == ROOT_SECTION for path, _ in files)
        named = (source.get("name") or "").strip().lower()
        for path, tokens in files:
            name = named if flat and len(listed) > 1 and named else section(path)
            entry = sections.setdefault(name, {"titles": set(), "tokens": 0})
            entry["titles"].add(page_title(path))
            entry["tokens"] += tokens
    fitted = _fitted(list(sections))
    ordered = sorted(sections, key=lambda name: (-sections[name]["tokens"], fitted[name]))[:MAX_FOLDERS]
    return [{"name": fitted[name], "description": _describe(fitted[name], sections[name]["titles"])}
            for name in ordered]


def merge(own: list[tuple[str, Optional[str]]], folder_list: list[dict[str, str]], hidden: list[str],
          max_topics: int) -> dict[str, Optional[str]]:
    """The one-pick question's options: the owner's topics, then folders filling what is left, sorted by name.

    Folders are taken largest first (``folder_list`` is in that order), skipping hidden ones and any whose name an
    own topic already has. Fewer than two options give none, since a choice with one real option says nothing. The
    frontend's ``visibleFolders`` applies the same rule to show the list.

    Args:
        own: The owner's topics that don't overlap, as ``(name, description or None)``.
        folder_list: :func:`folders` of the agent's sources.
        hidden: Folder names the owner hid.
        max_topics: Most options (``ANALYTICS_MAX_TOPICS``).

    Returns:
        ``{name: description}``, empty when the agent gets no topic question.
    """
    options: dict[str, Optional[str]] = dict(own[:max_topics])
    taken = {name.lower() for name in options} | {name.lower() for name in hidden}
    for folder in folder_list:
        if len(options) >= max_topics:
            break
        if folder["name"].lower() not in taken:
            options[folder["name"]] = folder["description"]
            taken.add(folder["name"].lower())
    if len(options) < 2:
        return {}
    return {name: options[name] for name in sorted(options, key=str.lower)}


def agent_sources(conn, agent: dict) -> list[dict]:
    """The sources an agent retrieves from (``source_id`` and ``extra_source_ids``), with their structure."""
    from docsgpt.storage.db.repositories.sources import SourcesRepository

    ids = [agent.get("source_id")] + list(agent.get("extra_source_ids") or [])
    ids = list(dict.fromkeys(str(i) for i in ids if i))
    return SourcesRepository(conn).list_by_ids(ids) if ids else []


def folders_of(conn, agent: dict) -> list[dict[str, str]]:
    """:func:`folders` of an agent's sources, for the settings list."""
    return folders(agent_sources(conn, agent))


def options(conn, agent: Optional[dict], config: AnalyticsConfig) -> dict[str, Optional[str]]:
    """The options of an agent's topic question, without "none of these"; empty when none is asked.

    Conversations without an agent get none. The owner's topics that don't overlap come first, then the agent's
    source folders (a workflow has none).
    """
    from docsgpt.core.settings import settings

    if agent is None:
        return {}
    own = [(t.name, t.description or None) for t in config.one_pick()]
    return merge(own, folders_of(conn, agent), config.hidden_folders, settings.ANALYTICS_MAX_TOPICS)


def options_hash(value: Any) -> str:
    """A 12-hex sha256 of a topic option dict or a tag definition, in its order: what a stored row was asked with."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()[:12]


def continuation(reaction: Optional[dict[str, float]]) -> float:
    """``p_cont``: how likely a message continues the topic before it, from its reaction probabilities."""
    return sum((reaction or {}).get(k, 0.0) for k in CONTINUATIONS)


def effective(own: dict[str, float], opener: Optional[dict[str, float]], p_cont: float) -> dict[str, float]:
    """``p_cont * topic(opener) + (1 - p_cont) * topic(own)``: a terse follow-up takes its opener's topic.

    A probability mix, not a threshold, so expected counts stay sums of probabilities.
    """
    if opener is None or p_cont <= 0:
        return dict(own)
    return {k: p_cont * opener.get(k, 0.0) + (1 - p_cont) * own.get(k, 0.0) for k in dict.fromkeys([*own, *opener])}


def effective_topics(
    messages: list[tuple[Optional[dict[str, float]], Optional[str], Optional[dict[str, float]]]],
) -> list[Optional[dict[str, float]]]:
    """``topic_effective`` for each user message of a conversation, in order.

    The opener of a message is the conversation's first message, or the latest one whose reaction was mostly
    ``new question``; a message that is itself an opener keeps its own topic, and so does one whose opener was asked
    other options.

    Args:
        messages: Per message, its ``topic`` probabilities (``None`` when it has none), their ``options_hash`` and
            the reaction probabilities of the message to the answer before it (``None`` when there is none).

    Returns:
        Per message, its effective topic probabilities, or ``None`` where it has no topic.
    """
    out: list[Optional[dict[str, float]]] = []
    opener = 0
    for i, (own, own_hash, reaction) in enumerate(messages):
        if (reaction or {}).get("new question", 0.0) > 0.5:
            opener = i
        if own is None:
            out.append(None)
            continue
        first, first_hash, _ = messages[opener]
        usable = opener != i and first is not None and first_hash == own_hash
        out.append(effective(own, first if usable else None, continuation(reaction)))
    return out
