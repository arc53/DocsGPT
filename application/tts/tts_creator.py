from application.tts.google_tts import GoogleTTS
from application.tts.elevenlabs import ElevenlabsTTS
from application.tts.base import BaseTTS



class TTSCreator:
    tts_providers = {
        "google_tts": GoogleTTS,
        "elevenlabs": ElevenlabsTTS,
    }

    @classmethod
    def create_tts(cls, tts_type, *args, **kwargs)-> BaseTTS:
        tts_class = cls.tts_providers.get(tts_type.lower())
        if not tts_class:
            raise ValueError(f"No tts class found for type {tts_type}")
        return tts_class(*args, **kwargs)