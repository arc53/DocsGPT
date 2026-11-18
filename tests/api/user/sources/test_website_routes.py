"""Tests for the Website source routes: settings and page removal."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.sources import SourcesRepository

USER = "u-web"


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.sources.website.db_session", _yield), patch(
        "docsgpt.api.user.sources.website.db_readonly", _yield
    ):
        yield


def _leaf(url, tokens):
    return {"type": "text/markdown", "size_bytes": 10, "token_count": tokens, "url": url, "title": url}


TREE = {
    "index.md": _leaf("https://docs.x.io/", 5),
    "Deploying": {
        "Docker.md": _leaf("https://docs.x.io/Deploying/Docker", 20),
        "Kubernetes.md": _leaf("https://docs.x.io/Deploying/Kubernetes", 30),
    },
    "extra.md": _leaf("https://docs.x.io/extra", 7),
}
CONFIG = {
    "entries": [
        {"url": "https://docs.x.io/", "mode": "site"},
        {"url": "https://docs.x.io/extra", "mode": "page"},
    ],
    "skip": [],
}


GUIDE = {"url": "https://docs.x.io/", "mode": "site", "path_prefix": "/guide/", "max_pages": 30}
# Two addresses that redirect to one page.
ALIASES = ["https://docs.x.io/old-a", "https://docs.x.io/old-b"]


def _seed(pg_conn, **kwargs):
    fields = {
        "type": "website",
        "remote_data": CONFIG,
        "directory_structure": TREE,
        "tokens": "62",
        "sync_frequency": "weekly",
        "metadata": {"website": {"pages": 4, "sites": [{"url": "https://docs.x.io/", "limit_reached": False}]}},
    }
    fields.update(kwargs)
    return SourcesRepository(pg_conn).create("Docs", user_id=USER, **fields)


def _call(app, pg_conn, resource, method, *, json=None, query=""):
    from flask import request

    with _patch_db(pg_conn), app.test_request_context(f"/api/website{query}", method=method, json=json):
        request.decoded_token = {"sub": USER}
        return getattr(resource(), method.lower())()


def test_redirect_aliases_remain_readable_in_a_deep_legacy_tree():
    """Refresh and removal can resolve aliases beyond Python's recursion limit."""
    import sys

    from docsgpt.api.user.sources.website import _requested_urls
    from docsgpt.parser.remote.website_tree import set_page

    path = "/".join(["folder"] * (sys.getrecursionlimit() + 100)) + "/page.md"
    structure = {}
    set_page(structure, path, {
        **_leaf("https://docs.x.io/new", 3),
        "requested_urls": [
            "https://docs.x.io/old", "https://www.docs.x.io/old/#intro",
            "https://docs.x.io/new/", None, "https://docs.x.io/older",
        ],
    })

    assert _requested_urls(structure) == {
        path: ["https://docs.x.io/old", "https://docs.x.io/older"],
    }


class TestGetWebsite:
    def test_returns_401_unauthenticated(self, app):
        from flask import request

        from docsgpt.api.user.sources.website import WebsiteSettings

        with app.test_request_context("/api/website?id=x", method="GET"):
            request.decoded_token = None
            assert WebsiteSettings().get().status_code == 401

    def test_returns_the_config_schedule_and_report(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn)
        response = _call(app, pg_conn, WebsiteSettings, "GET", query=f"?id={src['id']}")

        assert response.status_code == 200
        body = response.json
        assert body["config"]["entries"][0]["discovery"] == "auto"
        assert body["sync_frequency"] == "weekly"
        assert body["report"]["pages"] == 4
        assert body["legacy"] is False

    def test_lists_the_tree_paths_of_page_entries(self, app, pg_conn):
        # The Remove dialog calls these entries, and the rest pages a site's crawl found.
        from docsgpt.api.user.sources.website import WebsiteSettings

        redirected = {**_leaf("https://docs.x.io/new", 3), "requested_urls": ["https://docs.x.io/old"]}
        tree = {**TREE, "new.md": redirected, "legacy.md": {"type": "text/markdown", "token_count": 1}}
        config = {**CONFIG, "entries": CONFIG["entries"] + [{"url": "https://www.docs.x.io/old/", "mode": "page"}]}
        src = _seed(pg_conn, remote_data=config, directory_structure=tree)
        response = _call(app, pg_conn, WebsiteSettings, "GET", query=f"?id={src['id']}")

        assert response.status_code == 200
        assert sorted(response.json["entry_paths"]) == ["extra.md", "new.md"]

    def test_a_legacy_crawler_source_reads_as_a_website(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn, type="crawler", remote_data={"url": "https://docs.x.io/"}, metadata={})
        response = _call(app, pg_conn, WebsiteSettings, "GET", query=f"?id={src['id']}")

        assert response.status_code == 200
        assert response.json["legacy"] is True
        assert response.json["config"]["entries"][0]["discovery"] == "links"

    def test_someone_elses_source_is_404(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = SourcesRepository(pg_conn).create("Theirs", user_id="other", type="website", remote_data=CONFIG)
        response = _call(app, pg_conn, WebsiteSettings, "GET", query=f"?id={src['id']}")

        assert response.status_code == 404


class TestSaveWebsite:
    def test_saves_entries_skips_links_and_schedule(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn)
        response = _call(app, pg_conn, WebsiteSettings, "POST", json={
            "source_id": str(src["id"]),
            "entries": [{"url": "https://docs.x.io/", "mode": "site", "max_pages": 40}],
            "skip": [],
            "keep_links": True,
            "sync_frequency": "monthly",
        })

        assert response.status_code == 200
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert saved["remote_data"]["entries"][0]["max_pages"] == 40
        assert saved["remote_data"]["keep_links"] is True
        assert saved["sync_frequency"] == "monthly"

    def test_a_page_given_twice_is_stored_once(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn)
        response = _call(app, pg_conn, WebsiteSettings, "POST", json={
            "source_id": str(src["id"]),
            "entries": [
                {"url": "https://docs.x.io/", "mode": "site"},
                {"url": "https://docs.x.io/extra", "mode": "page"},
                {"url": "https://docs.x.io/extra/", "mode": "page"},
                {"url": "https://www.docs.x.io/extra#a", "mode": "page"},
            ],
        })

        assert response.status_code == 200, response.json
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]
        assert [e["url"] for e in saved] == ["https://docs.x.io/", "https://docs.x.io/extra"]
        assert response.json["config"]["entries"] == saved

    def test_a_site_limit_past_the_page_cap_is_cut_to_it(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn)
        with patch("docsgpt.core.settings.settings.WEB_MAX_PAGES", 50):
            response = _call(app, pg_conn, WebsiteSettings, "POST", json={
                "source_id": str(src["id"]),
                "entries": [{"url": "https://docs.x.io/", "mode": "site", "max_pages": 10**15}],
            })

        assert response.status_code == 200, response.json
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"][0]["max_pages"] == 50

    def test_a_new_path_past_the_length_limit_is_refused(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn)
        response = _call(app, pg_conn, WebsiteSettings, "POST", json={
            "source_id": str(src["id"]),
            "entries": [{"url": "https://docs.x.io/", "mode": "site", "path_prefix": "/" + "a" * 50000}],
        })

        assert response.status_code == 400
        assert response.json["code"] == "url_too_long"
        assert response.json["max_length"] == 2048
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"] == CONFIG

    def test_saving_a_legacy_source_upgrades_it(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn, type="sitemap", remote_data={"url": "https://docs.x.io/sitemap.xml"})
        response = _call(app, pg_conn, WebsiteSettings, "POST", json={
            "source_id": str(src["id"]),
            "entries": [{"url": "https://docs.x.io/sitemap.xml", "mode": "site"}],
        })

        assert response.status_code == 200
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["type"] == "website"

    @pytest.mark.parametrize("body, code", [
        ({"entries": []}, "invalid_config"),
        ({"entries": [{"url": "https://x.io"}], "sync_frequency": "hourly"}, "bad_sync_frequency"),
    ])
    def test_rejects_bad_input(self, app, pg_conn, body, code):
        src = _seed(pg_conn)
        response, _, _ = _post(app, pg_conn, "WebsiteSettings", src, **body)

        assert response.status_code == 400
        assert response.json["code"] == code
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"] == CONFIG

    def test_a_save_without_skip_or_keep_links_keeps_them(self, app, pg_conn):
        # As PATCH /sources/<id>/config: a key left out keeps its stored value.
        from docsgpt.api.user.sources.website import WebsiteSettings

        stored = {**CONFIG, "skip": ["https://docs.x.io/old/*"], "keep_links": True}
        src = _seed(pg_conn, remote_data=stored)
        response = _call(app, pg_conn, WebsiteSettings, "POST", json={
            "source_id": str(src["id"]), "entries": CONFIG["entries"], "sync_frequency": "daily",
        })

        assert response.status_code == 200
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]
        assert saved["skip"] == ["https://docs.x.io/old/*"]
        assert saved["keep_links"] is True
        assert response.json["config"]["skip"] == ["https://docs.x.io/old/*"]

    def test_an_empty_skip_and_keep_links_false_clear_them(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn, remote_data={**CONFIG, "skip": ["https://docs.x.io/old/*"], "keep_links": True})
        response = _call(app, pg_conn, WebsiteSettings, "POST", json={
            "source_id": str(src["id"]), "entries": CONFIG["entries"], "skip": [], "keep_links": False,
        })

        assert response.status_code == 200
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]
        assert saved["skip"] == []
        assert saved["keep_links"] is False


