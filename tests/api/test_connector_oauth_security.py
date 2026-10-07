"""Connector OAuth hardening: popup message origin, token exposure, session ownership."""

import base64
import json
import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from tests.connectors.conftest import _oauth_connectors_configured  # noqa: F401,E402  (autouse)


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn, module="docsgpt.api.connector.routes"):
    @contextmanager
    def _yield():
        yield conn

    with patch(f"{module}.db_session", _yield), patch(f"{module}.db_readonly", _yield), patch(
        "docsgpt.api.connector.routes.db_readonly", _yield
    ), patch("docsgpt.connectors.service.db_session", _yield), patch(
        "docsgpt.connectors.service.db_readonly", _yield
    ):
        yield


def _encode_state(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _seed_session(pg_conn, user, token, provider="google_drive", token_info=None):
    from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

    repo = ConnectorSessionsRepository(pg_conn)
    row = repo.upsert(user, provider, status="authorized")
    patch_fields = {"session_token": token}
    if token_info:
        patch_fields["token_info"] = token_info
    repo.update(str(row["id"]), patch_fields)
    return repo


class TestConnectorAllowedOrigins:
    def test_collects_configured_origins(self):
        from docsgpt.api.connector.routes import connector_allowed_origins
        from docsgpt.core.settings import settings

        with patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", "https://app.example.com/, https://b.example.com/x"), \
                patch.object(settings, "OIDC_FRONTEND_URL", "https://sso.example.com/home"), \
                patch.object(settings, "CONNECTOR_REDIRECT_BASE_URI", "https://api.example.com/api/connectors/callback"):
            origins = connector_allowed_origins()

        assert set(origins) == {
            "https://app.example.com",
            "https://b.example.com",
            "https://sso.example.com",
            "https://api.example.com",
        }

    def test_rejects_wildcards_and_non_http_values(self):
        from docsgpt.api.connector.routes import connector_allowed_origins
        from docsgpt.core.settings import settings

        with patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", "*, javascript:alert(1), null, not a url"), \
                patch.object(settings, "OIDC_FRONTEND_URL", None), \
                patch.object(settings, "CONNECTOR_REDIRECT_BASE_URI", "https://api.example.com/api/connectors/callback"):
            origins = connector_allowed_origins()

        assert origins == ["https://api.example.com"]

    def test_loopback_dev_frontend_allowed_only_for_loopback_callback(self):
        from docsgpt.api.connector.routes import connector_allowed_origins
        from docsgpt.core.settings import settings

        with patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", None), \
                patch.object(settings, "OIDC_FRONTEND_URL", None), \
                patch.object(settings, "CONNECTOR_REDIRECT_BASE_URI", "http://127.0.0.1:7091/api/connectors/callback"):
            local = connector_allowed_origins()
        with patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", None), \
                patch.object(settings, "OIDC_FRONTEND_URL", None), \
                patch.object(settings, "CONNECTOR_REDIRECT_BASE_URI", "https://api.example.com/api/connectors/callback"):
            public = connector_allowed_origins()

        assert "http://localhost:5173" in local
        assert "http://127.0.0.1:5173" in local
        assert "http://localhost:5173" not in public

    def test_loopback_aliases_keep_callback_scheme_and_port(self):
        from docsgpt.api.connector.routes import connector_allowed_origins
        from docsgpt.core.settings import settings

        with patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", None), \
                patch.object(settings, "OIDC_FRONTEND_URL", None), \
                patch.object(settings, "CONNECTOR_REDIRECT_BASE_URI", "https://localhost/api/connectors/callback"):
            origins = connector_allowed_origins()

        assert "https://127.0.0.1" in origins
        assert "http://localhost" not in origins
        assert "http://127.0.0.1" not in origins


class TestCallbackStatusPage:
    def test_never_posts_to_wildcard_origin(self, app):
        from docsgpt.api.connector.routes import ConnectorCallbackStatus

        with app.test_request_context(
            "/api/connectors/callback-status?status=success&provider=google_drive"
        ):
            r = ConnectorCallbackStatus().get()
        body = r.get_data(as_text=True)
        assert r.status_code == 200
        assert "'*'" not in body
        assert '"*"' not in body

    def test_ignores_session_token_query_param(self, app):
        from docsgpt.api.connector.routes import ConnectorCallbackStatus

        with app.test_request_context(
            "/api/connectors/callback-status?status=success&provider=google_drive"
            "&session_token=attacker-supplied&user_email=evil@example.com"
        ):
            r = ConnectorCallbackStatus().get()
        body = r.get_data(as_text=True)
        assert "attacker-supplied" not in body
        assert "evil@example.com" not in body

    def test_tokenless_success_posts_to_no_origin(self, app):
        from docsgpt.api.connector.routes import ConnectorCallbackStatus

        with app.test_request_context(
            "/api/connectors/callback-status?status=success&provider=google_drive"
        ):
            r = ConnectorCallbackStatus().get()
        assert "const targetOrigins = [];" in r.get_data(as_text=True)

    def test_request_provider_never_reaches_inline_script(self, app):
        from docsgpt.api.connector.routes import ConnectorCallbackStatus

        with app.test_request_context(
            "/api/connectors/callback-status?status=error&provider=zz-injected-provider"
        ):
            r = ConnectorCallbackStatus().get()
        body = r.get_data(as_text=True)
        script = body[body.index("<script>"):body.index("</script>")]
        assert "zz-injected-provider" not in script

    def test_error_posts_fixed_auth_error_to_allowed_origins(self, app):
        from docsgpt.api.connector.routes import ConnectorCallbackStatus
        from docsgpt.core.settings import settings

        with patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", "https://app.example.com"), app.test_request_context(
            "/api/connectors/callback-status?status=error&provider=google_drive&message=zz-request-message"
        ):
            r = ConnectorCallbackStatus().get()
        body = r.get_data(as_text=True)
        script = body[body.index("<script>"):body.index("</script>")]
        assert '{"type": "google_drive_auth_error"}' in script
        assert '"https://app.example.com"' in script
        assert "zz-request-message" not in script

    def test_cancelled_posts_nothing(self, app):
        from docsgpt.api.connector.routes import ConnectorCallbackStatus

        with app.test_request_context(
            "/api/connectors/callback-status?status=cancelled&provider=google_drive"
        ):
            r = ConnectorCallbackStatus().get()
        body = r.get_data(as_text=True)
        assert "const payload = null;" in body
        assert "const targetOrigins = [];" in body


