from application.llm.base import BaseLLM
from application.core.settings import settings

class OpenAILLM(BaseLLM):

    def __init__(self, api_key):
        global litellm
        import litellm

        litellm.api_key = api_key
        self.api_key = api_key  # Save the API key to be used later

    def _get_openai(self):
        # Import openai when needed
        import litellm
        # Set the API key every time you import litellm
        litellm.api_key = self.api_key
        return litellm

    def gen(self, model, engine, messages, stream=False, **kwargs):
        response = litellm.completion(
            model=model,
            engine=engine,
            messages=messages,
            stream=stream,
            **kwargs
        )

        return response["choices"][0]["message"]["content"]

    def gen_stream(self, model, engine, messages, stream=True, **kwargs):
        response = litellm.completion(
            model=model,
            engine=engine,
            messages=messages,
            stream=stream,
            **kwargs
        )

        for line in response:
            if "content" in line["choices"][0]["delta"]:
                yield line["choices"][0]["delta"]["content"]


class AzureOpenAILLM(OpenAILLM):

    def __init__(self, openai_api_key, openai_api_base, openai_api_version, deployment_name):
        super().__init__(openai_api_key)
        self.api_base = settings.OPENAI_API_BASE,
        self.api_version = settings.OPENAI_API_VERSION,
        self.deployment_name = settings.AZURE_DEPLOYMENT_NAME,

    def _get_openai(self):
        litellm = super()._get_openai()
        litellm.api_base = self.api_base
        litellm.api_version = self.api_version
        litellm.api_type = "azure"
        return litellm
