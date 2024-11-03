import io
import base64
from gtts import gTTS
from application.tts.base import BaseTTS


class GoogleTTS(BaseTTS):
    def __init__(self):
        pass


    def text_to_speech(self, text):
        lang = "en"
        audio_fp = io.BytesIO()
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0)
        audio_base64 = base64.b64encode(audio_fp.read()).decode("utf-8")
        return audio_base64, lang
