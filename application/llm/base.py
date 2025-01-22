from abc import ABC, abstractmethod

from application.cache import gen_cache, stream_cache
from application.usage import gen_token_usage, stream_token_usage


class BaseLLM(ABC):
    def __init__(self):
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

    def _apply_decorator(self, method, decorators, *args, **kwargs):
        for decorator in decorators:
            method = decorator(method)
        return method(self, *args, **kwargs)

    @abstractmethod
    def _raw_gen(self, model, messages, stream, tools, *args, **kwargs):
        pass

    def gen(self, model, messages, stream=False, tools=None, *args, **kwargs):
        decorators = [gen_token_usage, gen_cache]
        return self._apply_decorator(
            self._raw_gen,
            decorators=decorators,
            model=model,
            messages=messages,
            stream=stream,
            tools=tools,
            *args,
            **kwargs
        )

    @abstractmethod
    def _raw_gen_stream(self, model, messages, stream, *args, **kwargs):
        pass

    def gen_stream(self, model, messages, stream=True, tools=None, *args, **kwargs):
        decorators = [stream_cache, stream_token_usage]
        return self._apply_decorator(
            self._raw_gen_stream,
            decorators=decorators,
            model=model,
            messages=messages,
            stream=stream,
            tools=tools,
            *args,
            **kwargs
        )

    def supports_tools(self):
        return hasattr(self, "_supports_tools") and callable(
            getattr(self, "_supports_tools")
        )

    def _supports_tools(self):
        raise NotImplementedError("Subclass must implement _supports_tools method")
