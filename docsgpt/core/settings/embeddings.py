"""Embedding model selection and where it runs."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, field_validator

from docsgpt.core.paths import home_dir
from docsgpt.core.settings._shared import SettingsGroup, normalize_choice


class EmbeddingsSettings(SettingsGroup):
    """The embedding model, remote or local, and the batching around it."""

    EMBEDDINGS_NAME: str = Field(
        default="huggingface_sentence-transformers/all-mpnet-base-v2",
        description=(
            "Embedding model. The legacy model is the default on purpose: an install that never pinned this "
            "has vectors from it, and granite is the same width so a swap would fail silently. New installs "
            "get granite from .env-template; existing ones switch by setting this and running "
            "docsgpt.scripts.reembed."
        ),
    )
    EMBEDDINGS_BASE_URL: Optional[str] = Field(
        default=None, description="Remote embeddings API URL (OpenAI-compatible)."
    )
    EMBEDDINGS_KEY: Optional[str] = Field(
        default=None, description="API key for embeddings (with OpenAI, the same value as API_KEY)."
    )
    EMBEDDINGS_MAX_INPUT_TOKENS: Optional[int] = Field(
        default=None, description="Truncate each remote embed input to N tokens (overflow is lost)."
    )
    EMBEDDINGS_BATCH_SIZE: int = Field(
        default=32, ge=1, description="Chunks per store transaction and per remote embed request."
    )
    EMBEDDINGS_MODEL_BATCH_SIZE: int = Field(
        default=1,
        ge=1,
        description=(
            "Documents per local ONNX forward pass. Each pass pads to its longest input, and that waste grows "
            "with the square of chunk length: at 1250 tokens, 32 peaked at 6.6 GB, 1 at 2.9 GB."
        ),
    )
    EMBEDDINGS_THREADS: Optional[int] = Field(
        default=None,
        description=(
            "Intra-op threads for the local ONNX runner; unset uses every core. It scales sub-linearly, so "
            "several single-threaded workers beat one many-threaded process on the same cores."
        ),
    )
    EMBEDDINGS_CACHE_DIR: Optional[str] = Field(
        default_factory=lambda: str(home_dir() / "models"),
        description=(
            "Where embedding models and their tokenizers are cached. Persistent by default: FastEmbed's own "
            "default is the temp dir."
        ),
    )
    EMBEDDINGS_POOLING: Optional[Literal["cls", "mean"]] = Field(
        default=None,
        description=(
            'Pooling strategy ("cls" or "mean"). Read from the model\'s own repository; set only for a '
            "repository that declares none, or to override what it declares."
        ),
    )
    EMBEDDINGS_NORMALIZE: Optional[bool] = Field(
        default=None,
        description=(
            "L2-normalise embeddings. Read from the model's own repository; set only for a repository that "
            "declares nothing, or to override what it declares."
        ),
    )
    EMBEDDINGS_DELEGATE_TO_WORKER: bool = Field(
        default=True,
        description=(
            "Embed on the worker so the API holds no model (~890 MB), at one broker round trip per query. "
            "Ignored when EMBEDDINGS_BASE_URL is set, which is the better answer for production."
        ),
    )
    EMBEDDINGS_QUEUE: str = Field(default="embeddings", description="Celery queue the embed task is routed to.")
    EMBEDDINGS_DELEGATE_TIMEOUT: int = Field(
        default=60, gt=0, description="Seconds the API waits for the worker to return an embedding."
    )

    @field_validator("EMBEDDINGS_POOLING", mode="before")
    @classmethod
    def _normalize_pooling(cls, v):
        return normalize_choice(v)
