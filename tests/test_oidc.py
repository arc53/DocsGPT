"""Tests for the OIDC SSO module (application/api/oidc/)."""

import base64
import hashlib
import json
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk
from jose import jwt as jose_jwt

from application.core.settings import settings

ISSUER = "https://idp.test/app/"
CLIENT_ID = "docsgpt-test"
FRONTEND_URL = "http://frontend.test"
JWT_SECRET = "test-oidc-secret"
KID = "test-key-1"
BCL_EVENT = "http://schemas.openid.net/event/backchannel-logout"

DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": "https://idp.test/authorize",
    "token_endpoint": "https://idp.test/token",
    "jwks_uri": "https://idp.test/jwks",
    "userinfo_endpoint": "https://idp.test/userinfo",
    "end_session_endpoint": "https://idp.test/end-session",
}


def _generate_rsa_pem():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


PRIVATE_PEM = _generate_rsa_pem()
PUBLIC_JWK = {
    **jwk.construct(PRIVATE_PEM, algorithm="RS256").public_key().to_dict(),
    "kid": KID,
    "use": "sig",
}


def sign_id_token(claims, kid=KID, key=PRIVATE_PEM, algorithm="RS256"):
    return jose_jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})


def id_token_claims(**overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "oidc-user-1",
        "email": "user@example.com",
        "name": "OIDC User",
        "nonce": "test-nonce",
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    return claims


def logout_token_claims(**overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "oidc-user-1",
        "iat": now,
        "jti": "bcl-jti-1",
        "events": {BCL_EVENT: {}},
    }
    claims.update(overrides)
    return claims


def make_session_token(**overrides):
    """Mint a session JWT the way the callback does, for refresh-route tests."""
    now = int(time.time())
    payload = {
        "sub": "oidc-user-1",
        "jti": "jti-1",
        "iat": now,
        "exp": now + 3600,
        "oidc_sub": "oidc-user-1",
    }
    payload.update(overrides)
    return jose_jwt.encode(payload, JWT_SECRET, algorithm="HS256")


class FakeRedis:
    """Minimal stand-in for the redis-py client used by the oidc routes."""

    def __init__(self):
        self.store = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value.encode("utf-8") if isinstance(value, str) else value
        return True

    def getdel(self, key):
        return self.store.pop(key, None)


def make_fake_get(jwks_keys, discovery=None, userinfo=None, userinfo_status=200):
    """requests.get stub serving discovery + JWKS (+ optional userinfo); ``jwks_keys`` is mutable."""
    document = dict(DISCOVERY if discovery is None else discovery)

    def fake_get(url, timeout=None, headers=None):
        resp = Mock()
        resp.status_code = 200
        if "openid-configuration" in url:
            resp.json.return_value = dict(document)
        elif url == document["jwks_uri"]:
            resp.json.return_value = {"keys": list(jwks_keys)}
        elif userinfo is not None and url == document.get("userinfo_endpoint"):
            resp.status_code = userinfo_status
            resp.json.return_value = dict(userinfo)
        else:
            resp.status_code = 404
        return resp

    return fake_get


@pytest.fixture(autouse=True)
def oidc_settings(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_TYPE", "oidc")
    monkeypatch.setattr(settings, "OIDC_ISSUER", ISSUER)
    monkeypatch.setattr(settings, "OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", None)
    monkeypatch.setattr(settings, "OIDC_SCOPES", "openid profile email")
    monkeypatch.setattr(settings, "OIDC_USER_ID_CLAIM", "sub")
    monkeypatch.setattr(settings, "OIDC_FRONTEND_URL", FRONTEND_URL)
    monkeypatch.setattr(settings, "OIDC_REDIRECT_URI", None)
    monkeypatch.setattr(settings, "OIDC_SESSION_LIFETIME_SECONDS", 28800)
    monkeypatch.setattr(settings, "OIDC_PROVIDER_NAME", None)
    monkeypatch.setattr(settings, "OIDC_ALLOWED_GROUPS", None)
    monkeypatch.setattr(settings, "OIDC_GROUPS_CLAIM", "groups")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", JWT_SECRET)


@pytest.fixture(autouse=True)
def reset_provider_cache():
    from application.api.oidc import provider

    provider.reset_cache()
    yield
    provider.reset_cache()


@pytest.mark.unit
class TestProviderDiscovery:

    def test_discovery_fetched_once_then_cached(self):
        from application.api.oidc import provider

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            first = provider.get_discovery()
            second = provider.get_discovery()

        assert first == second == DISCOVERY
        assert mock_requests.get.call_count == 1

    def test_discovery_refetched_after_ttl(self):
        from application.api.oidc import provider

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            provider.get_discovery()
            provider._cache["discovery_at"] -= provider.DISCOVERY_TTL_SECONDS + 1
            provider.get_discovery()

        assert mock_requests.get.call_count == 2

    def test_discovery_failure_raises_oidc_error(self):
        from application.api.oidc import provider

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.return_value = Mock(status_code=502)
            mock_requests.RequestException = Exception
            with pytest.raises(provider.OIDCError):
                provider.get_discovery()


@pytest.mark.unit
class TestValidateIdToken:

    def _validate(self, token, nonce="test-nonce", jwks_keys=None):
        from application.api.oidc import provider

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get(
                jwks_keys if jwks_keys is not None else [PUBLIC_JWK]
            )
            return provider.validate_id_token(token, nonce)

    def test_valid_token_returns_claims(self):
        claims = self._validate(sign_id_token(id_token_claims()))
        assert claims["sub"] == "oidc-user-1"
        assert claims["email"] == "user@example.com"

    def test_nonce_mismatch_rejected(self):
        from application.api.oidc import provider

        with pytest.raises(provider.OIDCError):
            self._validate(sign_id_token(id_token_claims(nonce="other")))

    def test_wrong_audience_rejected(self):
        from application.api.oidc import provider

        with pytest.raises(provider.OIDCError):
            self._validate(sign_id_token(id_token_claims(aud="someone-else")))

    def test_wrong_issuer_rejected(self):
        from application.api.oidc import provider

        with pytest.raises(provider.OIDCError):
            self._validate(sign_id_token(id_token_claims(iss="https://evil.test/")))

    def test_expired_beyond_leeway_rejected(self):
        from application.api.oidc import provider

        expired = id_token_claims(exp=int(time.time()) - 120)
        with pytest.raises(provider.OIDCError):
            self._validate(sign_id_token(expired))

    def test_expired_within_leeway_accepted(self):
        barely = id_token_claims(exp=int(time.time()) - 30)
        claims = self._validate(sign_id_token(barely))
        assert claims["sub"] == "oidc-user-1"

    def test_hs256_id_token_rejected(self):
        from application.api.oidc import provider

        forged = jose_jwt.encode(
            id_token_claims(), JWT_SECRET, algorithm="HS256", headers={"kid": KID}
        )
        with pytest.raises(provider.OIDCError):
            self._validate(forged)

    def test_rekeyed_idp_with_reused_kid_recovers(self):
        # The IdP replaced its signing key but kept the kid (mock IdP
        # restarts, sloppy rotations): the cached key fails the signature,
        # one forced JWKS refetch picks up the new key and validation
        # succeeds.
        from application.api.oidc import provider

        new_pem = _generate_rsa_pem()
        new_jwk = {
            **jwk.construct(new_pem, algorithm="RS256").public_key().to_dict(),
            "kid": KID,
            "use": "sig",
        }
        token = sign_id_token(id_token_claims(), key=new_pem)

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            provider.get_jwks()  # prime the cache with the OLD key
            mock_requests.get.side_effect = make_fake_get([new_jwk])
            claims = provider.validate_id_token(token, "test-nonce")

        assert claims["sub"] == "oidc-user-1"

    def test_unknown_kid_triggers_single_jwks_refetch(self):
        from application.api.oidc import provider

        rotated_pem = _generate_rsa_pem()
        rotated_jwk = {
            **jwk.construct(rotated_pem, algorithm="RS256").public_key().to_dict(),
            "kid": "rotated-key",
            "use": "sig",
        }
        token = sign_id_token(id_token_claims(), kid="rotated-key", key=rotated_pem)

        jwks_keys = [PUBLIC_JWK]
        jwks_calls = []

        def fake_get(url, timeout=None):
            resp = Mock()
            resp.status_code = 200
            if "openid-configuration" in url:
                resp.json.return_value = dict(DISCOVERY)
            elif url == DISCOVERY["jwks_uri"]:
                jwks_calls.append(url)
                # Old key on first fetch, rotated key appears on refetch.
                resp.json.return_value = {"keys": list(jwks_keys)}
                jwks_keys.append(rotated_jwk)
            else:
                resp.status_code = 404
            return resp

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = fake_get
            claims = provider.validate_id_token(token, "test-nonce")

        assert claims["sub"] == "oidc-user-1"
        assert len(jwks_calls) == 2


@pytest.mark.unit
class TestExchangeCode:

    def test_posts_code_and_verifier(self):
        from application.api.oidc import provider

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = Mock(
                status_code=200, json=Mock(return_value={"id_token": "x"})
            )
            tokens = provider.exchange_code("auth-code", "verifier-123", "https://app.test/cb")

        assert tokens == {"id_token": "x"}
        args, kwargs = mock_requests.post.call_args
        assert args[0] == DISCOVERY["token_endpoint"]
        sent = kwargs["data"]
        assert sent["grant_type"] == "authorization_code"
        assert sent["code"] == "auth-code"
        assert sent["code_verifier"] == "verifier-123"
        assert sent["redirect_uri"] == "https://app.test/cb"
        assert sent["client_id"] == CLIENT_ID
        assert "client_secret" not in sent

    def test_includes_client_secret_when_post_method_supported(self, monkeypatch):
        from application.api.oidc import provider

        monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "s3cret")
        discovery = {**DISCOVERY, "token_endpoint_auth_methods_supported": ["client_secret_post"]}
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK], discovery=discovery)
            mock_requests.post.return_value = Mock(
                status_code=200, json=Mock(return_value={"id_token": "x"})
            )
            provider.exchange_code("auth-code", "verifier-123", "https://app.test/cb")

        assert mock_requests.post.call_args.kwargs["data"]["client_secret"] == "s3cret"

    def test_non_200_raises_oidc_error(self):
        from application.api.oidc import provider

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = Mock(status_code=400, text="bad request")
            with pytest.raises(provider.OIDCError):
                provider.exchange_code("auth-code", "verifier-123", "https://app.test/cb")