LONG_URL = "https://docs.x.io/" + "a" * 2100


def _post(app, pg_conn, resource: str, src, **body):
    """POST ``body`` for ``src`` to a website route, with both tasks mocked."""
    from docsgpt.api.user.sources import website

    with patch("docsgpt.api.user.sources.website.website_pages") as pages_task, patch(
        "docsgpt.api.user.sources.website.sync_source"
    ) as sync_task:
        pages_task.delay.return_value = MagicMock(id="pages-task")
        sync_task.delay.return_value = MagicMock(id="sync-task")
        response = _call(
            app, pg_conn, getattr(website, resource), "POST", json={"source_id": str(src["id"]), **body}
        )
    return response, pages_task, sync_task


class TestWritesRefuseBadValues:
    """A save checks every address it adds as strictly as /api/website/pages does.

    It parses without the write limits (so a stored config past one still
    saves), so what the change adds is checked here: an address with
    ``user:password@`` credentials or a malformed host, and a control
    character in an address, path or skip rule (a NUL can't even be stored).
    """

    SITE = {"url": "https://docs.x.io/", "mode": "site"}

    @pytest.mark.parametrize("entry", [
        {"url": "https://user:secret@evil.io/p", "mode": "page"},
        {"url": "https://a..b/p", "mode": "page"},
        {"url": "https://docs.x.io/a\u0000b", "mode": "page"},
        {"url": "https://docs.x.io/a\u0001b", "mode": "page"},
        {**SITE, "sitemap_url": "https://bob:pw@docs.x.io/sitemap.xml"},
        {"url": "https://alice:s3cret@docs.x.io/", "mode": "site"},
        {"url": "https://docs.x.io" + "/a" * 65, "mode": "page"},
    ])
    def test_a_save_refuses_a_new_address_that_isnt_one(self, app, pg_conn, entry):
        src = _seed(pg_conn)
        response, _, _ = _post(app, pg_conn, "WebsiteSettings", src, entries=[self.SITE, entry])

        assert response.status_code == 400, response.json
        assert response.json["code"] == "invalid_address"
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"] == CONFIG

    @pytest.mark.parametrize("body, code", [
        ({"entries": [{**SITE, "path_prefix": "/a\u0000"}]}, "invalid_config"),
        ({"entries": [SITE], "skip": ["https://docs.x.io/a\u0000"]}, "invalid_address"),
        ({"entries": [SITE], "skip": ["https://docs.x.io/a\u0007/*"]}, "invalid_address"),
        # One the parse would strip off the ends is refused all the same.
        ({"entries": [SITE], "skip": ["https://docs.x.io/a\n"]}, "invalid_address"),
        ({"entries": [SITE], "skip": ["\u001fhttps://docs.x.io/a"]}, "invalid_address"),
    ])
    def test_a_save_refuses_a_control_character_in_a_path_or_rule(self, app, pg_conn, body, code):
        src = _seed(pg_conn)
        response, _, _ = _post(app, pg_conn, "WebsiteSettings", src, **body)

        assert response.status_code == 400, response.json
        assert response.json["code"] == code
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"] == CONFIG

    def test_a_resent_body_keeps_a_stored_path_and_rules(self, app, pg_conn):
        stored = {"entries": [{**self.SITE, "path_prefix": "/guide/"}], "skip": ["https://docs.x.io/guide/old/*"]}
        src = _seed(pg_conn, remote_data=stored)
        response, _, _ = _post(app, pg_conn, "WebsiteSettings", src, **stored)

        assert response.status_code == 200, response.json
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]
        assert saved["entries"][0]["path_prefix"] == "/guide/"
        assert saved["skip"] == stored["skip"]

    def test_adding_a_site_with_a_control_character_in_its_path_is_refused(self, app, pg_conn):
        src = _seed(pg_conn)
        response, _, sync_task = _post(
            app, pg_conn, "AddWebsitePages", src, entries=[{**self.SITE, "path_prefix": "/a\u0000"}]
        )

        assert response.status_code == 400, response.json
        assert response.json["code"] == "invalid_config"
        sync_task.delay.assert_not_called()

    def test_a_source_id_with_a_nul_is_not_found(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        response = _call(app, pg_conn, WebsiteSettings, "POST", json={
            "source_id": "abc\u0000", "entries": [self.SITE],
        })

        assert response.status_code == 404
        assert _call(app, pg_conn, WebsiteSettings, "GET", query="?id=abc%00").status_code == 404

    def test_a_stored_address_a_save_keeps_is_not_checked_again(self, app, pg_conn):
        # Stored before the rule: the source still saves, and can drop it.
        old = {"url": "https://user:pw@docs.x.io/old", "mode": "page"}
        src = _seed(pg_conn, remote_data={**CONFIG, "entries": CONFIG["entries"] + [old]})
        response, _, _ = _post(
            app, pg_conn, "WebsiteSettings", src, entries=CONFIG["entries"] + [old], sync_frequency="daily"
        )

        assert response.status_code == 200, response.json
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["sync_frequency"] == "daily"


class TestOldDataPastAWriteLimit:
    """A write limit refuses a change that grows past it, not one that keeps what is already stored.

    A source can hold more than a limit allows: the admin lowered
    ``WEB_MAX_PAGES``, or it was saved before a limit existed. Its owner can
    still shrink it and save it unchanged.
    """

    SEVEN = CONFIG["entries"] + [{"url": f"https://docs.x.io/p{i}", "mode": "page"} for i in range(5)]

    @pytest.fixture
    def cap_of_five(self):
        with patch("docsgpt.core.settings.settings.WEB_MAX_PAGES", 5):
            yield

    def test_a_removal_works_once_the_page_cap_is_lowered(self, app, pg_conn, cap_of_five):
        src = _seed(pg_conn, remote_data={**CONFIG, "entries": self.SEVEN})
        response, pages_task, _ = _post(app, pg_conn, "RemoveWebsitePages", src, file_paths=["extra.md"])

        assert response.status_code == 200, response.json
        pages_task.delay.assert_called_once()
        assert len(SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]) == 6

    def test_a_removal_works_with_an_old_address_past_the_length_limit(self, app, pg_conn):
        src = _seed(pg_conn, remote_data={**CONFIG, "entries": CONFIG["entries"] + [{"url": LONG_URL}]})
        response, pages_task, _ = _post(app, pg_conn, "RemoveWebsitePages", src, file_paths=["extra.md"])

        assert response.status_code == 200, response.json
        pages_task.delay.assert_called_once()

    def test_a_crawled_page_with_a_long_address_can_be_removed(self, app, pg_conn):
        """Its skip rule is built from the address the crawl stored, so the length limit doesn't apply."""
        src = _seed(pg_conn, directory_structure={**TREE, "long.md": _leaf(LONG_URL, 3)})
        response, pages_task, _ = _post(app, pg_conn, "RemoveWebsitePages", src, file_paths=["long.md"])

        assert response.status_code == 200, response.json
        pages_task.delay.assert_called_once()
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["skip"] == [LONG_URL]

    def test_a_folder_with_a_long_address_can_be_removed(self, app, pg_conn):
        long_dir = "a" * 2100
        tree = {**TREE, long_dir: {"x.md": _leaf(f"https://docs.x.io/{long_dir}/x", 3)}}
        src = _seed(pg_conn, directory_structure=tree)
        response, pages_task, _ = _post(app, pg_conn, "RemoveWebsitePages", src, directory_path=long_dir)

        assert response.status_code == 200, response.json
        pages_task.delay.assert_called_once()
        skip = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["skip"]
        assert skip == [f"https://docs.x.io/{long_dir}/*"]

    def test_a_settings_save_still_refuses_a_new_long_rule(self, app, pg_conn):
        src = _seed(pg_conn)
        response, _, _ = _post(app, pg_conn, "WebsiteSettings", src, entries=CONFIG["entries"], skip=[LONG_URL])

        assert response.status_code == 400
        assert response.json["code"] == "url_too_long"
        assert response.json["max_length"] == 2048

    def test_a_settings_save_keeps_an_old_path_past_the_length_limit(self, app, pg_conn):
        long_prefix = "/" + "a" * 2100
        entries = [{"url": "https://docs.x.io/", "mode": "site", "path_prefix": long_prefix}]
        src = _seed(pg_conn, remote_data={**CONFIG, "entries": entries})
        kept, _, _ = _post(app, pg_conn, "WebsiteSettings", src, entries=entries, keep_links=True)
        added, _, _ = _post(app, pg_conn, "WebsiteSettings", src, entries=entries + [
            {"url": "https://blog.x.io/", "mode": "site", "path_prefix": long_prefix + "b"},
        ])

        assert kept.status_code == 200, kept.json
        assert added.status_code == 400
        assert added.json["code"] == "url_too_long"
        assert added.json["max_length"] == 2048
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]
        assert [e["url"] for e in saved["entries"]] == ["https://docs.x.io/"]

    def test_a_removal_that_adds_no_rule_works_past_the_skip_limit(self, app, pg_conn):
        stored = {**CONFIG, "skip": ["https://docs.x.io/old", "https://docs.x.io/extra"]}
        src = _seed(pg_conn, remote_data=stored)
        with patch("docsgpt.parser.remote.website_loader.MAX_SKIP_RULES", 1):
            response, _, _ = _post(app, pg_conn, "RemoveWebsitePages", src, file_paths=["extra.md"])

        assert response.status_code == 200, response.json

    def test_a_settings_save_works_once_the_page_cap_is_lowered(self, app, pg_conn, cap_of_five):
        src = _seed(pg_conn, remote_data={**CONFIG, "entries": self.SEVEN})
        unchanged, _, _ = _post(app, pg_conn, "WebsiteSettings", src, entries=self.SEVEN, keep_links=True)
        grown, _, _ = _post(
            app, pg_conn, "WebsiteSettings", src, entries=self.SEVEN + [{"url": "https://docs.x.io/new"}]
        )

        assert unchanged.status_code == 200, unchanged.json
        assert grown.status_code == 400
        assert grown.json["code"] == "page_limit"
        assert grown.json["max_pages"] == 5
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]
        assert len(saved["entries"]) == 7
        assert saved["keep_links"] is True

    def test_a_settings_save_keeps_an_old_address_past_the_length_limit(self, app, pg_conn):
        entries = CONFIG["entries"] + [{"url": LONG_URL, "mode": "page"}]
        src = _seed(pg_conn, remote_data={**CONFIG, "entries": entries})
        kept, _, _ = _post(app, pg_conn, "WebsiteSettings", src, entries=entries)
        added, _, _ = _post(
            app, pg_conn, "WebsiteSettings", src, entries=entries + [{"url": LONG_URL + "b", "mode": "page"}]
        )

        assert kept.status_code == 200, kept.json
        assert added.status_code == 400
        assert added.json["code"] == "url_too_long"
        assert added.json["max_length"] == 2048

    def test_a_settings_save_keeps_skip_rules_past_the_limit(self, app, pg_conn):
        skip = ["https://docs.x.io/old", LONG_URL]
        src = _seed(pg_conn, remote_data={**CONFIG, "skip": skip})
        with patch("docsgpt.parser.remote.website_loader.MAX_SKIP_RULES", 1):
            kept, _, _ = _post(app, pg_conn, "WebsiteSettings", src, entries=CONFIG["entries"], skip=skip)
            grown, _, _ = _post(
                app, pg_conn, "WebsiteSettings", src,
                entries=CONFIG["entries"], skip=skip + ["https://docs.x.io/new"],
            )

        assert kept.status_code == 200, kept.json
        assert grown.status_code == 400
        assert grown.json["code"] == "skip_limit"
        assert grown.json["max_skip"] == 1

    @pytest.mark.parametrize("limit, field, stored, sent", [
        # 7 pages past a cap of 5, replaced by 6 new ones.
        (
            "docsgpt.core.settings.settings.WEB_MAX_PAGES", "entries", SEVEN,
            [{"url": f"https://docs.x.io/new{i}", "mode": "page"} for i in range(6)],
        ),
        # 3 sites past a limit of 1, replaced by 2 new ones.
        (
            "docsgpt.parser.remote.website_loader.MAX_SITE_ENTRIES", "entries",
            [{"url": f"https://s{i}.x.io/", "mode": "site"} for i in range(3)],
            [{"url": f"https://t{i}.x.io/", "mode": "site"} for i in range(2)],
        ),
        # 3 skip rules past a limit of 1, replaced by 2 new ones.
        (
            "docsgpt.parser.remote.website_loader.MAX_SKIP_RULES", "skip",
            [f"https://docs.x.io/old{i}" for i in range(3)], [f"https://docs.x.io/gone{i}" for i in range(2)],
        ),
    ])
    def test_a_save_that_replaces_values_without_growing_past_a_limit_works(
        self, app, pg_conn, limit, field, stored, sent,
    ):
        # Only a count larger than the stored one is refused, however many of its values are new.
        cap = 5 if limit.endswith("WEB_MAX_PAGES") else 1
        src = _seed(pg_conn, remote_data={**CONFIG, field: stored})
        body = {"entries": CONFIG["entries"], field: sent}
        with patch(limit, cap):
            response, _, _ = _post(app, pg_conn, "WebsiteSettings", src, **body)

        assert response.status_code == 200, response.json
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"][field]
        assert [value["url"] if field == "entries" else value for value in saved] == [
            value["url"] if field == "entries" else value for value in sent
        ]

    def test_a_settings_save_keeps_sites_past_the_limit(self, app, pg_conn):
        sites = [{"url": "https://docs.x.io/", "mode": "site"}, {"url": "https://blog.x.io/", "mode": "site"}]
        src = _seed(pg_conn, remote_data={**CONFIG, "entries": sites})
        with patch("docsgpt.parser.remote.website_loader.MAX_SITE_ENTRIES", 1):
            kept, _, _ = _post(app, pg_conn, "WebsiteSettings", src, entries=sites)
            grown, _, _ = _post(
                app, pg_conn, "WebsiteSettings", src, entries=sites + [{"url": "https://api.x.io/", "mode": "site"}]
            )

        assert kept.status_code == 200, kept.json
        assert grown.status_code == 400
        assert grown.json["code"] == "site_limit"
        assert grown.json["max_sites"] == 1

    def test_adding_a_page_works_with_old_data_past_a_limit(self, app, pg_conn):
        stored = {
            **CONFIG,
            "entries": CONFIG["entries"] + [{"url": LONG_URL, "mode": "page"}],
            "skip": ["https://docs.x.io/old", "https://docs.x.io/older"],
        }
        src = _seed(pg_conn, remote_data=stored)
        with patch("docsgpt.parser.remote.website_loader.MAX_SKIP_RULES", 1):
            response, pages_task, _ = _post(
                app, pg_conn, "AddWebsitePages", src, entries=[{"url": "https://docs.x.io/new", "mode": "page"}]
            )

        assert response.status_code == 200, response.json
        pages_task.delay.assert_called_once()


