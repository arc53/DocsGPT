import uuid
from contextlib import contextmanager

import pytest
from flask import request


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
        """Post-cutover, a non-UUID id is swallowed by the repo try/except
        path and reported as "Artifact not found" (404), not a 400."""
        from application.api.user.tools.routes import GetArtifact

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get("not_an_object_id")

        assert resp.status_code == 404
        assert resp.json["message"] == "Artifact not found"

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
