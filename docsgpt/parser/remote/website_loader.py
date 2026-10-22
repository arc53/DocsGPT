"""The Website source: a list of pages and whole sites, minus skipped addresses.

A Website source stores what it fetches, not just one URL, so pages added or
removed by hand survive a sync:

- a ``page`` entry is fetched as written;
- a ``site`` entry is a start address plus its scope (page limit, a path to
  stay under, subdomains, how pages are found). "Automatic" reads the site's
  sitemap (robots.txt, then the well-known locations) and falls back to
  following links. The limit takes the sitemap's own order, after scope and
  skips are applied;
- ``skip`` lists addresses a site's crawl must leave out: an exact page, or a
  section written as ``https://host/path/*``.

``remote_data`` holds this config; ``parse_website_config`` validates it.
"""

import json
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlparse, urlsplit

import tldextract

from docsgpt.core.settings import settings
from docsgpt.core.url_validation import SSRFError, validate_url
from docsgpt.parser.remote.base import (
    BaseRemote,
    dedupe_virtual_paths,
    normalize_page_url,
    spans_multiple_hosts,
    url_to_virtual_path,
)
from docsgpt.parser.remote.crawler_loader import CrawlerLoader
from docsgpt.parser.remote.sitemap_loader import SitemapLoader
from docsgpt.parser.remote.web_loader import WebLoader
from docsgpt.parser.schema.base import Document
from docsgpt.security.safe_url import pinned_request

logger = logging.getLogger(__name__)

ENTRY_MODES = ("page", "site")
DISCOVERY_MODES = ("auto", "sitemap", "links")
# Well-known sitemap locations, tried when robots.txt names none.
_WELL_KNOWN_SITEMAPS = ("/sitemap.xml", "/sitemap_index.xml")
_SITEMAP_LINE = re.compile(r"^\s*sitemap\s*:\s*(\S+)", re.IGNORECASE)
# How much of a response to look at to decide it is a sitemap.
_SNIFF_BYTES = 64 * 1024

# The bundled public-suffix snapshot is enough to tell a registered domain;
# the default extractor would fetch the live list on first use.
_domains = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def _bare_host(host: Optional[str]) -> str:
    """A host compared case-insensitively, with ``www.`` treated as the bare host."""
    host = (host or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _registered_domain(host: str) -> str:
    extracted = _domains(host)
    if not extracted.domain or not extracted.suffix:
        return ""
    return f"{extracted.domain}.{extracted.suffix}"


def page_key(url: str) -> str:
    """One key per page: scheme, ``www.``, fragment, query order and a trailing slash don't count.

    Args:
        url: A page URL.

    Returns:
        ``host/path`` (plus ``?query``), for comparing pages and skip rules.

    Raises:
        ValueError: If the URL cannot be parsed.
    """
    parts = urlsplit(normalize_page_url(url.strip()))
    key = f"{_bare_host(parts.hostname)}{parts.path.rstrip('/')}"
    return f"{key}?{parts.query}" if parts.query else key


class SiteScope:
    """Which addresses a whole-site entry may reach."""

    def __init__(
        self,
        start_url: str,
        path_prefix: str = "",
        include_subdomains: bool = False,
        skip: Iterable[str] = (),
    ):
        """
        Args:
            start_url: The entry's start address; its host is the site.
            path_prefix: Only paths under this one (``/docs/``); empty for all.
            include_subdomains: Also accept other hosts of the same registered
                domain (``docs.example.co.uk`` for ``example.co.uk``).
            skip: Exact page URLs, or sections written ``https://host/path/*``.
        """
        self.host = _bare_host(urlparse(start_url).hostname)
        self.domain = _registered_domain(self.host)
        self.include_subdomains = include_subdomains
        prefix = (path_prefix or "").strip()
        self.path_prefix = "/" + prefix.strip("/") if prefix.strip("/") else ""
        self.skip_pages = set()
        self.skip_sections = []
        for rule in skip:
            rule = (rule or "").strip()
            try:
                if rule.endswith("*"):
                    self.skip_sections.append(page_key(rule[:-1]))
                elif rule:
                    self.skip_pages.add(page_key(rule))
            except ValueError:
                logger.warning(f"Ignoring unparseable skip rule {rule!r}")

    def _host_ok(self, host: str) -> bool:
        if host == self.host:
            return True
        return bool(self.include_subdomains and self.domain and _registered_domain(host) == self.domain)

    def accepts(self, url: str) -> bool:
        """Whether a crawl or sitemap of this site should take ``url``.

        Args:
            url: A candidate page URL.

        Returns:
            True when it is on the site, under the path, and not skipped.
        """
        try:
            parsed = urlparse(url)
            key = page_key(url)
        except ValueError:
            return False
        if parsed.scheme not in ("http", "https") or not self._host_ok(_bare_host(parsed.hostname)):
            return False
        if self.path_prefix:
            path = parsed.path or "/"
            if path.rstrip("/") != self.path_prefix and not path.startswith(self.path_prefix + "/"):
                return False
        if key in self.skip_pages:
            return False
        return not any(key.startswith(section + "/") for section in self.skip_sections)


def _fetch(url: str):
    """GET ``url``; ``None`` on a blocked address, a network error or an error status."""
    try:
        url = validate_url(url)
        response = pinned_request("GET", url, timeout=15)
        response.raise_for_status()
        return response
    except (SSRFError, Exception) as e:  # noqa: BLE001 - discovery is best effort
        logger.debug(f"Sitemap discovery: {url} unavailable ({e})")
        return None


def _looks_like_sitemap(response) -> bool:
    content = response.content if isinstance(response.content, bytes) else b""
    if content[:2] == b"\x1f\x8b":
        return True
    head = content[:_SNIFF_BYTES]
    return b"<urlset" in head or b"<sitemapindex" in head


def _is_sitemap_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".xml") or path.endswith(".xml.gz")


