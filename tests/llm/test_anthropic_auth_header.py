"""Which header carries the API key, checked on the wire with the real SDK.

anthropic 2.x sends the key as ``Authorization: Bearer``. The Claude API
accepts that; a gateway configured as a model's ``base_url`` may only read
``X-Api-Key``, the header 1.x used, so a custom endpoint keeps it.
"""

import httpx2
import pytest

_EMPTY_PAGE = {"data": [], "has_more": False, "first_id": None, "last_id": None}


def _send(llm, handler):
    """Route the client's requests to ``handler``, proxy mounts included, and list models once."""
    transport = httpx2.MockTransport(handler)
    client = llm.anthropic._client
    client._transport = transport
    client._mounts = {pattern: transport for pattern in client._mounts}
    llm.anthropic.models.list()


def _sent_headers(llm):
    """Headers of one request the client sends."""
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx2.Response(200, json=_EMPTY_PAGE)

    _send(llm, handler)
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

    def test_custom_endpoint_does_not_follow_a_redirect(self):
        # httpx drops Authorization on a cross-origin redirect but not
        # X-Api-Key, so following one would send the key off its endpoint.
        from anthropic import APIStatusError

        from docsgpt.llm.anthropic import AnthropicLLM

        hosts = []

        def handler(request):
            hosts.append(request.url.host)
            if request.url.host == "gateway.example.com":
                return httpx2.Response(307, headers={"Location": "https://elsewhere.example.net/v1/models"})
            return httpx2.Response(200, json=_EMPTY_PAGE)

        llm = AnthropicLLM(api_key="sk-test", base_url="https://gateway.example.com")
        llm.anthropic = llm.anthropic.with_options(max_retries=0)
        with pytest.raises(APIStatusError):
            _send(llm, handler)
        assert hosts == ["gateway.example.com"]
