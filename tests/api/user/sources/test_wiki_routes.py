"""Tests for the wiki source routes in application/api/user/sources/routes.py."""

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.sources.routes.db_session", _yield
    ), patch(
        "application.api.user.sources.routes.db_readonly", _yield
    ):
        yield


def _grant_team_access(pg_conn, owner, member, source_id, access_level):
    from application.storage.db.repositories.team_members import (
        TeamMembersRepository,
    )
    from application.storage.db.repositories.team_resource_grants import (
        TeamResourceGrantsRepository,
    )
    from application.storage.db.repositories.teams import TeamsRepository

    team = TeamsRepository(pg_conn).create(
        "Acme", f"acme-{uuid.uuid4().hex[:8]}", owner
    )
    TeamMembersRepository(pg_conn).add_member(
        team["id"], member, role="team_member"
    )
    TeamResourceGrantsRepository(pg_conn).grant(
        team["id"], "source", source_id, owner_id=owner, granted_by=owner,
        access_level=access_level,
    )


class TestCreateWikiSource:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import CreateWikiSource

        with app.test_request_context(
            "/api/sources/wiki", method="POST", json={"name": "w"}
        ):
            from flask import request
            request.decoded_token = None
            response = CreateWikiSource().post()
        assert response.status_code == 401

    def test_returns_400_missing_name(self, app, pg_conn):
        from application.api.user.sources.routes import CreateWikiSource

        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/wiki", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u-wiki"}
            response = CreateWikiSource().post()
        assert response.status_code == 400

    def test_creates_row_without_ingest(self, app, pg_conn):
        from application.api.user.sources.routes import CreateWikiSource
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-wiki-create"
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.reembed_wiki_page.delay"
        ) as mock_reembed, patch(
            "application.api.user.tasks.ingest.delay"
        ) as mock_ingest, patch(
            "application.api.user.tasks.reingest_source_task.delay"
        ) as mock_reingest, app.test_request_context(
            "/api/sources/wiki", method="POST", json={"name": "My Wiki"}
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = CreateWikiSource().post()

        assert response.status_code == 200
        source_id = response.json["source_id"]
        row = SourcesRepository(pg_conn).get_any(source_id, user)
        assert row["type"] == "wiki"
        assert row["config"]["kind"] == "wiki"
        # No seed content → no re-embed, and never any ingest/reingest task.
        mock_reembed.assert_not_called()
        mock_ingest.assert_not_called()
        mock_reingest.assert_not_called()

    def test_seed_page_roundtrips_and_only_seed_reembeds(self, app, pg_conn):
        from application.api.user.sources.routes import (
            CreateWikiSource,
            WikiPage,
            WIKI_INDEX_PATH,
        )

        user = "u-wiki-seed"
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.reembed_wiki_page.delay"
        ) as mock_reembed, patch(
            "application.api.user.tasks.ingest.delay"
        ) as mock_ingest, patch(
            "application.api.user.tasks.reingest_source_task.delay"
        ) as mock_reingest, app.test_request_context(
            "/api/sources/wiki",
            method="POST",
            json={"name": "Seeded", "initial_content": "# Hello\nworld"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = CreateWikiSource().post()

        assert response.status_code == 200
        source_id = response.json["source_id"]
        # Re-embed fires once, only for the seed page; no ingest/reingest ever.
        mock_reembed.assert_called_once()
        assert mock_reembed.call_args.args[0] == source_id
        assert mock_reembed.call_args.args[1] == WIKI_INDEX_PATH
        assert mock_reembed.call_args.kwargs["user"] == user
        mock_ingest.assert_not_called()
        mock_reingest.assert_not_called()

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{source_id}/wiki/page?path={WIKI_INDEX_PATH}"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            page_response = WikiPage().get(source_id)
        assert page_response.status_code == 200
        assert page_response.json["page"]["content"] == "# Hello\nworld"


class TestWikiPages:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import WikiPages

        with app.test_request_context("/api/sources/x/wiki/pages"):
            from flask import request
            request.decoded_token = None
            response = WikiPages().get("x")
        assert response.status_code == 401

    def test_owner_lists_pages(self, app, pg_conn):
        from application.api.user.sources.routes import WikiPages
        from application.storage.db.repositories.sources import SourcesRepository
        from application.storage.db.repositories.wiki_pages import WikiPagesRepository

        user = "u-wiki-list"
        src = SourcesRepository(pg_conn).create(
            "wiki-list", user_id=user, type="wiki", config={"kind": "wiki"}
        )
        sid = str(src["id"])
        WikiPagesRepository(pg_conn).upsert(sid, "/index.md", "root", updated_by=user)
        WikiPagesRepository(pg_conn).upsert(sid, "/docs/a.md", "a", updated_by=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/wiki/pages"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = WikiPages().get(sid)
        assert response.status_code == 200
        paths = {p["path"] for p in response.json["pages"]}
        assert paths == {"/index.md", "/docs/a.md"}

    def test_non_owner_without_grant_404(self, app, pg_conn):
        from application.api.user.sources.routes import WikiPages
        from application.storage.db.repositories.sources import SourcesRepository

        owner = "u-wiki-owner"
        stranger = "u-wiki-stranger"
        src = SourcesRepository(pg_conn).create(
            "wiki-private", user_id=owner, type="wiki", config={"kind": "wiki"}
        )
        sid = str(src["id"])

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/wiki/pages"
        ):
            from flask import request
            request.decoded_token = {"sub": stranger}
            response = WikiPages().get(sid)
        assert response.status_code == 404

    def test_team_viewer_can_read(self, app, pg_conn):
        from application.api.user.sources.routes import WikiPages
        from application.storage.db.repositories.sources import SourcesRepository
        from application.storage.db.repositories.wiki_pages import WikiPagesRepository

        owner = "alice-wiki"
        viewer = "bob-wiki-viewer"
        src = SourcesRepository(pg_conn).create(
            "wiki-shared", user_id=owner, type="wiki", config={"kind": "wiki"}
        )
        sid = str(src["id"])
        WikiPagesRepository(pg_conn).upsert(sid, "/index.md", "x", updated_by=owner)
        _grant_team_access(pg_conn, owner, viewer, sid, "viewer")

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/wiki/pages"
        ):
            from flask import request
            request.decoded_token = {"sub": viewer}
            response = WikiPages().get(sid)
        assert response.status_code == 200
        assert {p["path"] for p in response.json["pages"]} == {"/index.md"}


class TestWikiPage:
    def test_returns_400_missing_path(self, app, pg_conn):
        from application.api.user.sources.routes import WikiPage
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-wiki-page-nopath"
        src = SourcesRepository(pg_conn).create(
            "wiki", user_id=user, type="wiki", config={"kind": "wiki"}
        )
        sid = str(src["id"])
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/wiki/page"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = WikiPage().get(sid)
        assert response.status_code == 400

    def test_returns_400_traversal_path(self, app, pg_conn):
        from application.api.user.sources.routes import WikiPage
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-wiki-page-traversal"
        src = SourcesRepository(pg_conn).create(
            "wiki", user_id=user, type="wiki", config={"kind": "wiki"}
        )
        sid = str(src["id"])
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/wiki/page?path=/../secret.md"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = WikiPage().get(sid)
        assert response.status_code == 400

    def test_returns_404_unknown_page(self, app, pg_conn):
        from application.api.user.sources.routes import WikiPage
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-wiki-page-missing"
        src = SourcesRepository(pg_conn).create(
            "wiki", user_id=user, type="wiki", config={"kind": "wiki"}
        )
        sid = str(src["id"])
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/wiki/page?path=/nope.md"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = WikiPage().get(sid)
        assert response.status_code == 404

    def test_non_owner_without_grant_404(self, app, pg_conn):
        from application.api.user.sources.routes import WikiPage
        from application.storage.db.repositories.sources import SourcesRepository
        from application.storage.db.repositories.wiki_pages import WikiPagesRepository

        owner = "u-wiki-pg-owner"
        stranger = "u-wiki-pg-stranger"
        src = SourcesRepository(pg_conn).create(
            "wiki", user_id=owner, type="wiki", config={"kind": "wiki"}
        )
        sid = str(src["id"])
        WikiPagesRepository(pg_conn).upsert(sid, "/index.md", "secret", updated_by=owner)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/wiki/page?path=/index.md"
        ):
            from flask import request
            request.decoded_token = {"sub": stranger}
            response = WikiPage().get(sid)
        assert response.status_code == 404


