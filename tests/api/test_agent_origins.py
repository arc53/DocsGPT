"""An agent's allowed origins, enforced on every request that carries its key.

The Flask hook runs against a small app with routes shaped like the real ones
(JSON body, multipart form, query string, ``/v1`` bearer), so each place a key
can travel is covered. The MCP tool and the artifact download, which run
outside Flask, are checked through their own entry points.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask
from starlette.applications import Starlette
from starlette.testclient import TestClient

from docsgpt.api.agent_origins import (
    DENIED_MESSAGE,
    UNAVAILABLE_MESSAGE,
    enforce_agent_origin,
    origin_denied,
    trusted_origins,
)
from docsgpt.core.settings import settings
from docsgpt.storage.db.repositories.agents import AgentsRepository

ALLOWED = "https://docs.example.com"
OTHER = "https://evil.example.net"


@pytest.fixture
def db(pg_conn, monkeypatch):
    """Point the check's ``db_readonly`` at the test connection."""

    @contextmanager
    def _use_conn():
        yield pg_conn

    monkeypatch.setattr("docsgpt.api.agent_origins.db_readonly", _use_conn)
    return pg_conn


@pytest.fixture(autouse=True)
def _no_extra_trust(monkeypatch):
    """Trust nothing beyond the agent's list unless a test opts in."""
    monkeypatch.setattr(settings, "AGENT_TRUSTED_ORIGINS", [])
    monkeypatch.setattr(settings, "OIDC_FRONTEND_URL", None)
    monkeypatch.setattr(settings, "API_URL", "https://api.example.org")


def _agent(conn, *, restrict: bool, origins: list[str]) -> str:
    key = f"key-{uuid.uuid4().hex}"
    config = {"restrict_origins": restrict, "allowed_origins": origins}
    AgentsRepository(conn).create("owner", "widget", "published", key=key, config=config)
    return key


@pytest.fixture
def restricted(db) -> str:
    return _agent(db, restrict=True, origins=[ALLOWED])


@pytest.fixture
def unrestricted(db) -> str:
    return _agent(db, restrict=False, origins=[ALLOWED])


@pytest.fixture
def client(db):
    app = Flask(__name__)
    app.before_request(enforce_agent_origin)

    @app.route("/api/answer", methods=["POST"])
    @app.route("/stream", methods=["POST"])
    @app.route("/api/store_attachment", methods=["POST"])
    @app.route("/api/artifacts", methods=["GET"])
    @app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
    def _route():
        return {"ok": True}

    return app.test_client()


def _answer(client, key, **headers):
    return client.post("/api/answer", json={"question": "hi", "api_key": key}, headers=headers)


@pytest.mark.unit
class TestAllowedOrigins:
    def test_unrestricted_agent_answers_any_origin(self, client, unrestricted):
        assert _answer(client, unrestricted, Origin=OTHER).status_code == 200
        assert _answer(client, unrestricted).status_code == 200

    def test_listed_origin_is_served(self, client, restricted):
        assert _answer(client, restricted, Origin=ALLOWED).status_code == 200

    def test_unlisted_origin_is_refused(self, client, restricted):
        resp = _answer(client, restricted, Origin=OTHER)
        assert resp.status_code == 403
        assert resp.get_json() == {"success": False, "message": DENIED_MESSAGE}

    def test_missing_origin_is_refused(self, client, restricted):
        assert _answer(client, restricted).status_code == 403

    def test_opaque_null_origin_is_refused(self, client, restricted):
        assert _answer(client, restricted, Origin="null", Referer=f"{ALLOWED}/page").status_code == 403

    def test_referer_stands_in_for_a_missing_origin(self, client, restricted):
        assert _answer(client, restricted, Referer=f"{ALLOWED}/docs/page?x=1").status_code == 200
        assert _answer(client, restricted, Referer=f"{OTHER}/page").status_code == 403

    @pytest.mark.parametrize("sent", ["https://DOCS.example.com", "https://docs.example.com:443"])
    def test_origin_header_is_normalized(self, client, restricted, sent):
        assert _answer(client, restricted, Origin=sent).status_code == 200

    def test_a_different_port_or_scheme_is_another_origin(self, client, restricted):
        assert _answer(client, restricted, Origin="https://docs.example.com:8443").status_code == 403
        assert _answer(client, restricted, Origin="http://docs.example.com").status_code == 403

    def test_several_origins_are_each_allowed(self, client, db):
        key = _agent(db, restrict=True, origins=[ALLOWED, "http://localhost:3000"])
        assert _answer(client, key, Origin=ALLOWED).status_code == 200
        assert _answer(client, key, Origin="http://localhost:3000").status_code == 200
        assert _answer(client, key, Origin=OTHER).status_code == 403

    def test_restriction_off_keeps_the_list_but_allows_all(self, client, db):
        key = _agent(db, restrict=False, origins=[ALLOWED])
        assert _answer(client, key, Origin=OTHER).status_code == 200


