"""Repositories for the user-data Postgres database.

Each module in this package exposes exactly one repository class. Repository
methods take a ``Connection`` (either as a constructor argument or as a
method argument) and return plain ``dict`` rows via
``application.storage.db.base_repository.row_to_dict`` during the
MongoDB→Postgres cutover, so call sites don't have to change shape.

Repositories are added one collection at a time, matching the phased
rollout in ``migration-postgres.md``.
"""