def _fake_google_auth(access_token="at"):
    fake_auth = MagicMock()
    fake_auth.get_authorization_url.side_effect = lambda state: f"https://provider.example.com/auth?state={state}"
    fake_auth.exchange_code_for_tokens.return_value = {"access_token": access_token, "refresh_token": "rt"}
    fake_auth.sanitize_token_info.side_effect = lambda token_info: token_info
    fake_auth.create_credentials_from_token_info.side_effect = RuntimeError("no creds")
    return fake_auth


def _start(app, user, origin=None):
    from flask import request

    from docsgpt.api.connector.routes import ConnectorAuth

    headers = {"Origin": origin} if origin else {}
    with app.test_request_context("/api/connectors/auth?provider=google_drive", headers=headers):
        request.decoded_token = {"sub": user}
        r = ConnectorAuth().get()
    assert r.status_code == 200, r.json
    return r.json["state"]


def _provider_redirect(app, state, code="auth-code", **extra):
    """The provider sending whoever consented to the API callback; the request carries no login."""
    from urllib.parse import urlencode

    from docsgpt.api.connector.routes import ConnectorsCallback

    query = urlencode({"code": code, "state": state, **extra})
    with app.test_request_context(f"/api/connectors/callback?{query}"):
        return ConnectorsCallback().get()


def _complete(app, user, code, state):
    from flask import request

    from docsgpt.api.connector.routes import ConnectorAuthComplete

    with app.test_request_context(
        "/api/connectors/auth/complete", method="POST", json={"code": code, "state": state},
    ):
        request.decoded_token = {"sub": user} if user else None
        return ConnectorAuthComplete().post()


@contextmanager
def _oauth(pg_conn, fake_auth):
    from docsgpt.connectors import service

    with _patch_db(pg_conn), patch(
        "docsgpt.api.connector.routes.ConnectorCreator.create_auth", return_value=fake_auth,
    ), patch.object(service, "ensure_can_store_credentials"):
        yield


def _credentialed_rows(pg_conn, user):
    from sqlalchemy import text

    return pg_conn.execute(
        text("SELECT * FROM connector_sessions WHERE user_id = :u AND encrypted_credentials IS NOT NULL"),
        {"u": user},
    ).fetchall()


