"""DeepSeek-OCR over an API: provider presets, auth, retries and usage.

The HTTP layer is faked throughout; nothing here needs a model server.
"""
import pytest

pytest.importorskip("pypdfium2")
pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from docsgpt.parser.file.base_parser import DocumentParseError  # noqa: E402
from docsgpt.parser.file import ocr_parser as op  # noqa: E402


@pytest.fixture
def settings(monkeypatch):
    from docsgpt.core.settings import settings

    # A developer's .env may configure any of these; start every test from the defaults.
    for name, value in (
        ("OCR_DEEPSEEK_PROVIDER", "ollama"),
        ("OCR_DEEPSEEK_URL", None),
        ("OCR_DEEPSEEK_MODEL", None),
        ("OCR_DEEPSEEK_API_KEY", None),
        ("OCR_DEEPSEEK_CONCURRENCY", None),
        ("OCR_DEEPSEEK_MAX_RETRIES", 3),
        ("OCR_DEEPSEEK_TIMEOUT", 300.0),
        ("NOVITA_API_KEY", None),
    ):
        monkeypatch.setattr(settings, name, value)
    return settings


@pytest.fixture
def sleeps(monkeypatch):
    """Record backoff sleeps instead of sleeping."""
    recorded = []
    monkeypatch.setattr(op, "_sleep", recorded.append)
    return recorded


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, text=""):
        self.status_code = status
        self._body = body if body is not None else _completion("OCR TEXT")
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._body

    def raise_for_status(self):
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


def _completion(text, prompt_tokens=None, completion_tokens=None):
    body = {"choices": [{"message": {"content": text}}]}
    if prompt_tokens is not None:
        body["usage"] = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
    return body


