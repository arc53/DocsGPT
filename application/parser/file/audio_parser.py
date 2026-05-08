from pathlib import Path
from typing import Dict, Union

from application.core.settings import settings
from application.parser.file.base_parser import BaseParser
from application.stt.stt_creator import STTCreator
from application.stt.upload_limits import enforce_audio_file_size_limit


class AudioParser(BaseParser):
    def __init__(self, parser_config=None):
        super().__init__(parser_config=parser_config)
        self._transcript_metadata: Dict[str, Dict] = {}

    def _init_parser(self) -> Dict:
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, list[str]]:
        _ = errors
        try:
            enforce_audio_file_size_limit(file.stat().st_size)
        except OSError:
            pass
        stt = STTCreator.create_stt(settings.STT_PROVIDER)
        result = stt.transcribe(
            file,
            language=settings.STT_LANGUAGE,
            timestamps=settings.STT_ENABLE_TIMESTAMPS,
            diarize=settings.STT_ENABLE_DIARIZATION,
        )

        transcript_metadata = {
            "transcript_duration_s": result.get("duration_s"),
            "transcript_language": result.get("language"),
            "transcript_provider": result.get("provider"),
        }
        if result.get("segments"):
            transcript_metadata["transcript_segments"] = result["segments"]

        self._transcript_metadata[str(file)] = {
            key: value
            for key, value in transcript_metadata.items()
            if value not in (None, [], {})
        }
        return result.get("text", "")

    def get_file_metadata(self, file: Path) -> Dict:
        return self._transcript_metadata.get(str(file), {})
