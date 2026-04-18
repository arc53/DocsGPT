"""Additional tests for application/api/user/utils.py to cover paginated_response.

Target missing lines:
  - 257-262: paginated_response (collection query + serializer + response)
"""


import pytest
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app





