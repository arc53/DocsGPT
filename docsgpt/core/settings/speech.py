"""Text-to-speech and speech-to-text."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, field_validator

from docsgpt.core.settings._shared import SettingsGroup, normalize_choice


class SpeechSettings(SettingsGroup):
    """Voice providers and transcription options."""

    TTS_PROVIDER: Literal["google_tts", "elevenlabs", "none"] = Field(
        default="google_tts", description="Text-to-speech provider; none switches it off."
    )
    ELEVENLABS_API_KEY: Optional[str] = Field(default=None, description="ElevenLabs API key.")
    ELEVENLABS_VOICE_ID: str = Field(default="nPczCjzI2devNBz1zQrb", description="ElevenLabs voice ID.")
    ELEVENLABS_LANGUAGE: str = Field(default="en", description="Language code for ElevenLabs TTS.")
    STT_PROVIDER: Literal["openai", "faster_whisper", "none"] = Field(
        default="openai", description="Speech-to-text provider; none switches it off."
    )
    OPENAI_STT_MODEL: str = Field(default="gpt-4o-mini-transcribe", description="OpenAI transcription model.")
    STT_LANGUAGE: Optional[str] = Field(default=None, description="Language hint for transcription; unset auto-detects.")
    STT_MAX_FILE_SIZE_MB: int = Field(default=50, description="Cap on an audio file accepted for transcription.")
    STT_ENABLE_TIMESTAMPS: bool = Field(default=False, description="Return word/segment timestamps.")
    STT_ENABLE_DIARIZATION: bool = Field(default=False, description="Label speakers in the transcript.")

    @field_validator("TTS_PROVIDER", "STT_PROVIDER", mode="before")
    @classmethod
    def _normalize_speech_providers(cls, v):
        # An empty value has always meant "off"; keep that spelling working.
        v = normalize_choice(v)
        return "none" if v == "" else v
