from typing import Optional

from docsgpt.tts.google_tts import GoogleTTS
from docsgpt.tts.elevenlabs import ElevenlabsTTS
from docsgpt.tts.base import BaseTTS

#: TTS_PROVIDER value that switches text-to-speech off.
DISABLED = "none"


class TTSCreator:
    tts_providers = {
        "google_tts": GoogleTTS,
        "elevenlabs": ElevenlabsTTS,
    }

    @staticmethod
    def is_enabled(tts_type: Optional[str]) -> bool:
        """False when the provider is ``none`` or empty: text-to-speech is switched off."""
        return (tts_type or "").strip().lower() not in ("", DISABLED)

    @classmethod
    def create_tts(cls, tts_type, *args, **kwargs)-> BaseTTS:
        tts_class = cls.tts_providers.get(tts_type.lower())
        if not tts_class:
            raise ValueError(f"No tts class found for type {tts_type}")
        return tts_class(*args, **kwargs)
