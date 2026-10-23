"""Tests for the Website source's tree and config edits."""

from unittest.mock import patch

import pytest

from docsgpt.parser.remote.sitemap_loader import SitemapLoader
from docsgpt.parser.remote.website_loader import WebsiteLoader
from docsgpt.parser.remote.website_tree import (
    config_from_legacy,
    folder_skip_rule,
    pages_under,
    remove_pages,
    set_page,
    total_tokens,
    web_pages,
)
from tests.parser.remote.test_website_loader import page, sources, urlset


def leaf(url, tokens=10, title=None):
    return {"type": "text/markdown", "size_bytes": 40, "token_count": tokens, "url": url, "title": title or url}


TREE = {
    "index.md": leaf("https://docs.x.io/", 5),
    "Deploying": {
        "Docker.md": leaf("https://docs.x.io/Deploying/Docker", 20),
        "Kubernetes.md": leaf("https://docs.x.io/Deploying/Kubernetes", 30),
    },
    "changelog.md": leaf("https://docs.x.io/changelog", 7),
}


def tree():
    import copy

    return copy.deepcopy(TREE)


class TestTree:
    def test_web_pages_lists_every_page_with_its_path(self):
        assert web_pages(tree()) == [
            ("index.md", "https://docs.x.io/"),
            ("Deploying/Docker.md", "https://docs.x.io/Deploying/Docker"),
            ("Deploying/Kubernetes.md", "https://docs.x.io/Deploying/Kubernetes"),
            ("changelog.md", "https://docs.x.io/changelog"),
        ]

    def test_pages_under_a_folder(self):
        assert pages_under(tree(), "Deploying") == [
            ("Deploying/Docker.md", "https://docs.x.io/Deploying/Docker"),
            ("Deploying/Kubernetes.md", "https://docs.x.io/Deploying/Kubernetes"),
        ]
        assert pages_under(tree(), "Nope") == []

    def test_leaves_without_an_address_are_listed_on_request(self):
        # An older crawl's leaves carry no ``url``: listed with "" so a removal can name them.
        old_leaf = {"type": "application/octet-stream", "size_bytes": 10, "token_count": 5}
        structure = {**tree(), "old.md": old_leaf, "Deploying": {**TREE["Deploying"], "Helm.md": old_leaf}}

        assert ("old.md", "") not in web_pages(structure)
        assert web_pages(structure, include_unaddressed=True)[-1] == ("old.md", "")
        assert pages_under(structure, "Deploying", include_unaddressed=True) == [
            ("Deploying/Docker.md", "https://docs.x.io/Deploying/Docker"),
            ("Deploying/Kubernetes.md", "https://docs.x.io/Deploying/Kubernetes"),
            ("Deploying/Helm.md", ""),
        ]
        assert ("Deploying/Helm.md", "") not in pages_under(structure, "Deploying")

    def test_remove_pages_prunes_empty_folders(self):
        structure = tree()
        remove_pages(structure, ["Deploying/Docker.md", "Deploying/Kubernetes.md", "missing.md"])

        assert "Deploying" not in structure
        assert total_tokens(structure) == 12

    def test_set_page_creates_folders_and_replaces_a_leaf(self):
        structure = tree()
        set_page(structure, "Agents/basics.md", leaf("https://docs.x.io/Agents/basics", 9))
        set_page(structure, "index.md", leaf("https://docs.x.io/", 6))

        assert structure["Agents"]["basics.md"]["token_count"] == 9
        assert total_tokens(structure) == 9 + 6 + 20 + 30 + 7


class TestRemovalRules:
    def test_a_folder_becomes_one_section_rule(self):
        pages = pages_under(tree(), "Deploying")

        assert folder_skip_rule("Deploying", pages) == "https://docs.x.io/Deploying/*"

    def test_a_host_folder_keeps_the_host_out_of_the_path(self):
        pages = [("docs.x.io/Deploying/Docker.md", "https://docs.x.io/Deploying/Docker")]

        assert folder_skip_rule("docs.x.io/Deploying", pages) == "https://docs.x.io/Deploying/*"
        assert folder_skip_rule("docs.x.io", pages) == "https://docs.x.io/*"

    def test_removing_a_www_host_folder_leaves_the_bare_host_folder(self):
        from docsgpt.parser.remote.website_loader import SiteScope

        structure = {
            "www.x.io": {"guide.md": leaf("https://www.x.io/guide")},
            "x.io": {"blog": {"post.md": leaf("https://x.io/blog/post")}},
        }
        rule = folder_skip_rule("www.x.io", pages_under(structure, "www.x.io"))
        scope = SiteScope("https://x.io/", skip=[rule])

        assert rule == "https://www.x.io/*"
        assert not scope.accepts("https://www.x.io/guide")
        assert scope.accepts("https://x.io/blog/post")
        bare = folder_skip_rule("x.io/blog", pages_under(structure, "x.io/blog"))
        assert SiteScope("https://x.io/", skip=[bare]).accepts("https://www.x.io/guide")

    def test_a_folder_whose_name_is_not_in_its_urls_has_no_rule(self):
        # A folder name a URL can't account for (a dedupe suffix, say) gets
        # its pages skipped one by one instead.
        assert folder_skip_rule("Other", [("Other/a.md", "https://x.io/somewhere/a")]) is None


