import base64
from io import BytesIO

from docsgpt.core.settings import settings
from docsgpt.tts.base import BaseTTS


class ElevenlabsTTS(BaseTTS):
    def __init__(self):
        from elevenlabs.client import ElevenLabs

        self.client = ElevenLabs(
            api_key=settings.ELEVENLABS_API_KEY,
        )

    def text_to_speech(self, text):
        lang = settings.ELEVENLABS_LANGUAGE
        audio = self.client.text_to_speech.convert(
            voice_id=settings.ELEVENLABS_VOICE_ID,
            model_id="eleven_multilingual_v2",
            text=text,
            output_format="mp3_44100_128",
        )
        audio_data = BytesIO()
        for chunk in audio:
            audio_data.write(chunk)
        audio_bytes = audio_data.getvalue()

        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        return audio_base64, lang
