import logging

from application.llm.anthropic import AnthropicLLM
from application.llm.docsgpt_provider import DocsGPTAPILLM
from application.llm.google_ai import GoogleLLM
from application.llm.groq import GroqLLM
from application.llm.llama_cpp import LlamaCpp
from application.llm.novita import NovitaLLM
from application.llm.openai import AzureOpenAILLM, OpenAILLM
from application.llm.premai import PremAILLM
from application.llm.sagemaker import SagemakerAPILLM
from application.llm.open_router import OpenRouterLLM

logger = logging.getLogger(__name__)


class LLMCreator:
    llms = {
        "openai": OpenAILLM,
        "azure_openai": AzureOpenAILLM,
        "sagemaker": SagemakerAPILLM,
        "llama.cpp": LlamaCpp,
        "anthropic": AnthropicLLM,
        "docsgpt": DocsGPTAPILLM,
        "premai": PremAILLM,
        "groq": GroqLLM,
        "google": GoogleLLM,
        "novita": NovitaLLM,
        "openrouter": OpenRouterLLM,
    }

    @classmethod
    def create_llm(
        cls, type, api_key, user_api_key, decoded_token, model_id=None, *args, **kwargs
    ):
        from application.core.model_utils import get_base_url_for_model

        llm_class = cls.llms.get(type.lower())
        if not llm_class:
            raise ValueError(f"No LLM class found for type {type}")

        # Extract base_url from model configuration if model_id is provided
        base_url = None
        if model_id:
            base_url = get_base_url_for_model(model_id)

        return llm_class(
            api_key,
            user_api_key,
            decoded_token=decoded_token,
            model_id=model_id,
            base_url=base_url,
            *args,
            **kwargs,
        )
