"""The Website source: a list of pages and whole sites, minus skipped addresses.

A Website source stores what it fetches, not just one URL, so pages added or
removed by hand survive a sync:

- a ``page`` entry is fetched as written;
- a ``site`` entry is a start address plus its scope (page limit, a path to
  stay under, subdomains, how pages are found). "Automatic" reads the site's
  sitemap (robots.txt, then the well-known locations) and falls back to
  following links. The limit takes the sitemap's own order, after scope and
  skips are applied;
- ``WEB_MAX_PAGES`` caps the whole source: pages are fetched first, and sites
  share what is left, in their order;
- ``skip`` lists addresses a site's crawl must leave out: an exact page, or a
  section written as ``https://host/path/*``.

``remote_data`` holds this config; ``parse_website_config`` validates it.
"""

import json
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlparse, urlsplit

import requests
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
from docsgpt.parser.remote.page_content import FetchBudget, fetch_page
from docsgpt.parser.remote.sitemap_loader import SitemapLoader
from docsgpt.parser.remote.web_loader import WebLoader
from docsgpt.parser.schema.base import Document

logger = logging.getLogger(__name__)

ENTRY_MODES = ("page", "site")
DISCOVERY_MODES = ("auto", "sitemap", "links")

# Write limits on a config, so one saved source can't make every listing,
# sync and settings view walk an unbounded list. URLs past 2048 characters are
# refused by many servers and browsers anyway. Twenty sites is far more than
# a real source needs, and each site fans out into discovery fetches. Skip
# rules grow one per removed page (a folder adds one section rule), so the cap
# leaves room for years of pruning; a rule is a URL plus an optional ``*``.
MAX_URL_LENGTH = 2048
MAX_SITE_ENTRIES = 20
MAX_SKIP_RULES = 1000

# Well-known sitemap locations, tried when robots.txt names none.
_WELL_KNOWN_SITEMAPS = ("/sitemap.xml", "/sitemap_index.xml")
_SITEMAP_LINE = re.compile(r"^\s*sitemap\s*:\s*(\S+)", re.IGNORECASE)
# How much of a response to look at to decide it is a sitemap.
_SNIFF_BYTES = 64 * 1024
# Google reads the first 500 KiB of a robots.txt; past that is not a real one.
_ROBOTS_MAX_BYTES = 512 * 1024
# robots.txt ``Sitemap:`` lines taken. Sites list one to a handful; each is a
# sitemap walk.
MAX_ROBOTS_SITEMAPS = 10

# Every fetch a load makes (pages that fail or aren't HTML, robots.txt,
# sitemaps) is charged to one budget per source, so dead or non-HTML hosts
# can't multiply the work by the number of sites. It allows each page of the
# cap two attempts, plus the discovery fetches of a few sites; a normal load
# never reaches it.
_FETCHES_PER_PAGE = 2
_DISCOVERY_FETCHES = 30


def fetch_budget_for(cap: int) -> int:
    """How many fetches one load of a source may make.

    Args:
        cap: The source's page cap (``WEB_MAX_PAGES``).

    Returns:
        The fetch budget.
    """
    return _FETCHES_PER_PAGE * int(cap) + _DISCOVERY_FETCHES

