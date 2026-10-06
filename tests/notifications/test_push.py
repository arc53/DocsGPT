"""Web Push: the endpoint allowlist, subscription parsing, VAPID config, sending and pruning."""

from __future__ import annotations

import base64
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from docsgpt.core.settings import settings
from docsgpt.notifications import push
from docsgpt.storage.db.repositories.push_subscriptions import PushSubscriptionsRepository


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _vapid_pair() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = _b64(key.private_numbers().private_value.to_bytes(32, "big"))
    public = _b64(
        key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    return private, public


def _browser_keys():
    key = ec.generate_private_key(ec.SECP256R1())
    p256dh = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    return key, _b64(p256dh), _b64(auth), auth


@pytest.fixture()
def vapid(monkeypatch):
    private, public = _vapid_pair()
    monkeypatch.setattr(settings, "WEBPUSH_VAPID_PRIVATE_KEY", private)
    monkeypatch.setattr(settings, "WEBPUSH_VAPID_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "WEBPUSH_VAPID_SUBJECT", "mailto:ops@example.com")
    push._load_vapid.cache_clear()
    yield private, public
    push._load_vapid.cache_clear()


@pytest.fixture()
def db(pg_engine, monkeypatch):
    monkeypatch.setattr("docsgpt.storage.db.engine._engine", pg_engine)
    return pg_engine


class TestEndpointAllowlist:
    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://fcm.googleapis.com/fcm/send/abc",
            "https://updates.push.services.mozilla.com/wpush/v2/abc",
            "https://web.push.apple.com/QGx",
            "https://wns2-par02p.notify.windows.com/w/?token=abc",
            "https://FCM.googleapis.com:443/wp/abc",
        ],
    )
    def test_known_push_services(self, endpoint):
        assert push.endpoint_allowed(endpoint)

    @pytest.mark.parametrize(
        "endpoint",
        [
            "http://fcm.googleapis.com/fcm/send/abc",  # not https
            "https://evil.example.com/fcm.googleapis.com",
            "https://fcm.googleapis.com.evil.example.com/x",
            "https://notify.windows.com/x",  # the suffix itself is not a host
            "https://user:pw@fcm.googleapis.com/x",
            "https://fcm.googleapis.com:8443/x",
            "https://169.254.169.254/latest/meta-data",
            "https://localhost/x",
            "https://[::1]/x",
            "https://fcm.googleapis.com:notaport/x",
            "fcm.googleapis.com/x",
            "",
            None,
            "https://fcm.googleapis.com/" + "a" * 2000,
        ],
    )
    def test_everything_else(self, endpoint):
        assert not push.endpoint_allowed(endpoint)

    def test_extra_hosts_exact_and_wildcard(self, monkeypatch):
        monkeypatch.setattr(settings, "WEBPUSH_EXTRA_ALLOWED_HOSTS", ["push.internal.example", "*.trycloudflare.com"])
        assert push.endpoint_allowed("https://push.internal.example/sub")
        assert push.endpoint_allowed("https://abc-def.trycloudflare.com/sink/push-s05")
        assert not push.endpoint_allowed("https://trycloudflare.com/x")
        assert not push.endpoint_allowed("http://abc.trycloudflare.com/x")
        assert not push.endpoint_allowed("https://other.internal.example/sub")

    def test_extra_hosts_parse_from_a_comma_list(self, monkeypatch):
        from docsgpt.core.settings.notifications import NotificationSettings

        monkeypatch.setenv("WEBPUSH_EXTRA_ALLOWED_HOSTS", "a.example, *.b.example")
        assert NotificationSettings().WEBPUSH_EXTRA_ALLOWED_HOSTS == ["a.example", "*.b.example"]


class TestParseSubscription:
    def test_a_browser_subscription(self):
        _, p256dh, auth, _ = _browser_keys()
        parsed = push.parse_subscription(
            {"endpoint": "https://fcm.googleapis.com/x", "expirationTime": None, "keys": {"p256dh": p256dh, "auth": auth}}
        )
        assert parsed == {"endpoint": "https://fcm.googleapis.com/x", "p256dh": p256dh, "auth": auth}

    def test_padded_keys_are_normalized(self):
        _, p256dh, auth, _ = _browser_keys()
        parsed = push.parse_subscription(
            {"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": p256dh + "=", "auth": auth + "=="}}
        )
        assert parsed["p256dh"] == p256dh and parsed["auth"] == auth

    @pytest.mark.parametrize(
        "data",
        [
            None,
            [],
            {"endpoint": "https://evil.example.com/x", "keys": {"p256dh": "x", "auth": "y"}},
            {"endpoint": "https://fcm.googleapis.com/x"},
            {"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": "short", "auth": _b64(b"a" * 16)}},
            {"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": _b64(b"\x04" + b"a" * 64), "auth": "x"}},
            {"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": _b64(b"\x02" + b"a" * 64), "auth": _b64(b"a" * 16)}},
            {"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": 5, "auth": None}},
            {"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": "!!!!", "auth": "@@@"}},
        ],
    )
    def test_rejects(self, data):
        with pytest.raises(push.InvalidSubscription):
            push.parse_subscription(data)


