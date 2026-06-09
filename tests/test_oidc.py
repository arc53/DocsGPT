"""Tests for the OIDC SSO module (application/api/oidc/)."""

import base64
import hashlib
import json
import time
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

DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": "https://idp.test/authorize",
    "token_endpoint": "https://idp.test/token",
    "jwks_uri": "https://idp.test/jwks",
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


def make_fake_get(jwks_keys):
    """requests.get stub serving discovery + JWKS; ``jwks_keys`` is mutable."""

    def fake_get(url, timeout=None):
        resp = Mock()
        resp.status_code = 200
        if "openid-configuration" in url:
            resp.json.return_value = dict(DISCOVERY)
        elif url == DISCOVERY["jwks_uri"]:
            resp.json.return_value = {"keys": list(jwks_keys)}
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

    def test_includes_client_secret_when_configured(self, monkeypatch):
        from application.api.oidc import provider

        monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "s3cret")
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
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


def _mint_id_token_response(stored_nonce):
    return Mock(
        status_code=200,
        json=Mock(
            return_value={
                "access_token": "at",
                "token_type": "Bearer",
                "id_token": sign_id_token(id_token_claims(nonce=stored_nonce)),
            }
        ),
    )


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
class TestCallbackRoute:

    def _seed_state(self, fake_redis, state="state-1", nonce="nonce-1"):
        fake_redis.set(
            f"oidc:state:{state}",
            json.dumps({"code_verifier": "verifier-1", "nonce": nonce}),
        )
        return state, nonce

    def test_happy_path_mints_session_and_redirects_with_handoff(self, client, fake_redis):
        state, nonce = self._seed_state(fake_redis)
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
        state, nonce = self._seed_state(fake_redis)
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = _mint_id_token_response(nonce)
            first = client.get(f"/api/auth/oidc/callback?code=abc&state={state}")
            replay = client.get(f"/api/auth/oidc/callback?code=abc&state={state}")

        assert "#oidc_code=" in first.headers["Location"]
        assert replay.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=invalid_state"

    def test_unknown_state_rejected(self, client, fake_redis):
        response = client.get("/api/auth/oidc/callback?code=abc&state=forged")
        assert response.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=invalid_state"

    def test_idp_error_forwarded(self, client, fake_redis):
        response = client.get("/api/auth/oidc/callback?error=access_denied")
        assert (
            response.headers["Location"]
            == f"{FRONTEND_URL}/#oidc_error=access_denied"
        )

    def test_nonce_mismatch_fails_auth(self, client, fake_redis):
        state, _ = self._seed_state(fake_redis, nonce="nonce-1")
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = _mint_id_token_response("evil-nonce")
            response = client.get(f"/api/auth/oidc/callback?code=abc&state={state}")

        assert response.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=auth_failed"

    def test_missing_user_id_claim(self, client, fake_redis, monkeypatch):
        monkeypatch.setattr(settings, "OIDC_USER_ID_CLAIM", "preferred_username")
        state, nonce = self._seed_state(fake_redis)
        with patch("application.api.oidc.provider.requests") as mock_requests:
            mock_requests.get.side_effect = make_fake_get([PUBLIC_JWK])
            mock_requests.post.return_value = _mint_id_token_response(nonce)
            response = client.get(f"/api/auth/oidc/callback?code=abc&state={state}")

        assert response.headers["Location"] == f"{FRONTEND_URL}/#oidc_error=missing_claim"

    def test_optional_profile_claims_omitted_when_absent(self, client, fake_redis):
        state, nonce = self._seed_state(fake_redis)
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
