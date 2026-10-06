"""Tests for webhook signature verification (computed independently of the code under test)."""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from docsgpt.monitors import links, signatures
from docsgpt.monitors.signatures import SignatureError

BODY = b'{"status":"success"}'
NOW = 1_790_000_000


def _standard(secret: str, msg_id: str, ts: int, body: bytes) -> str:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    digest = hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


class TestStandardWebhooks:
    SECRET = "whsec_" + base64.b64encode(b"k" * 32).decode()

    def _headers(self, **overrides):
        headers = {
            "webhook-id": "msg_1",
            "webhook-timestamp": str(NOW),
            "webhook-signature": _standard(self.SECRET, "msg_1", NOW, BODY),
        }
        headers.update(overrides)
        return headers

    def test_a_valid_signature_returns_the_delivery_id(self):
        assert signatures.verify("standard_webhooks", self.SECRET, self._headers(), BODY, now=NOW) == "msg_1"

    def test_header_names_are_case_insensitive_and_svix_names_work(self):
        headers = {k.replace("webhook", "Svix").title(): v for k, v in self._headers().items()}
        assert signatures.verify("standard_webhooks", self.SECRET, headers, BODY, now=NOW) == "msg_1"

    def test_any_of_several_signatures_may_match(self):
        good = _standard(self.SECRET, "msg_1", NOW, BODY)
        headers = self._headers(**{"webhook-signature": f"v1,AAAA v1a,xyz {good}"})
        assert signatures.verify("standard_webhooks", self.SECRET, headers, BODY, now=NOW) == "msg_1"

    @pytest.mark.parametrize("skew", [-301, 301, 3600])
    def test_the_timestamp_must_be_within_five_minutes(self, skew):
        with pytest.raises(SignatureError, match="too old or too new"):
            signatures.verify("standard_webhooks", self.SECRET, self._headers(), BODY, now=NOW + skew)

    def test_within_tolerance_passes(self):
        assert signatures.verify("standard_webhooks", self.SECRET, self._headers(), BODY, now=NOW + 299)

    @pytest.mark.parametrize(
        "change",
        [
            {"body": BODY + b" "},
            {"webhook-id": "msg_2"},
            {"webhook-signature": "v2," + _standard(SECRET, "msg_1", NOW, BODY).split(",")[1]},
            {"webhook-signature": "v1,not-base64!"},
            {"webhook-timestamp": "yesterday"},
            {"webhook-id": ""},
        ],
    )
    def test_tampering_fails(self, change):
        body = change.pop("body", BODY)
        with pytest.raises(SignatureError):
            signatures.verify("standard_webhooks", self.SECRET, self._headers(**change), body, now=NOW)

    def test_wrong_secret_fails(self):
        other = links.new_secret("standard_webhooks")
        with pytest.raises(SignatureError):
            signatures.verify("standard_webhooks", other, self._headers(), BODY, now=NOW)

    def test_sign_standard_matches_the_spec_construction(self):
        assert signatures.sign_standard(self.SECRET, "msg_1", NOW, BODY) == _standard(self.SECRET, "msg_1", NOW, BODY)


class TestHexHmac:
    SECRET = "gh-secret-value"

    @pytest.mark.parametrize("scheme,header", [("github", "X-Hub-Signature-256"), ("hmac_sha256", "X-Signature")])
    def test_valid_and_invalid(self, scheme, header):
        digest = hmac.new(self.SECRET.encode(), BODY, hashlib.sha256).hexdigest()
        assert signatures.verify(scheme, self.SECRET, {header: f"sha256={digest}"}, BODY) is None
        assert signatures.verify(scheme, self.SECRET, {header.lower(): f"sha256={digest.upper()}"}, BODY) is None
        for bad in (f"sha1={digest}", "sha256=", digest, f"sha256={digest[:-1]}0"):
            with pytest.raises(SignatureError):
                signatures.verify(scheme, self.SECRET, {header: bad}, BODY)
        with pytest.raises(SignatureError, match="missing"):
            signatures.verify(scheme, self.SECRET, {}, BODY)

    def test_github_header_is_not_accepted_for_plain_hmac(self):
        digest = hmac.new(self.SECRET.encode(), BODY, hashlib.sha256).hexdigest()
        with pytest.raises(SignatureError):
            signatures.verify("hmac_sha256", self.SECRET, {"X-Hub-Signature-256": f"sha256={digest}"}, BODY)

    def test_comparisons_are_constant_time(self, monkeypatch):
        calls = []
        real = hmac.compare_digest

        def spy(a, b):
            calls.append((a, b))
            return real(a, b)

        monkeypatch.setattr(signatures.hmac, "compare_digest", spy)
        digest = hmac.new(self.SECRET.encode(), BODY, hashlib.sha256).hexdigest()
        signatures.verify("github", self.SECRET, {"X-Hub-Signature-256": f"sha256={digest}"}, BODY)
        assert calls


class TestSchemes:
    def test_unsigned_links_verify_nothing(self):
        assert signatures.verify("none", None, {}, BODY) is None

    def test_a_signed_link_without_a_secret_refuses(self):
        with pytest.raises(SignatureError):
            signatures.verify("github", None, {}, BODY)

    def test_unknown_scheme(self):
        with pytest.raises(SignatureError):
            signatures.verify("md5", "s", {}, BODY)
