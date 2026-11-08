"""Google Translate text-to-speech, the endpoint the unmaintained gTTS package wrapped."""

import base64
import json
import re
import time
import urllib.parse
from typing import Iterator, List, Optional, Tuple

import requests

from docsgpt.tts.base import BaseTTS

TTS_URL = "https://translate.google.com/_/TranslateWebserverUi/data/batchexecute"
RPC_ID = "jQ1olc"
MAX_CHARS = 100
TIMEOUT_SECONDS = 30
#: Upper bound on one synthesis, so a slow or throttling upstream can't hold a request thread for long.
DEADLINE_SECONDS = 90
HEADERS = {
    "Referer": "https://translate.google.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
}

# A long answer is many sequential chunks; a transient 429 or 5xx (or a dropped
# connection) on one would otherwise throw away the audio already made.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRY_BACKOFF_SECONDS = (0.5, 1.0, 2.0)

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
        deadline = time.monotonic() + DEADLINE_SECONDS
        with requests.Session() as session:
            for chunk in chunks:
                audio.extend(_synthesize_chunk(session, chunk, lang, deadline))
        return base64.b64encode(bytes(audio)).decode("utf-8"), lang


def _time_left(deadline: float) -> float:
    """Seconds until ``deadline``; raises TimeoutError once it has passed."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError(f"Google TTS took longer than {DEADLINE_SECONDS}s")
    return remaining


def _synthesize_chunk(session: requests.Session, chunk: str, lang: str, deadline: float) -> bytes:
    """mp3 bytes for one chunk, retrying throttling and server errors; every attempt and wait fits the deadline."""
    for attempt in range(len(RETRY_BACKOFF_SECONDS) + 1):
        retryable = attempt < len(RETRY_BACKOFF_SECONDS)
        try:
            response = session.post(
                TTS_URL,
                data=_rpc_body(chunk, lang),
                headers=HEADERS,
                timeout=min(TIMEOUT_SECONDS, _time_left(deadline)),
            )
        except (requests.ConnectionError, requests.Timeout):
            if not retryable:
                raise
        else:
            if not (retryable and response.status_code in RETRY_STATUSES):
                response.raise_for_status()
                part = _audio_from_lines(response.iter_lines())
                if part is None:
                    raise RuntimeError("Google TTS returned no audio")
                return part
        time.sleep(min(RETRY_BACKOFF_SECONDS[attempt], _time_left(deadline)))
    raise AssertionError("unreachable")
