"""Tests for the GitHub App user sign-in."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest


@pytest.fixture
def configured(monkeypatch):
    from docsgpt.core.settings import settings

    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "Iv1.client")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", "app-secret")
    monkeypatch.setattr(settings, "GITHUB_APP_SLUG", "docsgpt-acme")
    monkeypatch.setattr(settings, "CONNECTOR_REDIRECT_BASE_URI", "https://docs.example/api/connectors/callback")


def _response(payload, status=200):
    response = MagicMock(status_code=status)
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_needs_the_app_settings(monkeypatch):
    from docsgpt.core.settings import settings
    from docsgpt.parser.connectors.github.auth import GitHubAuth

    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", None)
    with pytest.raises(ValueError, match="GITHUB_CLIENT_ID"):
        GitHubAuth()


def test_authorization_url_carries_state_and_callback(configured):
    from docsgpt.parser.connectors.github.auth import GitHubAuth

    url = urlparse(GitHubAuth().get_authorization_url(state="st"))
    query = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://github.com/login/oauth/authorize"
    assert query["client_id"] == ["Iv1.client"]
    assert query["state"] == ["st"]
    assert query["redirect_uri"] == ["https://docs.example/api/connectors/callback"]


def test_installation_url_carries_state(configured):
    from docsgpt.parser.connectors.github.auth import GitHubAuth

    assert GitHubAuth().get_installation_url(state="st") == (
        "https://github.com/apps/docsgpt-acme/installations/new?state=st"
    )


def test_exchange_returns_expiring_tokens_and_the_login(configured):
    from docsgpt.parser.connectors.github.auth import GitHubAuth

    token = _response({
        "access_token": "ghu_a", "refresh_token": "ghr_r", "expires_in": 28800, "token_type": "bearer",
    })
    user = _response({"login": "octocat", "name": "The Octocat"})
    with patch("docsgpt.parser.connectors.github.auth.requests.post", return_value=token) as post, \
            patch("docsgpt.parser.connectors.github.auth.requests.get", return_value=user):
        info = GitHubAuth().exchange_code_for_tokens("code-1")
    assert post.call_args.kwargs["data"]["code"] == "code-1"
    assert post.call_args.kwargs["headers"]["Accept"] == "application/json"
    assert info["access_token"] == "ghu_a" and info["refresh_token"] == "ghr_r"
    assert info["user_info"]["login"] == "octocat"
    expiry = datetime.datetime.fromisoformat(info["expiry"])
    assert expiry > datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=7)


def test_exchange_error_in_a_200_body_raises(configured):
    """GitHub reports a bad code with 200 and an ``error`` field."""
    from docsgpt.parser.connectors.github.auth import GitHubAuth

    with patch("docsgpt.parser.connectors.github.auth.requests.post",
               return_value=_response({"error": "bad_verification_code"})):
        with pytest.raises(ValueError, match="bad_verification_code"):
            GitHubAuth().exchange_code_for_tokens("stale")


def test_refused_refresh_raises(configured):
    from docsgpt.parser.connectors.github.auth import GitHubAuth

    with patch("docsgpt.parser.connectors.github.auth.requests.post",
               return_value=_response({"error": "bad_refresh_token"})):
        with pytest.raises(ValueError, match="bad_refresh_token"):
            GitHubAuth().refresh_access_token("ghr_old")


def test_refresh_rotates_the_refresh_token(configured):
    from docsgpt.parser.connectors.github.auth import GitHubAuth

    with patch("docsgpt.parser.connectors.github.auth.requests.post", return_value=_response({
        "access_token": "ghu_b", "refresh_token": "ghr_new", "expires_in": 28800,
    })) as post:
        info = GitHubAuth().refresh_access_token("ghr_old")
    assert post.call_args.kwargs["data"]["grant_type"] == "refresh_token"
    assert info["access_token"] == "ghu_b" and info["refresh_token"] == "ghr_new"


class TestExpiry:
    def test_token_without_expiry_never_expires(self, configured):
        """An app with token expiry turned off issues tokens with no expiry: they stay valid."""
        from docsgpt.parser.connectors.github.auth import GitHubAuth

        assert GitHubAuth().is_token_expired({"access_token": "ghu_a"}) is False

    def test_expired_and_fresh(self, configured):
        from docsgpt.parser.connectors.github.auth import GitHubAuth

        now = datetime.datetime.now(datetime.timezone.utc)
        auth = GitHubAuth()
        assert auth.is_token_expired({"access_token": "a", "expiry": (now - datetime.timedelta(minutes=1)).isoformat()})
        assert not auth.is_token_expired({"access_token": "a", "expiry": (now + datetime.timedelta(hours=1)).isoformat()})
        assert auth.is_token_expired({})


def test_registered_as_an_auth_provider_but_not_a_file_connector():
    """GitHub signs in like the OAuth connectors but ingests through the remote loader."""
    from docsgpt.parser.connectors.connector_creator import ConnectorCreator

    assert ConnectorCreator.has_auth("github")
    assert not ConnectorCreator.is_supported("github")
    assert "github" not in ConnectorCreator.get_supported_connectors()