def discover_sitemaps(start_url: str) -> List[str]:
    """Find a site's sitemaps: robots.txt ``Sitemap:`` lines, else the well-known locations.

    Args:
        start_url: Any address on the site.

    Returns:
        Sitemap URLs to walk, in order; empty when the site has none.
    """
    parsed = urlparse(start_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    robots = _fetch(origin + "/robots.txt")
    if robots is not None:
        listed = []
        for line in (robots.text or "").splitlines():
            match = _SITEMAP_LINE.match(line)
            if match and match.group(1) not in listed:
                listed.append(match.group(1))
        if listed:
            return listed
    for path in _WELL_KNOWN_SITEMAPS:
        response = _fetch(origin + path)
        # A soft 404 answers every path with the app's HTML shell.
        if response is not None and _looks_like_sitemap(response):
            return [origin + path]
    return []


def _clamp_pages(requested: Optional[int]) -> int:
    limit = int(requested) if requested else int(settings.WEB_DEFAULT_PAGES)
    return max(1, min(limit, int(settings.WEB_MAX_PAGES)))


def parse_website_config(raw: Union[str, Dict[str, Any], None]) -> Dict[str, Any]:
    """Validate a Website source's config (as stored in ``remote_data``).

    Args:
        raw: The config, as a dict or its JSON.

    Returns:
        ``{"entries": [...], "skip": [...], "keep_links": bool}`` with every
        entry's fields filled in.

    Raises:
        ValueError: If the config is malformed or has no entries.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Website config is not JSON: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError("Website config must be an object")
    entries = []
    for item in raw.get("entries") or []:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str) or not item["url"].strip():
            raise ValueError("Each website entry needs a url")
        mode = item.get("mode") or "page"
        if mode not in ENTRY_MODES:
            raise ValueError(f"Unknown website entry mode {mode!r}")
        entry = {"url": item["url"].strip(), "mode": mode}
        if mode == "site":
            discovery = item.get("discovery") or "auto"
            if discovery not in DISCOVERY_MODES:
                raise ValueError(f"Unknown page discovery {discovery!r}")
            max_pages = item.get("max_pages")
            if max_pages is not None and (not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1):
                raise ValueError("max_pages must be a positive whole number")
            sitemap_url = item.get("sitemap_url")
            entry.update({
                "max_pages": max_pages,
                "path_prefix": str(item.get("path_prefix") or ""),
                "include_subdomains": bool(item.get("include_subdomains")),
                "discovery": discovery,
                "sitemap_url": sitemap_url.strip() if isinstance(sitemap_url, str) and sitemap_url.strip() else None,
            })
        entries.append(entry)
    if not entries:
        raise ValueError("A website source needs at least one page or site")
    skip = [rule.strip() for rule in raw.get("skip") or [] if isinstance(rule, str) and rule.strip()]
    return {"entries": entries, "skip": skip, "keep_links": bool(raw.get("keep_links"))}


class WebsiteLoader(BaseRemote):
    """Load a Website source's pages and sites into documents."""

    def __init__(self):
        # What the last load did, per site: how pages were found and whether
        # the page limit cut it short. Read by the worker for its notice.
        self.report: Dict[str, Any] = {}

    def load_data(self, inputs) -> List[Document]:
        """Fetch every entry, drop duplicates, and name pages for the file tree.

        Args:
            inputs: The Website config (see ``parse_website_config``).

        Returns:
            One document per page, in entry order.
        """
        config = parse_website_config(inputs)
        keep_links = config["keep_links"]
        documents: List[Document] = []
        seen = set()
        site_reports = []

        for entry in config["entries"]:
            if entry["mode"] == "page":
                try:
                    key = page_key(entry["url"])
                except ValueError:
                    logger.warning(f"Skipping unparseable page {entry['url']!r}")
                    continue
                if key in seen:
                    continue
                docs = WebLoader(keep_links=keep_links).load_data([entry["url"]])
            else:
                docs, report = self._load_site(entry, config["skip"], keep_links)
                site_reports.append(report)
            for doc in docs:
                key = page_key(doc.extra_info["source"])
                if key in seen:
                    continue
                seen.add(key)
                documents.append(doc)

        # Name pages after the whole load, so one host stays path-only and
        # several hosts get a folder each.
        include_host = spans_multiple_hosts([d.extra_info["source"] for d in documents])
        for doc in documents:
            doc.extra_info["file_path"] = url_to_virtual_path(doc.extra_info["source"], include_host)
        self.report = {"pages": len(documents), "sites": site_reports}
        return dedupe_virtual_paths(documents)

    @staticmethod
    def _load_site(entry: Dict[str, Any], skip: List[str], keep_links: bool) -> Tuple[List[Document], Dict[str, Any]]:
        """Load one whole-site entry through its sitemap, else by following links.

        Args:
            entry: A ``site`` entry from ``parse_website_config``.
            skip: The source's skip rules.
            keep_links: Keep the URL of links inside sentences.

        Returns:
            The pages, and a report: the start URL, ``found_with`` (``sitemap``,
            ``links`` or ``None``), the page count and ``limit_reached``.
        """
        url = entry["url"]
        limit = _clamp_pages(entry.get("max_pages"))
        scope = SiteScope(url, entry.get("path_prefix", ""), entry.get("include_subdomains", False), skip)
        discovery = entry.get("discovery", "auto")
        pasted_sitemap = _is_sitemap_url(url)

        if entry.get("sitemap_url"):
            sitemaps = [entry["sitemap_url"]]
        elif pasted_sitemap:
            sitemaps = [url]
        elif discovery in ("auto", "sitemap"):
            sitemaps = discover_sitemaps(url)
        else:
            sitemaps = []

        docs: List[Document] = []
        found_with = None
        limit_reached = False
        if sitemaps:
            loader = SitemapLoader(limit=limit, accept=scope.accepts, keep_links=keep_links)
            urls = loader.collect_urls(sitemaps)
            if urls:
                docs = loader.load_pages(urls)
                found_with = "sitemap"
                limit_reached = loader.limit_reached
        if not docs and discovery != "sitemap" and not pasted_sitemap:
            loader = CrawlerLoader(limit=limit, accept=scope.accepts, keep_links=keep_links)
            docs = loader.load_data(url)
            found_with = "links" if docs else None
            limit_reached = loader.limit_reached
        return docs, {"url": url, "found_with": found_with, "pages": len(docs), "limit_reached": limit_reached}