class TestVapidConfig:
    def test_off_without_a_private_key(self, monkeypatch):
        monkeypatch.setattr(settings, "WEBPUSH_VAPID_PRIVATE_KEY", None)
        assert push.vapid_config() is None
        assert not push.push_enabled()

    def test_on_with_a_matching_pair(self, vapid):
        config = push.vapid_config()
        assert config.public_key == vapid[1]
        assert config.subject == "mailto:ops@example.com"

    def test_public_key_is_derived_when_unset(self, vapid, monkeypatch):
        monkeypatch.setattr(settings, "WEBPUSH_VAPID_PUBLIC_KEY", None)
        assert push.vapid_config().public_key == vapid[1]

    def test_off_when_the_pair_does_not_match(self, vapid, monkeypatch):
        monkeypatch.setattr(settings, "WEBPUSH_VAPID_PUBLIC_KEY", _vapid_pair()[1])
        assert push.vapid_config() is None

    def test_off_with_a_malformed_key(self, vapid, monkeypatch):
        monkeypatch.setattr(settings, "WEBPUSH_VAPID_PRIVATE_KEY", "not-a-key")
        assert push.vapid_config() is None

    def test_subject_falls_back_to_the_https_public_url(self, vapid, monkeypatch):
        monkeypatch.setattr(settings, "WEBPUSH_VAPID_SUBJECT", None)
        monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", "https://docs.example.com/")
        assert push.vapid_config().subject == "https://docs.example.com"
        push._load_vapid.cache_clear()
        monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", "http://localhost:7091")
        monkeypatch.setattr(settings, "API_URL", "http://localhost:7091")
        assert push.vapid_config().subject.startswith("mailto:")


class TestBuildPayload:
    def test_bounds_text_and_keeps_urls_relative(self):
        payload = push.build_payload(
            kind="job", title="t" * 500, body="b\n" * 1000, url="https://evil.example.com", conversation_id="c1"
        )
        assert len(payload["title"]) <= push.TITLE_MAX_CHARS
        assert len(payload["body"]) <= push.BODY_MAX_CHARS
        assert payload["url"] == "/"
        assert payload["tag"] == "docsgpt:c1"
        assert push.build_payload(kind="x", title="", body="", url="//evil", conversation_id=None)["url"] == "/"
        assert push.build_payload(kind="x", title="", body="", url="/c/1", conversation_id=None)["title"] == "DocsGPT"

    def test_fits_in_a_push_message(self):
        payload = push.build_payload(kind="monitor", title="é" * 500, body="日" * 2000, url="/c/x", conversation_id="x")
        assert len(json.dumps(payload, ensure_ascii=False).encode()) < 3000


class _Response:
    def __init__(self, status):
        self.status_code = status
        self.text = ""
        self.reason = ""
        self.headers = {}


class TestSendOne:
    def test_encrypts_for_the_browser_and_signs_with_vapid(self, vapid, monkeypatch):
        """A real pywebpush round trip: the browser's key decrypts what the push service receives."""
        import http_ece

        captured = {}

        def fake_request(self, method, url, *args, **kwargs):
            captured.update(method=method, url=url, **kwargs)
            return _Response(201)

        monkeypatch.setattr("requests.Session.request", fake_request)
        browser_key, p256dh, auth_b64, auth = _browser_keys()
        subscription = {"endpoint": "https://fcm.googleapis.com/fcm/send/x", "p256dh": p256dh, "auth": auth_b64}
        status = push._send_one(subscription, '{"title": "hi"}', push.vapid_config(), "topic123")
        assert status == 201
        assert captured["url"] == subscription["endpoint"]
        assert captured["allow_redirects"] is False
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        assert headers["content-encoding"] == "aes128gcm"
        assert headers["topic"] == "topic123"
        assert headers["ttl"] == str(push.PUSH_TTL_SECONDS)
        assert headers["authorization"].startswith("vapid t=") and vapid[1] in headers["authorization"]
        plain = http_ece.decrypt(captured["data"], private_key=browser_key, auth_secret=auth, version="aes128gcm")
        assert json.loads(plain) == {"title": "hi"}

    def test_redirects_are_never_followed(self, monkeypatch):
        seen = {}

        def base_request(self, method, url, *args, **kwargs):
            seen.update(kwargs)
            return _Response(201)

        monkeypatch.setattr("requests.Session.request", base_request)
        push._NoRedirectSession().post("https://fcm.googleapis.com/x", data=b"", allow_redirects=True)
        assert seen["allow_redirects"] is False

    def test_an_error_status_is_returned_not_raised(self, vapid, monkeypatch):
        monkeypatch.setattr("requests.Session.request", lambda self, method, url, *a, **k: _Response(410))
        _, p256dh, auth, _ = _browser_keys()
        subscription = {"endpoint": "https://fcm.googleapis.com/x", "p256dh": p256dh, "auth": auth}
        assert push._send_one(subscription, "{}", push.vapid_config(), "t") == 410


