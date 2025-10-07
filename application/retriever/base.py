from abc import ABC, abstractmethod


class BaseRetriever(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def search(self, *args, **kwargs):
        pass

    @abstractmethod
    def get_params(self):
        pass
