"""User-data Postgres and schema management at startup."""

from __future__ import annotations

from typing import Optional

from pydantic import Field, field_validator

from docsgpt.core.db_uri import normalize_postgres_uri
from docsgpt.core.settings._shared import SettingsGroup


class DatabaseSettings(SettingsGroup):
    """The Postgres database holding users, conversations and sources, and what startup may do to it."""

    POSTGRES_URI: Optional[str] = Field(default=None, description="User-data Postgres connection URI.")
    AUTO_MIGRATE: bool = Field(
        default=True,
        description="On startup, apply pending Alembic migrations. Disable if you manage schema out-of-band.",
    )
    AUTO_CREATE_DB: bool = Field(
        default=True,
        description="On startup, create the target Postgres database if missing (needs CREATEDB privilege).",
    )
    AUTO_VECTOR_SCHEMA: bool = Field(
        default=True,
        description=(
            "On startup, create the pgvector/graph tables and verify the embedding dimension. No Alembic "
            "migration covers the vector DB (it may be a separate cluster); set False to manage it yourself."
        ),
    )

    @field_validator("POSTGRES_URI", mode="before")
    @classmethod
    def _normalize_postgres_uri(cls, v):
        return normalize_postgres_uri(v)
