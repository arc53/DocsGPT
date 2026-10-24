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
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import SplitResult, urljoin, urlparse, urlsplit

import requests
import tldextract

from docsgpt.core.settings import settings
from docsgpt.parser.remote.base import BaseRemote, dedupe_virtual_paths, spans_multiple_hosts, url_to_virtual_path
from docsgpt.parser.remote.crawler_loader import CrawlerLoader
from docsgpt.parser.remote.page_content import (
    MAX_PATH_SEGMENTS,
    MAX_URL_LENGTH,
    FetchBudget,
    bare_host,
    explicit_port,
    fetch_page,
    final_url,
    is_ambiguous_path,
    merge_requested_urls,
    normalized_path,
    page_key,
    within_url_limits,
)
from docsgpt.parser.remote.sitemap_loader import SITEMAP_SNIFF_BYTES, SitemapLoader, looks_like_sitemap
from docsgpt.parser.remote.web_loader import WebLoader
from docsgpt.parser.schema.base import Document

logger = logging.getLogger(__name__)

ENTRY_MODES = ("page", "site")
DISCOVERY_MODES = ("auto", "sitemap", "links")

# Write limits on a config, so one saved source can't make every listing,
# sync and settings view walk an unbounded list. Addresses are held to
# ``MAX_URL_LENGTH`` characters and ``MAX_PATH_SEGMENTS`` deep, as every
# fetch is (``within_url_limits``). Each site fans out into discovery
# fetches; skip rules grow one per removed page (a folder adds one section
# rule), so the cap leaves room for years of pruning.
MAX_SITE_ENTRIES = 20
MAX_SKIP_RULES = 1000

# Well-known sitemap locations, tried when robots.txt names none.
_WELL_KNOWN_SITEMAPS = ("/sitemap.xml", "/sitemap_index.xml")
_SITEMAP_LINE = re.compile(r"^\s*sitemap\s*:\s*(\S+)", re.IGNORECASE)
# Google reads the first 500 KiB of a robots.txt; past that is not a real one.
_ROBOTS_MAX_BYTES = 512 * 1024
# robots.txt ``Sitemap:`` lines taken; each is a sitemap walk.
MAX_ROBOTS_SITEMAPS = 10

# Every fetch a load makes (pages that fail or aren't HTML, robots.txt,
# sitemaps) is charged to one budget per source, so dead or non-HTML hosts
# can't multiply the work by the number of sites. It allows each page of the
# cap two attempts, plus the discovery fetches of a few sites.
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


# A load also stops starting fetches after a time that grows with the cap:
# a fetch may take a minute, so a site answering just inside its timeout
# could otherwise hold a worker for hours. A 100-page source gets about 22
# minutes, inside the hour a broker waits before redelivering a task.
_SECONDS_PER_PAGE = 10
_DISCOVERY_SECONDS = 300


def load_deadline_for(cap: int) -> float:
    """How many seconds one load of a source may keep starting fetches.

    Args:
        cap: The source's page cap (``WEB_MAX_PAGES``).

    Returns:
        The seconds from the start of the load.
    """
    return float(_SECONDS_PER_PAGE * int(cap) + _DISCOVERY_SECONDS)


# The bundled public-suffix snapshot is enough to tell a registered domain;
# the default extractor would fetch the live list on first use. Its private
# part counts too: each github.io or vercel.app tenant is a domain of its own.
_domains = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)


def _registered_domain(host: str) -> str:
    """The registered domain of a host (``example.co.uk`` for ``docs.example.co.uk``); empty when it has none."""
    extracted = _domains(host)
    if not extracted.domain or not extracted.suffix:
        return ""
    return f"{extracted.domain}.{extracted.suffix}"


