"""Admin > Defaults > Models: the instance task model (built-in models only), its route and its audit."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.core.settings import settings
from docsgpt.storage.db import model_defaults

URL = "/api/admin/defaults/models"


def _model(model_id, source="builtin", enabled=True):
    return SimpleNamespace(
        id=model_id,
        display_name=model_id.upper(),
        provider=SimpleNamespace(value="openai"),
        display_provider=None,
        source=source,
        enabled=enabled,
    )


BUILTINS = [_model("gpt-a"), _model("gpt-b"), _model("gpt-default")]
ADMIN_CUSTOM = _model("byom-admin", source="user")


def _registry():
    def get_model(model_id, user_id=None):
        if user_id and model_id == ADMIN_CUSTOM.id:
            return ADMIN_CUSTOM
        return next((m for m in BUILTINS if m.id == model_id), None)

    return SimpleNamespace(
        get_model=get_model,
        model_exists=lambda model_id, user_id=None: get_model(model_id, user_id) is not None,
        get_enabled_models=lambda user_id=None: BUILTINS + ([ADMIN_CUSTOM] if user_id else []),
        default_model_id="gpt-default",
    )


@contextmanager
def _yielding(conn):
    yield conn


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    registry = _registry()
    monkeypatch.setattr("docsgpt.core.model_registry.ModelRegistry.get_instance", lambda: registry)
    monkeypatch.setattr(settings, "TASK_MODEL_ID", None)


@pytest.fixture
def db(pg_conn):
    with ExitStack() as stack:
        for target in ("docsgpt.api.admin.defaults.db_readonly", "docsgpt.api.admin.defaults.db_session"):
            stack.enter_context(patch(target, lambda: _yielding(pg_conn)))
        yield pg_conn


@contextmanager
def _as(sub, *roles):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=list(roles) or ["user"]
    ):
        yield


def _admin():
    return _as("admin1", "admin", "user")


@pytest.mark.unit
class TestAdminModelDefaults:
    @pytest.mark.parametrize("method", ["get", "put"])
    def test_unauthenticated(self, client, method):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert getattr(client, method)(URL, json={}).status_code == 401

    @pytest.mark.parametrize("method", ["get", "put"])
    def test_non_admin_forbidden(self, client, db, method):
        with _as("member"):
            resp = getattr(client, method)(URL, json={"task_model_id": "gpt-a"})
        assert resp.status_code == 403
        assert model_defaults.stored_task_model(db) is None

    def test_get_without_a_row(self, client, db):
        with _admin():
            resp = client.get(URL)
        assert resp.status_code == 200
        assert resp.json["task_model_id"] is None
        assert resp.json["fallback_model_id"] == "gpt-default"
        # Built-in models only: never the admin's own custom models.
        assert [m["id"] for m in resp.json["models"]] == ["gpt-a", "gpt-b", "gpt-default"]
        assert set(resp.json["models"][0]) == {"id", "display_name", "provider"}

    def test_the_fallback_is_the_env_setting(self, client, db, monkeypatch):
        monkeypatch.setattr(settings, "TASK_MODEL_ID", "gpt-b")
        with _admin():
            assert client.get(URL).json["fallback_model_id"] == "gpt-b"

    def test_put_stores_returns_the_get_body_and_audits_once(self, client, db):
        with _admin():
            resp = client.put(URL, json={"task_model_id": "gpt-a"})
            again = client.put(URL, json={"task_model_id": "gpt-a"})
            got = client.get(URL)
        assert resp.status_code == 200 and again.status_code == 200
        assert resp.json["task_model_id"] == "gpt-a" == got.json["task_model_id"]
        assert resp.json == got.json
        assert model_defaults.stored_task_model(db) == "gpt-a"
        rows = db.execute(
            text("SELECT actor_id, metadata FROM auth_events WHERE event = 'model_defaults_set'")
        ).fetchall()
        assert len(rows) == 1, "an unchanged save records nothing"
        actor, metadata = rows[0]
        assert actor == "admin1"
        assert metadata["changes"] == {"task_model_id": [None, "gpt-a"]}

    def test_null_clears_it(self, client, db):
        model_defaults.save_task_model(db, "gpt-a")
        with _admin():
            resp = client.put(URL, json={"task_model_id": None})
        assert resp.status_code == 200 and resp.json["task_model_id"] is None
        assert model_defaults.stored_task_model(db) is None

    def test_surrounding_whitespace_is_stripped_before_checking(self, client, db):
        with _admin():
            resp = client.put(URL, json={"task_model_id": " gpt-a "})
        assert resp.status_code == 200 and resp.json["task_model_id"] == "gpt-a"
        assert model_defaults.stored_task_model(db) == "gpt-a"

    def test_whitespace_only_clears_it(self, client, db):
        model_defaults.save_task_model(db, "gpt-a")
        with _admin():
            resp = client.put(URL, json={"task_model_id": "   "})
        assert resp.status_code == 200 and resp.json["task_model_id"] is None
        assert model_defaults.stored_task_model(db) is None

    def test_a_disabled_default_model_is_no_fallback(self, client, db, monkeypatch):
        registry = _registry()
        registry.default_model_id = "gpt-off"
        monkeypatch.setattr("docsgpt.core.model_registry.ModelRegistry.get_instance", lambda: registry)
        BUILTINS.append(_model("gpt-off", enabled=False))
        try:
            with _admin():
                assert client.get(URL).json["fallback_model_id"] is None
        finally:
            BUILTINS.pop()

    @pytest.mark.parametrize(
        "body",
        [{}, {"task_model_id": 5}, {"task_model_id": "gone-model"}, {"task_model_id": "byom-admin"}, []],
    )
    def test_put_validates(self, client, db, body):
        with _admin():
            resp = client.put(URL, json=body)
        assert resp.status_code == 400 and resp.json["success"] is False
        assert model_defaults.stored_task_model(db) is None

    @pytest.mark.parametrize("stale", ["gone-model", "gpt-off"])
    def test_a_stale_stored_model_reads_as_none_and_unavailable(self, client, db, stale):
        model_defaults.save_task_model(db, stale)
        BUILTINS.append(_model("gpt-off", enabled=False))
        try:
            with _admin():
                body = client.get(URL).json
        finally:
            BUILTINS.pop()
        assert body["task_model_id"] is None
        assert body["task_model_unavailable"] is True

    def test_a_usable_or_unset_model_is_not_unavailable(self, client, db):
        with _admin():
            assert client.get(URL).json["task_model_unavailable"] is False
            client.put(URL, json={"task_model_id": "gpt-a"})
            assert client.get(URL).json["task_model_unavailable"] is False

    def test_null_clears_a_stale_model(self, client, db):
        model_defaults.save_task_model(db, "gone-model")
        with _admin():
            resp = client.put(URL, json={"task_model_id": None})
        assert resp.status_code == 200 and resp.json["task_model_unavailable"] is False
        assert model_defaults.stored_task_model(db) is None

    def test_tokens_are_refused(self):
        from docsgpt.api.pat.rules import is_denied

        assert is_denied(URL, "GET") and is_denied(URL, "PUT")
