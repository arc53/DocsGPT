"""Connection settings for each vector store backend."""

from __future__ import annotations

from typing import Optional

from pydantic import Field, field_validator

from docsgpt.core.db_uri import normalize_pgvector_connection_string
from docsgpt.core.paths import home_dir
from docsgpt.core.settings._shared import SettingsGroup, normalize_secret


class VectorStoreSettings(SettingsGroup):
    """Per-backend connection details; only the backend named by VECTOR_STORE is read."""

    MONGO_URI: Optional[str] = Field(
        default=None,
        description=(
            "Only consulted when VECTOR_STORE=mongodb or when running scripts/db/backfill.py; user data lives "
            "in Postgres."
        ),
    )

    # Elasticsearch.
    ELASTIC_CLOUD_ID: Optional[str] = Field(default=None, description="Elastic Cloud id.")
    ELASTIC_USERNAME: Optional[str] = Field(default=None, description="Elasticsearch username.")
    ELASTIC_PASSWORD: Optional[str] = Field(default=None, description="Elasticsearch password.")
    ELASTIC_URL: Optional[str] = Field(default=None, description="Elasticsearch URL.")
    ELASTIC_INDEX: str = Field(default="docsgpt", description="Elasticsearch index name.")

    # Qdrant.
    QDRANT_COLLECTION_NAME: str = Field(default="docsgpt", description="Qdrant collection name.")
    QDRANT_LOCATION: Optional[str] = Field(default=None, description="Qdrant location (':memory:' or a URL).")
    QDRANT_URL: Optional[str] = Field(default=None, description="Qdrant server URL.")
    QDRANT_PORT: int = Field(default=6333, description="Qdrant REST port.")
    QDRANT_GRPC_PORT: int = Field(default=6334, description="Qdrant gRPC port.")
    QDRANT_PREFER_GRPC: bool = Field(default=False, description="Use gRPC instead of REST where possible.")
    QDRANT_HTTPS: Optional[bool] = Field(default=None, description="Use HTTPS for the Qdrant connection.")
    QDRANT_API_KEY: Optional[str] = Field(default=None, description="Qdrant API key.")
    QDRANT_PREFIX: Optional[str] = Field(default=None, description="URL prefix for a Qdrant behind a proxy.")
    QDRANT_TIMEOUT: Optional[float] = Field(default=None, description="Qdrant request timeout in seconds.")
    QDRANT_HOST: Optional[str] = Field(default=None, description="Qdrant host (alternative to QDRANT_URL).")
    QDRANT_PATH: Optional[str] = Field(default=None, description="Path for an embedded on-disk Qdrant.")
    QDRANT_DISTANCE_FUNC: str = Field(default="Cosine", description="Qdrant distance function.")

    # PGVector.
    PGVECTOR_CONNECTION_STRING: Optional[str] = Field(
        default=None,
        description=(
            "pgvector connection string. postgres://, postgresql:// and postgresql+psycopg:// are all accepted "
            "and normalized internally for psycopg.connect(). Unset falls back to POSTGRES_URI."
        ),
    )
    PGVECTOR_POOL_MAX_SIZE: int = Field(
        default=8, ge=0, description="Per-process connection pool size; 0 uses one direct connection per store."
    )
    PGVECTOR_IVFFLAT_PROBES: Optional[int] = Field(
        default=None,
        description="IVFFlat probes; unset derives sqrt(lists) from the index. Higher means better recall, more scan.",
    )

    # Milvus.
    MILVUS_COLLECTION_NAME: str = Field(default="docsgpt", description="Milvus collection name.")
    MILVUS_URI: Optional[str] = Field(
        default_factory=lambda: str(home_dir() / "milvus_local.db"),
        description=(
            "Milvus server URI. The default is a milvus-lite (embedded) database file under the data home, "
            "like the other local stores."
        ),
    )
    MILVUS_TOKEN: str = Field(default="", description="Milvus auth token.")

    # LanceDB.
    LANCEDB_PATH: str = Field(
        default_factory=lambda: str(home_dir() / "data" / "lancedb"),
        description="LanceDB local data directory.",
    )
    LANCEDB_TABLE_NAME: str = Field(default="docsgpts", description="LanceDB table for stored vectors.")

    @field_validator("PGVECTOR_CONNECTION_STRING", mode="before")
    @classmethod
    def _normalize_pgvector_connection_string(cls, v):
        return normalize_pgvector_connection_string(v)

    @field_validator("QDRANT_API_KEY", mode="before")
    @classmethod
    def _normalize_vectorstore_secrets(cls, v):
        return normalize_secret(v)