@pytest.mark.unit
class TestTokenEndpointAuthMethod:

    def _exchange(self, discovery=None):
        from application.api.oidc import provider

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK], discovery=discovery)
            mock_requests.post.return_value = Mock(
                status_code=200, json=Mock(return_value={"id_token": "x"})
            )
            provider.exchange_code("auth-code", "verifier-123", "https://app.test/cb")
        return mock_requests.post.call_args

    def test_basic_auth_when_discovery_omits_methods(self, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "s3cret")
        call = self._exchange()

        assert call.kwargs["auth"] == (CLIENT_ID, "s3cret")
        assert "client_secret" not in call.kwargs["data"]

    def test_basic_auth_when_only_client_secret_basic_supported(self, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "s3cret")
        discovery = {**DISCOVERY, "token_endpoint_auth_methods_supported": ["client_secret_basic"]}
        call = self._exchange(discovery)

        assert call.kwargs["auth"] == (CLIENT_ID, "s3cret")
        assert "client_secret" not in call.kwargs["data"]

    def test_post_auth_when_client_secret_post_supported(self, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "s3cret")
        discovery = {
            **DISCOVERY,
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
        }
        call = self._exchange(discovery)

        assert call.kwargs["data"]["client_secret"] == "s3cret"
        assert "auth" not in call.kwargs

    def test_no_auth_kwarg_when_no_secret(self):
        call = self._exchange()

        assert "auth" not in call.kwargs
        assert "client_secret" not in call.kwargs["data"]


@pytest.mark.unit
class TestFetchUserinfo:

    def test_sends_bearer_token_and_returns_claims(self):
        from application.api.oidc import provider

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get(
                [PUBLIC_JWK], userinfo={"sub": "oidc-user-1", "groups": ["devs"]}
            )
            info = provider.fetch_userinfo("at-123")

        assert info == {"sub": "oidc-user-1", "groups": ["devs"]}
        userinfo_calls = [
            call
            for call in mock_requests.get.call_args_list
            if call.args[0] == DISCOVERY["userinfo_endpoint"]
        ]
        assert len(userinfo_calls) == 1
        assert userinfo_calls[0].kwargs["headers"]["Authorization"] == "Bearer at-123"

    def test_missing_endpoint_raises(self):
        from application.api.oidc import provider

        discovery = {k: v for k, v in DISCOVERY.items() if k != "userinfo_endpoint"}
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK], discovery=discovery)
            with pytest.raises(provider.OIDCError):
                provider.fetch_userinfo("at-123")

    def test_non_200_raises(self):
        from application.api.oidc import provider

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get(
                [PUBLIC_JWK], userinfo={"sub": "x"}, userinfo_status=500
            )
            with pytest.raises(provider.OIDCError):
                provider.fetch_userinfo("at-123")


