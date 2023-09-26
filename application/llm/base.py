from abc import ABC, abstractmethod
import json


class BaseLLM(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def gen(self, *args, **kwargs):
        pass

    @abstractmethod
    def gen_stream(self, *args, **kwargs):
        pass
