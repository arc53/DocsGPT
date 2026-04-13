"""Normalize user-supplied Postgres URIs for different drivers.

DocsGPT has two Postgres connection strings pointing at potentially
different databases:

* ``POSTGRES_URI`` feeds SQLAlchemy, which needs the
  ``postgresql+psycopg://`` dialect prefix to pick the psycopg v3 driver.
* ``PGVECTOR_CONNECTION_STRING`` feeds ``psycopg.connect()`` directly
  (via libpq) in ``application/vectorstore/pgvector.py``. libpq only
  understands ``postgres://`` and ``postgresql://`` — the SQLAlchemy
  dialect prefix is an invalid URI from its point of view.

The two fields therefore need opposite normalization so operators don't
have to know which driver a given field feeds. Each normalizer also
silently upgrades the legacy ``postgresql+psycopg2://`` prefix since
psycopg2 is no longer in the project.

This module is deliberately separate from ``application/core/settings.py``
so the Settings class stays focused on field declarations, and the
URI-rewriting logic can be unit-tested without triggering ``.env``
file loading from importing Settings.
"""

from __future__ import annotations


def _rewrite_uri_prefixes(v, rewrites):
    """Shared URI prefix rewriter used by both normalizers below.

    Strips whitespace, returns ``None`` for empty / ``"none"`` values,
    applies the first matching rewrite, and passes unrecognised input
    through so downstream consumers (SQLAlchemy, libpq) can produce
    their own error messages rather than us silently eating a
    misconfiguration.
    """
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    v = v.strip()
    if not v or v.lower() == "none":
        return None
    for prefix, target in rewrites:
        if v.startswith(prefix):
            return target + v[len(prefix):]
    return v


# POSTGRES_URI feeds SQLAlchemy, which needs a ``postgresql+psycopg://``
# dialect prefix to select the psycopg v3 driver. Normalize the
# operator-friendly forms TOWARD that dialect.
_POSTGRES_URI_REWRITES = (
    ("postgresql+psycopg2://", "postgresql+psycopg://"),
    ("postgresql://", "postgresql+psycopg://"),
    ("postgres://", "postgresql+psycopg://"),
)


# PGVECTOR_CONNECTION_STRING feeds ``psycopg.connect()`` directly in
# application/vectorstore/pgvector.py — NOT SQLAlchemy. libpq only
# understands ``postgres://`` and ``postgresql://``; the SQLAlchemy
# dialect prefix is an invalid URI from libpq's point of view. Strip it
# if the operator accidentally copied their POSTGRES_URI value here.
_PGVECTOR_CONNECTION_STRING_REWRITES = (
    ("postgresql+psycopg2://", "postgresql://"),
    ("postgresql+psycopg://", "postgresql://"),
)


def normalize_postgres_uri(v):
    """Normalize a user-supplied POSTGRES_URI to the SQLAlchemy psycopg3 form.

    Accepts the forms operators naturally write (``postgres://``,
    ``postgresql://``) and rewrites them to ``postgresql+psycopg://``.
    Unknown schemes pass through unchanged so SQLAlchemy can produce its
    own dialect-not-found error.
    """
    return _rewrite_uri_prefixes(v, _POSTGRES_URI_REWRITES)


def normalize_pgvector_connection_string(v):
    """Normalize a user-supplied PGVECTOR_CONNECTION_STRING for libpq.

    Strips the SQLAlchemy dialect prefix if the operator accidentally
    copied their POSTGRES_URI value here — libpq can't parse it.
    User-friendly forms (``postgres://``, ``postgresql://``) pass
    through unchanged since libpq accepts them natively.
    """
    return _rewrite_uri_prefixes(v, _PGVECTOR_CONNECTION_STRING_REWRITES)
