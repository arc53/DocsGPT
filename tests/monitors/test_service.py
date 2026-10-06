"""Tests for creating, listing and ending monitors (what the monitor tool and the Monitors page call)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from docsgpt.core.settings import settings
from docsgpt.monitors import links, service, sources
from docsgpt.monitors.checks import Content
from docsgpt.monitors.fetch import SourceUnreachable
from docsgpt.monitors.links import token_hash
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.monitors import MonitorsRepository
from docsgpt.storage.db.repositories.trigger_links import TriggerLinksRepository
from tests.monitors.helpers import executor_stub
from tests.monitors.test_sources import TOOLS, FakeExecutor


def _caller(conversation_id, **extra):
    return service.Caller(user_id="u1", conversation_id=conversation_id, **extra)


def _webpage_args(**overrides):
    args = {
        "description": "ACMEB below $90",
        "source": {"type": "webpage", "url": "https://shop.example.com/acmeb"},
        "check": {"type": "threshold", "op": "<", "value": 90},
        "on_match": "tell me the price",
    }
    args.update(overrides)
    return args


@pytest.fixture()
def page(monkeypatch):
    def install(text_value="Price: $95.10", error=None):
        def fetch(url, css_selector=None):
            if error is not None:
                raise error
            return Content(text=text_value)

        monkeypatch.setattr(service, "fetch_webpage", fetch)

    install()
    return install


@pytest.fixture()
def public_url(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", "https://docs.example.com")
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", None)


class TestRefusals:
    def test_monitors_off(self, monkeypatch, conversation_id):
        monkeypatch.setattr(settings, "MONITORS_ENABLED", False)
        assert "turned off" in service.create(_caller(conversation_id), _webpage_args())["error"]

    def test_auto_resume_off(self, monkeypatch, conversation_id):
        monkeypatch.setattr(settings, "AUTO_RESUME_ENABLED", False)
        assert "AUTO_RESUME_ENABLED" in service.create(_caller(conversation_id), _webpage_args())["error"]

    @pytest.mark.parametrize(
        "extra",
        [{"headless": True}, {"workflow": True}, {"api_route": True}, {"outside_caller": True}],
    )
    def test_callers_that_can_never_be_woken(self, conversation_id, extra, page):
        result = service.create(_caller(conversation_id, **extra), _webpage_args())
        assert "error" in result

    def test_no_conversation(self, mon_db):
        assert "saved conversation" in service.create(_caller(None), _webpage_args())["error"]

    def test_shared_or_api_key_conversations(self, mon_db, page):
        with mon_db.begin() as conn:
            repo = ConversationsRepository(conn)
            keyed = str(repo.create("u1", "w", api_key="k1")["id"])
            shared = str(repo.create("u1", "s", is_shared_usage=True)["id"])
        for conversation in (keyed, shared):
            assert "can't be resumed" in service.create(_caller(conversation), _webpage_args())["error"]

    def test_someone_elses_agent(self, mon_db, page):
        with mon_db.begin() as conn:
            agent = AgentsRepository(conn).create("owner-2", "Shared agent", "published")
            conversation = str(ConversationsRepository(conn).create("u1", "c", agent_id=str(agent["id"]))["id"])
        assert "can't be resumed" in service.create(_caller(conversation), _webpage_args())["error"]

    def test_nothing_is_stored_on_refusal(self, mon_db, monkeypatch, conversation_id):
        monkeypatch.setattr(settings, "MONITORS_ENABLED", False)
        service.create(_caller(conversation_id), _webpage_args())
        with mon_db.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM monitors")).scalar() == 0

    def test_per_user_cap(self, monkeypatch, conversation_id, page, events):
        monkeypatch.setattr(settings, "MONITOR_MAX_ACTIVE_PER_USER", 2)
        for _ in range(2):
            assert "monitor_id" in service.create(_caller(conversation_id), _webpage_args())
        result = service.create(_caller(conversation_id), _webpage_args())
        assert "limit is 2" in result["error"]

    def test_cap_zero_turns_creation_off(self, monkeypatch, conversation_id, page):
        monkeypatch.setattr(settings, "MONITOR_MAX_ACTIVE_PER_USER", 0)
        assert "turned off" in service.create(_caller(conversation_id), _webpage_args())["error"]


class TestPolledCreate:
    def test_webpage_baseline_is_returned_and_stored(self, mon_db, conversation_id, page, events):
        result = service.create(_caller(conversation_id), _webpage_args())
        assert result["status"] == "active"
        assert result["baseline"]["value"] == 95.1
        assert result["already_matching"] is False
        assert result["interval"] == "15m"
        assert "how often and until when" in result["next"]
        with mon_db.connect() as conn:
            monitor = MonitorsRepository(conn).get(result["monitor_id"], "u1")
        assert monitor["check_count"] == 1 and monitor["last_checked_at"] is not None
        assert monitor["monitor_state"]["hash"] and monitor["monitor_state"]["check"]["value"] == 95.1
        assert monitor["next_run_at"] is not None and monitor["approval"] is None
        assert events and events[-1]["type"] == "monitor.updated"
        assert events[-1]["payload"]["monitor_id"] == result["monitor_id"]
        assert events[-1]["payload"]["wakes_left"] == 1
        # The web app offers Web Push on an active monitor.updated (backgroundListener).
        assert events[-1]["payload"]["status"] == "active"

    def test_already_matching_is_said(self, conversation_id, page, events):
        page("Price: $80")
        result = service.create(_caller(conversation_id), _webpage_args())
        assert result["already_matching"] is True and "current state" in result["next"]

    def test_unreachable_source_creates_nothing(self, mon_db, conversation_id, page):
        page(error=SourceUnreachable("timeout"))
        assert "can't be reached" in service.create(_caller(conversation_id), _webpage_args())["error"]
        with mon_db.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM schedules")).scalar() == 0

    def test_a_check_that_does_not_fit_creates_nothing(self, conversation_id, page):
        page("no numbers here")
        refused = service.create(_caller(conversation_id), _webpage_args())
        assert "doesn't fit" in refused["error"]
        assert refused["excerpt"] == "no numbers here"

    def test_limits_are_noted(self, monkeypatch, conversation_id, page, events):
        monkeypatch.setattr(settings, "MONITOR_MIN_INTERVAL_SECONDS", 300)
        result = service.create(_caller(conversation_id), _webpage_args(interval="1m"))
        assert result["interval"] == "5m" and result["notes"]


class TestToolSourceApproval:
    @pytest.fixture()
    def tools(self, monkeypatch):
        state = {"pause": None, "result": {"items": [{"id": 1}]}}

        def build(user_id, agent_id, *, headless, allowlist=()):
            state.setdefault("builds", []).append({"headless": headless, "allowlist": list(allowlist)})
            # The creating turn's gate sees the approval pause; a pre-approved headless check does not.
            pause = None if headless and allowlist else state["pause"]
            return FakeExecutor(pause=pause, result=state["result"]), TOOLS

        monkeypatch.setattr(sources, "build_executor", build)
        return state

    def _args(self):
        return {
            "description": "New GitHub issues",
            "source": {"type": "tool", "tool": "list_issues", "args": {"q": "is:open"}},
            "check": {"type": "new_items", "items_path": "items", "id_field": "id"},
            "on_match": "summarize them",
        }

    def test_read_only_call_needs_no_approval(self, mon_db, conversation_id, tools, events):
        executor = executor_stub(conversation_id=conversation_id)
        assert service.create_needs_approval(executor, service.CREATE, self._args()) is False
        result = service.create(_caller(conversation_id, executor=executor), self._args())
        assert result["baseline"]["items_now"] == 1
        with mon_db.connect() as conn:
            monitor = MonitorsRepository(conn).get(result["monitor_id"], "u1")
            schedule = conn.execute(
                text("SELECT tool_allowlist FROM schedules WHERE id = CAST(:id AS uuid)"), {"id": result["monitor_id"]}
            ).scalar()
        assert monitor["approval"]["required"] is False and schedule == []
        assert monitor["monitor_spec"]["source"]["tool"] == "list_issues"

    def test_gated_call_asks_at_creation(self, conversation_id, tools):
        tools["pause"] = {"pause_type": "awaiting_approval"}
        executor = executor_stub(conversation_id=conversation_id)
        assert service.create_needs_approval(executor, service.CREATE, self._args()) is True
        assert service.create_needs_approval(executor, service.LIST, {}) is False
        assert service.create_needs_approval(executor_stub(headless=True), service.CREATE, self._args()) is False

    def test_gated_call_without_approval_is_refused(self, mon_db, conversation_id, tools):
        tools["pause"] = {"pause_type": "awaiting_approval"}
        executor = executor_stub(conversation_id=conversation_id, approved=False)
        result = service.create(_caller(conversation_id, executor=executor), self._args())
        assert "approval" in result["error"]
        with mon_db.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM monitors")).scalar() == 0

    def test_approved_call_is_bound_and_allowlisted(self, mon_db, conversation_id, tools, events):
        tools["pause"] = {"pause_type": "awaiting_approval"}
        executor = executor_stub(conversation_id=conversation_id, approved=True)
        result = service.create(_caller(conversation_id, executor=executor), self._args())
        assert "monitor_id" in result, result
        with mon_db.connect() as conn:
            monitor = MonitorsRepository(conn).get(result["monitor_id"], "u1")
            allowlist = conn.execute(
                text("SELECT tool_allowlist FROM schedules WHERE id = CAST(:id AS uuid)"), {"id": result["monitor_id"]}
            ).scalar()
        assert monitor["approval"]["required"] is True and monitor["approval"]["tool_id"] == "t-gh"
        assert allowlist == ["t-gh"]
        # The baseline replayed the call headless, under the binding.
        assert {"headless": True, "allowlist": ["t-gh"]} in tools["builds"]

    def test_refused_sources(self, conversation_id, tools):
        tools["pause"] = {"pause_type": "requires_client_execution"}
        executor = executor_stub(conversation_id=conversation_id)
        assert service.create_needs_approval(executor, service.CREATE, self._args()) is False
        assert (
            "can't be monitored" in service.create(_caller(conversation_id, executor=executor), self._args())["error"]
        )

    def test_a_failing_lookup_asks_rather_than_skips(self, monkeypatch, conversation_id):
        def broken(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(sources, "build_executor", broken)
        assert service.create_needs_approval(executor_stub(), service.CREATE, self._args()) is True


class TestLinkCreate:
    def test_webhook_returns_url_and_whsec_secret_once(self, mon_db, conversation_id, public_url, events):
        result = service.create(
            _caller(conversation_id),
            {
                "description": "CI finished",
                "source": {"type": "webhook", "signature": "standard_webhooks"},
                "check": {"type": "status", "value_path": "status", "terminal": ["success", "failure"]},
                "on_match": "tell me",
            },
        )
        assert result["url"].startswith("https://docs.example.com/api/triggers/trg_")
        # The model gets a reference; the real secret is only revealed to the owner or filled into approved calls.
        assert result["secret"] == "{{link_secret:" + result["secret_ref"] + "}}"
        assert len(result["secret_ref"]) == 6
        assert result["reachable_from_internet"] is True and "reachability_note" not in result
        assert "curl -X POST" in result["example_curl"] and result["method"] == "POST"
        assert "$DOCSGPT_WEBHOOK_SECRET" in result["example_curl"] or "${DOCSGPT_WEBHOOK_SECRET" in result[
            "example_curl"]
        assert "Reveal secret" in result["next"]
        token = result["url"].rsplit("/", 1)[1]
        with mon_db.connect() as conn:
            link = TriggerLinksRepository(conn).get_live(token_hash(token), "webhook")
            raw = conn.execute(text("SELECT token_hash, secret_encrypted FROM trigger_links")).fetchone()
        assert link["signature_scheme"] == "standard_webhooks"
        secret = links.open_secret(raw[1], "u1")
        assert secret.startswith("whsec_")
        assert token not in raw[0] and secret not in raw[1] and secret not in str(result)
        assert service.reveal_secret(result["monitor_id"], "u1") == {
            "secret": secret, "signature": "standard_webhooks"
        }
        assert service.reveal_secret(result["monitor_id"], "u2") is None
        assert events[-1]["type"] == "monitor.updated" and events[-1]["payload"]["status"] == "active"

    def test_a_webhook_without_a_status_check_says_every_call_wakes(self, conversation_id, public_url, events):
        result = service.create(
            _caller(conversation_id), {"description": "d", "source": {"type": "webhook"}, "on_match": "x"}
        )
        assert any("every call" in note for note in result["notes"])
        assert "counts once" in result["next"]

    def test_a_status_check_tells_the_user_what_to_send(self, conversation_id, public_url, events):
        result = service.create(
            _caller(conversation_id),
            {
                "description": "deploy",
                "source": {"type": "webhook"},
                "check": {"type": "status", "value_path": "deploy.state", "terminal": ["success", "failure"]},
                "on_match": "tell me",
            },
        )
        assert "`deploy.state`" in result["next"] and "success, failure" in result["next"]
        assert "notes" not in result or not any("every call" in n for n in result["notes"])
        assert "deploy" in result["example_curl"] and "state" in result["example_curl"]

    def test_local_base_is_flagged(self, monkeypatch, conversation_id, events):
        monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", None)
        monkeypatch.setattr(settings, "API_URL", "http://localhost:7091")
        result = service.create(
            _caller(conversation_id), {"description": "d", "source": {"type": "webhook"}, "on_match": "x"}
        )
        assert result["reachable_from_internet"] is False and "localhost" in result["reachability_note"]
        assert "secret" not in result

    def test_approval_link_points_at_the_page_and_hides_the_api(self, mon_db, conversation_id, public_url, events):
        result = service.create(
            _caller(conversation_id),
            {
                "description": "Manager approves the announcement",
                "source": {"type": "approval", "question": "Send it?", "details": "Draft"},
                "on_match": "send it",
            },
        )
        assert result["url"].startswith("https://docs.example.com/approve/apv_")
        assert "api_url" not in result and "/api/approvals/" not in str(result)
        assert result["options"] == ["approve", "reject"]
        assert "Never open, approve or reject it yourself" in result["next"]
        with mon_db.connect() as conn:
            link = TriggerLinksRepository(conn).get_live(token_hash(result["url"].rsplit("/", 1)[1]), "approval")
        assert link["max_hits"] == 1 and link["approval_spec"]["question"] == "Send it?"
        assert events[-1]["type"] == "monitor.updated" and events[-1]["payload"]["status"] == "active"

    def test_ingest_source_must_be_the_users(self, mon_db, conversation_id, events):
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        with mon_db.begin() as conn:
            mine = SourcesRepository(conn).create("docs", user_id="u1")
            theirs = SourcesRepository(conn).create("docs", user_id="u2")
        args = {"description": "Docs re-indexed", "on_match": "tell me"}
        bad = service.create(
            _caller(conversation_id), {**args, "source": {"type": "ingest", "source_id": str(theirs["id"])}}
        )
        assert "not one of the user's sources" in bad["error"]
        good = service.create(
            _caller(conversation_id), {**args, "source": {"type": "ingest", "source_id": str(mine["id"])}}
        )
        assert good["status"] == "active" and "interval" not in good


class TestManage:
    def test_list_end_and_resume(self, mon_db, conversation_id, page, events, public_url):
        caller = _caller(conversation_id)
        polled = service.create(caller, _webpage_args())
        hook = service.create(caller, {"description": "d", "source": {"type": "webhook"}, "on_match": "x"})
        listed = service.list_for_conversation(caller)
        assert {m["monitor_id"] for m in listed} == {polled["monitor_id"], hook["monitor_id"]}
        assert all("monitor_state" not in m and "approval" not in m for m in listed)
        listed_hook = next(m for m in listed if m["monitor_id"] == hook["monitor_id"])
        assert [link["state"] for link in listed_hook["links"]] == ["live"]
        assert next(m for m in listed if m["monitor_id"] == polled["monitor_id"])["links"] == []

        paused = service.end(polled["monitor_id"], "u1", "paused", reason="by the user")
        assert paused["status"] == "paused" and paused["next_run_at"] is None
        resumed = service.resume(polled["monitor_id"], "u1")
        assert resumed["status"] == "active" and resumed["next_run_at"] is not None

        assert service.end(hook["monitor_id"], "u2", "cancelled") is None
        assert (
            service.end(hook["monitor_id"], "u1", "cancelled", conversation_id="00000000-0000-0000-0000-000000000000")
            is None
        )
        cancelled = service.end(hook["monitor_id"], "u1", "cancelled")
        assert cancelled["status"] == "cancelled"
        listed_hook = next(m for m in service.list_for_conversation(caller) if m["monitor_id"] == hook["monitor_id"])
        assert listed_hook["links"][0]["state"] == "revoked"
        token = hook["url"].rsplit("/", 1)[1]
        with mon_db.connect() as conn:
            assert TriggerLinksRepository(conn).get_live(token_hash(token), "webhook") is None
        assert service.resume(hook["monitor_id"], "u1") is None

    def test_cancel_revokes_the_bound_approval(self, mon_db, conversation_id, monkeypatch, events):
        def build(user_id, agent_id, *, headless, allowlist=()):
            pause = None if headless and allowlist else {"pause_type": "awaiting_approval"}
            return FakeExecutor(pause=pause, result={"items": []}), TOOLS

        monkeypatch.setattr(sources, "build_executor", build)
        executor = executor_stub(conversation_id=conversation_id, approved=True)
        created = service.create(
            _caller(conversation_id, executor=executor),
            {"description": "d", "source": {"type": "tool", "tool": "list_issues", "args": {}}, "on_match": "x"},
        )
        service.end(created["monitor_id"], "u1", "cancelled")
        with mon_db.connect() as conn:
            monitor = MonitorsRepository(conn).get(created["monitor_id"], "u1")
            allowlist = conn.execute(
                text("SELECT tool_allowlist FROM schedules WHERE id = CAST(:id AS uuid)"), {"id": created["monitor_id"]}
            ).scalar()
        assert monitor["approval"] is None and allowlist == []



class TestGetLink:
    def test_a_get_link_takes_fewer_calls_and_says_where_not_to_paste_it(
        self, mon_db, conversation_id, public_url, events, monkeypatch
    ):
        monkeypatch.setattr(settings, "TRIGGER_GET_MAX_HITS", 7)
        result = service.create(
            _caller(conversation_id),
            {
                "description": "Garage door opened",
                "source": {"type": "webhook", "methods": ["POST", "GET"]},
                "check": {"type": "status", "value_path": "door.state", "terminal": ["open"]},
                "on_match": "tell me",
            },
        )
        assert result["method"] == "POST, GET" and result["max_calls"] == 7
        assert result["example_get"].startswith("curl '") and "door.state=open" in result["example_get"]
        assert "never to paste it into a chat" in result["next"]
        token = result["url"].rsplit("/", 1)[1]
        with mon_db.connect() as conn:
            link = TriggerLinksRepository(conn).get_live(token_hash(token), "webhook")
        assert link["allow_get"] is True and link["max_hits"] == 7

    def test_a_post_link_is_unchanged(self, mon_db, conversation_id, public_url, events):
        result = service.create(
            _caller(conversation_id),
            {"description": "CI", "source": {"type": "webhook"}, "on_match": "tell me"},
        )
        assert result["method"] == "POST" and "example_get" not in result
        token = result["url"].rsplit("/", 1)[1]
        with mon_db.connect() as conn:
            link = TriggerLinksRepository(conn).get_live(token_hash(token), "webhook")
        assert link["allow_get"] is False and link["max_hits"] == links.WEBHOOK_MAX_HITS


class TestQueryBody:
    def test_dotted_keys_nest_and_repeats_list(self):
        from docsgpt.monitors.triggers import query_body

        assert query_body([("a", "1"), ("b.c", "2"), ("b.d", "3"), ("t", "x"), ("t", "y")]) == {
            "a": "1", "b": {"c": "2", "d": "3"}, "t": ["x", "y"]
        }

    def test_a_key_that_is_a_value_and_a_parent_keeps_the_value(self):
        from docsgpt.monitors.triggers import query_body

        assert query_body([("a", "1"), ("a.b", "2"), ("x.", "3"), (".y", "4")]) == {
            "a": "1", "a.b": "2", "x.": "3", ".y": "4"
        }



class TestSenderSecrets:
    def test_a_stripe_link_waits_for_the_owners_secret(self, mon_db, conversation_id, public_url, events):
        result = service.create(
            _caller(conversation_id),
            {"description": "Invoices paid", "source": {"type": "webhook", "signature": "stripe"},
             "on_match": "tell me"},
        )
        assert result["secret"] is None and result["secret_source"] == "sender"
        assert "secret_ref" not in result
        assert "Set signing secret" in result["next"] and "Stripe" in result["signing"]
        assert "Stripe-Signature" in result["example_curl"]
        token = result["url"].rsplit("/", 1)[1]
        with mon_db.connect() as conn:
            link = TriggerLinksRepository(conn).get_live(token_hash(token), "webhook")
        assert link["secret_encrypted"] is None and link["ref"] is None
        assert service.reveal_secret(result["monitor_id"], "u1") is None
        assert service.set_secret(result["monitor_id"], "u1", "whsec_pasted_from_stripe_1") == {
            "saved": True, "signature": "stripe"
        }
        assert service.reveal_secret(result["monitor_id"], "u1")["secret"] == "whsec_pasted_from_stripe_1"
        with pytest.raises(ValueError):
            service.set_secret(result["monitor_id"], "u1", "sk_live_not_a_webhook_secret")
        assert service.set_secret(result["monitor_id"], "u2", "whsec_pasted_from_stripe_1") is None

    def test_a_slack_link_says_to_set_the_secret_before_the_request_url(
        self, mon_db, conversation_id, public_url, events
    ):
        result = service.create(
            _caller(conversation_id),
            {"description": "Mentions", "source": {"type": "webhook", "signature": "slack"}, "on_match": "reply"},
        )
        assert "before setting the Request URL" in result["next"]

    def test_a_header_token_link_shows_its_header(self, mon_db, conversation_id, public_url, events):
        result = service.create(
            _caller(conversation_id),
            {"description": "Pipelines", "on_match": "tell me",
             "source": {"type": "webhook", "signature": "header_token", "signature_header": "X-Gitlab-Token",
                        "methods": ["POST", "GET"]}},
        )
        assert result["signature_header"] == "X-Gitlab-Token"
        assert 'X-Gitlab-Token: $DOCSGPT_WEBHOOK_SECRET' in result["example_curl"]
        assert 'X-Gitlab-Token: $DOCSGPT_WEBHOOK_SECRET' in result["example_get"]
        assert "X-Gitlab-Token" in result["signing"]
        assert result["secret"] == "{{link_secret:" + result["secret_ref"] + "}}"

    def test_setting_a_secret_is_audited_without_the_value(self, mon_db, conversation_id, public_url, events):
        result = service.create(
            _caller(conversation_id),
            {"description": "CI", "source": {"type": "webhook", "signature": "github"}, "on_match": "tell me"},
        )
        service.set_secret(result["monitor_id"], "u1", "replacement-secret-0123456789")
        with mon_db.connect() as conn:
            rows = conn.execute(
                text("SELECT metadata::text FROM auth_events WHERE event = 'monitor.secret_set'")
            ).fetchall()
        assert len(rows) == 1 and "replacement-secret" not in rows[0][0]
        assert service.reveal_secret(result["monitor_id"], "u1")["secret"] == "replacement-secret-0123456789"

    def test_an_unsigned_or_ended_link_takes_no_secret(self, mon_db, conversation_id, public_url, events):
        unsigned = service.create(
            _caller(conversation_id), {"description": "CI", "source": {"type": "webhook"}, "on_match": "tell me"}
        )
        assert service.set_secret(unsigned["monitor_id"], "u1", "a-long-enough-secret-value") is None
        signed = service.create(
            _caller(conversation_id),
            {"description": "CI2", "source": {"type": "webhook", "signature": "github"}, "on_match": "tell me"},
        )
        service.end(signed["monitor_id"], "u1", "cancelled")
        assert service.set_secret(signed["monitor_id"], "u1", "a-long-enough-secret-value") is None


    def test_a_link_that_ends_before_the_write_saves_nothing(
        self, mon_db, conversation_id, public_url, events, monkeypatch
    ):
        result = service.create(
            _caller(conversation_id),
            {"description": "CI3", "source": {"type": "webhook", "signature": "github"}, "on_match": "tell me"},
        )
        monkeypatch.setattr(TriggerLinksRepository, "set_secret", lambda self, link_id, sealed: False)
        assert service.set_secret(result["monitor_id"], "u1", "a-long-enough-secret-value") is None
        with mon_db.connect() as conn:
            assert conn.execute(
                text("SELECT count(*) FROM auth_events WHERE event = 'monitor.secret_set'")
            ).scalar() == 0