def _in_section(key: str, section: str) -> bool:
    """Whether a page key falls under a section rule's key (both ``page_key(..., keep_www=True)``).

    A section is the tree folder of the same name, so it holds the pages
    below its path; a path section's own page sits beside the folder and
    stays. A host section (``https://host/*``) also holds the host's root
    page, with or without a query. It names its host exactly:
    ``https://www.x.io/*`` covers the ``www.x.io`` folder, not ``x.io``.
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
            start_url: The entry's start address; its host (and its port,
                when it names one other than the scheme's) is the site.
            path_prefix: Only paths under this one (``/docs/``); empty for all.
            include_subdomains: Also accept other hosts of the same registered
                domain (``docs.example.co.uk`` for ``example.co.uk``).
            skip: Exact page URLs, or sections written ``https://host/path/*``.
                A page rule ignores ``www.`` as ``page_key`` does; a section
                matches its host exactly (see ``_in_section``).
        """
        start = urlsplit(start_url)
        self.host = bare_host(start.hostname)
        # Another port is another server: a site is its host and port.
        try:
            self.port = explicit_port(start)
        except ValueError:
            self.port = None
        self.domain = _registered_domain(self.host)
        self.include_subdomains = include_subdomains
        # Spelled as page keys spell paths, so ``/Café`` and ``/Caf%C3%A9`` are one prefix.
        prefix = normalized_path("/" + (path_prefix or "").strip().strip("/")).strip("/")
        self.path_prefix = "/" + prefix if prefix else ""
        self.skip_pages = set()
        self.skip_sections = []
        for rule in skip:
            rule = (rule or "").strip()
            try:
                if rule.endswith("*"):
                    self.skip_sections.append(page_key(rule[:-1], keep_www=True))
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
            Never for a path servers could read as another one (an encoded
            ``/`` or ``\\``, or a dot segment; see ``is_ambiguous_path``):
            ``/docs/..%2Fadmin`` may be served from outside ``/docs``.
            Paths and rules are compared in one percent-encoding.
        """
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not self._host_ok(bare_host(parsed.hostname)):
                return False
            if explicit_port(parsed) != self.port:
                return False
            if is_ambiguous_path(parsed.path):
                return False
            if self.path_prefix:
                path = normalized_path(parsed.path) or "/"
                if path.rstrip("/") != self.path_prefix and not path.startswith(self.path_prefix + "/"):
                    return False
            if not self.skip_pages and not self.skip_sections:
                return True
            if page_key(url) in self.skip_pages:
                return False
            section_key = page_key(url, keep_www=True)
        except ValueError:
            return False
        return not any(_in_section(section_key, section) for section in self.skip_sections)


def _fetch(url: str, max_bytes: int, budget: Optional[FetchBudget] = None) -> Optional[requests.Response]:
    """GET at most ``max_bytes`` of ``url`` for discovery, charged to ``budget``.

    Returns:
        The response, or ``None`` on a spent budget, a blocked address (the
        pinned fetch refuses it), a network error, a redirect that can't be
        followed or an error status.
    """
    if budget is not None and not budget.take():
        logger.debug(f"Sitemap discovery: fetch budget spent before {url}")
        return None
    try:
        response = fetch_page(url, max_bytes, timeout=15, budget=budget)
        response.raise_for_status()
        return response
    except Exception as e:  # noqa: BLE001 - discovery is best effort
        logger.debug(f"Sitemap discovery: {url} unavailable ({e})")
        return None


def is_sitemap_url(url: str) -> bool:
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
    robots_url = origin + "/robots.txt"
    robots = _fetch(robots_url, _ROBOTS_MAX_BYTES, budget)
    if robots is not None:
        # A relative line (``Sitemap: /sitemap.xml``) is on the host that
        # served the robots.txt, after any redirect.
        base = final_url(robots, robots_url)
        listed = []
        for line in (robots.text or "").splitlines():
            match = _SITEMAP_LINE.match(line)
            if not match:
                continue
            try:
                sitemap = urljoin(base, match.group(1))
            except ValueError:
                continue
            if sitemap not in listed:
                listed.append(sitemap)
                if len(listed) >= MAX_ROBOTS_SITEMAPS:
                    break
        if listed:
            return listed
    for path in _WELL_KNOWN_SITEMAPS:
        # Only the head is sniffed; the sitemap walk fetches it in full.
        response = _fetch(origin + path, SITEMAP_SNIFF_BYTES, budget)
        # A soft 404 answers every path with the app's HTML shell.
        content = response.content if response is not None and isinstance(response.content, bytes) else b""
        if looks_like_sitemap(content):
            return [final_url(response, origin + path)]
    return []


def _clamp_pages(requested: Optional[int]) -> int:
    """A site's page limit: its own, else ``WEB_DEFAULT_PAGES``, kept within 1..``WEB_MAX_PAGES``."""
    limit = int(requested) if requested else int(settings.WEB_DEFAULT_PAGES)
    return max(1, min(limit, int(settings.WEB_MAX_PAGES)))


