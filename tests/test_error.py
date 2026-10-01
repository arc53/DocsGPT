import pytest
from docsgpt.agents.context_overflow import ContextOverflowError
from docsgpt.error import (
    GENERIC_ERROR_MESSAGE,
    bad_request,
    bounded_error_text,
    response_error,
    sanitize_api_error,
    user_facing_error,
)
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@pytest.mark.unit
def test_bad_request_with_message(app):
    with app.app_context():
        message = "Invalid input"
        response = bad_request(status_code=400, message=message)
        assert response.status_code == 400
        assert response.json == {"error": "Bad Request", "message": message}


@pytest.mark.unit
def test_bad_request_without_message(app):
    with app.app_context():
        response = bad_request(status_code=400)
        assert response.status_code == 400
        assert response.json == {"error": "Bad Request"}


@pytest.mark.unit
def test_response_error_with_message(app):
    with app.app_context():
        message = "Something went wrong"
        response = response_error(code_status=500, message=message)
        assert response.status_code == 500
        assert response.json == {"error": "Internal Server Error", "message": message}


@pytest.mark.unit
def test_response_error_without_message(app):
    with app.app_context():
        response = response_error(code_status=500)
        assert response.status_code == 500
        assert response.json == {"error": "Internal Server Error"}


@pytest.mark.unit
class TestSanitizeApiError:

    def test_503_unavailable(self):
        assert "temporarily unavailable" in sanitize_api_error("503 Service Unavailable")

    def test_high_demand(self):
        assert "temporarily unavailable" in sanitize_api_error("high demand")

    def test_429_rate_limit(self):
        assert "Rate limit" in sanitize_api_error("429 Too Many Requests")

    def test_quota_exceeded(self):
        assert "Rate limit" in sanitize_api_error("Quota exceeded")

    def test_401_unauthorized(self):
        assert "Authentication" in sanitize_api_error("401 Unauthorized")

    def test_invalid_api_key(self):
        assert "Authentication" in sanitize_api_error("Invalid API key provided")

    def test_timeout(self):
        assert "timed out" in sanitize_api_error("Request timed out")

    def test_connection_error(self):
        assert "Network" in sanitize_api_error("Connection refused")

    def test_long_message_sanitized(self):
        assert "error occurred" in sanitize_api_error("x" * 201)

    def test_traceback_sanitized(self):
        assert "error occurred" in sanitize_api_error("Traceback (most recent call)")

    def test_json_sanitized(self):
        assert "error occurred" in sanitize_api_error('{"error": "something"}')

    def test_short_safe_message_passed_through(self):
        assert sanitize_api_error("Something broke") == "Something broke"


# ── Curated user-facing errors ──────────────────────────────────────────────



@pytest.mark.unit
class TestUserFacingError:
    def test_context_overflow_names_the_sizes_and_the_way_out(self):
        error = ContextOverflowError(
            "raw detail", needed_tokens=262_790, available_tokens=200_000, stage="dispatch"
        )

        public = user_facing_error(error)

        assert public.code == "context_length_exceeded"
        assert "262,790" in public.message and "200,000" in public.message
        assert "fewer or smaller files" in public.message
        assert "Add to Knowledge" in public.message
        assert "raw detail" not in public.message
        # The sizes travel on their own too, so a client can word the error
        # in the user's language.
        assert public.params == {"needed_tokens": 262_790, "available_tokens": 200_000}

    def test_an_overflow_without_sizes_has_no_params(self):
        public = user_facing_error(RuntimeError("maximum context length is 128000 tokens"))
        assert public.code == "context_length_exceeded"
        assert public.params == {}

    def test_a_provider_context_length_error_maps_without_echoing_it(self):
        error = RuntimeError(
            "Error code: 400 - maximum context length is 128000 tokens; data:application/pdf;base64,"
            + "QUJD" * 1000
        )

        public = user_facing_error(error)

        assert public.code == "context_length_exceeded"
        assert "base64" not in public.message
        assert len(public.message) < 400

    def test_anything_else_is_the_generic_message(self):
        public = user_facing_error(RuntimeError("422 Input should be a valid string " + "QUJD" * 10_000))
        assert public.code == "server_error"
        assert public.message == GENERIC_ERROR_MESSAGE

    def test_the_v1_wording_does_not_point_at_the_web_ui(self):
        error = ContextOverflowError("x", needed_tokens=300_000, available_tokens=200_000, stage="build")
        public = user_facing_error(error, surface="v1")
        assert "Add to Knowledge" not in public.message
        assert "fewer or smaller files" in public.message


@pytest.mark.unit
class TestRejectedImage:
    _OPENAI = (
        "Error code: 400 - {'error': {'message': 'You uploaded an unsupported image. Please make sure "
        "your image is valid.', 'type': 'invalid_request_error', 'param': None, 'code': 'image_parse_error'}}"
    )

    def test_a_rejected_image_names_the_images_sent(self):
        public = user_facing_error(RuntimeError(self._OPENAI), image_names=["a.png", "b.jpg"])

        assert public.code == "image_unreadable"
        assert "a.png" in public.message and "b.jpg" in public.message
        assert "Please try again later" not in public.message
        assert public.params == {"files": ["a.png", "b.jpg"]}

    def test_one_image_is_named_as_the_one(self):
        public = user_facing_error(RuntimeError(self._OPENAI), image_names=["shot.png"])
        assert "shot.png" in public.message
        assert public.params == {"files": ["shot.png"]}

    def test_without_names_it_still_says_an_image_was_rejected(self):
        error = RuntimeError("anthropic 400: Could not process image")
        error.code = None
        public = user_facing_error(error)
        assert public.code == "image_unreadable"
        assert public.params == {}

    def test_an_unrelated_error_is_not_an_image_error(self):
        assert user_facing_error(RuntimeError("500 upstream"), image_names=["a.png"]).code == "server_error"


@pytest.mark.unit
class TestBoundedErrorText:
    def test_base64_payloads_are_cut_out(self):
        text = bounded_error_text(RuntimeError("bad part: data:application/pdf;base64," + "QUJD" * 100_000))
        assert "QUJDQUJD" not in text
        assert text.startswith("RuntimeError: bad part")
        assert len(text) <= 2_000

    def test_long_text_is_capped(self):
        assert len(bounded_error_text(ValueError("x " * 10_000))) <= 2_000
