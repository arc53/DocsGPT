from application.llm.openai import OpenAILLM, AzureOpenAILLM
from application.llm.sagemaker import SagemakerAPILLM
from application.llm.huggingface import HuggingFaceLLM
from application.llm.llama_cpp import LlamaCpp
from application.llm.anthropic import AnthropicLLM
from application.llm.docsgpt_provider import DocsGPTAPILLM
from application.llm.premai import PremAILLM


class LLMCreator:
    llms = {
        "openai": OpenAILLM,
        "azure_openai": AzureOpenAILLM,
        "sagemaker": SagemakerAPILLM,
        "huggingface": HuggingFaceLLM,
        "llama.cpp": LlamaCpp,
        "anthropic": AnthropicLLM,
        "docsgpt": DocsGPTAPILLM,
        "premai": PremAILLM,
    }

    singleton_llm = {
        'type': None,
        'llm': None
    }

    def create_llm(self, type, api_key, user_api_key, *args, **kwargs):
        llm_class = self.llms.get(type.lower())
        if not llm_class:
            raise ValueError(f"No LLM class found for type {type}")

        # do not create a new LLM (and allocate memory again) for each request for local models
        if self.singleton_llm['type'] != llm_class or self.singleton_llm['type'] != LlamaCpp:
            llm = llm_class(api_key, user_api_key, *args, **kwargs)
            self.singleton_llm['type'] = llm_class
            self.singleton_llm['llm'] = llm

        return self.singleton_llm['llm']
