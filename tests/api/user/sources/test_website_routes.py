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

    def test_a_legacy_crawler_source_reads_as_a_website(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn, type="crawler", remote_data={"url": "https://docs.x.io/"}, metadata={})
        response = _call(app, pg_conn, WebsiteSettings, "GET", query=f"?id={src['id']}")

        assert response.status_code == 200
        assert response.json["legacy"] is True
        assert response.json["config"]["entries"][0]["discovery"] == "links"

    def test_a_non_web_source_is_400(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn, type="local", remote_data=None)
        response = _call(app, pg_conn, WebsiteSettings, "GET", query=f"?id={src['id']}")

        assert response.status_code == 400

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

    def test_saving_a_legacy_source_upgrades_it(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn, type="sitemap", remote_data={"url": "https://docs.x.io/sitemap.xml"})
        response = _call(app, pg_conn, WebsiteSettings, "POST", json={
            "source_id": str(src["id"]),
            "entries": [{"url": "https://docs.x.io/sitemap.xml", "mode": "site"}],
        })

        assert response.status_code == 200
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["type"] == "website"

    @pytest.mark.parametrize(
        "body", [{"entries": []}, {"entries": [{"url": "https://x.io"}], "sync_frequency": "hourly"}]
    )
    def test_rejects_bad_input(self, app, pg_conn, body):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn)
        response = _call(app, pg_conn, WebsiteSettings, "POST", json={"source_id": str(src["id"]), **body})

        assert response.status_code == 400


class TestRemovePages:
    def _remove(self, app, pg_conn, src, store, **body):
        from docsgpt.api.user.sources.website import RemoveWebsitePages

        with patch("docsgpt.api.user.sources.website.get_vector_store", return_value=store):
            return _call(app, pg_conn, RemoveWebsitePages, "POST", json={"source_id": str(src["id"]), **body})

    def test_a_page_added_by_address_leaves_the_list(self, app, pg_conn):
        src = _seed(pg_conn)
        store = MagicMock()
        response = self._remove(app, pg_conn, src, store, file_paths=["extra.md"])

        assert response.status_code == 200
        store.delete_chunks_by_source_paths.assert_called_once_with(["https://docs.x.io/extra"])
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert [e["url"] for e in saved["remote_data"]["entries"]] == ["https://docs.x.io/"]
        # The remaining site can find the page too, so it is skipped as well:
        # otherwise the next sync brings it back.
        assert saved["remote_data"]["skip"] == ["https://docs.x.io/extra"]
        assert "extra.md" not in saved["directory_structure"]
        assert saved["tokens"] == "55"

    def test_a_page_entry_no_site_can_reach_adds_no_rule(self, app, pg_conn):
        src = _seed(
            pg_conn,
            remote_data={"entries": [
                {"url": "https://docs.x.io/", "mode": "site", "path_prefix": "/Deploying/"},
                {"url": "https://docs.x.io/extra", "mode": "page"},
            ]},
        )
        response = self._remove(app, pg_conn, src, MagicMock(), file_paths=["extra.md"])

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
        response = self._remove(app, pg_conn, src, MagicMock(), directory_path="Deploying")

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
        response = self._remove(app, pg_conn, src, MagicMock(), directory_path="Deploying")

        assert response.status_code == 200
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["skip"] == []

    def test_a_removal_past_the_skip_rule_limit_is_refused(self, app, pg_conn):
        src = _seed(pg_conn, remote_data={**CONFIG, "skip": ["https://docs.x.io/old"]})
        store = MagicMock()
        with patch("docsgpt.parser.remote.website_loader.MAX_SKIP_RULES", 1):
            response = self._remove(app, pg_conn, src, store, file_paths=["Deploying/Docker.md"])

        assert response.status_code == 400
        assert "skip rules" in response.json["error"]
        store.delete_chunks_by_source_paths.assert_not_called()
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert saved["remote_data"]["skip"] == ["https://docs.x.io/old"]
        assert "Docker.md" in saved["directory_structure"]["Deploying"]

    def test_a_page_already_skipped_gets_no_second_rule(self, app, pg_conn):
        src = _seed(pg_conn, remote_data={**CONFIG, "skip": ["https://docs.x.io/Deploying/*"]})
        response = self._remove(app, pg_conn, src, MagicMock(), file_paths=["Deploying/Docker.md"])

        assert response.status_code == 200
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["skip"] == [
            "https://docs.x.io/Deploying/*"
        ]

    def test_a_crawled_page_is_skipped_in_later_syncs(self, app, pg_conn):
        src = _seed(pg_conn)
        response = self._remove(app, pg_conn, src, MagicMock(), file_paths=["Deploying/Docker.md"])

        assert response.status_code == 200
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert saved["remote_data"]["skip"] == ["https://docs.x.io/Deploying/Docker"]
        assert "Docker.md" not in saved["directory_structure"]["Deploying"]

    def test_a_folder_becomes_one_section_rule(self, app, pg_conn):
        src = _seed(pg_conn)
        store = MagicMock()
        response = self._remove(app, pg_conn, src, store, directory_path="Deploying")

        assert response.status_code == 200
        assert response.json["removed"] == 2
        # One pass over the store for the whole folder (FAISS saves once).
        store.delete_chunks_by_source_paths.assert_called_once_with(
            ["https://docs.x.io/Deploying/Docker", "https://docs.x.io/Deploying/Kubernetes"]
        )
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert saved["remote_data"]["skip"] == ["https://docs.x.io/Deploying/*"]
        assert "Deploying" not in saved["directory_structure"]
        assert saved["tokens"] == "12"

    def test_removing_the_last_page_entry_of_a_page_only_source_is_refused(self, app, pg_conn):
        src = _seed(
            pg_conn,
            remote_data={"entries": [{"url": "https://docs.x.io/extra", "mode": "page"}]},
            directory_structure={"extra.md": _leaf("https://docs.x.io/extra", 7)},
        )
        store = MagicMock()
        response = self._remove(app, pg_conn, src, store, file_paths=["extra.md"])

        assert response.status_code == 400
        # The UI words this one itself.
        assert response.json["code"] == "last_entry"
        store.delete_chunks_by_source_paths.assert_not_called()

    def test_unknown_paths_are_400(self, app, pg_conn):
        src = _seed(pg_conn)
        response = self._remove(app, pg_conn, src, MagicMock(), file_paths=["nope.md"])

        assert response.status_code == 400


