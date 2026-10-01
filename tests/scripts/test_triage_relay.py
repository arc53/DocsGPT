"""Tests for the triage relay (.github/triage/relay.py): event routing and fact extraction."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

RELAY_PATH = Path(__file__).resolve().parents[2] / ".github" / "triage" / "relay.py"
_spec = importlib.util.spec_from_file_location("triage_relay", RELAY_PATH)
relay = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = relay
_spec.loader.exec_module(relay)

BOT = "arc53-machine"
SKIP = relay.Maintainers.from_env(None, None)


def _issue(**overrides):
    issue = {"number": 7, "state": "open", "labels": [], "user": {"login": "reporter", "type": "User"}}
    issue.update(overrides)
    return issue


def _comment(body, login="someone", association="NONE"):
    return {"id": 99, "body": body, "author_association": association, "user": {"login": login, "type": "User"}}


def _sender(login="someone", kind="User"):
    return {"login": login, "type": kind}


class TestClaims:
    @pytest.mark.parametrize(
        "text",
        [
            "Can I work on this?",
            "Hi, I'd like to work on this issue",
            "I would like to take this one",
            "Please assign this to me",
            "assign me",
            "I'm working on this already",
            "Let me fix it",
            "i want to contribute to this",
        ],
    )
    def test_claims(self, text):
        assert relay.is_claim(text)

    @pytest.mark.parametrize(
        "text",
        ["Can someone fix this?", "Is anyone working on this?", "+1, same here", "This was assigned to me by mistake? no"],
    )
    def test_not_claims(self, text):
        assert not relay.is_claim(text)


class TestRoute:
    def test_issue_opened(self):
        event = {"action": "opened", "issue": _issue(), "sender": _sender()}
        assert relay.route("issues", event, BOT, SKIP) == {"kind": "issue_opened", "number": 7}

    def test_bot_sender_is_skipped(self):
        event = {"action": "opened", "issue": _issue(), "sender": _sender(BOT)}
        assert relay.route("issues", event, BOT, SKIP)["kind"] is None

    def test_claim_comment(self):
        event = {"action": "created", "issue": _issue(), "comment": _comment("can I work on this?"), "sender": _sender()}
        assert relay.route("issue_comment", event, BOT, SKIP) == {
            "kind": "issue_claim", "number": 7, "comment_id": 99,
        }

    def test_maintainer_comment_is_skipped(self):
        event = {
            "action": "created",
            "issue": _issue(),
            "comment": _comment("can I work on this?", association="MEMBER"),
            "sender": _sender(),
        }
        assert relay.route("issue_comment", event, BOT, SKIP)["kind"] is None

    def test_comment_on_pull_request_is_skipped(self):
        event = {
            "action": "created",
            "issue": _issue(pull_request={"url": "x"}),
            "comment": _comment("can I work on this?"),
            "sender": _sender(),
        }
        assert relay.route("issue_comment", event, BOT, SKIP)["kind"] is None

    def test_author_reply_while_waiting(self):
        event = {
            "action": "created",
            "issue": _issue(labels=[{"name": "needs-info"}]),
            "comment": _comment("Here are the logs", login="reporter"),
            "sender": _sender("reporter"),
        }
        assert relay.route("issue_comment", event, BOT, SKIP)["kind"] == "issue_author_reply"

    def test_plain_comment_is_skipped(self):
        event = {"action": "created", "issue": _issue(), "comment": _comment("+1"), "sender": _sender()}
        assert relay.route("issue_comment", event, BOT, SKIP)["kind"] is None

    def test_pull_request_opened(self):
        pr = {"number": 5, "draft": False, "user": {"login": "dev", "type": "User"}, "author_association": "NONE"}
        event = {"action": "opened", "pull_request": pr, "sender": _sender("dev")}
        assert relay.route("pull_request_target", event, BOT, SKIP) == {"kind": "pr_opened", "number": 5}

    @pytest.mark.parametrize(
        "overrides",
        [
            {"draft": True},
            {"user": {"login": "dependabot[bot]", "type": "Bot"}},
            {"user": {"login": BOT, "type": "User"}},
            {"author_association": "MEMBER"},
        ],
    )
    def test_pull_requests_not_triaged(self, overrides):
        pr = {"number": 5, "draft": False, "user": {"login": "dev", "type": "User"}, "author_association": "NONE"}
        pr.update(overrides)
        event = {"action": "opened", "pull_request": pr, "sender": _sender("dev")}
        assert relay.route("pull_request_target", event, BOT, SKIP)["kind"] is None

    def test_coderabbit_status(self):
        sender = _sender("coderabbitai[bot]", "Bot")
        event = {"context": "CodeRabbit", "state": "success", "sha": "abc", "sender": sender}
        assert relay.route("status", event, BOT, SKIP) == {"kind": "pr_review", "sha": "abc"}

    def test_workflow_run_started_by_a_bot(self):
        run = {"event": "pull_request", "head_sha": "def"}
        event = {"action": "completed", "workflow_run": run, "sender": _sender("dependabot[bot]", "Bot")}
        assert relay.route("workflow_run", event, BOT, SKIP)["kind"] == "pr_review"

    def test_bot_comment_is_skipped(self):
        event = {
            "action": "created",
            "issue": _issue(),
            "comment": _comment("can I work on this?", login="coderabbitai[bot]"),
            "sender": _sender("coderabbitai[bot]", "Bot"),
        }
        assert relay.route("issue_comment", event, BOT, SKIP)["kind"] is None

    def test_other_status_is_skipped(self):
        event = {"context": "Vercel – docs", "state": "failure", "sha": "abc", "sender": _sender("vercel")}
        assert relay.route("status", event, BOT, SKIP)["kind"] is None

    def test_workflow_run_from_pull_request(self):
        event = {"action": "completed", "workflow_run": {"event": "pull_request", "head_sha": "def"}, "sender": _sender()}
        assert relay.route("workflow_run", event, BOT, SKIP) == {"kind": "pr_review", "sha": "def"}

    def test_workflow_run_from_push_is_skipped(self):
        event = {"action": "completed", "workflow_run": {"event": "push", "head_sha": "def"}, "sender": _sender()}
        assert relay.route("workflow_run", event, BOT, SKIP)["kind"] is None


class TestFacts:
    def test_media(self):
        assert relay.has_media("![shot](https://github.com/user-attachments/assets/abc)")
        assert relay.has_media('<img src="x.png">')
        assert relay.has_media("demo: https://example.com/demo.gif")
        assert not relay.has_media("No screenshots, backend only.")

    def test_linked_issues(self):
        body = "Fixes #12. Closes https://github.com/arc53/DocsGPT/issues/34, related to #12"
        assert relay.linked_issues(body) == [12, 34]

    def test_link_domains_ignore_github(self):
        body = "See https://memcode.in/docs and https://github.com/x/y and https://memcode.in/pricing"
        assert relay.link_domains(body) == ["memcode.in"]

    def test_title_keywords_drop_template_prefix(self):
        assert relay.title_keywords("🐛 Bug Report: RstParser does not remove directives") == [
            "rstparser", "remove", "directives",
        ]

    def test_parse_marker_takes_last(self):
        body = (
            "<!-- docsgpt-triage sha=aaa ci=pending verdict=opened -->\n"
            "text\n<!-- docsgpt-triage sha=bbb ci=success verdict=ready -->"
        )
        assert relay.parse_marker(body) == {"sha": "bbb", "ci": "success", "verdict": "ready"}
        assert relay.parse_marker("no marker") is None

    def test_classify_paths(self):
        facts = relay.classify_paths(
            ["frontend/src/settings/Foo.tsx", "frontend/src/locale/en.json", "tests/test_x.py", "docsgpt/app.py"]
        )
        assert facts["areas"] == ["backend", "frontend", "tests"]
        assert facts["ui_changed"] is True
        assert facts["locales_touched"] == ["en"]
        assert facts["locales_missing"] == ["de", "es", "jp", "ru", "zh", "zh-TW"]

    def test_classify_paths_without_locales(self):
        assert relay.classify_paths(["docsgpt/app.py"])["locales_missing"] == []

    def test_dependency_changes(self):
        files = [
            {
                "filename": "pyproject.toml",
                "patch": '@@\n+    "torch>=2.4",\n-    "flask==3.0.0",\n+    "flask==3.1.0",\n+testpaths = ["tests"]',
            },
            {
                "filename": "frontend/package.json",
                "patch": '@@\n+    "lodash": "^4.17.21",\n+    "build": "vite build",\n+  "version": "1.2.0",',
            },
            {"filename": "README.md", "patch": '+    "requests>=2",'},
        ]
        result = relay.dependency_changes(files)
        assert result["added"] == [
            {"file": "pyproject.toml", "name": "torch", "spec": ">=2.4"},
            {"file": "frontend/package.json", "name": "lodash", "spec": "^4.17.21"},
        ]
        assert result["changed"] == [{"file": "pyproject.toml", "name": "flask", "from": "==3.0.0", "to": "==3.1.0"}]
        assert result["removed"] == []

    def test_new_settings(self):
        files = [
            {"filename": "docsgpt/core/settings/retrieval.py", "patch": "+    RRF_K: int = Field(default=60)\n+    x = 1"},
            {"filename": "docsgpt/app.py", "patch": "+    OTHER: int = 1"},
        ]
        assert relay.new_settings(files) == ["RRF_K"]

    def test_clean_bot_text(self):
        text = "<!-- hidden -->_⚠️ Potential issue_ | _🟠 Major_\n<details>long</details>\nFix it."
        assert relay.clean_bot_text(text) == "_⚠️ Potential issue_ | _🟠 Major_\n\nFix it."

    def test_truncate(self):
        assert relay.truncate("abc", 5) == "abc"
        assert relay.truncate("abcdef", 3).startswith("abc\n…[truncated, 3 more chars]")


class TestCiState:
    def test_awaiting_approval(self):
        runs = [{"name": "Python linting", "conclusion": "action_required"}]
        assert relay.ci_state([], runs, [])["state"] == "awaiting_approval"

    def test_failure_wins(self):
        checks = [
            {"name": "ruff", "status": "completed", "conclusion": "success"},
            {"name": "pytest", "status": "completed", "conclusion": "failure"},
        ]
        result = relay.ci_state(checks, [], [])
        assert result["state"] == "failure"
        assert result["failed"] == ["pytest"]

    def test_pending(self):
        checks = [{"name": "pytest", "status": "in_progress", "conclusion": None}]
        assert relay.ci_state(checks, [], [])["state"] == "pending"

    def test_vercel_coderabbit_and_labeler_ignored(self):
        checks = [{"name": "triage", "status": "completed", "conclusion": "success"}]
        statuses = [
            {"context": "Vercel – docs", "state": "failure"},
            {"context": "CodeRabbit", "state": "pending"},
        ]
        assert relay.ci_state(checks, [], statuses)["state"] == "none"

    def test_success(self):
        checks = [{"name": "pytest", "status": "completed", "conclusion": "success"}]
        assert relay.ci_state(checks, [], [{"context": "ci/other", "state": "success"}])["state"] == "success"


class TestRateLimit:
    def test_retry_after(self):
        assert relay.rate_limit_wait(403, {"Retry-After": "20"}) == 20

    def test_capped(self):
        assert relay.rate_limit_wait(429, {"Retry-After": "600"}) == 65

    def test_reset_header(self, monkeypatch):
        monkeypatch.setattr(relay.time, "time", lambda: 1000)
        headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1010"}
        assert relay.rate_limit_wait(403, headers) == 11

    def test_plain_forbidden_is_not_retried(self):
        assert relay.rate_limit_wait(403, {}) is None
        assert relay.rate_limit_wait(404, {"Retry-After": "5"}) is None


class TestReviewIsDue:
    def _facts(self, **overrides):
        facts = {
            "draft": False,
            "author": {"association": "NONE", "login": "dev"},
            "ci": {"state": "awaiting_approval"},
            "coderabbit": {"status": "success"},
            "head_sha": "abc123",
            "last_bot_review": None,
        }
        facts.update(overrides)
        return facts

    def test_due(self):
        assert relay.review_is_due(self._facts(), SKIP, BOT) is None

    def test_waits_for_running_checks(self):
        assert "running" in relay.review_is_due(self._facts(coderabbit={"status": "pending"}), SKIP, BOT)

    def test_skips_a_commit_already_reviewed(self):
        last = {"sha": "abc123", "ci": "awaiting_approval", "verdict": "changes_needed"}
        assert "already reviewed" in relay.review_is_due(self._facts(last_bot_review=last), SKIP, BOT)

    def test_reviews_again_when_ci_changes(self):
        last = {"sha": "abc123", "ci": "awaiting_approval", "verdict": "changes_needed"}
        assert relay.review_is_due(self._facts(last_bot_review=last, ci={"state": "success"}), SKIP, BOT) is None

    def test_quick_pass_comment_does_not_count_as_review(self):
        last = {"sha": "abc123", "ci": "awaiting_approval", "verdict": "opened"}
        assert relay.review_is_due(self._facts(last_bot_review=last), SKIP, BOT) is None

    def test_maintainer_pr_is_skipped(self):
        facts = self._facts(author={"association": "MEMBER", "login": "dartpain"})
        assert relay.review_is_due(facts, SKIP, BOT) is not None


class TestWriteJob:
    def test_writes_payload_and_job_line(self, tmp_path):
        out = tmp_path / "triage"
        first = relay.write_job(str(out), 0, "pr_review", 12, {"kind": "pr_review", "title": "Ünïcode"}, "pr-12-abc")
        relay.write_job(str(out), 1, "pr_review", 13, {"kind": "pr_review"}, "k" * 300)
        assert json.loads(Path(first).read_text(encoding="utf-8")) == {"kind": "pr_review", "title": "Ünïcode"}
        lines = (out / "jobs.tsv").read_text(encoding="utf-8").splitlines()
        assert lines[0] == f"pr-12-abc\t{first}"
        key, path = lines[1].split("\t")
        assert len(key) == 256
        assert path.endswith("01-pr_review-13.json")


class TestShaEvents:
    def test_workflow_run_uses_its_listed_pull_requests(self):
        run = {"event": "pull_request", "head_sha": "def", "pull_requests": [{"number": 5}, {"number": 6}]}
        event = {"action": "completed", "workflow_run": run, "sender": _sender()}
        assert relay.route("workflow_run", event, BOT, SKIP) == {"kind": "pr_review", "sha": "def", "numbers": [5, 6]}

    def test_only_prs_whose_head_is_the_event_sha_are_reviewed(self, monkeypatch):
        heads = {5: "def", 6: "other"}

        def facts(gh, number, bot):
            return {
                "number": number,
                "head_sha": heads[number],
                "draft": False,
                "author": {"association": "NONE", "login": "dev"},
                "ci": {"state": "success"},
                "coderabbit": {"status": "success"},
                "last_bot_review": None,
            }

        monkeypatch.setattr(relay, "pr_facts", facts)
        monkeypatch.setattr(relay, "prs_for_sha", lambda gh, sha: [5, 6])
        jobs = relay.jobs_for(None, {"kind": "pr_review", "sha": "def"}, {}, BOT, SKIP)
        assert [job[1]["number"] for job in jobs] == [5]


class TestMaintainers:
    def test_listed_login_with_private_membership(self):
        assert SKIP.includes("dartpain", "CONTRIBUTOR")
        assert SKIP.includes("ManishMadan2882", None)

    def test_association_counts_without_the_list(self):
        assert SKIP.includes("someone-new", "MEMBER")

    def test_contributor_is_not_a_maintainer(self):
        assert not SKIP.includes("someone-new", "CONTRIBUTOR")

    def test_list_from_env_is_case_insensitive(self):
        maintainers = relay.Maintainers.from_env(" Alice , bob ", "OWNER")
        assert maintainers.includes("alice") and maintainers.includes("BOB")
        assert not maintainers.includes("dartpain", "MEMBER")

    def test_claim_from_a_private_member_is_skipped(self):
        event = {
            "action": "created",
            "issue": _issue(),
            "comment": _comment("I'll take this", login="pabik", association="CONTRIBUTOR"),
            "sender": _sender("pabik"),
        }
        assert relay.route("issue_comment", event, BOT, SKIP)["kind"] is None

    def test_pull_request_from_a_private_member_is_skipped(self):
        pr = {"number": 5, "draft": False, "user": {"login": "dartpain", "type": "User"}, "author_association": "CONTRIBUTOR"}
        event = {"action": "opened", "pull_request": pr, "sender": _sender("dartpain")}
        assert relay.route("pull_request_target", event, BOT, SKIP)["kind"] is None

    def test_issue_opened_by_a_maintainer_is_still_triaged(self):
        event = {"action": "opened", "issue": _issue(user={"login": "dartpain", "type": "User"}), "sender": _sender("dartpain")}
        assert relay.route("issues", event, BOT, SKIP) == {"kind": "issue_opened", "number": 7}

    def test_review_skips_a_private_member(self):
        facts = {
            "draft": False,
            "author": {"association": "CONTRIBUTOR", "login": "dartpain"},
            "ci": {"state": "success"},
            "coderabbit": {"status": "success"},
            "head_sha": "abc",
            "last_bot_review": None,
        }
        assert relay.review_is_due(facts, SKIP, BOT) is not None

    def test_mark_maintainer(self):
        assert relay.mark_maintainer({"login": "dartpain", "association": "CONTRIBUTOR"}, SKIP)["is_maintainer"]
        assert not relay.mark_maintainer({"login": "dev", "association": "NONE"}, SKIP)["is_maintainer"]