class TestRemovePages:
    """The route checks the removal and saves its skip rules; the worker deletes the pages."""

    def _remove(self, app, pg_conn, src, **body):
        from docsgpt.api.user.sources.website import RemoveWebsitePages

        with patch("docsgpt.api.user.sources.website.website_pages") as pages_task, patch(
            "docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore"
        ) as create_store:
            pages_task.delay.return_value = MagicMock(id="remove-task")
            response = _call(app, pg_conn, RemoveWebsitePages, "POST", json={"source_id": str(src["id"]), **body})
        # No chunk is touched in the request: the worker deletes them.
        create_store.assert_not_called()
        self.pages_task = pages_task
        return response

    def test_a_page_added_by_address_leaves_the_list(self, app, pg_conn):
        src = _seed(pg_conn)
        response = self._remove(app, pg_conn, src, file_paths=["extra.md"])

        assert response.status_code == 200
        assert response.json["task_id"] == "remove-task"
        # The worker finds each page by its URL, so a sync that moved it meanwhile doesn't matter.
        self.pages_task.delay.assert_called_once_with(
            str(src["id"]), USER, "remove",
            pages=[{"path": "extra.md", "url": "https://docs.x.io/extra", "requested_urls": []}],
            actor_id=USER,
        )
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert [e["url"] for e in saved["remote_data"]["entries"]] == ["https://docs.x.io/"]
        # The remaining site can find the page too, so it is skipped as well:
        # otherwise the next sync brings it back.
        assert saved["remote_data"]["skip"] == ["https://docs.x.io/extra"]
        # The page list changes when the worker has deleted the chunks.
        assert "extra.md" in saved["directory_structure"]
        assert saved["tokens"] == "62"

    def test_a_page_entry_no_site_can_reach_adds_no_rule(self, app, pg_conn):
        src = _seed(
            pg_conn,
            remote_data={"entries": [
                {"url": "https://docs.x.io/", "mode": "site", "path_prefix": "/Deploying/"},
                {"url": "https://docs.x.io/extra", "mode": "page"},
            ]},
        )
        response = self._remove(app, pg_conn, src, file_paths=["extra.md"])

        assert response.status_code == 200
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert saved["remote_data"]["skip"] == []

    def test_a_folder_of_page_entries_under_a_site_gets_its_rule(self, app, pg_conn):
        src = _seed(
            pg_conn,
            remote_data={"entries": [
                {"url": "https://docs.x.io/", "mode": "site"},
                {"url": "https://docs.x.io/Deploying/Docker", "mode": "page"},
                {"url": "https://docs.x.io/Deploying/Kubernetes", "mode": "page"},
            ]},
        )
        response = self._remove(app, pg_conn, src, directory_path="Deploying")

        assert response.status_code == 200
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert [e["url"] for e in saved["remote_data"]["entries"]] == ["https://docs.x.io/"]
        assert saved["remote_data"]["skip"] == ["https://docs.x.io/Deploying/*"]

    def test_a_folder_no_site_can_reach_adds_no_rule(self, app, pg_conn):
        src = _seed(
            pg_conn,
            remote_data={"entries": [
                {"url": "https://docs.x.io/", "mode": "site", "path_prefix": "/blog/"},
                {"url": "https://docs.x.io/Deploying/Docker", "mode": "page"},
                {"url": "https://docs.x.io/Deploying/Kubernetes", "mode": "page"},
            ]},
        )
        response = self._remove(app, pg_conn, src, directory_path="Deploying")

        assert response.status_code == 200
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["skip"] == []

    def test_a_removal_past_the_skip_rule_limit_is_refused(self, app, pg_conn):
        src = _seed(pg_conn, remote_data={**CONFIG, "skip": ["https://docs.x.io/old"]})
        with patch("docsgpt.parser.remote.website_loader.MAX_SKIP_RULES", 1):
            response = self._remove(app, pg_conn, src, file_paths=["Deploying/Docker.md"])

        assert response.status_code == 400
        assert "skip rules" in response.json["error"]
        assert response.json["code"] == "skip_limit"
        assert response.json["max_skip"] == 1
        self.pages_task.delay.assert_not_called()
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert saved["remote_data"]["skip"] == ["https://docs.x.io/old"]
        assert "Docker.md" in saved["directory_structure"]["Deploying"]

    def test_a_page_already_skipped_gets_no_second_rule(self, app, pg_conn):
        src = _seed(pg_conn, remote_data={**CONFIG, "skip": ["https://docs.x.io/Deploying/*"]})
        response = self._remove(app, pg_conn, src, file_paths=["Deploying/Docker.md"])

        assert response.status_code == 200
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["skip"] == [
            "https://docs.x.io/Deploying/*"
        ]

    def test_a_crawled_page_is_skipped_in_later_syncs(self, app, pg_conn):
        src = _seed(pg_conn)
        response = self._remove(app, pg_conn, src, file_paths=["Deploying/Docker.md"])

        assert response.status_code == 200
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert saved["remote_data"]["skip"] == ["https://docs.x.io/Deploying/Docker"]
        self.pages_task.delay.assert_called_once_with(
            str(src["id"]), USER, "remove",
            pages=[{"path": "Deploying/Docker.md", "url": "https://docs.x.io/Deploying/Docker", "requested_urls": []}],
            actor_id=USER,
        )

    def test_a_folder_becomes_one_section_rule(self, app, pg_conn):
        src = _seed(pg_conn)
        response = self._remove(app, pg_conn, src, directory_path="Deploying")

        assert response.status_code == 200
        assert response.json["removed"] == 2
        # One task for the whole folder (FAISS saves once).
        self.pages_task.delay.assert_called_once_with(
            str(src["id"]), USER, "remove", pages=[
                {"path": "Deploying/Docker.md", "url": "https://docs.x.io/Deploying/Docker", "requested_urls": []},
                {
                    "path": "Deploying/Kubernetes.md", "url": "https://docs.x.io/Deploying/Kubernetes",
                    "requested_urls": [],
                },
            ], actor_id=USER,
        )
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert saved["remote_data"]["skip"] == ["https://docs.x.io/Deploying/*"]

    def test_removing_the_last_page_entry_of_a_page_only_source_is_refused(self, app, pg_conn):
        src = _seed(
            pg_conn,
            remote_data={"entries": [{"url": "https://docs.x.io/extra", "mode": "page"}]},
            directory_structure={"extra.md": _leaf("https://docs.x.io/extra", 7)},
        )
        response = self._remove(app, pg_conn, src, file_paths=["extra.md"])

        assert response.status_code == 400
        # The UI words this one itself.
        assert response.json["code"] == "last_entry"
        self.pages_task.delay.assert_not_called()

    def test_someone_without_edit_access_is_refused(self, app, pg_conn):
        src = SourcesRepository(pg_conn).create(
            "Theirs", user_id="other", type="website", remote_data=CONFIG, directory_structure=TREE
        )
        response = self._remove(app, pg_conn, src, file_paths=["extra.md"])

        assert response.status_code == 404
        self.pages_task.delay.assert_not_called()

    def test_a_path_named_twice_is_removed_once(self, app, pg_conn):
        src = _seed(pg_conn)
        response = self._remove(app, pg_conn, src, file_paths=["extra.md", "extra.md", "extra.md"])

        assert response.status_code == 200
        assert response.json["removed"] == 1
        assert self.pages_task.delay.call_args.kwargs["pages"] == [
            {"path": "extra.md", "url": "https://docs.x.io/extra", "requested_urls": []}
        ]

    def test_a_page_inside_the_removed_folder_counts_once(self, app, pg_conn):
        src = _seed(pg_conn)
        response = self._remove(
            app, pg_conn, src, file_paths=["Deploying/Docker.md"], directory_path="Deploying"
        )

        assert response.status_code == 200
        assert response.json["removed"] == 2
        assert [p["path"] for p in self.pages_task.delay.call_args.kwargs["pages"]] == [
            "Deploying/Docker.md", "Deploying/Kubernetes.md",
        ]

    def test_pages_named_outside_a_removed_folder_get_their_own_rules(self, app, pg_conn):
        # The folder's section rule doesn't cover extra.md; without its own rule the next crawl brings it back.
        src = _seed(pg_conn)
        response = self._remove(app, pg_conn, src, file_paths=["extra.md"], directory_path="Deploying")

        assert response.status_code == 200
        assert response.json["removed"] == 3
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]
        assert [e["url"] for e in saved["entries"]] == ["https://docs.x.io/"]
        assert saved["skip"] == ["https://docs.x.io/Deploying/*", "https://docs.x.io/extra"]

    def test_a_redirected_page_entry_leaves_the_list_by_its_requested_address(self, app, pg_conn):
        # Added as /old, stored under /new after the redirect: the entry is /old.
        tree = {**TREE, "new.md": {**_leaf("https://docs.x.io/new", 3), "requested_urls": ["https://docs.x.io/old"]}}
        config = {"entries": CONFIG["entries"] + [{"url": "https://docs.x.io/old", "mode": "page"}], "skip": []}
        src = _seed(pg_conn, remote_data=config, directory_structure=tree)
        response = self._remove(app, pg_conn, src, file_paths=["new.md"])

        assert response.status_code == 200
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]
        assert [e["url"] for e in saved["entries"]] == ["https://docs.x.io/", "https://docs.x.io/extra"]
        # The site reaches both addresses, so neither brings the page back.
        assert saved["skip"] == ["https://docs.x.io/new", "https://docs.x.io/old"]
        self.pages_task.delay.assert_called_once_with(str(src["id"]), USER, "remove", pages=[
            {"path": "new.md", "url": "https://docs.x.io/new", "requested_urls": ["https://docs.x.io/old"]},
        ], actor_id=USER)

    def test_a_page_several_entries_redirect_to_drops_every_entry(self, app, pg_conn):
        # /old-a and /old-b both redirect to /new: one page, kept under both addresses.
        aliases = ["https://docs.x.io/old-a", "https://docs.x.io/old-b"]
        leaf = {**_leaf("https://docs.x.io/new", 3), "requested_urls": aliases}
        tree = {**TREE, "new.md": leaf}
        config = {"entries": CONFIG["entries"] + [
            {"url": "https://docs.x.io/old-a", "mode": "page"}, {"url": "https://docs.x.io/old-b/", "mode": "page"},
        ], "skip": []}
        src = _seed(pg_conn, remote_data=config, directory_structure=tree)
        response = self._remove(app, pg_conn, src, file_paths=["new.md"])

        assert response.status_code == 200, response.json
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]
        assert [e["url"] for e in saved["entries"]] == ["https://docs.x.io/", "https://docs.x.io/extra"]
        # The site reaches every address, so none brings the page back.
        assert saved["skip"] == ["https://docs.x.io/new", "https://docs.x.io/old-a", "https://docs.x.io/old-b"]
        self.pages_task.delay.assert_called_once_with(str(src["id"]), USER, "remove", pages=[{
            "path": "new.md", "url": "https://docs.x.io/new",
            "requested_urls": ["https://docs.x.io/old-a", "https://docs.x.io/old-b"],
        }], actor_id=USER)

    def test_a_redirected_page_entry_in_a_removed_folder_leaves_the_list(self, app, pg_conn):
        tree = {"index.md": _leaf("https://docs.x.io/", 5), "guide": {
            "new.md": {**_leaf("https://docs.x.io/guide/new", 3), "requested_urls": ["https://docs.x.io/guide/old"]},
        }}
        config = {"entries": [
            {"url": "https://docs.x.io/", "mode": "page"}, {"url": "https://docs.x.io/guide/old", "mode": "page"},
        ]}
        src = _seed(pg_conn, remote_data=config, directory_structure=tree)
        response = self._remove(app, pg_conn, src, directory_path="guide")

        assert response.status_code == 200
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]
        assert [e["url"] for e in saved["entries"]] == ["https://docs.x.io/"]
        assert saved["skip"] == []

    def test_too_many_paths_in_one_request_are_refused(self, app, pg_conn):
        src = _seed(pg_conn)
        with patch("docsgpt.api.user.sources.website.MAX_REMOVE_PATHS", 2):
            response = self._remove(app, pg_conn, src, file_paths=["a.md", "b.md", "c.md"])
            # Repeats don't count toward it.
            repeated = self._remove(app, pg_conn, src, file_paths=["extra.md"] * 3)

        assert response.status_code == 400
        assert response.json["code"] == "too_many_paths"
        assert response.json["max_paths"] == 2
        assert repeated.status_code == 200


