import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Re-exported here so existing call sites (and tests) that do
# ``from application.core.model_settings import ModelRegistry`` keep
# working. The implementation lives in ``application/core/model_registry.py``.
# Imported lazily inside ``__getattr__`` to avoid an import cycle with
# ``model_yaml`` → ``model_settings`` (this file).


class ModelProvider(str, Enum):
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    OPENROUTER = "openrouter"
    AZURE_OPENAI = "azure_openai"
    ANTHROPIC = "anthropic"
    GROQ = "groq"
    GOOGLE = "google"
    HUGGINGFACE = "huggingface"
    LLAMA_CPP = "llama.cpp"
    DOCSGPT = "docsgpt"
    PREMAI = "premai"
    SAGEMAKER = "sagemaker"
    NOVITA = "novita"


@dataclass
class ModelCapabilities:
    supports_tools: bool = False
    supports_structured_output: bool = False
    supports_streaming: bool = True
    supported_attachment_types: List[str] = field(default_factory=list)
    context_window: int = 128000
    input_cost_per_token: Optional[float] = None
    output_cost_per_token: Optional[float] = None


@dataclass
class AvailableModel:
    id: str
    provider: ModelProvider
    display_name: str
    description: str = ""
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    enabled: bool = True
    base_url: Optional[str] = None
    # User-facing label distinct from the dispatch ``provider``. Used by
    # openai_compatible YAMLs so a Mistral model shows "mistral" in the
    # API response while still routing through the OpenAI wire format.
    display_provider: Optional[str] = None
    # Per-record API key. Operator YAMLs leave this None; populated for
    # openai_compatible models (resolved from the YAML's ``api_key_env``)
    # and reserved for the future end-user BYOM phase. Never serialized
    # into to_dict().
    api_key: Optional[str] = field(default=None, repr=False, compare=False)

    def to_dict(self) -> Dict:
        result = {
            "id": self.id,
            "provider": self.display_provider or self.provider.value,
            "display_name": self.display_name,
            "description": self.description,
            "supported_attachment_types": self.capabilities.supported_attachment_types,
            "supports_tools": self.capabilities.supports_tools,
            "supports_structured_output": self.capabilities.supports_structured_output,
            "supports_streaming": self.capabilities.supports_streaming,
            "context_window": self.capabilities.context_window,
            "enabled": self.enabled,
        }
        if self.base_url:
            result["base_url"] = self.base_url
        return result


def __getattr__(name):
    """Lazy re-export of ``ModelRegistry`` from ``model_registry.py``.

    Done lazily to avoid an import cycle: ``model_registry`` imports
    ``model_yaml`` which imports the dataclasses from this file.
    """
    if name == "ModelRegistry":
        from application.core.model_registry import ModelRegistry as _MR

        return _MR
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
