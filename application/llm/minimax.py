from application.core.settings import settings
from application.llm.openai import OpenAILLM

MINIMAX_BASE_URL = "https://api.minimax.io/v1"


class MiniMaxLLM(OpenAILLM):
    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.MINIMAX_API_KEY or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or MINIMAX_BASE_URL,
            *args,
            **kwargs,
        )

    @staticmethod
    def _clamp_temperature(kwargs):
        """Clamp temperature to MiniMax's valid range (0.0, 1.0]."""
        if "temperature" in kwargs:
            temp = kwargs["temperature"]
            if temp is not None:
                temp = float(temp)
                if temp <= 0:
                    kwargs["temperature"] = 0.01
                elif temp > 1.0:
                    kwargs["temperature"] = 1.0

    def _raw_gen(
        self,
        baseself,
        model,
        messages,
        stream=False,
        tools=None,
        response_format=None,
        **kwargs,
    ):
        self._clamp_temperature(kwargs)
        # MiniMax does not support response_format; drop it
        return super()._raw_gen(
            baseself,
            model,
            messages,
            stream=stream,
            tools=tools,
            response_format=None,
            **kwargs,
        )

    def _raw_gen_stream(
        self,
        baseself,
        model,
        messages,
        stream=True,
        tools=None,
        response_format=None,
        **kwargs,
    ):
        self._clamp_temperature(kwargs)
        # MiniMax does not support response_format; drop it
        return super()._raw_gen_stream(
            baseself,
            model,
            messages,
            stream=stream,
            tools=tools,
            response_format=None,
            **kwargs,
        )

    def _supports_structured_output(self):
        return False
