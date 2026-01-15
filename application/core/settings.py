import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

current_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    AUTH_TYPE: Optional[str] = None  # simple_jwt, session_jwt, or None
    LLM_PROVIDER: str = "docsgpt"
    LLM_NAME: Optional[str] = (
        None  # if LLM_PROVIDER is openai, LLM_NAME can be gpt-4 or gpt-3.5-turbo
    )
    EMBEDDINGS_NAME: str = "huggingface_sentence-transformers/all-mpnet-base-v2"
    EMBEDDINGS_BASE_URL: Optional[str] = None  # Remote embeddings API URL (OpenAI-compatible)
    EMBEDDINGS_KEY: Optional[str] = (
        None  # api key for embeddings (if using openai, just copy API_KEY)
    )
    
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    MONGO_URI: str = "mongodb://localhost:27017/docsgpt"
    MONGO_DB_NAME: str = "docsgpt"
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
    VECTOR_STORE: str = (
        "faiss"  #  "faiss" or "elasticsearch" or "qdrant" or "milvus" or "lancedb" or "pgvector"
    )
    RETRIEVERS_ENABLED: list = ["classic_rag"]
    AGENT_NAME: str = "classic"
    FALLBACK_LLM_PROVIDER: Optional[str] = None  # provider for fallback llm
    FALLBACK_LLM_NAME: Optional[str] = None  # model name for fallback llm
    FALLBACK_LLM_API_KEY: Optional[str] = None  # api key for fallback llm

    # Google Drive integration
    GOOGLE_CLIENT_ID: Optional[str] = (
        None  # Replace with your actual Google OAuth client ID
    )
    GOOGLE_CLIENT_SECRET: Optional[str] = (
        None  # Replace with your actual Google OAuth client secret
    )
    CONNECTOR_REDIRECT_BASE_URI: Optional[str] = (
        "http://127.0.0.1:7091/api/connectors/callback"  ##add redirect url as it is to your provider's console(gcp)
    )

    # GitHub source
    GITHUB_ACCESS_TOKEN: Optional[str] = None  # PAT token with read repo access

    # LLM Cache
    CACHE_REDIS_URL: str = "redis://localhost:6379/2"

    API_URL: str = "http://localhost:7091"  # backend url for celery worker
    INTERNAL_KEY: Optional[str] = None  # internal api key for worker-to-backend auth

    API_KEY: Optional[str] = None  # LLM api key (used by LLM_PROVIDER)

    # Provider-specific API keys (for multi-model support)
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    HUGGINGFACE_API_KEY: Optional[str] = None
    OPEN_ROUTER_API_KEY: Optional[str] = None

    OPENAI_API_BASE: Optional[str] = None  # azure openai api base url
    OPENAI_API_VERSION: Optional[str] = None  # azure openai api version
    AZURE_DEPLOYMENT_NAME: Optional[str] = None  # azure deployment name for answering
    AZURE_EMBEDDINGS_DEPLOYMENT_NAME: Optional[str] = (
        None  # azure deployment name for embeddings
    )
    OPENAI_BASE_URL: Optional[str] = (
        None  # openai base url for open ai compatable models
    )

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

    # PGVector vectorstore config
    PGVECTOR_CONNECTION_STRING: Optional[str] = None
    # Milvus vectorstore config
    MILVUS_COLLECTION_NAME: Optional[str] = "docsgpt"
    MILVUS_URI: Optional[str] = "./milvus_local.db"  # milvus lite version as default
    MILVUS_TOKEN: Optional[str] = ""

    # LanceDB vectorstore config
    LANCEDB_PATH: str = "./data/lancedb"  # Path where LanceDB stores its local data
    LANCEDB_TABLE_NAME: Optional[str] = (
        "docsgpts"  # Name of the table to use for storing vectors
    )

    FLASK_DEBUG_MODE: bool = False
    STORAGE_TYPE: str = "local"  # local or s3
    URL_STRATEGY: str = "backend"  # backend or s3

    JWT_SECRET_KEY: str = ""

    # Encryption settings
    ENCRYPTION_SECRET_KEY: str = "default-docsgpt-encryption-key"

    TTS_PROVIDER: str = "google_tts"  # google_tts or elevenlabs
    ELEVENLABS_API_KEY: Optional[str] = None

    # Tool pre-fetch settings
    ENABLE_TOOL_PREFETCH: bool = True

    # Conversation Compression Settings
    ENABLE_CONVERSATION_COMPRESSION: bool = True
    COMPRESSION_THRESHOLD_PERCENTAGE: float = 0.8  # Trigger at 80% of context
    COMPRESSION_MODEL_OVERRIDE: Optional[str] = None  # Use different model for compression
    COMPRESSION_PROMPT_VERSION: str = "v1.0"  # Track prompt iterations
    COMPRESSION_MAX_HISTORY_POINTS: int = 3  # Keep only last N compression points to prevent DB bloat


# Project root is one level above application/
path = Path(__file__).parent.parent.parent.absolute()
settings = Settings(_env_file=path.joinpath(".env"), _env_file_encoding="utf-8")
