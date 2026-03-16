"""
Model configurations for all supported LLM providers.
"""

from application.core.model_settings import (
    AvailableModel,
    ModelCapabilities,
    ModelProvider,
)

# Base image attachment types supported by most vision-capable LLMs
IMAGE_ATTACHMENTS = [
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
]

# PDF excluded: most OpenAI-compatible endpoints don't support native PDF uploads.
# When excluded, PDFs are synthetically processed by converting pages to images.
OPENAI_ATTACHMENTS = IMAGE_ATTACHMENTS

GOOGLE_ATTACHMENTS = ["application/pdf"] + IMAGE_ATTACHMENTS

ANTHROPIC_ATTACHMENTS = IMAGE_ATTACHMENTS

OPENROUTER_ATTACHMENTS = IMAGE_ATTACHMENTS


OPENAI_MODELS = [
    AvailableModel(
        id="gpt-5.1",
        provider=ModelProvider.OPENAI,
        display_name="GPT-5.1",
        description="Flagship model with enhanced reasoning, coding, and agentic capabilities",
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_structured_output=True,
            supported_attachment_types=OPENAI_ATTACHMENTS,
            context_window=200000,
        ),
    ),
    AvailableModel(
        id="gpt-5-mini",
        provider=ModelProvider.OPENAI,
        display_name="GPT-5 Mini",
        description="Faster, cost-effective variant of GPT-5.1",
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_structured_output=True,
            supported_attachment_types=OPENAI_ATTACHMENTS,
            context_window=200000,
        ),
    )
]


ANTHROPIC_MODELS = [
    AvailableModel(
        id="claude-3-5-sonnet-20241022",
        provider=ModelProvider.ANTHROPIC,
        display_name="Claude 3.5 Sonnet (Latest)",
        description="Latest Claude 3.5 Sonnet with enhanced capabilities",
        capabilities=ModelCapabilities(
            supports_tools=True,
            supported_attachment_types=ANTHROPIC_ATTACHMENTS,
            context_window=200000,
        ),
    ),
    AvailableModel(
        id="claude-3-5-sonnet",
        provider=ModelProvider.ANTHROPIC,
        display_name="Claude 3.5 Sonnet",
        description="Balanced performance and capability",
        capabilities=ModelCapabilities(
            supports_tools=True,
            supported_attachment_types=ANTHROPIC_ATTACHMENTS,
            context_window=200000,
        ),
    ),
    AvailableModel(
        id="claude-3-opus",
        provider=ModelProvider.ANTHROPIC,
        display_name="Claude 3 Opus",
        description="Most capable Claude model",
        capabilities=ModelCapabilities(
            supports_tools=True,
            supported_attachment_types=ANTHROPIC_ATTACHMENTS,
            context_window=200000,
        ),
    ),
    AvailableModel(
        id="claude-3-haiku",
        provider=ModelProvider.ANTHROPIC,
        display_name="Claude 3 Haiku",
        description="Fastest Claude model",
        capabilities=ModelCapabilities(
            supports_tools=True,
            supported_attachment_types=ANTHROPIC_ATTACHMENTS,
            context_window=200000,
        ),
    ),
]


GOOGLE_MODELS = [
    AvailableModel(
        id="gemini-flash-latest",
        provider=ModelProvider.GOOGLE,
        display_name="Gemini Flash (Latest)",
        description="Latest experimental Gemini model",
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_structured_output=True,
            supported_attachment_types=GOOGLE_ATTACHMENTS,
            context_window=int(1e6),
        ),
    ),
    AvailableModel(
        id="gemini-flash-lite-latest",
        provider=ModelProvider.GOOGLE,
        display_name="Gemini Flash Lite (Latest)",
        description="Fast with huge context window",
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_structured_output=True,
            supported_attachment_types=GOOGLE_ATTACHMENTS,
            context_window=int(1e6),
        ),
    ),
    AvailableModel(
        id="gemini-3-pro-preview",
        provider=ModelProvider.GOOGLE,
        display_name="Gemini 3 Pro",
        description="Most capable Gemini model",
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_structured_output=True,
            supported_attachment_types=GOOGLE_ATTACHMENTS,
            context_window=2000000,
        ),
    ),
]


GROQ_MODELS = [
    AvailableModel(
        id="llama-3.3-70b-versatile",
        provider=ModelProvider.GROQ,
        display_name="Llama 3.3 70B",
        description="Latest Llama model with high-speed inference",
        capabilities=ModelCapabilities(
            supports_tools=True,
            context_window=128000,
        ),
    ),
    AvailableModel(
        id="openai/gpt-oss-120b",
        provider=ModelProvider.GROQ,
        display_name="GPT-OSS 120B",
        description="Open-source GPT model optimized for speed",
        capabilities=ModelCapabilities(
            supports_tools=True,
            context_window=128000,
        ),
    ),
]


OPENROUTER_MODELS = [
    AvailableModel(
        id="qwen/qwen3-coder:free",
        provider=ModelProvider.OPENROUTER,
        display_name="Qwen 3 Coder",
        description="Latest Qwen model with high-speed inference",
        capabilities=ModelCapabilities(
            supports_tools=True,
            context_window=128000,
            supported_attachment_types=OPENROUTER_ATTACHMENTS
        ),
    ),
    AvailableModel(
        id="google/gemma-3-27b-it:free",
        provider=ModelProvider.OPENROUTER,
        display_name="Gemma 3 27B",
        description="Latest Gemma model with high-speed inference",
        capabilities=ModelCapabilities(
            supports_tools=True,
            context_window=128000,
            supported_attachment_types=OPENROUTER_ATTACHMENTS
        ),
    ),
]

AZURE_OPENAI_MODELS = [
    AvailableModel(
        id="azure-gpt-4",
        provider=ModelProvider.AZURE_OPENAI,
        display_name="Azure OpenAI GPT-4",
        description="Azure-hosted GPT model",
        capabilities=ModelCapabilities(
            supports_tools=True,
            supports_structured_output=True,
            supported_attachment_types=OPENAI_ATTACHMENTS,
            context_window=8192,
        ),
    ),
]


def create_custom_openai_model(model_name: str, base_url: str) -> AvailableModel:
    """Create a custom OpenAI-compatible model (e.g., LM Studio, Ollama)."""
    return AvailableModel(
        id=model_name,
        provider=ModelProvider.OPENAI,
        display_name=model_name,
        description=f"Custom OpenAI-compatible model at {base_url}",
        base_url=base_url,
        capabilities=ModelCapabilities(
            supports_tools=True,
            supported_attachment_types=OPENAI_ATTACHMENTS,
        ),
    )