@pytest.mark.unit
class TestWhereTheKeyTravels:
    def test_stream_json_body(self, client, restricted):
        resp = client.post("/stream", json={"api_key": restricted}, headers={"Origin": OTHER})
        assert resp.status_code == 403

    def test_multipart_form(self, client, restricted):
        resp = client.post(
            "/api/store_attachment",
            data={"api_key": restricted},
            content_type="multipart/form-data",
            headers={"Origin": OTHER},
        )
        assert resp.status_code == 403

    def test_query_string(self, client, restricted):
        resp = client.get("/api/artifacts", query_string={"api_key": restricted}, headers={"Origin": OTHER})
        assert resp.status_code == 403

    def test_v1_bearer_gets_an_openai_shaped_error(self, client, restricted):
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": []},
            headers={"Authorization": f"Bearer {restricted}", "Origin": OTHER},
        )
        assert resp.status_code == 403
        assert resp.get_json() == {"error": {"message": DENIED_MESSAGE, "type": "permission_error"}}

    def test_v1_bearer_from_a_listed_origin(self, client, restricted):
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": []},
            headers={"Authorization": f"Bearer {restricted}", "Origin": ALLOWED},
        )
        assert resp.status_code == 200

    def test_a_bearer_outside_v1_is_not_read_as_an_agent_key(self, client, restricted):
        # Elsewhere the bearer is a user's session token.
        resp = client.post("/api/answer", json={}, headers={"Authorization": f"Bearer {restricted}"})
        assert resp.status_code == 200

    def test_a_second_key_cannot_mask_a_restricted_one(self, client, restricted, unrestricted):
        # The hook must not check one key while the route uses another.
        resp = client.post(
            "/api/answer",
            query_string={"api_key": unrestricted},
            json={"api_key": restricted},
            headers={"Origin": OTHER},
        )
        assert resp.status_code == 403

    def test_a_repeated_parameter_is_checked_in_full(self, client, restricted, unrestricted):
        resp = client.get(
            "/api/artifacts",
            query_string=[("api_key", unrestricted), ("api_key", restricted)],
            headers={"Origin": OTHER},
        )
        assert resp.status_code == 403

    def test_preflight_is_not_checked(self, client, restricted):
        resp = client.options("/v1/chat/completions", headers={"Authorization": f"Bearer {restricted}"})
        assert resp.status_code == 200

    def test_an_unknown_key_is_left_to_the_route(self, client):
        assert _answer(client, "no-such-key", Origin=OTHER).status_code == 200

    def test_a_request_without_a_key_is_not_checked(self, client):
        assert client.post("/api/answer", json={"question": "hi"}, headers={"Origin": OTHER}).status_code == 200


