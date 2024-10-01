from flask import Flask

from application.api.answer.routes import answer
from application.api.internal.routes import internal
from application.api.user.routes import user
from application.core.settings import settings



def test_app_config():
    app = Flask(__name__)
    app.register_blueprint(user)
    app.register_blueprint(answer)
    app.register_blueprint(internal)
    app.config["UPLOAD_FOLDER"] = "inputs"
    app.config["CELERY_BROKER_URL"] = settings.CELERY_BROKER_URL
    app.config["CELERY_RESULT_BACKEND"] = settings.CELERY_RESULT_BACKEND
    app.config["MONGO_URI"] = settings.MONGO_URI

    assert app.config["UPLOAD_FOLDER"] == "inputs"
    assert app.config["CELERY_BROKER_URL"] == settings.CELERY_BROKER_URL
    assert app.config["CELERY_RESULT_BACKEND"] == settings.CELERY_RESULT_BACKEND
    assert app.config["MONGO_URI"] == settings.MONGO_URI
