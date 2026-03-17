from pathlib import Path

from application.core.settings import settings
from application.stt.constants import SUPPORTED_AUDIO_EXTENSIONS
from application.utils import safe_filename


STT_REQUEST_SIZE_OVERHEAD_BYTES = 1024 * 1024
STT_SIZE_LIMITED_PATHS = frozenset(("/api/stt", "/api/stt/live/chunk"))


class AudioFileTooLargeError(ValueError):
    pass


def get_stt_max_file_size_bytes() -> int:
    return max(0, settings.STT_MAX_FILE_SIZE_MB) * 1024 * 1024


def build_stt_file_size_limit_message() -> str:
    return f"Audio file exceeds {settings.STT_MAX_FILE_SIZE_MB}MB limit"


def is_audio_filename(filename: str | Path | None) -> bool:
    if not filename:
        return False
    safe_name = safe_filename(Path(str(filename)).name)
    return Path(safe_name).suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def enforce_audio_file_size_limit(size_bytes: int) -> None:
    max_size_bytes = get_stt_max_file_size_bytes()
    if max_size_bytes and size_bytes > max_size_bytes:
        raise AudioFileTooLargeError(build_stt_file_size_limit_message())


def should_reject_stt_request(path: str, content_length: int | None) -> bool:
    if path not in STT_SIZE_LIMITED_PATHS or content_length is None:
        return False
    max_request_size_bytes = (
        get_stt_max_file_size_bytes() + STT_REQUEST_SIZE_OVERHEAD_BYTES
    )
    return content_length > max_request_size_bytes
