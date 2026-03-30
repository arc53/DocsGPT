"""Tests for application/stt/faster_whisper_stt.py"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from application.stt.faster_whisper_stt import FasterWhisperSTT


@pytest.mark.unit
class TestFasterWhisperSTTInit:

    def test_init_defaults(self):
        stt = FasterWhisperSTT()
        assert stt.model_size == "base"
        assert stt.device == "auto"
        assert stt.compute_type == "int8"
        assert stt._model is None

    def test_init_custom_params(self):
        stt = FasterWhisperSTT(
            model_size="large-v2",
            device="cuda",
            compute_type="float16",
        )
        assert stt.model_size == "large-v2"
        assert stt.device == "cuda"
        assert stt.compute_type == "float16"


@pytest.mark.unit
class TestFasterWhisperSTTGetModel:

    def test_get_model_lazy_init(self):
        stt = FasterWhisperSTT()

        mock_whisper_model = MagicMock()
        mock_module = MagicMock()
        mock_module.WhisperModel.return_value = mock_whisper_model

        with patch.dict("sys.modules", {"faster_whisper": mock_module}):
            model = stt._get_model()

        assert model is mock_whisper_model
        mock_module.WhisperModel.assert_called_once_with(
            "base",
            device="auto",
            compute_type="int8",
        )

    def test_get_model_caches(self):
        stt = FasterWhisperSTT()

        mock_whisper_model = MagicMock()
        mock_module = MagicMock()
        mock_module.WhisperModel.return_value = mock_whisper_model

        with patch.dict("sys.modules", {"faster_whisper": mock_module}):
            model1 = stt._get_model()
            model2 = stt._get_model()

        assert model1 is model2
        assert mock_module.WhisperModel.call_count == 1

    def test_get_model_raises_import_error(self):
        stt = FasterWhisperSTT()

        with patch.dict("sys.modules", {"faster_whisper": None}):
            with pytest.raises(ImportError, match="faster-whisper is required"):
                stt._get_model()


@pytest.mark.unit
class TestFasterWhisperSTTTranscribe:

    def _make_stt_with_mock_model(self):
        stt = FasterWhisperSTT()
        mock_model = MagicMock()
        stt._model = mock_model
        return stt, mock_model

    def test_transcribe_basic(self):
        stt, mock_model = self._make_stt_with_mock_model()

        seg1 = MagicMock()
        seg1.text = " Hello world "
        seg1.start = 0.0
        seg1.end = 1.5

        seg2 = MagicMock()
        seg2.text = " How are you "
        seg2.start = 1.5
        seg2.end = 3.0

        info = MagicMock()
        info.language = "en"
        info.duration = 3.0

        mock_model.transcribe.return_value = (iter([seg1, seg2]), info)

        result = stt.transcribe(Path("/tmp/audio.wav"))

        assert result["text"] == "Hello world How are you"
        assert result["language"] == "en"
        assert result["duration_s"] == 3.0
        assert result["segments"] == []  # timestamps=False by default
        assert result["provider"] == "faster_whisper"

        mock_model.transcribe.assert_called_once_with(
            "/tmp/audio.wav",
            language=None,
            word_timestamps=False,
        )

    def test_transcribe_with_language(self):
        stt, mock_model = self._make_stt_with_mock_model()

        info = MagicMock()
        info.language = "fr"
        info.duration = 1.0

        mock_model.transcribe.return_value = (iter([]), info)

        result = stt.transcribe(Path("/tmp/audio.wav"), language="fr")

        mock_model.transcribe.assert_called_once_with(
            "/tmp/audio.wav",
            language="fr",
            word_timestamps=False,
        )
        assert result["language"] == "fr"

    def test_transcribe_with_timestamps(self):
        stt, mock_model = self._make_stt_with_mock_model()

        seg = MagicMock()
        seg.text = " Hello "
        seg.start = 0.0
        seg.end = 1.0

        info = MagicMock()
        info.language = "en"
        info.duration = 1.0

        mock_model.transcribe.return_value = (iter([seg]), info)

        result = stt.transcribe(Path("/tmp/audio.wav"), timestamps=True)

        assert len(result["segments"]) == 1
        assert result["segments"][0]["start"] == 0.0
        assert result["segments"][0]["end"] == 1.0
        assert result["segments"][0]["text"] == "Hello"

        mock_model.transcribe.assert_called_once_with(
            "/tmp/audio.wav",
            language=None,
            word_timestamps=True,
        )

    def test_transcribe_empty_segments(self):
        stt, mock_model = self._make_stt_with_mock_model()

        info = MagicMock()
        info.language = "en"
        info.duration = 0.0

        mock_model.transcribe.return_value = (iter([]), info)

        result = stt.transcribe(Path("/tmp/audio.wav"))

        assert result["text"] == ""
        assert result["segments"] == []

    def test_transcribe_segment_with_empty_text(self):
        stt, mock_model = self._make_stt_with_mock_model()

        seg = MagicMock()
        seg.text = "   "
        seg.start = 0.0
        seg.end = 0.5

        info = MagicMock()
        info.language = "en"
        info.duration = 0.5

        mock_model.transcribe.return_value = (iter([seg]), info)

        result = stt.transcribe(Path("/tmp/audio.wav"))

        # Empty text stripped should not be included in text_parts
        assert result["text"] == ""

    def test_transcribe_diarize_is_ignored(self):
        stt, mock_model = self._make_stt_with_mock_model()

        info = MagicMock()
        info.language = "en"
        info.duration = 1.0

        mock_model.transcribe.return_value = (iter([]), info)

        # diarize param should be accepted but ignored
        result = stt.transcribe(
            Path("/tmp/audio.wav"),
            diarize=True,
        )

        assert result["provider"] == "faster_whisper"

    def test_transcribe_missing_attrs_use_none(self):
        stt, mock_model = self._make_stt_with_mock_model()

        seg = MagicMock(spec=[])  # No attributes
        seg.text = ""  # Override to avoid AttributeError on text

        # Create a segment that uses getattr fallbacks
        class MinimalSegment:
            pass

        minimal = MinimalSegment()

        info_cls = type("Info", (), {})()

        mock_model.transcribe.return_value = (iter([minimal]), info_cls)

        result = stt.transcribe(Path("/tmp/audio.wav"), timestamps=True)

        assert result["language"] is None
        assert result["duration_s"] is None
        # Segment should have None for start/end
        assert len(result["segments"]) == 1
        assert result["segments"][0]["start"] is None
        assert result["segments"][0]["end"] is None
