"""Tests for the Website source: scope rules, sitemap discovery and the loader."""

import gzip
from contextlib import ExitStack
from unittest.mock import patch

import pytest
import requests

from docsgpt.parser.remote.website_loader import SiteScope, WebsiteLoader, discover_sitemaps

HTML = "text/html; charset=utf-8"
XML = "application/xml"


def page(title: str, body: str = "", links=()) -> tuple:
    anchors = "".join(f"<p><a href='{href}'>{href}</a></p>" for href in links)
    text = body or f"{title} has real content about the product, written out in a full sentence."
    return HTML, (
        f"<html><head><title>{title}</title></head><body><main><h1>{title}</h1><p>{text}</p>{anchors}</main>"
        "</body></html>"
    )


def urlset(*pages_) -> tuple:
    locs = "".join(f"<url><loc>{p}</loc></url>" for p in pages_)
    return XML, f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'


def index(*children) -> tuple:
    locs = "".join(f"<sitemap><loc>{c}</loc></sitemap>" for c in children)
    return XML, (
        f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</sitemapindex>'
    )


def robots(*sitemaps) -> tuple:
    return "text/plain", "User-agent: *\nAllow: /\n" + "".join(f"Sitemap: {s}\n" for s in sitemaps)


class FakeWeb:
    """Answers ``pinned_fetch_bytes`` from a URL map; unknown URLs are 404s.

    It keeps the real fetcher's contract: at most ``max_bytes`` of body,
    truncated or refused with ``ResponseTooLargeError``.
    """

    def __init__(self, sites: dict):
        self.sites = sites
        self.fetched = []
        self.limits = {}

    def __call__(self, url, *, max_bytes, headers=None, timeout=10.0, allow_redirects=False, truncate=False):
        from docsgpt.security.safe_url import ResponseTooLargeError

        self.fetched.append(url)
        self.limits[url] = (max_bytes, truncate)
        response = requests.Response()
        response.url = url
        response.reason = "Not Found"
        if url not in self.sites:
            response.status_code = 404
            return b"", response
        content_type, body = self.sites[url]
        if isinstance(content_type, int):
            # A redirect: (status, Location).
            response.status_code = content_type
            response.headers["Location"] = body
            return b"<html><head><title>301 Moved Permanently</title></head></html>", response
        content = body if isinstance(body, bytes) else body.encode()
        if len(content) > max_bytes:
            if not truncate:
                raise ResponseTooLargeError(f"response body exceeds the {max_bytes}-byte limit")
            content = content[:max_bytes]
        response.status_code = 200
        response.headers["Content-Type"] = content_type
        return content, response


@pytest.fixture
def web():
    """Patch the shared fetch with one fake web; DNS answers a public address."""

    def install(sites):
        fake = FakeWeb(sites)
        stack = ExitStack()
        stack.enter_context(patch("docsgpt.parser.remote.page_content.pinned_fetch_bytes", fake))
        stack.enter_context(patch("docsgpt.core.url_validation.resolve_hostname", return_value="93.184.216.34"))
        install.stacks.append(stack)
        return fake

    install.stacks = []
    yield install
    for stack in install.stacks:
        stack.close()


def sources(docs):
    return [d.extra_info["source"] for d in docs]


