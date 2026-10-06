"""Tests for link tokens, secrets and the URLs handed to the user."""

from __future__ import annotations

import base64
import hashlib
import json

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
        command = links.example_curl("https://h/api/triggers/t", "none")
        assert "curl -X POST 'https://h/api/triggers/t'" in command

    def _body_of(self, command):
        """Run the command's body half in a shell and parse what it would send."""
        import shutil
        import subprocess

        if not shutil.which("bash"):
            pytest.skip("needs bash")
        script = command.split("; curl ", 1)[0].split("; sig=", 1)[0] + '; printf %s "$body"'
        return json.loads(subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout)

    def test_the_example_body_carries_a_timestamp(self):
        """Identical bodies count once within TRIGGER_DEDUPE_WINDOW_SECONDS, so each example call differs."""
        body = self._body_of(links.example_curl("https://h/t", "none"))
        assert body["status"] == "success" and body["sent_at"].endswith("Z")

    def test_a_status_check_shapes_the_example_body(self):
        check = {"type": "status", "value_path": "deployment.state", "terminal": ["success", "failure"]}
        body = self._body_of(links.example_curl("https://h/t", "github", check))
        assert body["deployment"] == {"state": "success"} and "sent_at" in body

    def test_odd_check_values_cannot_break_out_of_the_command(self):
        check = {"type": "status", "value_path": "status", "terminal": ["it's $(touch /tmp/x) done % now"]}
        body = self._body_of(links.example_curl("https://h/t", "none", check))
        assert body["status"] == "it's $(touch /tmp/x) done % now"

    @pytest.mark.parametrize("scheme,header", [("github", "X-Hub-Signature-256"), ("hmac_sha256", "X-Signature")])
    def test_hmac_curl_signs_the_body_with_the_secret_from_the_environment(self, scheme, header):
        command = links.example_curl("https://h/t", scheme)
        assert header in command and 'openssl dgst -sha256 -hmac "$DOCSGPT_WEBHOOK_SECRET"' in command

    def test_standard_webhooks_curl_reads_the_secret_from_the_environment(self):
        command = links.example_curl("https://h/t", "standard_webhooks")
        assert '"${DOCSGPT_WEBHOOK_SECRET#whsec_}"' in command and "whsec_" not in command.replace("#whsec_", "")
        assert "webhook-signature: v1,$sig" in command

    @pytest.mark.parametrize("scheme", ["github", "hmac_sha256"])
    def test_the_hmac_command_signs_correctly(self, scheme, tmp_path):
        """Run the command's signing half in a shell and check it against the server's own HMAC."""
        import hashlib
        import hmac
        import os
        import shutil
        import subprocess

        if not shutil.which("openssl") or not shutil.which("bash"):
            pytest.skip("needs bash and openssl")
        command = links.example_curl("https://h/t", scheme)
        signing = command.split("; curl ", 1)[0] + '; printf "%s\\n%s" "$body" "$sig"'
        secret = links.new_secret(scheme)
        out = subprocess.run(
            ["bash", "-c", signing], capture_output=True, text=True, env={**os.environ, "DOCSGPT_WEBHOOK_SECRET": secret},
            check=True,
        ).stdout
        body, sig = out.rsplit("\n", 1)
        assert json.loads(body)["status"] == "success"
        assert sig == hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

    def test_link_view_hides_the_hash_and_secret(self):
        view = links.link_view({"id": "1", "kind": "webhook", "token_hash": "h", "secret_encrypted": "s"})
        assert "token_hash" not in view and "secret_encrypted" not in view