class TestLegacyConfig:
    @pytest.mark.parametrize(
        "source_type, remote_data, expected",
        [
            ("url", "https://x.io/a", [{"url": "https://x.io/a", "mode": "page"}]),
            # Older rows stored the address itself, not JSON.
            ("crawler", "https://x.io/",
             [{"url": "https://x.io/", "mode": "site", "discovery": "links", "max_pages": 10}]),
            ("sitemap", "https://x.io/sitemap.xml",
             [{"url": "https://x.io/sitemap.xml", "mode": "site", "discovery": "sitemap", "max_pages": 20}]),
            ("url", {"urls": ["https://x.io/a", "https://x.io/b"]},
             [{"url": "https://x.io/a", "mode": "page"}, {"url": "https://x.io/b", "mode": "page"}]),
            ("crawler", {"url": "https://x.io/"},
             [{"url": "https://x.io/", "mode": "site", "discovery": "links", "max_pages": 10}]),
            ("sitemap", {"url": "https://x.io/sitemap.xml"},
             [{"url": "https://x.io/sitemap.xml", "mode": "site", "discovery": "sitemap", "max_pages": 20,
               "sitemap_url": "https://x.io/sitemap.xml", "include_subdomains": True}]),
            # Not named like a sitemap: it may be a page, as the old loader took it.
            ("sitemap", {"url": "https://x.io/guide"},
             [{"url": "https://x.io/guide", "mode": "page"},
              {"url": "https://x.io/guide", "mode": "site", "discovery": "sitemap", "max_pages": 20,
               "sitemap_url": "https://x.io/guide", "include_subdomains": True}]),
        ],
    )
    def test_converts_the_old_loaders_with_their_old_limits(self, source_type, remote_data, expected):
        config = config_from_legacy(source_type, remote_data)

        assert [{k: v for k, v in e.items() if k in expected[i]} for i, e in enumerate(config["entries"])] == expected
        assert config["skip"] == []

    def test_a_website_config_passes_through(self):
        config = config_from_legacy("website", {"entries": [{"url": "https://x.io/", "mode": "site"}]})

        assert config["entries"][0]["mode"] == "site"

    def test_nothing_to_convert(self):
        assert config_from_legacy("crawler", None) is None
        assert config_from_legacy("github", {"repo_url": "https://github.com/a/b"}) is None

    def test_a_legacy_url_source_over_the_cap_still_reads(self):
        urls = [f"https://x.io/{i}" for i in range(3)]
        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 2
            config = config_from_legacy("url", {"urls": urls})

        assert [e["url"] for e in config["entries"]] == urls

    def test_a_website_source_over_a_lowered_cap_still_reads(self):
        stored = {"entries": [{"url": f"https://x.io/{i}", "mode": "page"} for i in range(3)]}
        with patch("docsgpt.parser.remote.website_loader.settings") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 2
            config = config_from_legacy("website", stored)

        assert config is not None and len(config["entries"]) == 3

    def test_a_legacy_source_drops_malformed_urls_without_raising(self):
        config = config_from_legacy("url", {"urls": ["http://[x", "https://x.io/a"]})

        assert [e["url"] for e in config["entries"]] == ["https://x.io/a"]
        assert config_from_legacy("url", "http://[x") is None
        assert config_from_legacy("crawler", {"url": "http://[x"}) is None
        assert config_from_legacy("website", {"entries": [{"url": "http://[x", "mode": "page"}]}) is None


class TestLegacySitemapLoadsWhatItLoaded:
    """A converted sitemap source fetches the pages the old sitemap loader did."""

    def test_pages_a_sitemap_lists_on_a_subdomain_stay(self, web):
        web({
            "https://x.io/sitemap.xml": urlset("https://docs.x.io/a", "https://docs.x.io/b", "https://x.io/c"),
            "https://docs.x.io/a": page("A"),
            "https://docs.x.io/b": page("B"),
            "https://x.io/c": page("C"),
        })
        legacy = SitemapLoader().load_data("https://x.io/sitemap.xml")

        converted = WebsiteLoader().load_data(config_from_legacy("sitemap", "https://x.io/sitemap.xml"))

        assert sources(converted) == sources(legacy) == ["https://docs.x.io/a", "https://docs.x.io/b", "https://x.io/c"]

    def test_an_address_that_is_a_page_is_loaded_as_one(self, web):
        web({"https://x.io/guide": page("Guide", links=["/other"]), "https://x.io/other": page("Other")})
        legacy = SitemapLoader().load_data("https://x.io/guide")

        converted = WebsiteLoader().load_data(config_from_legacy("sitemap", "https://x.io/guide"))

        assert sources(converted) == sources(legacy) == ["https://x.io/guide"]

    def test_a_sitemap_without_an_xml_name_is_not_also_a_page(self, web):
        web({"https://x.io/sitemap": urlset("https://x.io/a"), "https://x.io/a": page("A")})

        converted = WebsiteLoader().load_data(config_from_legacy("sitemap", "https://x.io/sitemap"))

        assert sources(converted) == ["https://x.io/a"]
