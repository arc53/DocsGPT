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


def _hex(secret: str, content: bytes) -> str:
    return hmac.new(secret.encode(), content, hashlib.sha256).hexdigest()


class TestStripe:
    SECRET = "whsec_stripe_endpoint_secret_123"

    def _header(self, ts=NOW, body=BODY, *, extra=()):
        parts = [f"t={ts}", *extra, f"v1={_hex(self.SECRET, f'{ts}.'.encode() + body)}"]
        return {"Stripe-Signature": ",".join(parts)}

    def test_a_signed_delivery_verifies(self):
        assert signatures.verify("stripe", self.SECRET, self._header(), BODY, now=NOW) is None
        assert signatures.sign_stripe(self.SECRET, NOW, BODY) == self._header()["Stripe-Signature"]

    def test_any_v1_matching_passes(self):
        # Stripe sends one v1 per active secret while one is rolled, and a v0 test signature.
        header = self._header(extra=("v1=" + "0" * 64, "v0=" + "f" * 64))
        assert signatures.verify("stripe", self.SECRET, header, BODY, now=NOW) is None

    @pytest.mark.parametrize(
        "headers,body,now,message",
        [
            ({}, BODY, NOW, "missing"),
            ({"Stripe-Signature": f"t={NOW}"}, BODY, NOW, "no v1"),
            ({"Stripe-Signature": "v1=abc"}, BODY, NOW, "timestamp is missing"),
            ({"Stripe-Signature": "t=soon,v1=abc"}, BODY, NOW, "not a Unix time"),
            (None, BODY + b" ", NOW, "no Stripe v1 signature matches"),
            (None, BODY, NOW + signatures.TOLERANCE_SECONDS + 1, "too old"),
        ],
    )
    def test_rejects(self, headers, body, now, message):
        with pytest.raises(SignatureError, match=message):
            signatures.verify("stripe", self.SECRET, headers if headers is not None else self._header(), body,
                              now=now)


class TestSlack:
    SECRET = "8f742231b10e8888abcd99yyyzzz85a5"

    def _headers(self, ts=NOW, body=BODY):
        return {
            "X-Slack-Request-Timestamp": str(ts),
            "X-Slack-Signature": "v0=" + _hex(self.SECRET, f"v0:{ts}:".encode() + body),
        }

    def test_a_signed_request_verifies(self):
        assert signatures.verify("slack", self.SECRET, self._headers(), BODY, now=NOW) is None
        assert signatures.sign_slack(self.SECRET, NOW, BODY) == self._headers()["X-Slack-Signature"]

    @pytest.mark.parametrize(
        "change,message",
        [
            (lambda h: h.pop("X-Slack-Signature"), "X-Slack-Signature is missing"),
            (lambda h: h.pop("X-Slack-Request-Timestamp"), "X-Slack-Request-Timestamp is missing"),
            (lambda h: h.update({"X-Slack-Signature": "v0=" + "0" * 64}), "does not match"),
            (lambda h: h.update({"X-Slack-Request-Timestamp": str(NOW - 301)}), "too old"),
        ],
    )
    def test_rejects(self, change, message):
        headers = self._headers()
        change(headers)
        with pytest.raises(SignatureError, match=message):
            signatures.verify("slack", self.SECRET, headers, BODY, now=NOW)


class TestStaticTokens:
    SECRET = "tok_0123456789abcdefghij"

    def test_header_token_reads_the_default_header(self):
        assert signatures.verify("header_token", self.SECRET, {"x-webhook-token": self.SECRET}, b"") is None
        with pytest.raises(SignatureError, match="X-Webhook-Token is missing"):
            signatures.verify("header_token", self.SECRET, {}, b"")
        with pytest.raises(SignatureError, match="does not match"):
            signatures.verify("header_token", self.SECRET, {"X-Webhook-Token": self.SECRET + "x"}, b"")

    def test_header_token_reads_the_links_header(self):
        headers = {"X-Gitlab-Token": self.SECRET}
        assert signatures.verify("header_token", self.SECRET, headers, BODY, header_name="X-Gitlab-Token") is None
        with pytest.raises(SignatureError):
            signatures.verify("header_token", self.SECRET, headers, BODY)

    def test_bearer(self):
        assert signatures.verify("bearer", self.SECRET, {"Authorization": f"Bearer {self.SECRET}"}, b"") is None
        assert signatures.verify("bearer", self.SECRET, {"authorization": f"bearer  {self.SECRET}"}, b"") is None
        for value in (f"Basic {self.SECRET}", "Bearer", f"Bearer {self.SECRET[:-1]}"):
            with pytest.raises(SignatureError):
                signatures.verify("bearer", self.SECRET, {"Authorization": value}, b"")

    def test_compares_in_constant_time(self, monkeypatch):
        seen = []
        real = hmac.compare_digest

        def spy(a, b):
            seen.append((a, b))
            return real(a, b)

        monkeypatch.setattr(signatures.hmac, "compare_digest", spy)
        signatures.verify("bearer", self.SECRET, {"Authorization": f"Bearer {self.SECRET}"}, b"")
        signatures.verify("header_token", self.SECRET, {"X-Webhook-Token": self.SECRET}, b"")
        assert len(seen) == 2


class TestOwnerSecrets:
    @pytest.mark.parametrize(
        "scheme,value",
        [
            ("stripe", "whsec_abcdefghijklmnop1234"),
            ("slack", "8f742231b10e8888abcd99yyyzzz85a5"),
            ("standard_webhooks", "whsec_" + base64.b64encode(b"k" * 24).decode()),
            ("github", "a-long-enough-secret-value"),
            ("bearer", "a-long-enough-secret-value"),
        ],
    )
    def test_accepted(self, scheme, value):
        assert links.check_owner_secret(scheme, f"  {value} ") == value

    @pytest.mark.parametrize(
        "scheme,value,message",
        [
            ("stripe", "sk_live_abcdefghijklmnopqrst", "starts with whsec_"),
            ("slack", "short", "16 to 512"),
            ("slack", "has a space inside it here", "no spaces"),
            ("standard_webhooks", "whsec_not base64!!", "no spaces"),
            ("standard_webhooks", "whsec_###notbase64####", "base64"),
            ("github", 12345, "must be text"),
            ("github", "x" * 600, "16 to 512"),
        ],
    )
    def test_refused(self, scheme, value, message):
        with pytest.raises(ValueError, match=message):
            links.check_owner_secret(scheme, value)