@pytest.mark.unit
class TestRefreshGrant:

    def test_posts_refresh_token_grant(self):
        from application.api.oidc import provider

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = Mock(
                status_code=200, json=Mock(return_value={"access_token": "at-2"})
            )
            tokens = provider.refresh_grant("rt-old")

        assert tokens == {"access_token": "at-2"}
        sent = mock_requests.post.call_args.kwargs["data"]
        assert sent["grant_type"] == "refresh_token"
        assert sent["refresh_token"] == "rt-old"
        assert sent["client_id"] == CLIENT_ID


@pytest.mark.unit
class TestValidateIdTokenNonceOptional:

    def test_nonce_none_skips_nonce_check(self):
        from application.api.oidc import provider

        claims = id_token_claims()
        del claims["nonce"]
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            decoded = provider.validate_id_token(sign_id_token(claims), nonce=None)

        assert decoded["sub"] == "oidc-user-1"

    def test_nonce_none_accepts_token_that_still_has_nonce(self):
        from application.api.oidc import provider

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            decoded = provider.validate_id_token(sign_id_token(id_token_claims()), nonce=None)

        assert decoded["sub"] == "oidc-user-1"


@pytest.mark.unit
class TestValidateLogoutToken:

    def _validate(self, token, jwks_keys=None):
        from application.api.oidc import provider

        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get(
                jwks_keys if jwks_keys is not None else [PUBLIC_JWK]
            )
            return provider.validate_logout_token(token)

    def test_valid_sub_token_returns_claims(self):
        claims = self._validate(sign_id_token(logout_token_claims()))
        assert claims["sub"] == "oidc-user-1"

    def test_valid_sid_only_token(self):
        claims = logout_token_claims(sid="sess-9")
        del claims["sub"]
        assert self._validate(sign_id_token(claims))["sid"] == "sess-9"

    def test_missing_events_claim_rejected(self):
        from application.api.oidc import provider

        claims = logout_token_claims()
        del claims["events"]
        with pytest.raises(provider.OIDCError):
            self._validate(sign_id_token(claims))

    def test_wrong_event_uri_rejected(self):
        from application.api.oidc import provider

        claims = logout_token_claims(events={"http://other.event/uri": {}})
        with pytest.raises(provider.OIDCError):
            self._validate(sign_id_token(claims))

    def test_nonce_prohibited(self):
        from application.api.oidc import provider

        with pytest.raises(provider.OIDCError):
            self._validate(sign_id_token(logout_token_claims(nonce="n-1")))

    def test_missing_sub_and_sid_rejected(self):
        from application.api.oidc import provider

        claims = logout_token_claims()
        del claims["sub"]
        with pytest.raises(provider.OIDCError):
            self._validate(sign_id_token(claims))

    def test_wrong_audience_rejected(self):
        from application.api.oidc import provider

        with pytest.raises(provider.OIDCError):
            self._validate(sign_id_token(logout_token_claims(aud="someone-else")))


class _WatermarkRedis:
    """Minimal redis stand-in for the denylist (set + mget)."""

    def __init__(self):
        self.store = {}

    def set(self, key, value, ex=None):
        self.store[key] = value.encode("utf-8") if isinstance(value, str) else value
        return True

    def mget(self, keys):
        return [self.store.get(key) for key in keys]


@pytest.mark.unit
class TestDenylistWatermark:
    """is_denied compares the token iat against the stored revocation timestamp."""

    def _wire(self, monkeypatch):
        from application.api.oidc import denylist

        redis = _WatermarkRedis()
        monkeypatch.setattr(denylist, "get_redis_instance", lambda: redis)
        return denylist, redis

    def test_session_before_revocation_denied_after_allowed(self, monkeypatch):
        denylist, redis = self._wire(monkeypatch)
        denylist.deny_user("u1")
        watermark = int(redis.store[denylist._USER_PREFIX + "u1"])
        # Issued before the revocation -> denied.
        assert denylist.is_denied({"sub": "u1", "iat": watermark - 5}) is True
        # Issued at/after the revocation (e.g. an immediate re-login) -> allowed.
        assert denylist.is_denied({"sub": "u1", "iat": watermark + 5}) is False

    def test_unrelated_identity_not_denied(self, monkeypatch):
        denylist, redis = self._wire(monkeypatch)
        denylist.deny_user("u1")
        watermark = int(redis.store[denylist._USER_PREFIX + "u1"])
        assert denylist.is_denied({"sub": "u2", "iat": watermark - 5}) is False

    def test_missing_iat_is_conservatively_denied(self, monkeypatch):
        denylist, _ = self._wire(monkeypatch)
        denylist.deny_idp_sub("idp-1")
        assert denylist.is_denied({"oidc_sub": "idp-1"}) is True

    def test_no_entry_means_allowed(self, monkeypatch):
        denylist, _ = self._wire(monkeypatch)
        assert denylist.is_denied({"sub": "u1", "iat": 1}) is False


@pytest.fixture(scope="module")
def app():
    with patch("application.app.handle_auth", return_value={"sub": "test_user"}):
        from application.app import app as flask_app

        flask_app.config["TESTING"] = True
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def fake_redis():
    redis = FakeRedis()
    with patch("application.api.oidc.routes.get_redis_instance", return_value=redis):
        yield redis


@pytest.fixture
def db_mocks():
    """Patch the DB seams of the oidc routes; default: unknown user, active on upsert."""
    users_repo = Mock()
    users_repo.get.return_value = None
    users_repo.upsert.side_effect = lambda user_id: {"user_id": user_id, "active": True}
    events_repo = Mock()

    @contextmanager
    def fake_session():
        yield Mock()

    with patch("application.api.oidc.routes.db_session", fake_session), patch(
        "application.api.oidc.routes.db_readonly", fake_session
    ), patch(
        "application.api.oidc.routes.UsersRepository", return_value=users_repo
    ), patch(
        "application.api.oidc.routes.AuthEventsRepository", return_value=events_repo
    ):
        yield SimpleNamespace(users=users_repo, events=events_repo)


