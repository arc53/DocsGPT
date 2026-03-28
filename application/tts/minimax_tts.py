import base64
import json
import logging

import requests

from application.core.settings import settings
from application.tts.base import BaseTTS

logger = logging.getLogger(__name__)

MINIMAX_TTS_BASE_URL = "https://api.minimax.io"

MINIMAX_TTS_VOICES = [
    "English_Graceful_Lady",
    "English_Insightful_Speaker",
    "English_radiant_girl",
    "English_Persuasive_Man",
    "English_Lucky_Robot",
    "English_expressive_narrator",
]


class MiniMaxTTS(BaseTTS):
    def __init__(self):
        self.api_key = settings.MINIMAX_API_KEY
        self.base_url = MINIMAX_TTS_BASE_URL

    def text_to_speech(self, text):
        lang = "en"
        url = f"{self.base_url}/v1/t2a_v2"

        payload = {
            "model": "speech-2.8-hd",
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": "English_Graceful_Lady",
                "speed": 1,
                "vol": 1,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }

        response = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

        result = response.json()
        status_code = result.get("base_resp", {}).get("status_code", -1)
        if status_code != 0:
            status_msg = result.get("base_resp", {}).get("status_msg", "unknown error")
            raise RuntimeError(f"MiniMax TTS error ({status_code}): {status_msg}")

        hex_audio = result.get("data", {}).get("audio", "")
        if not hex_audio:
            raise RuntimeError("MiniMax TTS returned empty audio data")

        audio_bytes = bytes.fromhex(hex_audio)
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        return audio_base64, lang