class TestSiteScope:
    def test_same_host_with_or_without_www(self):
        scope = SiteScope("https://www.example.com/")

        assert scope.accepts("https://www.example.com/a")
        assert scope.accepts("https://example.com/b")
        assert scope.accepts("http://example.com/c")
        assert not scope.accepts("https://other.com/a")
        assert not scope.accepts("ftp://example.com/a")
        assert not scope.accepts("mailto:team@example.com")

    def test_subdomains_only_when_switched_on(self):
        scope = SiteScope("https://example.co.uk/")
        wide = SiteScope("https://example.co.uk/", include_subdomains=True)

        assert not scope.accepts("https://docs.example.co.uk/a")
        assert wide.accepts("https://docs.example.co.uk/a")
        # The registered domain, not a suffix match: another .co.uk site is out.
        assert not wide.accepts("https://other.co.uk/a")
        assert not wide.accepts("https://evilexample.co.uk/a")

    def test_stay_under_a_path(self):
        scope = SiteScope("https://docs.example.com/Deploying/Docker", path_prefix="/Deploying/")

        assert scope.accepts("https://docs.example.com/Deploying/Kubernetes")
        assert not scope.accepts("https://docs.example.com/Agents/basics")
        # Without the trailing slash the section's own page is in too.
        assert SiteScope("https://x.io/", path_prefix="/guides").accepts("https://x.io/guides")

    def test_skip_rules_exact_and_prefix(self):
        scope = SiteScope(
            "https://docs.example.com/",
            skip=["https://docs.example.com/changelog", "https://docs.example.com/Deploying/*"],
        )

        assert not scope.accepts("https://docs.example.com/changelog")
        assert not scope.accepts("https://docs.example.com/changelog/")
        assert not scope.accepts("https://docs.example.com/changelog#v2")
        assert not scope.accepts("https://docs.example.com/Deploying/Kubernetes")
        assert scope.accepts("https://docs.example.com/changelogs")
        # The section's own page sits beside its folder (Deploying.md), so
        # removing the folder leaves it.
        assert scope.accepts("https://docs.example.com/Deploying")

    def test_a_host_folder_rule_covers_the_host_root_page(self):
        # A removed host folder in a multi-host source holds host/index.md.
        scope = SiteScope("https://a.io/", skip=["https://b.io/*"], include_subdomains=False)
        wide = SiteScope("https://a.io/", skip=["https://a.io/*"])

        assert not wide.accepts("https://a.io/")
        assert not wide.accepts("https://a.io")
        assert not wide.accepts("https://a.io/?lang=de")
        assert not wide.accepts("https://a.io/docs")
        assert scope.accepts("https://a.io/")
        assert not SiteScope("https://b.io/", skip=["https://b.io/*"]).accepts("https://b.io/")

    def test_a_section_rule_covers_only_its_own_host_folder(self):
        # The tree has a folder per host as written, www. included: removing
        # the www.a.io folder must leave the a.io folder's pages alone.
        www_removed = SiteScope("https://a.io/", skip=["https://www.a.io/*", "https://www.a.io/blog/*"])
        bare_removed = SiteScope("https://a.io/", skip=["https://a.io/docs/*"])

        assert not www_removed.accepts("https://www.a.io/guide")
        assert not www_removed.accepts("https://www.a.io/")
        assert www_removed.accepts("https://a.io/guide")
        assert www_removed.accepts("https://a.io/blog/post")
        assert not bare_removed.accepts("https://a.io/docs/x")
        assert bare_removed.accepts("https://www.a.io/docs/x")
        # A page rule names the page itself, which www. doesn't change.
        assert not SiteScope("https://a.io/", skip=["https://www.a.io/p"]).accepts("https://a.io/p")

    @pytest.mark.parametrize(
        "start, other, own",
        [
            ("https://alice.github.io/", "https://mallory.github.io/x", "https://docs.alice.github.io/x"),
            ("https://foo.vercel.app/", "https://bar.vercel.app/x", "https://preview.foo.vercel.app/x"),
            ("https://myapp.herokuapp.com/", "https://evil.herokuapp.com/x", "https://api.myapp.herokuapp.com/x"),
        ],
    )
    def test_subdomains_never_cross_a_shared_hosting_suffix(self, start, other, own):
        # github.io and friends are public suffixes too (the private part of
        # the list): each tenant is its own registered domain.
        scope = SiteScope(start, include_subdomains=True)

        assert not scope.accepts(other)
        assert scope.accepts(own)

    def test_the_suffix_list_is_read_offline(self):
        from docsgpt.parser.remote import website_loader

        with patch("requests.Session.send", side_effect=AssertionError("no network")):
            assert website_loader._registered_domain("a.b.github.io") == "b.github.io"


class TestDiscoverSitemaps:
    def test_reads_sitemap_lines_from_robots_txt(self, web):
        web({"https://www.example.com/robots.txt": robots("https://www.example.com/sitemap.xml")})

        assert discover_sitemaps("https://www.example.com/docs/") == ["https://www.example.com/sitemap.xml"]

    def test_falls_back_to_well_known_locations(self, web):
        web({
            "https://example.com/robots.txt": ("text/plain", "User-agent: *\nAllow: /\n"),
            "https://example.com/sitemap_index.xml": index("https://example.com/sitemap-0.xml"),
        })

        assert discover_sitemaps("https://example.com/") == ["https://example.com/sitemap_index.xml"]

    def test_an_html_page_at_sitemap_xml_is_not_a_sitemap(self, web):
        # Soft 404s: the app answers every path with its HTML shell.
        web({"https://example.com/sitemap.xml": page("Not found")})

        assert discover_sitemaps("https://example.com/") == []


class TestWebsiteLoaderPages:
    def test_fetches_each_page_once(self, web):
        web({
            "https://docs.example.com/a": page("A"),
            "https://docs.example.com/b": page("B"),
        })
        loader = WebsiteLoader()
        docs = loader.load_data({"entries": [
            {"url": "https://docs.example.com/a", "mode": "page"},
            {"url": "https://docs.example.com/b", "mode": "page"},
            {"url": "https://docs.example.com/a#intro", "mode": "page"},
        ]})

        assert sources(docs) == ["https://docs.example.com/a", "https://docs.example.com/b"]
        assert [d.extra_info["file_path"] for d in docs] == ["a.md", "b.md"]
        assert docs[0].extra_info["title"] == "A"

    def test_pages_on_two_hosts_get_host_folders(self, web):
        web({"https://a.io/x": page("X"), "https://b.io/y": page("Y")})
        docs = WebsiteLoader().load_data({"entries": [
            {"url": "https://a.io/x", "mode": "page"}, {"url": "https://b.io/y", "mode": "page"},
        ]})

        assert [d.extra_info["file_path"] for d in docs] == ["a.io/x.md", "b.io/y.md"]


