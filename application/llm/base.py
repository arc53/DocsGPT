from abc import ABC, abstractmethod
from application.usage import gen_token_usage, stream_token_usage


class BaseLLM(ABC):
    def __init__(self):
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

    def _apply_decorator(self, method, decorator, *args, **kwargs):
        return decorator(method, *args, **kwargs)

    @abstractmethod
    def _raw_gen(self, model, messages, stream, *args, **kwargs):
        pass

    def gen(self, model, messages, stream=False, *args, **kwargs):
        return self._apply_decorator(self._raw_gen, gen_token_usage)(
            self, model=model, messages=messages, stream=stream, *args, **kwargs
        )

    @abstractmethod
    def _raw_gen_stream(self, model, messages, stream, *args, **kwargs):
        pass

    def gen_stream(self, model, messages, stream=True, *args, **kwargs):
        return self._apply_decorator(self._raw_gen_stream, stream_token_usage)(
            self, model=model, messages=messages, stream=stream, *args, **kwargs
        )
