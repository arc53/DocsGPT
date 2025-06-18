import asyncio
import websockets
import json
import base64
from io import BytesIO
from application.tts.base import BaseTTS


class ElevenlabsTTS(BaseTTS):
    def __init__(self):        
        self.api_key = 'ELEVENLABS_API_KEY'# here you should put your api key
        self.model = "eleven_flash_v2_5"
        self.voice = "VOICE_ID" # this is the hash code for the voice not the name!
        self.write_audio = 1

    def text_to_speech(self, text):
        asyncio.run(self._text_to_speech_websocket(text))

    async def _text_to_speech_websocket(self, text):
        uri = f"wss://api.elevenlabs.io/v1/text-to-speech/{self.voice}/stream-input?model_id={self.model}"
        websocket = await websockets.connect(uri)
        payload = {
            "text": " ",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8,
            },
            "xi_api_key": self.api_key,
        }

        await websocket.send(json.dumps(payload))
        
        async def listen():
            while 1:
                try:
                    msg = await websocket.recv()
                    data = json.loads(msg)

                    if data.get("audio"):
                        print("audio received")
                        yield base64.b64decode(data["audio"])
                    elif data.get("isFinal"):
                        break
                except websockets.exceptions.ConnectionClosed:
                    print("websocket closed")
                    break
        listen_task =  asyncio.create_task(self.stream(listen()))
        
        await websocket.send(json.dumps({"text": text}))
        # this is to signal the end of the text, either use this or flush
        await websocket.send(json.dumps({"text": ""})) 

        await listen_task
    
    async def stream(self, audio_stream):
        if self.write_audio:
            audio_bytes = BytesIO()
            async for chunk in audio_stream:
                if chunk:
                    audio_bytes.write(chunk)
            with open("output_audio.mp3", "wb") as f:
                f.write(audio_bytes.getvalue())
        
        else:
            async for chunk in audio_stream:
                pass # depends on the streamer!


def test_elevenlabs_websocket():
    """
    Tests the ElevenlabsTTS text_to_speech method with a sample prompt.
    Prints out the base64-encoded result and writes it to 'output_audio.mp3'.
    """
    # Instantiate your TTS class
    tts = ElevenlabsTTS()

    # Call the method with some sample text
    tts.text_to_speech("Hello from ElevenLabs WebSocket!")

    print("Saved audio to output_audio.mp3.")


if __name__ == "__main__":
    test_elevenlabs_websocket()
