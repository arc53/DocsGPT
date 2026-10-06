"""Notification kinds: the heading each kind gets, and the text a push shows."""

from __future__ import annotations

import pytest

from docsgpt.notifications import kinds, push

JOB_ID = "5f0c2a8e-1b7d-4e6a-9c3f-2d8b7a6e5f41"


class TestHeading:
    @pytest.mark.parametrize(
        ("kind", "heading"),
        [
            ("job", "Background job finished"),
            ("lost", "Background job interrupted"),
            ("monitor", "Monitor matched"),
            ("monitor_paused", "Monitor paused"),
            ("monitor_expired", "Monitor expired"),
            ("trigger", "Webhook received"),
            ("approval", "Approval received"),
        ],
    )
    def test_known_kinds(self, kind, heading):
        assert kinds.heading(kind) == heading

    def test_unknown_kinds_have_none(self):
        assert kinds.heading("something_else") is None
        assert kinds.heading("") is None

    def test_every_wake_source_is_a_known_kind(self):
        from docsgpt.background.wake import WAKE_SOURCES

        assert set(WAKE_SOURCES) <= set(kinds.KIND_HEADINGS)


class TestUserTitle:
    def test_drops_the_job_id_the_model_needs_but_the_user_does_not(self):
        assert kinds.user_title(f"code_executor finished (job {JOB_ID})") == "code_executor finished"
        assert kinds.user_title(f"run_code lost (job {JOB_ID}) (+2 more)") == "run_code lost (+2 more)"

    def test_leaves_other_titles_alone(self):
        assert kinds.user_title("BTC below $50k") == "BTC below $50k"
        assert kinds.user_title("  spaced  ") == "spaced"
        assert kinds.user_title("") == ""
        assert kinds.user_title(None) == ""


class TestPushText:
    def test_a_known_kind_leads_with_its_heading(self):
        assert kinds.push_text("monitor", "BTC below $50k", "It is $49,800.") == (
            "Monitor matched",
            "BTC below $50k: It is $49,800.",
        )

    def test_title_or_body_alone(self):
        assert kinds.push_text("job", "run_code finished", "") == ("Background job finished", "run_code finished")
        assert kinds.push_text("approval", "", "Approved.") == ("Approval received", "Approved.")

    def test_an_unknown_kind_keeps_the_callers_title(self):
        assert kinds.push_text("custom", "Your export is ready", "3 files") == ("Your export is ready", "3 files")
        assert kinds.push_text("custom", "", "3 files") == ("DocsGPT", "3 files")


class TestPushPayloadUsesIt:
    def test_build_payload_words_a_known_kind(self):
        payload = push.build_payload(
            kind="lost", title=f"run_code lost (job {JOB_ID})", body="Verify first.", url="/c/c1", conversation_id="c1"
        )
        assert payload["title"] == "Background job interrupted"
        assert payload["body"] == "run_code lost: Verify first."
        assert payload["kind"] == "lost"
