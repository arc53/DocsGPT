"""Fetching and normalizing what a monitor watches.

Webpages are fetched through the SSRF-pinned fetcher (``pinned_fetch_bytes``:
every resolved address must be public, the connection is pinned to the
validated IP, redirects are not followed), with a 30 s timeout and a byte
cap. HTML is reduced to its text (or the text of ``css_selector``), JSON is
parsed and kept as data, so a change in markup, scripts or tracking
parameters is not a change in content.

Failures are sorted into :class:`SourceUnreachable` (timeouts, connection
errors, 5xx, 429: skipped, never a change) and :class:`SourceError`
(everything else: counted toward the three-strike pause).
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import requests
from urllib.parse import urljoin

from docsgpt.agents.tools.read_webpage import _decode_body
from docsgpt.monitors.checks import Content
from docsgpt.security.safe_url import ResponseTooLargeError, UnsafeUserUrlError, pinned_fetch_bytes

#: Bytes read from a page; a longer page is cut here, never refused.
FETCH_MAX_BYTES = 1024 * 1024

#: Characters of normalized text kept (256 KiB).
TEXT_MAX_CHARS = 256 * 1024

#: Seconds a page fetch may wait on the connection or between reads.
FETCH_TIMEOUT_SECONDS = 30

#: Redirects a page fetch follows.
MAX_REDIRECTS = 3

_USER_AGENT = "DocsGPT-Monitor/1.0"

_JSON_TYPES = ("application/json", "application/ld+json")
_DROP_TAGS = ("script", "style", "noscript", "template", "svg", "iframe", "head")
_BLANK_LINES = re.compile(r"\n\s*\n+")
_SPACES = re.compile(r"[ \t\r\f\v]+")


class SourceError(Exception):
    """The source answered, but not with something the monitor can use."""


class SourceUnreachable(SourceError):
    """The source could not be reached (offline, timeout, 5xx): the check is skipped."""


class SourceRevoked(SourceError):
    """The source is gone for good (a revoked device, a removed tool): the monitor must pause."""


def _clean_text(text: str) -> str:
    lines = [_SPACES.sub(" ", line).strip() for line in text.replace("\x00", "").splitlines()]
    joined = "\n".join(lines)
    return _BLANK_LINES.sub("\n\n", joined).strip()[:TEXT_MAX_CHARS]


def html_text(html: str, css_selector: Optional[str] = None) -> str:
    """The readable text of an HTML document, or of the elements ``css_selector`` picks.

    Raises:
        SourceError: The selector matches nothing.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()
    if css_selector:
        nodes = soup.select(css_selector)
        if not nodes:
            raise SourceError(f"the selector {css_selector!r} matched nothing on the page")
        return _clean_text("\n\n".join(node.get_text("\n") for node in nodes))
    body = soup.body or soup
    return _clean_text(body.get_text("\n"))


def canonical_json(data: Any) -> str:
    """Stable text for parsed JSON: sorted keys, so key order is not a change."""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1, default=str)[:TEXT_MAX_CHARS]


def content_from_text(text: str, *, css_selector: Optional[str] = None, html: bool = False) -> Content:
    """Normalize a body: JSON becomes data, HTML its text, anything else stays text."""
    stripped = text.strip()
    if stripped[:1] in ("{", "[") and not html:
        try:
            data = json.loads(stripped)
        except ValueError:
            data = None
        if data is not None:
            return Content(text=canonical_json(data), data=data)
    if html or re.match(r"(?is)\s*(<!doctype html|<html|<head|<body|<div|<p[\s>])", stripped):
        return Content(text=html_text(text, css_selector))
    return Content(text=_clean_text(text))


def _get(url: str):
    """One pinned GET of ``url``: ``(body, response)``, with errors sorted for the tick."""
    try:
        return pinned_fetch_bytes(
            url,
            max_bytes=FETCH_MAX_BYTES,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/json;q=0.9,*/*;q=0.5"},
            timeout=FETCH_TIMEOUT_SECONDS,
            truncate=True,
        )
    except UnsafeUserUrlError as exc:
        raise SourceError(f"the URL is not allowed: {exc}") from None
    except ResponseTooLargeError:
        raise SourceError("the page is too large") from None
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise SourceUnreachable(f"could not reach {url}: {type(exc).__name__}") from None
    except requests.RequestException as exc:
        raise SourceUnreachable(f"could not fetch {url}: {type(exc).__name__}") from None


def fetch_webpage(url: str, css_selector: Optional[str] = None) -> Content:
    """Fetch a page and normalize it.

    Redirects are followed up to :data:`MAX_REDIRECTS` hops; every hop is a
    new pinned fetch, so each target is validated (public address, http(s))
    before it is connected to.

    Args:
        url: The page.
        css_selector: Watch only the elements this selects.

    Returns:
        The normalized content.

    Raises:
        SourceUnreachable: Timeout, connection failure, 429 or 5xx.
        SourceError: An unsafe URL, too many redirects, another HTTP error, binary content, an empty selection.
    """
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        body, response = _get(current)
        status = response.status_code
        if not 300 <= status < 400:
            break
        location = (response.headers.get("Location") or "").strip()
        if not location:
            raise SourceError(f"{current} answered a redirect with no target")
        current = urljoin(current, location)
        if not current.lower().startswith(("http://", "https://")):
            raise SourceError("the URL redirects to something that is not a web page")
    else:
        raise SourceError(f"the URL redirects more than {MAX_REDIRECTS} times; watch the final URL instead")
    if status == 429 or status >= 500:
        raise SourceUnreachable(f"{url} answered HTTP {status}")
    if status >= 400:
        raise SourceError(f"{url} answered HTTP {status}")
    content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if content_type.startswith(("image/", "audio/", "video/")) or content_type in ("application/pdf",
                                                                                     "application/zip"):
        raise SourceError(f"the URL returns {content_type}, not a page")
    if b"\x00" in body[:1024]:
        raise SourceError("the URL returns binary content, not a page")
    text = _decode_body(body, response.headers.get("Content-Type") or "")
    if content_type in _JSON_TYPES or content_type.endswith("+json"):
        try:
            data = json.loads(text)
        except ValueError:
            raise SourceError("the URL says it returns JSON but the body is not valid JSON") from None
        return Content(text=canonical_json(data), data=data)
    if css_selector or content_type in ("text/html", "application/xhtml+xml"):
        return Content(text=html_text(text, css_selector))
    return content_from_text(text)


def content_from_tool_result(tool_name: str, result: Any) -> Content:
    """Normalize what a tool call returned.

    A remote command's result is reduced to its exit code and output (its
    duration changes every run): the text is the output of a successful
    command, else the whole outcome. A JSON-looking string is parsed; any
    other value is kept as data with canonical text.
    """
    if tool_name == "remote_device" and isinstance(result, dict):
        stdout = str(result.get("stdout") or "")
        outcome = {
            "exit_code": result.get("exit_code"),
            "stdout": stdout,
            "stderr": str(result.get("stderr") or ""),
        }
        if stdout.strip()[:1] in ("{", "["):
            try:
                outcome["stdout"] = json.loads(stdout)
            except ValueError:
                pass
        if result.get("exit_code") == 0 and not outcome["stderr"]:
            return Content(text=_clean_text(stdout), data=outcome)
        return Content(text=canonical_json(outcome), data=outcome)
    if isinstance(result, (dict, list)):
        return Content(text=canonical_json(result), data=result)
    if isinstance(result, (int, float)) and not isinstance(result, bool):
        return Content(text=str(result), data=result)
    return content_from_text(str(result if result is not None else ""))
