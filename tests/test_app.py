import pytest


@pytest.mark.unit
class TestLogContextTeardown:
    """Flask >= 3.1.2 tears a stream_with_context request down twice: once when
    the view returns, once when the generator is finalized. A ContextVar token
    may only be reset once, so the teardown hook has to be idempotent."""

    def test_reset_is_idempotent(self):
        from flask import request

        from docsgpt.app import _LOG_CTX_TOKEN_ATTR, _reset_log_context, app
        from docsgpt.core import log_context

        with app.test_request_context("/"):
            token = log_context.bind(activity_id="abc", endpoint="stream")
            setattr(request, _LOG_CTX_TOKEN_ATTR, token)

            _reset_log_context(None)
            _reset_log_context(None)  # second teardown must not raise

            assert getattr(request, _LOG_CTX_TOKEN_ATTR) is None
        assert "activity_id" not in log_context.snapshot()