def _legacy_leaf(tokens):
    """A leaf an older loader wrote: no ``url`` (or title)."""
    return {"type": "application/octet-stream", "size_bytes": 10, "token_count": tokens}


LEGACY_TREE = {
    "index.md": _legacy_leaf(5),
    "Deploying": {"Docker.md": _legacy_leaf(20), "Kubernetes.md": _legacy_leaf(30)},
    "extra.md": _legacy_leaf(7),
}
# What each leaf's chunks carry: the page's address and the tree path it was stored under.
LEGACY_CHUNKS = [
    {"doc_id": "c1", "text": "home", "metadata": {"source": "https://docs.x.io/", "file_path": "index.md"}},
    {"doc_id": "c2", "text": "docker", "metadata": {
        "source": "https://docs.x.io/Deploying/Docker", "file_path": "Deploying/Docker.md"}},
    {"doc_id": "c3", "text": "k8s", "metadata": {
        "source": "https://docs.x.io/Deploying/Kubernetes", "file_path": "Deploying/Kubernetes.md"}},
    {"doc_id": "c4", "text": "extra", "metadata": {"source": "https://docs.x.io/extra", "file_path": "extra.md"}},
]


class TestRemoveFromAnOlderSource:
    """A source from the older url/crawler/sitemap loaders: its leaves carry no address.

    Each leaf's address is read from its chunks; the removal then edits the
    config as for any page. A page whose address can't be found is still
    removed, by its path, and the config is left as it is.
    """

    def _remove(self, app, pg_conn, src, chunks=LEGACY_CHUNKS, **body):
        from docsgpt.api.user.sources.website import RemoveWebsitePages

        store = MagicMock()
        store.get_chunks.return_value = chunks
        with patch("docsgpt.api.user.sources.website.website_pages") as pages_task, patch(
            "docsgpt.api.user.sources.website.get_vector_store", return_value=store
        ):
            pages_task.delay.return_value = MagicMock(id="remove-task")
            response = _call(app, pg_conn, RemoveWebsitePages, "POST", json={"source_id": str(src["id"]), **body})
        return response, pages_task

    def _saved(self, pg_conn, src):
        return SourcesRepository(pg_conn).get(str(src["id"]), USER)

    def test_a_crawled_page_is_skipped_in_later_syncs(self, app, pg_conn):
        src = _seed(pg_conn, type="crawler", remote_data="https://docs.x.io/", directory_structure=LEGACY_TREE)
        response, pages_task = self._remove(app, pg_conn, src, file_paths=["extra.md"])

        assert response.status_code == 200, response.json
        saved = self._saved(pg_conn, src)
        assert saved["type"] == "website"
        assert saved["remote_data"]["skip"] == ["https://docs.x.io/extra"]
        # The leaf has no address: it goes with the one read from its chunks,
        # so the worker removes that page, not whatever holds its path later.
        pages_task.delay.assert_called_once_with(
            str(src["id"]), USER, "remove",
            pages=[{"path": "extra.md", "url": "https://docs.x.io/extra", "requested_urls": []}],
            actor_id=USER,
        )

    def test_a_folder_becomes_one_section_rule(self, app, pg_conn):
        src = _seed(pg_conn, type="crawler", remote_data="https://docs.x.io/", directory_structure=LEGACY_TREE)
        response, pages_task = self._remove(app, pg_conn, src, directory_path="Deploying")

        assert response.status_code == 200, response.json
        assert response.json["removed"] == 2
        assert self._saved(pg_conn, src)["remote_data"]["skip"] == ["https://docs.x.io/Deploying/*"]
        assert [p["path"] for p in pages_task.delay.call_args.kwargs["pages"]] == [
            "Deploying/Docker.md", "Deploying/Kubernetes.md",
        ]

    def test_a_sitemap_page_is_skipped(self, app, pg_conn):
        src = _seed(
            pg_conn, type="sitemap", remote_data="https://docs.x.io/sitemap.xml", directory_structure=LEGACY_TREE,
        )
        response, _ = self._remove(app, pg_conn, src, file_paths=["Deploying/Docker.md"])

        assert response.status_code == 200, response.json
        assert self._saved(pg_conn, src)["remote_data"]["skip"] == ["https://docs.x.io/Deploying/Docker"]

    def test_a_page_added_by_address_leaves_the_list(self, app, pg_conn):
        src = _seed(
            pg_conn, type="url", remote_data={"urls": ["https://docs.x.io/", "https://docs.x.io/extra"]},
            directory_structure=LEGACY_TREE,
        )
        response, _ = self._remove(app, pg_conn, src, file_paths=["extra.md"])

        assert response.status_code == 200, response.json
        saved = self._saved(pg_conn, src)["remote_data"]
        assert [e["url"] for e in saved["entries"]] == ["https://docs.x.io/"]
        assert saved["skip"] == []

    def test_a_page_keyed_by_its_title_is_found_and_queued_with_its_address(self, app, pg_conn):
        # The url loader's chunks carry no file_path: the leaf was named after
        # the page's title, and the worker can only find them by the address.
        tree = {"Home": _legacy_leaf(5), "Extra page": _legacy_leaf(7)}
        chunks = [
            {"doc_id": "c1", "text": "home", "metadata": {"source": "https://docs.x.io/", "title": "Home"}},
            {"doc_id": "c2", "text": "x", "metadata": {"source": "https://docs.x.io/extra", "title": "Extra page"}},
        ]
        src = _seed(
            pg_conn, type="url", remote_data={"urls": ["https://docs.x.io/", "https://docs.x.io/extra"]},
            directory_structure=tree,
        )
        response, pages_task = self._remove(app, pg_conn, src, chunks=chunks, file_paths=["Extra page"])

        assert response.status_code == 200, response.json
        assert [e["url"] for e in self._saved(pg_conn, src)["remote_data"]["entries"]] == ["https://docs.x.io/"]
        assert pages_task.delay.call_args.kwargs["pages"] == [
            {"path": "Extra page", "url": "https://docs.x.io/extra", "requested_urls": []},
        ]

    def test_a_folder_of_unaddressed_leaves_is_queued_with_their_addresses(self, app, pg_conn):
        src = _seed(pg_conn, type="crawler", remote_data="https://docs.x.io/", directory_structure=LEGACY_TREE)
        response, pages_task = self._remove(app, pg_conn, src, directory_path="Deploying")

        assert response.status_code == 200, response.json
        assert pages_task.delay.call_args.kwargs["pages"] == [
            {"path": "Deploying/Docker.md", "url": "https://docs.x.io/Deploying/Docker", "requested_urls": []},
            {"path": "Deploying/Kubernetes.md", "url": "https://docs.x.io/Deploying/Kubernetes", "requested_urls": []},
        ]

    def test_a_website_source_not_synced_since_is_handled_too(self, app, pg_conn):
        src = _seed(pg_conn, directory_structure=LEGACY_TREE)
        response, _ = self._remove(app, pg_conn, src, file_paths=["Deploying/Docker.md"])

        assert response.status_code == 200, response.json
        assert self._saved(pg_conn, src)["remote_data"]["skip"] == ["https://docs.x.io/Deploying/Docker"]

    def test_a_page_whose_address_cant_be_found_is_removed_by_path(self, app, pg_conn):
        src = _seed(pg_conn, type="crawler", remote_data="https://docs.x.io/", directory_structure=LEGACY_TREE)
        response, pages_task = self._remove(app, pg_conn, src, chunks=[], file_paths=["extra.md"])

        assert response.status_code == 200, response.json
        pages_task.delay.assert_called_once_with(
            str(src["id"]), USER, "remove", pages=[{"path": "extra.md", "url": "", "requested_urls": []}],
            actor_id=USER,
        )
        # Nothing to edit the config by: it is left as stored.
        saved = self._saved(pg_conn, src)
        assert saved["type"] == "crawler" and saved["remote_data"] == src["remote_data"]

    def test_a_store_that_fails_to_list_still_removes_by_path(self, app, pg_conn):
        from docsgpt.api.user.sources.website import RemoveWebsitePages

        src = _seed(pg_conn, type="crawler", remote_data="https://docs.x.io/", directory_structure=LEGACY_TREE)
        store = MagicMock()
        store.get_chunks.side_effect = RuntimeError("store down")
        with patch("docsgpt.api.user.sources.website.website_pages") as pages_task, patch(
            "docsgpt.api.user.sources.website.get_vector_store", return_value=store
        ):
            pages_task.delay.return_value = MagicMock(id="remove-task")
            response = _call(app, pg_conn, RemoveWebsitePages, "POST", json={
                "source_id": str(src["id"]), "file_paths": ["extra.md"],
            })

        assert response.status_code == 200, response.json
        assert pages_task.delay.call_args.kwargs["pages"] == [{"path": "extra.md", "url": "", "requested_urls": []}]


