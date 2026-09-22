"""Unit tests for docsgpt/api/pat/tokens.py and the PAT branch of handle_auth."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from docsgpt.api.pat import tokens


def _request(authorization=None, ip="10.1.1.1"):
    request = Mock()
    request.headers = {"Authorization": authorization} if authorization else {}
    request.remote_addr = ip
    return request


@contextmanager
def _db(row):
    repo = Mock()
    repo.find_active_by_hash.return_value = row

    @contextmanager
    def _conn():
        yield Mock()

    with patch.object(tokens, "db_readonly", _conn), patch.object(
        tokens, "db_session", _conn
    ), patch.object(tokens, "PersonalAccessTokensRepository", return_value=repo):
        yield repo


_ROW = {
    "id": "11111111-1111-1111-1111-111111111111",
    "user_id": "alice",
    "name": "ci",
    "scopes": ["agents:write", "chat:run"],
    "resource_filter": {"agents": ["22222222-2222-2222-2222-222222222222"]},
    "last_used_at": None,
}


@pytest.mark.unit
class TestTokenFormat:
    def test_generate_returns_prefixed_secret_hash_and_display_prefix(self):
        token, token_hash, display = tokens.generate_token()
        assert token.startswith("dgpt_pat_")
        assert len(token) > 40
        assert token_hash == tokens.hash_token(token)
        assert len(token_hash) == 64
        assert token.startswith(display) and len(display) == len("dgpt_pat_") + 6

    def test_tokens_are_unique(self):
        assert tokens.generate_token()[0] != tokens.generate_token()[0]

    def test_redact_never_returns_the_secret(self):
        token, _, display = tokens.generate_token()
        assert tokens.redact(token) == display + "…"
        assert tokens.redact("some-agent-key") == "some…"
        assert tokens.redact(None) == ""

    @pytest.mark.parametrize(
        "value,expected",
        [("dgpt_pat_abc", True), ("eyJhbGciOi", False), ("", False), (None, False)],
    )
    def test_looks_like_pat(self, value, expected):
        assert tokens.looks_like_pat(value) is expected


@pytest.mark.unit
class TestScopes:
    def test_write_implies_read(self):
        assert tokens.expand_scopes(["agents:write"]) == {"agents:write", "agents:read"}

    def test_standalone_scopes_imply_nothing(self):
        assert tokens.expand_scopes(["agents:keys", "chat:run"]) == {"agents:keys", "chat:run"}

    def test_normalize_sorts_and_dedupes(self):
        assert tokens.normalize_scopes(["sources:read", "agents:read", "sources:read"]) == [
            "agents:read",
            "sources:read",
        ]

    @pytest.mark.parametrize("raw", [None, [], "agents:read", ["admin:all"], [1], ["agents:read", "x"]])
    def test_normalize_rejects_bad_input(self, raw):
        with pytest.raises(ValueError):
            tokens.normalize_scopes(raw)

    def test_no_admin_scope_exists(self):
        assert not any(s.startswith("admin") for s in tokens.SCOPES)


@pytest.mark.unit
class TestResourceFilter:
    UUID_A = "22222222-2222-2222-2222-222222222222"

    def test_empty_is_unrestricted(self):
        assert tokens.normalize_resource_filter(None, ["agents:read"]) == {}
        assert tokens.normalize_resource_filter({}, ["agents:read"]) == {}

    def test_canonicalizes_and_dedupes_ids(self):
        out = tokens.normalize_resource_filter(
            {"agents": [self.UUID_A.upper(), self.UUID_A]}, ["agents:read"]
        )
        assert out == {"agents": [self.UUID_A]}

    def test_chat_scope_allows_agent_and_source_restrictions(self):
        out = tokens.normalize_resource_filter(
            {"agents": [self.UUID_A], "sources": [self.UUID_A]}, ["chat:run"]
        )
        assert set(out) == {"agents", "sources"}

    def test_tools_restriction_cannot_be_combined_with_chat(self):
        with pytest.raises(ValueError, match="chat:run"):
            tokens.normalize_resource_filter({"tools": [self.UUID_A]}, ["tools:read", "chat:run"])
        assert tokens.normalize_resource_filter({"tools": [self.UUID_A]}, ["tools:read"])

    @pytest.mark.parametrize(
        "raw,scopes",
        [
            ("agents", ["agents:read"]),
            ({"conversations": [UUID_A]}, ["conversations:read"]),
            ({"sources": [UUID_A]}, ["agents:read"]),
            ({"agents": []}, ["agents:read"]),
            ({"agents": "all"}, ["agents:read"]),
            ({"agents": ["not-a-uuid"]}, ["agents:read"]),
            ({"agents": [UUID_A] * 201}, ["agents:read"]),
        ],
    )
    def test_rejects_bad_filters(self, raw, scopes):
        with pytest.raises(ValueError):
            tokens.normalize_resource_filter(raw, scopes)


@pytest.mark.unit
class TestExpiryPolicy:
    @pytest.fixture(autouse=True)
    def _policy(self, monkeypatch):
        monkeypatch.setattr(tokens.settings, "PAT_DEFAULT_LIFETIME_DAYS", 90)
        monkeypatch.setattr(tokens.settings, "PAT_MAX_LIFETIME_DAYS", 365)
        monkeypatch.setattr(tokens.settings, "PAT_ALLOW_NON_EXPIRING", False)

    def _days(self, expires_at):
        return round((expires_at - datetime.now(timezone.utc)) / timedelta(days=1))

    def test_default_lifetime(self):
        assert self._days(tokens.resolve_expiry(None)) == 90

    def test_explicit_lifetime(self):
        assert self._days(tokens.resolve_expiry(7)) == 7

    def test_max_lifetime_enforced(self):
        assert self._days(tokens.resolve_expiry(365)) == 365
        with pytest.raises(ValueError):
            tokens.resolve_expiry(366)

    def test_non_expiring_refused_unless_operator_allows(self, monkeypatch):
        with pytest.raises(ValueError, match="disabled"):
            tokens.resolve_expiry(0)
        monkeypatch.setattr(tokens.settings, "PAT_ALLOW_NON_EXPIRING", True)
        assert tokens.resolve_expiry(0) is None

    @pytest.mark.parametrize("raw", [-1, "30", 1.5, True])
    def test_rejects_bad_values(self, raw):
        with pytest.raises(ValueError):
            tokens.resolve_expiry(raw)


@pytest.mark.unit
class TestAuthenticatePat:
    @pytest.fixture(autouse=True)
    def _enabled(self, monkeypatch):
        monkeypatch.setattr(tokens.settings, "PAT_ENABLED", True)
        monkeypatch.setattr(tokens.settings, "AUTH_TYPE", "oidc")

    def test_valid_token_yields_claims_from_the_row(self):
        with _db(dict(_ROW)) as repo:
            claims = tokens.authenticate_pat("dgpt_pat_secret", _request())
        repo.find_active_by_hash.assert_called_once_with(tokens.hash_token("dgpt_pat_secret"))
        assert claims == {
            "sub": "alice",
            "auth_method": "pat",
            "pat_id": _ROW["id"],
            "pat_name": "ci",
            "scopes": ["agents:read", "agents:write", "chat:run"],
            "resource_filter": _ROW["resource_filter"],
        }
        repo.touch_last_used.assert_called_once()
        assert repo.touch_last_used.call_args.args[:2] == (_ROW["id"], "10.1.1.1")

    def test_unknown_token_is_invalid(self):
        with _db(None):
            assert tokens.authenticate_pat("dgpt_pat_x", _request())["error"] == "invalid_token"

    def test_lookup_failure_fails_closed(self):
        with _db(dict(_ROW)) as repo:
            repo.find_active_by_hash.side_effect = RuntimeError("db down")
            assert tokens.authenticate_pat("dgpt_pat_x", _request())["error"] == "invalid_token"

    def test_usage_write_failure_never_fails_the_request(self):
        with _db(dict(_ROW)) as repo:
            repo.touch_last_used.side_effect = RuntimeError("db down")
            assert tokens.authenticate_pat("dgpt_pat_x", _request())["sub"] == "alice"

    def test_recent_usage_skips_the_write(self):
        row = dict(_ROW, last_used_at=datetime.now(timezone.utc).isoformat())
        with _db(row) as repo:
            tokens.authenticate_pat("dgpt_pat_x", _request())
        repo.touch_last_used.assert_not_called()

    @pytest.mark.parametrize("auth_type", ["simple_jwt", "session_jwt"])
    def test_rejected_where_there_is_no_stable_user_identity(self, monkeypatch, auth_type):
        monkeypatch.setattr(tokens.settings, "AUTH_TYPE", auth_type)
        with _db(dict(_ROW)) as repo:
            assert tokens.authenticate_pat("dgpt_pat_x", _request())["error"] == "invalid_token"
        repo.find_active_by_hash.assert_not_called()

    def test_rejected_when_disabled(self, monkeypatch):
        monkeypatch.setattr(tokens.settings, "PAT_ENABLED", False)
        with _db(dict(_ROW)):
            assert tokens.authenticate_pat("dgpt_pat_x", _request())["error"] == "invalid_token"

    def test_works_with_auth_disabled(self, monkeypatch):
        monkeypatch.setattr(tokens.settings, "AUTH_TYPE", None)
        with _db(dict(_ROW)):
            assert tokens.authenticate_pat("dgpt_pat_x", _request())["sub"] == "alice"

    def test_starlette_request_ip(self):
        request = Mock(spec=["headers", "client"])
        request.client.host = "10.9.9.9"
        with _db(dict(_ROW)) as repo:
            tokens.authenticate_pat("dgpt_pat_x", request)
        assert repo.touch_last_used.call_args.args[1] == "10.9.9.9"


@pytest.mark.unit
class TestHandleAuthPatBranch:
    def test_pat_bearer_goes_to_the_pat_verifier_in_any_auth_mode(self):
        from docsgpt import auth

        for auth_type in (None, "oidc", "simple_jwt"):
            with patch.object(auth.settings, "AUTH_TYPE", auth_type), patch(
                "docsgpt.api.pat.tokens.authenticate_pat", return_value={"sub": "alice"}
            ) as verifier:
                request = _request("Bearer dgpt_pat_secret")
                assert auth.handle_auth(request) == {"sub": "alice"}
            verifier.assert_called_once_with("dgpt_pat_secret", request)

    def test_bearer_scheme_is_case_insensitive(self):
        from docsgpt import auth

        with patch("docsgpt.api.pat.tokens.authenticate_pat", return_value={"sub": "a"}) as verifier:
            auth.handle_auth(_request("bearer dgpt_pat_secret"))
        verifier.assert_called_once()

    def test_jwt_cannot_smuggle_pat_claims(self):
        from jose import jwt

        from docsgpt import auth

        forged = jwt.encode(
            {
                "sub": "mallory",
                "auth_method": "pat",
                "scopes": ["agents:write"],
                "resource_filter": {},
                "pat_id": "x",
                "pat_name": "x",
            },
            "secret",
            algorithm="HS256",
        )
        with patch.object(auth.settings, "AUTH_TYPE", "simple_jwt"), patch.object(
            auth.settings, "JWT_SECRET_KEY", "secret"
        ):
            decoded = auth.handle_auth(_request(f"Bearer {forged}"))
        assert decoded == {"sub": "mallory"}