def _seed_state(client, fake_redis, state="state-1", nonce="nonce-1"):
    fake_redis.set(
        f"oidc:state:{state}",
        json.dumps({"code_verifier": "verifier-1", "nonce": nonce}),
    )
    # Mirror the browser cookie the login route sets, so the callback's
    # state-binding (CSRF) check passes.
    client.set_cookie("oidc_state", state)
    return state, nonce


def _signed_token_response(claims, **extra):
    """Token-endpoint response carrying an id_token signed over ``claims``."""
    body = {
        "access_token": "at",
        "token_type": "Bearer",
        "id_token": sign_id_token(claims),
    }
    body.update(extra)
    return Mock(status_code=200, json=Mock(return_value=body))


def _mint_id_token_response(stored_nonce, **extra):
    return _signed_token_response(id_token_claims(nonce=stored_nonce), **extra)


@pytest.mark.unit
class TestLoginRoute:

    def test_redirects_to_idp_with_pkce_and_stores_state(self, client, fake_redis):
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            response = client.get("/api/auth/oidc/login")

        assert response.status_code == 302
        location = response.headers["Location"]
        assert location.startswith(DISCOVERY["authorization_endpoint"])
        params = {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}
        assert params["response_type"] == "code"
        assert params["client_id"] == CLIENT_ID
        assert params["scope"] == "openid profile email"
        assert params["code_challenge_method"] == "S256"
        assert params["redirect_uri"].endswith("/api/auth/oidc/callback")

        stored = json.loads(fake_redis.store[f"oidc:state:{params['state']}"])
        assert stored["nonce"] == params["nonce"]
        expected_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(stored["code_verifier"].encode("ascii")).digest()
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        assert params["code_challenge"] == expected_challenge

    def test_503_when_redis_unavailable(self, client):
        with patch("application.api.oidc.routes.get_redis_instance", return_value=None):
            response = client.get("/api/auth/oidc/login")
        assert response.status_code == 503

    def test_503_when_discovery_fails(self, client, fake_redis):
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.return_value = Mock(status_code=502)
            mock_requests.RequestException = Exception
            response = client.get("/api/auth/oidc/login")
        assert response.status_code == 503


