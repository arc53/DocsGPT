from abc import ABC, abstractmethod


class BaseTTS(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def text_to_speech(self, *args, **kwargs):
        pass