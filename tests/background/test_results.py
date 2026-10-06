"""Tests for the model-facing job text."""

from __future__ import annotations

from docsgpt.background.results import (
    LOST_NOTE,
    final_view,
    head_tail,
    model_status,
    running_payload,
    stored_result,
)


class TestHeadTail:
    def test_short_text_is_unchanged(self):
        assert head_tail("abc", 10) == "abc"

    def test_long_text_keeps_head_and_tail_within_the_limit(self):
        text = "H" * 600 + "M" * 1000 + "T" * 600
        out = head_tail(text, 500)
        assert len(out) <= 500
        assert out.startswith("H")
        assert out.endswith("T")
        assert "characters omitted" in out

    def test_non_strings_are_converted(self):
        assert head_tail({"a": 1}, 100) == "{'a': 1}"


class TestRunningPayload:
    def test_auto_resume_note(self):
        payload = running_payload("j1", auto_resume=True, elapsed_s=31.7, output_tail="x" * 5000)
        assert payload["status"] == "running"
        assert payload["job_id"] == "j1"
        assert payload["started_as"] == "background"
        assert payload["elapsed_s"] == 31
        assert len(payload["output_tail"]) == 2000
        assert "resumed automatically" in payload["note"]
        assert "Do NOT run it again" in payload["note"]
        assert "wait on it with check_job" in payload["note"]
        assert "leave out the job id" in payload["note"]

    def test_poll_only_note(self):
        payload = running_payload("j1", auto_resume=False, elapsed_s=0)
        assert "not resumed" in payload["note"]
        assert "check_job" in payload["note"]
        assert "output_tail" not in payload


class TestFinalView:
    def test_lost_reads_as_failed_with_the_lost_note(self):
        view = final_view({"id": "j", "tool_name": "t", "action_name": "a", "status": "lost"}, max_chars=100)
        assert view["status"] == "failed"
        assert view["note"] == LOST_NOTE
        assert model_status("lost") == "failed"

    def test_result_is_bounded(self):
        job = {
            "id": "j",
            "tool_name": "code_executor",
            "action_name": "run_code",
            "status": "completed",
            "result": stored_result("x" * 5000, status="completed", artifacts=[{"id": "a1"}]),
        }
        view = final_view(job, max_chars=1000)
        assert view["tool"] == "code_executor.run_code"
        assert len(view["result"]) <= 1000
        assert view["artifacts"] == [{"id": "a1"}]

    def test_error_message(self):
        job = {"id": "j", "tool_name": "t", "action_name": "a", "status": "failed", "error": {"message": "boom"}}
        assert final_view(job, max_chars=100)["error"] == "boom"
