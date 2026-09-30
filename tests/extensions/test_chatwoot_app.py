"""Tests for the Chatwoot webhook bridge in ``extensions/chatwoot/app.py``."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import time
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
import requests

APP_PATH = Path(__file__).resolve().parents[2] / "extensions" / "chatwoot" / "app.py"
SECRET = "webhook-secret"


def _load_app() -> ModuleType:
    """Load the Chatwoot bridge module from its file path.

    Returns:
        The freshly imported ``app`` module.
    """
    spec = importlib.util.spec_from_file_location("chatwoot_bridge_app", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Return the bridge module configured with test settings."""
    module = _load_app()
    monkeypatch.setattr(module, "docsgpt_url", "http://docsgpt.test")
    monkeypatch.setattr(module, "chatwoot_url", "http://chatwoot.test")
    monkeypatch.setattr(module, "docsgpt_key", "agent-key")
    monkeypatch.setattr(module, "chatwoot_token", "cw-token")
    monkeypatch.setattr(module, "chatwoot_webhook_secret", SECRET)
    monkeypatch.setattr(module, "chatwoot_allow_unsigned", False)
    monkeypatch.setattr(module, "account_id", None)
    monkeypatch.setattr(module, "assignee_id", None)
    return module


def _response(status: int, payload: object) -> MagicMock:
    """Build a fake ``requests.Response``."""
    resp = MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = payload
    resp.text = json.dumps(payload)
    return resp


def _signed_headers(body: bytes, timestamp: int | None = None) -> dict[str, str]:
    """Sign ``body`` the way Chatwoot does: HMAC-SHA256 over ``{timestamp}.{body}``."""
    ts = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Chatwoot-Timestamp": ts,
        "X-Chatwoot-Signature": f"sha256={digest}",
    }


def _event(**overrides: object) -> dict:
    """Build a Chatwoot ``message_created`` webhook payload."""
    event = {
        "event": "message_created",
        "message_type": "incoming",
        "content": "How do I install DocsGPT?",
        "sender": {"id": 7},
        "account": {"id": 1},
        "conversation": {"id": 42, "labels": [], "meta": {"assignee": None}},
    }
    event.update(overrides)
    return event


class TestSendToBot:
    def test_posts_valid_payload_and_returns_answer(self, bridge: ModuleType) -> None:
        with patch.object(bridge.requests, "post", return_value=_response(200, {"answer": "Use pip."})) as post:
            assert bridge.send_to_bot(7, "hi") == "Use pip."

        url = post.call_args.args[0]
        payload = post.call_args.kwargs["json"]
        assert url == "http://docsgpt.test/api/answer"
        assert payload["question"] == "hi"
        assert payload["api_key"] == "agent-key"
        assert json.loads(payload["history"]) == []
        assert "embeddings_key" not in payload

    def test_returns_none_on_error_status(self, bridge: ModuleType) -> None:
        resp = _response(500, {"error": "An error occurred processing your request"})
        with patch.object(bridge.requests, "post", return_value=resp):
            assert bridge.send_to_bot(7, "hi") is None

    def test_returns_none_when_answer_missing(self, bridge: ModuleType) -> None:
        with patch.object(bridge.requests, "post", return_value=_response(200, {"error": "nope"})):
            assert bridge.send_to_bot(7, "hi") is None

    def test_returns_none_on_connection_error(self, bridge: ModuleType) -> None:
        with patch.object(bridge.requests, "post", side_effect=requests.ConnectionError("down")):
            assert bridge.send_to_bot(7, "hi") is None


