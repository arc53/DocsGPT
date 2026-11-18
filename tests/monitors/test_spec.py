"""Tests for validating monitor_create requests and the values derived from them."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from docsgpt.core.settings import settings
from docsgpt.monitors import spec
from docsgpt.monitors.spec import SpecError, parse_request

NOW = datetime(2026, 10, 5, 12, 7, tzinfo=timezone.utc)


def _req(**overrides):
    args = {
        "description": "ACMEB below $90",
        "source": {"type": "webpage", "url": "https://example.com/price"},
        "on_match": "tell me the price",
    }
    args.update(overrides)
    return parse_request(args, now=NOW)


class TestDefaultsAndLimits:
    def test_defaults_come_from_settings(self):
        request = _req()
        assert request.interval_seconds == settings.MONITOR_DEFAULT_INTERVAL_SECONDS
        assert request.expires_at == NOW + timedelta(days=settings.MONITOR_DEFAULT_TTL_DAYS)
        assert request.max_wakes == settings.MONITOR_DEFAULT_MAX_WAKES
        assert request.polled and request.notes == []

    def test_short_interval_is_raised_to_the_minimum_and_noted(self, monkeypatch):
        monkeypatch.setattr(settings, "MONITOR_MIN_INTERVAL_SECONDS", 300)
        request = _req(interval="1m")
        assert request.interval_seconds == 300
        assert "5m" in request.notes[0]

    def test_bench_minimum_of_sixty_seconds_is_accepted(self, monkeypatch):
        monkeypatch.setattr(settings, "MONITOR_MIN_INTERVAL_SECONDS", 60)
        assert _req(interval="1m").interval_seconds == 60

    def test_lifetime_and_wakes_are_capped(self, monkeypatch):
        monkeypatch.setattr(settings, "MONITOR_MAX_TTL_DAYS", 30)
        monkeypatch.setattr(settings, "MONITOR_MAX_WAKES", 20)
        request = _req(expires_in="90d", max_wakes=50)
        assert request.expires_at == NOW + timedelta(days=30)
        assert request.max_wakes == 20
        assert len(request.notes) == 2

    def test_the_lifetime_note_says_how_to_go_longer(self, monkeypatch):
        """The cap note must not invite a schedule in place of a link: a schedule can't receive calls."""
        monkeypatch.setattr(settings, "MONITOR_MAX_TTL_DAYS", 30)
        hook = _req(source={"type": "webhook"}, expires_in="90d")
        assert hook.notes == [
            "lifetime lowered to 30d, the longest allowed; to keep the link longer, the user asks for a new one "
            "before it expires"
        ]
        polled = _req(expires_in="90d")
        assert "create a new monitor before it expires" in polled.notes[0]

    def test_weeks_and_numbers_are_durations(self):
        assert _req(expires_in="1w").expires_at == NOW + timedelta(days=7)
        assert _req(interval=3600).interval_seconds == 3600

    @pytest.mark.parametrize("bad", ["soon", "-5m", True, "0h"])
    def test_bad_durations(self, bad):
        with pytest.raises(SpecError):
            _req(interval=bad)

    def test_interval_longer_than_lifetime_is_refused(self):
        with pytest.raises(SpecError, match="longer than"):
            _req(interval="2d", expires_in="1d")

    def test_event_sources_have_no_interval(self):
        request = _req(source={"type": "webhook"}, interval="5m")
        assert request.interval_seconds is None and not request.polled
        assert "not polled" in request.notes[0]


