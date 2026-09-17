"""LLM providers, API keys and per-provider tunables."""

from __future__ import annotations

import os
from typing import Optional

from pydantic import Field, field_validator

from docsgpt.core.paths import home_dir
from docsgpt.core.settings._shared import SettingsGroup, normalize_secret


class LLMSettings(SettingsGroup):
    """Which model answers, how it is reached, and provider-specific behaviour."""

    LLM_PROVIDER: str = Field(default="docsgpt", description="LLM provider key, e.g. openai, anthropic, docsgpt.")
    LLM_NAME: Optional[str] = Field(
        default=None, description="Model name for the provider; with openai, e.g. gpt-4 or gpt-3.5-turbo."
    )
    API_KEY: Optional[str] = Field(default=None, description="LLM API key used by LLM_PROVIDER.")

    # Provider-specific API keys (for multi-model support).
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="OpenAI API key.")
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None, description="Anthropic API key.")
    GOOGLE_API_KEY: Optional[str] = Field(default=None, description="Google AI API key.")
    GROQ_API_KEY: Optional[str] = Field(default=None, description="Groq API key.")
    HUGGINGFACE_API_KEY: Optional[str] = Field(default=None, description="Hugging Face API key.")
    OPEN_ROUTER_API_KEY: Optional[str] = Field(default=None, description="OpenRouter API key.")
    NOVITA_API_KEY: Optional[str] = Field(default=None, description="Novita API key.")

    OPENAI_API_BASE: Optional[str] = Field(default=None, description="Azure OpenAI API base URL.")
    OPENAI_API_VERSION: Optional[str] = Field(default=None, description="Azure OpenAI API version.")
    AZURE_DEPLOYMENT_NAME: Optional[str] = Field(default=None, description="Azure deployment name for answering.")
    AZURE_EMBEDDINGS_DEPLOYMENT_NAME: Optional[str] = Field(
        default=None, description="Azure deployment name for embeddings."
    )
    OPENAI_BASE_URL: Optional[str] = Field(
        default=None, description="Base URL for OpenAI-compatible model servers."
    )
    LLM_PATH: str = Field(
        default=os.path.join(str(home_dir()), "models/docsgpt-7b-f16.gguf"),
        description="Path to the local GGUF model used by the llama.cpp provider.",
    )

    FALLBACK_LLM_PROVIDER: Optional[str] = Field(default=None, description="Provider for the fallback LLM.")
    FALLBACK_LLM_NAME: Optional[str] = Field(default=None, description="Model name for the fallback LLM.")
    FALLBACK_LLM_API_KEY: Optional[str] = Field(default=None, description="API key for the fallback LLM.")
    TITLE_MODEL_ID: Optional[str] = Field(
        default=None, description="Optional cheaper model for conversation titles; unset reuses the answer model."
    )
    MODELS_CONFIG_DIR: Optional[str] = Field(
        default=None,
        description=(
            "Directory of operator-supplied model YAMLs, loaded after the built-in catalog; later wins on "
            "duplicate model id. See docsgpt/core/models/README.md."
        ),
    )
    DEFAULT_LLM_TOKEN_LIMIT: int = Field(
        default=128000, description="Context window assumed when the model is not found in the registry."
    )
    RESERVED_TOKENS: dict = Field(
        default={"system_prompt": 500, "current_query": 500, "safety_buffer": 1000},
        description="Tokens held back from the context window for the system prompt, the query and a safety buffer.",
    )
    CACHE_REDIS_URL: str = Field(default="redis://localhost:6379/2", description="Redis URL for the LLM cache.")

    # OpenAI Responses API.
    OPENAI_RESPONSES_STORE: bool = Field(
        default=False,
        description=(
            "True persists Responses API calls server-side so previous_response_id can chain turns. False keeps "
            "them stateless, carrying reasoning across the tool loop as encrypted items."
        ),
    )
    OPENAI_RESPONSES_CHAIN_ACROSS_TURNS: bool = Field(
        default=True,
        description=(
            "Cross-turn previous_response_id chaining (store mode only). The chained transcript lives on the "
            "provider and is invisible to every local guard, so it is bounded: a turn starts from the local "
            "history when the previous turn's reported prompt already reached the budget (default: the model's "
            "context window) or when the conversation was compressed after that turn was produced."
        ),
    )
    OPENAI_RESPONSES_CHAIN_BUDGET_TOKENS: Optional[int] = Field(
        default=None, description="Prompt-token budget for cross-turn chaining; unset uses the model's context window."
    )
    OPENAI_RESPONSES_TRUNCATION_AUTO: bool = Field(
        default=False,
        description=(
            'Send truncation: "auto" so the provider drops the oldest input items instead of failing every '
            "request once a chain exceeds the model's window."
        ),
    )
    OPENAI_PROMPT_CACHE_KEY: bool = Field(
        default=True,
        description=(
            "Route a user's Responses API calls to the same prompt-cache shard with an opaque per-user key."
        ),
    )
    OPENAI_PROMPT_CACHE_RETENTION: Optional[str] = Field(
        default=None, description="Request extended prompt-cache retention where the provider offers it."
    )
    OPENAI_REASONING_SUMMARY: str = Field(
        default="auto", description="Reasoning summary mode requested from the Responses API."
    )

    @field_validator(
        "API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "HUGGINGFACE_API_KEY",
        "NOVITA_API_KEY",
        "FALLBACK_LLM_API_KEY",
        mode="before",
    )
    @classmethod
    def _normalize_llm_secrets(cls, v):
        return normalize_secret(v)
