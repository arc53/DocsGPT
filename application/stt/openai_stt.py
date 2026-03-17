from pathlib import Path
from typing import Any, Dict, Optional

from openai import OpenAI

from application.core.settings import settings
from application.stt.base import BaseSTT


class OpenAISTT(BaseSTT):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY or settings.API_KEY
        self.base_url = base_url or settings.OPENAI_BASE_URL or "https://api.openai.com/v1"
        self.model = model or settings.OPENAI_STT_MODEL
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def transcribe(
        self,
        file_path: Path,
        language: Optional[str] = None,
        timestamps: bool = False,
        diarize: bool = False,
    ) -> Dict[str, Any]:
        _ = diarize
        request: Dict[str, Any] = {
            "file": file_path,
            "model": self.model,
            "response_format": "verbose_json",
        }
        if language:
            request["language"] = language
        if timestamps:
            request["timestamp_granularities"] = ["segment"]

        with open(file_path, "rb") as audio_file:
            request["file"] = audio_file
            response = self.client.audio.transcriptions.create(**request)
        response_dict = self._to_dict(response)
        segments = response_dict.get("segments") or []

        return {
            "text": response_dict.get("text", ""),
            "language": response_dict.get("language") or language,
            "duration_s": response_dict.get("duration"),
            "segments": [self._to_dict(segment) for segment in segments],
            "provider": "openai",
        }

    @staticmethod
    def _to_dict(value: Any) -> Dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, dict):
            return value
        return {}