class TestWebsiteLoaderSites:
    SITEMAP_SITE = {
        "https://www.example.com/robots.txt": robots("https://www.example.com/sitemap.xml"),
        "https://www.example.com/sitemap.xml": index("https://www.example.com/sitemap-0.xml"),
        "https://www.example.com/sitemap-0.xml": urlset(
            "https://www.example.com/",
            "https://www.example.com/blog/one",
            "https://www.example.com/blog/two",
            "https://www.example.com/product/agents",
            "https://other.com/elsewhere",
        ),
        "https://www.example.com/": page("Home"),
        "https://www.example.com/blog/one": page("One"),
        "https://www.example.com/blog/two": page("Two"),
        "https://www.example.com/product/agents": page("Agents"),
    }

    def test_automatic_follows_a_sitemap_index_top_to_bottom(self, web):
        fake = web(self.SITEMAP_SITE)
        loader = WebsiteLoader()
        docs = loader.load_data({"entries": [{"url": "https://www.example.com/", "mode": "site", "max_pages": 3}]})

        assert sources(docs) == [
            "https://www.example.com/",
            "https://www.example.com/blog/one",
            "https://www.example.com/blog/two",
        ]
        assert "https://www.example.com/product/agents" not in fake.fetched
        assert loader.report["sites"][0]["found_with"] == "sitemap"
        assert loader.report["sites"][0]["limit_reached"] is True

    def test_skips_and_other_hosts_are_filtered_before_the_limit(self, web):
        web(self.SITEMAP_SITE)
        docs = WebsiteLoader().load_data({
            "entries": [{"url": "https://www.example.com/", "mode": "site", "max_pages": 3}],
            "skip": ["https://www.example.com/blog/*"],
        })

        assert sources(docs) == ["https://www.example.com/", "https://www.example.com/product/agents"]

    def test_stay_under_applies_to_sitemap_pages(self, web):
        web(self.SITEMAP_SITE)
        docs = WebsiteLoader().load_data({"entries": [
            {"url": "https://www.example.com/blog/", "mode": "site", "path_prefix": "/blog/"},
        ]})

        assert sources(docs) == ["https://www.example.com/blog/one", "https://www.example.com/blog/two"]

    def test_a_pasted_sitemap_url_is_used_as_the_sitemap(self, web):
        fake = web(self.SITEMAP_SITE)
        docs = WebsiteLoader().load_data({"entries": [
            {"url": "https://www.example.com/sitemap-0.xml", "mode": "site", "max_pages": 2},
        ]})

        assert sources(docs) == ["https://www.example.com/", "https://www.example.com/blog/one"]
        assert "https://www.example.com/robots.txt" not in fake.fetched

    def test_gzipped_sitemap_is_read(self, web):
        web({
            "https://x.io/robots.txt": robots("https://x.io/sitemap.xml.gz"),
            "https://x.io/sitemap.xml.gz": ("application/gzip", gzip.compress(urlset("https://x.io/p")[1].encode())),
            "https://x.io/p": page("P"),
        })
        docs = WebsiteLoader().load_data({"entries": [{"url": "https://x.io/", "mode": "site"}]})

        assert sources(docs) == ["https://x.io/p"]

    def test_without_a_sitemap_it_follows_links(self, web):
        web({
            "https://x.io/": page("Home", links=["/guide", "https://other.com/out"]),
            "https://x.io/guide": page("Guide", links=["/"]),
        })
        loader = WebsiteLoader()
        docs = loader.load_data({"entries": [{"url": "https://x.io/", "mode": "site"}]})

        assert sorted(sources(docs)) == ["https://x.io/", "https://x.io/guide"]
        assert loader.report["sites"][0]["found_with"] == "links"
        assert loader.report["sites"][0]["limit_reached"] is False

    def test_follow_links_respects_scope_and_skips(self, web):
        web({
            "https://x.io/docs/": page("Docs", links=["/docs/a", "/docs/b", "/blog/c"]),
            "https://x.io/docs/a": page("A"),
            "https://x.io/docs/b": page("B"),
            "https://x.io/blog/c": page("C"),
        })
        docs = WebsiteLoader().load_data({
            "entries": [{"url": "https://x.io/docs/", "mode": "site", "discovery": "links", "path_prefix": "/docs/"}],
            "skip": ["https://x.io/docs/b"],
        })

        assert sorted(sources(docs)) == ["https://x.io/docs/", "https://x.io/docs/a"]

    def test_an_out_of_scope_start_page_is_followed_but_not_kept(self, web):
        fake = web({
            "https://x.io/": page("Home", links=["/docs/a", "/blog/b"]),
            "https://x.io/docs/a": page("A"),
            "https://x.io/blog/b": page("B"),
        })
        docs = WebsiteLoader().load_data({"entries": [
            {"url": "https://x.io/", "mode": "site", "discovery": "links", "path_prefix": "/docs"},
        ]})

        assert sources(docs) == ["https://x.io/docs/a"]
        assert "https://x.io/" in fake.fetched

    def test_an_out_of_scope_start_page_does_not_use_up_the_page_limit(self, web):
        fake = web({
            "https://x.io/": page("Home", links=["/docs/a", "/docs/b"]),
            "https://x.io/docs/a": page("A"),
            "https://x.io/docs/b": page("B"),
        })
        loader = WebsiteLoader()
        docs = loader.load_data({"entries": [
            {"url": "https://x.io/", "mode": "site", "discovery": "links", "path_prefix": "/docs", "max_pages": 1},
        ]})

        assert sources(docs) == ["https://x.io/docs/a"]
        assert loader.report["sites"][0]["limit_reached"] is True
        # The start page is still a fetch.
        assert fake.fetched[0] == "https://x.io/"

    def test_a_skipped_start_page_is_not_reimported(self, web):
        web({
            "https://x.io/": page("Home", links=["/a"]),
            "https://x.io/a": page("A"),
        })
        docs = WebsiteLoader().load_data({
            "entries": [{"url": "https://x.io/", "mode": "site", "discovery": "links"}],
            "skip": ["https://x.io/"],
        })

        assert sources(docs) == ["https://x.io/a"]

    def test_page_limit_is_clamped_to_the_admin_cap(self, web):
        links = [f"/p{i}" for i in range(10)]
        sites = {"https://x.io/": page("Home", links=links)}
        sites.update({f"https://x.io/p{i}": page(f"P{i}") for i in range(10)})
        web(sites)
        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 3
            fake_settings.WEB_DEFAULT_PAGES = 2
            docs = WebsiteLoader().load_data({"entries": [{"url": "https://x.io/", "mode": "site", "max_pages": 50}]})
            default = WebsiteLoader().load_data({"entries": [{"url": "https://x.io/", "mode": "site"}]})

        assert len(docs) == 3
        assert len(default) == 2

    def test_the_admin_cap_covers_the_whole_source(self, web):
        links = [f"/p{i}" for i in range(10)]
        sites = {"https://x.io/": page("Home", links=links), "https://y.io/a": page("Y")}
        sites.update({f"https://x.io/p{i}": page(f"P{i}") for i in range(10)})
        web(sites)
        loader = WebsiteLoader()
        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 3
            fake_settings.WEB_DEFAULT_PAGES = 2
            # The page is listed after the site but is kept: added pages
            # come first, and the site gets what is left.
            docs = loader.load_data({"entries": [
                {"url": "https://x.io/", "mode": "site", "max_pages": 50},
                {"url": "https://y.io/a", "mode": "page"},
            ]})

        assert len(docs) == 3
        assert "https://y.io/a" in sources(docs)
        assert loader.report["sites"][0]["limit_reached"] is True

    def test_sites_share_the_admin_cap(self, web):
        sites = {}
        for host in ("x.io", "z.io"):
            sites[f"https://{host}/"] = page("Home", links=[f"/p{i}" for i in range(5)])
            sites.update({f"https://{host}/p{i}": page(f"P{i}") for i in range(5)})
        web(sites)
        loader = WebsiteLoader()
        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 4
            fake_settings.WEB_DEFAULT_PAGES = 4
            docs = loader.load_data({"entries": [
                {"url": "https://x.io/", "mode": "site", "max_pages": 3},
                {"url": "https://z.io/", "mode": "site", "max_pages": 3},
            ]})

        assert len(docs) == 4
        assert [s["pages"] for s in loader.report["sites"]] == [3, 1]
        assert loader.report["sites"][1]["limit_reached"] is True

    def test_keep_links_reaches_the_extractor(self, web):
        web({"https://x.io/a": page("A", body="Read the <a href='https://ref.io/spec'>spec</a> before you start.")})
        plain = WebsiteLoader().load_data({"entries": [{"url": "https://x.io/a", "mode": "page"}]})
        linked = WebsiteLoader().load_data({"entries": [{"url": "https://x.io/a", "mode": "page"}], "keep_links": True})

        assert "](" not in plain[0].text
        assert "[spec](https://ref.io/spec)" in linked[0].text


