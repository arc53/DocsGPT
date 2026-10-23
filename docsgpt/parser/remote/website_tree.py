"""Edits to a Website source's file tree and config.

A web page is a leaf of ``directory_structure`` that carries its ``url``
(see ``worker.add_file_to_structure``). Removing pages edits the tree; it also
edits the config, so the next sync doesn't bring them back. Sources created by
the older url/crawler/sitemap loaders are converted to a Website config the
first time they are edited.
"""

import json
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from docsgpt.parser.remote.website_loader import is_sitemap_url, is_web_address, parse_website_config

# The old loaders' fixed page limits, kept when their sources are converted.
_LEGACY_CRAWL_PAGES = 10
_LEGACY_SITEMAP_PAGES = 20

Page = Tuple[str, str]  # (tree path, page URL)


def _is_leaf(node: Any) -> bool:
    """Whether a tree node is a file (it carries a ``token_count``), not a folder."""
    return isinstance(node, dict) and "token_count" in node


def web_pages(structure: Dict[str, Any], prefix: str = "", include_unaddressed: bool = False) -> List[Page]:
    """Every web page in a tree, depth first in stored order.

    Args:
        structure: ``directory_structure``.
        prefix: Path of ``structure`` within the whole tree.
        include_unaddressed: Also list the leaves without a ``url`` (an
            older loader's), with ``""`` for it.

    Returns:
        ``(path, url)`` for each leaf that carries a ``url``, and with
        ``include_unaddressed`` each one that doesn't.
    """
    pages: List[Page] = []
    for name, node in (structure or {}).items():
        path = f"{prefix}/{name}" if prefix else name
        if _is_leaf(node):
            if node.get("url"):
                pages.append((path, node["url"]))
            elif include_unaddressed:
                pages.append((path, ""))
        elif isinstance(node, dict):
            pages.extend(web_pages(node, path, include_unaddressed))
    return pages


def pages_under(structure: Dict[str, Any], dir_path: str, include_unaddressed: bool = False) -> List[Page]:
    """The web pages inside a folder of the tree.

    Args:
        structure: ``directory_structure``.
        dir_path: The folder's path, e.g. ``"Deploying"``.
        include_unaddressed: Also list the leaves without a ``url``, as ``web_pages``.

    Returns:
        ``(path, url)`` for each page in the folder and its subfolders.
    """
    node: Any = structure
    for part in [p for p in dir_path.split("/") if p]:
        node = node.get(part) if isinstance(node, dict) else None
        if node is None or _is_leaf(node):
            return []
    return web_pages(node, dir_path.strip("/"), include_unaddressed)


def remove_pages(structure: Dict[str, Any], paths: List[str]) -> None:
    """Delete leaves from a tree in place, pruning folders left empty.

    Args:
        structure: ``directory_structure``.
        paths: Leaf paths; unknown ones are ignored.
    """
    for path in paths:
        parts = [p for p in path.split("/") if p]
        if not parts:
            continue
        trail = [structure]
        for part in parts[:-1]:
            node = trail[-1].get(part)
            if not isinstance(node, dict) or _is_leaf(node):
                break
            trail.append(node)
        else:
            if _is_leaf(trail[-1].get(parts[-1])):
                del trail[-1][parts[-1]]
                for depth in range(len(trail) - 1, 0, -1):
                    if trail[depth]:
                        break
                    del trail[depth - 1][parts[depth - 1]]


def set_page(structure: Dict[str, Any], path: str, leaf: Dict[str, Any]) -> None:
    """Add or replace a leaf, creating its folders.

    Args:
        structure: ``directory_structure``.
        path: The leaf's path.
        leaf: The leaf (``type``, ``size_bytes``, ``token_count``, ``url``...).
    """
    parts = [p for p in path.split("/") if p]
    node = structure
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict) or _is_leaf(child):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = leaf


def count_pages(structure: Dict[str, Any]) -> int:
    """How many pages a web source's tree holds: its leaves.

    Leaves from before pages carried their ``url`` count too, so an older
    crawler or sitemap source isn't shown as empty.
    """
    count = 0
    for node in (structure or {}).values():
        if _is_leaf(node):
            count += 1
        elif isinstance(node, dict):
            count += count_pages(node)
    return count


def total_tokens(structure: Dict[str, Any]) -> int:
    """Sum of the tree's leaf token counts (the source's ``tokens``)."""
    total = 0
    for node in (structure or {}).values():
        if _is_leaf(node):
            total += int(node.get("token_count") or 0)
        elif isinstance(node, dict):
            total += total_tokens(node)
    return total


def folder_skip_rule(dir_path: str, pages: List[Page]) -> Optional[str]:
    """The section rule (``https://host/path/*``) that covers a folder's pages.

    The tree folder is the URL path (with the host first when the source
    spans hosts), so the rule is rebuilt from a page's URL. A host folder is
    the host as written, and so is the rule's host: ``www.x.io`` and
    ``x.io`` are two folders, and a section rule matches its host exactly
    (``SiteScope``), so removing one folder leaves the other's pages.

    Args:
        dir_path: The folder's tree path.
        pages: The folder's pages (``pages_under``).

    Returns:
        The rule, or ``None`` when the folder doesn't map onto one URL prefix
        (its pages are then skipped one by one).
    """
    parts = [p for p in dir_path.split("/") if p]
    if not pages or not parts:
        return None
    first = urlparse(pages[0][1])
    if parts[0] == first.netloc:
        parts = parts[1:]
    prefix = "/" + "/".join(parts) if parts else ""
    rule_base = f"{first.scheme}://{first.netloc}{prefix}"
    for _, url in pages:
        parsed = urlparse(url)
        if parsed.netloc != first.netloc or not (parsed.path + "/").startswith(prefix + "/"):
            return None
    return rule_base + "/*"


