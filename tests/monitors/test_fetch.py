"""Tests for fetching and normalizing what a monitor watches."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from docsgpt.monitors import fetch
from docsgpt.monitors.fetch import SourceError, SourceUnreachable
from docsgpt.security.safe_url import UnsafeUserUrlError


def _response(status: int, headers=None):
    return SimpleNamespace(status_code=status, headers=headers or {})


class _Pages:
    """Stands in for ``pinned_fetch_bytes``: answers per URL and records the calls."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        answer = self.pages[url]
        if isinstance(answer, BaseException):
            raise answer
        body, status, headers = answer
        return body, _response(status, headers)


@pytest.fixture()
def pages(monkeypatch):
    def install(mapping):
        stub = _Pages(mapping)
        monkeypatch.setattr(fetch, "pinned_fetch_bytes", stub)
        return stub

    return install


HTML = b"<html><head><title>t</title><script>var x=1</script></head><body><div id='p'>Price: $52,140</div>" \
       b"<p>Other</p></body></html>"


class TestFetchWebpage:
    def test_html_is_reduced_to_text_and_the_cap_truncates(self, pages):
        stub = pages({"https://x.test/": (HTML, 200, {"Content-Type": "text/html"})})
        content = fetch.fetch_webpage("https://x.test/")
        assert "Price: $52,140" in content.text and "var x" not in content.text
        assert stub.calls[0][1]["truncate"] is True
        assert stub.calls[0][1]["max_bytes"] == fetch.FETCH_MAX_BYTES

    def test_css_selector_picks_the_part(self, pages):
        pages({"https://x.test/": (HTML, 200, {"Content-Type": "text/html"})})
        assert fetch.fetch_webpage("https://x.test/", "#p").text == "Price: $52,140"

    def test_empty_selection_is_an_error(self, pages):
        pages({"https://x.test/": (HTML, 200, {"Content-Type": "text/html"})})
        with pytest.raises(SourceError, match="matched nothing"):
            fetch.fetch_webpage("https://x.test/", ".missing")

    def test_json_is_parsed_with_sorted_keys(self, pages):
        pages({"https://x.test/a": (b'{"b": 1, "a": {"price": 9}}', 200, {"Content-Type": "application/json"})})
        content = fetch.fetch_webpage("https://x.test/a")
        assert content.data == {"b": 1, "a": {"price": 9}}
        assert content.text.index('"a"') < content.text.index('"b"')

    def test_redirects_are_followed_through_the_pinned_fetcher(self, pages):
        stub = pages(
            {
                "http://x.test/p": (b"", 301, {"Location": "https://x.test/p"}),
                "https://x.test/p": (b"", 302, {"Location": "/final"}),
                "https://x.test/final": (b"hello", 200, {"Content-Type": "text/plain"}),
            }
        )
        assert fetch.fetch_webpage("http://x.test/p").text == "hello"
        assert [url for url, _ in stub.calls] == ["http://x.test/p", "https://x.test/p", "https://x.test/final"]

    def test_a_redirect_to_a_private_address_is_refused(self, pages):
        pages(
            {
                "https://x.test/": (b"", 302, {"Location": "http://10.0.0.5/admin"}),
                "http://10.0.0.5/admin": UnsafeUserUrlError("private address"),
            }
        )
        with pytest.raises(SourceError, match="not allowed"):
            fetch.fetch_webpage("https://x.test/")

    def test_too_many_redirects(self, pages):
        pages({f"https://x.test/{i}": (b"", 302, {"Location": f"/{i + 1}"}) for i in range(10)})
        with pytest.raises(SourceError, match="redirects more than"):
            fetch.fetch_webpage("https://x.test/0")

    def test_redirect_to_another_scheme_is_refused(self, pages):
        pages({"https://x.test/": (b"", 302, {"Location": "file:///etc/passwd"})})
        with pytest.raises(SourceError, match="not a web page"):
            fetch.fetch_webpage("https://x.test/")

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_server_trouble_is_unreachable(self, pages, status):
        pages({"https://x.test/": (b"", status, {})})
        with pytest.raises(SourceUnreachable):
            fetch.fetch_webpage("https://x.test/")

    def test_a_404_is_an_error_not_unreachable(self, pages):
        pages({"https://x.test/": (b"", 404, {})})
        with pytest.raises(SourceError) as info:
            fetch.fetch_webpage("https://x.test/")
        assert not isinstance(info.value, SourceUnreachable)

    @pytest.mark.parametrize("exc", [requests.Timeout(), requests.ConnectionError()])
    def test_network_failures_are_unreachable(self, pages, exc):
        pages({"https://x.test/": exc})
        with pytest.raises(SourceUnreachable):
            fetch.fetch_webpage("https://x.test/")

    def test_binary_content_is_refused(self, pages):
        pages({"https://x.test/i": (b"\x89PNG\x00\x00", 200, {"Content-Type": "image/png"})})
        with pytest.raises(SourceError, match="image/png"):
            fetch.fetch_webpage("https://x.test/i")


class TestToolResults:
    def test_remote_command_ignores_duration(self):
        first = fetch.content_from_tool_result(
            "remote_device", {"exit_code": 0, "stdout": "ok\n", "stderr": "", "duration_ms": 10}
        )
        second = fetch.content_from_tool_result(
            "remote_device", {"exit_code": 0, "stdout": "ok\n", "stderr": "", "duration_ms": 99}
        )
        assert first.digest == second.digest and first.text == "ok"

    def test_remote_command_json_stdout_is_data(self):
        content = fetch.content_from_tool_result("remote_device", {"exit_code": 0, "stdout": '{"n": 3}'})
        assert content.data["stdout"] == {"n": 3}

    def test_failed_command_keeps_the_exit_code(self):
        content = fetch.content_from_tool_result("remote_device", {"exit_code": 2, "stdout": "", "stderr": "boom"})
        assert content.data["exit_code"] == 2 and "boom" in content.text

    def test_json_string_results_parse(self):
        assert fetch.content_from_tool_result("api_tool", '{"price": 88}').data == {"price": 88}

    def test_dict_and_number_results(self):
        assert fetch.content_from_tool_result("x", {"a": 1}).data == {"a": 1}
        assert fetch.content_from_tool_result("x", 5).data == 5
        assert fetch.content_from_tool_result("x", None).text == ""