# ``host:port`` at the start of an address: ``urlsplit`` reads ``y.io:8080/c``
# as scheme ``y.io``. A dotted host, or localhost, is never a scheme people
# use, so it is taken as a host; ``tel:911`` or ``mailto:x`` stay schemes.
# The part before the first dot excludes dots, so a run of them can't backtrack.
_HOST_PORT = re.compile(r"^(?:[^:/?#@\s.]*\.[^:/?#@\s]*|localhost):\d+(?:[/?#]|$)", re.IGNORECASE)


def _has_scheme(url: str) -> bool:
    """Whether a stripped address names its scheme (``https://``, ``mailto:``), not ``host:port``.

    Raises:
        ValueError: If the address cannot be parsed.
    """
    return bool(urlsplit(url).scheme) and not _HOST_PORT.match(url)


def is_web_address(url: str) -> bool:
    """Whether ``url`` names a fetchable http(s) address, as the loaders would dial it.

    A missing scheme is taken as ``http://``, as ``validate_url`` does;
    ``host:port/path`` counts as missing one. No DNS lookup: the SSRF check
    runs at fetch time.

    Args:
        url: An address as the user wrote it.

    Returns:
        True when it parses, is http or https, and names a host (and a valid
        port, when it has one). False for an address with a control
        character anywhere, whitespace or a backslash in its host part, a
        host label that is empty or longer than DNS allows, or
        ``user:password@`` credentials: the fetch would send them, and the
        page's stored address would keep them.
    """
    if _CONTROL_CHARACTER.search(url):
        return False
    parts = _web_parts(url)
    if parts is None:
        return False
    if "@" in parts.netloc or "\\" in parts.netloc or any(ch.isspace() for ch in parts.netloc):
        return False
    return _labels_ok(parts.hostname)


def _web_parts(url: str) -> Optional[SplitResult]:
    """The ``urlsplit`` of an http(s) address with a host and a valid port (``http://`` if unnamed), else ``None``.

    The check a stored config's addresses get: one ``is_web_address`` now
    refuses still reads, and its fetch is refused on its own.
    """
    try:
        candidate = url if _has_scheme(url) else "http://" + url
        parts = urlsplit(candidate)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a port out of range
    except ValueError:
        return None
    return parts if parts.scheme in ("http", "https") and host else None


# C0 controls and DEL: a URL never carries them as written.
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
# The longest DNS label, in its ASCII (punycode) form.
_MAX_LABEL_LENGTH = 63


def _labels_ok(host: str) -> bool:
    """Whether a host's labels can be dialed: none empty (one trailing root dot allowed), none past 63 as ASCII."""
    if ":" in host:
        return True  # IPv6, from inside brackets
    labels = host.split(".")
    if labels[-1] == "" and len(labels) > 1:
        labels.pop()
    for label in labels:
        if not label:
            return False
        ascii_length = len(label) if label.isascii() else len("xn--") + len(label.encode("punycode"))
        if ascii_length > _MAX_LABEL_LENGTH:
            return False
    return True


class WebsiteConfigError(ValueError):
    """A Website config ``parse_website_config`` refuses.

    The message is English, for logs; ``code`` and ``details`` let the API
    hand the UI something to word itself.

    Attributes:
        code: ``site_limit``, ``skip_limit``, ``url_too_long``,
            ``page_limit``, ``invalid_address`` or ``invalid_config``.
        details: The refusal's numbers: ``max_sites``, ``max_skip``,
            ``max_length``, ``max_pages``, or the offending ``url``; empty
            for ``invalid_config``.
    """

    def __init__(self, message: str, code: str = "invalid_config", details: Optional[Dict[str, Any]] = None):
        """
        Args:
            message: The English message.
            code: The refusal's code.
            details: Its numbers or the offending value.
        """
        super().__init__(message)
        self.code = code
        self.details: Dict[str, Any] = dict(details or {})


def _with_scheme(url: str) -> str:
    """A stripped ``url`` with ``https://`` in front when written without a scheme (``example.com/docs``)."""
    try:
        return url if _has_scheme(url) else "https://" + url
    except ValueError:
        return url


