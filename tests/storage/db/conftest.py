"""Fixtures for repository tests.

These tests exercise real SQL against a real Postgres schema. They used
to require a long-running Postgres (via ``POSTGRES_URI``) — that is no
longer the case. They now piggy-back on the ephemeral ``pg_conn`` fixture
defined in the root ``tests/conftest.py`` (backed by pytest-postgresql),
so CI and local runs don't need any external Postgres service.

Each test still runs inside a transaction that rolls back on teardown,
keeping tests hermetic.
"""

from __future__ import annotations
