from application.llm.openai import OpenAILLM, AzureOpenAILLM
from application.llm.sagemaker import SagemakerAPILLM
from application.llm.huggingface import HuggingFaceLLM



class LLMCreator:
    llms = {
        'openai': OpenAILLM,
        'azure_openai': AzureOpenAILLM,
        'sagemaker': SagemakerAPILLM,
        'huggingface': HuggingFaceLLM
    }

    @classmethod
    def create_llm(cls, type, *args, **kwargs):
        llm_class = cls.llms.get(type.lower())
        if not llm_class:
            raise ValueError(f"No LLM class found for type {type}")
        return llm_class(*args, **kwargs)