def _entry_url(value: Any, label: str, enforce_limits: bool) -> str:
    """The stripped address of an entry field, with a scheme, or ``WebsiteConfigError`` when it isn't one.

    A write (``enforce_limits``) takes only an ``is_web_address`` at most
    ``MAX_URL_LENGTH`` long and ``MAX_PATH_SEGMENTS`` deep; a stored config
    read back only needs addresses that parse (``_web_parts``). A NUL is
    refused either way: PostgreSQL can't store one in JSONB.
    """
    url = value.strip()
    readable = is_web_address(url) if enforce_limits else "\x00" not in url and _web_parts(url) is not None
    if not readable:
        # The value is echoed back to the client: kept to a URL's length.
        raise WebsiteConfigError(
            f"{label} {url[:200]!r} is not a web address", "invalid_address", {"url": url[:MAX_URL_LENGTH]},
        )
    if enforce_limits and len(url) > MAX_URL_LENGTH:
        raise WebsiteConfigError(
            f"{label} is longer than {MAX_URL_LENGTH} characters", "url_too_long", {"max_length": MAX_URL_LENGTH},
        )
    if enforce_limits and not within_url_limits(_with_scheme(url)):
        raise WebsiteConfigError(
            f"{label} {url[:200]!r} is nested more than {MAX_PATH_SEGMENTS} folders deep",
            "invalid_address",
            {"url": url},
        )
    return _with_scheme(url)