@pytest.mark.unit
class TestOidcDisabled:
    """Outside AUTH_TYPE=oidc the routes 404 cleanly instead of 500-ing."""

    def test_routes_404_when_not_oidc(self, client, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_TYPE", "session_jwt")
        assert client.get("/api/auth/oidc/login").status_code == 404
        assert client.get("/api/auth/oidc/logout").status_code == 404
        # Even a (would-be) RS256 logout token must not reach discovery.
        post = client.post(
            "/api/auth/oidc/backchannel-logout", data={"logout_token": "x"}
        )
        assert post.status_code == 404


@pytest.mark.unit
class TestCallbackRoute:

    @pytest.fixture(autouse=True)
    def _db(self, db_mocks):
        self.db = db_mocks

    def _seed_state(self, client, fake_redis, state="state-1", nonce="nonce-1"):
        return _seed_state(client, fake_redis, state=state, nonce=nonce)

    def test_happy_path_mints_session_and_redirects_with_handoff(self, client, fake_redis):
        state, nonce = self._seed_state(client, fake_redis)
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = _mint_id_token_response(nonce)
            response = client.get(f"/api/auth/oidc/callback?code=abc&state={state}")

        assert response.status_code == 302
        location = response.headers["Location"]
        assert location.startswith(f"{FRONTEND_URL}/#oidc_code=")
        handoff = location.split("#oidc_code=", 1)[1]

        session_token = fake_redis.store[f"oidc:handoff:{handoff}"].decode("utf-8")
        decoded = jose_jwt.decode(session_token, JWT_SECRET, algorithms=["HS256"])
        assert decoded["sub"] == "oidc-user-1"
        assert decoded["email"] == "user@example.com"
        assert decoded["name"] == "OIDC User"
        now = int(time.time())
        assert now + 28800 - 60 <= decoded["exp"] <= now + 28800 + 60
        # State must have been consumed.
        assert f"oidc:state:{state}" not in fake_redis.store

    def test_replayed_state_rejected(self, client, fake_redis):
        state, nonce = self._seed_state(client, fake_redis)
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = _mint_id_token_response(nonce)
            first = client.get(f"/api/auth/oidc/callback?code=abc&state={state}")
            replay = client.get(f"/api/auth/oidc/callback?code=abc&state={state}")

        assert "#oidc_code=" in first.headers["Location"]
        assert replay.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=invalid_state"

    def test_unknown_state_rejected(self, client, fake_redis):
        # Cookie matches the state (passes the CSRF binding) but the state was
        # never stored in Redis — the server-side lookup must still reject it.
        client.set_cookie("oidc_state", "forged")
        response = client.get("/api/auth/oidc/callback?code=abc&state=forged")
        assert response.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=invalid_state"

    def test_missing_state_cookie_rejected(self, client, fake_redis):
        # State is valid server-side, but no browser cookie binds it — a forged
        # cross-browser callback (login CSRF) lands here.
        self._seed_state(client, fake_redis)
        client.delete_cookie("oidc_state")
        response = client.get("/api/auth/oidc/callback?code=abc&state=state-1")
        assert response.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=invalid_state"

    def test_mismatched_state_cookie_rejected(self, client, fake_redis):
        # The cookie carries a different login attempt's state than the query
        # param — reject rather than complete an attacker-seeded flow.
        self._seed_state(client, fake_redis)
        client.set_cookie("oidc_state", "attacker-state")
        response = client.get("/api/auth/oidc/callback?code=abc&state=state-1")
        assert response.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=invalid_state"

    def test_idp_error_forwarded(self, client, fake_redis):
        response = client.get("/api/auth/oidc/callback?error=access_denied")
        assert (
            response.headers["Location"]
            == f"{FRONTEND_URL}/#oidc_error=access_denied"
        )

    def test_nonce_mismatch_fails_auth(self, client, fake_redis):
        state, _ = self._seed_state(client, fake_redis, nonce="nonce-1")
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = _mint_id_token_response("evil-nonce")
            response = client.get(f"/api/auth/oidc/callback?code=abc&state={state}")

        assert response.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=auth_failed"

    def test_missing_user_id_claim(self, client, fake_redis, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_USER_ID_CLAIM", "preferred_username")
        state, nonce = self._seed_state(client, fake_redis)
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = _mint_id_token_response(nonce)
            response = client.get(f"/api/auth/oidc/callback?code=abc&state={state}")

        assert response.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=missing_claim"

    def test_optional_profile_claims_omitted_when_absent(self, client, fake_redis):
        state, nonce = self._seed_state(client, fake_redis)
        claims = id_token_claims(nonce=nonce)
        del claims["email"]
        del claims["name"]
        token_response = Mock(
            status_code=200,
            json=Mock(return_value={"id_token": sign_id_token(claims)}),
        )
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = token_response
            response = client.get(f"/api/auth/oidc/callback?code=abc&state={state}")

        handoff = response.headers["Location"].split("#oidc_code=", 1)[1]
        session_token = fake_redis.store[f"oidc:handoff:{handoff}"].decode("utf-8")
        decoded = jose_jwt.decode(session_token, JWT_SECRET, algorithms=["HS256"])
        assert "email" not in decoded
        assert "name" not in decoded


@pytest.mark.unit
class TestTokenRoute:

    def test_handoff_code_single_use(self, client, fake_redis):
        fake_redis.set("oidc:handoff:code-1", "minted-jwt")
        first = client.post("/api/auth/oidc/token", json={"code": "code-1"})
        replay = client.post("/api/auth/oidc/token", json={"code": "code-1"})

        assert first.status_code == 200
        assert first.get_json() == {"token": "minted-jwt"}
        assert replay.status_code == 401

    def test_unknown_code_rejected(self, client, fake_redis):
        response = client.post("/api/auth/oidc/token", json={"code": "nope"})
        assert response.status_code == 401

    def test_missing_body_rejected(self, client, fake_redis):
        response = client.post("/api/auth/oidc/token")
        assert response.status_code == 401

    def test_503_when_redis_unavailable(self, client):
        with patch("application.api.oidc.routes.get_redis_instance", return_value=None):
            response = client.post("/api/auth/oidc/token", json={"code": "code-1"})
        assert response.status_code == 503


@pytest.mark.unit
class TestLogoutRoute:

    def test_redirects_to_idp_end_session(self, client):
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            response = client.get("/api/auth/oidc/logout")

        assert response.status_code == 302
        location = response.headers["Location"]
        assert location.startswith(DISCOVERY["end_session_endpoint"])
        params = {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}
        assert params["post_logout_redirect_uri"] == FRONTEND_URL
        assert params["client_id"] == CLIENT_ID

    def test_falls_back_to_frontend_when_discovery_fails(self, client):
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.return_value = Mock(status_code=502)
            mock_requests.RequestException = Exception
            response = client.get("/api/auth/oidc/logout")

        assert response.status_code == 302
        assert response.headers["Location"] == FRONTEND_URL


@pytest.mark.unit
class TestCallbackGroups:

    @pytest.fixture(autouse=True)
    def _db(self, db_mocks):
        self.db = db_mocks

    def _callback(self, client, fake_redis, claims, userinfo=None, userinfo_status=200):
        state, nonce = _seed_state(client, fake_redis)
        claims = {**claims, "nonce": nonce}
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get(
                [PUBLIC_JWK], userinfo=userinfo, userinfo_status=userinfo_status
            )
            mock_requests.post.return_value = _signed_token_response(claims)
            return client.get(f"/api/auth/oidc/callback?code=abc&state={state}")

    def test_login_allowed_when_group_matches(self, client, fake_redis, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_ALLOWED_GROUPS", "admins, devs")
        response = self._callback(client, fake_redis, id_token_claims(groups=["devs", "qa"]))

        assert "#oidc_code=" in response.headers["Location"]

    def test_login_denied_when_no_group_matches(self, client, fake_redis, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_ALLOWED_GROUPS", "admins, devs")
        response = self._callback(client, fake_redis, id_token_claims(groups=["qa"]))

        assert response.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=not_authorized"
        call = self.db.events.insert.call_args
        assert call.args == ("oidc-user-1", "oidc_login_denied")
        assert call.kwargs["metadata"] == {"reason": "not_authorized", "groups": ["qa"]}

    def test_single_string_group_claim_coerced_to_list(self, client, fake_redis, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_ALLOWED_GROUPS", "devs")
        response = self._callback(client, fake_redis, id_token_claims(groups="devs"))

        assert "#oidc_code=" in response.headers["Location"]

    def test_allow_everyone_when_allowlist_unset(self, client, fake_redis):
        response = self._callback(client, fake_redis, id_token_claims())

        assert "#oidc_code=" in response.headers["Location"]

    def test_custom_groups_claim_name(self, client, fake_redis, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_ALLOWED_GROUPS", "admin")
        monkeypatch.setattr(settings, "OIDC_GROUPS_CLAIM", "roles")
        response = self._callback(client, fake_redis, id_token_claims(roles=["admin"]))

        assert "#oidc_code=" in response.headers["Location"]

    def test_missing_groups_claim_recovered_via_userinfo(self, client, fake_redis, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_ALLOWED_GROUPS", "devs")
        response = self._callback(
            client,
            fake_redis,
            id_token_claims(),
            userinfo={"sub": "oidc-user-1", "groups": ["devs"]},
        )

        assert "#oidc_code=" in response.headers["Location"]

    def test_userinfo_sub_mismatch_fails_auth(self, client, fake_redis, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_ALLOWED_GROUPS", "devs")
        response = self._callback(
            client,
            fake_redis,
            id_token_claims(),
            userinfo={"sub": "intruder", "groups": ["devs"]},
        )

        assert response.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=auth_failed"

    def test_userinfo_failure_is_nonfatal_then_groups_denied(self, client, fake_redis, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_ALLOWED_GROUPS", "devs")
        response = self._callback(
            client,
            fake_redis,
            id_token_claims(),
            userinfo={"sub": "oidc-user-1", "groups": ["devs"]},
            userinfo_status=500,
        )

        assert response.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=not_authorized"

    def test_missing_user_id_claim_recovered_via_userinfo(self, client, fake_redis, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_USER_ID_CLAIM", "preferred_username")
        response = self._callback(
            client,
            fake_redis,
            id_token_claims(),
            userinfo={"sub": "oidc-user-1", "preferred_username": "alice"},
        )

        handoff = response.headers["Location"].split("#oidc_code=", 1)[1]
        session_token = fake_redis.store[f"oidc:handoff:{handoff}"].decode("utf-8")
        decoded = jose_jwt.decode(session_token, JWT_SECRET, algorithms=["HS256"])
        assert decoded["sub"] == "alice"


@pytest.mark.unit
class TestCallbackUserGate:

    @pytest.fixture(autouse=True)
    def _db(self, db_mocks):
        self.db = db_mocks

    def _callback(self, client, fake_redis):
        state, nonce = _seed_state(client, fake_redis)
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = _mint_id_token_response(nonce)
            return client.get(f"/api/auth/oidc/callback?code=abc&state={state}")

    def test_disabled_user_rejected(self, client, fake_redis):
        self.db.users.get.return_value = {"user_id": "oidc-user-1", "active": False}
        response = self._callback(client, fake_redis)

        assert response.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=account_disabled"
        assert not any(key.startswith("oidc:handoff:") for key in fake_redis.store)
        call = self.db.events.insert.call_args
        assert call.args == ("oidc-user-1", "oidc_login_denied")
        assert call.kwargs["metadata"] == {"reason": "account_disabled"}

    def test_new_user_provisioned_and_login_audited(self, client, fake_redis):
        response = self._callback(client, fake_redis)

        assert "#oidc_code=" in response.headers["Location"]
        self.db.users.upsert.assert_called_once_with("oidc-user-1")
        call = self.db.events.insert.call_args
        assert call.args == ("oidc-user-1", "oidc_login")
        assert call.kwargs["metadata"] == {"email": "user@example.com", "groups": None}
        assert call.kwargs["user_agent"]

    def test_existing_active_user_not_upserted(self, client, fake_redis):
        self.db.users.get.return_value = {"user_id": "oidc-user-1", "active": True}
        response = self._callback(client, fake_redis)

        assert "#oidc_code=" in response.headers["Location"]
        self.db.users.upsert.assert_not_called()

    def test_db_outage_does_not_block_login(self, client, fake_redis):
        with patch(
            "application.api.oidc.routes.db_session",
            side_effect=RuntimeError("db down"),
        ):
            response = self._callback(client, fake_redis)

        assert "#oidc_code=" in response.headers["Location"]

    def test_audit_insert_failure_does_not_block_login(self, client, fake_redis):
        self.db.events.insert.side_effect = RuntimeError("insert failed")
        response = self._callback(client, fake_redis)

        assert "#oidc_code=" in response.headers["Location"]

    def test_successful_login_does_not_touch_denylist(self, client, fake_redis):
        # The denylist keys on a revocation timestamp and the minted session
        # carries a newer iat, so a fresh login is allowed without clearing any
        # entry — clearing would resurrect sessions revoked on other devices.
        with patch("application.api.oidc.routes.denylist") as deny:
            response = self._callback(client, fake_redis)

        assert "#oidc_code=" in response.headers["Location"]
        assert not deny.allow_user.called
        assert not deny.allow_idp_sub.called

    def test_denied_login_does_not_touch_denylist(self, client, fake_redis):
        self.db.users.get.return_value = {"user_id": "oidc-user-1", "active": False}
        with patch("application.api.oidc.routes.denylist") as deny:
            response = self._callback(client, fake_redis)

        assert "account_disabled" in response.headers["Location"]
        assert not deny.allow_user.called
        assert not deny.allow_idp_sub.called


@pytest.mark.unit
class TestSessionTokenMint:

    @pytest.fixture(autouse=True)
    def _db(self, db_mocks):
        self.db = db_mocks

    def _login_decoded(self, client, fake_redis, claims=None, **token_extra):
        state, nonce = _seed_state(client, fake_redis)
        claims = {**(claims or id_token_claims()), "nonce": nonce}
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = _signed_token_response(claims, **token_extra)
            response = client.get(f"/api/auth/oidc/callback?code=abc&state={state}")
        handoff = response.headers["Location"].split("#oidc_code=", 1)[1]
        session_token = fake_redis.store[f"oidc:handoff:{handoff}"].decode("utf-8")
        return jose_jwt.decode(session_token, JWT_SECRET, algorithms=["HS256"])

    def test_contains_jti_and_oidc_sub(self, client, fake_redis):
        decoded = self._login_decoded(client, fake_redis)

        assert len(decoded["jti"]) == 36
        assert decoded["oidc_sub"] == "oidc-user-1"
        assert "oidc_sid" not in decoded

    def test_oidc_sid_included_when_id_token_has_sid(self, client, fake_redis):
        decoded = self._login_decoded(client, fake_redis, claims=id_token_claims(sid="sess-42"))

        assert decoded["oidc_sid"] == "sess-42"

    def test_picture_claim_passthrough(self, client, fake_redis):
        decoded = self._login_decoded(
            client, fake_redis, claims=id_token_claims(picture="https://img.test/me.png")
        )

        assert decoded["picture"] == "https://img.test/me.png"

    def test_overlong_picture_dropped(self, client, fake_redis):
        decoded = self._login_decoded(
            client, fake_redis, claims=id_token_claims(picture="https://img.test/" + "x" * 2048)
        )

        assert "picture" not in decoded

    def test_refresh_token_stored_under_jti(self, client, fake_redis):
        decoded = self._login_decoded(client, fake_redis, refresh_token="rt-1")

        assert fake_redis.store[f"oidc:refresh:{decoded['jti']}"] == b"rt-1"

    def test_no_refresh_key_when_idp_sends_none(self, client, fake_redis):
        self._login_decoded(client, fake_redis)

        assert not any(key.startswith("oidc:refresh:") for key in fake_redis.store)


@pytest.mark.unit
class TestBackchannelLogoutRoute:

    URL = "/api/auth/oidc/backchannel-logout"

    @pytest.fixture(autouse=True)
    def _seams(self, db_mocks):
        self.db = db_mocks
        with patch("application.api.oidc.routes.denylist") as deny:
            self.denylist = deny
            yield

    def _post(self, client, claims=None, **kwargs):
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            if claims is not None:
                kwargs.setdefault("data", {"logout_token": sign_id_token(claims)})
            return client.post(self.URL, **kwargs)

    def test_sub_logout_denylists_sub(self, client, fake_redis):
        response = self._post(client, logout_token_claims())

        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        self.denylist.deny_idp_sub.assert_called_once_with("oidc-user-1")
        self.denylist.deny_sid.assert_not_called()
        call = self.db.events.insert.call_args
        assert call.args == ("oidc-user-1", "backchannel_logout")
        assert call.kwargs["metadata"] is None

    def test_sid_only_logout_denylists_sid(self, client, fake_redis):
        claims = logout_token_claims(sid="sess-7", jti="bcl-jti-2")
        del claims["sub"]
        response = self._post(client, claims)

        assert response.status_code == 200
        self.denylist.deny_sid.assert_called_once_with("sess-7")
        self.denylist.deny_idp_sub.assert_not_called()
        call = self.db.events.insert.call_args
        assert call.args == ("sid:sess-7", "backchannel_logout")
        assert call.kwargs["metadata"] == {"sid": "sess-7"}

    def test_sub_and_sid_denylists_both(self, client, fake_redis):
        response = self._post(client, logout_token_claims(sid="sess-8", jti="bcl-jti-3"))

        assert response.status_code == 200
        self.denylist.deny_idp_sub.assert_called_once_with("oidc-user-1")
        self.denylist.deny_sid.assert_called_once_with("sess-8")

    def test_json_body_accepted(self, client, fake_redis):
        token = sign_id_token(logout_token_claims(jti="bcl-jti-4"))
        response = self._post(client, json={"logout_token": token})

        assert response.status_code == 200

    def test_missing_token_rejected(self, client, fake_redis):
        response = client.post(self.URL)

        assert response.status_code == 400
        assert response.headers["Cache-Control"] == "no-store"

    def test_missing_events_rejected(self, client, fake_redis):
        claims = logout_token_claims()
        del claims["events"]
        response = self._post(client, claims)

        assert response.status_code == 400
        assert response.get_json() == {"error": "invalid_logout_token"}
        assert response.headers["Cache-Control"] == "no-store"
        self.denylist.deny_idp_sub.assert_not_called()

    def test_nonce_present_rejected(self, client, fake_redis):
        response = self._post(client, logout_token_claims(nonce="n-1"))

        assert response.status_code == 400
        self.denylist.deny_idp_sub.assert_not_called()

    def test_bad_signature_rejected(self, client, fake_redis):
        rogue_pem = _generate_rsa_pem()
        token = sign_id_token(logout_token_claims(), key=rogue_pem)
        response = self._post(client, data={"logout_token": token})

        assert response.status_code == 400
        self.denylist.deny_idp_sub.assert_not_called()

    def test_jti_replay_rejected(self, client, fake_redis):
        token = sign_id_token(logout_token_claims(jti="bcl-jti-replay"))
        first = self._post(client, data={"logout_token": token})
        replay = self._post(client, data={"logout_token": token})

        assert first.status_code == 200
        assert replay.status_code == 400
        assert self.denylist.deny_idp_sub.call_count == 1

    def test_missing_jti_rejected(self, client, fake_redis):
        # jti is required (Back-Channel Logout 1.0) and underpins replay
        # protection — a token without one must not be accepted.
        claims = logout_token_claims()
        del claims["jti"]
        response = self._post(client, claims)

        assert response.status_code == 400
        self.denylist.deny_idp_sub.assert_not_called()

    def test_stale_iat_rejected(self, client, fake_redis):
        # Beyond the jti replay-cache window the token can no longer be deduped,
        # so an old iat is rejected outright (bounds replay after eviction).
        claims = logout_token_claims(jti="bcl-stale", iat=int(time.time()) - 10000)
        response = self._post(client, claims)

        assert response.status_code == 400
        self.denylist.deny_idp_sub.assert_not_called()

    def test_revocation_write_failure_returns_502(self, client, fake_redis):
        # Redis down: report failure so the IdP retries instead of recording a
        # logout that never revoked anything.
        self.denylist.deny_idp_sub.return_value = False
        response = self._post(client, logout_token_claims(jti="bcl-502"))

        assert response.status_code == 502
        assert response.get_json() == {"error": "revocation_unavailable"}


@pytest.mark.unit
class TestRefreshRoute:

    URL = "/api/auth/oidc/refresh"

    @pytest.fixture(autouse=True)
    def _seams(self, db_mocks):
        self.db = db_mocks
        with patch("application.api.oidc.routes.denylist") as deny:
            deny.is_denied.return_value = False
            self.denylist = deny
            yield

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _refresh(self, client, token, idp_response=None, idp_status=200):
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = Mock(
                status_code=idp_status,
                text="error",
                json=Mock(return_value=idp_response or {}),
            )
            response = client.post(self.URL, headers=self._auth(token))
            return response, mock_requests

    def test_happy_path_rotates_refresh_token(self, client, fake_redis):
        token = make_session_token()
        fake_redis.store["oidc:refresh:jti-1"] = b"rt-old"
        id_claims = id_token_claims(sid="sess-1")
        del id_claims["nonce"]
        response, mock_requests = self._refresh(
            client,
            token,
            idp_response={
                "access_token": "at-2",
                "refresh_token": "rt-new",
                "id_token": sign_id_token(id_claims),
            },
        )

        assert response.status_code == 200
        decoded = jose_jwt.decode(
            response.get_json()["token"], JWT_SECRET, algorithms=["HS256"]
        )
        assert decoded["sub"] == "oidc-user-1"
        assert decoded["jti"] != "jti-1"
        assert decoded["oidc_sub"] == "oidc-user-1"
        assert decoded["oidc_sid"] == "sess-1"
        assert "oidc:refresh:jti-1" not in fake_redis.store
        assert fake_redis.store[f"oidc:refresh:{decoded['jti']}"] == b"rt-new"
        sent = mock_requests.post.call_args.kwargs["data"]
        assert sent["grant_type"] == "refresh_token"
        assert sent["refresh_token"] == "rt-old"
        call = self.db.events.insert.call_args
        assert call.args == ("oidc-user-1", "oidc_refresh")

    def test_identity_reused_when_no_id_token_returned(self, client, fake_redis):
        token = make_session_token(
            email="user@example.com", name="OIDC User", oidc_sid="sess-2"
        )
        fake_redis.store["oidc:refresh:jti-1"] = b"rt-old"
        response, _ = self._refresh(client, token, idp_response={"access_token": "at-2"})

        assert response.status_code == 200
        decoded = jose_jwt.decode(
            response.get_json()["token"], JWT_SECRET, algorithms=["HS256"]
        )
        assert decoded["sub"] == "oidc-user-1"
        assert decoded["email"] == "user@example.com"
        assert decoded["oidc_sid"] == "sess-2"
        # IdP kept the old refresh token, so it is re-stored under the new jti.
        assert fake_redis.store[f"oidc:refresh:{decoded['jti']}"] == b"rt-old"

    def test_refresh_denied_when_groups_no_longer_allowed(
        self, client, fake_redis, monkeypatch
    ):
        monkeypatch.setattr(settings, "OIDC_ALLOWED_GROUPS", "admins")
        token = make_session_token()
        fake_redis.store["oidc:refresh:jti-1"] = b"rt-old"
        id_claims = id_token_claims(groups=["users"])
        del id_claims["nonce"]
        response, _ = self._refresh(
            client,
            token,
            idp_response={
                "access_token": "at-2",
                "refresh_token": "rt-new",
                "id_token": sign_id_token(id_claims),
            },
        )

        assert response.status_code == 401
        assert response.get_json() == {"error": "not_authorized"}
        # Denial is audited and no renewed session/refresh token exists.
        call = self.db.events.insert.call_args
        assert call.args[1] == "oidc_login_denied"
        assert call.kwargs["metadata"]["via"] == "refresh"
        assert not any(k.startswith("oidc:refresh:") for k in fake_redis.store)

    def test_refresh_allowed_when_group_still_matches(
        self, client, fake_redis, monkeypatch
    ):
        monkeypatch.setattr(settings, "OIDC_ALLOWED_GROUPS", "users, admins")
        token = make_session_token()
        fake_redis.store["oidc:refresh:jti-1"] = b"rt-old"
        id_claims = id_token_claims(groups=["users"])
        del id_claims["nonce"]
        response, _ = self._refresh(
            client,
            token,
            idp_response={
                "access_token": "at-2",
                "refresh_token": "rt-new",
                "id_token": sign_id_token(id_claims),
            },
        )

        assert response.status_code == 200

    def test_refresh_without_id_token_skips_group_check(
        self, client, fake_redis, monkeypatch
    ):
        # No fresh claims to evaluate — membership was checked at login and
        # will be re-checked the next time the IdP returns an id_token.
        monkeypatch.setattr(settings, "OIDC_ALLOWED_GROUPS", "admins")
        token = make_session_token()
        fake_redis.store["oidc:refresh:jti-1"] = b"rt-old"
        response, _ = self._refresh(client, token, idp_response={"access_token": "at-2"})

        assert response.status_code == 200

    def test_expired_session_rejected(self, client, fake_redis):
        token = make_session_token(exp=int(time.time()) - 120)
        response = client.post(self.URL, headers=self._auth(token))

        assert response.status_code == 401
        assert response.get_json() == {"error": "token_expired"}

    def test_garbage_token_rejected(self, client, fake_redis):
        response = client.post(self.URL, headers=self._auth("not-a-jwt"))

        assert response.status_code == 401
        assert response.get_json() == {"error": "invalid_token"}

    def test_missing_authorization_rejected(self, client, fake_redis):
        response = client.post(self.URL)

        assert response.status_code == 401
        assert response.get_json() == {"error": "invalid_token"}

    def test_session_without_jti_rejected(self, client, fake_redis):
        token = make_session_token(jti=None)
        response = client.post(self.URL, headers=self._auth(token))

        assert response.status_code == 401
        assert response.get_json() == {"error": "invalid_token"}

    def test_denylisted_session_rejected(self, client, fake_redis):
        self.denylist.is_denied.return_value = True
        token = make_session_token()
        fake_redis.store["oidc:refresh:jti-1"] = b"rt-old"
        response = client.post(self.URL, headers=self._auth(token))

        assert response.status_code == 401
        assert response.get_json() == {"error": "token_revoked"}
        assert "oidc:refresh:jti-1" in fake_redis.store

    def test_disabled_user_rejected(self, client, fake_redis):
        self.db.users.get.return_value = {"user_id": "oidc-user-1", "active": False}
        token = make_session_token()
        fake_redis.store["oidc:refresh:jti-1"] = b"rt-old"
        response = client.post(self.URL, headers=self._auth(token))

        assert response.status_code == 401
        assert response.get_json() == {"error": "account_disabled"}

    def test_no_stored_refresh_token_404(self, client, fake_redis):
        token = make_session_token()
        response = client.post(self.URL, headers=self._auth(token))

        assert response.status_code == 404
        assert response.get_json() == {"error": "no_refresh_token"}

    def test_idp_refresh_failure_401(self, client, fake_redis):
        token = make_session_token()
        fake_redis.store["oidc:refresh:jti-1"] = b"rt-old"
        response, _ = self._refresh(client, token, idp_status=400)

        assert response.status_code == 401
        assert response.get_json() == {"error": "refresh_failed"}

    def test_503_when_redis_unavailable(self, client):
        token = make_session_token()
        with patch("application.api.oidc.routes.get_redis_instance", return_value=None):
            response = client.post(self.URL, headers=self._auth(token))

        assert response.status_code == 503
        assert response.get_json() == {"error": "redis_unavailable"}

    def test_transient_idp_failure_503_and_token_restored(self, client, fake_redis):
        # 5xx from the IdP is transient: keep the (still-valid) refresh token and
        # tell the client to retry rather than dropping a live session.
        token = make_session_token()
        fake_redis.store["oidc:refresh:jti-1"] = b"rt-old"
        response, _ = self._refresh(client, token, idp_status=503)

        assert response.status_code == 503
        assert response.get_json() == {"error": "refresh_unavailable"}
        assert fake_redis.store["oidc:refresh:jti-1"] == b"rt-old"

    def test_remapped_disabled_identity_rejected(self, client, fake_redis):
        # The refreshed id_token maps to a different (disabled) user id than the
        # session sub — the post-grant gate must refuse it.
        token = make_session_token()
        fake_redis.store["oidc:refresh:jti-1"] = b"rt-old"
        self.db.users.get.side_effect = (
            lambda uid: {"user_id": uid, "active": False} if uid == "oidc-user-2" else None
        )
        id_claims = id_token_claims(sub="oidc-user-2")
        del id_claims["nonce"]
        response, _ = self._refresh(
            client,
            token,
            idp_response={
                "access_token": "at-2",
                "refresh_token": "rt-new",
                "id_token": sign_id_token(id_claims),
            },
        )

        assert response.status_code == 401
        assert response.get_json() == {"error": "account_disabled"}
