import pytest
from flask import Flask
from application.error import bad_request, response_error


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


def test_bad_request_with_message(app):
    with app.app_context():
        response = bad_request(status_code=400)
        assert response.status_code == 400
        assert response.json == {'error': 'Bad Request', 'message': 'An error occurred'}


def test_bad_request_without_message(app):
    with app.app_context():
        response = bad_request(status_code=400)
        assert response.status_code == 400
        assert response.json == {'error': 'Bad Request'}


def test_response_error_with_message(app):
    with app.app_context():
        response = response_error(code_status=500)
        assert response.status_code == 500
        assert response.json == {'error': 'Internal Server Error', 'message': 'An error occurred'}


def test_response_error_without_message(app):
    with app.app_context():
        response = response_error(code_status=500)
        assert response.status_code == 500
        assert response.json == {'error': 'Internal Server Error'}