def parse_website_config(
    raw: Union[str, Dict[str, Any], None], enforce_page_cap: bool = True,
) -> Dict[str, Any]:
    """Validate a Website source's config (as stored in ``remote_data``).

    Args:
        raw: The config, as a dict or its JSON.
        enforce_page_cap: Apply the write limits: ``WEB_MAX_PAGES`` on the
            entries (a site's ``max_pages`` is cut to it), ``MAX_SITE_ENTRIES``,
            ``MAX_SKIP_RULES`` and ``MAX_URL_LENGTH`` (addresses, skip rules
            and ``path_prefix``); page entries that are one page by
            ``page_key`` are cut to the first. Writes keep it on. Reading a
            stored config turns it off, so a lowered cap or a config that
            grew past a limit still lists and syncs.
            Every entry URL must parse either way, and hold no NUL. Control
            characters in a skip rule or ``path_prefix`` are refused on a
            write (``invalid_address`` and ``invalid_config``); a read drops
            the rule and strips them from the path.

    Returns:
        ``{"entries": [...], "skip": [...], "keep_links": bool}`` with every
        entry's fields filled in. An address or skip rule written without a
        scheme (``example.com/docs``) gets ``https://``, so its host parses.

    Raises:
        WebsiteConfigError: A ``ValueError`` with a ``code``: the config is
            malformed or has no entries (``invalid_config``), an entry URL
            isn't a web address (``invalid_address``), or, with
            ``enforce_page_cap``, a limit is passed (``page_limit``,
            ``site_limit``, ``skip_limit``, ``url_too_long``).
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise WebsiteConfigError(f"Website config is not JSON: {e}") from e
    if not isinstance(raw, dict):
        raise WebsiteConfigError("Website config must be an object")
    items = raw.get("entries") or []
    if not isinstance(items, list):
        raise WebsiteConfigError("Website entries must be a list")
    entries = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str) or not item["url"].strip():
            raise WebsiteConfigError("Each website entry needs a url")
        mode = item.get("mode") or "page"
        if mode not in ENTRY_MODES:
            raise WebsiteConfigError(f"Unknown website entry mode {mode!r}")
        entry = {"url": _entry_url(item["url"], "Address", enforce_page_cap), "mode": mode}
        if mode == "site":
            discovery = item.get("discovery") or "auto"
            if discovery not in DISCOVERY_MODES:
                raise WebsiteConfigError(f"Unknown page discovery {discovery!r}")
            max_pages = item.get("max_pages")
            if max_pages is not None and (
                not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1
            ):
                raise WebsiteConfigError("max_pages must be a positive whole number")
            if enforce_page_cap and max_pages is not None:
                # Cut, not refused: a site saved before the cap was lowered
                # still saves (the source settings can't edit its limit).
                max_pages = min(max_pages, int(settings.WEB_MAX_PAGES))
            sitemap_url = item.get("sitemap_url")
            if isinstance(sitemap_url, str) and sitemap_url.strip():
                sitemap_url = _entry_url(sitemap_url, "Sitemap address", enforce_page_cap)
            else:
                sitemap_url = None
            path_prefix = str(item.get("path_prefix") or "")
            if _CONTROL_CHARACTER.search(path_prefix):
                if enforce_page_cap:
                    raise WebsiteConfigError("Path has control characters in it")
                path_prefix = _CONTROL_CHARACTER.sub("", path_prefix)
            if enforce_page_cap and len(path_prefix) > MAX_URL_LENGTH:
                raise WebsiteConfigError(
                    f"Path is longer than {MAX_URL_LENGTH} characters", "url_too_long", {"max_length": MAX_URL_LENGTH},
                )
            entry.update({
                "max_pages": max_pages,
                "path_prefix": path_prefix,
                "include_subdomains": bool(item.get("include_subdomains")),
                "discovery": discovery,
                "sitemap_url": sitemap_url,
            })
        entries.append(entry)
    if not entries:
        raise WebsiteConfigError("A website source needs at least one page or site")
    rules = raw.get("skip") or []
    skip = [_with_scheme(r.strip()) for r in rules if isinstance(r, str) and r.strip()] if isinstance(rules, list) else []
    # A rule with a control character matches no address a crawl meets, and
    # one with a NUL can't be stored: refused on a write, dropped on a read.
    bad_rule = next((rule for rule in skip if _CONTROL_CHARACTER.search(rule)), None)
    if bad_rule is not None and enforce_page_cap:
        raise WebsiteConfigError(
            f"Skip rule {bad_rule[:200]!r} is not a web address", "invalid_address", {"url": bad_rule[:MAX_URL_LENGTH]},
        )
    if bad_rule is not None:
        skip = [rule for rule in skip if not _CONTROL_CHARACTER.search(rule)]
    if enforce_page_cap:
        # Variants of one page (``/new``, ``/new/``, ``www.``, a fragment)
        # are one entry: the first is kept.
        page_keys = set()
        unique = []
        for entry in entries:
            if entry["mode"] == "page":
                key = page_key(entry["url"])
                if key in page_keys:
                    continue
                page_keys.add(key)
            unique.append(entry)
        entries = unique
        cap = int(settings.WEB_MAX_PAGES)
        # A site brings at least one page, so it counts toward the cap too.
        if len(entries) > cap:
            raise WebsiteConfigError(f"A website source holds up to {cap} pages", "page_limit", {"max_pages": cap})
        if sum(1 for entry in entries if entry["mode"] == "site") > MAX_SITE_ENTRIES:
            raise WebsiteConfigError(
                f"A website source holds up to {MAX_SITE_ENTRIES} sites", "site_limit", {"max_sites": MAX_SITE_ENTRIES},
            )
        if len(skip) > MAX_SKIP_RULES:
            raise WebsiteConfigError(
                f"A website source holds up to {MAX_SKIP_RULES} skip rules", "skip_limit", {"max_skip": MAX_SKIP_RULES},
            )
        if any(len(rule.removesuffix("*")) > MAX_URL_LENGTH for rule in skip):
            raise WebsiteConfigError(
                f"A skip rule is longer than {MAX_URL_LENGTH} characters", "url_too_long", {"max_length": MAX_URL_LENGTH},
            )
    return {"entries": entries, "skip": skip, "keep_links": bool(raw.get("keep_links"))}


class WebsiteLoader(BaseRemote):
    """Load a Website source's pages and sites into documents."""

    def __init__(self) -> None:
        """Start with an empty report."""
        # What the last load did: its page count, per site how pages were
        # found and whether the page limit cut it short, and whether the limit
        # left anything out at all. Read by the worker for its notice.
        self.report: Dict[str, Any] = {}

    def load_data(self, inputs: Union[str, Dict[str, Any]]) -> List[Document]:
        """Fetch every entry, drop duplicates, and name pages for the file tree.

        Args:
            inputs: The Website config (see ``parse_website_config``).

        Returns:
            One document per page: the pages first, then each site's, in entry
            order. ``WEB_MAX_PAGES`` caps the total, so sites get what the
            pages leave; page entries past it (a stored config read after the
            cap was lowered) are left out in entry order, and ``report``
            says so. Every fetch, discovery included, is charged to one
            budget (``fetch_budget_for``), so failed or non-HTML fetches can't
            multiply across sites; no fetch starts after the load's deadline
            (``load_deadline_for``), and what is left then is reported like
            pages past the limit. Each document's ``requested_urls`` lists
            the other addresses that led to its page (``note_requested_url``):
            entries or links that redirect to a page already loaded are
            merged into its document instead of dropped.
        """
        # A stored config: the write limits don't apply, the fetch budget does.
        config = parse_website_config(inputs, enforce_page_cap=False)
        keep_links = config["keep_links"]
        cap = int(settings.WEB_MAX_PAGES)
        fetches = FetchBudget(fetch_budget_for(cap), deadline=time.monotonic() + load_deadline_for(cap))
        documents: List[Document] = []
        # The document of each page, by page_key.
        seen: Dict[str, Document] = {}
        site_reports = []

        # Page entries the cap left out (a stored config past a lowered cap),
        # and those left when the load ran out of time.
        pages_cut = 0
        pages_late = 0

        entries = sorted(config["entries"], key=lambda entry: entry["mode"] != "page")
        for entry in entries:
            report = None
            if entry["mode"] == "page":
                try:
                    key = page_key(entry["url"])
                except ValueError:
                    logger.warning(f"Skipping unparseable page {entry['url']!r}")
                    continue
                if key in seen:
                    continue
                if len(documents) >= cap:
                    pages_cut += 1
                    continue
                if fetches.deadline is not None and time.monotonic() >= fetches.deadline:
                    pages_late += 1
                    continue
                docs = WebLoader(keep_links=keep_links, budget=fetches).load_data([entry["url"]])
            else:
                pages_left = 0 if fetches.spent() else min(cap - len(documents), fetches.remaining)
                if pages_left < 1:
                    site_reports.append({
                        "url": entry["url"], "found_with": None, "pages": 0, "limit_reached": True,
                    })
                    continue
                docs, report = self._load_site(entry, config["skip"], keep_links, pages_left, fetches)
                site_reports.append(report)
            added = 0
            for doc in docs:
                doc.extra_info.setdefault("requested_urls", [])
                key = page_key(doc.extra_info["source"])
                if key in seen:
                    # The page again (an entry or link that redirects to it):
                    # one document, listing every address that led to it.
                    merge_requested_urls(seen[key], doc)
                    continue
                seen[key] = doc
                documents.append(doc)
                added += 1
            if report is not None:
                # A page already loaded (by a page entry or an earlier site)
                # isn't this site's.
                report["pages"] = added

        if pages_cut:
            logger.info(f"Website load: {pages_cut} page entries left out at the {cap}-page cap")
        if pages_late:
            logger.warning(f"Website load: {pages_late} page entries left out when the load ran out of time")
        # Name pages after the whole load, so one host stays path-only and
        # several hosts get a folder each.
        include_host = spans_multiple_hosts([d.extra_info["source"] for d in documents])
        for doc in documents:
            doc.extra_info["file_path"] = url_to_virtual_path(doc.extra_info["source"], include_host)
        self.report = {
            "pages": len(documents),
            "sites": site_reports,
            # Whether the page limit left anything out: a page entry past the
            # cap or the load's deadline, or a site cut short.
            "limit_reached": bool(pages_cut or pages_late) or any(site["limit_reached"] for site in site_reports),
        }
        return dedupe_virtual_paths(documents)

    @staticmethod
    def _load_site(
        entry: Dict[str, Any], skip: List[str], keep_links: bool, budget: int, fetches: FetchBudget,
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
        limit = max(1, min(_clamp_pages(entry.get("max_pages")), budget))
        scope = SiteScope(url, entry.get("path_prefix", ""), entry.get("include_subdomains", False), skip)
        discovery = entry.get("discovery", "auto")
        pasted_sitemap = is_sitemap_url(url)

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
            loader = CrawlerLoader(scope.accepts, limit=limit, keep_links=keep_links, budget=fetches)
            docs = loader.load_data(url)
            found_with = "links" if docs else None
            limit_reached = loader.limit_reached
        return docs, {"url": url, "found_with": found_with, "pages": len(docs), "limit_reached": limit_reached}