# The bundled public-suffix snapshot is enough to tell a registered domain;
# the default extractor would fetch the live list on first use.
_domains = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def _bare_host(host: Optional[str]) -> str:
    """A host compared case-insensitively, with ``www.`` treated as the bare host."""
    host = (host or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _registered_domain(host: str) -> str:
    """The registered domain of a host (``example.co.uk`` for ``docs.example.co.uk``); empty when it has none."""
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


def _in_section(key: str, section: str) -> bool:
    """Whether a page key falls under a section rule's key.

    A section is the folder of the same name in the file tree, so it holds
    the pages below its path. A path section's own page sits beside the
    folder (``/Deploying`` is ``Deploying.md``) and stays; a host section
    (``https://host/*``, a removed host folder) also holds the host's root
    page, ``host/index.md``, with or without a query.

    Args:
        key: A candidate page's ``page_key``.
        section: The rule's ``page_key``, without the ``*``.

    Returns:
        True when the rule covers the page.
    """
    if key.startswith(section + "/"):
        return True
    host_only = "/" not in section and "?" not in section
    return host_only and (key == section or key.startswith(section + "?"))


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
        """Whether a bare host is the site, or a subdomain of it when those are on."""
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
        return not any(_in_section(key, section) for section in self.skip_sections)


def _fetch(url: str, max_bytes: int, budget: Optional[FetchBudget] = None) -> Optional[requests.Response]:
    """GET at most ``max_bytes`` of ``url`` for discovery.

    Args:
        url: The address.
        max_bytes: How much of the body to read; the rest is cut off.
        budget: The load's fetch budget, charged one fetch.

    Returns:
        The response, or ``None`` on a spent budget, a blocked address, a
        network error or an error status.
    """
    if budget is not None and not budget.take():
        logger.debug(f"Sitemap discovery: fetch budget spent before {url}")
        return None
    try:
        url = validate_url(url)
        response = fetch_page(url, max_bytes, timeout=15)
        response.raise_for_status()
        return response
    except (SSRFError, Exception) as e:  # noqa: BLE001 - discovery is best effort
        logger.debug(f"Sitemap discovery: {url} unavailable ({e})")
        return None


def _looks_like_sitemap(response: requests.Response) -> bool:
    """Whether a response is a sitemap (XML or gzip), not a soft-404 HTML page.

    Args:
        response: A fetched well-known sitemap location.

    Returns:
        True for gzip bytes or a ``<urlset>``/``<sitemapindex>`` near the start.
    """
    content = response.content if isinstance(response.content, bytes) else b""
    if content[:2] == b"\x1f\x8b":
        return True
    head = content[:_SNIFF_BYTES]
    return b"<urlset" in head or b"<sitemapindex" in head


def _is_sitemap_url(url: str) -> bool:
    """Whether an address names a sitemap file (``.xml`` or ``.xml.gz``).

    Args:
        url: A start address.

    Returns:
        True when its path ends in ``.xml`` or ``.xml.gz``.
    """
    path = urlparse(url).path.lower()
    return path.endswith(".xml") or path.endswith(".xml.gz")


def discover_sitemaps(start_url: str, budget: Optional[FetchBudget] = None) -> List[str]:
    """Find a site's sitemaps: robots.txt ``Sitemap:`` lines, else the well-known locations.

    Args:
        start_url: Any address on the site.
        budget: The load's fetch budget; each discovery fetch costs one.

    Returns:
        Sitemap URLs to walk, in order, at most ``MAX_ROBOTS_SITEMAPS``;
        empty when the site has none.
    """
    parsed = urlparse(start_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    robots = _fetch(origin + "/robots.txt", _ROBOTS_MAX_BYTES, budget)
    if robots is not None:
        listed = []
        for line in (robots.text or "").splitlines():
            match = _SITEMAP_LINE.match(line)
            if match and match.group(1) not in listed:
                listed.append(match.group(1))
                if len(listed) >= MAX_ROBOTS_SITEMAPS:
                    break
        if listed:
            return listed
    for path in _WELL_KNOWN_SITEMAPS:
        # Only the head is sniffed; the sitemap walk fetches it in full.
        response = _fetch(origin + path, _SNIFF_BYTES, budget)
        # A soft 404 answers every path with the app's HTML shell.
        if response is not None and _looks_like_sitemap(response):
            return [origin + path]
    return []


def _clamp_pages(requested: Optional[int]) -> int:
    """A site's page limit: its own, else ``WEB_DEFAULT_PAGES``, kept within 1..``WEB_MAX_PAGES``."""
    limit = int(requested) if requested else int(settings.WEB_DEFAULT_PAGES)
    return max(1, min(limit, int(settings.WEB_MAX_PAGES)))


def is_web_address(url: str) -> bool:
    """Whether ``url`` names a fetchable http(s) address, as the loaders would dial it.

    A missing scheme is taken as ``http://``, as ``validate_url`` does. No DNS
    lookup: the SSRF check runs at fetch time.

    Args:
        url: An address as the user wrote it.

    Returns:
        True when it parses, is http or https, and names a host (and a valid
        port, when it has one).
    """
    try:
        candidate = url if urlsplit(url).scheme else "http://" + url
        parts = urlsplit(candidate)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a port out of range
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(host)


def _entry_url(value: Any, label: str, enforce_limits: bool) -> str:
    """The stripped address of an entry field, or ``ValueError`` when it isn't one."""
    url = value.strip()
    if not is_web_address(url):
        raise ValueError(f"{label} {url[:200]!r} is not a web address")
    if enforce_limits and len(url) > MAX_URL_LENGTH:
        raise ValueError(f"{label} is longer than {MAX_URL_LENGTH} characters")
    return url


def parse_website_config(
    raw: Union[str, Dict[str, Any], None], enforce_page_cap: bool = True,
) -> Dict[str, Any]:
    """Validate a Website source's config (as stored in ``remote_data``).

    Args:
        raw: The config, as a dict or its JSON.
        enforce_page_cap: Apply the write limits: ``WEB_MAX_PAGES`` on the
            entries, ``MAX_SITE_ENTRIES``, ``MAX_SKIP_RULES`` and
            ``MAX_URL_LENGTH``. Writes keep it on. Reading a stored config
            turns it off, so a lowered cap or a config that grew past a limit
            (pages appended, skips added on removal) still lists and syncs.
            Every entry URL must parse either way.

    Returns:
        ``{"entries": [...], "skip": [...], "keep_links": bool}`` with every
        entry's fields filled in.

    Raises:
        ValueError: If the config is malformed, has no entries, an entry URL
            isn't a web address, or (with ``enforce_page_cap``) a limit is
            passed.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Website config is not JSON: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError("Website config must be an object")
    items = raw.get("entries") or []
    if not isinstance(items, list):
        raise ValueError("Website entries must be a list")
    entries = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str) or not item["url"].strip():
            raise ValueError("Each website entry needs a url")
        mode = item.get("mode") or "page"
        if mode not in ENTRY_MODES:
            raise ValueError(f"Unknown website entry mode {mode!r}")
        entry = {"url": _entry_url(item["url"], "Address", enforce_page_cap), "mode": mode}
        if mode == "site":
            discovery = item.get("discovery") or "auto"
            if discovery not in DISCOVERY_MODES:
                raise ValueError(f"Unknown page discovery {discovery!r}")
            max_pages = item.get("max_pages")
            if max_pages is not None and (
                not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1
            ):
                raise ValueError("max_pages must be a positive whole number")
            sitemap_url = item.get("sitemap_url")
            if isinstance(sitemap_url, str) and sitemap_url.strip():
                sitemap_url = _entry_url(sitemap_url, "Sitemap address", enforce_page_cap)
            else:
                sitemap_url = None
            entry.update({
                "max_pages": max_pages,
                "path_prefix": str(item.get("path_prefix") or ""),
                "include_subdomains": bool(item.get("include_subdomains")),
                "discovery": discovery,
                "sitemap_url": sitemap_url,
            })
        entries.append(entry)
    if not entries:
        raise ValueError("A website source needs at least one page or site")
    rules = raw.get("skip") or []
    skip = [rule.strip() for rule in rules if isinstance(rule, str) and rule.strip()] if isinstance(rules, list) else []
    if enforce_page_cap:
        cap = int(settings.WEB_MAX_PAGES)
        # A site brings at least one page, so it counts toward the cap too.
        if len(entries) > cap:
            raise ValueError(f"A website source holds up to {cap} pages")
        if sum(1 for entry in entries if entry["mode"] == "site") > MAX_SITE_ENTRIES:
            raise ValueError(f"A website source holds up to {MAX_SITE_ENTRIES} sites")
        if len(skip) > MAX_SKIP_RULES:
            raise ValueError(f"A website source holds up to {MAX_SKIP_RULES} skip rules")
        if any(len(rule.removesuffix("*")) > MAX_URL_LENGTH for rule in skip):
            raise ValueError(f"A skip rule is longer than {MAX_URL_LENGTH} characters")
    return {"entries": entries, "skip": skip, "keep_links": bool(raw.get("keep_links"))}


class WebsiteLoader(BaseRemote):
    """Load a Website source's pages and sites into documents."""

    def __init__(self) -> None:
        """Start with an empty report."""
        # What the last load did, per site: how pages were found and whether
        # the page limit cut it short. Read by the worker for its notice.
        self.report: Dict[str, Any] = {}

    def load_data(self, inputs: Union[str, Dict[str, Any]]) -> List[Document]:
        """Fetch every entry, drop duplicates, and name pages for the file tree.

        Args:
            inputs: The Website config (see ``parse_website_config``).

        Returns:
            One document per page: the pages first, then each site's, in entry
            order. ``WEB_MAX_PAGES`` caps the total, so sites get what the
            pages leave. Every fetch, discovery included, is charged to one
            budget (``fetch_budget_for``), so failed or non-HTML fetches can't
            multiply across sites.
        """
        # A stored config: the write limits don't apply, the fetch budget does.
        config = parse_website_config(inputs, enforce_page_cap=False)
        keep_links = config["keep_links"]
        cap = int(settings.WEB_MAX_PAGES)
        fetches = FetchBudget(fetch_budget_for(cap))
        documents: List[Document] = []
        seen = set()
        site_reports = []

        entries = sorted(config["entries"], key=lambda entry: entry["mode"] != "page")
        for entry in entries:
            if entry["mode"] == "page":
                try:
                    key = page_key(entry["url"])
                except ValueError:
                    logger.warning(f"Skipping unparseable page {entry['url']!r}")
                    continue
                if key in seen:
                    continue
                docs = WebLoader(keep_links=keep_links, budget=fetches).load_data([entry["url"]])
            else:
                pages_left = min(cap - len(documents), fetches.remaining)
                if pages_left < 1:
                    site_reports.append({
                        "url": entry["url"], "found_with": None, "pages": 0, "limit_reached": True,
                    })
                    continue
                docs, report = self._load_site(entry, config["skip"], keep_links, pages_left, fetches)
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
    def _load_site(
        entry: Dict[str, Any],
        skip: List[str],
        keep_links: bool,
        budget: Optional[int] = None,
        fetches: Optional[FetchBudget] = None,
    ) -> Tuple[List[Document], Dict[str, Any]]:
        """Load one whole-site entry through its sitemap, else by following links.

        Args:
            entry: A ``site`` entry from ``parse_website_config``.
            skip: The source's skip rules.
            keep_links: Keep the URL of links inside sentences.
            budget: The most pages the source has left; lowers the entry's limit.
            fetches: The load's fetch budget, charged for discovery and pages.

        Returns:
            The pages, and a report: the start URL, ``found_with`` (``sitemap``,
            ``links`` or ``None``), the page count and ``limit_reached``.
        """
        url = entry["url"]
        limit = _clamp_pages(entry.get("max_pages"))
        if budget is not None:
            limit = max(1, min(limit, budget))
        scope = SiteScope(url, entry.get("path_prefix", ""), entry.get("include_subdomains", False), skip)
        discovery = entry.get("discovery", "auto")
        pasted_sitemap = _is_sitemap_url(url)

        if entry.get("sitemap_url"):
            sitemaps = [entry["sitemap_url"]]
        elif pasted_sitemap:
            sitemaps = [url]
        elif discovery in ("auto", "sitemap"):
            sitemaps = discover_sitemaps(url, fetches)
        else:
            sitemaps = []

        docs: List[Document] = []
        found_with = None
        limit_reached = False
        if sitemaps:
            loader = SitemapLoader(limit=limit, accept=scope.accepts, keep_links=keep_links, budget=fetches)
            urls = loader.collect_urls(sitemaps)
            if urls:
                docs = loader.load_pages(urls)
                found_with = "sitemap"
                limit_reached = loader.limit_reached
        if not docs and discovery != "sitemap" and not pasted_sitemap:
            loader = CrawlerLoader(limit=limit, accept=scope.accepts, keep_links=keep_links, budget=fetches)
            docs = loader.load_data(url)
            found_with = "links" if docs else None
            limit_reached = loader.limit_reached
        return docs, {"url": url, "found_with": found_with, "pages": len(docs), "limit_reached": limit_reached}