class TestAddPages:
    @pytest.fixture
    def cap(self):
        """``WEB_MAX_PAGES`` at 5 for the add route; a test may set another."""
        with patch("docsgpt.api.user.sources.website.settings", VECTOR_STORE="faiss", WEB_MAX_PAGES=5) as fake:
            yield fake

    def _add(self, app, pg_conn, src, entries):
        return _post(app, pg_conn, "AddWebsitePages", src, entries=entries)

    def test_pages_on_the_same_host_are_appended(self, app, pg_conn):
        src = _seed(pg_conn)
        new_page = [{"url": "https://docs.x.io/new", "mode": "page"}]
        response, pages_task, sync_task = self._add(app, pg_conn, src, new_page)

        assert response.status_code == 200
        assert response.json["mode"] == "append"
        pages_task.delay.assert_called_once_with(
            str(src["id"]), USER, "add", urls=["https://docs.x.io/new"], actor_id=USER
        )
        sync_task.delay.assert_not_called()
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]
        assert saved[-1] == {"url": "https://docs.x.io/new", "mode": "page"}

    def test_a_page_already_listed_is_refused_and_nothing_queued(self, app, pg_conn):
        src = _seed(pg_conn)
        response, pages_task, sync_task = self._add(
            app, pg_conn, src, [{"url": "https://docs.x.io/extra#top", "mode": "page"}]
        )

        assert response.status_code == 400
        assert response.json["code"] == "already_listed"
        assert response.json["error"] == "These pages and sites are already in this source."
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"] == CONFIG
        pages_task.delay.assert_not_called()
        sync_task.delay.assert_not_called()

    def test_a_site_already_listed_is_refused_and_nothing_queued(self, app, pg_conn):
        src = _seed(pg_conn, remote_data={"entries": [GUIDE], "skip": []})
        same = {**GUIDE, "url": "https://www.docs.x.io/#top"}
        response, pages_task, sync_task = self._add(app, pg_conn, src, [same])

        assert response.status_code == 400
        assert response.json["code"] == "already_listed"
        pages_task.delay.assert_not_called()
        sync_task.delay.assert_not_called()

    @pytest.mark.parametrize("change", [
        {"path_prefix": "/api/"},
        {"include_subdomains": True},
        {"max_pages": 90},
        {"discovery": "links"},
        {"sitemap_url": "https://docs.x.io/guide-map.xml"},
    ])
    def test_another_scope_of_a_listed_site_is_added(self, app, pg_conn, change):
        src = _seed(pg_conn, remote_data={"entries": [GUIDE], "skip": []})
        response, pages_task, sync_task = self._add(app, pg_conn, src, [{**GUIDE, **change}])

        assert response.status_code == 200, response.json
        assert response.json["mode"] == "sync"
        entries = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]
        assert len(entries) == 2
        assert all(entries[1][field] == value for field, value in change.items())
        assert sync_task.delay.call_args.kwargs["source_data"]["entries"] == entries
        pages_task.delay.assert_not_called()

    def test_two_scopes_of_one_site_in_one_request_are_both_added(self, app, pg_conn):
        src = _seed(pg_conn)
        response, _, sync_task = self._add(app, pg_conn, src, [
            {"url": "https://x.io/", "mode": "site", "path_prefix": "/guide/"},
            {"url": "https://x.io/", "mode": "site", "path_prefix": "/api/"},
        ])

        assert response.status_code == 200, response.json
        entries = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]
        assert [e.get("path_prefix") for e in entries[2:]] == ["/guide/", "/api/"]
        sync_task.delay.assert_called_once()

    def test_only_what_is_new_is_fetched(self, app, pg_conn):
        # A listed site beside a new page: the page is appended, not a rebuild for the site.
        src = _seed(pg_conn)
        response, pages_task, sync_task = self._add(app, pg_conn, src, [
            CONFIG["entries"][0],
            {"url": "https://docs.x.io/extra", "mode": "page"},
            {"url": "https://docs.x.io/new", "mode": "page"},
        ])

        assert response.status_code == 200, response.json
        assert response.json["mode"] == "append"
        pages_task.delay.assert_called_once_with(
            str(src["id"]), USER, "add", urls=["https://docs.x.io/new"], actor_id=USER
        )
        sync_task.delay.assert_not_called()

    def test_one_page_named_several_ways_in_one_request_is_listed_once(self, app, pg_conn):
        src = _seed(pg_conn)
        response, pages_task, _ = self._add(app, pg_conn, src, [
            {"url": "https://docs.x.io/new", "mode": "page"},
            {"url": "https://docs.x.io/new/", "mode": "page"},
            {"url": "https://www.docs.x.io/new#a", "mode": "page"},
        ])

        assert response.status_code == 200
        entries = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]
        assert [e["url"] for e in entries] == ["https://docs.x.io/", "https://docs.x.io/extra", "https://docs.x.io/new"]
        pages_task.delay.assert_called_once_with(
            str(src["id"]), USER, "add", urls=["https://docs.x.io/new"], actor_id=USER
        )

    def test_a_whole_site_rebuilds_the_source(self, app, pg_conn):
        src = _seed(pg_conn)
        response, pages_task, sync_task = self._add(
            app, pg_conn, src, [{"url": "https://docs.x.io/API/", "mode": "site", "path_prefix": "/API/"}],
        )

        assert response.status_code == 200
        assert response.json["mode"] == "sync"
        pages_task.delay.assert_not_called()
        kwargs = sync_task.delay.call_args.kwargs
        assert kwargs["loader"] == "website"
        assert kwargs["doc_id"] == str(src["id"])
        assert kwargs["source_data"]["entries"][-1]["path_prefix"] == "/API/"

    def test_a_page_on_a_new_host_rebuilds_the_source(self, app, pg_conn):
        # Every page then needs a host folder in the tree.
        src = _seed(pg_conn)
        other_host = [{"url": "https://github.com/a/b", "mode": "page"}]
        response, pages_task, sync_task = self._add(app, pg_conn, src, other_host)

        assert response.json["mode"] == "sync"
        sync_task.delay.assert_called_once()

    @pytest.mark.parametrize("address", ["docs.x.io/new", "https://docs.x.io/new"])
    def test_a_page_written_without_a_scheme_on_a_listed_host_is_appended(self, app, pg_conn, address):
        src = _seed(pg_conn)
        response, pages_task, sync_task = self._add(app, pg_conn, src, [{"url": address, "mode": "page"}])

        assert response.status_code == 200, response.json
        assert response.json["mode"] == "append"
        pages_task.delay.assert_called_once()
        sync_task.delay.assert_not_called()

    def test_a_page_on_a_new_host_rebuilds_a_source_listed_without_schemes(self, app, pg_conn):
        # Hosts come from the tree's page URLs; an old scheme-less entry doesn't change that.
        src = _seed(pg_conn, remote_data={**CONFIG, "entries": [{"url": "docs.x.io/", "mode": "site"}]})
        response, _, sync_task = self._add(app, pg_conn, src, [{"url": "github.com/a/b", "mode": "page"}])

        assert response.json["mode"] == "sync"
        sync_task.delay.assert_called_once()

    def test_pages_past_the_admin_cap_are_refused(self, app, pg_conn, cap):
        # The seeded source holds 4 pages; the cap covers the whole source.
        src = _seed(pg_conn)
        response, pages_task, sync_task = self._add(app, pg_conn, src, [
            {"url": "https://docs.x.io/one", "mode": "page"},
            {"url": "https://docs.x.io/two", "mode": "page"},
        ])
        fits, _, _ = self._add(app, pg_conn, src, [{"url": "https://docs.x.io/one", "mode": "page"}])

        assert response.status_code == 400
        assert response.json["code"] == "page_limit"
        assert response.json["max_pages"] == 5
        pages_task.delay.assert_not_called()
        sync_task.delay.assert_not_called()
        assert fits.status_code == 200
        entries = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]
        assert [e["url"] for e in entries][-1] == "https://docs.x.io/one"
        assert "https://docs.x.io/two" not in [e["url"] for e in entries]

    def test_pages_not_fetched_yet_count_toward_the_cap(self, app, pg_conn, cap):
        # A page entry counts from when it is listed: one still queued, or
        # one whose fetch failed, holds its place under the cap.
        src = _seed(pg_conn)
        first, _, _ = self._add(app, pg_conn, src, [{"url": "https://docs.x.io/one", "mode": "page"}])
        second, pages_task, _ = self._add(app, pg_conn, src, [{"url": "https://docs.x.io/two", "mode": "page"}])

        assert first.status_code == 200
        assert second.status_code == 400
        assert second.json["code"] == "page_limit"
        pages_task.delay.assert_not_called()
        entries = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]
        assert "https://docs.x.io/two" not in [e["url"] for e in entries]

    @pytest.mark.parametrize("extra_leaf, listed", [
        # Listed and in the tree (``Docker/`` is ``Docker``): 4 pages, not 5.
        (TREE["extra.md"], ["https://docs.x.io/extra", "https://docs.x.io/Deploying/Docker/"]),
        # Listed as /old, stored as /new after a redirect.
        ({**_leaf("https://docs.x.io/new", 7), "requested_urls": ["https://docs.x.io/old"]}, ["https://docs.x.io/old"]),
        # Two listed addresses redirect to one page.
        (
            {**_leaf("https://docs.x.io/new", 7), "requested_urls": ALIASES},
            ALIASES,
        ),
    ])
    def test_a_page_listed_and_in_the_tree_counts_once(self, app, pg_conn, cap, extra_leaf, listed):
        src = _seed(pg_conn, directory_structure={**TREE, "extra.md": extra_leaf}, remote_data={**CONFIG, "entries": [
            CONFIG["entries"][0], *({"url": url, "mode": "page"} for url in listed),
        ]})
        response, _, _ = self._add(app, pg_conn, src, [{"url": "https://docs.x.io/one", "mode": "page"}])

        assert response.status_code == 200, response.json

    def test_the_merged_config_is_validated(self, app, pg_conn):
        src = _seed(pg_conn)
        with patch(
            "docsgpt.api.user.sources.website.parse_website_config",
            side_effect=[{"entries": [{"url": "https://docs.x.io/new", "mode": "page"}]}, ValueError("too many")],
        ):
            response, pages_task, _ = self._add(app, pg_conn, src, [{"url": "https://docs.x.io/new", "mode": "page"}])

        assert response.status_code == 400
        assert response.json["error"] == "too many"
        pages_task.delay.assert_not_called()
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"] == CONFIG

    def test_a_site_on_a_full_source_is_refused(self, app, pg_conn, cap):
        cap.WEB_MAX_PAGES = 4
        src = _seed(pg_conn)
        response, _, sync_task = self._add(app, pg_conn, src, [{"url": "https://docs.x.io/API/", "mode": "site"}])

        assert response.status_code == 400
        assert response.json["code"] == "page_limit"
        sync_task.delay.assert_not_called()

    def test_bad_entries_are_400(self, app, pg_conn):
        src = _seed(pg_conn)
        response, pages_task, sync_task = self._add(app, pg_conn, src, [{"url": ""}])

        assert response.status_code == 400
        pages_task.delay.assert_not_called()
        sync_task.delay.assert_not_called()


