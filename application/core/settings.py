import os
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from application.core.db_uri import (  # noqa: E402
    normalize_pgvector_connection_string,
    normalize_postgres_uri,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    AUTH_TYPE: Optional[str] = None  # simple_jwt, session_jwt, or None
    LLM_PROVIDER: str = "docsgpt"
    LLM_NAME: Optional[str] = None  # if LLM_PROVIDER is openai, LLM_NAME can be gpt-4 or gpt-3.5-turbo
    EMBEDDINGS_NAME: str = "huggingface_sentence-transformers/all-mpnet-base-v2"
    EMBEDDINGS_BASE_URL: Optional[str] = None  # Remote embeddings API URL (OpenAI-compatible)
    EMBEDDINGS_KEY: Optional[str] = None  # api key for embeddings (if using openai, just copy API_KEY)
    # Optional directory of operator-supplied model YAMLs, loaded after the
    # built-in catalog under application/core/models/. Later wins on
    # duplicate model id. See application/core/models/README.md.
    MODELS_CONFIG_DIR: Optional[str] = None

    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    # Prefetch=1 caps SIGKILL loss to one task. Visibility timeout must exceed
    # the longest legitimate task runtime (ingest, agent webhook) but stay
    # short enough that SIGKILLed tasks redeliver promptly. 1h matches Onyx
    # and Dify defaults; long ingests can override via env.
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1
    CELERY_VISIBILITY_TIMEOUT: int = 3600
    # Recycle the prefork worker child once its resident size crosses this many
    # kilobytes — backstops native-heap growth from docling/torch parsing. 0 disables.
    CELERY_WORKER_MAX_MEMORY_PER_CHILD: int = 4194304
    # Recycle the child after this many tasks; 0 disables (memory cap is the primary knob).
    CELERY_WORKER_MAX_TASKS_PER_CHILD: int = 0
    # Only consulted when VECTOR_STORE=mongodb or when running scripts/db/backfill.py; user data lives in Postgres.
    MONGO_URI: Optional[str] = None
    # User-data Postgres DB.
    POSTGRES_URI: Optional[str] = None
    # On app startup, apply pending Alembic migrations. Default ON for dev; disable in prod if you manage schema out-of-band.
    AUTO_MIGRATE: bool = True
    # On app startup, create the target Postgres database if it's missing (requires CREATEDB privilege). Dev-friendly default.
    AUTO_CREATE_DB: bool = True
    LLM_PATH: str = os.path.join(current_dir, "models/docsgpt-7b-f16.gguf")
    DEFAULT_MAX_HISTORY: int = 150
    DEFAULT_LLM_TOKEN_LIMIT: int = 128000  # Fallback when model not found in registry
    RESERVED_TOKENS: dict = {
        "system_prompt": 500,
        "current_query": 500,
        "safety_buffer": 1000,
    }
    DEFAULT_AGENT_LIMITS: dict = {
        "token_limit": 50000,
        "request_limit": 500,
    }
    UPLOAD_FOLDER: str = "inputs"
    PARSE_PDF_AS_IMAGE: bool = False
    PARSE_IMAGE_REMOTE: bool = False
    DOCLING_OCR_ENABLED: bool = False  # Enable OCR for docling parsers (PDF, images)
    DOCLING_OCR_ATTACHMENTS_ENABLED: bool = False  # Enable OCR for docling when parsing attachments
    VECTOR_STORE: str = "faiss"  #  "faiss" or "elasticsearch" or "qdrant" or "milvus" or "lancedb" or "pgvector"
    RETRIEVERS_ENABLED: list = ["classic_rag"]
    AGENT_NAME: str = "classic"
    FALLBACK_LLM_PROVIDER: Optional[str] = None  # provider for fallback llm
    FALLBACK_LLM_NAME: Optional[str] = None  # model name for fallback llm
    FALLBACK_LLM_API_KEY: Optional[str] = None  # api key for fallback llm

    # Google Drive integration
    GOOGLE_CLIENT_ID: Optional[str] = None  # Replace with your actual Google OAuth client ID
    GOOGLE_CLIENT_SECRET: Optional[str] = None  # Replace with your actual Google OAuth client secret
    CONNECTOR_REDIRECT_BASE_URI: Optional[str] = (
        "http://127.0.0.1:7091/api/connectors/callback"  ##add redirect url as it is to your provider's console(gcp)
    )

    # Microsoft Entra ID (Azure AD) integration
    MICROSOFT_CLIENT_ID: Optional[str] = None  # Azure AD Application (client) ID
    MICROSOFT_CLIENT_SECRET: Optional[str] = None  # Azure AD Application client secret
    MICROSOFT_TENANT_ID: Optional[str] = "common"  # Azure AD Tenant ID (or 'common' for multi-tenant)
    MICROSOFT_AUTHORITY: Optional[str] = None  # e.g., "https://login.microsoftonline.com/{tenant_id}"

    # Confluence Cloud integration
    CONFLUENCE_CLIENT_ID: Optional[str] = None
    CONFLUENCE_CLIENT_SECRET: Optional[str] = None

    # GitHub source
    GITHUB_ACCESS_TOKEN: Optional[str] = None  # PAT token with read repo access

    # LLM Cache
    CACHE_REDIS_URL: str = "redis://localhost:6379/2"

    API_URL: str = "http://localhost:7091"  # backend url for celery worker
    MCP_OAUTH_REDIRECT_URI: Optional[str] = None  # public callback URL for MCP OAuth
    INTERNAL_KEY: Optional[str] = None  # internal api key for worker-to-backend auth

    API_KEY: Optional[str] = None  # LLM api key (used by LLM_PROVIDER)

    # Provider-specific API keys (for multi-model support)
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    HUGGINGFACE_API_KEY: Optional[str] = None
    OPEN_ROUTER_API_KEY: Optional[str] = None
    NOVITA_API_KEY: Optional[str] = None

    OPENAI_API_BASE: Optional[str] = None  # azure openai api base url
    OPENAI_API_VERSION: Optional[str] = None  # azure openai api version
    AZURE_DEPLOYMENT_NAME: Optional[str] = None  # azure deployment name for answering
    AZURE_EMBEDDINGS_DEPLOYMENT_NAME: Optional[str] = None  # azure deployment name for embeddings
    OPENAI_BASE_URL: Optional[str] = None  # openai base url for open ai compatable models

    # elasticsearch
    ELASTIC_CLOUD_ID: Optional[str] = None  # cloud id for elasticsearch
    ELASTIC_USERNAME: Optional[str] = None  # username for elasticsearch
    ELASTIC_PASSWORD: Optional[str] = None  # password for elasticsearch
    ELASTIC_URL: Optional[str] = None  # url for elasticsearch
    ELASTIC_INDEX: Optional[str] = "docsgpt"  # index name for elasticsearch

    # SageMaker config
    SAGEMAKER_ENDPOINT: Optional[str] = None  # SageMaker endpoint name
    SAGEMAKER_REGION: Optional[str] = None  # SageMaker region name
    SAGEMAKER_ACCESS_KEY: Optional[str] = None  # SageMaker access key
    SAGEMAKER_SECRET_KEY: Optional[str] = None  # SageMaker secret key

    # prem ai project id
    PREMAI_PROJECT_ID: Optional[str] = None

    # Qdrant vectorstore config
    QDRANT_COLLECTION_NAME: Optional[str] = "docsgpt"
    QDRANT_LOCATION: Optional[str] = None
    QDRANT_URL: Optional[str] = None
    QDRANT_PORT: Optional[int] = 6333
    QDRANT_GRPC_PORT: int = 6334
    QDRANT_PREFER_GRPC: bool = False
    QDRANT_HTTPS: Optional[bool] = None
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_PREFIX: Optional[str] = None
    QDRANT_TIMEOUT: Optional[float] = None
    QDRANT_HOST: Optional[str] = None
    QDRANT_PATH: Optional[str] = None
    QDRANT_DISTANCE_FUNC: str = "Cosine"

    # PGVector vectorstore config. Write the URI in whichever form you
    # prefer — ``postgres://``, ``postgresql://``, or even the SQLAlchemy
    # dialect form (``postgresql+psycopg://``) are all accepted and
    # normalized internally for ``psycopg.connect()``.
    PGVECTOR_CONNECTION_STRING: Optional[str] = None
    # Milvus vectorstore config
    MILVUS_COLLECTION_NAME: Optional[str] = "docsgpt"
    MILVUS_URI: Optional[str] = "./milvus_local.db"  # milvus lite version as default
    MILVUS_TOKEN: Optional[str] = ""

    # LanceDB vectorstore config
    LANCEDB_PATH: str = "./data/lancedb"  # Path where LanceDB stores its local data
    LANCEDB_TABLE_NAME: Optional[str] = "docsgpts"  # Name of the table to use for storing vectors

    FLASK_DEBUG_MODE: bool = False
    STORAGE_TYPE: str = "local"  # local or s3

    # Anonymous startup version check for security issues.
    VERSION_CHECK: bool = True
    URL_STRATEGY: str = "backend"  # backend or s3

    JWT_SECRET_KEY: str = ""

    # Encryption settings
    ENCRYPTION_SECRET_KEY: str = "default-docsgpt-encryption-key"

    TTS_PROVIDER: str = "google_tts"  # google_tts or elevenlabs
    ELEVENLABS_API_KEY: Optional[str] = None
    STT_PROVIDER: str = "openai"  # openai or faster_whisper
    OPENAI_STT_MODEL: str = "gpt-4o-mini-transcribe"
    STT_LANGUAGE: Optional[str] = None
    STT_MAX_FILE_SIZE_MB: int = 50
    STT_ENABLE_TIMESTAMPS: bool = False
    STT_ENABLE_DIARIZATION: bool = False

    # Tool pre-fetch settings
    ENABLE_TOOL_PREFETCH: bool = True

    # Conversation Compression Settings
    ENABLE_CONVERSATION_COMPRESSION: bool = True
    COMPRESSION_THRESHOLD_PERCENTAGE: float = 0.8  # Trigger at 80% of context
    COMPRESSION_MODEL_OVERRIDE: Optional[str] = None  # Use different model for compression
    COMPRESSION_PROMPT_VERSION: str = "v1.0"  # Track prompt iterations
    COMPRESSION_MAX_HISTORY_POINTS: int = 3  # Keep only last N compression points to prevent DB bloat

    # Internal SSE push channel (notifications + durable replay journal)
    # Master switch — when False, /api/events emits a "push_disabled" comment
    # and returns; clients fall back to polling. Publisher becomes a no-op.
    ENABLE_SSE_PUSH: bool = True
    # Per-user durable backlog cap (~entries). At typical event rates this
    # gives ~24h of replay; tune up for verbose feeds, down for memory.
    EVENTS_STREAM_MAXLEN: int = 1000
    # SSE keepalive comment cadence. Must sit under Cloudflare's 100s idle
    # close and iOS Safari's ~60s — 15s gives generous headroom.
    SSE_KEEPALIVE_SECONDS: int = 15
    # Cap on simultaneous SSE connections per user. Each connection holds
    # one WSGI thread (32 per gunicorn worker) and one Redis pub/sub
    # connection. 8 covers normal multi-tab use without letting one user
    # starve the pool. Set to 0 to disable the cap.
    SSE_MAX_CONCURRENT_PER_USER: int = 8
    # Per-request cap on the number of backlog entries XRANGE returns
    # for ``/api/events`` snapshots. Bounds the bytes a single replay
    # can move from Redis to the wire — a malicious client looping
    # ``Last-Event-ID=<oldest>`` reconnects can only enumerate this
    # many entries per round-trip. Combined with the per-user
    # connection cap above and the windowed budget below, total
    # enumeration throughput is bounded.
    EVENTS_REPLAY_MAX_PER_REQUEST: int = 200
    # Sliding-window cap on snapshot replays per user. Once the budget
    # is exhausted the route returns HTTP 429 with the cursor pinned;
    # the client backs off and retries after the window rolls over.
    EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW: int = 30
    EVENTS_REPLAY_BUDGET_WINDOW_SECONDS: int = 60

    # Retention for the ``message_events`` journal. The ``cleanup_message_events``
    # beat task deletes rows older than this. Reconnect-replay only
    # needs the journal for streams a client could still be tailing,
    # so 14 days is a generous default that covers paused/tool-action
    # flows without unbounded table growth.
    MESSAGE_EVENTS_RETENTION_DAYS: int = 14

    @field_validator("POSTGRES_URI", mode="before")
    @classmethod
    def _normalize_postgres_uri_validator(cls, v):
        return normalize_postgres_uri(v)

    @field_validator("PGVECTOR_CONNECTION_STRING", mode="before")
    @classmethod
    def _normalize_pgvector_connection_string_validator(cls, v):
        return normalize_pgvector_connection_string(v)

    @field_validator(
        "API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "HUGGINGFACE_API_KEY",
        "NOVITA_API_KEY",
        "EMBEDDINGS_KEY",
        "FALLBACK_LLM_API_KEY",
        "QDRANT_API_KEY",
        "ELEVENLABS_API_KEY",
        "INTERNAL_KEY",
        mode="before",
    )
    @classmethod
    def normalize_api_key(cls, v: Optional[str]) -> Optional[str]:
        """
        Normalize API keys: convert 'None', 'none', empty strings,
        and whitespace-only strings to actual None.
        Handles Pydantic loading 'None' from .env as string "None".
        """
        if v is None:
            return None
        if not isinstance(v, str):
            return v
        stripped = v.strip()
        if stripped == "" or stripped.lower() == "none":
            return None
        return stripped


# Project root is one level above application/
path = Path(__file__).parent.parent.parent.absolute()
settings = Settings(_env_file=path.joinpath(".env"), _env_file_encoding="utf-8")