class TestDeliver:
    def _subscribe(self, db, endpoint, user_id="u1"):
        _, p256dh, auth, _ = _browser_keys()
        with db.begin() as conn:
            return str(
                PushSubscriptionsRepository(conn).upsert(user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth)[
                    "id"
                ]
            )

    def _rows(self, db, user_id="u1"):
        with db.connect() as conn:
            return {r["endpoint"]: r for r in PushSubscriptionsRepository(conn).list_for_user(user_id)}

    def test_sends_prunes_gone_and_counts_failures(self, db, vapid, monkeypatch):
        statuses = {
            "https://fcm.googleapis.com/ok": 201,
            "https://fcm.googleapis.com/gone": 410,
            "https://fcm.googleapis.com/missing": 404,
            "https://fcm.googleapis.com/busy": 429,
        }
        for endpoint in statuses:
            self._subscribe(db, endpoint)
        self._subscribe(db, "https://fcm.googleapis.com/boom")
        self._subscribe(db, "https://fcm.googleapis.com/other-user", user_id="u2")
        sent_to = []

        def fake_send(subscription, data, config, topic):
            sent_to.append(subscription["endpoint"])
            if subscription["endpoint"].endswith("boom"):
                raise ConnectionError("network")
            return statuses[subscription["endpoint"]]

        monkeypatch.setattr(push, "_send_one", fake_send)
        payload = push.build_payload(kind="job", title="Done", body="b", url="/c/1", conversation_id="1")
        counts = push.deliver("u1", payload)
        assert counts == {"sent": 1, "pruned": 2, "failed": 2, "skipped": 0}
        assert "https://fcm.googleapis.com/other-user" not in sent_to
        rows = self._rows(db)
        assert set(rows) == {"https://fcm.googleapis.com/ok", "https://fcm.googleapis.com/busy", "https://fcm.googleapis.com/boom"}
        assert rows["https://fcm.googleapis.com/ok"]["last_success_at"] is not None
        assert rows["https://fcm.googleapis.com/busy"]["failure_count"] == 1
        assert rows["https://fcm.googleapis.com/boom"]["failure_count"] == 1

    def test_a_subscription_that_keeps_failing_is_dropped(self, db, vapid, monkeypatch):
        sub_id = self._subscribe(db, "https://fcm.googleapis.com/flaky")
        with db.begin() as conn:
            for _ in range(push.MAX_CONSECUTIVE_FAILURES - 1):
                PushSubscriptionsRepository(conn).record_failure(sub_id)
        monkeypatch.setattr(push, "_send_one", lambda *a: 500)
        assert push.deliver("u1", {"tag": "x"})["pruned"] == 1
        assert self._rows(db) == {}

    def test_an_endpoint_no_longer_allowed_is_skipped_not_sent(self, db, vapid, monkeypatch):
        monkeypatch.setattr(settings, "WEBPUSH_EXTRA_ALLOWED_HOSTS", ["push.example.com"])
        self._subscribe(db, "https://push.example.com/x")
        monkeypatch.setattr(settings, "WEBPUSH_EXTRA_ALLOWED_HOSTS", [])
        monkeypatch.setattr(push, "_send_one", lambda *a: pytest.fail("must not send"))
        assert push.deliver("u1", {"tag": "x"}) == {"sent": 0, "pruned": 0, "failed": 0, "skipped": 1}
        assert len(self._rows(db)) == 1

    def test_nothing_without_vapid(self, monkeypatch):
        monkeypatch.setattr(settings, "WEBPUSH_VAPID_PRIVATE_KEY", None)
        assert push.deliver("u1", {})["sent"] == 0


class TestTask:
    def test_runs_deliver_and_swallows_errors(self, monkeypatch):
        from docsgpt.notifications import tasks

        monkeypatch.setattr(push, "deliver", lambda user_id, payload: {"sent": 1, "user": user_id})
        assert tasks.send_web_push.run("u1", {"title": "t"}) == {"sent": 1, "user": "u1"}
        monkeypatch.setattr(push, "deliver", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
        assert tasks.send_web_push.run("u1", {}) == {"error": True}

    def test_the_worker_loads_the_task(self):
        from docsgpt import celeryconfig

        assert "docsgpt.notifications.tasks" in celeryconfig.imports