class TestParseWebsiteConfig:
    def test_fills_site_defaults_and_accepts_json(self):
        from docsgpt.parser.remote.website_loader import parse_website_config

        config = parse_website_config(
            '{"entries": [{"url": " https://x.io/ ", "mode": "site"}], "skip": ["", "https://x.io/a"]}'
        )

        assert config == {
            "entries": [{
                "url": "https://x.io/", "mode": "site", "max_pages": None, "path_prefix": "",
                "include_subdomains": False, "discovery": "auto", "sitemap_url": None,
            }],
            "skip": ["https://x.io/a"],
            "keep_links": False,
        }

    def test_a_page_entry_keeps_only_its_url(self):
        from docsgpt.parser.remote.website_loader import parse_website_config

        config = parse_website_config({"entries": [{"url": "https://x.io/a", "max_pages": 9}]})

        assert config["entries"] == [{"url": "https://x.io/a", "mode": "page"}]

    def test_rejects_more_pages_than_the_admin_cap(self):
        from docsgpt.parser.remote.website_loader import parse_website_config

        entries = [{"url": f"https://x.io/{i}", "mode": "page"} for i in range(3)]
        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 2
            with pytest.raises(ValueError, match="up to 2 pages"):
                parse_website_config({"entries": entries})
            assert len(parse_website_config({"entries": entries[:2]})["entries"]) == 2

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "not json",
            {"entries": []},
            {"entries": [{"mode": "page"}]},
            {"entries": [{"url": "https://x.io", "mode": "crawl"}]},
            {"entries": [{"url": "https://x.io", "mode": "site", "discovery": "magic"}]},
            {"entries": [{"url": "https://x.io", "mode": "site", "max_pages": 0}]},
            {"entries": [{"url": "https://x.io", "mode": "site", "max_pages": "50"}]},
            {"entries": [{"url": "https://x.io", "mode": "site", "max_pages": True}]},
        ],
    )
    def test_rejects_malformed_configs(self, raw):
        from docsgpt.parser.remote.website_loader import parse_website_config

        with pytest.raises(ValueError):
            parse_website_config(raw)

    @pytest.mark.parametrize(
        "url",
        [
            "http://[x",
            "ftp://x.io/a",
            "https://",
            "javascript:alert(1)",
            "https://x.io:99999/",
            "https://x.io/" + "a" * 2100,
        ],
    )
    def test_rejects_an_entry_url_that_is_not_a_web_address(self, url):
        from docsgpt.parser.remote.website_loader import parse_website_config

        with pytest.raises(ValueError):
            parse_website_config({"entries": [{"url": url, "mode": "page"}]})

    def test_rejects_a_sitemap_url_that_is_not_a_web_address(self):
        from docsgpt.parser.remote.website_loader import parse_website_config

        with pytest.raises(ValueError):
            parse_website_config({"entries": [{"url": "https://x.io/", "mode": "site", "sitemap_url": "http://[x"}]})

    def test_an_address_without_a_scheme_gets_https(self):
        from docsgpt.parser.remote.website_loader import parse_website_config

        config = parse_website_config({
            "entries": [
                {"url": "x.io/docs", "mode": "page"},
                {"url": " y.io ", "mode": "site", "sitemap_url": "y.io/sitemap.xml"},
                {"url": "http://z.io/", "mode": "page"},
            ],
            "skip": ["y.io/old", "y.io/blog/*", "https://y.io/a"],
        })

        assert config["entries"][0] == {"url": "https://x.io/docs", "mode": "page"}
        assert config["entries"][1]["url"] == "https://y.io"
        assert config["entries"][1]["sitemap_url"] == "https://y.io/sitemap.xml"
        assert config["entries"][2]["url"] == "http://z.io/"
        assert config["skip"] == ["https://y.io/old", "https://y.io/blog/*", "https://y.io/a"]

    def test_a_stored_scheme_less_site_still_has_a_host(self, web):
        web({"https://x.io/docs": page("Docs", links=["/docs/a"]), "https://x.io/docs/a": page("A")})

        docs = WebsiteLoader().load_data({"entries": [{"url": "x.io/docs", "mode": "site", "discovery": "links"}]})

        assert sorted(sources(docs)) == ["https://x.io/docs", "https://x.io/docs/a"]

    def test_caps_sites_entries_and_skip_rules_on_write(self):
        from docsgpt.parser.remote import website_loader
        from docsgpt.parser.remote.website_loader import parse_website_config

        sites = [{"url": f"https://s{i}.io/", "mode": "site"} for i in range(website_loader.MAX_SITE_ENTRIES + 1)]
        with pytest.raises(ValueError, match="sites"):
            parse_website_config({"entries": sites})

        one = [{"url": "https://x.io/", "mode": "site"}]
        rules = [f"https://x.io/p{i}" for i in range(website_loader.MAX_SKIP_RULES + 1)]
        with pytest.raises(ValueError, match="skip"):
            parse_website_config({"entries": one, "skip": rules})
        with pytest.raises(ValueError, match="skip"):
            parse_website_config({"entries": one, "skip": ["https://x.io/" + "a" * 2100]})

        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 2
            mixed = [{"url": "https://x.io/a", "mode": "page"}, {"url": "https://x.io/", "mode": "site"}]
            assert len(parse_website_config({"entries": mixed})["entries"]) == 2
            with pytest.raises(ValueError, match="up to 2"):
                parse_website_config({"entries": mixed + [{"url": "https://y.io/", "mode": "site"}]})

    def test_a_stored_config_reads_past_the_write_limits(self):
        # Reads are lenient: a lowered WEB_MAX_PAGES, or a config that grew
        # past a limit, must not lock the source or break its listing.
        from docsgpt.parser.remote import website_loader
        from docsgpt.parser.remote.website_loader import parse_website_config

        pages = [{"url": f"https://x.io/{i}", "mode": "page"} for i in range(3)]
        sites = [{"url": f"https://s{i}.io/", "mode": "site"} for i in range(website_loader.MAX_SITE_ENTRIES + 1)]
        rules = [f"https://x.io/p{i}" for i in range(website_loader.MAX_SKIP_RULES + 1)]
        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 2
            config = parse_website_config({"entries": pages + sites, "skip": rules}, enforce_page_cap=False)

        assert len(config["entries"]) == 3 + len(sites)
        assert len(config["skip"]) == len(rules)

    def test_a_stored_config_with_a_bad_url_still_fails(self):
        from docsgpt.parser.remote.website_loader import parse_website_config

        with pytest.raises(ValueError):
            parse_website_config({"entries": [{"url": "http://[x", "mode": "page"}]}, enforce_page_cap=False)


