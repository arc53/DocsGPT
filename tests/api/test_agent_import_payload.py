"""How the agent import routes read the YAML document from a request (portability._read_import_payload)."""

from __future__ import annotations

import io
import json

import pytest
from flask import Flask

from docsgpt.api.user.agents.portability import _read_import_payload

YAML = "apiVersion: docsgpt/v1\nkind: Agent\nspec:\n  name: Bot\n"


@pytest.fixture
def app():
    return Flask(__name__)


def _read(app, **kwargs):
    with app.test_request_context("/api/import_agent", method="POST", **kwargs):
        from flask import request

        return _read_import_payload(request)


@pytest.mark.unit
class TestReadImportPayload:
    def test_raw_yaml_body(self, app):
        assert _read(app, data=YAML, content_type="application/x-yaml") == (YAML, {})

    def test_curl_data_binary_default_content_type(self, app):
        """curl --data-binary without -H sends application/x-www-form-urlencoded; the body is still the YAML."""
        assert _read(app, data=YAML, content_type="application/x-www-form-urlencoded") == (YAML, {})

    def test_multipart_file(self, app):
        data = {"file": (io.BytesIO(YAML.encode()), "bot.agent.yaml")}
        assert _read(app, data=data, content_type="multipart/form-data") == (YAML, {})

    def test_json_carries_the_resolution(self, app):
        resolution = {"sources": {"Docs": "3f0e8f0c-5a53-4f0e-9a39-0e5f4f8d2c11"}}
        body = json.dumps({"yaml": YAML, "resolution": resolution})
        assert _read(app, data=body, content_type="application/json") == (YAML, resolution)
