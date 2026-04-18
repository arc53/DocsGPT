import uuid
from contextlib import contextmanager

import pytest
from flask import request
from sqlalchemy import text


@pytest.fixture
def _patch_db_readonly(pg_conn, monkeypatch):
    """Route handler opens its own ``db_readonly()`` connection; redirect it
    to the per-test transactional pg_conn so we can see seeded data and it
    rolls back after the test."""

    @contextmanager
    def _use_pg_conn():
        yield pg_conn

    monkeypatch.setattr(
        "application.api.user.tools.routes.db_readonly", _use_pg_conn
    )


@pytest.mark.unit
class TestGetArtifact:
    def test_note_artifact_success(
        self, pg_conn, _patch_db_readonly, flask_app, decoded_token
    ):
        from application.api.user.tools.routes import GetArtifact
        from application.storage.db.repositories.notes import NotesRepository
        from application.storage.db.repositories.user_tools import UserToolsRepository

        tool_row = UserToolsRepository(pg_conn).create(
            user_id=decoded_token["sub"], name="notes_tool"
        )
        tool_id = str(tool_row["id"])

        note = NotesRepository(pg_conn).upsert(
            user_id=decoded_token["sub"],
            tool_id=tool_id,
            title="t",
            content="a\nb",
        )
        note_id = str(note["id"])

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(note_id)

        assert resp.status_code == 200
        assert resp.json["artifact"]["artifact_type"] == "note"
        assert resp.json["artifact"]["data"]["content"] == "a\nb"
        assert resp.json["artifact"]["data"]["line_count"] == 2

    def test_todo_artifact_success(
        self, pg_conn, _patch_db_readonly, flask_app, decoded_token
    ):
        from application.api.user.tools.routes import GetArtifact
        from application.storage.db.repositories.todos import TodosRepository
        from application.storage.db.repositories.user_tools import UserToolsRepository

        tool_row = UserToolsRepository(pg_conn).create(
            user_id=decoded_token["sub"], name="todo_tool"
        )
        tool_id = str(tool_row["id"])

        todos = TodosRepository(pg_conn)
        t1 = todos.create(
            user_id=decoded_token["sub"], tool_id=tool_id, title="First task"
        )
        t2 = todos.create(
            user_id=decoded_token["sub"], tool_id=tool_id, title="Second task"
        )
        todos.set_completed(str(t2["id"]), decoded_token["sub"], True)

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(str(t1["id"]))

        assert resp.status_code == 200
        assert resp.json["artifact"]["artifact_type"] == "todo_list"
        data = resp.json["artifact"]["data"]
        assert data["total_count"] == 2
        assert data["open_count"] == 1
        assert data["completed_count"] == 1
        assert len(data["items"]) == 2
        todo_ids = [item["todo_id"] for item in data["items"]]
        assert 1 in todo_ids
        assert 2 in todo_ids

    def test_todo_artifact_all_param(
        self, pg_conn, _patch_db_readonly, flask_app, decoded_token
    ):
        """All todos are returned regardless of the 'all' query parameter."""
        from application.api.user.tools.routes import GetArtifact
        from application.storage.db.repositories.todos import TodosRepository
        from application.storage.db.repositories.user_tools import UserToolsRepository

        tool_row = UserToolsRepository(pg_conn).create(
            user_id=decoded_token["sub"], name="todo_tool"
        )
        tool_id = str(tool_row["id"])

        todos = TodosRepository(pg_conn)
        t1 = todos.create(
            user_id=decoded_token["sub"], tool_id=tool_id, title="First task"
        )
        t2 = todos.create(
            user_id=decoded_token["sub"], tool_id=tool_id, title="Second task"
        )
        todos.set_completed(str(t2["id"]), decoded_token["sub"], True)

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(str(t1["id"]))

        assert resp.status_code == 200
        data = resp.json["artifact"]["data"]
        assert data["total_count"] == 2
        assert data["open_count"] == 1
        assert data["completed_count"] == 1

        with flask_app.app_context():
            with flask_app.test_request_context(query_string={"all": "true"}):
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(str(t1["id"]))

        assert resp.status_code == 200
        data = resp.json["artifact"]["data"]
        assert data["total_count"] == 2

    def test_invalid_artifact_id_returns_not_found(
        self, _patch_db_readonly, flask_app, decoded_token
    ):
        """A non-UUID, non-legacy id falls through ``get_any`` on both
        repos without raising (id-shape dispatch keeps the UUID cast out
        of the path) and surfaces as a clean 404."""
        from application.api.user.tools.routes import GetArtifact

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get("not_an_object_id")

        assert resp.status_code == 404

    def test_artifact_not_found_returns_404(
        self, _patch_db_readonly, flask_app, decoded_token
    ):
        from application.api.user.tools.routes import GetArtifact

        non_existent_id = str(uuid.uuid4())

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(non_existent_id)

        assert resp.status_code == 404
        assert resp.json["message"] == "Artifact not found"

    def test_other_user_artifact_returns_404(
        self, pg_conn, _patch_db_readonly, flask_app, decoded_token
    ):
        from application.api.user.tools.routes import GetArtifact
        from application.storage.db.repositories.notes import NotesRepository
        from application.storage.db.repositories.user_tools import UserToolsRepository

        tool_row = UserToolsRepository(pg_conn).create(
            user_id="other_user", name="tool1"
        )
        tool_id = str(tool_row["id"])

        note = NotesRepository(pg_conn).upsert(
            user_id="other_user", tool_id=tool_id, title="t", content="secret"
        )

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(str(note["id"]))

        assert resp.status_code == 404

    def test_note_artifact_by_legacy_mongo_id(
        self, pg_conn, _patch_db_readonly, flask_app, decoded_token
    ):
        """Pre-cutover note artifact ids (Mongo ObjectIds) must resolve
        once the notes.legacy_mongo_id column is populated by backfill."""
        from application.api.user.tools.routes import GetArtifact
        from application.storage.db.repositories.user_tools import UserToolsRepository

        tool_row = UserToolsRepository(pg_conn).create(
            user_id=decoded_token["sub"], name="notes_tool"
        )
        tool_id = str(tool_row["id"])

        legacy_id = "507f1f77bcf86cd799439011"
        pg_conn.execute(
            text(
                """
                INSERT INTO notes (user_id, tool_id, title, content, legacy_mongo_id)
                VALUES (:user_id, CAST(:tool_id AS uuid), 'note', 'legacy body', :legacy)
                """
            ),
            {"user_id": decoded_token["sub"], "tool_id": tool_id, "legacy": legacy_id},
        )

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(legacy_id)

        assert resp.status_code == 200
        assert resp.json["artifact"]["artifact_type"] == "note"
        assert resp.json["artifact"]["data"]["content"] == "legacy body"

    def test_todo_artifact_by_legacy_mongo_id(
        self, pg_conn, _patch_db_readonly, flask_app, decoded_token
    ):
        """Pre-cutover todo artifact ids (Mongo ObjectIds) must resolve via
        ``TodosRepository.get_any`` — that dispatch keeps the 24-hex
        ObjectId out of the bare ``CAST(:id AS uuid)`` path that would
        otherwise poison the readonly transaction."""
        from application.api.user.tools.routes import GetArtifact
        from application.storage.db.repositories.todos import TodosRepository
        from application.storage.db.repositories.user_tools import UserToolsRepository

        tool_row = UserToolsRepository(pg_conn).create(
            user_id=decoded_token["sub"], name="todo_tool"
        )
        tool_id = str(tool_row["id"])

        legacy_id = "507f1f77bcf86cd799439020"
        todos = TodosRepository(pg_conn)
        todos.create(
            user_id=decoded_token["sub"],
            tool_id=tool_id,
            title="legacy todo",
            legacy_mongo_id=legacy_id,
        )
        todos.create(
            user_id=decoded_token["sub"], tool_id=tool_id, title="sibling"
        )

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(legacy_id)

        assert resp.status_code == 200
        assert resp.json["artifact"]["artifact_type"] == "todo_list"
        # Both todos under the resolved tool_id are returned, proving the
        # legacy lookup surfaced the correct ``tool_id`` for ``list_for_tool``.
        assert resp.json["artifact"]["data"]["total_count"] == 2