class TestApiCallbackForwardsToApp:
    def test_forwards_code_and_state_to_the_app_that_started(self, app, pg_conn):
        from urllib.parse import parse_qs, urlsplit

        from docsgpt.core.settings import settings

        fake_auth = _fake_google_auth()
        with _oauth(pg_conn, fake_auth), patch.object(
            settings, "CONNECTOR_ALLOWED_ORIGINS", "https://app.example.com",
        ):
            state = _start(app, "u-forward", origin="https://app.example.com")
            r = _provider_redirect(app, state, code="the-code")

        target = urlsplit(r.location)
        assert r.status_code == 302
        assert f"{target.scheme}://{target.netloc}{target.path}" == "https://app.example.com/connectors/callback"
        assert parse_qs(target.query) == {"code": ["the-code"], "state": [state]}
        assert r.headers["Cache-Control"] == "no-store"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        # Forwarding neither exchanges the code nor uses up the state.
        fake_auth.exchange_code_for_tokens.assert_not_called()
        with _oauth(pg_conn, fake_auth):
            assert _complete(app, "u-forward", "the-code", state).status_code == 200

    def test_forwards_provider_errors(self, app, pg_conn):
        from docsgpt.core.settings import settings

        with _oauth(pg_conn, _fake_google_auth()), patch.object(
            settings, "CONNECTOR_REDIRECT_BASE_URI", "https://docs.example.com/api/connectors/callback",
        ):
            state = _start(app, "u-forward")
            r = _provider_redirect(app, state, code="", error="access_denied")
        # No Origin or Referer: back to the configured callback's origin.
        assert r.location.startswith("https://docs.example.com/connectors/callback?")
        assert "error=access_denied" in r.location

    def test_unknown_state_renders_an_error_without_forwarding(self, app, pg_conn):
        with _oauth(pg_conn, _fake_google_auth()):
            r = _provider_redirect(app, "never-issued")
        assert r.status_code == 302
        assert r.location.startswith("/api/connectors/callback-status?")
        assert "status=error" in r.location


