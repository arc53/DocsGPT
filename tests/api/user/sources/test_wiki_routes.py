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
