"""Per-agent topic lists for the ``topic`` question, and the effective topic of a follow-up message.

``auto`` derives the sections from the agent's sources exactly as arc-decide's training and eval sets did
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
from docsgpt.analytics.config import TOPIC_DESCRIPTION_UNITS, AnalyticsConfig

#: Path parts that name no section of their own.
SKIPPED_DIRS = ("docs", "content", "src", "en")
ROOT_SECTION = "overview"
#: Page titles shown per section.
TOPIC_TITLES = 5
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


def auto_topics(sources: list[dict], max_topics: int) -> dict[str, str]:
    """The ``auto`` topic list of an agent's sources: section name to description, sorted by name.

    In an agent with several sources, a flat one (every page at its root) is one section named after the
    source. With more than ``max_topics`` sections the largest by tokens are kept; the rest fall into "none of
    these". Fewer than two sections give no list, since a choice with one real option says nothing.

    Args:
        sources: Source rows with ``name`` and ``directory_structure``.
        max_topics: Most sections kept (``ANALYTICS_MAX_TOPICS``).

    Returns:
        ``{section: description}``, empty when the agent gets no topic question.
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
    if len(sections) < 2:
        return {}
    kept = sorted(sections, key=lambda name: (-sections[name]["tokens"], name))[:max_topics]
    return {name: _describe(name, sections[name]["titles"]) for name in sorted(kept)}


def agent_sources(conn, agent: dict) -> list[dict]:
    """The sources an agent retrieves from (``source_id`` and ``extra_source_ids``), with their structure."""
    from docsgpt.storage.db.repositories.sources import SourcesRepository

    ids = [agent.get("source_id")] + list(agent.get("extra_source_ids") or [])
    ids = list(dict.fromkeys(str(i) for i in ids if i))
    return SourcesRepository(conn).list_by_ids(ids) if ids else []


def suggestions(conn, agent: dict) -> list[dict[str, str]]:
    """The ``auto`` list as ``[{name, description}]``, for the editor's "Suggest from sources"."""
    from docsgpt.core.settings import settings

    topics = auto_topics(agent_sources(conn, agent), settings.ANALYTICS_MAX_TOPICS)
    return [{"name": name, "description": description} for name, description in topics.items()]


def options(conn, agent: Optional[dict], config: AnalyticsConfig) -> dict[str, Optional[str]]:
    """The options of an agent's topic question, without "none of these"; empty when none is asked.

    Conversations without an agent, and agents in mode ``off``, get none. ``custom`` uses the owner's list as it
    is, a single topic included; ``auto`` derives the list from the agent's sources.
    """
    from docsgpt.core.settings import settings

    if agent is None or config.topics.mode == "off":
        return {}
    if config.topics.mode == "custom":
        items = sorted(config.topics.items, key=lambda t: t.name.lower())
        return {t.name: t.description or None for t in items[: settings.ANALYTICS_MAX_TOPICS]}
    return dict(auto_topics(agent_sources(conn, agent), settings.ANALYTICS_MAX_TOPICS))


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
