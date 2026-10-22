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

    @pytest.mark.parametrize("body", [{"entries": []}, {"entries": [{"url": "https://x.io"}], "sync_frequency": "hourly"}])
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
        store.delete_chunks_by_source_path.assert_called_once_with("https://docs.x.io/extra")
        saved = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert [e["url"] for e in saved["remote_data"]["entries"]] == ["https://docs.x.io/"]
        assert saved["remote_data"]["skip"] == []
        assert "extra.md" not in saved["directory_structure"]
        assert saved["tokens"] == "55"

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
        assert store.delete_chunks_by_source_path.call_count == 2
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
        store.delete_chunks_by_source_path.assert_not_called()

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
            response = _call(app, pg_conn, AddWebsitePages, "POST", json={"source_id": str(src["id"]), "entries": entries})
        return response, pages_task, sync_task

    def test_pages_on_the_same_host_are_appended(self, app, pg_conn):
        src = _seed(pg_conn)
        response, pages_task, sync_task = self._add(app, pg_conn, src, [{"url": "https://docs.x.io/new", "mode": "page"}])

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
        response, pages_task, sync_task = self._add(app, pg_conn, src, [{"url": "https://github.com/a/b", "mode": "page"}])

        assert response.json["mode"] == "sync"
        sync_task.delay.assert_called_once()

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
            response = _call(app, pg_conn, RefreshWebsitePage, "POST", json={"source_id": str(src["id"]), "file_path": file_path})
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
