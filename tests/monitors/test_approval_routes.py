"""Tests for the public approval link: GET shows (and changes nothing), the first POST decides, then 409."""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import text

from docsgpt.core.settings import settings
from docsgpt.monitors import service, triggers
from docsgpt.storage.db.repositories.monitors import MonitorsRepository


@pytest.fixture()
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture()
def approval(mon_db, conversation_id, monkeypatch, events):
    """An approval monitor created the way the tool does; returns ``(token, monitor_id)``."""
    monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", "https://docs.example.com")
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", None)

    def make(**source):
        result = service.create(
            service.Caller(user_id="u1", conversation_id=conversation_id),
            {
                "description": "Manager approves the announcement",
                "source": {"type": "approval", "question": "Send the announcement?", "details": "Draft: ...", **source},
                "on_match": "if approved, send it",
            },
        )
        return result["url"].rsplit("/", 1)[1], result["monitor_id"]

    return make


class TestView:
    def test_get_shows_the_question_and_changes_nothing(self, client, mon_db, approval, wakes):
        token, monitor_id = approval()
        response = client.get(f"/api/approvals/{token}")
        assert response.status_code == 200
        body = response.get_json()
        assert body["question"] == "Send the announcement?" and body["details"] == "Draft: ..."
        assert body["options"] == ["approve", "reject"] and body["allow_comment"] is True
        assert body["decided"] is False and body["waiting"] is True
        assert body["title"] == "Manager approves the announcement"
        assert "conversation_id" not in body and "user_id" not in body and "on_match" not in str(body)
        client.get(f"/api/approvals/{token}")
        assert wakes == []
        with mon_db.connect() as conn:
            assert conn.execute(text("SELECT decision FROM trigger_links")).scalar() is None
            assert MonitorsRepository(conn).get_internal(monitor_id)["status"] == "active"

    def test_unknown_token_is_404(self, client, mon_db):
        assert client.get("/api/approvals/apv_not_a_real_token_123").status_code == 404
        assert client.post("/api/approvals/apv_not_a_real_token_123", json={"decision": "approve"}).status_code == 404


class TestDecide:
    def test_first_decision_wins_and_wakes_the_conversation(self, client, mon_db, approval, wakes, conversation_id):
        token, monitor_id = approval()
        response = client.post(
            f"/api/approvals/{token}", json={"decision": "Approve", "comment": "Call it a hybrid week."}
        )
        assert response.status_code == 200 and response.get_json() == {"decided": True, "decision": "approve"}
        assert len(wakes) == 1
        wake = wakes[0]
        assert wake["source"] == "approval" and wake["conversation_id"] == conversation_id
        assert wake["ref_id"] == monitor_id and wake["dedupe_key"].startswith("approval:")
        assert wake["payload"] == {"decision": "approve", "comment": "Call it a hybrid week."}
        assert "Call it a hybrid week." not in wake["body"]
        assert "if approved, send it" in wake["body"]
        assert "covers only what they saw plus the changes their comment asks for" in wake["body"]

        again = client.post(f"/api/approvals/{token}", json={"decision": "reject"})
        assert again.status_code == 409 and len(wakes) == 1
        view = client.get(f"/api/approvals/{token}").get_json()
        assert view["decided"] is True and view["decision"] == "approve" and view["waiting"] is False
        with mon_db.connect() as conn:
            monitor = MonitorsRepository(conn).get_internal(monitor_id)
        assert monitor["status"] == "completed" and monitor["wake_count"] == 1

    def test_custom_options_and_bad_decisions(self, client, approval, wakes):
        token, _ = approval(options=["Ship", "Hold", "Rework"], allow_comment=False)
        assert client.get(f"/api/approvals/{token}").get_json()["options"] == ["Ship", "Hold", "Rework"]
        assert client.post(f"/api/approvals/{token}", json={"decision": "approve"}).status_code == 400
        assert client.post(f"/api/approvals/{token}", json={}).status_code == 400
        no_comment = client.post(f"/api/approvals/{token}", json={"decision": "hold", "comment": "x"})
        assert no_comment.status_code == 400
        assert client.post(f"/api/approvals/{token}", json={"decision": "hold"}).status_code == 200
        assert wakes[0]["payload"]["decision"] == "Hold"

    def test_a_form_post_works(self, client, approval, wakes):
        token, _ = approval()
        assert client.post(f"/api/approvals/{token}", data={"decision": "reject"}).status_code == 200

    def test_the_agents_own_fetchers_cannot_decide(self, client, approval, wakes):
        token, _ = approval()
        for agent in ("DocsGPT-Agent/1.0", "DocsGPT-Monitor/1.0"):
            response = client.post(
                f"/api/approvals/{token}", json={"decision": "approve"}, headers={"User-Agent": agent}
            )
            assert response.status_code == 403
        assert wakes == []

    def test_a_cancelled_monitor_link_is_404(self, client, approval):
        token, monitor_id = approval()
        service.end(monitor_id, "u1", "cancelled")
        assert client.get(f"/api/approvals/{token}").status_code == 404
        assert client.post(f"/api/approvals/{token}", json={"decision": "approve"}).status_code == 404

    def test_a_paused_monitor_is_not_waiting(self, client, approval, wakes):
        token, monitor_id = approval()
        service.end(monitor_id, "u1", "paused")
        assert client.post(f"/api/approvals/{token}", json={"decision": "approve"}).status_code == 409
        assert wakes == []

    def test_long_comments_are_cut(self, client, approval, wakes):
        token, _ = approval()
        client.post(f"/api/approvals/{token}", json={"decision": "approve", "comment": "x" * 5000})
        assert len(wakes[0]["payload"]["comment"]) == triggers.MAX_COMMENT_CHARS

    def test_rate_limited(self, client, approval, monkeypatch, fake_redis, wakes):
        monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: fake_redis)
        token, _ = approval()
        statuses = [
            client.post(f"/api/approvals/{token}", json={"decision": "maybe"}).status_code
            for _ in range(triggers.APPROVAL_RATE_PER_MINUTE + 2)
        ]
        assert statuses[-1] == 429 and statuses[0] == 400

    def test_concurrent_decisions_only_one_wins(self, mon_db, approval, wakes):
        token, _ = approval()
        results = []

        def press(choice):
            results.append(triggers.decide(token, decision=choice, comment=None, headers={})[0])

        threads = [threading.Thread(target=press, args=(c,)) for c in ("approve", "reject") * 4]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(results).count(200) == 1 and all(code in (200, 409) for code in results)
        assert len(wakes) == 1
