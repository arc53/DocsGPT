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

The result is a merge key, never shown to anyone, so it only has to be the
same for a word's singular and plural — not to be a word itself.

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
        "alias", "canvas", "atlas", "bias", "pandas",
    }
)

#: Plural endings that drop ``es``, and the singular endings that meet them.
#: ``caches`` cannot say whether it is ``cache`` + "s" or ``cach`` + "es"
#: (as ``batches`` is ``batch`` + "es"), so rather than guess, both
#: ``caches`` and ``cache`` fold to ``cach`` — as ``databases``/``database``
#: fold to ``databas``. Hardly any real word differs from one of these singulars
#: by its final "e" alone, so the fold merges next to nothing it should not.
_ES_PLURAL = ("ches", "shes", "ses", "zes", "xes")
_E_SINGULAR = ("che", "she", "se", "ze", "xe")


def _singular(word: str) -> str:
    """Fold one word so its singular and plural share a key, else leave it alone.

    ``-ies`` and a singular's ``-ie`` both fold to ``-y`` (``policies``,
    ``cookies``/``cookie``). The ``-es`` endings in :data:`_ES_PLURAL` drop
    ``es`` and the singular endings in :data:`_E_SINGULAR` drop their ``e``, so
    both sides of an ambiguous plural meet (``caches``/``cache`` -> ``cach``).
    Otherwise a bare trailing ``s`` is dropped on a word long enough to be
    safe. Everything in :data:`_NOT_PLURAL`, and anything ending in
    ``ss``/``us``/``is``, is returned unchanged.
    """
    if len(word) < 4 or word in _NOT_PLURAL:
        return word
    if word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(_ES_PLURAL):
        return word[:-2]
    if word.endswith("ie") and len(word) > 4:
        return word[:-2] + "y"
    if word.endswith(_E_SINGULAR):
        return word[:-1]
    if word.endswith("s"):
        return word[:-1]
    return word


def canonical_name(name: str) -> str:
    """Merge key for an entity name.

    Args:
        name: The entity name as the model wrote it.

    Returns:
        A lowercase, punctuation-free key shared by a name's singular and
        plural. Returns ``""`` for an empty or punctuation-only name, which
        callers treat as "no entity".

    Examples:
        ``VECTOR_STORE`` and ``Vector stores`` -> ``vector store``;
        ``.env file`` and ``env_file`` -> ``env file``;
        ``cache`` and ``caches`` -> ``cach``;
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
