"""``docsgpt ocr-check``: one real OCR request against the configured engine, reported plainly."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("PIL")
pytest.importorskip("pypdfium2")

from docsgpt import cli  # noqa: E402
from docsgpt.parser.file import ocr_parser as op  # noqa: E402
from docsgpt.scripts import ocr_check  # noqa: E402


@pytest.fixture
def settings(monkeypatch):
    from docsgpt.core.settings import settings

    for name, value in (
        ("OCR_ENGINE", "deepseek"),
        ("OCR_ENABLED", True),
        ("OCR_ATTACHMENTS_ENABLED", False),
        ("OCR_DEEPSEEK_PROVIDER", "novita"),
        ("OCR_DEEPSEEK_URL", None),
        ("OCR_DEEPSEEK_MODEL", None),
        ("OCR_DEEPSEEK_API_KEY", "sk-very-secret"),
        ("OCR_DEEPSEEK_CONCURRENCY", None),
        ("OCR_DEEPSEEK_MAX_RETRIES", 0),
        ("NOVITA_API_KEY", None),
    ):
        monkeypatch.setattr(settings, name, value)
    return settings


def _replying(text, usage=True):
    body = {"choices": [{"message": {"content": text}}]}
    if usage:
        body["usage"] = {"prompt_tokens": 280, "completion_tokens": 12}
    response = MagicMock(status_code=200, headers={})
    response.json.return_value = body
    return MagicMock(return_value=response)


@pytest.mark.unit
class TestOcrCheck:
    def test_success_reports_the_endpoint_text_and_usage(self, settings, monkeypatch, capsys):
        post = _replying(f"# {ocr_check.SAMPLE_LINES[0]}\n\n{ocr_check.SAMPLE_LINES[1]}")
        monkeypatch.setattr("requests.post", post)
        assert ocr_check.main([]) == 0
        out = capsys.readouterr().out
        assert "provider=novita" in out
        assert "deepseek/deepseek-ocr-2" in out
        assert "sk-very-secret" not in out
        assert "280 prompt" in out
        assert "OCR CHECK: PASS" in out
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer sk-very-secret"}

    def test_unreadable_answer_fails(self, settings, monkeypatch, capsys):
        monkeypatch.setattr("requests.post", _replying("I cannot see any text."))
        assert ocr_check.main([]) == 1
        assert "OCR CHECK: FAIL" in capsys.readouterr().out

    def test_misconfiguration_fails_without_a_request(self, settings, monkeypatch, capsys):
        settings.OCR_DEEPSEEK_API_KEY = None
        post = MagicMock()
        monkeypatch.setattr("requests.post", post)
        assert ocr_check.main([]) == 1
        out = capsys.readouterr().out
        assert "OCR_DEEPSEEK_API_KEY" in out
        post.assert_not_called()

    def test_rejected_key_is_reported(self, settings, monkeypatch, capsys):
        response = MagicMock(status_code=401, headers={}, text="invalid key")
        monkeypatch.setattr("requests.post", MagicMock(return_value=response))
        assert ocr_check.main([]) == 1
        assert "rejected the request (401)" in capsys.readouterr().out

    def test_engine_flag_overrides_the_setting(self, settings, monkeypatch, capsys):
        settings.OCR_ENGINE = "tesseract"
        monkeypatch.setattr("requests.post", _replying(" ".join(ocr_check.SAMPLE_LINES)))
        assert ocr_check.main(["--engine", "deepseek"]) == 0

    def test_tesseract_without_the_binary_names_the_install(self, settings, monkeypatch, capsys):
        settings.OCR_ENGINE = "tesseract"
        monkeypatch.setattr(op.TesseractEngine, "available", staticmethod(lambda: False))
        assert ocr_check.main([]) == 1
        assert "tesseract" in capsys.readouterr().out

    def test_warns_when_ocr_is_off(self, settings, monkeypatch, capsys):
        settings.OCR_ENABLED = False
        monkeypatch.setattr("requests.post", _replying(" ".join(ocr_check.SAMPLE_LINES)))
        assert ocr_check.main([]) == 0
        assert "OCR_ENABLED and OCR_ATTACHMENTS_ENABLED are both off" in capsys.readouterr().out

    def test_own_file_passes_on_any_text(self, settings, monkeypatch, capsys, tmp_path):
        from PIL import Image

        image = tmp_path / "receipt.png"
        Image.new("RGB", (64, 32), "white").save(image)
        monkeypatch.setattr("requests.post", _replying("TOTAL 12.50"))
        assert ocr_check.main(["--file", str(image)]) == 0
        assert "TOTAL 12.50" in capsys.readouterr().out

    def test_own_pdf_uses_its_first_page(self, settings, monkeypatch, tmp_path):
        from PIL import Image

        pdf = tmp_path / "scan.pdf"
        Image.new("RGB", (200, 300), "white").save(pdf, "PDF")
        monkeypatch.setattr("requests.post", _replying("page one"))
        assert ocr_check.main(["--file", str(pdf)]) == 0

    def test_sample_image_is_legible_to_tesseract(self):
        if not op.TesseractEngine.available():
            pytest.skip("tesseract binary not installed")
        text = op.TesseractEngine(languages=["eng"]).ocr_image(ocr_check.sample_image())
        assert ocr_check.sample_recognised(text)


@pytest.mark.unit
class TestCommand:
    def test_registered_as_a_docsgpt_command(self, monkeypatch):
        main = MagicMock(return_value=0)
        monkeypatch.setattr("docsgpt.scripts.ocr_check.main", main)
        assert cli.main(["ocr-check", "--engine", "deepseek"]) == 0
        main.assert_called_once_with(["--engine", "deepseek"])

    def test_listed_in_the_help(self, capsys):
        cli.build_parser().print_help()
        assert "ocr-check" in capsys.readouterr().out
