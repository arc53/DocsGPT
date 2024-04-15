from abc import ABC, abstractmethod


class BaseLLM(ABC):
    def __init__(self):
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}

    @abstractmethod
    def gen(self, *args, **kwargs):
        pass

    @abstractmethod
    def gen_stream(self, *args, **kwargs):
        pass
