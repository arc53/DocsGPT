from application.llm.base import BaseLLM
from application.core.settings import settings

class OpenAILLM(BaseLLM):

    def __init__(self, api_key):
        global openai
        import openai
        openai.api_key = api_key
        self.api_key = api_key  # Save the API key to be used later

    def _get_openai(self):
        # Import openai when needed
        import openai
        # Set the API key every time you import openai
        openai.api_key = self.api_key
        return openai

    def gen(self, model, engine, messages, stream=False, **kwargs):
        response = openai.ChatCompletion.create(
            model=model,
            engine=engine,
            messages=messages,
            stream=stream,
            **kwargs
        )

        return response["choices"][0]["message"]["content"]

    def gen_stream(self, model, engine, messages, stream=True, **kwargs):
        response = openai.ChatCompletion.create(
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
        openai = super()._get_openai()
        openai.api_base = self.api_base
        openai.api_version = self.api_version
        openai.api_type = "azure"
        return openai