class TestRefreshPage:
    def _refresh(self, app, pg_conn, src, file_path, **body):
        response, pages_task, _ = _post(app, pg_conn, "RefreshWebsitePage", src, file_path=file_path, **body)
        return response, pages_task

    def test_queues_the_page(self, app, pg_conn):
        src = _seed(pg_conn)
        response, pages_task = self._refresh(app, pg_conn, src, "Deploying/Docker.md")

        assert response.status_code == 200
        assert response.json["task_id"] == "pages-task"
        # With its address: the worker finds it by that, wherever a sync moved it.
        pages_task.delay.assert_called_once_with(
            str(src["id"]), USER, "refresh", file_path="Deploying/Docker.md", url="https://docs.x.io/Deploying/Docker",
            actor_id=USER,
        )

    def test_a_page_named_by_address_is_found_wherever_it_is(self, app, pg_conn):
        # The UI's tree is older than a sync that moved the page to another path.
        src = _seed(pg_conn)
        response, pages_task = self._refresh(
            app, pg_conn, src, "extra.md", url="https://docs.x.io/Deploying/Docker#top",
        )

        assert response.status_code == 200
        pages_task.delay.assert_called_once_with(
            str(src["id"]), USER, "refresh", file_path="Deploying/Docker.md", url="https://docs.x.io/Deploying/Docker",
            actor_id=USER,
        )

    def test_a_redirected_page_is_found_by_the_address_it_was_asked_for(self, app, pg_conn):
        tree = {**TREE, "new.md": {**_leaf("https://docs.x.io/new", 3), "requested_urls": ["https://docs.x.io/old"]}}
        src = _seed(pg_conn, directory_structure=tree)
        response, pages_task = self._refresh(app, pg_conn, src, "old.md", url="https://docs.x.io/old")

        assert response.status_code == 200
        pages_task.delay.assert_called_once_with(
            str(src["id"]), USER, "refresh", file_path="new.md", url="https://docs.x.io/new", actor_id=USER,
        )

    def test_a_page_is_found_by_any_address_that_redirected_to_it(self, app, pg_conn):
        aliases = ["https://docs.x.io/old-a", "https://docs.x.io/old-b"]
        leaf = {**_leaf("https://docs.x.io/new", 3), "requested_urls": aliases}
        src = _seed(pg_conn, directory_structure={**TREE, "new.md": leaf})
        response, pages_task = self._refresh(app, pg_conn, src, "old.md", url="https://docs.x.io/old-b")

        assert response.status_code == 200
        pages_task.delay.assert_called_once_with(
            str(src["id"]), USER, "refresh", file_path="new.md", url="https://docs.x.io/new", actor_id=USER,
        )

    def test_an_address_no_longer_in_the_source_is_400(self, app, pg_conn):
        src = _seed(pg_conn)
        response, pages_task = self._refresh(app, pg_conn, src, "extra.md", url="https://docs.x.io/gone")

        assert response.status_code == 400
        assert response.json["code"] == "not_found"
        pages_task.delay.assert_not_called()

