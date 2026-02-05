from datetime import datetime

import pytest
from bson.objectid import ObjectId
from flask import request


@pytest.mark.unit
class TestGetArtifact:
    def test_note_artifact_success(self, mock_mongo_db, flask_app, decoded_token):
        from application.core.settings import settings
        from application.api.user.tools.routes import GetArtifact

        db = mock_mongo_db[settings.MONGO_DB_NAME]
        note_id = ObjectId()
        db["notes"].insert_one(
            {
                "_id": note_id,
                "user_id": decoded_token["sub"],
                "tool_id": "tool1",
                "note": "a\nb",
                "updated_at": datetime(2025, 1, 1),
            }
        )

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(str(note_id))

        assert resp.status_code == 200
        assert resp.json["artifact"]["artifact_type"] == "note"
        assert resp.json["artifact"]["data"]["content"] == "a\nb"
        assert resp.json["artifact"]["data"]["line_count"] == 2

    def test_todo_artifact_success(self, mock_mongo_db, flask_app, decoded_token):
        from application.core.settings import settings
        from application.api.user.tools.routes import GetArtifact

        db = mock_mongo_db[settings.MONGO_DB_NAME]
        todo_id_1 = ObjectId()
        todo_id_2 = ObjectId()
        db["todos"].insert_many([
            {
                "_id": todo_id_1,
                "user_id": decoded_token["sub"],
                "tool_id": "tool1",
                "todo_id": 1,
                "title": "First task",
                "status": "open",
                "created_at": datetime(2025, 1, 1),
                "updated_at": datetime(2025, 1, 1),
            },
            {
                "_id": todo_id_2,
                "user_id": decoded_token["sub"],
                "tool_id": "tool1",
                "todo_id": 2,
                "title": "Second task",
                "status": "completed",
                "created_at": datetime(2025, 1, 1),
                "updated_at": datetime(2025, 1, 2),
            },
        ])

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(str(todo_id_1))

        assert resp.status_code == 200
        assert resp.json["artifact"]["artifact_type"] == "todo_list"
        data = resp.json["artifact"]["data"]
        assert data["total_count"] == 2
        assert data["open_count"] == 1
        assert data["completed_count"] == 1

    def test_invalid_artifact_id_returns_400(self, mock_mongo_db, flask_app, decoded_token):
        from application.api.user.tools.routes import GetArtifact

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get("not_an_object_id")

        assert resp.status_code == 400
        assert resp.json["message"] == "Invalid artifact ID"

    def test_artifact_not_found_returns_404(self, mock_mongo_db, flask_app, decoded_token):
        from application.api.user.tools.routes import GetArtifact

        non_existent_id = ObjectId()

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(str(non_existent_id))

        assert resp.status_code == 404
        assert resp.json["message"] == "Artifact not found"

    def test_other_user_artifact_returns_404(self, mock_mongo_db, flask_app, decoded_token):
        from application.core.settings import settings
        from application.api.user.tools.routes import GetArtifact

        db = mock_mongo_db[settings.MONGO_DB_NAME]
        note_id = ObjectId()
        db["notes"].insert_one(
            {
                "_id": note_id,
                "user_id": "other_user",
                "tool_id": "tool1",
                "note": "secret",
                "updated_at": datetime(2025, 1, 1),
            }
        )

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(str(note_id))

        assert resp.status_code == 404

    def test_memory_file_artifact_success(self, mock_mongo_db, flask_app, decoded_token):
        from application.core.settings import settings
        from application.api.user.tools.routes import GetArtifact

        db = mock_mongo_db[settings.MONGO_DB_NAME]
        memory_id = ObjectId()
        db["memories"].insert_one(
            {
                "_id": memory_id,
                "user_id": decoded_token["sub"],
                "tool_id": "tool1",
                "path": "/notes.txt",
                "artifact_data": {
                    "artifact_type": "memory_file",
                    "path": "/notes.txt",
                    "content": "Hello world",
                    "updated_at": "2025-01-01T00:00:00",
                },
            }
        )

        with flask_app.app_context():
            with flask_app.test_request_context():
                request.decoded_token = decoded_token
                resource = GetArtifact()
                resp = resource.get(str(memory_id))

        assert resp.status_code == 200
        assert resp.json["artifact"]["artifact_type"] == "memory"
        data = resp.json["artifact"]["data"]
        assert data["artifact_subtype"] == "file"
        assert data["file"]["path"] == "/notes.txt"
        assert data["file"]["content"] == "Hello world"

