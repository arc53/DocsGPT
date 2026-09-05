import os
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field, field_validator
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

    # RBAC: persisted admin grants live in user_roles (AUTH_TYPE=oidc only). This is the
    # only non-DB admin path, for AUTH_TYPE=None self-host. MUST stay False if networked.
    LOCAL_MODE_ADMIN: bool = False

    # SCIM 2.0 provisioning (IdP-driven user create/deactivate at /scim/v2)
    SCIM_ENABLED: bool = False
    SCIM_TOKEN: Optional[str] = None  # bearer token for IdP SCIM clients (required when enabled)

    LLM_PROVIDER: str = "docsgpt"
    LLM_NAME: Optional[str] = None  # if LLM_PROVIDER is openai, LLM_NAME can be gpt-4 or gpt-3.5-turbo
    # Legacy model on purpose: an install that never pinned this has vectors from it, and
    # granite is the same width so a swap would fail silently. New installs get granite from
    # .env-template; existing ones switch by setting this and running application.scripts.reembed.
    EMBEDDINGS_NAME: str = "huggingface_sentence-transformers/all-mpnet-base-v2"
    EMBEDDINGS_BASE_URL: Optional[str] = None  # Remote embeddings API URL (OpenAI-compatible)
    EMBEDDINGS_KEY: Optional[str] = None  # api key for embeddings (if using openai, just copy API_KEY)
    EMBEDDINGS_MAX_INPUT_TOKENS: Optional[int] = None  # truncate each remote embed input to N tokens (overflow lost)
    EMBEDDINGS_BATCH_SIZE: int = 32  # chunks per store transaction / remote embed request
    # Documents per local ONNX forward pass. Each pass pads to its longest input, and that
    # waste grows with the square of chunk length: at 1250 tokens, 32 peaked at 6.6 GB, 1 at 2.9 GB.
    EMBEDDINGS_MODEL_BATCH_SIZE: int = 1
    # Intra-op threads for the local ONNX runner; None = every core. It scales sub-linearly,
    # so several single-threaded workers beat one many-threaded process on the same cores.
    EMBEDDINGS_THREADS: Optional[int] = None
    EMBEDDINGS_CACHE_DIR: Optional[str] = None  # where FastEmbed caches model artifacts
    # Pooling ("cls"/"mean") and L2 normalisation. Read from the model's own repository;
    # set these only for a repository that declares neither, or to override what it declares.
    EMBEDDINGS_POOLING: Optional[str] = None
    EMBEDDINGS_NORMALIZE: Optional[bool] = None
    # Embed on the worker so the API holds no model (~890 MB), at one broker round trip per
    # query. Ignored when EMBEDDINGS_BASE_URL is set, which is the better answer for production.
    EMBEDDINGS_DELEGATE_TO_WORKER: bool = True
    EMBEDDINGS_QUEUE: str = "embeddings"  # queue the embed task is routed to
    EMBEDDINGS_DELEGATE_TIMEOUT: int = 60  # seconds to wait for the worker
    GITHUB_INGEST_MAX_FILE_BYTES: int = 1048576  # skip repo blobs larger than this (0 = no cap)
    GITHUB_INGEST_MAX_WORKERS: int = 8  # parallel file fetches per GitHub repo ingest
    # Operator-supplied model YAMLs, loaded after the built-in catalog; later wins on
    # duplicate model id. See application/core/models/README.md.
    MODELS_CONFIG_DIR: Optional[str] = None

    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    # Prefetch=1 caps SIGKILL loss to one task. Visibility timeout must exceed the longest
    # legitimate task runtime but stay short enough that SIGKILLed tasks redeliver promptly.
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1
    CELERY_VISIBILITY_TIMEOUT: int = 3600
    # Recycle a prefork child past this resident size in KB; backstops docling/torch heap growth.
    # Checked between tasks, so it does not bound the peak within one. 0 disables.
    CELERY_WORKER_MAX_MEMORY_PER_CHILD: int = 4194304
    CELERY_WORKER_MAX_TASKS_PER_CHILD: int = 0  # recycle after N tasks; 0 disables
    # Only consulted when VECTOR_STORE=mongodb or when running scripts/db/backfill.py; user data lives in Postgres.
    MONGO_URI: Optional[str] = None
    # User-data Postgres DB.
    POSTGRES_URI: Optional[str] = None
    # On startup, apply pending Alembic migrations. Disable if you manage schema out-of-band.
    AUTO_MIGRATE: bool = True
    # On startup, create the target Postgres database if missing (needs CREATEDB privilege).
    AUTO_CREATE_DB: bool = True
    # On startup, create the pgvector/graph tables and verify the embedding dimension. No Alembic
    # migration covers the vector DB (it may be a separate cluster); set False to manage it yourself.
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
    # Request cap is applied by Flask before multipart parsing; the per-file cap also while copying.
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
    # Document parser for source ingestion, chat attachments and the
    # read_document tool. "anydoc" (default): firecrawl-anydoc, a Rust
    # converter with no ML models — milliseconds per file, ~100 MB peak RSS.
    # "docling": the layout/table-model pipeline (optional install; needed
    # for read_document's structured output and the docling OCR backend).
    # Files anydoc cannot convert (scanned PDFs, malformed input) fall back to
    # docling when it is installed, otherwise to the native OCR parsers (OCR
    # on) or the legacy parsers. Rollback to the previous behaviour is this
    # one variable.
    DOC_PARSER_ENGINE: str = "anydoc"
    # OCR for scanned PDFs and images. OCR_ENABLED covers source ingestion,
    # OCR_ATTACHMENTS_ENABLED chat attachments. Which stack performs it is
    # OCR_BACKEND; which engine, OCR_ENGINE. The DOCLING_OCR_* names are the
    # pre-2026-09 spellings and stay accepted as aliases.
    OCR_ENABLED: bool = Field(
        default=False, validation_alias=AliasChoices("OCR_ENABLED", "DOCLING_OCR_ENABLED")
    )
    OCR_ATTACHMENTS_ENABLED: bool = Field(
        default=False,
        validation_alias=AliasChoices("OCR_ATTACHMENTS_ENABLED", "DOCLING_OCR_ATTACHMENTS_ENABLED"),
    )
    # Which stack runs OCR when it is on:
    #   auto    — docling when installed, otherwise native.
    #   docling — the layout-model pipeline (hybrid region OCR, reading order,
    #             table structure); needs the optional docling extra.
    #   native  — pypdfium2/Pillow page rendering straight into tesseract or a
    #             DeepSeek-OCR endpoint (application/parser/file/ocr_parser.py).
    #             No ML models in the worker; tables come out as text lines
    #             under tesseract.
    OCR_BACKEND: str = "auto"
    # Pages docling's threaded pipeline buffers in flight; the library
    # default (100) drives worker RSS to ~3 GB on a mid-size PDF.
    DOCLING_PIPELINE_QUEUE_MAX_SIZE: int = 2
    DOCLING_COMPILE_TORCH_MODELS: bool = False
    DOCLING_TABULAR_MAX_BYTES: int = 2_000_000
    DOCLING_MARKUP_MAX_BYTES: int = 8_000_000
    # HTML/XHTML larger than this (bytes) are head-truncated before the
    # markdownify parser runs (the anydoc engine's HTML path). The tree that
    # path builds costs ~50x the input — 30 MB of HTML measured at 1.6 GB RSS —
    # and the upload cap is 100 MB, so the gate is what keeps one upload from
    # taking the ingest worker down. 0 disables it.
    MARKUP_MAX_BYTES: int = 8_000_000
    # Trust-check anydoc's PDF output (application/parser/file/pdf_trust.py):
    # flag composite (Type0) fonts without a ToUnicode map, and CJK-declaring
    # PDFs whose extracted text has almost no CJK — the two classes where
    # anydoc drops text silently. A flagged file re-parses on the docling
    # fallback when docling is installed; otherwise the anydoc output is kept
    # and the document gets extra_info["parse_warnings"]. ~30 ms per scanned MB.
    PDF_TRUST_CHECK: bool = True
    # Rewrite dot-leader / whitespace-aligned table runs in anydoc's PDF
    # markdown into GFM tables (application/parser/file/tableize.py). Off by
    # default: it rewrites content on a heuristic (>=3 uniform label+numbers
    # lines) validated only on a small corpus so far.
    ANYDOC_TABLEIZE: bool = False
    # OCR engine used when OCR is on (OCR_ENABLED / OCR_ATTACHMENTS_ENABLED).
    # Benched 2026-08 on EN/ZH/table/degraded scans (docs/Guides/ocr has the
    # menu):
    #   tesseract — recommended: best classic-engine accuracy (perfect EN word
    #     recall, 0.000 bilingual CER, 100% table cells), ~35 MB, CPU-only.
    #     Needs the system binary + language packs: an optional install like
    #     every OCR dependency (build with INSTALL_TESSERACT=true, or apt/brew
    #     install tesseract-ocr for a local run). Both backends.
    #   deepseek — DeepSeek-OCR against an Ollama/vLLM endpoint
    #     (OCR_DEEPSEEK_*). Best table/CJK quality; the worker stays light
    #     (no layout models) but each page costs seconds on the model server.
    #     Both backends.
    #   auto — docling's pick: ocrmac on macOS (excellent), rapidocr on Linux
    #     (silently shreds some long text lines — avoid as a server default).
    #   ocrmac | rapidocr — force one of those.
    # auto/ocrmac/rapidocr exist only inside docling; the native backend runs
    # tesseract for them. An engine that is not installed degrades (docling:
    # to "auto") with a warning instead of failing the parse.
    OCR_ENGINE: str = "tesseract"
    # Tesseract language packs, "+"-separated (e.g. "eng+chi_sim+deu"). Other
    # engines keep their own defaults — their language codes differ.
    OCR_LANGS: str = "eng"
    OCR_DEEPSEEK_URL: str = "http://localhost:11434/v1/chat/completions"
    OCR_DEEPSEEK_MODEL: str = "deepseek-ocr:3b"
    # Seconds allowed per page request to the DeepSeek endpoint, on both
    # backends (native sends pages one at a time; docling's VLM pipeline
    # keeps its own concurrency). A 3B model on a laptop needs minutes; a
    # vLLM GPU deployment, seconds.
    OCR_DEEPSEEK_TIMEOUT: float = 300.0
    # Native backend only: resolution at which pages without a text layer are
    # rendered before OCR. 200 suits tesseract; clamped to 72-600.
    OCR_RENDER_DPI: int = 200
    # Chars-per-page floor below which an OCR'd PDF/image parse is treated as an OCR
    # dropout (long-running docling workers were observed returning zero characters for
    # every scanned page after a long scanned PDF, with no error) rather than as content.
    # docling retries once on a fresh full-page-OCR converter; both backends then fail
    # loudly instead of indexing an empty document. 0 disables the guard.
    OCR_MIN_CHARS_PER_PAGE: int = Field(
        default=20, validation_alias=AliasChoices("OCR_MIN_CHARS_PER_PAGE", "DOCLING_OCR_MIN_CHARS_PER_PAGE")
    )
    # Read PDF *attachments* via their embedded text layer (pypdfium2) instead
    # of docling, falling back to docling when there is no text layer to read.
    # Attachments go into a prompt, so docling's structural markdown earns far
    # less than the tens of seconds per file it costs; source ingestion is
    # unaffected and always uses docling, because chunking and retrieval do
    # depend on that structure.
    ATTACHMENT_PDF_TEXT_FAST_PATH: bool = True
    # Median chars per sampled page below which a PDF is treated as a scan and handed to docling.
    # Measured on real uploads: scans at 0-17 chars/page, text-layer documents at 433-6834.
    ATTACHMENT_PDF_TEXT_MIN_MEDIAN_CHARS: int = 32
    ATTACHMENT_TEXT_MAX_BYTES: int = 5_000_000
    AGENT_IMAGE_MAX_BYTES: int = 5_000_000
    AGENT_IMAGE_MAX_PIXELS: int = 16_777_216
    VECTOR_STORE: str = "faiss"  #  "faiss" or "elasticsearch" or "qdrant" or "milvus" or "lancedb" or "pgvector"
    # Retriever keys an agent may use; must match RetrieverCreator.retrievers registry keys,
    # NOT the legacy ``classic_rag`` label which never matched the registry.
    RETRIEVERS_ENABLED: list = ["classic", "default"]
    # Concurrent per-source searches in one retrieval; the query is embedded once and shared.
    RETRIEVAL_MAX_PARALLEL_SOURCES: int = 4
    # Kill-switch for per-source retrieval dispatch; False collapses to a single retriever.
    PER_SOURCE_RETRIEVAL_ENABLED: bool = True
    GRAPHRAG_ENABLED: bool = False  # gates graph-aware ingestion/retrieval
    # Model for ingest-time graph extraction; None reuses LLM_PROVIDER/LLM_NAME.
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

    # Legacy AWS credentials from the retired SageMaker provider. Still read as a deprecated
    # fallback by S3 storage; do not use for new deployments.
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

    # PGVector config. postgres://, postgresql:// and postgresql+psycopg:// are all accepted
    # and normalized internally for psycopg.connect().
    PGVECTOR_CONNECTION_STRING: Optional[str] = None
    PGVECTOR_POOL_MAX_SIZE: int = 8  # per-process pool; 0 = one direct connection per store
    # IVFFlat probes; None derives sqrt(lists) from the index. Higher = better recall, more scan.
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

    # S3-compatible object storage (STORAGE_TYPE=s3): AWS S3, MinIO, R2, B2, Spaces, ...
    # For non-AWS, set S3_ENDPOINT_URL and usually S3_PATH_STYLE=true.
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

    # True persists Responses API calls server-side so previous_response_id can chain turns.
    # False keeps them stateless, carrying reasoning across the tool loop as encrypted items.
    OPENAI_RESPONSES_STORE: bool = False
    # Cross-turn ``previous_response_id`` chaining (store mode only). The
    # chained transcript lives on the provider and is invisible to every
    # local guard, so it is bounded: a turn starts from the local history
    # when the previous turn's reported prompt already reached the budget
    # (default: the model's context window) or when the conversation was
    # compressed after that turn was produced.
    OPENAI_RESPONSES_CHAIN_ACROSS_TURNS: bool = True
    OPENAI_RESPONSES_CHAIN_BUDGET_TOKENS: Optional[int] = None
    # ``truncation: "auto"`` lets the provider drop the oldest input items
    # instead of failing every request once a chain exceeds the model's window.
    OPENAI_RESPONSES_TRUNCATION_AUTO: bool = False
    # Prompt-cache hints on the Responses API: route a user's calls to the
    # same cache shard (opaque per-user key), and request extended retention
    # where offered.
    OPENAI_PROMPT_CACHE_KEY: bool = True
    OPENAI_PROMPT_CACHE_RETENTION: Optional[str] = None
    OPENAI_REASONING_SUMMARY: str = "auto"

    # Lets OpenAI-compatible clients identify a logical chat by session header, which
    # chat-completions itself has no field for.
    V1_SESSION_TTL_SECONDS: int = 24 * 60 * 60
    # Optional cheaper model for conversation titles; unset reuses the answer model.
    TITLE_MODEL_ID: Optional[str] = None

    # Config-free tools on by default in agentless chats. ``scheduler`` is dual-registered in
    # BUILTIN_AGENT_TOOLS so one synthetic id resolves via defaults or the agent picker.
    # Add "code_executor" and "artifact_generator" once a sandbox runner is configured — both
    # execute through it and would fail on every call without one.
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
    # Per-field cap on the verbatim tail kept after a compression point (0 disables).
    COMPRESSION_RECENT_FIELD_MAX_TOKENS: int = 8000
    # Cap on one tool result entering the LLM context (0 disables); journal/DB keep it whole.
    TOOL_RESULT_MAX_TOKENS: int = 20000

    # Agent Guardrails
    GUARDRAILS_ENABLED: bool = True  # master switch; False disables every stage
    # Allowlist of GuardrailCreator.checks keys; empty means every registered check.
    GUARDRAILS_CHECKS_ENABLED: list = []
    # A GuardrailsConfig fragment every agent inherits and cannot weaken; agents may add
    # controls or make an action stricter, never looser. "enabled" is required — without it
    # the floor parses but applies to nothing. Example:
    # {"enabled": true, "mode": "scan_all",
    #  "controls": [{"check": "secrets", "stage": "output", "action": "redact"}]}
    GUARDRAILS_FLOOR: dict = {}
    # Judge model for the topic/policy checks; None reuses the request's model.
    GUARDRAILS_JUDGE_MODEL: Optional[str] = None
    # Persist scanned text alongside guardrail_events. Off by default: pre-redaction text is
    # exactly the material a PII control exists to keep out of storage.
    GUARDRAILS_STORE_SCANNED_TEXT: bool = False
    GUARDRAILS_EVENTS_RETENTION_DAYS: int = Field(default=30, ge=1)

    # Internal SSE push channel (notifications + durable replay journal).
    # False makes /api/events emit "push_disabled" and return; clients fall back to polling.
    ENABLE_SSE_PUSH: bool = True
    # Per-user durable backlog cap in entries; ~24h of replay at typical rates.
    EVENTS_STREAM_MAXLEN: int = 1000
    # Bounds uvicorn's shutdown drain (uvicorn_worker doesn't forward --graceful-timeout).
    # Keep below the gunicorn --timeout (180) watchdog. Used by BoundedDrainUvicornWorker.
    GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS: int = 30
    WSGI_THREADPOOL_WORKERS: int = 96
    SSE_KEEPALIVE_SECONDS: int = Field(default=15, ge=1)
    # Simultaneous SSE connections per user; each holds a WSGI thread and a Redis pub/sub
    # connection. 8 covers multi-tab use without one user starving the pool. 0 disables.
    SSE_MAX_CONCURRENT_PER_USER: int = 8
    # Backlog entries XRANGE returns per /api/events snapshot. Bounds what one replay moves
    # from Redis to the wire: a client looping Last-Event-ID reconnects enumerates at most
    # this many per round-trip, and the budget below bounds total throughput.
    EVENTS_REPLAY_MAX_PER_REQUEST: int = 200
    EVENTS_REPLAY_MAX_AGE_HOURS: int = 48
    # Sliding-window cap on snapshot replays per user; exhausting it returns 429 with the
    # cursor pinned so the client backs off until the window rolls over.
    EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW: int = 30
    EVENTS_REPLAY_BUDGET_WINDOW_SECONDS: int = 60

    # Retention for the message_events journal, enforced by the cleanup_message_events beat
    # task. Replay only needs streams a client could still be tailing.
    MESSAGE_EVENTS_RETENTION_DAYS: int = 14

    # Remote Device feature.
    REMOTE_DEVICE_SESSION_IDLE_SECONDS: int = 60
    REMOTE_DEVICE_REQUIRE_SIGNATURE: bool = False
    REMOTE_DEVICE_PAIRING_TTL_SECONDS: int = 600
    # Redis broker tunables, routing invocations cross-process so a scheduled run reaches the
    # web-held device session. The queue TTL must exceed the max drain deadline (605s) so a
    # command for a briefly-offline device isn't evicted before its own drain gives up.
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

    # Code-execution sandbox. The app is a CLIENT of an always-on runner; defaults are safe so
    # app import never fails when the sandbox is unconfigured.
    SANDBOX_BACKEND: str = "jupyter"  # "jupyter" (self-host) | "daytona" (Daytona Cloud)
    # URL of the Jupyter Kernel Gateway runner (the docsgpt-sandbox service).
    SANDBOX_GATEWAY_URL: str = "http://localhost:8888"
    SANDBOX_GATEWAY_AUTH_TOKEN: Optional[str] = None  # gateway auth token, if set
    # Kernelspec per session. The env-scrubbing "docsgpt-python" spec keeps kernel code from
    # reading the gateway token or operator secrets from os.environ; the stock "python3" spec
    # inherits the gateway env verbatim and must not be used with untrusted code.
    SANDBOX_KERNEL_NAME: str = "docsgpt-python"
    SANDBOX_MAX_TTL: int = 1200  # hard cap (s) on agent-selectable keep-alive TTL
    # Concurrent live sessions per process, backend-agnostic; at the cap an LRU-idle session is
    # evicted. 0 or negative disables the cap.
    SANDBOX_MAX_SESSIONS: int = 32
    SANDBOX_EXEC_TIMEOUT: int = 60  # default wall-clock cap (s) per exec call
    SANDBOX_HTTP_TIMEOUT: int = 10  # fixed cap (s) for REST control calls (create/delete/alive/interrupt)
    SANDBOX_MAX_OUTPUT_BYTES: int = 8 * 1024 * 1024  # cap on buffered stdout+stderr per exec
    SANDBOX_MAX_FILE_BYTES: int = 10 * 1024 * 1024  # cap on get_file size routed through stdout
    SANDBOX_MAX_INPUT_BYTES: int = 25 * 1024 * 1024  # cap on an input document staged into a sandbox session
    # ``read_document`` parsing on a dedicated Celery ``parsing`` queue (backend parser).
    DOCUMENT_PARSE_QUEUE: str = "parsing"  # queue the parse_document task is routed to
    DOCUMENT_PARSE_TIMEOUT: int = 120  # seconds the tool awaits the enqueued parse before degrading
    # The base timeout is a FLOOR: the window grows with document size, because OCR cost scales
    # with pages. Without this a large scan is silently dropped at the base window.
    DOCUMENT_PARSE_TIMEOUT_PER_MB: int = 60  # extra seconds of parse window per MiB of input
    DOCUMENT_PARSE_TIMEOUT_MAX: int = 900  # absolute ceiling on the size-scaled parse window
    DOCUMENT_PARSE_MAX_BYTES: int = 0  # cap on a parsed document's bytes (0 = reuse SANDBOX_MAX_INPUT_BYTES)
    DOCUMENT_MAX_DECOMPRESSED_BYTES: int = 300 * 1024 * 1024
    DOCUMENT_MAX_ARCHIVE_ENTRIES: int = 10000
    # Files per node passed natively to the LLM; past the cap they are extracted to text or
    # dropped, to bound context and cost. Re-uses SANDBOX_MAX_INPUT_BYTES per file.
    WORKFLOW_NODE_NATIVE_MAX_FILES: int = 5
    # Documents per node extracted via the parsing worker. Each issues a separate blocking
    # parse; past the cap they are skipped with a truncation note.
    WORKFLOW_NODE_EXTRACT_MAX_FILES: int = 5
    # Wall clock one node may spend on blocking parses, shared across all of them. Without it a
    # node could serialize WORKFLOW_NODE_EXTRACT_MAX_FILES full windows on a web threadpool slot.
    WORKFLOW_NODE_EXTRACT_BUDGET_SECONDS: int = 900
    # A run row is pre-created as ``running``; a disconnect or crash can strand it there. The
    # beat reaper fails runs still ``running`` past this. Generous so a long run is never cut off.
    WORKFLOW_RUN_STALE_SECONDS: int = 3600
    # Runner container caps, consumed by the docsgpt-sandbox compose service, not the app.
    # These cgroup limits are part of the untrusted-code security boundary.
    SANDBOX_MEMORY: str = "1g"  # docker mem_limit for the runner container
    SANDBOX_CPUS: str = "1.0"  # docker cpu quota for the runner container
    # Daytona Cloud backend (SANDBOX_BACKEND="daytona"). All knobs are optional so app import
    # never fails when the backend is unused.
    DAYTONA_API_KEY: Optional[str] = None  # Daytona Cloud API key (secret)
    DAYTONA_API_URL: Optional[str] = None  # override Daytona API base URL, if self-targeting
    DAYTONA_TARGET: Optional[str] = None  # Daytona region/target, e.g. "us"
    DAYTONA_SNAPSHOT: Optional[str] = None  # image for new sandboxes; render libs via scripts/build_daytona_snapshot.py
    DAYTONA_LANGUAGE: str = "python"  # default runtime language for created sandboxes
    DAYTONA_AUTO_STOP_INTERVAL: int = 15  # minutes idle before Daytona auto-stops a sandbox (0 disables)
    DAYTONA_AUTO_DELETE_INTERVAL: int = 60  # minutes after stop before Daytona auto-deletes (-1 disables)
    DAYTONA_MAX_SANDBOXES: int = 50  # cap on concurrent live Daytona sandboxes (cost-DoS guard)
    # Per-user artifact quotas, enforced at persistence time. 0 or negative disables a quota.
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