class TestValidation:
    @pytest.mark.parametrize(
        "overrides,message",
        [
            ({"description": ""}, "description"),
            ({"on_match": ""}, "on_match"),
            ({"source": {"type": "email"}}, "source.type"),
            ({"source": {"type": "webpage", "url": "ftp://x"}}, "http"),
            ({"source": {"type": "webpage", "url": "https://x", "css_selector": "div[["}}, "CSS"),
            ({"source": {"type": "tool"}}, "source.tool"),
            ({"source": {"type": "tool", "tool": "t", "args": "x"}}, "source.args"),
            ({"source": {"type": "webhook", "signature": "md5"}}, "signature"),
            ({"source": {"type": "approval"}}, "question"),
            ({"source": {"type": "approval", "question": "Q", "options": ["only"]}}, "2 to 6"),
            ({"check": {"type": "regex", "pattern": "("}}, "regular expression"),
            ({"check": {"type": "threshold", "op": "~", "value": 1}}, "op"),
            ({"check": {"type": "threshold", "op": "<", "value": "x"}}, "number"),
            ({"check": {"type": "status", "value_path": "status"}}, "terminal"),
            ({"check": {"type": "new_items"}}, "id_field"),
            ({"max_wakes": 0}, "at least 1"),
        ],
    )
    def test_rejects(self, overrides, message):
        with pytest.raises(SpecError, match=message):
            _req(**overrides)

    def test_operator_words_and_status_terminals_normalize(self):
        threshold = _req(check={"type": "threshold", "op": "below", "value": "90", "value_path": "price"}).check
        assert threshold == {"type": "threshold", "value_path": "price", "op": "<", "value": 90.0}
        status = _req(check={"type": "status", "value_path": "status", "terminal": ["Success", "FAILURE", "success"]})
        assert status.check["terminal"] == ["success", "failure"]

    def test_approval_defaults_and_rules(self):
        request = _req(source={"type": "approval", "question": "Send it?", "context": "Draft text"})
        assert request.source["options"] == ["approve", "reject"]
        assert request.source["allow_comment"] is True
        assert request.source["details"] == "Draft text"
        assert request.max_wakes == 1

    def test_an_approval_ignores_a_check_and_condition_with_a_note(self):
        """The decision is the event; a check can't change that, so it is dropped, not refused."""
        request = _req(
            source={"type": "approval", "question": "Q"}, check={"type": "regex", "pattern": "(?s)."},
            condition="if they approve",
        )
        assert request.check is None and request.condition is None
        assert any("check and condition ignored" in note for note in request.notes)
        malformed = _req(source={"type": "approval", "question": "Q"}, check={"type": "nonsense"})
        assert malformed.check is None

    def test_approval_on_match_defaults(self):
        assert parse_request(
            {"description": "d", "source": {"type": "approval", "question": "Q"}}, now=NOW
        ).on_match

    def test_an_ingest_ignores_a_check_with_a_note_and_keeps_its_condition(self):
        request = _req(source={"type": "ingest", "source_id": "s"}, check={"type": "changed"}, condition="it failed")
        assert request.check is None and request.condition == "it failed"
        assert any("check ignored" in note for note in request.notes)

    def test_a_malformed_check_on_a_webhook_is_still_an_error(self):
        with pytest.raises(SpecError):
            _req(source={"type": "webhook"}, check={"type": "nonsense"})


class TestDerived:
    def test_args_hash_is_of_the_template(self):
        args = {"query": "after:{{last_checked_date}} from:boss"}
        first = spec.canonical_args_hash("t1", "search", args)
        assert first == spec.canonical_args_hash("t1", "search", dict(args))
        assert first != spec.canonical_args_hash("t1", "search", {"query": "after:2026/10/05 from:boss"})
        assert first != spec.canonical_args_hash("t2", "search", args)
        assert first != spec.canonical_args_hash("t1", "send", args)

    def test_substitute_replaces_placeholders_deeply(self):
        args = {"q": "after:{{last_checked_date}}", "range": ["{{last_checked_at}}", "{{now}}"], "n": 3}
        out = spec.substitute(args, now=NOW, last_checked_at="2026-10-04T08:00:00Z")
        assert out == {"q": "after:2026/10/04", "range": ["2026-10-04T08:00:00Z", "2026-10-05T12:07:00Z"], "n": 3}
        assert args["q"] == "after:{{last_checked_date}}"
        first = spec.substitute({"q": "{{last_changed_at}}"}, now=NOW)
        assert first == {"q": "2026-10-05T12:07:00Z"}

    def test_next_tick_avoids_the_hour_and_half_hour_and_caps_at_expiry(self):
        for minute in range(60):
            now = NOW.replace(minute=minute, second=0)
            tick = spec.next_tick(now, 900, None)
            assert tick.minute not in (0, 30)
            assert tick >= now + timedelta(seconds=900)
        end = NOW + timedelta(minutes=5)
        assert spec.next_tick(NOW, 900, end) == end

    def test_bounded_state_trims_the_big_parts(self):
        import json

        seen = [f"item-{i:06d}" for i in range(1000)]
        state = {"hash": "h", "excerpt": "x" * 20000, "check": {"holds": True, "epoch": 2, "key": "k", "seen": seen}}
        bounded = spec.bounded_state(state)
        assert len(json.dumps(bounded).encode()) <= spec.STATE_LIMIT_BYTES
        assert bounded["hash"] == "h"
        assert bounded["check"]["epoch"] == 2 and bounded["check"]["holds"] is True
        # The newest ids are the ones kept.
        assert bounded["check"]["seen"][-1] == "item-000999"
        assert state["check"]["seen"] is seen and len(seen) == 1000

    def test_bounded_state_leaves_small_state_alone(self):
        state = {"hash": "h", "excerpt": "short", "check": {"holds": False, "seen": ["a"]}}
        assert spec.bounded_state(state) == state

    def test_human_duration(self):
        assert spec.human_duration(900) == "15m"
        assert spec.human_duration(86400 * 7) == "7d"
        assert spec.human_duration(90) == "90s"


