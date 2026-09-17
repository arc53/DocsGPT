"""Text-to-speech and speech-to-text."""

from __future__ import annotations

from typing import Optional

from pydantic import Field, field_validator

from docsgpt.core.settings._shared import SettingsGroup, normalize_secret


class SpeechSettings(SettingsGroup):
    """Voice providers and transcription options."""

    TTS_PROVIDER: str = Field(
        default="google_tts", description="Text-to-speech provider: google_tts, elevenlabs, or none to switch it off."
    )
    ELEVENLABS_API_KEY: Optional[str] = Field(default=None, description="ElevenLabs API key.")
    STT_PROVIDER: str = Field(
        default="openai", description="Speech-to-text provider: openai, faster_whisper, or none to switch it off."
    )
    OPENAI_STT_MODEL: str = Field(default="gpt-4o-mini-transcribe", description="OpenAI transcription model.")
    STT_LANGUAGE: Optional[str] = Field(default=None, description="Language hint for transcription; unset auto-detects.")
    STT_MAX_FILE_SIZE_MB: int = Field(default=50, description="Cap on an audio file accepted for transcription.")
    STT_ENABLE_TIMESTAMPS: bool = Field(default=False, description="Return word/segment timestamps.")
    STT_ENABLE_DIARIZATION: bool = Field(default=False, description="Label speakers in the transcript.")

    @field_validator("ELEVENLABS_API_KEY", mode="before")
    @classmethod
    def _normalize_speech_secrets(cls, v):
        return normalize_secret(v)
