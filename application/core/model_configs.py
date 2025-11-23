"""
Model configurations for all supported LLM providers.
"""

from application.core.model_settings import (
    AvailableModel,
    ModelCapabilities,
    ModelProvider,
)

OPENAI_ATTACHMENTS = [
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
]

GOOGLE_ATTACHMENTS = [
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
]


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
            context_window=400000,
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
            context_window=400000,
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
            context_window=20000,  # Set low for testing compression
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
        id="llama-3.1-8b-instant",
        provider=ModelProvider.GROQ,
        display_name="Llama 3.1 8B",
        description="Ultra-fast inference",
        capabilities=ModelCapabilities(
            supports_tools=True,
            context_window=128000,
        ),
    ),
    AvailableModel(
        id="mixtral-8x7b-32768",
        provider=ModelProvider.GROQ,
        display_name="Mixtral 8x7B",
        description="High-speed inference with tools",
        capabilities=ModelCapabilities(
            supports_tools=True,
            context_window=32768,
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
