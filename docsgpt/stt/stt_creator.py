from typing import Optional

from docsgpt.stt.base import BaseSTT
from docsgpt.stt.faster_whisper_stt import FasterWhisperSTT
from docsgpt.stt.openai_stt import OpenAISTT

#: STT_PROVIDER value that switches speech-to-text off.
DISABLED = "none"


class STTCreator:
    stt_providers = {
        "openai": OpenAISTT,
        "faster_whisper": FasterWhisperSTT,
    }

    @staticmethod
    def is_enabled(stt_type: Optional[str]) -> bool:
        """False when the provider is ``none`` or empty: speech-to-text is switched off."""
        return (stt_type or "").strip().lower() not in ("", DISABLED)

    @classmethod
    def create_stt(cls, stt_type, *args, **kwargs) -> BaseSTT:
        stt_class = cls.stt_providers.get(stt_type.lower())
        if not stt_class:
            raise ValueError(f"No stt class found for type {stt_type}")
        return stt_class(*args, **kwargs)
