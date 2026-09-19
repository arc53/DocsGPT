"""Canonical entity naming for the per-source knowledge graph.

Nodes are merged on ``normalized_name``, which has been ``name.lower()``. That
splits entities a reader would call the same thing: measured on the DocsGPT docs
corpus, ``agent``/``agents``, ``VECTOR_STORE``/``Vector store``/``vector stores``,
``Celery worker``/``Celery workers`` and ``.env file``/``env_file`` all landed as
separate nodes — 58 such collisions across 1,704 entities, with 75% of entities
appearing in exactly one chunk as a result.

:func:`canonical_name` folds the differences that are purely orthographic:
case, surrounding punctuation, underscore/hyphen word breaks, and a *cautious*
plural. Cautious matters: this corpus contains ``postgres``, ``kubernetes``,
``https`` and ``aws``, none of which are plurals, so a naive "strip trailing s"
would corrupt them into new entities rather than merge anything.

Always on: every graph is built with canonical names.
"""

from __future__ import annotations

import re

_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_UNDERSCORE = re.compile(r"[_\-]+")
_SPACE = re.compile(r"\s+")

#: Words that end in "s" without being plural. Singularising these would invent
#: entities ("postgre", "kubernete") instead of merging existing ones.
_NOT_PLURAL = frozenset(
    {
        "postgres", "kubernetes", "https", "aws", "dns", "tls", "cors", "css",
        "js", "sas", "gas", "ss", "class", "access", "process", "status",
        "analysis", "basis", "axis", "https", "rss", "less", "express",
        "redis", "nats", "kibana", "elasticsearch", "os", "ios", "macos",
        "always", "sometimes", "series", "docs", "ops", "devops", "sse",
    }
)


def _singular(word: str) -> str:
    """Best-effort singular of one word, biased hard towards leaving it alone.

    Only the endings that are unambiguous in this domain are touched:
    ``-ies`` -> ``-y`` (``policies``), ``-ses``/``-xes``/``-zes``/``-ches``/
    ``-shes`` -> drop ``es`` (``indexes``, ``batches``), and a bare trailing
    ``s`` on a word long enough to be safe. Everything in :data:`_NOT_PLURAL`,
    and anything ending in ``ss``/``us``/``is``, is returned unchanged.
    """
    if len(word) < 4 or word in _NOT_PLURAL:
        return word
    if word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word


def canonical_name(name: str) -> str:
    """Merge key for an entity name.

    Args:
        name: The entity name as the model wrote it.

    Returns:
        A lowercase, punctuation-free, singularised key. Returns ``""`` for an
        empty or punctuation-only name, which callers treat as "no entity".

    Examples:
        ``VECTOR_STORE`` and ``Vector stores`` -> ``vector store``;
        ``.env file`` and ``env_file`` -> ``env file``;
        ``postgres`` stays ``postgres``.
    """
    if not name:
        return ""
    text = _UNDERSCORE.sub(" ", str(name))
    text = _PUNCT.sub(" ", text)
    text = _SPACE.sub(" ", text).strip().lower()
    if not text:
        return ""
    return " ".join(_singular(word) for word in text.split())


def normalize_entity_name(name: str) -> str:
    """The key an entity is merged on: its :func:`canonical_name`.

    Every graph the corpora were measured on was built this way, so it is the
    only mode rather than a flag. A graph built before this used plain
    ``lower()`` keys; re-extracting it merges onto these instead.
    """
    return canonical_name(name)
