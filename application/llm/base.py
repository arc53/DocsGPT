from abc import ABC, abstractmethod
from application.usage import gen_token_usage, stream_token_usage
from application.cache import stream_cache, gen_cache


class BaseLLM(ABC):
    def __init__(self):
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

    def _apply_decorator(self, method, decorators, *args, **kwargs):
        for decorator in decorators:
            method = decorator(method)
        return method(self, *args, **kwargs)

    @abstractmethod
    def _raw_gen(self, model, messages, stream, *args, **kwargs):
        pass

    def gen(self, model, messages, stream=False, *args, **kwargs):
        decorators = [gen_token_usage, gen_cache]
        return self._apply_decorator(self._raw_gen, decorators=decorators, model=model, messages=messages, stream=stream, *args, **kwargs)

    @abstractmethod
    def _raw_gen_stream(self, model, messages, stream, *args, **kwargs):
        pass

    def gen_stream(self, model, messages, stream=True, *args, **kwargs):
        decorators = [stream_cache, stream_token_usage]
        return self._apply_decorator(self._raw_gen_stream, decorators=decorators, model=model, messages=messages, stream=stream, *args, **kwargs)