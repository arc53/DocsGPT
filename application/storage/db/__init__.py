"""PostgreSQL storage layer for user-level data.

This package holds the SQLAlchemy Core engine, metadata, repositories, and
migration infrastructure for the user-data Postgres database. It is separate
from ``application/vectorstore/pgvector.py`` — the two may point at the same
cluster or at different clusters depending on operator configuration.

Repository modules are added in later phases
as individual collections are ported.
"""
