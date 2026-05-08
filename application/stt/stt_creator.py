from application.stt.base import BaseSTT
from application.stt.faster_whisper_stt import FasterWhisperSTT
from application.stt.openai_stt import OpenAISTT


class STTCreator:
    stt_providers = {
        "openai": OpenAISTT,
        "faster_whisper": FasterWhisperSTT,
    }

    @classmethod
    def create_stt(cls, stt_type, *args, **kwargs) -> BaseSTT:
        stt_class = cls.stt_providers.get(stt_type.lower())
        if not stt_class:
            raise ValueError(f"No stt class found for type {stt_type}")
        return stt_class(*args, **kwargs)
