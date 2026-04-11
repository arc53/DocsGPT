"""Tests for ``application.core.db_uri``.

DocsGPT has two Postgres connection strings — ``POSTGRES_URI`` (consumed
by SQLAlchemy) and ``PGVECTOR_CONNECTION_STRING`` (consumed by
``psycopg.connect()`` directly). They need opposite normalization
because SQLAlchemy requires a ``postgresql+psycopg://`` dialect prefix
and libpq rejects it. Each field has its own normalizer so operators
can write whichever form feels natural and cross-pollination between
the two fields is forgiven.

The normalizers live in ``application.core.db_uri`` as plain functions
so these tests can exercise them directly without having to instantiate
``Settings`` (which would pull in ``.env`` file side effects).
"""

from __future__ import annotations

import pytest

from application.core.db_uri import (
    normalize_pgvector_connection_string,
    normalize_postgres_uri,
)


@pytest.mark.unit
class TestNormalizePostgresUri:
    @pytest.mark.parametrize(
        "input_value,expected",
        [
            # User-friendly forms get rewritten to the SQLAlchemy dialect.
            (
                "postgres://u:p@h:5432/d",
                "postgresql+psycopg://u:p@h:5432/d",
            ),
            (
                "postgresql://u:p@h:5432/d",
                "postgresql+psycopg://u:p@h:5432/d",
            ),
            # Legacy psycopg2 dialect is silently upgraded — psycopg2 is
            # no longer in requirements.txt, so there's no way it can work
            # as-is, and rewriting is friendlier than failing.
            (
                "postgresql+psycopg2://u:p@h:5432/d",
                "postgresql+psycopg://u:p@h:5432/d",
            ),
            # Already-correct dialect passes through unchanged.
            (
                "postgresql+psycopg://u:p@h:5432/d",
                "postgresql+psycopg://u:p@h:5432/d",
            ),
            # Whitespace is trimmed before rewriting.
            (
                "  postgres://u:p@h/d  ",
                "postgresql+psycopg://u:p@h/d",
            ),
            # Query-string params (sslmode, options) are preserved verbatim.
            (
                "postgresql://u:p@h:5432/d?sslmode=require&application_name=docsgpt",
                "postgresql+psycopg://u:p@h:5432/d?sslmode=require&application_name=docsgpt",
            ),
        ],
    )
    def test_rewrites_common_forms_to_psycopg_dialect(self, input_value, expected):
        assert normalize_postgres_uri(input_value) == expected

    @pytest.mark.parametrize(
        "input_value",
        [None, "", "   ", "None", "none"],
    )
    def test_empty_or_none_like_returns_none(self, input_value):
        assert normalize_postgres_uri(input_value) is None

    def test_unknown_scheme_passes_through(self):
        """A dialect we don't recognise is left alone so SQLAlchemy can
        produce its own error message when the engine tries to connect.
        Better than silently eating the config."""
        weird = "postgresql+asyncpg://u:p@h/d"
        assert normalize_postgres_uri(weird) == weird

    def test_non_string_input_passes_through(self):
        """Non-string inputs (e.g. if pydantic ever passes an int) shouldn't
        crash the normalizer — let pydantic's own type validation handle it."""
        assert normalize_postgres_uri(42) == 42  # type: ignore[arg-type]


@pytest.mark.unit
class TestNormalizePgvectorConnectionString:
    """Symmetric to the POSTGRES_URI normalizer but pulls in the OPPOSITE
    direction: strips the SQLAlchemy dialect prefix so libpq accepts it.
    """

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            # User-friendly forms pass through — libpq accepts them natively.
            (
                "postgres://u:p@h:5432/d",
                "postgres://u:p@h:5432/d",
            ),
            (
                "postgresql://u:p@h:5432/d",
                "postgresql://u:p@h:5432/d",
            ),
            # SQLAlchemy dialect prefixes get stripped so libpq accepts them.
            # Operators hit this when they copy POSTGRES_URI → PGVECTOR_CONNECTION_STRING.
            (
                "postgresql+psycopg://u:p@h:5432/d",
                "postgresql://u:p@h:5432/d",
            ),
            (
                "postgresql+psycopg2://u:p@h:5432/d",
                "postgresql://u:p@h:5432/d",
            ),
            # Whitespace is trimmed before rewriting.
            (
                "  postgresql+psycopg://u:p@h/d  ",
                "postgresql://u:p@h/d",
            ),
            # Query-string params (sslmode, etc.) are preserved verbatim.
            (
                "postgresql+psycopg://u:p@h:5432/d?sslmode=require",
                "postgresql://u:p@h:5432/d?sslmode=require",
            ),
        ],
    )
    def test_rewrites_dialect_forms_to_libpq_compatible(self, input_value, expected):
        assert normalize_pgvector_connection_string(input_value) == expected

    @pytest.mark.parametrize(
        "input_value",
        [None, "", "   ", "None", "none"],
    )
    def test_empty_or_none_like_returns_none(self, input_value):
        assert normalize_pgvector_connection_string(input_value) is None

    def test_unknown_scheme_passes_through(self):
        """A scheme we don't recognise is left alone so libpq can produce
        its own error message when the connection is attempted."""
        weird = "mysql://u:p@h/d"
        assert normalize_pgvector_connection_string(weird) == weird

    def test_non_string_input_passes_through(self):
        assert normalize_pgvector_connection_string(42) == 42  # type: ignore[arg-type]