class TestWebhook:
    def _post(self, bridge: ModuleType, event: dict, headers: dict[str, str] | None = None):
        body = json.dumps(event).encode()
        client = bridge.app.test_client()
        return client.post("/docsgpt", data=body, headers=headers or _signed_headers(body))

    def test_rejects_unsigned_request(self, bridge: ModuleType) -> None:
        resp = self._post(bridge, _event(), headers={"Content-Type": "application/json"})
        assert resp.status_code == 401

    def test_rejects_signature_without_timestamp(self, bridge: ModuleType) -> None:
        body = json.dumps(_event()).encode()
        digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        headers = {"Content-Type": "application/json", "X-Chatwoot-Signature": f"sha256={digest}"}
        assert self._post(bridge, _event(), headers=headers).status_code == 401

    def test_rejects_stale_timestamp(self, bridge: ModuleType) -> None:
        body = json.dumps(_event()).encode()
        headers = _signed_headers(body, timestamp=int(time.time()) - 3600)
        assert self._post(bridge, _event(), headers=headers).status_code == 401

    def test_relays_answer_to_chatwoot(self, bridge: ModuleType) -> None:
        answer = _response(200, {"answer": "Use pip."})
        created = _response(200, {"id": 99, "content": "Use pip."})
        with patch.object(bridge.requests, "post", side_effect=[answer, created]) as post:
            resp = self._post(bridge, _event())

        assert resp.status_code == 200
        chatwoot_call = post.call_args_list[1]
        assert chatwoot_call.args[0] == "http://chatwoot.test/api/v1/accounts/1/conversations/42/messages"
        assert chatwoot_call.kwargs["json"] == {"content": "Use pip."}
        assert chatwoot_call.kwargs["headers"]["api_access_token"] == "cw-token"

    def test_docsgpt_error_returns_502_without_posting(self, bridge: ModuleType) -> None:
        with patch.object(bridge.requests, "post", return_value=_response(500, {"error": "boom"})) as post:
            resp = self._post(bridge, _event())

        assert resp.status_code == 502
        assert post.call_count == 1

    def test_chatwoot_error_returns_502(self, bridge: ModuleType) -> None:
        answer = _response(200, {"answer": "Use pip."})
        failed = _response(401, {"error": "unauthorized"})
        with patch.object(bridge.requests, "post", side_effect=[answer, failed]):
            resp = self._post(bridge, _event())

        assert resp.status_code == 502

    def test_ignores_outgoing_messages(self, bridge: ModuleType) -> None:
        with patch.object(bridge.requests, "post") as post:
            resp = self._post(bridge, _event(message_type="outgoing"))

        assert resp.status_code == 200
        post.assert_not_called()

    def test_ignores_human_requested_label(self, bridge: ModuleType) -> None:
        conversation = {"id": 42, "labels": ["human-requested"], "meta": {"assignee": None}}
        with patch.object(bridge.requests, "post") as post:
            resp = self._post(bridge, _event(conversation=conversation))

        assert resp.status_code == 200
        post.assert_not_called()

    def test_account_filter_skips_other_accounts(self, bridge: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(bridge, "account_id", "5")
        with patch.object(bridge.requests, "post") as post:
            resp = self._post(bridge, _event())

        assert resp.status_code == 200
        post.assert_not_called()

    def test_assignee_filter_matches_assigned_agent(
        self, bridge: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bridge, "assignee_id", "3")
        conversation = {"id": 42, "labels": [], "meta": {"assignee": {"id": 3}}}
        answer = _response(200, {"answer": "Use pip."})
        created = _response(200, {"id": 99})
        with patch.object(bridge.requests, "post", side_effect=[answer, created]) as post:
            resp = self._post(bridge, _event(conversation=conversation))

        assert resp.status_code == 200
        assert post.call_count == 2


class TestAllowUnsigned:
    def _post(self, bridge: ModuleType, headers: dict[str, str]):
        body = json.dumps(_event()).encode()
        return bridge.app.test_client().post("/docsgpt", data=body, headers=headers)

    def test_flag_parsed_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("chatwoot_allow_unsigned", "true")
        assert _load_app().chatwoot_allow_unsigned is True
        monkeypatch.setenv("chatwoot_allow_unsigned", "false")
        assert _load_app().chatwoot_allow_unsigned is False
        monkeypatch.delenv("chatwoot_allow_unsigned")
        assert _load_app().chatwoot_allow_unsigned is False

    def test_startup_warning_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("chatwoot_allow_unsigned", "true")
        with caplog.at_level("WARNING"):
            _load_app()
        assert any("chatwoot_allow_unsigned" in r.getMessage() for r in caplog.records)

    def test_unsigned_request_rejected_by_default(self, bridge: ModuleType) -> None:
        assert self._post(bridge, {"Content-Type": "application/json"}).status_code == 401

    def test_unsigned_request_accepted_when_allowed(
        self, bridge: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bridge, "chatwoot_allow_unsigned", True)
        monkeypatch.setattr(bridge, "chatwoot_webhook_secret", "")
        answer = _response(200, {"answer": "Use pip."})
        created = _response(200, {"id": 99})
        with patch.object(bridge.requests, "post", side_effect=[answer, created]) as post:
            resp = self._post(bridge, {"Content-Type": "application/json"})

        assert resp.status_code == 200
        assert post.call_count == 2

    def test_bad_signature_still_rejected_when_allowed(
        self, bridge: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bridge, "chatwoot_allow_unsigned", True)
        headers = {
            "Content-Type": "application/json",
            "X-Chatwoot-Timestamp": str(int(time.time())),
            "X-Chatwoot-Signature": "sha256=deadbeef",
        }
        assert self._post(bridge, headers).status_code == 401
