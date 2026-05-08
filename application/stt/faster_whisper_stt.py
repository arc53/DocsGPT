from pathlib import Path
from typing import Dict, Optional

from application.stt.base import BaseSTT


class FasterWhisperSTT(BaseSTT):
    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "int8",
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise ImportError(
                    "faster-whisper is required to use the faster_whisper STT provider."
                ) from exc

            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def transcribe(
        self,
        file_path: Path,
        language: Optional[str] = None,
        timestamps: bool = False,
        diarize: bool = False,
    ) -> Dict[str, object]:
        _ = diarize
        model = self._get_model()
        segments_iter, info = model.transcribe(
            str(file_path),
            language=language,
            word_timestamps=timestamps,
        )

        segments = []
        text_parts = []
        for segment in segments_iter:
            segment_text = getattr(segment, "text", "").strip()
            if segment_text:
                text_parts.append(segment_text)
            segments.append(
                {
                    "start": getattr(segment, "start", None),
                    "end": getattr(segment, "end", None),
                    "text": segment_text,
                }
            )

        return {
            "text": " ".join(text_parts).strip(),
            "language": getattr(info, "language", language),
            "duration_s": getattr(info, "duration", None),
            "segments": segments if timestamps else [],
            "provider": "faster_whisper",
        }