class TestWebsiteConfigErrors:
    """Each refusal carries a code and its numbers, for the API to hand the UI."""

    def _error(self, raw, **kwargs):
        from docsgpt.parser.remote.website_loader import WebsiteConfigError, parse_website_config

        with pytest.raises(WebsiteConfigError) as caught:
            parse_website_config(raw, **kwargs)
        assert isinstance(caught.value, ValueError)
        return caught.value

    def test_limits(self):
        from docsgpt.parser.remote import website_loader

        one = [{"url": "https://x.io/", "mode": "site"}]
        sites = [{"url": f"https://s{i}.io/", "mode": "site"} for i in range(website_loader.MAX_SITE_ENTRIES + 1)]
        error = self._error({"entries": sites})
        assert (error.code, error.details) == ("site_limit", {"max_sites": website_loader.MAX_SITE_ENTRIES})
        assert str(error) == f"A website source holds up to {website_loader.MAX_SITE_ENTRIES} sites"

        rules = [f"https://x.io/p{i}" for i in range(website_loader.MAX_SKIP_RULES + 1)]
        error = self._error({"entries": one, "skip": rules})
        assert (error.code, error.details) == ("skip_limit", {"max_skip": website_loader.MAX_SKIP_RULES})

        for raw in (
            {"entries": [{"url": "https://x.io/" + "a" * 2100, "mode": "page"}]},
            {"entries": [{"url": "https://x.io/", "mode": "site", "sitemap_url": "https://x.io/" + "a" * 2100}]},
            {"entries": one, "skip": ["https://x.io/" + "a" * 2100]},
        ):
            error = self._error(raw)
            assert (error.code, error.details) == ("url_too_long", {"max_length": website_loader.MAX_URL_LENGTH})

        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 2
            error = self._error({"entries": [{"url": f"https://x.io/{i}", "mode": "page"} for i in range(3)]})
        assert (error.code, error.details) == ("page_limit", {"max_pages": 2})
        assert str(error) == "A website source holds up to 2 pages"

    @pytest.mark.parametrize("url", ["http://[x", "ftp://x.io/a", "javascript:alert(1)"])
    def test_invalid_address(self, url):
        error = self._error({"entries": [{"url": f"  {url} ", "mode": "page"}]})

        assert (error.code, error.details) == ("invalid_address", {"url": url})

    def test_an_invalid_sitemap_address(self):
        error = self._error({"entries": [{"url": "https://x.io/", "mode": "site", "sitemap_url": "http://[x"}]})

        assert (error.code, error.details) == ("invalid_address", {"url": "http://[x"})

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "not json",
            [],
            {"entries": "x"},
            {"entries": []},
            {"entries": [{"mode": "page"}]},
            {"entries": [{"url": "https://x.io", "mode": "crawl"}]},
            {"entries": [{"url": "https://x.io", "mode": "site", "discovery": "magic"}]},
            {"entries": [{"url": "https://x.io", "mode": "site", "max_pages": 0}]},
        ],
    )
    def test_every_other_refusal_is_invalid_config(self, raw):
        error = self._error(raw)

        assert (error.code, error.details) == ("invalid_config", {})

    def test_a_stored_config_still_raises_typed_errors(self):
        error = self._error({"entries": [{"url": "http://[x", "mode": "page"}]}, enforce_page_cap=False)

        assert error.code == "invalid_address"