class TestSignInStartsOnlyFromAllowedOrigins:
    def test_refuses_an_origin_that_may_not_receive_the_code(self, app, pg_conn):
        """The API callback forwards the code to where the sign-in started, so that must be allowed."""
        from sqlalchemy import text
        from flask import request

        from docsgpt.api.connector.routes import ConnectorAuth

        with _oauth(pg_conn, _fake_google_auth()), app.test_request_context(
            "/api/connectors/auth?provider=google_drive", headers={"Origin": "https://attacker.example.com"},
        ):
            request.decoded_token = {"sub": "attacker"}
            r = ConnectorAuth().get()

        assert r.status_code == 400
        assert r.json["code"] == "origin_not_allowed"
        assert pg_conn.execute(text("SELECT count(*) FROM connector_oauth_flows")).scalar() == 0

    def test_same_origin_request_returns_to_the_referer_origin(self, app, pg_conn):
        from flask import request
        from sqlalchemy import text

        from docsgpt.api.connector.routes import ConnectorAuth
        from docsgpt.core.settings import settings

        # The API serves the UI on its public host, which the callback names.
        with _oauth(pg_conn, _fake_google_auth()), patch.object(
            settings, "CONNECTOR_REDIRECT_BASE_URI", "https://docs.example.com/api/connectors/callback",
        ), app.test_request_context(
            "/api/connectors/auth?provider=google_drive",
            base_url="https://docs.example.com",
            headers={"Referer": "https://docs.example.com/settings/connectors"},
        ):
            request.decoded_token = {"sub": "u-same-origin"}
            r = ConnectorAuth().get()

        assert r.status_code == 200
        assert r.json["callback_origin"] == "https://docs.example.com"
        assert pg_conn.execute(text("SELECT return_origin FROM connector_oauth_flows")).scalar() == (
            "https://docs.example.com"
        )

    def test_app_callback_redirect_uri_names_the_popup_origin(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorAuth
        from docsgpt.core.settings import settings
        from flask import request

        with _oauth(pg_conn, _fake_google_auth()), patch.object(
            settings, "CONNECTOR_REDIRECT_BASE_URI", "https://app.example.com/connectors/callback",
        ), app.test_request_context(
            "/api/connectors/auth?provider=google_drive",
            base_url="https://api.example.com",
            headers={"Origin": "https://app.example.com"},
        ):
            request.decoded_token = {"sub": "u-app-callback"}
            r = ConnectorAuth().get()

        assert r.status_code == 200
        assert r.json["callback_origin"] == "https://app.example.com"


class TestHostileHost:
    """The request's Host is the client's to choose; it never decides where codes are forwarded."""

    def _start(self, app, pg_conn, headers):
        from flask import request

        from docsgpt.api.connector.routes import ConnectorAuth
        from docsgpt.core.settings import settings

        with _oauth(pg_conn, _fake_google_auth()), patch.object(
            settings, "CONNECTOR_REDIRECT_BASE_URI", "https://docs.example.com/api/connectors/callback",
        ), patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", None), patch.object(
            settings, "OIDC_FRONTEND_URL", None,
        ), app.test_request_context("/api/connectors/auth?provider=google_drive", headers=headers):
            request.decoded_token = {"sub": "attacker"}
            return ConnectorAuth().get()

    @pytest.mark.parametrize(
        "headers",
        [
            {"Host": "evil.example.net"},
            {"Host": "evil.example.net", "Origin": "http://evil.example.net"},
            {"Host": "evil.example.net", "Referer": "http://evil.example.net/settings"},
        ],
    )
    def test_forged_host_is_not_a_return_origin(self, app, pg_conn, headers):
        from sqlalchemy import text

        r = self._start(app, pg_conn, headers)

        stored = pg_conn.execute(text("SELECT return_origin FROM connector_oauth_flows")).scalars().all()
        assert all("evil.example.net" not in origin for origin in stored)
        assert "evil.example.net" not in (r.json or {}).get("callback_origin", "")

    def test_no_origin_returns_to_the_configured_callback_origin(self, app, pg_conn):
        from sqlalchemy import text

        r = self._start(app, pg_conn, {"Host": "evil.example.net"})

        assert r.status_code == 200
        assert pg_conn.execute(text("SELECT return_origin FROM connector_oauth_flows")).scalar() == (
            "https://docs.example.com"
        )

    def test_forged_origin_with_matching_host_is_refused(self, app, pg_conn):
        r = self._start(app, pg_conn, {"Host": "evil.example.net", "Origin": "http://evil.example.net"})
        assert r.status_code == 400
        assert r.json["code"] == "origin_not_allowed"