class TestWebhookMethods:
    def test_post_only_by_default(self):
        assert "methods" not in _req(source={"type": "webhook"}).source

    def test_get_is_opt_in_and_lives_a_short_while(self, monkeypatch):
        monkeypatch.setattr(settings, "TRIGGER_GET_DEFAULT_TTL_HOURS", 12)
        request = _req(source={"type": "webhook", "methods": ["get", "POST"]})
        assert request.source["methods"] == ["POST", "GET"]
        assert request.expires_at == NOW + timedelta(hours=12)

    def test_an_explicit_lifetime_still_applies(self):
        request = _req(source={"type": "webhook", "methods": ["GET"]}, expires_in="3d")
        assert request.source["methods"] == ["POST", "GET"]
        assert request.expires_at == NOW + timedelta(days=3)

    @pytest.mark.parametrize(
        "source,message",
        [
            ({"type": "webhook", "methods": ["PUT"]}, "takes only POST, GET"),
            ({"type": "webhook", "methods": "nonsense"}, "takes only"),
            ({"type": "webhook", "methods": [1]}, "must be a list"),
            ({"type": "webhook", "methods": ["GET"], "signature": "github"}, "a GET call has none"),
        ],
    )
    def test_rejects(self, source, message):
        with pytest.raises(SpecError, match=message):
            _req(source=source)


class TestExposeSecret:
    @pytest.mark.parametrize("value", [True, "yes", 1])
    def test_a_model_can_never_ask_for_the_raw_secret(self, value):
        request = _req(source={"type": "webhook", "signature": "github", "expose_secret": value})
        assert "expose_secret" not in request.source and "expose_secret_ignored" not in request.source
        assert any("expose_secret ignored" in note for note in request.notes)

    def test_false_is_simply_the_default(self):
        request = _req(source={"type": "webhook", "signature": "github", "expose_secret": False})
        assert not any("expose_secret" in note for note in request.notes)


class TestSchemes:
    @pytest.mark.parametrize("scheme", ["stripe", "slack", "header_token", "bearer"])
    def test_new_schemes_are_accepted(self, scheme):
        assert _req(source={"type": "webhook", "signature": scheme}).source["signature"] == scheme

    def test_a_header_token_names_its_header(self):
        source = _req(source={"type": "webhook", "signature": "header_token", "signature_header": "X-Gitlab-Token"}
                      ).source
        assert source["signature_header"] == "X-Gitlab-Token"
        assert "signature_header" not in _req(source={"type": "webhook", "signature": "header_token"}).source

    @pytest.mark.parametrize(
        "source,message",
        [
            ({"signature": "bearer", "signature_header": "X-Token"}, "only to signature"),
            ({"signature": "header_token", "signature_header": "Bad Header"}, "header name like"),
            ({"signature": "header_token", "signature_header": "Authorization"}, "can't be Authorization"),
            ({"signature": "header_token", "signature_header": "webhook-id"}, "can't be webhook-id"),
            ({"signature": "stripe", "methods": ["GET"]}, "a GET call has none"),
        ],
    )
    def test_rejects(self, source, message):
        with pytest.raises(SpecError, match=message):
            _req(source={"type": "webhook", **source})

    @pytest.mark.parametrize("scheme", ["header_token", "bearer"])
    def test_a_static_token_link_may_take_get(self, scheme):
        assert _req(source={"type": "webhook", "signature": scheme, "methods": ["GET"]}).source["methods"] == [
            "POST", "GET"
        ]
