import os
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from application.core.db_uri import (  # noqa: E402
    normalize_pgvector_connection_string,
    normalize_postgres_uri,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    AUTH_TYPE: Optional[str] = None  # simple_jwt, session_jwt, oidc, or None

    # OIDC SSO (AUTH_TYPE=oidc) — any OpenID Connect IdP with discovery (Authentik, Keycloak, ...)
    OIDC_ISSUER: Optional[str] = None  # e.g. https://auth.example.com/application/o/docsgpt/
    OIDC_CLIENT_ID: Optional[str] = None
    OIDC_CLIENT_SECRET: Optional[str] = None  # optional; PKCE is always used
    OIDC_SCOPES: str = "openid profile email"
    OIDC_USER_ID_CLAIM: str = "sub"  # ID-token claim mapped to the DocsGPT user id
    OIDC_FRONTEND_URL: Optional[str] = None  # browser-facing app origin, e.g. http://localhost:5173
    OIDC_REDIRECT_URI: Optional[str] = None  # override; default <request host>/api/auth/oidc/callback
    OIDC_SESSION_LIFETIME_SECONDS: int = 28800  # minted session JWT lifetime (8h)
    OIDC_PROVIDER_NAME: Optional[str] = None  # sign-in button label, e.g. "Acme SSO"
    OIDC_ALLOWED_GROUPS: Optional[str] = None  # comma-separated allowlist; unset = any authenticated user
    OIDC_GROUPS_CLAIM: str = "groups"  # ID-token/userinfo claim carrying group membership
    OIDC_ADMIN_GROUPS: Optional[str] = None  # comma-separated groups granted admin; unset = no OIDC admin mapping

    # RBAC (admin/user roles). Persisted admin grants live in the user_roles
    # table and apply only under AUTH_TYPE=oidc. LOCAL_MODE_ADMIN is the only
    # non-DB admin path and applies only to AUTH_TYPE=None (no-auth self-host).
    # It MUST stay False in any networked deployment.
    LOCAL_MODE_ADMIN: bool = False

    # SCIM 2.0 provisioning (IdP-driven user create/deactivate at /scim/v2)
    SCIM_ENABLED: bool = False
    SCIM_TOKEN: Optional[str] = None  # bearer token for IdP SCIM clients (required when enabled)

    LLM_PROVIDER: str = "docsgpt"
    LLM_NAME: Optional[str] = None  # if LLM_PROVIDER is openai, LLM_NAME can be gpt-4 or gpt-3.5-turbo
    EMBEDDINGS_NAME: str = "huggingface_sentence-transformers/all-mpnet-base-v2"
    EMBEDDINGS_BASE_URL: Optional[str] = None  # Remote embeddings API URL (OpenAI-compatible)
    EMBEDDINGS_KEY: Optional[str] = None  # api key for embeddings (if using openai, just copy API_KEY)
    EMBEDDINGS_MAX_INPUT_TOKENS: Optional[int] = None  # truncate each remote embed input to N tokens (overflow lost)
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
    # On app startup, create the pgvector/graph tables and verify the embedding dimension. Set False to manage them
    # out-of-band — there is no Alembic migration for the vector DB because it may be a separate cluster.
    AUTO_VECTOR_SCHEMA: bool = True
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
    # Public upload request cap is applied by Flask before multipart parsing.
    # The per-file cap is also enforced while copying each controlled stream.
    UPLOAD_MAX_REQUEST_BYTES: int = Field(default=256 * 1024 * 1024, gt=0)
    UPLOAD_MAX_FILE_BYTES: int = Field(default=100 * 1024 * 1024, gt=0)
    PARSE_SPEC_MAX_BYTES: int = Field(default=10 * 1024 * 1024, gt=0)
    # ZIP limits apply cumulatively across nested archives in one extraction.
    UPLOAD_MAX_ARCHIVE_BYTES: int = Field(default=250 * 1024 * 1024, gt=0)
    UPLOAD_MAX_ARCHIVE_FILES: int = Field(default=10_000, gt=0)
    UPLOAD_MAX_ARCHIVE_RATIO: int = Field(default=1000, gt=0)
    UPLOAD_MAX_ARCHIVE_DEPTH: int = Field(default=3, ge=0)
    PARSE_PDF_AS_IMAGE: bool = False
    PARSE_IMAGE_REMOTE: bool = False
    DOCLING_OCR_ENABLED: bool = False  # Enable OCR for docling parsers (PDF, images)
    DOCLING_OCR_ATTACHMENTS_ENABLED: bool = False  # Enable OCR for docling when parsing attachments
    # Pages docling's threaded pipeline buffers in flight; the library
    # default (100) drives worker RSS to ~3 GB on a mid-size PDF.
    DOCLING_PIPELINE_QUEUE_MAX_SIZE: int = 2
    DOCLING_COMPILE_TORCH_MODELS: bool = False
    DOCLING_TABULAR_MAX_BYTES: int = 2_000_000
    DOCLING_MARKUP_MAX_BYTES: int = 8_000_000
    # Chars-per-page floor below which an OCR'd PDF/image parse is treated as a docling
    # pipeline dropout (long-running workers were observed returning zero characters for
    # every scanned page after a long scanned PDF, with no error) rather than as content.
    # Such a parse is retried once on a fresh full-page-OCR converter and then fails
    # loudly instead of indexing an empty document. 0 disables the guard.
    DOCLING_OCR_MIN_CHARS_PER_PAGE: int = 20
    # Read PDF *attachments* via their embedded text layer (pypdfium2) instead
    # of docling, falling back to docling when there is no text layer to read.
    # Attachments go into a prompt, so docling's structural markdown earns far
    # less than the tens of seconds per file it costs; source ingestion is
    # unaffected and always uses docling, because chunking and retrieval do
    # depend on that structure.
    ATTACHMENT_PDF_TEXT_FAST_PATH: bool = True
    # Median characters per sampled page below which a PDF is treated as a scan
    # and handed to docling. Measured separation on real uploads: scans at
    # 0-17 chars/page, text-layer documents at 433-6834.
    ATTACHMENT_PDF_TEXT_MIN_MEDIAN_CHARS: int = 32
    ATTACHMENT_TEXT_MAX_BYTES: int = 5_000_000
    AGENT_IMAGE_MAX_BYTES: int = 5_000_000
    AGENT_IMAGE_MAX_PIXELS: int = 16_777_216
    VECTOR_STORE: str = "faiss"  #  "faiss" or "elasticsearch" or "qdrant" or "milvus" or "lancedb" or "pgvector"
    # Allow-list of retriever keys an agent may use. Values must match the
    # ``RetrieverCreator.retrievers`` registry keys (``classic`` / ``default``),
    # NOT the legacy ``classic_rag`` label which never matched the registry.
    RETRIEVERS_ENABLED: list = ["classic", "default"]
    # Concurrent per-source vector searches within one retrieval (multi-source chats);
    # the query is embedded once and shared across sources.
    RETRIEVAL_MAX_PARALLEL_SOURCES: int = 4
    # Kill-switch for per-source retrieval dispatch. When False the retrieval
    # path collapses to today's single-retriever behavior (consumed by the
    # Dispatcher in a later change; defined here so the flag exists up front).
    PER_SOURCE_RETRIEVAL_ENABLED: bool = True
    # Flagship GraphRAG flag. Reserved and unused for now; gates graph-aware
    # ingestion/retrieval when that feature lands.
    GRAPHRAG_ENABLED: bool = False
    # Model for ingest-time graph extraction; None reuses the instance default
    # model (LLM_PROVIDER/LLM_NAME). Operator-overridable (e.g. a cheaper model).
    GRAPHRAG_EXTRACTION_MODEL: Optional[str] = None
    # Hard cap on chunks extracted per source (cost control).
    GRAPHRAG_MAX_CHUNKS_FOR_EXTRACTION: int = 2000
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

    # Public base URL for user-facing endpoint references in prompts
    PUBLIC_API_BASE_URL: Optional[str] = None
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
    ORCAROUTER_API_KEY: Optional[str] = None
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

    # Legacy AWS credentials from the retired SageMaker LLM provider.
    # Still read as a deprecated fallback by S3 storage (see the S3_*
    # block below); do not use for new deployments.
    SAGEMAKER_REGION: Optional[str] = None
    SAGEMAKER_ACCESS_KEY: Optional[str] = None
    SAGEMAKER_SECRET_KEY: Optional[str] = None

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
    # Per-process psycopg connection pool for the vector store; 0 = one direct
    # connection per store instance, the legacy behaviour.
    PGVECTOR_POOL_MAX_SIZE: int = 8
    # IVFFlat probes for vector search. ``None`` derives sqrt(lists) from the
    # index itself; set an integer to pin it. Higher = better recall, more scan.
    PGVECTOR_IVFFLAT_PROBES: Optional[int] = None
    # Milvus vectorstore config
    MILVUS_COLLECTION_NAME: Optional[str] = "docsgpt"
    MILVUS_URI: Optional[str] = "./milvus_local.db"  # milvus lite version as default
    MILVUS_TOKEN: Optional[str] = ""

    # LanceDB vectorstore config
    LANCEDB_PATH: str = "./data/lancedb"  # Path where LanceDB stores its local data
    LANCEDB_TABLE_NAME: Optional[str] = "docsgpts"  # Name of the table to use for storing vectors

    FLASK_DEBUG_MODE: bool = False
    STORAGE_TYPE: str = "local"  # local or s3

    # S3-compatible object storage (used when STORAGE_TYPE=s3). Works with AWS
    # S3 and any S3-compatible service (MinIO, Cloudflare R2, Backblaze B2,
    # DigitalOcean Spaces, ...). For non-AWS services, set S3_ENDPOINT_URL and
    # usually S3_PATH_STYLE=true. The SAGEMAKER_* credentials are still read as
    # a deprecated fallback for backward compatibility.
    S3_BUCKET_NAME: str = "docsgpt-test-bucket"
    S3_ENDPOINT_URL: Optional[str] = None  # custom endpoint for S3-compatible services; omit for AWS
    S3_ACCESS_KEY_ID: Optional[str] = None
    S3_SECRET_ACCESS_KEY: Optional[str] = None
    S3_REGION: Optional[str] = None  # AWS region; use "auto" for Cloudflare R2
    S3_PATH_STYLE: bool = False  # path-style addressing (required by most non-AWS services)

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

    # When True, OpenAI Responses API calls are persisted server-side
    # (store=true) so a previous_response_id can chain turns. When False
    # (the default) Responses calls are stateless (store=false) and any
    # reasoning is carried across the in-turn tool loop via encrypted
    # reasoning items instead.
    OPENAI_RESPONSES_STORE: bool = False
    OPENAI_REASONING_SUMMARY: str = "auto"

    # OpenAI-compatible clients can identify a logical chat with session
    # headers even though chat-completions itself has no conversation field.
    V1_SESSION_TTL_SECONDS: int = 24 * 60 * 60

    # Optional cheaper model for first-party conversation titles. When unset,
    # listed conversations use their answer model, but title work is still
    # dispatched off the response path.
    TITLE_MODEL_ID: Optional[str] = None

    # Config-free tools on by default in agentless chats. ``scheduler`` is
    # dual-registered (also in ``BUILTIN_AGENT_TOOLS``) so the same synthetic id
    # resolves whether reached via defaults or the agent picker.
    #
    # ``code_executor`` and ``artifact_generator`` belong here too on any
    # deployment that runs a sandbox (see SANDBOX_BACKEND / SANDBOX_GATEWAY_URL):
    # ``artifact_generator`` renders the .docx/.pdf/.xlsx/.pptx files users ask
    # chat for. They are left out of the shipped default because both execute
    # through the sandbox runner and would fail on every call without one — add
    # them explicitly once a runner is configured:
    #     DEFAULT_CHAT_TOOLS = [..., "code_executor", "artifact_generator"]
    DEFAULT_CHAT_TOOLS: list = [
        "memory",
        "read_webpage",
        "scheduler",
    ]

    # Conversation Compression Settings
    ENABLE_CONVERSATION_COMPRESSION: bool = True
    COMPRESSION_THRESHOLD_PERCENTAGE: float = 0.8  # Trigger at 80% of context
    COMPRESSION_MODEL_OVERRIDE: Optional[str] = None  # Use different model for compression
    COMPRESSION_PROMPT_VERSION: str = "v1.0"  # Track prompt iterations
    COMPRESSION_MAX_HISTORY_POINTS: int = 3  # Keep only last N compression points to prevent DB bloat
    COMPRESSION_RECENT_FIELD_MAX_TOKENS: int = 8000  # Per-field cap on the verbatim tail kept after a compression point (0 disables)
    TOOL_RESULT_MAX_TOKENS: int = 20000  # Cap on a single tool result entering the LLM context (0 disables); journal/DB keep the full result

    # Agent Guardrails
    # Master switch. When False, no guardrail stage runs regardless of what an
    # agent's config says.
    GUARDRAILS_ENABLED: bool = True
    # Registry-key allowlist; values must match GuardrailCreator.checks keys.
    # Empty means "every registered check".
    GUARDRAILS_CHECKS_ENABLED: list = []
    # Instance floor: a GuardrailsConfig fragment every agent inherits and
    # cannot weaken. Agents may add controls or make an action stricter, never
    # looser. "enabled" is required — without it the floor parses but applies
    # to nothing. Example:
    # {"enabled": true, "mode": "scan_all",
    #  "controls": [{"check": "secrets", "stage": "output",
    #                "action": "redact"}]}
    GUARDRAILS_FLOOR: dict = {}
    # Judge model for the topic/policy checks. None reuses the request's model.
    GUARDRAILS_JUDGE_MODEL: Optional[str] = None
    # Persist scanned text alongside guardrail_events. Off by default: the
    # pre-redaction text is exactly the sensitive material a PII control exists
    # to keep out of storage.
    GUARDRAILS_STORE_SCANNED_TEXT: bool = False
    GUARDRAILS_EVENTS_RETENTION_DAYS: int = Field(default=30, ge=1)

    # Internal SSE push channel (notifications + durable replay journal)
    # Master switch — when False, /api/events emits a "push_disabled" comment
    # and returns; clients fall back to polling. Publisher becomes a no-op.
    ENABLE_SSE_PUSH: bool = True
    # Per-user durable backlog cap (~entries). At typical event rates this
    # gives ~24h of replay; tune up for verbose feeds, down for memory.
    EVENTS_STREAM_MAXLEN: int = 1000
    # Bounds uvicorn's graceful-shutdown drain (uvicorn_worker doesn't forward
    # --graceful-timeout). Keep below the gunicorn --timeout (180) watchdog.
    # Used by gunicorn_worker.BoundedDrainUvicornWorker.
    GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS: int = 30
    WSGI_THREADPOOL_WORKERS: int = 96
    SSE_KEEPALIVE_SECONDS: int = Field(default=15, ge=1)
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
    EVENTS_REPLAY_MAX_AGE_HOURS: int = 48
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

    # Remote Device feature.
    REMOTE_DEVICE_SESSION_IDLE_SECONDS: int = 60
    REMOTE_DEVICE_REQUIRE_SIGNATURE: bool = False
    REMOTE_DEVICE_PAIRING_TTL_SECONDS: int = 600
    # Redis-backed broker tunables (route invocations cross-process so a
    # scheduled/Celery run reaches the web-held device session). The command
    # queue TTL must exceed the max command drain deadline (the tool caps
    # timeout_ms at 600s, drained with a +5s margin = 605s) so a queued command
    # for a briefly-offline device isn't evicted before its own drain gives up.
    REMOTE_DEVICE_CMD_QUEUE_TTL_SECONDS: int = 900
    REMOTE_DEVICE_INVOCATION_TTL_SECONDS: int = 900
    REMOTE_DEVICE_OUTPUT_STREAM_MAXLEN: int = 10_000

    # Scheduler (see scheduler.md).
    SCHEDULE_DISPATCHER_INTERVAL: int = 30
    SCHEDULE_MIN_INTERVAL: int = 900
    SCHEDULE_MAX_PER_USER: int = 50
    SCHEDULE_RUN_TIMEOUT: int = 600
    SCHEDULE_MISFIRE_GRACE: int = 60
    SCHEDULE_AUTOPAUSE_FAILURES: int = 3
    SCHEDULE_ONCE_MAX_HORIZON: int = 31_536_000
    SCHEDULE_RUN_OUTPUT_RETENTION_DAYS: int = 90

    # Code-execution sandbox (see artifacts-code-execution-spec.md §4 C2).
    # The app is a CLIENT of an always-on runner; defaults are safe so app
    # import never fails when the sandbox is unconfigured.
    SANDBOX_BACKEND: str = "jupyter"  # "jupyter" (self-host) | "daytona" (Daytona Cloud)
    # URL of the Jupyter Kernel Gateway runner (the docsgpt-sandbox service).
    SANDBOX_GATEWAY_URL: str = "http://localhost:8888"
    SANDBOX_GATEWAY_AUTH_TOKEN: Optional[str] = None  # gateway auth token, if set
    # Kernelspec launched per session. Defaults to the env-scrubbing "docsgpt-python"
    # spec (shipped by the docsgpt-sandbox runner) so kernel code cannot read the
    # gateway auth token or operator secrets from os.environ. The stock "python3"
    # spec inherits the gateway env verbatim and must not be used with untrusted code.
    SANDBOX_KERNEL_NAME: str = "docsgpt-python"
    SANDBOX_MAX_TTL: int = 1200  # hard cap (s) on agent-selectable keep-alive TTL
    # Per-process/worker cap on concurrent live sandbox sessions. Backend-agnostic
    # (complements DAYTONA_MAX_SANDBOXES); when reached, an LRU-idle session is
    # evicted to make room. This bound is local to each app/worker process.
    # 0 (or any non-positive value) disables the cap (unlimited sessions).
    SANDBOX_MAX_SESSIONS: int = 32
    SANDBOX_EXEC_TIMEOUT: int = 60  # default wall-clock cap (s) per exec call
    SANDBOX_HTTP_TIMEOUT: int = 10  # fixed cap (s) for REST control calls (create/delete/alive/interrupt)
    SANDBOX_MAX_OUTPUT_BYTES: int = 8 * 1024 * 1024  # cap on buffered stdout+stderr per exec
    SANDBOX_MAX_FILE_BYTES: int = 10 * 1024 * 1024  # cap on get_file size routed through stdout
    SANDBOX_MAX_INPUT_BYTES: int = 25 * 1024 * 1024  # cap on an input document staged into a sandbox session
    # ``read_document`` parsing on a dedicated Celery ``parsing`` queue (backend parser).
    DOCUMENT_PARSE_QUEUE: str = "parsing"  # queue the parse_document task is routed to
    DOCUMENT_PARSE_TIMEOUT: int = 120  # seconds the tool awaits the enqueued parse before degrading
    # The base timeout is a FLOOR: the awaited window (and the task's per-call Celery
    # time limits) grow with the document's size, because OCR cost scales with pages
    # -- a 30-page scan needs ~60s, a 100-page scan several minutes. Without this a
    # large scan is silently dropped from the node/tool at the base window.
    DOCUMENT_PARSE_TIMEOUT_PER_MB: int = 60  # extra seconds of parse window per MiB of input
    DOCUMENT_PARSE_TIMEOUT_MAX: int = 900  # absolute ceiling on the size-scaled parse window
    DOCUMENT_PARSE_MAX_BYTES: int = 0  # cap on a parsed document's bytes (0 = reuse SANDBOX_MAX_INPUT_BYTES)
    DOCUMENT_MAX_DECOMPRESSED_BYTES: int = 300 * 1024 * 1024
    DOCUMENT_MAX_ARCHIVE_ENTRIES: int = 10000
    # Per-agent-node cap on files passed natively to the node's LLM (vision/doc
    # inputs). Files past the cap are extracted to text or dropped, not attached
    # natively, to bound context/cost. Re-uses SANDBOX_MAX_INPUT_BYTES per file.
    WORKFLOW_NODE_NATIVE_MAX_FILES: int = 5
    # Per-agent-node cap on documents extracted to text via the parsing worker.
    # Each non-native, non-text document issues a separate blocking parse, so a
    # node referencing many documents (e.g. the ``*`` token) is bounded here to
    # avoid serializing dozens of parses; documents past the cap are skipped with
    # a truncation note instead of extracted.
    WORKFLOW_NODE_EXTRACT_MAX_FILES: int = 5
    # Total wall clock one node may spend on blocking document parses, shared
    # across all of them. The per-document window scales with size (up to
    # DOCUMENT_PARSE_TIMEOUT_MAX), so without a shared budget a node could
    # serialize WORKFLOW_NODE_EXTRACT_MAX_FILES full windows and hold a web
    # threadpool slot for that whole time.
    WORKFLOW_NODE_EXTRACT_BUDGET_SECONDS: int = 900
    # A workflow run row is pre-created as ``running`` and finalized when its
    # generator completes; a client disconnect or worker crash can strand it in
    # ``running`` forever. The beat reaper fails runs still ``running`` past this
    # many seconds. Generous so a legitimately long run is never cut off.
    WORKFLOW_RUN_STALE_SECONDS: int = 3600
    # Runner container resource caps — consumed by the docsgpt-sandbox compose
    # service (deployment/sandbox), not by the app client. cgroup CPU/mem caps
    # are part of the untrusted-code security boundary.
    SANDBOX_MEMORY: str = "1g"  # docker mem_limit for the runner container
    SANDBOX_CPUS: str = "1.0"  # docker cpu quota for the runner container
    # Daytona Cloud managed backend (used only when SANDBOX_BACKEND="daytona").
    # The app is a REST client of Daytona Cloud authenticated by DAYTONA_API_KEY;
    # all knobs are optional so app import never fails when the backend is unused.
    DAYTONA_API_KEY: Optional[str] = None  # Daytona Cloud API key (secret)
    DAYTONA_API_URL: Optional[str] = None  # override Daytona API base URL, if self-targeting
    DAYTONA_TARGET: Optional[str] = None  # Daytona region/target, e.g. "us"
    DAYTONA_SNAPSHOT: Optional[str] = None  # image for new sandboxes; render libs via scripts/build_daytona_snapshot.py
    DAYTONA_LANGUAGE: str = "python"  # default runtime language for created sandboxes
    DAYTONA_AUTO_STOP_INTERVAL: int = 15  # minutes idle before Daytona auto-stops a sandbox (0 disables)
    DAYTONA_AUTO_DELETE_INTERVAL: int = 60  # minutes after stop before Daytona auto-deletes (-1 disables)
    DAYTONA_MAX_SANDBOXES: int = 50  # cap on concurrent live Daytona sandboxes (cost-DoS guard)
    # Per-user artifact quotas (generous defaults; enforced at persistence time).
    # For all three, 0 (or any non-positive value) disables that quota (unlimited).
    ARTIFACT_MAX_BYTES: int = 50 * 1024 * 1024  # cap on a single stored artifact version's bytes
    ARTIFACT_MAX_COUNT_PER_USER: int = 5000  # cap on artifacts a user may own
    ARTIFACT_MAX_TOTAL_BYTES_PER_USER: int = 5 * 1024 * 1024 * 1024  # cap on a user's total stored bytes

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
