import asyncio
import websockets
import json
import base64
from io import BytesIO
from base import BaseTTS


class ElevenlabsTTS(BaseTTS):
    def __init__(self):        
        self.api_key = 'sk_19b72c883e8bdfcec2705be2d048f3830a40d2faa4b76b26'
        self.model = "eleven_multilingual_v2"
        self.voice = "Brian"

    def text_to_speech(self, text):
        audio_bytes = asyncio.run(self._text_to_speech_websocket(text))
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        lang = "en"
        return audio_base64, lang

    async def _text_to_speech_websocket(self, text):
        uri = f"wss://api.elevenlabs.io/v1/text-to-speech/{self.voice}/stream-input?model_id={self.model}"

        payload = {
            "text": text,
            "model_id": self.model,
            "voice_settings": {
                "voice_id": self.voice
            },
            "xi-api-key": self.api_key,
            "Accept": "audio/mpeg"
        }
        audio_data = BytesIO()

        async with websockets.connect(uri) as websocket:
            
            await websocket.send(json.dumps(payload))
            
            async for message in websocket:
                if isinstance(message, bytes):
                    audio_data.write(message)
                else:
                    print("Received a non-binary frame:", message)

        return audio_data.getvalue()


def test_elevenlabs_websocket():
    """
    Tests the ElevenlabsTTS text_to_speech method with a sample prompt.
    Prints out the base64-encoded result and writes it to 'output_audio.mp3'.
    """
    # Instantiate your TTS class
    tts = ElevenlabsTTS()

    # Call the method with some sample text
    audio_base64, lang = tts.text_to_speech("Hello from ElevenLabs WebSocket!")

    print(f"Received language: {lang}")
    print(f"Base64 Audio (truncated): {audio_base64[:100]}...")

    # Optional: Save the audio to a local file for manual listening.
    # We'll assume the audio is in MP3 format based on "Accept": "audio/mpeg".
    audio_bytes = base64.b64decode(audio_base64)
    with open("output_audio.mp3", "wb") as f:
        f.write(audio_bytes)

    print("Saved audio to output_audio.mp3.")


if __name__ == "__main__":
    test_elevenlabs_websocket()
