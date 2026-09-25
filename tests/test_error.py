import pytest
from docsgpt.error import bad_request, response_error, sanitize_api_error
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


class TestUserFacingError:
    def test_context_window_errors_are_curated(self):
        from docsgpt.error import user_facing_error

        for raw in (
            "Error code: 400 - {'error': {'code': 'context_length_exceeded'}}",
            "Your input exceeds the context window of this model",
            "prompt is too long: 300000 tokens > 200000 maximum",
            "Conversation context (300,000 tokens) exceeds the model's context window",
        ):
            curated = user_facing_error(RuntimeError(raw))
            assert curated is not None
            code, message = curated
            assert code == "context_window_exceeded"
            assert "attachments" in message

    def test_token_rate_limit_is_curated(self):
        from docsgpt.error import user_facing_error

        code, message = user_facing_error(
            RuntimeError("Error code: 429 - Rate limit reached: tokens_per_minute")
        )
        assert code == "rate_limited"
        assert "try again" in message.lower()

    def test_other_errors_are_not_classified(self):
        from docsgpt.error import user_facing_error

        assert user_facing_error(RuntimeError("something odd")) is None
