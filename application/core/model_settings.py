import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ModelProvider(str, Enum):
    OPENAI = "openai"
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

    def to_dict(self) -> Dict:
        result = {
            "id": self.id,
            "provider": self.provider.value,
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


class ModelRegistry:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not ModelRegistry._initialized:
            self.models: Dict[str, AvailableModel] = {}
            self.default_model_id: Optional[str] = None
            self._load_models()
            ModelRegistry._initialized = True

    @classmethod
    def get_instance(cls) -> "ModelRegistry":
        return cls()

    def _load_models(self):
        from application.core.settings import settings

        self.models.clear()

        # Skip DocsGPT model if using custom OpenAI-compatible endpoint
        if not settings.OPENAI_BASE_URL:
            self._add_docsgpt_models(settings)
        if settings.OPENAI_API_KEY or (
            settings.LLM_PROVIDER == "openai" and settings.API_KEY
        ):
            self._add_openai_models(settings)
        if settings.OPENAI_API_BASE or (
            settings.LLM_PROVIDER == "azure_openai" and settings.API_KEY
        ):
            self._add_azure_openai_models(settings)
        if settings.ANTHROPIC_API_KEY or (
            settings.LLM_PROVIDER == "anthropic" and settings.API_KEY
        ):
            self._add_anthropic_models(settings)
        if settings.GOOGLE_API_KEY or (
            settings.LLM_PROVIDER == "google" and settings.API_KEY
        ):
            self._add_google_models(settings)
        if settings.GROQ_API_KEY or (
            settings.LLM_PROVIDER == "groq" and settings.API_KEY
        ):
            self._add_groq_models(settings)
        if settings.OPEN_ROUTER_API_KEY or (
            settings.LLM_PROVIDER == "openrouter" and settings.API_KEY
        ):
            self._add_openrouter_models(settings)
        if settings.HUGGINGFACE_API_KEY or (
            settings.LLM_PROVIDER == "huggingface" and settings.API_KEY
        ):
            self._add_huggingface_models(settings)
        # Default model selection

        if settings.LLM_NAME and settings.LLM_NAME in self.models:
            self.default_model_id = settings.LLM_NAME
        elif settings.LLM_PROVIDER and settings.API_KEY:
            for model_id, model in self.models.items():
                if model.provider.value == settings.LLM_PROVIDER:
                    self.default_model_id = model_id
                    break
        else:
            self.default_model_id = next(iter(self.models.keys()))
        logger.info(
            f"ModelRegistry loaded {len(self.models)} models, default: {self.default_model_id}"
        )

    def _add_openai_models(self, settings):
        from application.core.model_configs import (
            OPENAI_MODELS,
            create_custom_openai_model,
        )

        # Add standard OpenAI models if API key is present
        if settings.OPENAI_API_KEY:
            for model in OPENAI_MODELS:
                self.models[model.id] = model

        # Add custom model if OPENAI_BASE_URL is configured with a custom LLM_NAME
        if (
            settings.LLM_PROVIDER == "openai"
            and settings.OPENAI_BASE_URL
            and settings.LLM_NAME
        ):
            custom_model = create_custom_openai_model(
                settings.LLM_NAME, settings.OPENAI_BASE_URL
            )
            self.models[settings.LLM_NAME] = custom_model
            logger.info(
                f"Registered custom OpenAI model: {settings.LLM_NAME} at {settings.OPENAI_BASE_URL}"
            )

        # Fallback: add all OpenAI models if none were added
        if not any(m.provider.value == "openai" for m in self.models.values()):
            for model in OPENAI_MODELS:
                self.models[model.id] = model

    def _add_azure_openai_models(self, settings):
        from application.core.model_configs import AZURE_OPENAI_MODELS

        if settings.LLM_PROVIDER == "azure_openai" and settings.LLM_NAME:
            for model in AZURE_OPENAI_MODELS:
                if model.id == settings.LLM_NAME:
                    self.models[model.id] = model
                    return
        for model in AZURE_OPENAI_MODELS:
            self.models[model.id] = model

    def _add_anthropic_models(self, settings):
        from application.core.model_configs import ANTHROPIC_MODELS

        if settings.ANTHROPIC_API_KEY:
            for model in ANTHROPIC_MODELS:
                self.models[model.id] = model
            return
        if settings.LLM_PROVIDER == "anthropic" and settings.LLM_NAME:
            for model in ANTHROPIC_MODELS:
                if model.id == settings.LLM_NAME:
                    self.models[model.id] = model
                    return
        for model in ANTHROPIC_MODELS:
            self.models[model.id] = model

    def _add_google_models(self, settings):
        from application.core.model_configs import GOOGLE_MODELS

        if settings.GOOGLE_API_KEY:
            for model in GOOGLE_MODELS:
                self.models[model.id] = model
            return
        if settings.LLM_PROVIDER == "google" and settings.LLM_NAME:
            for model in GOOGLE_MODELS:
                if model.id == settings.LLM_NAME:
                    self.models[model.id] = model
                    return
        for model in GOOGLE_MODELS:
            self.models[model.id] = model

    def _add_groq_models(self, settings):
        from application.core.model_configs import GROQ_MODELS

        if settings.GROQ_API_KEY:
            for model in GROQ_MODELS:
                self.models[model.id] = model
            return
        if settings.LLM_PROVIDER == "groq" and settings.LLM_NAME:
            for model in GROQ_MODELS:
                if model.id == settings.LLM_NAME:
                    self.models[model.id] = model
                    return
        for model in GROQ_MODELS:
            self.models[model.id] = model
    
    def _add_openrouter_models(self, settings):
        from application.core.model_configs import OPENROUTER_MODELS

        if settings.OPEN_ROUTER_API_KEY:
            for model in OPENROUTER_MODELS:
                self.models[model.id] = model
            return
        if settings.LLM_PROVIDER == "openrouter" and settings.LLM_NAME:
            for model in OPENROUTER_MODELS:
                if model.id == settings.LLM_NAME:
                    self.models[model.id] = model
                    return
        for model in OPENROUTER_MODELS:
            self.models[model.id] = model

    def _add_docsgpt_models(self, settings):
        model_id = "docsgpt-local"
        model = AvailableModel(
            id=model_id,
            provider=ModelProvider.DOCSGPT,
            display_name="DocsGPT Model",
            description="Local model",
            capabilities=ModelCapabilities(
                supports_tools=False,
                supported_attachment_types=[],
            ),
        )
        self.models[model_id] = model

    def _add_huggingface_models(self, settings):
        model_id = "huggingface-local"
        model = AvailableModel(
            id=model_id,
            provider=ModelProvider.HUGGINGFACE,
            display_name="Hugging Face Model",
            description="Local Hugging Face model",
            capabilities=ModelCapabilities(
                supports_tools=False,
                supported_attachment_types=[],
            ),
        )
        self.models[model_id] = model

    def get_model(self, model_id: str) -> Optional[AvailableModel]:
        return self.models.get(model_id)

    def get_all_models(self) -> List[AvailableModel]:
        return list(self.models.values())

    def get_enabled_models(self) -> List[AvailableModel]:
        return [m for m in self.models.values() if m.enabled]

    def model_exists(self, model_id: str) -> bool:
        return model_id in self.models
