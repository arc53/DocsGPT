"""Google Translate text-to-speech, the endpoint the unmaintained gTTS package wrapped."""

import base64
import json
import re
import urllib.parse
from typing import Iterator, List, Optional, Tuple

import requests

from docsgpt.tts.base import BaseTTS

TTS_URL = "https://translate.google.com/_/TranslateWebserverUi/data/batchexecute"
RPC_ID = "jQ1olc"
MAX_CHARS = 100
TIMEOUT_SECONDS = 30
HEADERS = {
    "Referer": "https://translate.google.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
}

_SENTENCE_END = re.compile(r"(?<=[.!?;:。！？])\s+|\n+")


def _split_text(text: str, limit: int = MAX_CHARS) -> List[str]:
    """Split text into chunks of at most ``limit`` chars, at sentence ends, then spaces, then hard cuts."""
    chunks: List[str] = []
    for sentence in _SENTENCE_END.split(text):
        sentence = sentence.strip()
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit + 1)
            if cut <= 0:
                cut = limit
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            chunks.append(sentence)
    return [chunk for chunk in chunks if chunk]


def _rpc_body(text: str, lang: str) -> str:
    """Form body for one batchexecute call (normal speed)."""
    parameter = json.dumps([text, lang, None, "null"], separators=(",", ":"))
    rpc = json.dumps([[[RPC_ID, parameter, None, "generic"]]], separators=(",", ":"))
    return f"f.req={urllib.parse.quote(rpc)}&"


def _audio_from_lines(lines: Iterator[bytes]) -> Optional[bytes]:
    """The mp3 bytes in a batchexecute response, or None when it carries none."""
    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if RPC_ID not in line:
            continue
        for entry in json.loads(line):
            if len(entry) > 2 and entry[1] == RPC_ID and entry[2]:
                payload = json.loads(entry[2])
                if payload and payload[0]:
                    return base64.b64decode(payload[0])
    return None


class GoogleTTS(BaseTTS):
    def __init__(self):
        pass

    def text_to_speech(self, text: str) -> Tuple[str, str]:
        """Base64 mp3 of ``text`` spoken in English, and the language code."""
        lang = "en"
        chunks = _split_text(text)
        if not chunks:
            raise ValueError("No text to speak")
        audio = bytearray()
        for chunk in chunks:
            response = requests.post(
                TTS_URL, data=_rpc_body(chunk, lang), headers=HEADERS, timeout=TIMEOUT_SECONDS
            )
            response.raise_for_status()
            part = _audio_from_lines(response.iter_lines())
            if part is None:
                raise RuntimeError("Google TTS returned no audio")
            audio.extend(part)
        return base64.b64encode(bytes(audio)).decode("utf-8"), lang
