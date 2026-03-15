from application.core.settings import settings
from application.llm.openai import OpenAILLM

DOCSGPT_API_KEY = "sk-docsgpt-public"
DOCSGPT_BASE_URL = "https://oai.arc53.com"
DOCSGPT_MODEL = "docsgpt"

class DocsGPTAPILLM(OpenAILLM):
    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=DOCSGPT_API_KEY,
            user_api_key=user_api_key,
            base_url=DOCSGPT_BASE_URL,
            *args,
            **kwargs,
        )

    def _raw_gen(
        self,
        baseself,
        model,
        messages,
        stream=False,
        tools=None,
        engine=settings.AZURE_DEPLOYMENT_NAME,
        response_format=None,
        **kwargs,
    ):
        return super()._raw_gen(
            baseself,
            DOCSGPT_MODEL,
            messages,
            stream=stream,
            tools=tools,
            engine=engine,
            response_format=response_format,
            **kwargs,
        )

    def _raw_gen_stream(
        self,
        baseself,
        model,
        messages,
        stream=True,
        tools=None,
        engine=settings.AZURE_DEPLOYMENT_NAME,
        response_format=None,
        **kwargs,
    ):
        return super()._raw_gen_stream(
            baseself,
            DOCSGPT_MODEL,
            messages,
            stream=stream,
            tools=tools,
            engine=engine,
            response_format=response_format,
            **kwargs,
        )