class FakePost:
    """Stands in for ``requests.post``: replays scripted responses and records each call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers or {}, "timeout": timeout})
        item = self.responses.pop(0) if self.responses else FakeResponse()
        if isinstance(item, BaseException):
            raise item
        return item


def _image():
    return Image.new("RGB", (8, 8), "white")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSettings:
    def test_defaults(self):
        from docsgpt.core.settings import Settings

        defaults = Settings.model_construct()
        assert defaults.OCR_DEEPSEEK_PROVIDER == "ollama"
        assert defaults.OCR_DEEPSEEK_URL is None
        assert defaults.OCR_DEEPSEEK_MODEL is None
        assert defaults.OCR_DEEPSEEK_API_KEY is None
        assert defaults.OCR_DEEPSEEK_CONCURRENCY is None
        assert defaults.OCR_DEEPSEEK_MAX_RETRIES == 3

    def test_env_values_are_normalized(self, monkeypatch):
        from docsgpt.core.settings import Settings

        monkeypatch.setenv("OCR_DEEPSEEK_PROVIDER", " Novita ")
        monkeypatch.setenv("OCR_DEEPSEEK_CONCURRENCY", "")
        monkeypatch.setenv("OCR_DEEPSEEK_API_KEY", "None")
        monkeypatch.setenv("OCR_DEEPSEEK_URL", "")
        loaded = Settings()
        assert loaded.OCR_DEEPSEEK_PROVIDER == "novita"
        assert loaded.OCR_DEEPSEEK_CONCURRENCY is None
        assert loaded.OCR_DEEPSEEK_API_KEY is None
        assert loaded.OCR_DEEPSEEK_URL is None

    def test_unknown_provider_is_rejected(self, monkeypatch):
        from pydantic import ValidationError

        from docsgpt.core.settings import Settings

        monkeypatch.setenv("OCR_DEEPSEEK_PROVIDER", "openrouter")
        with pytest.raises(ValidationError):
            Settings()


# ---------------------------------------------------------------------------
# Endpoint resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveEndpoint:
    def test_ollama_default_matches_the_previous_defaults(self, settings):
        endpoint = op.resolve_deepseek_endpoint()
        assert endpoint.provider == "ollama"
        assert endpoint.url == "http://localhost:11434/v1/chat/completions"
        assert endpoint.model == "deepseek-ocr:3b"
        assert endpoint.api_key is None
        assert endpoint.concurrency == 1
        assert endpoint.hosted is False
        assert endpoint.problem is None
        assert endpoint.headers() == {}

    def test_novita_preset(self, settings):
        settings.OCR_DEEPSEEK_PROVIDER = "novita"
        settings.OCR_DEEPSEEK_API_KEY = "sk-ocr"
        endpoint = op.resolve_deepseek_endpoint()
        assert endpoint.url == "https://api.novita.ai/openai/chat/completions"
        assert endpoint.model == "deepseek/deepseek-ocr-2"
        assert endpoint.concurrency == 4
        assert endpoint.hosted is True
        assert endpoint.headers() == {"Authorization": "Bearer sk-ocr"}
        assert endpoint.problem is None

    def test_novita_falls_back_to_the_llm_key(self, settings):
        settings.OCR_DEEPSEEK_PROVIDER = "novita"
        settings.NOVITA_API_KEY = "sk-llm"
        assert op.resolve_deepseek_endpoint().api_key == "sk-llm"
        settings.OCR_DEEPSEEK_API_KEY = "sk-ocr"
        assert op.resolve_deepseek_endpoint().api_key == "sk-ocr"

    def test_deepinfra_preset_without_a_key_names_the_setting(self, settings):
        settings.OCR_DEEPSEEK_PROVIDER = "deepinfra"
        endpoint = op.resolve_deepseek_endpoint()
        assert endpoint.url == "https://api.deepinfra.com/v1/openai/chat/completions"
        assert endpoint.model == "deepseek-ai/DeepSeek-OCR"
        assert "OCR_DEEPSEEK_API_KEY" in endpoint.problem

    def test_vllm_preset(self, settings):
        settings.OCR_DEEPSEEK_PROVIDER = "vllm"
        endpoint = op.resolve_deepseek_endpoint()
        assert endpoint.url == "http://localhost:8000/v1/chat/completions"
        assert endpoint.model == "deepseek-ai/DeepSeek-OCR"
        assert endpoint.concurrency == 4
        assert endpoint.problem is None

    def test_custom_needs_url_and_model(self, settings):
        settings.OCR_DEEPSEEK_PROVIDER = "custom"
        assert "OCR_DEEPSEEK_URL" in op.resolve_deepseek_endpoint().problem
        settings.OCR_DEEPSEEK_URL = "https://ocr.example/v1/chat/completions"
        assert "OCR_DEEPSEEK_MODEL" in op.resolve_deepseek_endpoint().problem
        settings.OCR_DEEPSEEK_MODEL = "deepseek-ocr"
        endpoint = op.resolve_deepseek_endpoint()
        assert endpoint.problem is None
        assert endpoint.concurrency == 1

    def test_explicit_values_override_the_preset(self, settings):
        settings.OCR_DEEPSEEK_PROVIDER = "deepinfra"
        settings.OCR_DEEPSEEK_API_KEY = "k"
        settings.OCR_DEEPSEEK_URL = "https://proxy.example/v1/chat/completions"
        settings.OCR_DEEPSEEK_MODEL = "deepseek-ai/DeepSeek-OCR-2"
        settings.OCR_DEEPSEEK_CONCURRENCY = 9
        settings.OCR_DEEPSEEK_MAX_RETRIES = 0
        settings.OCR_DEEPSEEK_TIMEOUT = 12
        endpoint = op.resolve_deepseek_endpoint()
        assert endpoint.url == "https://proxy.example/v1/chat/completions"
        assert endpoint.model == "deepseek-ai/DeepSeek-OCR-2"
        assert endpoint.concurrency == 9
        assert endpoint.max_retries == 0
        assert endpoint.timeout == 12.0

    def test_a_local_server_with_a_key_sends_it(self, settings):
        settings.OCR_DEEPSEEK_API_KEY = "vllm-token"
        assert op.resolve_deepseek_endpoint().headers() == {"Authorization": "Bearer vllm-token"}

    def test_describe_never_prints_the_key(self, settings):
        settings.OCR_DEEPSEEK_PROVIDER = "novita"
        settings.OCR_DEEPSEEK_API_KEY = "sk-secret-value"
        text = op.resolve_deepseek_endpoint().describe()
        assert "sk-secret-value" not in text
        assert "novita" in text and "deepseek/deepseek-ocr-2" in text


# ---------------------------------------------------------------------------
# Engine: auth, errors, retries, usage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEngineRequests:
    def test_engine_reads_the_resolved_endpoint(self, settings):
        settings.OCR_DEEPSEEK_PROVIDER = "novita"
        settings.OCR_DEEPSEEK_API_KEY = "sk-ocr"
        engine = op.DeepseekOcrEngine()
        assert engine.url == "https://api.novita.ai/openai/chat/completions"
        assert engine.model == "deepseek/deepseek-ocr-2"
        assert engine.concurrency == 4

    def test_sends_the_bearer_token(self, settings, monkeypatch):
        settings.OCR_DEEPSEEK_PROVIDER = "deepinfra"
        settings.OCR_DEEPSEEK_API_KEY = "sk-ocr"
        post = FakePost(FakeResponse(body=_completion("hello")))
        monkeypatch.setattr("requests.post", post)
        assert op.DeepseekOcrEngine().ocr_image(_image()) == "hello"
        assert post.calls[0]["headers"]["Authorization"] == "Bearer sk-ocr"
        assert post.calls[0]["json"]["model"] == "deepseek-ai/DeepSeek-OCR"

    def test_no_auth_header_for_a_keyless_local_server(self, settings, monkeypatch):
        post = FakePost(FakeResponse())
        monkeypatch.setattr("requests.post", post)
        op.DeepseekOcrEngine().ocr_image(_image())
        assert "Authorization" not in post.calls[0]["headers"]

    def test_misconfiguration_fails_before_any_request(self, settings, monkeypatch):
        settings.OCR_DEEPSEEK_PROVIDER = "deepinfra"
        post = FakePost()
        monkeypatch.setattr("requests.post", post)
        with pytest.raises(op.OcrUnavailableError, match="OCR_DEEPSEEK_API_KEY"):
            op.DeepseekOcrEngine().ocr_image(_image())
        assert post.calls == []

    @pytest.mark.parametrize("status", [401, 403])
    def test_rejected_key_is_named_and_not_retried(self, settings, monkeypatch, sleeps, status):
        settings.OCR_DEEPSEEK_PROVIDER = "novita"
        settings.OCR_DEEPSEEK_API_KEY = "bad"
        post = FakePost(FakeResponse(status=status, text='{"error":"invalid api key"}'))
        monkeypatch.setattr("requests.post", post)
        with pytest.raises(op.OcrUnavailableError, match="OCR_DEEPSEEK_API_KEY"):
            op.DeepseekOcrEngine().ocr_image(_image())
        assert len(post.calls) == 1
        assert sleeps == []

    def test_unknown_model_names_the_model(self, settings, monkeypatch, sleeps):
        post = FakePost(FakeResponse(status=404, text='{"error":"model \\"deepseek-ocr:3b\\" not found"}'))
        monkeypatch.setattr("requests.post", post)
        with pytest.raises(op.OcrUnavailableError, match="deepseek-ocr:3b"):
            op.DeepseekOcrEngine().ocr_image(_image())
        assert len(post.calls) == 1

    def test_other_client_errors_include_the_body(self, settings, monkeypatch, sleeps):
        post = FakePost(FakeResponse(status=400, text="image too large"))
        monkeypatch.setattr("requests.post", post)
        with pytest.raises(DocumentParseError, match="image too large"):
            op.DeepseekOcrEngine().ocr_image(_image())
        assert len(post.calls) == 1

    def test_rate_limit_is_retried_honouring_retry_after(self, settings, monkeypatch, sleeps):
        post = FakePost(
            FakeResponse(status=429, headers={"Retry-After": "7"}),
            FakeResponse(body=_completion("after the wait")),
        )
        monkeypatch.setattr("requests.post", post)
        assert op.DeepseekOcrEngine().ocr_image(_image()) == "after the wait"
        assert len(post.calls) == 2
        assert sleeps == [7.0]

    def test_retry_after_is_capped(self, settings, monkeypatch, sleeps):
        post = FakePost(FakeResponse(status=429, headers={"Retry-After": "3600"}), FakeResponse())
        monkeypatch.setattr("requests.post", post)
        op.DeepseekOcrEngine().ocr_image(_image())
        assert sleeps == [op._MAX_RETRY_WAIT_SECONDS]

    def test_server_errors_back_off_exponentially_then_fail(self, settings, monkeypatch, sleeps):
        settings.OCR_DEEPSEEK_MAX_RETRIES = 2
        post = FakePost(*(FakeResponse(status=503, text="overloaded") for _ in range(3)))
        monkeypatch.setattr("requests.post", post)
        with pytest.raises(DocumentParseError, match="503"):
            op.DeepseekOcrEngine().ocr_image(_image())
        assert len(post.calls) == 3
        assert len(sleeps) == 2
        assert sleeps[1] > sleeps[0]

    def test_refused_connection_is_retried(self, settings, monkeypatch, sleeps):
        import requests

        post = FakePost(requests.ConnectionError("refused"), FakeResponse(body=_completion("up again")))
        monkeypatch.setattr("requests.post", post)
        assert op.DeepseekOcrEngine().ocr_image(_image()) == "up again"
        assert len(sleeps) == 1

    def test_read_timeout_is_not_retried(self, settings, monkeypatch, sleeps):
        import requests

        post = FakePost(requests.ReadTimeout("slow"))
        monkeypatch.setattr("requests.post", post)
        with pytest.raises(DocumentParseError, match="OCR_DEEPSEEK_TIMEOUT"):
            op.DeepseekOcrEngine().ocr_image(_image())
        assert len(post.calls) == 1
        assert sleeps == []

    def test_usage_is_accumulated_and_reset(self, settings, monkeypatch):
        post = FakePost(
            FakeResponse(body=_completion("a", prompt_tokens=100, completion_tokens=20)),
            FakeResponse(body=_completion("b", prompt_tokens=110, completion_tokens=30)),
            FakeResponse(body=_completion("c")),
        )
        monkeypatch.setattr("requests.post", post)
        engine = op.DeepseekOcrEngine()
        for _ in range(3):
            engine.ocr_image(_image())
        assert engine.usage() == {"requests": 3, "prompt_tokens": 210, "completion_tokens": 50}
        engine.reset_usage()
        assert engine.usage() == {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0}
