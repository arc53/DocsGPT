"""Which header carries the API key, checked on the wire with the real SDK.

anthropic 2.x sends the key as ``Authorization: Bearer``. The Claude API
accepts that; a gateway configured as a model's ``base_url`` may only read
``X-Api-Key``, the header 1.x used, so a custom endpoint keeps it.
"""

import httpx2
import pytest


def _sent_headers(llm):
    """Headers of one request the client sends, captured by a mock transport."""
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx2.Response(200, json={"data": [], "has_more": False, "first_id": None, "last_id": None})

    llm.anthropic._client._transport = httpx2.MockTransport(handler)
    llm.anthropic.models.list()
    return seen


@pytest.mark.unit
class TestApiKeyHeader:

    def test_anthropic_endpoint_gets_bearer(self):
        from docsgpt.llm.anthropic import AnthropicLLM

        headers = _sent_headers(AnthropicLLM(api_key="sk-test"))
        assert headers.get("authorization") == "Bearer sk-test"
        assert "x-api-key" not in headers

    def test_custom_endpoint_gets_x_api_key(self):
        from docsgpt.llm.anthropic import AnthropicLLM

        headers = _sent_headers(AnthropicLLM(api_key="sk-test", base_url="https://gateway.example.com"))
        assert headers.get("x-api-key") == "sk-test"
        assert "authorization" not in headers