class TestSignInBoundToStarter:
    """GHSA-g7m7-6989-4h6x: a sign-in link started by one user and completed by another."""

    def test_victim_consent_on_attackers_link_never_reaches_the_attacker(self, app, pg_conn):
        from urllib.parse import parse_qs, urlsplit

        from docsgpt.api.connector.routes import ConnectorValidateSession
        from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

        fake_auth = _fake_google_auth(access_token="VICTIM-AT")
        with _oauth(pg_conn, fake_auth):
            state = _start(app, "attacker")
            # The victim consents; the API callback stores nothing and forwards
            # the victim's browser to the app's callback page.
            forwarded = _provider_redirect(app, state, code="victim-code")
            assert _credentialed_rows(pg_conn, "attacker") == []
            pending = ConnectorSessionsRepository(pg_conn).get_by_user_provider("attacker", "google_drive")
            assert pending["status"] == "pending"

            # The page posts the code with the victim's own login: refused, and
            # the state is spent, so the attacker cannot use it after.
            params = parse_qs(urlsplit(forwarded.location).query)
            refused = _complete(app, "victim", params["code"][0], params["state"][0])
            assert refused.status_code == 400
            assert _complete(app, "attacker", "victim-code", state).status_code == 400

            with app.test_request_context(
                "/api/connectors/validate-session", method="POST",
                json={"provider": "google_drive", "connection_id": str(pending["id"])},
            ):
                from flask import request

                request.decoded_token = {"sub": "attacker"}
                validated = ConnectorValidateSession().post()

        assert "VICTIM-AT" not in validated.get_data(as_text=True)
        fake_auth.exchange_code_for_tokens.assert_not_called()
        assert _credentialed_rows(pg_conn, "attacker") == []
        assert _credentialed_rows(pg_conn, "victim") == []

    def test_starter_finishes_own_sign_in(self, app, pg_conn):
        from docsgpt.api.connector.routes import _origin_of
        from docsgpt.connectors import service
        from docsgpt.core.settings import settings

        fake_auth = _fake_google_auth(access_token="OWN-AT")
        with _oauth(pg_conn, fake_auth):
            state = _start(app, "alice")
            done = _complete(app, "alice", "alice-code", state)

        assert done.status_code == 200
        assert done.json["provider"] == "google_drive"
        assert done.json["return_origin"] == _origin_of(settings.CONNECTOR_REDIRECT_BASE_URI)
        fake_auth.exchange_code_for_tokens.assert_called_once_with("alice-code")
        rows = _credentialed_rows(pg_conn, "alice")
        assert [str(row.id) for row in rows] == [done.json["connection_id"]]
        assert service.read_secrets(dict(rows[0]._mapping))["token_info"]["access_token"] == "OWN-AT"

    def test_state_is_single_use(self, app, pg_conn):
        fake_auth = _fake_google_auth()
        with _oauth(pg_conn, fake_auth):
            state = _start(app, "alice")
            assert _complete(app, "alice", "code-1", state).status_code == 200
            assert _complete(app, "alice", "code-2", state).status_code == 400
        assert fake_auth.exchange_code_for_tokens.call_count == 1

    def test_forged_state_naming_a_row_is_refused(self, app, pg_conn):
        from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

        row = ConnectorSessionsRepository(pg_conn).upsert("alice", "google_drive", status="pending")
        forged = _encode_state({"provider": "google_drive", "object_id": str(row["id"])})
        fake_auth = _fake_google_auth()
        with _oauth(pg_conn, fake_auth):
            assert _provider_redirect(app, forged).location.startswith("/api/connectors/callback-status?")
            assert _complete(app, "alice", "code", forged).status_code == 400
        fake_auth.exchange_code_for_tokens.assert_not_called()

    def test_expired_state_is_refused(self, app, pg_conn):
        from sqlalchemy import text

        fake_auth = _fake_google_auth()
        with _oauth(pg_conn, fake_auth):
            state = _start(app, "alice")
            pg_conn.execute(text("UPDATE connector_oauth_flows SET expires_at = now() - interval '1 second'"))
            assert _complete(app, "alice", "code", state).status_code == 400
        fake_auth.exchange_code_for_tokens.assert_not_called()

    def test_complete_requires_login(self, app, pg_conn):
        with _oauth(pg_conn, _fake_google_auth()):
            state = _start(app, "alice")
            assert _complete(app, None, "code", state).status_code == 401
            # An unauthenticated attempt does not spend the state.
            assert _complete(app, "alice", "code", state).status_code == 200

    def test_exchange_failure_reports_the_provider(self, app, pg_conn):
        fake_auth = _fake_google_auth()
        fake_auth.exchange_code_for_tokens.side_effect = RuntimeError("invalid_grant")
        with _oauth(pg_conn, fake_auth):
            r = _complete(app, "alice", "code", _start(app, "alice"))
        assert r.status_code == 400
        assert r.json["provider"] == "google_drive"
        assert _credentialed_rows(pg_conn, "alice") == []