class TestConvertSourceToWiki:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import ConvertSourceToWiki

        with app.test_request_context(
            "/api/sources/x/wiki/convert", method="POST"
        ):
            from flask import request
            request.decoded_token = None
            response = ConvertSourceToWiki().post("x")
        assert response.status_code == 401

    def test_blank_source_enabled_inline_no_task(self, app, pg_conn):
        from application.api.user.sources.routes import ConvertSourceToWiki
        from application.storage.db.repositories.sources import SourcesRepository
        from application.storage.db.source_config import SourceConfig

        user = "u-convert-blank"
        src = SourcesRepository(pg_conn).create(
            "blank", user_id=user, type="file", directory_structure={}
        )
        sid = str(src["id"])

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.convert_source_to_wiki.delay"
        ) as mock_convert, app.test_request_context(
            f"/api/sources/{sid}/wiki/convert", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ConvertSourceToWiki().post(sid)

        assert response.status_code == 200
        assert response.json["converted"] is False
        assert response.json["enabled"] is True
        mock_convert.assert_not_called()
        got = SourcesRepository(pg_conn).get_any(sid, user)
        cfg = SourceConfig.parse(got.get("config"))
        assert cfg.kind == "wiki"
        assert cfg.retrieval.exposure == "agentic_tool"

    def test_fileful_source_enqueues_task(self, app, pg_conn):
        from application.api.user.sources.routes import ConvertSourceToWiki
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-convert-files"
        src = SourcesRepository(pg_conn).create(
            "files", user_id=user, type="file",
            directory_structure={"a.md": {"type": "text/markdown"}},
        )
        sid = str(src["id"])

        fake_task = type("T", (), {"id": "task-xyz"})()
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.convert_source_to_wiki.delay",
            return_value=fake_task,
        ) as mock_convert, app.test_request_context(
            f"/api/sources/{sid}/wiki/convert", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ConvertSourceToWiki().post(sid)

        assert response.status_code == 200
        assert response.json["task_id"] == "task-xyz"
        mock_convert.assert_called_once()
        assert mock_convert.call_args.kwargs["source_id"] == sid
        assert mock_convert.call_args.kwargs["user"] == user
        assert mock_convert.call_args.kwargs["idempotency_key"] == (
            f"convert-wiki:{sid}"
        )

    def test_in_progress_ingest_rejected_409(self, app, pg_conn):
        from application.api.user.sources.routes import ConvertSourceToWiki
        from application.storage.db.repositories.ingest_chunk_progress import (
            IngestChunkProgressRepository,
        )
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-convert-ingesting"
        src = SourcesRepository(pg_conn).create(
            "ingesting", user_id=user, type="file",
            directory_structure={"a.md": {"type": "text/markdown"}},
        )
        sid = str(src["id"])
        # An active embed in flight (embedded 0 of 5) → "processing".
        IngestChunkProgressRepository(pg_conn).init_progress(sid, 5)

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.convert_source_to_wiki.delay"
        ) as mock_convert, app.test_request_context(
            f"/api/sources/{sid}/wiki/convert", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ConvertSourceToWiki().post(sid)

        assert response.status_code == 409
        mock_convert.assert_not_called()

    def test_viewer_rejected_403(self, app, pg_conn):
        from application.api.user.sources.routes import ConvertSourceToWiki
        from application.storage.db.repositories.sources import SourcesRepository

        owner = "alice-convert"
        viewer = "bob-convert-viewer"
        src = SourcesRepository(pg_conn).create(
            "files", user_id=owner, type="file",
            directory_structure={"a.md": {"type": "text/markdown"}},
        )
        sid = str(src["id"])
        _grant_team_access(pg_conn, owner, viewer, sid, "viewer")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.convert_source_to_wiki.delay"
        ) as mock_convert, app.test_request_context(
            f"/api/sources/{sid}/wiki/convert", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": viewer}
            response = ConvertSourceToWiki().post(sid)

        assert response.status_code == 403
        mock_convert.assert_not_called()


class TestWikiPageEdit:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import WikiPage

        with app.test_request_context(
            "/api/sources/x/wiki/page", method="PUT", json={}
        ):
            from flask import request
            request.decoded_token = None
            response = WikiPage().put("x")
        assert response.status_code == 401

    def test_owner_writes_and_enqueues_reembed(self, app, pg_conn):
        from application.api.user.sources.routes import WikiPage
        from application.storage.db.repositories.sources import SourcesRepository
        from application.storage.db.repositories.wiki_pages import WikiPagesRepository

        user = "u-edit-owner"
        src = SourcesRepository(pg_conn).create(
            "wiki", user_id=user, type="wiki", config={"kind": "wiki"}
        )
        sid = str(src["id"])

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.reembed_wiki_page.delay"
        ) as mock_reembed, app.test_request_context(
            f"/api/sources/{sid}/wiki/page",
            method="PUT",
            json={"path": "/notes.md", "content": "body"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = WikiPage().put(sid)

        assert response.status_code == 200
        assert response.json["page"]["path"] == "/notes.md"
        assert response.json["page"]["version"] is not None
        page = WikiPagesRepository(pg_conn).get_by_path(sid, "/notes.md")
        assert page["content"] == "body"
        mock_reembed.assert_called_once()
        assert mock_reembed.call_args.args[1] == "/notes.md"
        assert mock_reembed.call_args.kwargs["user"] == user

    def test_team_editor_reembeds_as_owner(self, app, pg_conn):
        from application.api.user.sources.routes import WikiPage
        from application.storage.db.repositories.sources import SourcesRepository

        owner = "alice-edit"
        editor = "bob-edit-editor"
        src = SourcesRepository(pg_conn).create(
            "wiki", user_id=owner, type="wiki", config={"kind": "wiki"}
        )
        sid = str(src["id"])
        _grant_team_access(pg_conn, owner, editor, sid, "editor")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.reembed_wiki_page.delay"
        ) as mock_reembed, app.test_request_context(
            f"/api/sources/{sid}/wiki/page",
            method="PUT",
            json={"path": "/e.md", "content": "edited"},
        ):
            from flask import request
            request.decoded_token = {"sub": editor}
            response = WikiPage().put(sid)

        assert response.status_code == 200
        # Re-embed runs AS the owner so the owner-scoped worker load resolves.
        assert mock_reembed.call_args.kwargs["user"] == owner

    def test_stale_version_returns_409(self, app, pg_conn):
        from application.api.user.sources.routes import WikiPage
        from application.storage.db.repositories.sources import SourcesRepository
        from application.storage.db.repositories.wiki_pages import WikiPagesRepository

        user = "u-edit-conflict"
        src = SourcesRepository(pg_conn).create(
            "wiki", user_id=user, type="wiki", config={"kind": "wiki"}
        )
        sid = str(src["id"])
        WikiPagesRepository(pg_conn).upsert(sid, "/c.md", "v1", updated_by=user)
        # Bump to version 2 so a stale expected_version=1 loses the race.
        WikiPagesRepository(pg_conn).upsert(sid, "/c.md", "v2", updated_by=user)

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.reembed_wiki_page.delay"
        ) as mock_reembed, app.test_request_context(
            f"/api/sources/{sid}/wiki/page",
            method="PUT",
            json={"path": "/c.md", "content": "v3", "expected_version": 1},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = WikiPage().put(sid)

        assert response.status_code == 409
        mock_reembed.assert_not_called()

    def test_traversal_path_returns_400(self, app, pg_conn):
        from application.api.user.sources.routes import WikiPage
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-edit-traversal"
        src = SourcesRepository(pg_conn).create(
            "wiki", user_id=user, type="wiki", config={"kind": "wiki"}
        )
        sid = str(src["id"])

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.reembed_wiki_page.delay"
        ), app.test_request_context(
            f"/api/sources/{sid}/wiki/page",
            method="PUT",
            json={"path": "/../secret.md", "content": "x"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = WikiPage().put(sid)
        assert response.status_code == 400

    def test_viewer_rejected_403(self, app, pg_conn):
        from application.api.user.sources.routes import WikiPage
        from application.storage.db.repositories.sources import SourcesRepository

        owner = "alice-edit-viewer"
        viewer = "bob-edit-viewer"
        src = SourcesRepository(pg_conn).create(
            "wiki", user_id=owner, type="wiki", config={"kind": "wiki"}
        )
        sid = str(src["id"])
        _grant_team_access(pg_conn, owner, viewer, sid, "viewer")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.reembed_wiki_page.delay"
        ) as mock_reembed, app.test_request_context(
            f"/api/sources/{sid}/wiki/page",
            method="PUT",
            json={"path": "/v.md", "content": "x"},
        ):
            from flask import request
            request.decoded_token = {"sub": viewer}
            response = WikiPage().put(sid)

        assert response.status_code == 403
        mock_reembed.assert_not_called()
