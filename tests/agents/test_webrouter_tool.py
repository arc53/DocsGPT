"""Tests for docsgpt/agents/tools/webrouter.py"""

from unittest.mock import MagicMock, patch

import pytest
from web_router import (
    ExtractedDocument,
    ExtractFailure,
    ExtractResponse,
    ProviderError,
    SearchResponse,
    SearchResult,
)

from docsgpt.agents.tools.webrouter import WebRouterTool


def _router(search=None, extract=None):
    """A stand-in WebRouter used as a context manager."""
    router = MagicMock()
    router.__enter__.return_value = router
    router.search.return_value = search
    router.extract.return_value = extract
    return router


@pytest.fixture
def tool():
    return WebRouterTool(config={})


@pytest.mark.unit
class TestWebRouterExecuteAction:
    def test_unknown_action_raises(self, tool):
        with pytest.raises(ValueError, match="Unknown action"):
            tool.execute_action("invalid")


@pytest.mark.unit
class TestWebRouterWebSearch:
    def test_search_success(self, tool):
        response = SearchResponse(
            provider="tavily",
            query="python",
            results=[
                SearchResult(
                    url="https://python.org",
                    title="Python",
                    description="The official site",
                    content="Full page body",
                    published_date="2026-01-01",
                )
            ],
        )
        router = _router(search=response)
        with patch.object(WebRouterTool, "_router", return_value=router):
            result = tool.execute_action("webrouter_web_search", query="python")

        assert result["status_code"] == 200
        assert result["provider"] == "tavily"
        assert result["results"] == [
            {
                "title": "Python",
                "url": "https://python.org",
                "snippet": "The official site",
                "published_date": "2026-01-01",
            }
        ]
        router.__exit__.assert_called_once()

    def test_search_options_forwarded_and_clamped(self, tool):
        router = _router(search=SearchResponse(provider="exa", query="q"))
        with patch.object(WebRouterTool, "_router", return_value=router):
            tool.execute_action(
                "webrouter_web_search", query=" q ", max_results=100, include_domains=["python.org", " ", 3]
            )

        args, kwargs = router.search.call_args
        assert args == ("q",)
        assert kwargs["max_results"] == 20
        assert kwargs["include_domains"] == ["python.org"]
        assert kwargs["provider"] is None
        assert kwargs["data_apis"] is False

    def test_search_max_results_floor_and_bad_value(self, tool):
        router = _router(search=SearchResponse(provider="exa", query="q"))
        with patch.object(WebRouterTool, "_router", return_value=router):
            tool.execute_action("webrouter_web_search", query="q", max_results=0)
            assert router.search.call_args[1]["max_results"] == 1
            tool.execute_action("webrouter_web_search", query="q", max_results="many")
            assert router.search.call_args[1]["max_results"] == 5

    def test_snippet_falls_back_to_content_and_is_capped(self, tool):
        response = SearchResponse(
            provider="exa", query="q", results=[SearchResult(url="https://a.com", content="x" * 900)]
        )
        with patch.object(WebRouterTool, "_router", return_value=_router(search=response)):
            result = tool.execute_action("webrouter_web_search", query="q")

        assert result["results"][0]["snippet"] == "x" * 500

    def test_empty_query_makes_no_call(self, tool):
        with patch.object(WebRouterTool, "_router") as factory:
            result = tool.execute_action("webrouter_web_search", query="  ")

        assert result["status_code"] == 400
        factory.assert_not_called()

    def test_search_error_returns_500(self, tool):
        router = _router()
        router.search.side_effect = ProviderError("tavily", "every provider failed")
        with patch.object(WebRouterTool, "_router", return_value=router):
            result = tool.execute_action("webrouter_web_search", query="q")

        assert result["status_code"] == 500
        assert result["results"] == []
        assert "failed" in result["message"].lower()