@pytest.mark.unit
class TestTrustedOrigins:
    def test_the_operators_trusted_origins(self, client, restricted, monkeypatch):
        monkeypatch.setattr(settings, "AGENT_TRUSTED_ORIGINS", ["https://app.docsgpt.cloud/"])
        assert _answer(client, restricted, Origin="https://app.docsgpt.cloud").status_code == 200
        assert _answer(client, restricted, Origin=OTHER).status_code == 403

    def test_the_default_trusts_docsgpt_cloud(self):
        default = type(settings).model_fields["AGENT_TRUSTED_ORIGINS"].default
        assert default == ["https://app.docsgpt.cloud", "https://ent.docsgpt.cloud"]

    def test_the_configured_api_url(self, client, restricted):
        # The UI served by the backend calls from API_URL, whatever Host it reached.
        assert _answer(client, restricted, Origin="https://api.example.org").status_code == 200

    def test_a_forged_host_is_not_trusted(self, client, restricted):
        # Host is chosen by the caller (or by DNS rebinding): naming it in Origin must not pass.
        resp = client.post(
            "/api/answer",
            json={"api_key": restricted},
            base_url="http://attacker.example",
            headers={"Origin": "http://attacker.example"},
        )
        assert resp.status_code == 403

    def test_the_frontend_url(self, client, restricted, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_FRONTEND_URL", "https://app.example.org/")
        assert _answer(client, restricted, Origin="https://app.example.org").status_code == 200

    def test_the_dev_server_when_api_url_is_loopback(self, client, restricted, monkeypatch):
        monkeypatch.setattr(settings, "API_URL", "http://localhost:7091")
        assert _answer(client, restricted, Origin="http://localhost:5173").status_code == 200

    def test_no_dev_server_trust_when_api_url_is_public(self, client, restricted):
        # The test client reaches the API as localhost; only API_URL decides.
        assert _answer(client, restricted, Origin="http://localhost:5173").status_code == 403

    def test_trusted_origins_are_normalized_and_deduplicated(self, monkeypatch):
        monkeypatch.setattr(settings, "AGENT_TRUSTED_ORIGINS", ["https://A.com/", "https://a.com", "junk"])
        monkeypatch.setattr(settings, "API_URL", "https://api.example.org/")
        assert trusted_origins() == ["https://api.example.org", "https://a.com"]


@pytest.mark.unit
class TestRegisteredOnTheApp:
    def test_runs_after_authentication(self):
        from docsgpt.app import app, authenticate_request

        hooks = app.before_request_funcs[None]
        assert enforce_agent_origin in hooks
        assert hooks.index(authenticate_request) < hooks.index(enforce_agent_origin)


@pytest.mark.unit
class TestOutsideFlask:
    def test_mcp_search_refuses_an_unlisted_origin(self, restricted):
        from docsgpt import mcp_server

        headers = {"authorization": f"Bearer {restricted}", "origin": OTHER}
        with patch.object(mcp_server, "get_http_headers", lambda include=None: headers), \
                patch.object(mcp_server, "search") as search:
            with pytest.raises(PermissionError, match="not allowed"):
                asyncio.run(mcp_server.search_docs("q"))
        search.assert_not_called()

    def test_mcp_search_serves_a_listed_origin(self, restricted):
        from docsgpt import mcp_server

        headers = {"authorization": f"Bearer {restricted}", "origin": ALLOWED}
        with patch.object(mcp_server, "get_http_headers", lambda include=None: headers), \
                patch.object(mcp_server, "search", return_value=[{"text": "t"}]):
            assert asyncio.run(mcp_server.search_docs("q")) == [{"text": "t"}]

    def test_artifact_download_refuses_an_unlisted_origin(self, restricted):
        from docsgpt.api.user.artifacts.download import artifact_download_routes

        client = TestClient(Starlette(routes=artifact_download_routes))
        with patch("docsgpt.api.asgi_auth.handle_auth", return_value=None), \
                patch("docsgpt.api.user.artifacts.download._load_version") as load:
            resp = client.get(
                f"/api/artifacts/{uuid.uuid4()}/download",
                params={"api_key": restricted},
                headers={"Origin": OTHER},
            )
        assert resp.status_code == 403
        assert resp.json() == {"success": False, "message": DENIED_MESSAGE}
        load.assert_not_called()

    def test_artifact_download_does_not_trust_a_forged_host(self, restricted):
        from docsgpt.api.user.artifacts.download import artifact_download_routes

        client = TestClient(Starlette(routes=artifact_download_routes))
        with patch("docsgpt.api.asgi_auth.handle_auth", return_value=None), \
                patch("docsgpt.api.user.artifacts.download._load_version") as load:
            resp = client.get(
                f"/api/artifacts/{uuid.uuid4()}/download",
                params={"api_key": restricted},
                headers={"Host": "attacker.example", "Origin": "http://attacker.example"},
            )
        assert resp.status_code == 403
        load.assert_not_called()

    def test_artifact_download_uses_the_referer_of_a_link(self, restricted):
        from docsgpt.api.user.artifacts.download import artifact_download_routes

        client = TestClient(Starlette(routes=artifact_download_routes))
        with patch("docsgpt.api.asgi_auth.handle_auth", return_value=None), \
                patch(
                    "docsgpt.api.user.artifacts.download._load_version",
                    return_value=(None, ("Artifact not found", 404)),
                ) as load:
            resp = client.get(
                f"/api/artifacts/{uuid.uuid4()}/download",
                params={"api_key": restricted},
                headers={"Referer": f"{ALLOWED}/help"},
            )
        # Past the origin check, on to the route's own lookup.
        assert resp.status_code == 404
        load.assert_called_once()

    def test_origin_denied_skips_empty_keys(self):
        assert origin_denied([None, "", "  "], SimpleNamespace(get=lambda name: None)) is False


@contextmanager
def _database_down():
    raise RuntimeError("database unavailable")
    yield  # pragma: no cover


@pytest.mark.unit
class TestFailsClosed:
    """When the agent can't be looked up, a keyed request is refused, never let through."""

    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.setattr("docsgpt.api.agent_origins.db_readonly", _database_down)
        app = Flask(__name__)
        app.before_request(enforce_agent_origin)

        @app.route("/api/answer", methods=["POST"])
        @app.route("/v1/chat/completions", methods=["POST"])
        def _route():
            return {"ok": True}

        return app.test_client()

    def test_flask_route(self, client):
        resp = client.post("/api/answer", json={"api_key": "k"}, headers={"Origin": ALLOWED})
        assert resp.status_code == 503
        assert resp.get_json() == {"success": False, "message": UNAVAILABLE_MESSAGE}

    def test_v1(self, client):
        resp = client.post("/v1/chat/completions", json={}, headers={"Authorization": "Bearer k"})
        assert resp.status_code == 503
        assert resp.get_json() == {"error": {"message": UNAVAILABLE_MESSAGE, "type": "server_error"}}

    def test_a_request_without_a_key_needs_no_lookup(self, client):
        assert client.post("/api/answer", json={"question": "hi"}).status_code == 200

    def test_mcp(self, monkeypatch):
        from docsgpt import mcp_server

        monkeypatch.setattr("docsgpt.api.agent_origins.db_readonly", _database_down)
        with patch.object(mcp_server, "get_http_headers", lambda include=None: {"authorization": "Bearer k"}), \
                patch.object(mcp_server, "search") as search:
            with pytest.raises(RuntimeError, match="try again"):
                asyncio.run(mcp_server.search_docs("q"))
        search.assert_not_called()

    def test_artifact_download(self, monkeypatch):
        from docsgpt.api.user.artifacts.download import artifact_download_routes

        monkeypatch.setattr("docsgpt.api.agent_origins.db_readonly", _database_down)
        client = TestClient(Starlette(routes=artifact_download_routes))
        with patch("docsgpt.api.asgi_auth.handle_auth", return_value=None):
            resp = client.get(f"/api/artifacts/{uuid.uuid4()}/download", params={"api_key": "k"})
        assert resp.status_code == 503
        assert resp.json() == {"success": False, "message": UNAVAILABLE_MESSAGE}