def _urls(remote_data: Any) -> List[str]:
    """The URLs an old url/crawler/sitemap source stored, in any of its shapes.

    Args:
        remote_data: A URL, a list of them, a dict holding one under
            ``url``/``urls``/``raw``, or the JSON of any of these.

    Returns:
        The non-empty URLs, stripped.
    """
    if isinstance(remote_data, str):
        stripped = remote_data.strip()
        if stripped[:1] in ("{", "["):
            try:
                return _urls(json.loads(stripped))
            except json.JSONDecodeError:
                return []
        return [stripped] if stripped else []
    if isinstance(remote_data, list):
        return [u.strip() for u in remote_data if isinstance(u, str) and u.strip()]
    if isinstance(remote_data, dict):
        for key in ("url", "urls", "raw"):
            if remote_data.get(key):
                return _urls(remote_data[key])
    return []


def config_from_legacy(source_type: str, remote_data: Any) -> Optional[Dict[str, Any]]:
    """A Website config for a source, converting the old web loaders.

    Each conversion keeps what the old loader fetched: ``url`` sources become
    page entries; a ``crawler`` source a link-following site of 10 pages; a
    ``sitemap`` source a sitemap-only site of 20 pages with its subdomains in
    scope (a sitemap's pages often sit on one, and the old loader took any
    host it listed), plus a page entry for the address when it isn't named
    like a sitemap (``.xml``/``.xml.gz``), since the old loader loaded an
    address that wasn't a sitemap as a page. A real sitemap fetched as that
    page is XML, which yields no page. Pages a sitemap lists on an unrelated
    domain are the one thing the conversion drops.

    Args:
        source_type: ``sources.type``.
        remote_data: The stored ``remote_data``.

    Returns:
        The validated config, or ``None`` for a source that isn't a web
        source or has nothing to fetch. Never raises: this reads stored rows
        (the Knowledge listing, settings, syncs), so the write limits don't
        apply and an old loader's unparseable URLs are dropped.
    """
    loader = (source_type or "").lower()
    if loader == "website":
        try:
            return parse_website_config(remote_data, enforce_page_cap=False)
        except ValueError:
            return None
    urls = [url for url in _urls(remote_data) if is_web_address(url)]
    if not urls:
        return None
    if loader == "url":
        entries = [{"url": url, "mode": "page"} for url in urls]
    elif loader == "crawler":
        entries = [{"url": urls[0], "mode": "site", "discovery": "links", "max_pages": _LEGACY_CRAWL_PAGES}]
    elif loader == "sitemap":
        # The old loader took every page its sitemap listed and loaded an
        # address that wasn't a sitemap as a page. Sitemaps list pages of
        # their own site, often on a subdomain (x.io/sitemap.xml naming
        # docs.x.io/...), so subdomains stay in scope; and an address not
        # named like a sitemap is also kept as a page entry, which a real
        # sitemap answers with XML that yields no page.
        entries = [{
            "url": urls[0], "mode": "site", "discovery": "sitemap", "include_subdomains": True,
            "max_pages": _LEGACY_SITEMAP_PAGES, "sitemap_url": urls[0],
        }]
        if not is_sitemap_url(urls[0]):
            entries.insert(0, {"url": urls[0], "mode": "page"})
    else:
        return None
    try:
        return parse_website_config({"entries": entries}, enforce_page_cap=False)
    except ValueError:
        return None


def held_pages(config: Dict[str, Any], structure: Any) -> Dict[str, Any]:
    """The pages a Website source holds toward ``WEB_MAX_PAGES``, as the add route counts them.

    Its page entries count from when they are listed (one still queued, or
    one whose fetch failed, keeps its place), and so do the pages in its tree
    (a site's crawl). A page that is both counts once, a redirected one too
    (its entries list the addresses its leaf keeps as ``requested_urls``, or
    an older leaf's ``requested_url``). Leaves without a ``url`` (older
    crawls) count but have no key. The tree is walked without recursion, so
    a deep path can't exhaust the stack.

    Args:
        config: The Website config (``entries`` with ``url`` and ``mode``).
        structure: ``directory_structure``.

    Returns:
        ``{"keys": page keys held, "count": how many pages}``.
    """
    from docsgpt.parser.remote.website_loader import page_key

    def key(url: str) -> str:
        try:
            return page_key(url)
        except ValueError:
            return url

    tree_keys: set = set()
    aliases: set = set()
    unaddressed = 0
    stack = [structure] if isinstance(structure, dict) else []
    while stack:
        node = stack.pop()
        for child in node.values():
            if _is_leaf(child):
                if not child.get("url"):
                    unaddressed += 1
                    continue
                tree_keys.add(key(child["url"]))
                listed = child.get("requested_urls")
                asked = [u for u in listed if isinstance(u, str) and u] if isinstance(listed, list) else []
                if isinstance(child.get("requested_url"), str) and child["requested_url"]:
                    asked.append(child["requested_url"])
                aliases.update(key(address) for address in asked)
            elif isinstance(child, dict):
                stack.append(child)
    asked_keys = aliases - tree_keys
    entry_keys = {key(e["url"]) for e in (config or {}).get("entries") or [] if e.get("mode") == "page"}
    count = len(tree_keys) + len(entry_keys - tree_keys - asked_keys) + unaddressed
    return {"keys": tree_keys | asked_keys | entry_keys, "count": count}
