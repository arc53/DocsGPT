"""Owner / editor / viewer / stranger matrix for the source endpoints.

Every source route resolves the caller's role through
``docsgpt.api.user.resource_access``: 404 when the source isn't visible, 403
when it is but the role can't perform the action, and writes land as the owner.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

OWNER = "alice-roles"
EDITOR = "bob-roles-editor"
VIEWER = "carol-roles-viewer"
STRANGER = "dave-roles-stranger"


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn, *modules):
    @contextmanager
    def _yield():
        yield conn

    patches = []
    for mod in modules:
        for name in ("db_session", "db_readonly"):
            target = f"{mod}.{name}"
            try:
                p = patch(target, _yield)
                p.start()
                patches.append(p)
            except AttributeError:
                pass
    try:
        yield
    finally:
        for p in reversed(patches):
            p.stop()


ROUTES = "docsgpt.api.user.sources.routes"
CHUNKS = "docsgpt.api.user.sources.chunks"
UPLOAD = "docsgpt.api.user.sources.upload"
CONNECTOR = "docsgpt.api.connector.routes"
CONNECTIONS = "docsgpt.connectors.service"


def _shared_source(pg_conn, **kwargs):
    """Seed a source owned by OWNER, shared to EDITOR (editor) and VIEWER (viewer)."""
    from docsgpt.storage.db.repositories.sources import SourcesRepository
    from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
    from docsgpt.storage.db.repositories.team_resource_grants import (
        TeamResourceGrantsRepository,
    )
    from docsgpt.storage.db.repositories.teams import TeamsRepository

    src = SourcesRepository(pg_conn).create(
        kwargs.pop("name", "shared-src"), user_id=OWNER, **kwargs
    )
    sid = str(src["id"])
    for member, level in ((EDITOR, "editor"), (VIEWER, "viewer")):
        team = TeamsRepository(pg_conn).create(
            f"T-{level}", f"t-{level}-{uuid.uuid4().hex[:8]}", OWNER
        )
        TeamMembersRepository(pg_conn).add_member(team["id"], member, role="team_member")
        TeamResourceGrantsRepository(pg_conn).grant(
            team["id"], "source", sid, owner_id=OWNER, granted_by=OWNER,
            access_level=level,
        )
    return sid


def _set(pg_conn, sid, **switches):
    from docsgpt.api.user.resource_access import set_settings

    set_settings(pg_conn, "source", sid, switches, OWNER)


def _call(app, user, path, fn, method="GET", **ctx):
    with app.test_request_context(path, method=method, **ctx):
        from flask import request

        request.decoded_token = {"sub": user}
        return fn()


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


class TestListPayload:
    def test_sources_rows_carry_access(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import CombinedJson

        sid = _shared_source(pg_conn)
        with _patch_db(pg_conn, ROUTES):
            owner = _call(app, OWNER, "/api/sources", CombinedJson().get)
            editor = _call(app, EDITOR, "/api/sources", CombinedJson().get)
            viewer = _call(app, VIEWER, "/api/sources", CombinedJson().get)
        o = next(r for r in owner.json if r["id"] == sid)
        e = next(r for r in editor.json if r["id"] == sid)
        v = next(r for r in viewer.json if r["id"] == sid)
        assert o["access"] == "owner"
        assert "delete" in o["allowed_actions"]
        assert o["ownership"] == "user"
        assert e["access"] == "editor"
        assert "edit" in e["allowed_actions"] and "delete" not in e["allowed_actions"]
        assert e["allowed_actions"] == sorted(e["allowed_actions"])
        assert e["team_access"] == "editor"
        assert v["access"] == "viewer"
        assert v["allowed_actions"] == ["use", "view_config"]
        # viewers_can_see_config defaults on.
        assert "config" in v

    def test_viewer_config_hidden_when_switch_off(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import CombinedJson, PaginatedSources

        sid = _shared_source(pg_conn)
        _set(pg_conn, sid, viewers_can_see_config=False)
        with _patch_db(pg_conn, ROUTES):
            viewer = _call(app, VIEWER, "/api/sources", CombinedJson().get)
            editor = _call(app, EDITOR, "/api/sources", CombinedJson().get)
            vpage = _call(app, VIEWER, "/api/sources/paginated", PaginatedSources().get)
        v = next(r for r in viewer.json if r["id"] == sid)
        e = next(r for r in editor.json if r["id"] == sid)
        vp = next(r for r in vpage.json["paginated"] if r["id"] == sid)
        # Only the behaviour selector survives: the UI needs it to pick the view.
        assert v["config"] == {"kind": "classic"}
        assert v["allowed_actions"] == ["use"]
        assert vp["config"] == {"kind": "classic"}
        assert "retrieval" in e["config"]

    def test_viewer_keeps_graphrag_kind_when_config_hidden(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import CombinedJson

        sid = _shared_source(pg_conn, config={"kind": "graphrag"})
        _set(pg_conn, sid, viewers_can_see_config=False)
        with _patch_db(pg_conn, ROUTES):
            viewer = _call(app, VIEWER, "/api/sources", CombinedJson().get)
        v = next(r for r in viewer.json if r["id"] == sid)
        assert v["config"] == {"kind": "graphrag"}

    def test_paginated_rows_carry_access(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import PaginatedSources

        sid = _shared_source(pg_conn)
        _set(pg_conn, sid, editors_can_delete=True)
        with _patch_db(pg_conn, ROUTES):
            owner = _call(app, OWNER, "/api/sources/paginated", PaginatedSources().get)
            editor = _call(app, EDITOR, "/api/sources/paginated", PaginatedSources().get)
        o = next(r for r in owner.json["paginated"] if r["id"] == sid)
        e = next(r for r in editor.json["paginated"] if r["id"] == sid)
        assert o["access"] == "owner"
        assert e["access"] == "editor"
        assert "delete" in e["allowed_actions"]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def _delete(app, pg_conn, user, sid):
    from docsgpt.api.user.sources.routes import DeleteOldIndexes

    storage = MagicMock()
    storage.is_directory.return_value = False
    with _patch_db(pg_conn, ROUTES), patch(
        f"{ROUTES}.settings.VECTOR_STORE", "milvus"
    ), patch(f"{ROUTES}.StorageCreator.get_storage", return_value=storage), patch(
        f"{ROUTES}.VectorCreator.create_vectorstore", return_value=MagicMock()
    ):
        return _call(app, user, f"/api/delete_old?source_id={sid}", DeleteOldIndexes().get)


class TestDelete:
    @pytest.mark.parametrize("user, status", [(EDITOR, 403), (VIEWER, 403), (STRANGER, 404)])
    def test_non_owner_denied_by_default(self, app, pg_conn, user, status):
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        sid = _shared_source(pg_conn)
        assert _delete(app, pg_conn, user, sid).status_code == status
        assert SourcesRepository(pg_conn).get_by_id(sid) is not None

    def test_editor_deletes_when_switch_on(self, app, pg_conn):
        from sqlalchemy import text

        from docsgpt.storage.db.repositories.sources import SourcesRepository

        sid = _shared_source(pg_conn)
        _set(pg_conn, sid, editors_can_delete=True)
        assert _delete(app, pg_conn, EDITOR, sid).status_code == 200
        assert SourcesRepository(pg_conn).get_by_id(sid) is None
        grants = pg_conn.execute(
            text("SELECT count(*) FROM team_resource_grants WHERE resource_id = CAST(:i AS uuid)"),
            {"i": sid},
        ).scalar()
        settings_rows = pg_conn.execute(
            text("SELECT count(*) FROM resource_share_settings WHERE resource_id = CAST(:i AS uuid)"),
            {"i": sid},
        ).scalar()
        assert grants == 0
        assert settings_rows == 0

    def test_viewer_still_denied_when_switch_on(self, app, pg_conn):
        sid = _shared_source(pg_conn)
        _set(pg_conn, sid, editors_can_delete=True)
        assert _delete(app, pg_conn, VIEWER, sid).status_code == 403


# ---------------------------------------------------------------------------
# Sync frequency / sync / reingest / config
# ---------------------------------------------------------------------------


class TestManageSync:
    @pytest.mark.parametrize("user, status", [(OWNER, 200), (EDITOR, 200), (VIEWER, 403), (STRANGER, 404)])
    def test_matrix(self, app, pg_conn, user, status):
        from docsgpt.api.user.sources.routes import ManageSync
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        sid = _shared_source(pg_conn)
        with _patch_db(pg_conn, ROUTES):
            resp = _call(
                app, user, "/api/manage_sync", ManageSync().post, method="POST",
                json={"source_id": sid, "sync_frequency": "weekly"},
            )
        assert resp.status_code == status
        got = SourcesRepository(pg_conn).get_by_id(sid)["sync_frequency"]
        assert (got == "weekly") == (status == 200)


class TestSyncSource:
    @pytest.mark.parametrize("user, status", [(EDITOR, 200), (VIEWER, 403), (STRANGER, 404)])
    def test_matrix_runs_as_owner(self, app, pg_conn, user, status):
        from docsgpt.api.user.sources.routes import SyncSource

        sid = _shared_source(
            pg_conn, type="url", remote_data={"url": "https://example.com"}
        )
        delay = MagicMock(return_value=MagicMock(id="t-1"))
        with _patch_db(pg_conn, ROUTES), patch(f"{ROUTES}.sync_source.delay", delay):
            resp = _call(
                app, user, "/api/sync_source", SyncSource().post, method="POST",
                json={"source_id": sid},
            )
        assert resp.status_code == status
        if status == 200:
            assert delay.call_args.kwargs["user"] == OWNER
            # The editor who asked receives the sync's events too.
            assert delay.call_args.kwargs["actor_id"] == user
        else:
            delay.assert_not_called()


class TestReingest:
    @pytest.mark.parametrize("user, status", [(EDITOR, 200), (VIEWER, 403), (STRANGER, 404)])
    def test_matrix(self, app, pg_conn, user, status):
        from docsgpt.api.user.sources.routes import ReingestSource

        sid = _shared_source(pg_conn)
        delay = MagicMock(return_value=MagicMock(id="t-2"))
        with _patch_db(pg_conn, ROUTES), patch(f"{ROUTES}.reingest_source_task.delay", delay):
            resp = _call(
                app, user, "/api/sources/reingest", ReingestSource().post,
                method="POST", json={"source_id": sid},
            )
        assert resp.status_code == status
        if status == 200:
            assert delay.call_args.kwargs["user"] == OWNER
            assert delay.call_args.kwargs["actor_id"] == user


WEBSITE = "docsgpt.api.user.sources.website"


class TestWebsiteWrites:
    """A team editor's Website change runs as the owner; the editor receives its events."""

    def _post(self, app, pg_conn, resource, body):
        from docsgpt.api.user.sources import website

        pages = MagicMock(return_value=MagicMock(id="t-pages"))
        sync = MagicMock(return_value=MagicMock(id="t-sync"))
        with _patch_db(pg_conn, WEBSITE), patch(f"{WEBSITE}.website_pages.delay", pages), patch(
            f"{WEBSITE}.sync_source.delay", sync
        ):
            resp = _call(app, EDITOR, "/api/website", getattr(website, resource)().post, method="POST", json=body)
        return resp, pages, sync

    def _website(self, pg_conn):
        leaf = {"type": "text/markdown", "size_bytes": 1, "token_count": 1, "url": "https://docs.x.io/a"}
        return _shared_source(
            pg_conn, type="website",
            directory_structure={"a.md": leaf, "b.md": {**leaf, "url": "https://docs.x.io/b"}},
            remote_data={"entries": [{"url": "https://docs.x.io/a"}, {"url": "https://docs.x.io/b"}], "skip": []},
        )

    @pytest.mark.parametrize("resource, body", [
        ("AddWebsitePages", {"entries": [{"url": "https://docs.x.io/c"}]}),
        ("RefreshWebsitePage", {"file_path": "a.md"}),
        ("RemoveWebsitePages", {"file_paths": ["a.md"]}),
    ])
    def test_a_page_change_carries_the_editor(self, app, pg_conn, resource, body):
        sid = self._website(pg_conn)
        resp, pages, _sync = self._post(app, pg_conn, resource, {"source_id": sid, **body})
        assert resp.status_code == 200, resp.json
        assert pages.call_args.args[1] == OWNER
        assert pages.call_args.kwargs["actor_id"] == EDITOR

    def test_a_site_added_carries_the_editor(self, app, pg_conn):
        sid = self._website(pg_conn)
        resp, _pages, sync = self._post(
            app, pg_conn, "AddWebsitePages",
            {"source_id": sid, "entries": [{"url": "https://docs.x.io/", "mode": "site"}]},
        )
        assert resp.status_code == 200, resp.json
        assert sync.call_args.kwargs["user"] == OWNER
        assert sync.call_args.kwargs["actor_id"] == EDITOR

    def test_a_reingest_that_syncs_carries_the_editor(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import ReingestSource

        sid = self._website(pg_conn)
        sync = MagicMock(return_value=MagicMock(id="t-sync"))
        with _patch_db(pg_conn, ROUTES), patch(f"{ROUTES}.sync_source.apply_async", sync):
            resp = _call(
                app, EDITOR, "/api/sources/reingest", ReingestSource().post, method="POST", json={"source_id": sid}
            )
        assert resp.status_code == 200, resp.json
        assert sync.call_args.kwargs["kwargs"]["user"] == OWNER
        assert sync.call_args.kwargs["kwargs"]["actor_id"] == EDITOR


class TestConfig:
    @pytest.mark.parametrize("user, status", [(EDITOR, 200), (VIEWER, 403), (STRANGER, 404)])
    def test_matrix(self, app, pg_conn, user, status):
        from docsgpt.api.user.sources.routes import SourceConfigResource

        sid = _shared_source(pg_conn)
        with _patch_db(pg_conn, ROUTES):
            resp = _call(
                app, user, f"/api/sources/{sid}/config",
                lambda: SourceConfigResource().patch(sid), method="PATCH",
                json={"retrieval": {"chunks": 7}},
            )
        assert resp.status_code == status


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestReads:
    @pytest.mark.parametrize("user, status", [(OWNER, 200), (EDITOR, 200), (VIEWER, 200), (STRANGER, 404)])
    def test_directory_structure(self, app, pg_conn, user, status):
        from docsgpt.api.user.sources.routes import DirectoryStructure

        sid = _shared_source(pg_conn)
        with _patch_db(pg_conn, ROUTES):
            resp = _call(app, user, f"/api/directory_structure?id={sid}", DirectoryStructure().get)
        assert resp.status_code == status

    @pytest.mark.parametrize("user, status", [(VIEWER, 200), (STRANGER, 404)])
    def test_get_chunks(self, app, pg_conn, user, status):
        from docsgpt.api.user.sources.chunks import GetChunks

        sid = _shared_source(pg_conn)
        store = MagicMock()
        store.get_chunks.return_value = []
        with _patch_db(pg_conn, CHUNKS), patch(f"{CHUNKS}.get_vector_store", return_value=store):
            resp = _call(app, user, f"/api/get_chunks?id={sid}", GetChunks().get)
        assert resp.status_code == status


# ---------------------------------------------------------------------------
# Wiki writes
# ---------------------------------------------------------------------------


class TestWikiWrites:
    @pytest.mark.parametrize("user, status", [(EDITOR, 200), (VIEWER, 403), (STRANGER, 404)])
    def test_put_page(self, app, pg_conn, user, status):
        from docsgpt.api.user.sources.routes import WikiPage

        sid = _shared_source(pg_conn, type="wiki", config={"kind": "wiki"})
        delay = MagicMock()
        with _patch_db(pg_conn, ROUTES), patch(f"{ROUTES}.reembed_wiki_page.delay", delay):
            resp = _call(
                app, user, f"/api/sources/{sid}/wiki/page",
                lambda: WikiPage().put(sid), method="PUT",
                json={"path": "/a.md", "content": "hi"},
            )
        assert resp.status_code == status
        if status == 200:
            assert delay.call_args.kwargs["user"] == OWNER

    @pytest.mark.parametrize("user, status", [(EDITOR, 200), (VIEWER, 403), (STRANGER, 404)])
    def test_convert(self, app, pg_conn, user, status):
        from docsgpt.api.user.sources.routes import ConvertSourceToWiki

        sid = _shared_source(pg_conn)
        with _patch_db(pg_conn, ROUTES):
            resp = _call(
                app, user, f"/api/sources/{sid}/wiki/convert",
                lambda: ConvertSourceToWiki().post(sid), method="POST",
            )
        assert resp.status_code == status


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------


class TestChunkWrites:
    @pytest.mark.parametrize("user, status", [(EDITOR, 201), (VIEWER, 403), (STRANGER, 404)])
    def test_add(self, app, pg_conn, user, status):
        from docsgpt.api.user.sources.chunks import AddChunk

        sid = _shared_source(pg_conn)
        store = MagicMock()
        store.add_chunk.return_value = "c1"
        with _patch_db(pg_conn, CHUNKS), patch(f"{CHUNKS}.get_vector_store", return_value=store):
            resp = _call(
                app, user, "/api/add_chunk", AddChunk().post, method="POST",
                json={"id": sid, "text": "hello"},
            )
        assert resp.status_code == status
        assert store.add_chunk.called == (status == 201)

    @pytest.mark.parametrize("user, status", [(EDITOR, 200), (VIEWER, 403), (STRANGER, 404)])
    def test_delete(self, app, pg_conn, user, status):
        from docsgpt.api.user.sources.chunks import DeleteChunk

        sid = _shared_source(pg_conn)
        store = MagicMock()
        store.get_chunks.return_value = [{"doc_id": "c1", "text": "a", "metadata": {}}]
        store.delete_chunk.return_value = True
        with _patch_db(pg_conn, CHUNKS), patch(f"{CHUNKS}.get_vector_store", return_value=store):
            resp = _call(
                app, user, f"/api/delete_chunk?id={sid}&chunk_id=c1",
                DeleteChunk().delete, method="DELETE",
            )
        assert resp.status_code == status

    @pytest.mark.parametrize("user, status", [(EDITOR, 200), (VIEWER, 403), (STRANGER, 404)])
    def test_update(self, app, pg_conn, user, status):
        from docsgpt.api.user.sources.chunks import UpdateChunk

        sid = _shared_source(pg_conn)
        store = MagicMock()
        store.get_chunks.return_value = [{"doc_id": "c1", "text": "a", "metadata": {}}]
        store.update_chunk.return_value = "c1"
        with _patch_db(pg_conn, CHUNKS), patch(f"{CHUNKS}.get_vector_store", return_value=store):
            resp = _call(
                app, user, "/api/update_chunk", UpdateChunk().put, method="PUT",
                json={"id": sid, "chunk_id": "c1", "text": "b"},
            )
        assert resp.status_code == status


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


class TestManageSourceFiles:
    @pytest.mark.parametrize("user, status", [(EDITOR, 400), (VIEWER, 403), (STRANGER, 404)])
    def test_matrix(self, app, pg_conn, user, status):
        # An editor passes the role check and reaches the operation's own
        # validation (no files → 400); viewer and stranger stop at the check.
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        sid = _shared_source(pg_conn, file_path="/data/src")
        with _patch_db(pg_conn, UPLOAD), patch(
            f"{UPLOAD}.StorageCreator.get_storage", return_value=MagicMock()
        ):
            resp = _call(
                app, user, "/api/manage_source_files", ManageSourceFiles().post,
                method="POST", data={"source_id": sid, "operation": "add"},
                content_type="multipart/form-data",
            )
        assert resp.status_code == status


# ---------------------------------------------------------------------------
# Connector sync
# ---------------------------------------------------------------------------


def _connector_source(pg_conn):
    return _shared_source(
        pg_conn, name="drive-src", type="connector:file",
        remote_data={"provider": "google_drive", "file_ids": ["f"], "folder_ids": []},
    )


def _owner_session(pg_conn, token="st-owner", token_info=None):
    from docsgpt.storage.db.repositories.connector_sessions import (
        ConnectorSessionsRepository,
    )

    repo = ConnectorSessionsRepository(pg_conn)
    row = repo.upsert(OWNER, "google_drive", status="authorized")
    repo.update(
        str(row["id"]),
        {
            "session_token": token,
            "token_info": token_info or {"access_token": "a", "refresh_token": "r"},
        },
    )
    return str(row["id"])


def _link(pg_conn, sid, connection):
    """Point the source at ``connection``, as an ingest through a connection does."""
    from sqlalchemy import text

    pg_conn.execute(
        text("UPDATE sources SET connection_id = CAST(:c AS uuid) WHERE id = CAST(:s AS uuid)"),
        {"c": connection, "s": sid},
    )


def _connector_sync(app, pg_conn, user, body):
    from docsgpt.api.connector.routes import ConnectorSync

    delay = MagicMock(return_value=MagicMock(id="t-sync"))
    with _patch_db(pg_conn, CONNECTOR, CONNECTIONS), patch(
        f"{CONNECTOR}.ingest_connector_task.delay", delay
    ):
        resp = _call(app, user, "/api/connectors/sync", ConnectorSync().post, method="POST", json=body)
    return resp, delay


class TestConnectorSync:
    def test_editor_syncs_with_owner_session(self, app, pg_conn):
        sid = _connector_source(pg_conn)
        owner_connection = _owner_session(pg_conn)
        _link(pg_conn, sid, owner_connection)
        resp, delay = _connector_sync(app, pg_conn, EDITOR, {"source_id": sid})
        assert resp.status_code == 200
        kwargs = delay.call_args.kwargs
        assert kwargs["user"] == OWNER
        assert kwargs["connection_id"] == owner_connection
        # The sync runs as the owner; its events also reach the editor.
        assert kwargs["actor_id"] == EDITOR

    def test_editor_cannot_substitute_own_session(self, app, pg_conn):
        from docsgpt.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        sid = _connector_source(pg_conn)
        owner_connection = _owner_session(pg_conn)
        _link(pg_conn, sid, owner_connection)
        repo = ConnectorSessionsRepository(pg_conn)
        row = repo.upsert(EDITOR, "google_drive", status="authorized")
        repo.update(str(row["id"]), {"session_token": "st-editor", "token_info": {"access_token": "x"}})
        resp, delay = _connector_sync(
            app, pg_conn, EDITOR,
            {"source_id": sid, "session_token": "st-editor", "connection_id": str(row["id"])},
        )
        assert resp.status_code == 200
        assert delay.call_args.kwargs["connection_id"] == owner_connection

    def test_owner_session_missing_returns_409(self, app, pg_conn):
        from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

        sid = _connector_source(pg_conn)
        connection = _owner_session(pg_conn)
        _link(pg_conn, sid, connection)
        ConnectorSessionsRepository(pg_conn).update(connection, {"status": "reconnect_needed"})
        resp, delay = _connector_sync(app, pg_conn, EDITOR, {"source_id": sid})
        assert resp.status_code == 409
        assert "owner" in resp.json["error"].lower()
        assert resp.json["message"] == resp.json["error"]
        # The UI words the refusal itself.
        assert resp.json["code"] == "reconnect_needed"
        delay.assert_not_called()

    @pytest.mark.parametrize("user, wording", [
        (OWNER, "This source's account connection was removed; connect the account again to sync it."),
        (
            EDITOR,
            "This source's account connection was removed; the owner needs to connect the account again to sync it.",
        ),
    ])
    def test_a_source_without_its_connection_is_refused(self, app, pg_conn, user, wording):
        """Removing a connection keeping its sources nulls ``connection_id`` (ON DELETE SET NULL).

        The owner's other account must not read the selection: that would re-link the source to it.
        """
        sid = _connector_source(pg_conn)
        _owner_session(pg_conn, token="st-other")

        resp, delay = _connector_sync(app, pg_conn, user, {"source_id": sid})

        assert resp.status_code == 409
        assert resp.json["code"] == "connection_missing"
        assert resp.json["error"] == wording
        assert resp.json["message"] == resp.json["error"]
        delay.assert_not_called()

    @pytest.mark.parametrize("user, status", [(VIEWER, 403), (STRANGER, 404)])
    def test_viewer_and_stranger_denied(self, app, pg_conn, user, status):
        sid = _connector_source(pg_conn)
        _owner_session(pg_conn)
        resp, delay = _connector_sync(app, pg_conn, user, {"source_id": sid})
        assert resp.status_code == status
        delay.assert_not_called()

    def test_owner_still_uses_own_token(self, app, pg_conn):
        sid = _connector_source(pg_conn)
        owner_connection = _owner_session(pg_conn)
        resp, delay = _connector_sync(
            app, pg_conn, OWNER, {"source_id": sid, "session_token": "st-owner"}
        )
        assert resp.status_code == 200
        assert delay.call_args.kwargs["user"] == OWNER
        assert delay.call_args.kwargs["connection_id"] == owner_connection
        assert delay.call_args.kwargs["actor_id"] == OWNER

    def test_editor_syncs_with_the_sources_own_connection(self, app, pg_conn):
        from sqlalchemy import text

        from docsgpt.security.encryption import encrypt_json
        from docsgpt.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        sid = _connector_source(pg_conn)
        _owner_session(pg_conn)
        second = str(ConnectorSessionsRepository(pg_conn).create(
            OWNER, "google_drive", connector_key="google_drive", auth_kind="oauth",
            account_label="second@example.com",
            encrypted_credentials=encrypt_json({"token_info": {"access_token": "b", "refresh_token": "r"}}, OWNER),
        )["id"])
        pg_conn.execute(
            text("UPDATE sources SET connection_id = CAST(:c AS uuid) WHERE id = CAST(:s AS uuid)"),
            {"c": second, "s": sid},
        )
        resp, delay = _connector_sync(app, pg_conn, EDITOR, {"source_id": sid})
        assert resp.status_code == 200
        assert delay.call_args.kwargs["connection_id"] == second

    def test_editor_sync_refuses_a_signed_out_source_connection(self, app, pg_conn):
        from sqlalchemy import text

        sid = _connector_source(pg_conn)
        connection = _owner_session(pg_conn)
        pg_conn.execute(
            text("UPDATE connector_sessions SET status = 'reconnect_needed' WHERE id = CAST(:c AS uuid)"),
            {"c": connection},
        )
        pg_conn.execute(
            text("UPDATE sources SET connection_id = CAST(:c AS uuid) WHERE id = CAST(:s AS uuid)"),
            {"c": connection, "s": sid},
        )
        resp, delay = _connector_sync(app, pg_conn, EDITOR, {"source_id": sid})
        assert resp.status_code == 409
        delay.assert_not_called()
