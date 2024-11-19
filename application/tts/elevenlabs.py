from io import BytesIO
import base64
from application.tts.base import BaseTTS


class ElevenlabsTTS(BaseTTS):
    def __init__(self):
        from elevenlabs.client import ElevenLabs

        self.client = ElevenLabs(
            api_key="ELEVENLABS_API_KEY",
            )
    

    def text_to_speech(self, text):
        lang = "en"
        audio = self.client.generate(
            text=text,
            model="eleven_multilingual_v2",
            voice="Brian",
        )
        audio_data = BytesIO()
        for chunk in audio:
            audio_data.write(chunk)
        audio_bytes = audio_data.getvalue()

        # Encode to base64
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        return audio_base64, lang
