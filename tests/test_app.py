import pytest
from application.api.answer import answer
from application.api.internal.routes import internal
from application.api.user.routes import user
from application.core.settings import settings
from flask import Flask


@pytest.mark.unit
def test_app_config():
    app = Flask(__name__)
    app.register_blueprint(user)
    app.register_blueprint(answer)
    app.register_blueprint(internal)
    app.config["UPLOAD_FOLDER"] = "inputs"
    app.config["CELERY_BROKER_URL"] = settings.CELERY_BROKER_URL
    app.config["CELERY_RESULT_BACKEND"] = settings.CELERY_RESULT_BACKEND

    assert app.config["UPLOAD_FOLDER"] == "inputs"
    assert app.config["CELERY_BROKER_URL"] == settings.CELERY_BROKER_URL
    assert app.config["CELERY_RESULT_BACKEND"] == settings.CELERY_RESULT_BACKEND


@pytest.mark.unit
class TestLogContextTeardown:
    """Flask >= 3.1.2 tears a stream_with_context request down twice: once when
    the view returns, once when the generator is finalized. A ContextVar token
    may only be reset once, so the teardown hook has to be idempotent."""

    def test_reset_is_idempotent(self):
        from flask import request

        from application.app import _LOG_CTX_TOKEN_ATTR, _reset_log_context, app
        from application.core import log_context

        with app.test_request_context("/"):
            token = log_context.bind(activity_id="abc", endpoint="stream")
            setattr(request, _LOG_CTX_TOKEN_ATTR, token)

            _reset_log_context(None)
            _reset_log_context(None)  # second teardown must not raise

            assert getattr(request, _LOG_CTX_TOKEN_ATTR) is None
        assert "activity_id" not in log_context.snapshot()