class TestAddPages:
    def _add(self, app, pg_conn, src, entries):
        from docsgpt.api.user.sources.website import AddWebsitePages

        with patch("docsgpt.api.user.sources.website.website_pages") as pages_task, patch(
            "docsgpt.api.user.sources.website.sync_source"
        ) as sync_task:
            pages_task.delay.return_value = MagicMock(id="pages-task")
            sync_task.delay.return_value = MagicMock(id="sync-task")
            response = _call(
                app, pg_conn, AddWebsitePages, "POST", json={"source_id": str(src["id"]), "entries": entries}
            )
        return response, pages_task, sync_task

    def test_pages_on_the_same_host_are_appended(self, app, pg_conn):
        src = _seed(pg_conn)
        new_page = [{"url": "https://docs.x.io/new", "mode": "page"}]
        response, pages_task, sync_task = self._add(app, pg_conn, src, new_page)

        assert response.status_code == 200
        assert response.json["mode"] == "append"
        pages_task.delay.assert_called_once_with(str(src["id"]), USER, "add", urls=["https://docs.x.io/new"])
        sync_task.delay.assert_not_called()
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]
        assert saved[-1] == {"url": "https://docs.x.io/new", "mode": "page"}

    def test_a_page_already_listed_is_not_listed_twice(self, app, pg_conn):
        src = _seed(pg_conn)
        response, pages_task, _ = self._add(app, pg_conn, src, [{"url": "https://docs.x.io/extra#top", "mode": "page"}])

        assert response.status_code == 200
        entries = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]
        assert [e["url"] for e in entries] == ["https://docs.x.io/", "https://docs.x.io/extra"]
        pages_task.delay.assert_called_once()

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

    def test_pages_past_the_admin_cap_are_refused(self, app, pg_conn):
        # The seeded source holds 4 pages; the cap covers the whole source.
        src = _seed(pg_conn)
        with patch("docsgpt.api.user.sources.website.settings", VECTOR_STORE="faiss") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 5
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

    def test_pages_not_fetched_yet_count_toward_the_cap(self, app, pg_conn):
        # A page entry counts from when it is listed: one still queued, or
        # one whose fetch failed, holds its place under the cap.
        src = _seed(pg_conn)
        with patch("docsgpt.api.user.sources.website.settings", VECTOR_STORE="faiss") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 5
            first, _, _ = self._add(app, pg_conn, src, [{"url": "https://docs.x.io/one", "mode": "page"}])
            second, pages_task, _ = self._add(app, pg_conn, src, [{"url": "https://docs.x.io/two", "mode": "page"}])

        assert first.status_code == 200
        assert second.status_code == 400
        assert second.json["code"] == "page_limit"
        pages_task.delay.assert_not_called()
        entries = SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]
        assert "https://docs.x.io/two" not in [e["url"] for e in entries]

    def test_a_listed_page_already_in_the_tree_counts_once(self, app, pg_conn):
        # ``extra`` is both a page entry and a tree page: 4 pages, not 5.
        src = _seed(pg_conn, remote_data={**CONFIG, "entries": CONFIG["entries"] + [
            {"url": "https://docs.x.io/Deploying/Docker/", "mode": "page"},
        ]})
        with patch("docsgpt.api.user.sources.website.settings", VECTOR_STORE="faiss") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 5
            response, _, _ = self._add(app, pg_conn, src, [{"url": "https://docs.x.io/one", "mode": "page"}])

        assert response.status_code == 200

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

    def test_a_site_on_a_full_source_is_refused(self, app, pg_conn):
        src = _seed(pg_conn)
        with patch("docsgpt.api.user.sources.website.settings", VECTOR_STORE="faiss") as fake_settings:
            fake_settings.WEB_MAX_PAGES = 4
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
    def _refresh(self, app, pg_conn, src, file_path):
        from docsgpt.api.user.sources.website import RefreshWebsitePage

        with patch("docsgpt.api.user.sources.website.website_pages") as pages_task:
            pages_task.delay.return_value = MagicMock(id="refresh-task")
            response = _call(
                app, pg_conn, RefreshWebsitePage, "POST", json={"source_id": str(src["id"]), "file_path": file_path}
            )
        return response, pages_task

    def test_queues_the_page(self, app, pg_conn):
        src = _seed(pg_conn)
        response, pages_task = self._refresh(app, pg_conn, src, "Deploying/Docker.md")

        assert response.status_code == 200
        assert response.json["task_id"] == "refresh-task"
        pages_task.delay.assert_called_once_with(str(src["id"]), USER, "refresh", file_path="Deploying/Docker.md")

    def test_an_unknown_page_is_400(self, app, pg_conn):
        src = _seed(pg_conn)
        response, pages_task = self._refresh(app, pg_conn, src, "nope.md")

        assert response.status_code == 400
        pages_task.delay.assert_not_called()


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
        from docsgpt.api.user.sources.website import AddWebsitePages

        src = _seed(pg_conn)
        meanwhile = {**CONFIG, "entries": CONFIG["entries"] + [{"url": "https://docs.x.io/other", "mode": "page"}]}
        with _change_after_load(pg_conn, {"remote_data": meanwhile}), patch(
            "docsgpt.api.user.sources.website.website_pages"
        ) as pages_task:
            pages_task.delay.return_value = MagicMock(id="t")
            response = _call(app, pg_conn, AddWebsitePages, "POST", json={
                "source_id": str(src["id"]), "entries": [{"url": "https://docs.x.io/new", "mode": "page"}],
            })

        assert response.status_code == 200
        urls = [e["url"] for e in SourcesRepository(pg_conn).get(str(src["id"]), USER)["remote_data"]["entries"]]
        assert urls == [
            "https://docs.x.io/", "https://docs.x.io/extra", "https://docs.x.io/other", "https://docs.x.io/new",
        ]

    def test_a_removal_keeps_a_page_added_meanwhile(self, app, pg_conn):
        from docsgpt.api.user.sources.website import RemoveWebsitePages

        src = _seed(pg_conn)
        meanwhile = {**TREE, "late.md": _leaf("https://docs.x.io/late", 4)}
        with _change_after_load(pg_conn, {"directory_structure": meanwhile}), patch(
            "docsgpt.api.user.sources.website.get_vector_store", return_value=MagicMock()
        ):
            response = _call(app, pg_conn, RemoveWebsitePages, "POST", json={
                "source_id": str(src["id"]), "file_paths": ["extra.md"],
            })

        assert response.status_code == 200
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert "late.md" in saved["directory_structure"]
        assert "extra.md" not in saved["directory_structure"]
        assert saved["tokens"] == "59"

    def test_a_settings_save_keeps_a_schedule_set_meanwhile(self, app, pg_conn):
        from docsgpt.api.user.sources.website import WebsiteSettings

        src = _seed(pg_conn)
        with _change_after_load(pg_conn, {"sync_frequency": "daily"}):
            response = _call(app, pg_conn, WebsiteSettings, "POST", json={
                "source_id": str(src["id"]), "entries": CONFIG["entries"],
            })

        assert response.status_code == 200
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["sync_frequency"] == "daily"

    def test_a_removal_while_a_sync_runs_is_refused(self, app, pg_conn):
        from docsgpt.api.user.sources.website import RemoveWebsitePages
        from docsgpt.vectorstore.index_lock import SourceBusy

        src = _seed(pg_conn)
        store = MagicMock()

        @contextmanager
        def busy(source_id, **kwargs):
            raise SourceBusy("busy")
            yield

        with patch("docsgpt.api.user.sources.website.source_index_lock", busy), patch(
            "docsgpt.api.user.sources.website.get_vector_store", return_value=store
        ):
            response = _call(app, pg_conn, RemoveWebsitePages, "POST", json={
                "source_id": str(src["id"]), "file_paths": ["extra.md"],
            })

        assert response.status_code == 409
        assert response.json["code"] == "source_busy"
        store.delete_chunks_by_source_paths.assert_not_called()
        assert "extra.md" in SourcesRepository(pg_conn).get(str(src["id"]), USER)["directory_structure"]


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
        from docsgpt.api.user.sources import website

        src = _seed(pg_conn, config={"kind": "wiki"}, sync_frequency="never")
        store = MagicMock()
        with patch("docsgpt.api.user.sources.website.website_pages") as pages_task, patch(
            "docsgpt.api.user.sources.website.sync_source"
        ) as sync_task, patch("docsgpt.api.user.sources.website.get_vector_store", return_value=store):
            response = _call(
                app, pg_conn, getattr(website, resource), "POST", json={"source_id": str(src["id"]), **body}
            )

        assert response.status_code == 400
        assert response.json["code"] == "wiki"
        pages_task.delay.assert_not_called()
        sync_task.delay.assert_not_called()
        store.delete_chunks_by_source_paths.assert_not_called()
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
        from docsgpt.api.user.sources import website

        src = _seed(pg_conn)
        store = MagicMock()
        with patch("docsgpt.api.user.sources.website.website_pages") as pages_task, patch(
            "docsgpt.api.user.sources.website.get_vector_store", return_value=store
        ):
            response = _call(
                app, pg_conn, getattr(website, resource), "POST", json={"source_id": str(src["id"]), **body}
            )

        assert response.status_code == 400
        assert response.json["code"] == "chunks_unsupported"
        pages_task.delay.assert_not_called()
        store.delete_chunks_by_source_paths.assert_not_called()
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert saved["remote_data"] == CONFIG
        assert "extra.md" in saved["directory_structure"]

    def test_added_pages_rebuild_the_source(self, app, pg_conn):
        from docsgpt.api.user.sources.website import AddWebsitePages

        src = _seed(pg_conn)
        with patch("docsgpt.api.user.sources.website.website_pages") as pages_task, patch(
            "docsgpt.api.user.sources.website.sync_source"
        ) as sync_task:
            sync_task.delay.return_value = MagicMock(id="sync-task")
            response = _call(app, pg_conn, AddWebsitePages, "POST", json={
                "source_id": str(src["id"]), "entries": [{"url": "https://docs.x.io/new", "mode": "page"}],
            })

        assert response.status_code == 200
        assert response.json["mode"] == "sync"
        pages_task.delay.assert_not_called()
        sync_task.delay.assert_called_once()