class TestAuthUrlReportsCallbackOrigin:
    def test_callback_origin_is_the_app_that_started(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorAuth
        from docsgpt.core.settings import settings

        fake_auth = MagicMock()
        fake_auth.get_authorization_url.return_value = "https://ex/auth?state=x"

        with _patch_db(pg_conn), patch(
            "docsgpt.api.connector.routes.ConnectorCreator.is_supported", return_value=True,
        ), patch(
            "docsgpt.api.connector.routes.ConnectorCreator.create_auth", return_value=fake_auth,
        ), patch.object(
            settings, "CONNECTOR_REDIRECT_BASE_URI", "https://api.example.com/api/connectors/callback",
        ), patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", "https://app.example.com"), app.test_request_context(
            "/api/connectors/auth?provider=google_drive",
            base_url="https://api.example.com",
            headers={"Origin": "https://app.example.com"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u-auth-origin"}
            r = ConnectorAuth().get()

        assert r.status_code == 200
        assert r.json["callback_origin"] == "https://app.example.com"

    @pytest.mark.parametrize(
        "origin, allowed",
        [("https://app.example.com", False), ("https://api.example.com", True), (None, True)],
    )
    def test_starts_only_from_an_allowed_origin(self, app, pg_conn, caplog, origin, allowed):
        from docsgpt.api.connector.routes import ConnectorAuth
        from docsgpt.core.settings import settings

        fake_auth = MagicMock()
        fake_auth.get_authorization_url.return_value = "https://ex/auth?state=x"
        headers = {"Origin": origin} if origin else {}

        with _patch_db(pg_conn), patch(
            "docsgpt.api.connector.routes.ConnectorCreator.is_supported", return_value=True,
        ), patch(
            "docsgpt.api.connector.routes.ConnectorCreator.create_auth", return_value=fake_auth,
        ), patch.object(settings, "CONNECTOR_ALLOWED_ORIGINS", None), patch.object(
            settings, "OIDC_FRONTEND_URL", None,
        ), patch.object(
            settings, "CONNECTOR_REDIRECT_BASE_URI", "https://api.example.com/api/connectors/callback",
        ), app.test_request_context(
            "/api/connectors/auth?provider=google_drive", headers=headers, base_url="https://api.example.com",
        ), caplog.at_level(logging.WARNING):
            from flask import request
            request.decoded_token = {"sub": "u-auth-warn"}
            r = ConnectorAuth().get()

        assert r.status_code == (200 if allowed else 400)
        warned = any("CONNECTOR_ALLOWED_ORIGINS" in rec.getMessage() for rec in caplog.records)
        assert warned is not allowed


class TestDisconnectOwnership:
    def test_requires_authentication(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorDisconnect

        repo = _seed_session(pg_conn, "u-owner", "st-noauth")
        with _patch_db(pg_conn), app.test_request_context(
            "/api/connectors/disconnect", method="POST",
            json={"provider": "google_drive", "session_token": "st-noauth"},
        ):
            from flask import request
            request.decoded_token = None
            r = ConnectorDisconnect().post()

        assert r.status_code == 401
        assert repo.get_by_session_token("st-noauth") is not None

    def test_cannot_delete_another_users_session(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorDisconnect

        repo = _seed_session(pg_conn, "u-victim", "st-victim")
        with _patch_db(pg_conn), app.test_request_context(
            "/api/connectors/disconnect", method="POST",
            json={"provider": "google_drive", "session_token": "st-victim"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u-attacker"}
            ConnectorDisconnect().post()

        assert repo.get_by_session_token("st-victim") is not None

    def test_owner_can_delete_own_session(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorDisconnect

        repo = _seed_session(pg_conn, "u-self", "st-self")
        with _patch_db(pg_conn), app.test_request_context(
            "/api/connectors/disconnect", method="POST",
            json={"provider": "google_drive", "session_token": "st-self"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u-self"}
            r = ConnectorDisconnect().post()

        assert r.status_code == 200
        assert repo.get_by_session_token("st-self") is None


class TestSyncSessionOwnership:
    def test_rejects_foreign_session_token(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorSync
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        _seed_session(pg_conn, "u-victim-sync", "st-victim-sync")
        attacker = "u-attacker-sync"
        src = SourcesRepository(pg_conn).create(
            "drive-src", user_id=attacker,
            remote_data={"provider": "google_drive", "file_ids": ["f"], "folder_ids": []},
        )

        delay = MagicMock()
        with _patch_db(pg_conn), patch(
            "docsgpt.api.connector.routes.ingest_connector_task.delay", delay,
        ), app.test_request_context(
            "/api/connectors/sync", method="POST",
            json={"source_id": str(src["id"]), "session_token": "st-victim-sync"},
        ):
            from flask import request
            request.decoded_token = {"sub": attacker}
            r = ConnectorSync().post()

        assert r.status_code == 401
        delay.assert_not_called()


class TestRemoteUploadSessionOwnership:
    def _post(self, app, pg_conn, user, token, apply_mock):
        from docsgpt.api.user.sources.upload import UploadRemote

        with _patch_db(pg_conn, "docsgpt.api.user.sources.upload"), patch(
            "docsgpt.api.user.sources.upload.ingest_connector_task.apply_async", apply_mock,
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": user, "source": "google_drive", "name": "g",
                "data": json.dumps({"session_token": token, "file_ids": ["f1"]}),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            return UploadRemote().post()

    def test_rejects_foreign_session_token(self, app, pg_conn):
        _seed_session(pg_conn, "u-victim-up", "st-victim-up")
        apply_mock = MagicMock(return_value=MagicMock(id="t"))

        r = self._post(app, pg_conn, "u-attacker-up", "st-victim-up", apply_mock)

        assert r.status_code == 401
        apply_mock.assert_not_called()

    def test_accepts_own_session_token(self, app, pg_conn):
        _seed_session(pg_conn, "u-owner-up", "st-owner-up")
        apply_mock = MagicMock(return_value=MagicMock(id="t"))

        r = self._post(app, pg_conn, "u-owner-up", "st-owner-up", apply_mock)

        assert r.status_code == 200
        apply_mock.assert_called_once()

    def test_rejects_session_issued_for_another_provider(self, app, pg_conn):
        _seed_session(pg_conn, "u-prov-up", "st-prov-up", provider="share_point")
        apply_mock = MagicMock(return_value=MagicMock(id="t"))

        r = self._post(app, pg_conn, "u-prov-up", "st-prov-up", apply_mock)

        assert r.status_code == 401
        apply_mock.assert_not_called()


class TestValidateSessionOwnership:
    def test_rejects_foreign_session_token(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorValidateSession

        _seed_session(pg_conn, "u-victim-val", "st-victim-val", token_info={"access_token": "victim-at"})
        create_auth = MagicMock()
        with _patch_db(pg_conn), patch(
            "docsgpt.api.connector.routes.ConnectorCreator.create_auth", create_auth,
        ), app.test_request_context(
            "/api/connectors/validate-session", method="POST",
            json={"provider": "google_drive", "session_token": "st-victim-val"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u-attacker-val"}
            r = ConnectorValidateSession().post()

        assert r.status_code == 401
        assert "victim-at" not in r.get_data(as_text=True)
        create_auth.assert_not_called()


class TestSessionProviderBinding:
    def _files(self, app, pg_conn, user, provider, token, create_connector):
        from docsgpt.api.connector.routes import ConnectorFiles

        with _patch_db(pg_conn), patch(
            "docsgpt.api.connector.routes.ConnectorCreator.create_connector", create_connector,
        ), app.test_request_context(
            "/api/connectors/files", method="POST", json={"provider": provider, "session_token": token},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            return ConnectorFiles().post()

    def test_files_rejects_session_issued_for_another_provider(self, app, pg_conn):
        _seed_session(pg_conn, "u-files-prov", "st-files-prov", provider="google_drive")
        create_connector = MagicMock()

        r = self._files(app, pg_conn, "u-files-prov", "share_point", "st-files-prov", create_connector)

        assert r.status_code == 401
        create_connector.assert_not_called()

    def test_files_matches_provider_case_insensitively(self, app, pg_conn):
        _seed_session(pg_conn, "u-files-case", "st-files-case", provider="google_drive")
        create_connector = MagicMock(return_value=MagicMock(load_data=MagicMock(return_value=[]), next_page_token=None))

        r = self._files(app, pg_conn, "u-files-case", "Google_Drive", "st-files-case", create_connector)

        assert r.status_code == 200
        create_connector.assert_called_once()

    def test_validate_session_rejects_session_issued_for_another_provider(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorValidateSession

        _seed_session(
            pg_conn, "u-val-prov", "st-val-prov", provider="google_drive", token_info={"access_token": "at"},
        )
        create_auth = MagicMock()
        with _patch_db(pg_conn), patch(
            "docsgpt.api.connector.routes.ConnectorCreator.create_auth", create_auth,
        ), app.test_request_context(
            "/api/connectors/validate-session", method="POST",
            json={"provider": "share_point", "session_token": "st-val-prov"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u-val-prov"}
            r = ConnectorValidateSession().post()

        assert r.status_code == 401
        create_auth.assert_not_called()

    def test_sync_rejects_session_issued_for_another_provider(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorSync
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        user = "u-sync-prov"
        _seed_session(pg_conn, user, "st-sync-prov", provider="share_point")
        src = SourcesRepository(pg_conn).create(
            "drive-src", user_id=user,
            remote_data={"provider": "google_drive", "file_ids": ["f"], "folder_ids": []},
        )
        delay = MagicMock()
        with _patch_db(pg_conn), patch(
            "docsgpt.api.connector.routes.ingest_connector_task.delay", delay,
        ), app.test_request_context(
            "/api/connectors/sync", method="POST",
            json={"source_id": str(src["id"]), "session_token": "st-sync-prov"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            r = ConnectorSync().post()

        assert r.status_code == 401
        delay.assert_not_called()