class TestWebsiteLoaderLenientRead:
    def test_a_lowered_cap_does_not_fail_the_load(self, web):
        web({f"https://x.io/{i}": page(f"P{i}") for i in range(3)})
        loader = WebsiteLoader()
        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 2
            fake_settings.WEB_DEFAULT_PAGES = 2
            docs = loader.load_data({"entries": [{"url": f"https://x.io/{i}", "mode": "page"} for i in range(3)]})

        # The stored config still reads, but the cap holds: page entries are
        # taken in order and the cut is reported.
        assert sources(docs) == ["https://x.io/0", "https://x.io/1"]
        assert loader.report["pages"] == 2
        assert loader.report["limit_reached"] is True

    def test_a_load_within_the_cap_is_not_reported_as_cut(self, web):
        web({"https://x.io/a": page("A")})
        loader = WebsiteLoader()
        loader.load_data({"entries": [{"url": "https://x.io/a", "mode": "page"}]})

        assert loader.report["limit_reached"] is False


class TestRedirects:
    def test_a_page_entry_is_stored_under_the_address_it_redirects_to(self, web):
        web({"https://x.io/docs": (301, "/docs/"), "https://x.io/docs/": page("Real docs")})

        docs = WebsiteLoader().load_data({"entries": [{"url": "https://x.io/docs", "mode": "page"}]})

        assert sources(docs) == ["https://x.io/docs/"]
        assert docs[0].extra_info["title"] == "Real docs"
        assert "Moved" not in docs[0].text

    def test_a_redirect_without_a_location_is_not_indexed(self, web):
        web({"https://x.io/docs": (302, "")})

        assert WebsiteLoader().load_data({"entries": [{"url": "https://x.io/docs", "mode": "page"}]}) == []

    def test_a_crawl_drops_a_page_that_redirects_out_of_scope(self, web):
        web({
            "https://x.io/docs/": page("Docs", links=["/docs/a", "/docs/b", "/docs/c"]),
            "https://x.io/docs/a": (301, "https://login.other.io/sso"),
            "https://login.other.io/sso": page("Sign in"),
            "https://x.io/docs/b": (301, "/blog/b"),
            "https://x.io/blog/b": page("Blog B"),
            "https://x.io/docs/c": (308, "/docs/c/"),
            "https://x.io/docs/c/": page("C"),
        })

        docs = WebsiteLoader().load_data({"entries": [
            {"url": "https://x.io/docs/", "mode": "site", "discovery": "links", "path_prefix": "/docs"},
        ]})

        assert sources(docs) == ["https://x.io/docs/", "https://x.io/docs/c/"]

    def test_a_crawl_does_not_load_a_redirect_target_twice(self, web):
        fake = web({
            "https://x.io/": page("Home", links=["/old", "/new"]),
            "https://x.io/old": (301, "/new"),
            "https://x.io/new": page("New"),
        })

        docs = WebsiteLoader().load_data({"entries": [{"url": "https://x.io/", "mode": "site", "discovery": "links"}]})

        assert sources(docs) == ["https://x.io/", "https://x.io/new"]
        assert fake.fetched.count("https://x.io/new") == 1

    def test_a_skip_rule_applies_to_where_a_page_redirects(self, web):
        web({
            "https://x.io/sitemap.xml": urlset("https://x.io/a", "https://x.io/b"),
            "https://x.io/a": (301, "https://x.io/changelog"),
            "https://x.io/changelog": page("Changelog"),
            "https://x.io/b": page("B"),
        })

        docs = WebsiteLoader().load_data({
            "entries": [{"url": "https://x.io/", "mode": "site", "sitemap_url": "https://x.io/sitemap.xml"}],
            "skip": ["https://x.io/changelog"],
        })

        assert sources(docs) == ["https://x.io/b"]

    def test_robots_and_sitemaps_follow_redirects(self, web):
        web({
            "http://x.io/robots.txt": (301, "https://x.io/robots.txt"),
            "https://x.io/robots.txt": robots("http://x.io/sitemap.xml"),
            "http://x.io/sitemap.xml": (301, "https://x.io/sitemap.xml"),
            "https://x.io/sitemap.xml": urlset("https://x.io/a"),
            "https://x.io/a": page("A"),
        })
        loader = WebsiteLoader()

        docs = loader.load_data({"entries": [{"url": "http://x.io/", "mode": "site"}]})

        assert sources(docs) == ["https://x.io/a"]
        assert loader.report["sites"][0]["found_with"] == "sitemap"

    def test_a_relative_robots_sitemap_line_is_resolved(self, web):
        web({"https://x.io/robots.txt": robots("/maps/sitemap.xml", "https://x.io/other.xml")})

        assert discover_sitemaps("https://x.io/docs/") == ["https://x.io/maps/sitemap.xml", "https://x.io/other.xml"]