@pytest.mark.unit
class TestWebRouterReadPages:
    def test_read_success_with_partial_failure(self, tool):
        response = ExtractResponse(
            provider="jina",
            documents=[ExtractedDocument(url="https://a.com", title="A", content="# A\nbody")],
            failures=[ExtractFailure(url="https://b.com", error="HTTP 404")],
        )
        router = _router(extract=response)
        with patch.object(WebRouterTool, "_router", return_value=router):
            result = tool.execute_action("webrouter_read_pages", urls=["https://a.com", "https://b.com"])

        assert result["status_code"] == 200
        assert result["provider"] == "jina"
        assert result["results"] == [{"url": "https://a.com", "title": "A", "content": "# A\nbody", "truncated": False}]
        assert result["failures"] == [{"url": "https://b.com", "error": "HTTP 404"}]
        assert router.extract.call_args[0][0] == ["https://a.com", "https://b.com"]
        router.__exit__.assert_called_once()

    def test_single_url_string_accepted(self, tool):
        response = ExtractResponse(provider="jina", documents=[ExtractedDocument(url="https://a.com")])
        router = _router(extract=response)
        with patch.object(WebRouterTool, "_router", return_value=router):
            tool.execute_action("webrouter_read_pages", urls="https://a.com")

        assert router.extract.call_args[0][0] == ["https://a.com"]

    def test_content_truncated_to_max_chars(self, tool):
        response = ExtractResponse(
            provider="jina", documents=[ExtractedDocument(url="https://a.com", content="abcdef")]
        )
        with patch.object(WebRouterTool, "_router", return_value=_router(extract=response)):
            result = tool.execute_action("webrouter_read_pages", urls=["https://a.com"], max_chars=3)

        assert result["results"][0]["content"] == "abc"
        assert result["results"][0]["truncated"] is True

    def test_non_http_urls_refused_and_not_sent(self, tool):
        response = ExtractResponse(provider="jina", documents=[ExtractedDocument(url="https://a.com")])
        router = _router(extract=response)
        with patch.object(WebRouterTool, "_router", return_value=router):
            result = tool.execute_action(
                "webrouter_read_pages", urls=["file:///etc/passwd", "https://a.com", "ftp://x.org/f"]
            )

        assert router.extract.call_args[0][0] == ["https://a.com"]
        assert [f["url"] for f in result["failures"]] == ["file:///etc/passwd", "ftp://x.org/f"]

    def test_only_non_http_urls_makes_no_call(self, tool):
        with patch.object(WebRouterTool, "_router") as factory:
            result = tool.execute_action("webrouter_read_pages", urls=["javascript:alert(1)"])

        assert result["status_code"] == 400
        factory.assert_not_called()

    def test_too_many_urls_makes_no_call(self, tool):
        urls = [f"https://site{i}.com" for i in range(6)]
        with patch.object(WebRouterTool, "_router") as factory:
            result = tool.execute_action("webrouter_read_pages", urls=urls)

        assert result["status_code"] == 400
        factory.assert_not_called()

    def test_read_error_returns_500_with_every_url_failed(self, tool):
        router = _router()
        router.extract.side_effect = ProviderError("jina", "nothing came back")
        with patch.object(WebRouterTool, "_router", return_value=router):
            result = tool.execute_action("webrouter_read_pages", urls=["https://a.com"])

        assert result["status_code"] == 500
        assert [f["url"] for f in result["failures"]] == ["https://a.com"]


@pytest.mark.unit
class TestWebRouterConfig:
    def test_provider_and_key_passed_as_provider_config(self):
        tool = WebRouterTool(config={"provider": " Tavily ", "token": "tvly-test"})
        with patch("web_router.WebRouter") as router_cls:
            tool._router()

        router_cls.assert_called_once_with(provider_config={"tavily": {"api_key": "tvly-test"}})

    def test_no_key_uses_environment_and_keyless_tiers(self, tool):
        with patch("web_router.WebRouter") as router_cls:
            tool._router()

        router_cls.assert_called_once_with(provider_config=None)

    def test_provider_sent_with_each_call(self):
        tool = WebRouterTool(config={"provider": "exa"})
        router = _router(search=SearchResponse(provider="exa", query="q"))
        with patch.object(WebRouterTool, "_router", return_value=router):
            tool.execute_action("webrouter_web_search", query="q")

        assert router.search.call_args[1]["provider"] == "exa"

    def test_key_without_provider_refused(self):
        tool = WebRouterTool(config={"token": "secret"})
        with patch.object(WebRouterTool, "_router") as factory:
            search = tool.execute_action("webrouter_web_search", query="q")
            read = tool.execute_action("webrouter_read_pages", urls=["https://a.com"])

        assert search["status_code"] == read["status_code"] == 400
        assert "provider" in search["message"]
        factory.assert_not_called()

    def test_config_requirements_are_optional(self, tool):
        reqs = tool.get_config_requirements()
        assert set(reqs) == {"provider", "token"}
        assert not any(spec["required"] for spec in reqs.values())
        assert reqs["token"]["secret"] is True

    def test_real_router_methods_accept_the_options_sent(self):
        """The installed webrouter's search and extract take every keyword this tool passes."""
        import inspect

        from web_router import WebRouter

        search = inspect.signature(WebRouter.search).parameters
        extract = inspect.signature(WebRouter.extract).parameters
        assert {"provider", "max_results", "include_domains", "timeout", "data_apis"} <= set(search)
        assert {"provider", "timeout", "data_apis"} <= set(extract)