class TestABrokerThatIsDown:
    """A task that can't be queued is a 500 with code queue_failed, not a bare error; what was saved stays."""

    def _post_failing(self, app, pg_conn, resource, src, **body):
        from docsgpt.api.user.sources import website

        with patch("docsgpt.api.user.sources.website.website_pages") as pages_task, patch(
            "docsgpt.api.user.sources.website.sync_source"
        ) as sync_task:
            pages_task.delay.side_effect = ConnectionError("broker unreachable")
            sync_task.delay.side_effect = ConnectionError("broker unreachable")
            return _call(app, pg_conn, getattr(website, resource), "POST", json={"source_id": str(src["id"]), **body})

    @pytest.mark.parametrize("entry", [
        {"url": "https://docs.x.io/new", "mode": "page"},
        {"url": "https://other.io/", "mode": "site"},
    ])
    def test_an_add_saves_the_entry_and_says_the_next_sync_fetches_it(self, app, pg_conn, entry):
        src = _seed(pg_conn)
        response = self._post_failing(app, pg_conn, "AddWebsitePages", src, entries=[entry])

        assert response.status_code == 500
        assert response.json == {
            "success": False, "code": "queue_failed",
            "error": "The change was saved, but its task couldn't be queued; the next sync picks it up.",
        }
        entries = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]
        assert entries[-1]["url"] == entry["url"]

    def test_a_removal_saves_its_rules_and_says_so(self, app, pg_conn):
        src = _seed(pg_conn)
        response = self._post_failing(app, pg_conn, "RemoveWebsitePages", src, file_paths=["Deploying/Docker.md"])

        assert response.status_code == 500
        assert response.json["code"] == "queue_failed"
        assert "saved" in response.json["error"]
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert saved["remote_data"]["skip"] == ["https://docs.x.io/Deploying/Docker"]

    def test_a_refresh_says_it_did_not_run(self, app, pg_conn):
        src = _seed(pg_conn)
        response = self._post_failing(app, pg_conn, "RefreshWebsitePage", src, file_path="extra.md")

        assert response.status_code == 500
        assert response.json == {
            "success": False, "code": "queue_failed",
            "error": "The refresh couldn't be queued; try again, or sync the source.",
        }


class _ConfigError(ValueError):
    """Stands in for the parser's typed config error: a ``code`` and its ``details``."""

    def __init__(self, message, code, **details):
        super().__init__(message)
        self.code = code
        self.details = details


class TestRefusalCodes:
    """Each refusal carries a ``code``, so the UI can word it in the reader's language."""

    @pytest.mark.parametrize(
        "resource, body",
        [
            ("WebsiteSettings", {"entries": CONFIG["entries"]}),
            ("AddWebsitePages", {"entries": [{"url": "https://docs.x.io/new", "mode": "page"}]}),
            ("RefreshWebsitePage", {"file_path": "a.md"}),
            ("RemoveWebsitePages", {"file_paths": ["a.md"]}),
        ],
    )
    def test_a_source_that_isnt_a_website(self, app, pg_conn, resource, body):
        src = _seed(pg_conn, type="local", remote_data=None)
        response, _, _ = _post(app, pg_conn, resource, src, **body)

        assert response.status_code == 400
        assert response.json["code"] == "not_website"

    def test_reading_a_source_that_isnt_a_website(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn, type="local", remote_data=None)
        response = _call(app, pg_conn, WebsiteSettings, "GET", query=f"?id={src['id']}")

        assert response.json["code"] == "not_website"

    @pytest.mark.parametrize(
        "resource, body",
        [("RefreshWebsitePage", {"file_path": "nope.md"}), ("RemoveWebsitePages", {"file_paths": ["nope.md"]})],
    )
    def test_an_unknown_page(self, app, pg_conn, resource, body):
        response, pages_task, _ = _post(app, pg_conn, resource, _seed(pg_conn), **body)

        assert response.status_code == 400
        assert response.json["code"] == "not_found"
        pages_task.delay.assert_not_called()

    @pytest.mark.parametrize(
        "resource, body",
        [
            ("WebsiteSettings", {"entries": CONFIG["entries"]}),
            ("AddWebsitePages", {"entries": [{"url": "https://docs.x.io/new", "mode": "page"}]}),
        ],
    )
    def test_a_config_error_passes_on_its_code_and_details(self, app, pg_conn, resource, body):
        src = _seed(pg_conn)
        err = _ConfigError("A website source holds up to 20 sites", "site_limit", max_sites=20)
        with patch("docsgpt.api.user.sources.website.parse_website_config", side_effect=err):
            response, _, _ = _post(app, pg_conn, resource, src, **body)

        assert response.status_code == 400
        assert response.json == {
            "success": False, "error": "A website source holds up to 20 sites", "code": "site_limit", "max_sites": 20,
        }

    def test_a_config_error_without_a_code_is_invalid_config(self, app, pg_conn):
        response, _, _ = _post(app, pg_conn, "WebsiteSettings", _seed(pg_conn), entries=[{"url": ""}])

        assert response.status_code == 400
        assert response.json["code"] == "invalid_config"


