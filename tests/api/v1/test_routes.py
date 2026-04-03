from flask import Flask

from application.api.v1.routes import v1_bp


class _FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    def find(self, query):
        return [doc for doc in self.docs if all(doc.get(k) == v for k, v in query.items())]


def _build_app():
    app = Flask(__name__)
    app.register_blueprint(v1_bp)
    return app


def test_v1_models_does_not_expose_agent_keys(monkeypatch):
    docs = [
        {"_id": "agent-1", "key": "key-1", "user": "user-1", "name": "Agent One"},
        {"_id": "agent-2", "key": "key-2", "user": "user-1", "name": "Agent Two"},
    ]

    fake_mongo = {"testdb": {"agents": _FakeCollection(docs)}}
    monkeypatch.setattr("application.api.v1.routes.MongoDB.get_client", lambda: fake_mongo)
    monkeypatch.setattr("application.api.v1.routes.settings.MONGO_DB_NAME", "testdb")

    app = _build_app()
    client = app.test_client()
    response = client.get("/v1/models", headers={"Authorization": "Bearer key-1"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["object"] == "list"
    assert len(payload["data"]) == 2
    assert payload["data"][0]["id"] == "agent-1"
    assert payload["data"][1]["id"] == "agent-2"
    # Keys must never appear as model IDs
    assert all(model["id"] != "key-1" for model in payload["data"])
    assert all(model["id"] != "key-2" for model in payload["data"])


def test_v1_models_invalid_key_returns_401(monkeypatch):
    docs = [
        {"_id": "agent-1", "key": "key-1", "user": "user-1", "name": "Agent One"},
    ]

    fake_mongo = {"testdb": {"agents": _FakeCollection(docs)}}
    monkeypatch.setattr("application.api.v1.routes.MongoDB.get_client", lambda: fake_mongo)
    monkeypatch.setattr("application.api.v1.routes.settings.MONGO_DB_NAME", "testdb")

    app = _build_app()
    client = app.test_client()
    response = client.get("/v1/models", headers={"Authorization": "Bearer wrong-key"})

    assert response.status_code == 401
