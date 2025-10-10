import pytest
from application.error import bad_request, response_error
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
