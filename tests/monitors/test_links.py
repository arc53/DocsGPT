"""Tests for link tokens, secrets and the URLs handed to the user."""

from __future__ import annotations

import base64
import hashlib

import pytest

from docsgpt.core.settings import settings
from docsgpt.monitors import links


class TestTokens:
    def test_tokens_are_long_random_and_prefixed(self):
        tokens = {links.new_token("webhook") for _ in range(50)}
        assert len(tokens) == 50
        token = tokens.pop()
        assert token.startswith("trg_")
        # 32 random bytes, base64url: at least 43 characters after the prefix.
        assert len(token) - 4 >= 43
        assert links.new_token("approval").startswith("apv_")

    def test_only_the_sha256_is_kept(self):
        token = links.new_token("webhook")
        assert links.token_hash(token) == hashlib.sha256(token.encode()).hexdigest()
        assert links.token_hash(token) != links.token_hash(token + "x")


class TestSecrets:
    def test_standard_webhooks_secret_is_whsec_base64_of_32_bytes(self):
        secret = links.new_secret("standard_webhooks")
        assert secret.startswith("whsec_")
        assert len(base64.b64decode(secret[len("whsec_"):])) == 32

    @pytest.mark.parametrize("scheme", ["github", "hmac_sha256"])
    def test_hmac_secrets(self, scheme):
        secret = links.new_secret(scheme)
        assert secret and len(secret) >= 40 and not secret.startswith("whsec_")

    def test_unsigned_links_have_no_secret(self):
        assert links.new_secret("none") is None

    def test_sealed_secret_round_trips_and_is_not_plaintext(self):
        sealed = links.seal_secret("s3cret-value", "u1")
        assert sealed and "s3cret-value" not in sealed
        assert links.open_secret(sealed, "u1") == "s3cret-value"
        assert links.seal_secret(None, "u1") is None and links.open_secret(None, "u1") is None


class TestUrls:
    def test_public_api_base_url_wins_over_api_url(self, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", "https://docs.example.com/")
        monkeypatch.setattr(settings, "API_URL", "http://backend:7091")
        monkeypatch.setattr(settings, "PUBLIC_APP_URL", None)
        assert links.trigger_url("trg_x") == "https://docs.example.com/api/triggers/trg_x"
        assert links.approval_page_url("apv_x") == "https://docs.example.com/approve/apv_x"

    def test_falls_back_to_api_url_and_app_url_overrides_the_page(self, monkeypatch):
        monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", None)
        monkeypatch.setattr(settings, "API_URL", "http://localhost:7091")
        monkeypatch.setattr(settings, "PUBLIC_APP_URL", "http://localhost:5173")
        assert links.trigger_url("t") == "http://localhost:7091/api/triggers/t"
        assert links.approval_page_url("a") == "http://localhost:5173/approve/a"

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:7091/api/triggers/t",
            "http://127.0.0.1/api/triggers/t",
            "http://10.1.2.3/api/triggers/t",
            "http://192.168.1.4:7091/x",
            "http://backend:7091/x",
            "http://docsgpt.local/x",
            "http://[::1]/x",
            "",
        ],
    )
    def test_local_and_private_bases_are_flagged(self, url):
        public, note = links.reachability(url)
        assert public is False and note

    def test_public_base_is_reachable(self):
        assert links.reachability("https://docs.example.com/api/triggers/t") == (True, None)


class TestExamples:
    def test_unsigned_curl_posts_json(self):
        command = links.example_curl("https://h/api/triggers/t", "none", None)
        assert command.startswith("curl -X POST 'https://h/api/triggers/t'")

    @pytest.mark.parametrize("scheme,header", [("github", "X-Hub-Signature-256"), ("hmac_sha256", "X-Signature")])
    def test_hmac_curl_signs_the_body(self, scheme, header):
        command = links.example_curl("https://h/t", scheme, "sek")
        assert header in command and "openssl dgst -sha256 -hmac 'sek'" in command

    def test_link_view_hides_the_hash_and_secret(self):
        view = links.link_view({"id": "1", "kind": "webhook", "token_hash": "h", "secret_encrypted": "s"})
        assert "token_hash" not in view and "secret_encrypted" not in view