class TestWebsiteLoaderDedupe:
    def test_sitemap_duplicates_and_variants_do_not_use_up_the_limit(self, web):
        fake = web({
            "https://x.io/sitemap.xml": urlset(
                "https://x.io/p0", "https://x.io/p0", "https://x.io/p0/", "https://x.io/p1",
                "https://x.io/p1#x", "https://www.x.io/p1", "https://x.io/p2", "https://x.io/p3",
            ),
            **{f"https://x.io/p{i}": page(f"P{i}") for i in range(4)},
        })
        loader = WebsiteLoader()
        docs = loader.load_data({"entries": [
            {"url": "https://x.io/", "mode": "site", "sitemap_url": "https://x.io/sitemap.xml", "max_pages": 4},
        ]})

        assert sources(docs) == [f"https://x.io/p{i}" for i in range(4)]
        assert loader.report["sites"][0]["limit_reached"] is False
        assert [u for u in fake.fetched if "/p" in u] == [f"https://x.io/p{i}" for i in range(4)]

    def test_a_site_reports_only_the_pages_it_added(self, web):
        web({
            "https://x.io/sitemap.xml": urlset("https://x.io/a", "https://x.io/b"),
            "https://x.io/a": page("A"),
            "https://x.io/b": page("B"),
        })
        loader = WebsiteLoader()
        docs = loader.load_data({"entries": [
            {"url": "https://x.io/a", "mode": "page"},
            {"url": "https://x.io/", "mode": "site", "sitemap_url": "https://x.io/sitemap.xml"},
        ]})

        assert sources(docs) == ["https://x.io/a", "https://x.io/b"]
        assert loader.report["pages"] == 2
        assert loader.report["sites"][0]["pages"] == 1


class TestPlainTextPages:
    def test_a_plain_text_page_entry_ingests(self, web):
        web({
            "https://x.io/llms.txt": ("text/plain; charset=utf-8", "# X\n\nX is a product.\n"),
            "https://x.io/api.json": ("application/json", '{"version": 2}'),
        })
        docs = WebsiteLoader().load_data({"entries": [
            {"url": "https://x.io/llms.txt", "mode": "page"},
            {"url": "https://x.io/api.json", "mode": "page"},
        ]})

        assert sources(docs) == ["https://x.io/llms.txt", "https://x.io/api.json"]
        assert docs[0].text == "# X\n\nX is a product."

    def test_a_crawl_keeps_plain_text_but_follows_no_links_from_it(self, web):
        fake = web({
            "https://x.io/": page("Home", links=["/notes.md", "/data.json"]),
            "https://x.io/notes.md": ("text/markdown", "# Notes\n\n<a href='/hidden'>hidden</a> and [x](/other)\n"),
            "https://x.io/data.json": ("application/json", '{"a": 1}'),
            "https://x.io/hidden": page("Hidden"),
            "https://x.io/other": page("Other"),
        })
        docs = WebsiteLoader().load_data({"entries": [{"url": "https://x.io/", "mode": "site", "discovery": "links"}]})

        assert sorted(sources(docs)) == ["https://x.io/", "https://x.io/notes.md"]
        assert "https://x.io/hidden" not in fake.fetched
        assert "https://x.io/other" not in fake.fetched