class TestBodyTypes:
    """A body of the wrong shape is a 400, never a 500."""

    @pytest.mark.parametrize("resource", ["WebsiteSettings", "AddWebsitePages", "RefreshWebsitePage",
                                          "RemoveWebsitePages"])
    @pytest.mark.parametrize("body", [[1, 2], 5, "x", True])
    def test_a_body_that_isnt_an_object_is_400(self, app, pg_conn, resource, body):
        from docsgpt.api.user.sources import website

        with patch("docsgpt.api.user.sources.website.website_pages") as pages_task, patch(
            "docsgpt.api.user.sources.website.sync_source"
        ) as sync_task:
            response = _call(app, pg_conn, getattr(website, resource), "POST", json=body)

        assert response.status_code == 400
        assert response.json["code"] == "invalid_body"
        pages_task.delay.assert_not_called()
        sync_task.delay.assert_not_called()

    @pytest.mark.parametrize(
        "resource, body, field",
        [
            ("RemoveWebsitePages", {"directory_path": ["Deploying"]}, "directory_path"),
            ("RemoveWebsitePages", {"file_paths": "extra.md"}, "file_paths"),
            ("RemoveWebsitePages", {"file_paths": ["extra.md", 3]}, "file_paths"),
            ("RefreshWebsitePage", {"file_path": ["extra.md"]}, "file_path"),
            ("RefreshWebsitePage", {"file_path": "extra.md", "url": 3}, "url"),
            ("WebsiteSettings", {"entries": CONFIG["entries"], "skip": "https://docs.x.io/a"}, "skip"),
            ("WebsiteSettings", {"entries": CONFIG["entries"], "skip": [1]}, "skip"),
            ("WebsiteSettings", {"entries": CONFIG["entries"], "keep_links": "yes"}, "keep_links"),
            ("WebsiteSettings", {"entries": CONFIG["entries"], "sync_frequency": ["daily"]}, "sync_frequency"),
            ("WebsiteSettings", {"entries": {"url": "https://docs.x.io/"}}, "entries"),
            ("AddWebsitePages", {"entries": "https://docs.x.io/new"}, "entries"),
        ],
    )
    def test_a_field_of_the_wrong_type_is_400(self, app, pg_conn, resource, body, field):
        src = _seed(pg_conn)
        response, pages_task, sync_task = _post(app, pg_conn, resource, src, **body)

        assert response.status_code == 400
        assert response.json["code"] == "invalid_field"
        assert response.json["field"] == field
        pages_task.delay.assert_not_called()
        sync_task.delay.assert_not_called()
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"] == CONFIG

    @pytest.mark.parametrize("source_id", [123, {"a": 1}, ["x"]])
    def test_a_source_id_that_isnt_a_string_is_400(self, app, pg_conn, source_id):
        from docsgpt.api.user.sources.website import WebsiteSettings

        response = _call(app, pg_conn, WebsiteSettings, "POST", json={
            "source_id": source_id, "entries": CONFIG["entries"],
        })

        assert response.status_code == 400
        assert response.json["code"] == "invalid_field"
        assert response.json["field"] == "source_id"

    def test_a_missing_field_is_400_with_a_code(self, app, pg_conn):
        from docsgpt.api.user.sources.website import AddWebsitePages

        response = _call(app, pg_conn, AddWebsitePages, "POST", json={"entries": CONFIG["entries"]})

        assert response.status_code == 400
        assert response.json["code"] == "missing_fields"
        assert response.json["fields"] == ["source_id"]


@contextmanager
def _change_after_load(pg_conn, fields):
    """Commit ``fields`` to the row right after the route's first read: a concurrent change.

    The route must build on the row as it is under its lock, not on that first read.
    """
    from docsgpt.api.user.sources import website

    real = website.load_source

    def load_then_change(conn, source_id, user, action):
        doc, ra = real(conn, source_id, user, action)
        SourcesRepository(pg_conn).update(str(doc["id"]), USER, fields)
        return doc, ra

    with patch("docsgpt.api.user.sources.website.load_source", load_then_change):
        yield


class TestConcurrentEdits:
    def test_an_add_keeps_an_entry_added_meanwhile(self, app, pg_conn):
        src = _seed(pg_conn)
        meanwhile = {**CONFIG, "entries": CONFIG["entries"] + [{"url": "https://docs.x.io/other", "mode": "page"}]}
        with _change_after_load(pg_conn, {"remote_data": meanwhile}):
            response, _, _ = _post(
                app, pg_conn, "AddWebsitePages", src, entries=[{"url": "https://docs.x.io/new", "mode": "page"}]
            )

        assert response.status_code == 200
        urls = [e["url"] for e in SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]]
        assert urls == [
            "https://docs.x.io/", "https://docs.x.io/extra", "https://docs.x.io/other", "https://docs.x.io/new",
        ]

    def test_a_removal_keeps_an_entry_added_meanwhile(self, app, pg_conn):
        src = _seed(pg_conn)
        meanwhile = {**CONFIG, "entries": CONFIG["entries"] + [{"url": "https://docs.x.io/late", "mode": "page"}]}
        with _change_after_load(pg_conn, {"remote_data": meanwhile}):
            response, _, _ = _post(app, pg_conn, "RemoveWebsitePages", src, file_paths=["extra.md"])

        assert response.status_code == 200
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert [e["url"] for e in saved["remote_data"]["entries"]] == ["https://docs.x.io/", "https://docs.x.io/late"]

    def test_a_settings_save_keeps_a_schedule_set_meanwhile(self, app, pg_conn):
        src = _seed(pg_conn)
        with _change_after_load(pg_conn, {"sync_frequency": "daily"}):
            response, _, _ = _post(app, pg_conn, "WebsiteSettings", src, entries=CONFIG["entries"])

        assert response.status_code == 200
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["sync_frequency"] == "daily"

    def test_a_removal_while_a_sync_runs_is_queued(self, app, pg_conn):
        # The worker waits for the sync's index lock; the request doesn't take it.
        from docsgpt.vectorstore.index_lock import SourceBusy

        src = _seed(pg_conn)

        def busy(*args, **kwargs):
            raise SourceBusy("busy")

        with patch("docsgpt.vectorstore.index_lock._acquire", busy):
            response, pages_task, _ = _post(app, pg_conn, "RemoveWebsitePages", src, file_paths=["extra.md"])

        assert response.status_code == 200
        pages_task.delay.assert_called_once()


class TestAWikiIsNotEditedAsAWebsite:
    """After a conversion the row still reads as a website; its pages are the wiki's now."""

    @pytest.mark.parametrize(
        "resource, body",
        [
            ("WebsiteSettings", {"entries": CONFIG["entries"], "sync_frequency": "daily"}),
            ("AddWebsitePages", {"entries": [{"url": "https://docs.x.io/new", "mode": "page"}]}),
            ("RefreshWebsitePage", {"file_path": "extra.md"}),
            ("RemoveWebsitePages", {"file_paths": ["extra.md"]}),
        ],
    )
    def test_each_change_is_refused(self, app, pg_conn, resource, body):
        src = _seed(pg_conn, config={"kind": "wiki"}, sync_frequency="never")
        response, pages_task, sync_task = _post(app, pg_conn, resource, src, **body)

        assert response.status_code == 400
        assert response.json["code"] == "wiki"
        pages_task.delay.assert_not_called()
        sync_task.delay.assert_not_called()
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert saved["sync_frequency"] == "never"
        assert saved["remote_data"] == CONFIG
        assert "extra.md" in saved["directory_structure"]


class TestAStoreWithoutChunkEdits:
    """Elasticsearch can't change single chunks: page changes are refused or rebuilt, never faked."""

    @pytest.fixture(autouse=True)
    def _elasticsearch(self):
        with patch("docsgpt.api.user.sources.website.settings.VECTOR_STORE", "elasticsearch"):
            yield

    @pytest.mark.parametrize(
        "resource, body",
        [
            ("RefreshWebsitePage", {"file_path": "extra.md"}),
            ("RemoveWebsitePages", {"file_paths": ["extra.md"]}),
        ],
    )
    def test_refresh_and_remove_are_refused(self, app, pg_conn, resource, body):
        src = _seed(pg_conn)
        response, pages_task, _ = _post(app, pg_conn, resource, src, **body)

        assert response.status_code == 400
        assert response.json["code"] == "chunks_unsupported"
        pages_task.delay.assert_not_called()
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert saved["remote_data"] == CONFIG
        assert "extra.md" in saved["directory_structure"]

    def test_added_pages_rebuild_the_source(self, app, pg_conn):
        src = _seed(pg_conn)
        response, pages_task, sync_task = _post(
            app, pg_conn, "AddWebsitePages", src, entries=[{"url": "https://docs.x.io/new", "mode": "page"}]
        )

        assert response.status_code == 200
        assert response.json["mode"] == "sync"
        pages_task.delay.assert_not_called()
        sync_task.delay.assert_called_once()