class TestBoundedFetching:
    def test_a_page_is_read_only_up_to_the_markup_cap(self, web):
        filler = "<p>" + "word " * 200 + "</p>"
        fake = web({
            "https://x.io/": page("Home", body=filler + "<a href='/late'>late</a>"),
            "https://x.io/late": page("Late"),
        })
        with patch("docsgpt.parser.remote.page_content.settings") as fake_settings:
            fake_settings.MARKUP_MAX_BYTES = 300
            docs = WebsiteLoader().load_data(
                {"entries": [{"url": "https://x.io/", "mode": "site", "discovery": "links"}]}
            )

        # The link sits past the cap, so the crawl never sees it.
        assert sources(docs) == ["https://x.io/"]
        assert fake.limits["https://x.io/"] == (301, True)
        assert "https://x.io/late" not in fake.fetched

    def test_robots_and_sitemaps_are_size_capped(self, web):
        from docsgpt.parser.remote.sitemap_loader import MAX_SITEMAP_BYTES

        fake = web({
            "https://x.io/robots.txt": robots("https://x.io/sitemap.xml"),
            "https://x.io/sitemap.xml": urlset("https://x.io/p"),
            "https://x.io/p": page("P"),
        })
        WebsiteLoader().load_data({"entries": [{"url": "https://x.io/", "mode": "site"}]})

        robots_cap, _ = fake.limits["https://x.io/robots.txt"]
        assert robots_cap <= 512 * 1024
        assert fake.limits["https://x.io/sitemap.xml"] == (MAX_SITEMAP_BYTES, False)

    def test_an_oversized_sitemap_is_skipped(self, web):
        with patch("docsgpt.parser.remote.sitemap_loader.MAX_SITEMAP_BYTES", 50):
            web({
                "https://x.io/robots.txt": robots("https://x.io/sitemap.xml"),
                "https://x.io/sitemap.xml": urlset("https://x.io/p", "https://x.io/q"),
                "https://x.io/": page("Home"),
            })
            loader = WebsiteLoader()
            docs = loader.load_data({"entries": [{"url": "https://x.io/", "mode": "site"}]})

        # No usable sitemap: Automatic falls back to following links.
        assert loader.report["sites"][0]["found_with"] == "links"
        assert sources(docs) == ["https://x.io/"]

    def test_robots_sitemap_lines_are_capped(self, web):
        from docsgpt.parser.remote.website_loader import MAX_ROBOTS_SITEMAPS

        listed = [f"https://x.io/s{i}.xml" for i in range(MAX_ROBOTS_SITEMAPS + 5)]
        web({"https://x.io/robots.txt": robots(*listed)})

        assert discover_sitemaps("https://x.io/") == listed[:MAX_ROBOTS_SITEMAPS]

    def test_dead_sites_share_one_fetch_budget(self, web):
        # Every site lists pages that aren't HTML: no documents, so a budget
        # that only shrinks for documents would let each site fetch its fill.
        from docsgpt.parser.remote import website_loader

        sites = {}
        entries = []
        for i in range(20):
            host = f"https://h{i}.io"
            sites[f"{host}/robots.txt"] = robots(f"{host}/sitemap.xml")
            sites[f"{host}/sitemap.xml"] = urlset(*[f"{host}/f{j}.pdf" for j in range(10)])
            sites.update({f"{host}/f{j}.pdf": ("application/pdf", b"%PDF-1.4") for j in range(10)})
            entries.append({"url": f"{host}/", "mode": "site", "discovery": "sitemap"})
        fake = web(sites)
        loader = WebsiteLoader()
        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 5
            fake_settings.WEB_DEFAULT_PAGES = 5
            docs = loader.load_data({"entries": entries})

        assert docs == []
        assert len(fake.fetched) <= website_loader.fetch_budget_for(5)
        assert len(fake.fetched) < 20 * 7
        assert loader.report["sites"][-1]["limit_reached"] is True

    def test_child_sitemaps_per_walk_are_capped(self, web):
        from docsgpt.parser.remote.sitemap_loader import MAX_SITEMAPS_PER_WALK

        children = [f"https://x.io/c{i}.xml" for i in range(MAX_SITEMAPS_PER_WALK + 30)]
        sites = {"https://x.io/index.xml": index(*children)}
        # Empty children: the page budget never stops the walk on its own.
        sites.update({child: urlset() for child in children})
        fake = web(sites)
        from docsgpt.parser.remote.sitemap_loader import SitemapLoader

        SitemapLoader(limit=100).collect_urls(["https://x.io/index.xml"])

        assert len(fake.fetched) == MAX_SITEMAPS_PER_WALK

    def test_a_nested_entry_that_is_not_a_sitemap_is_not_a_page(self, web):
        # A hostile index lists pages as child sitemaps: they must not reach
        # the source past scope and skips.
        web({
            "https://x.io/robots.txt": robots("https://x.io/sitemap.xml"),
            "https://x.io/sitemap.xml": index("https://evil.io/page", "https://x.io/skipped", "https://x.io/s0.xml"),
            "https://evil.io/page": page("Evil"),
            "https://x.io/skipped": page("Skipped"),
            "https://x.io/s0.xml": urlset("https://x.io/ok"),
            "https://x.io/ok": page("OK"),
        })
        docs = WebsiteLoader().load_data({
            "entries": [{"url": "https://x.io/", "mode": "site"}],
            "skip": ["https://x.io/skipped"],
        })

        assert sources(docs) == ["https://x.io/ok"]

    def test_exactly_the_limit_is_not_reported_as_cut_short(self, web):
        web({
            "https://x.io/robots.txt": robots("https://x.io/sitemap.xml"),
            "https://x.io/sitemap.xml": urlset("https://x.io/a", "https://x.io/b"),
            "https://x.io/a": page("A"),
            "https://x.io/b": page("B"),
        })
        exact = WebsiteLoader()
        exact.load_data({"entries": [{"url": "https://x.io/", "mode": "site", "max_pages": 2}]})
        short = WebsiteLoader()
        docs = short.load_data({"entries": [{"url": "https://x.io/", "mode": "site", "max_pages": 1}]})

        assert exact.report["sites"][0] == {"url": "https://x.io/", "found_with": "sitemap", "pages": 2,
                                            "limit_reached": False}
        assert short.report["sites"][0]["limit_reached"] is True
        assert sources(docs) == ["https://x.io/a"]
