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


class _FakeGitHub:
    """Answers ``GET /pulls/<n>`` with the given author; nothing else is called."""

    def __init__(self, user: dict) -> None:
        self.user = user

    def get(self, path: str, **params) -> dict:
        assert path.startswith("/pulls/")
        return {"user": self.user}


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
        assert facts["locales_missing"] == ["de", "es", "fr", "jp", "ru", "zh", "zh-TW"]

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

    def test_secondary_limit_without_headers(self):
        body = b'{"message": "You have exceeded a secondary rate limit. Please wait a few minutes"}'
        assert relay.rate_limit_wait(403, {}, body) == relay.SECONDARY_LIMIT_WAIT

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
        human = _FakeGitHub({"login": "dev", "type": "User"})
        jobs = relay.jobs_for(human, {"kind": "pr_review", "sha": "def"}, {}, BOT, SKIP)
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


class TestBotAuthoredPullRequests:
    def test_ci_finishing_on_a_dependabot_pr_is_not_reviewed(self, monkeypatch):
        def facts(gh, number, bot):
            return {
                "number": number,
                "head_sha": "def",
                "draft": False,
                "author": {"association": "NONE", "login": "dependabot[bot]", "type": "Bot"},
                "ci": {"state": "success"},
                "coderabbit": {"status": "success"},
                "last_bot_review": None,
            }

        monkeypatch.setattr(relay, "pr_facts", facts)
        decision = {"kind": "pr_review", "sha": "def", "numbers": [9]}
        bot_author = _FakeGitHub({"login": "dependabot[bot]", "type": "Bot"})
        assert relay.jobs_for(bot_author, decision, {}, BOT, SKIP) == []
        # Facts already collected (a manual run) still keep a bot's PR out of automatic review.
        assert relay.review_is_due(facts(None, 9, BOT), SKIP, BOT) == "authored by a bot"

    def test_a_human_pr_from_the_same_event_is_reviewed(self, monkeypatch):
        def facts(gh, number, bot):
            return {
                "number": number,
                "head_sha": "def",
                "draft": False,
                "author": {"association": "NONE", "login": "dev", "type": "User"},
                "ci": {"state": "success"},
                "coderabbit": {"status": "success"},
                "last_bot_review": None,
            }

        monkeypatch.setattr(relay, "pr_facts", facts)
        decision = {"kind": "pr_review", "sha": "def", "numbers": [9]}
        human = _FakeGitHub({"login": "dev", "type": "User"})
        assert [job[1]["number"] for job in relay.jobs_for(human, decision, {}, BOT, SKIP)] == [9]

    def test_a_refused_search_counts_as_unknown(self):
        class Refusing:
            def count(self, query: str) -> int:
                raise relay.urllib.error.HTTPError("u", 422, "refused", {}, None)

        assert relay.count_or_none(Refusing(), "is:pr author:dependabot[bot]") is None

    def test_a_refused_optional_search_gives_no_items(self):
        class Refusing:
            def search(self, query: str, limit: int = 5) -> dict:
                raise relay.urllib.error.HTTPError("u", 403, "rate limited", {}, None)

        assert relay.search_items(Refusing(), "is:pr is:open bump", 6) == []
        assert relay.similar_items(Refusing(), 1, "Bump the uv group across directories") == []


def _claim_comment(login: str, number: int, at: str, body: str = "I would like to take this issue, please assign me") -> dict:
    return {
        "user": {"login": login},
        "html_url": f"https://github.com/arc53/DocsGPT/issues/{number}#issuecomment-1",
        "created_at": at,
        "body": body,
    }


class TestPendingClaims:
    # Three claims seconds apart, all triaged in parallel before any assignment lands.
    COMMENTS = [
        _claim_comment("sujal", 2902, "2026-10-02T14:44:50Z"),
        _claim_comment("sujal", 2908, "2026-10-02T14:44:55Z"),
        _claim_comment("sujal", 2911, "2026-10-02T14:44:58Z"),
        _claim_comment("someone", 2903, "2026-10-02T14:44:52Z"),
        _claim_comment("sujal", 2875, "2026-10-02T14:44:53Z").copy(),
    ]

    def setup_method(self) -> None:
        self.COMMENTS[-1]["html_url"] = "https://github.com/arc53/DocsGPT/pull/2875#issuecomment-2"

    def test_each_claim_counts_the_earlier_ones(self):
        first = relay.pending_claims(self.COMMENTS, "sujal", "2026-10-02T14:44:50Z", 2902, [])
        third = relay.pending_claims(self.COMMENTS, "sujal", "2026-10-02T14:44:58Z", 2911, [])
        assert first == []
        assert third == [2902, 2908]

    def test_claims_already_assigned_are_not_counted_twice(self):
        assert relay.pending_claims(self.COMMENTS, "sujal", "2026-10-02T14:44:58Z", 2911, [2902]) == [2908]

    def test_old_and_non_claim_comments_are_ignored(self):
        comments = [
            _claim_comment("sujal", 2800, "2026-10-02T13:00:00Z"),
            _claim_comment("sujal", 2801, "2026-10-02T14:40:00Z", body="Thanks, that worked"),
        ]
        assert relay.pending_claims(comments, "sujal", "2026-10-02T14:44:58Z", 2911, []) == []


class TestAssignedOpenIssues:
    def test_counts_issues_only_from_the_issues_api(self):
        class Pages:
            def pages(self, path: str, limit: int = 300, **params) -> list:
                assert path == "/issues" and params == {"assignee": "sujal", "state": "open"}
                return [{"number": 1}, {"number": 2, "pull_request": {}}, {"number": 3}]

        assert relay.assigned_open_issues(Pages(), "sujal") == [1, 3]

    def test_unavailable_is_none(self):
        class Refusing:
            def pages(self, path: str, limit: int = 300, **params) -> list:
                raise relay.urllib.error.HTTPError("u", 403, "rate limited", {}, None)

        assert relay.assigned_open_issues(Refusing(), "sujal") is None


class TestMentions:
    @pytest.mark.parametrize(
        "text",
        ["@arc53-machine can you check again?", "Thanks @Arc53-Machine.", "(@arc53-machine)", "cc @arc53-machine"],
    )
    def test_mentions(self, text):
        assert relay.mentions(text, BOT)

    @pytest.mark.parametrize("text", ["arc53-machine said so", "@arc53-machine-two", "mail me@arc53-machine", None])
    def test_not_mentions(self, text):
        assert not relay.mentions(text, BOT)

    def _event(self, body, login="someone", association="NONE", **issue):
        comment = _comment(body, login=login, association=association)
        return {"action": "created", "issue": _issue(**issue), "comment": comment, "sender": _sender(login)}

    def test_mention_on_a_pull_request(self):
        event = self._event("@arc53-machine Done, check again", pull_request={"url": "x"})
        assert relay.route("issue_comment", event, BOT, SKIP) == {"kind": "pr_mention", "number": 7, "comment_id": 99}

    def test_mention_on_an_issue(self):
        event = self._event("@arc53-machine is this still wanted?")
        assert relay.route("issue_comment", event, BOT, SKIP)["kind"] == "issue_mention"

    def test_mention_on_a_closed_issue(self):
        event = self._event("@arc53-machine why was this closed?", state="closed")
        assert relay.route("issue_comment", event, BOT, SKIP)["kind"] == "issue_mention"

    def test_mention_from_a_maintainer(self):
        event = self._event("@arc53-machine label this as a bug", login="dartpain")
        assert relay.route("issue_comment", event, BOT, SKIP)["kind"] == "issue_mention"

    def test_claim_that_mentions_the_bot_is_a_claim(self):
        event = self._event("Hey @arc53-machine, I'd like to work on this issue")
        assert relay.route("issue_comment", event, BOT, SKIP)["kind"] == "issue_claim"

    def test_bot_mentioning_itself_is_skipped(self):
        event = self._event("@arc53-machine", login=BOT)
        event["sender"] = _sender(BOT)
        assert relay.route("issue_comment", event, BOT, SKIP)["kind"] is None


class TestWillingToSubmitPr:
    @pytest.mark.parametrize(
        "body",
        [
            "### 🔗 Are you willing to submit PR?\n\nYes, I am willing to submit a PR!",
            "### Are you willing to submit PR?\n\nYes I am willing to submit a PR!",
        ],
    )
    def test_form_answers(self, body):
        assert relay.willing_to_submit_pr(body)

    @pytest.mark.parametrize("body", ["### 🔗 Are you willing to submit PR?\n\nNo", "", None])
    def test_no_answer(self, body):
        assert not relay.willing_to_submit_pr(body)


class _IssueGitHub:
    """Answers the calls ``issue_facts`` makes, for one issue."""

    def __init__(self, issue: dict, comments: list, timeline: list) -> None:
        self.issue, self.comments, self.timeline = issue, comments, timeline
        self.queries: list[str] = []

    def get(self, path: str, **params) -> dict:
        if path.startswith("users/"):
            return {"type": "User", "created_at": "2020-01-01T00:00:00Z"}
        return self.issue

    def pages(self, path: str, limit: int = 300, **params) -> list:
        if path.endswith("/comments"):
            return self.comments
        if path.endswith("/timeline"):
            return self.timeline
        return []

    def search(self, query: str, limit: int = 5) -> dict:
        self.queries.append(query)
        if "is:merged merged:>=" in query:
            return {"items": [{"number": 2837, "title": "isolate deploy tests", "state": "closed", "labels": []}]}
        return {"items": [], "total_count": 0}

    def count(self, query: str) -> int:
        return 0


class TestIssueFacts:
    def _issue(self, body):
        return {
            "number": 3067,
            "html_url": "https://github.com/arc53/DocsGPT/issues/3067",
            "title": "Idempotency lockout on manage_source_files",
            "state": "open",
            "body": body,
            "labels": [],
            "created_at": "2026-10-11T23:37:12Z",
            "updated_at": "2026-10-11T23:57:25Z",
            "user": {"login": "diya"},
            "author_association": "NONE",
            "assignees": [],
            "comments": 1,
        }

    def _claim(self, login, at, number=1):
        return {
            "id": number,
            "body": "I would love to work on this issue",
            "created_at": at,
            "author_association": "NONE",
            "user": {"login": login, "type": "User"},
        }

    def test_author_willing_to_submit_pr_claims_first(self):
        gh = _IssueGitHub(
            self._issue("Yes, I am willing to submit a PR!"), [self._claim("satanic", "2026-10-11T23:56:23Z")], []
        )
        facts = relay.issue_facts(gh, 3067, BOT, SKIP)
        assert facts["author_willing_to_submit_pr"] is True
        assert [c["login"] for c in facts["claimants"]] == ["diya", "satanic"]
        assert facts["claimants"][0] == {
            "login": "diya", "at": "2026-10-11T23:37:12Z", "comment_id": None, "source": "issue_form",
        }

    def test_author_who_also_comments_is_listed_once(self):
        gh = _IssueGitHub(
            self._issue("Yes, I am willing to submit a PR!"),
            [self._claim("satanic", "2026-10-11T23:56:23Z"), self._claim("diya", "2026-10-12T03:09:27Z", 2)],
            [],
        )
        assert [c["login"] for c in relay.issue_facts(gh, 3067, BOT, SKIP)["claimants"]] == ["diya", "satanic"]

    def test_author_not_willing_has_no_claim(self):
        gh = _IssueGitHub(self._issue("No"), [self._claim("satanic", "2026-10-11T23:56:23Z")], [])
        facts = relay.issue_facts(gh, 3067, BOT, SKIP)
        assert facts["author_willing_to_submit_pr"] is False
        assert [c["login"] for c in facts["claimants"]] == ["satanic"]

    def test_maintainer_author_is_never_a_claimant(self):
        issue = self._issue("Yes, I am willing to submit a PR!")
        issue["user"] = {"login": "dartpain"}
        assert relay.issue_facts(_IssueGitHub(issue, [], []), 3067, BOT, SKIP)["claimants"] == []

    def test_merged_prs_that_fix_it(self):
        timeline = [
            {
                "event": "cross-referenced",
                "source": {
                    "issue": {
                        "number": 3070,
                        "title": "fix(sources): prevent idempotency lockout",
                        "state": "closed",
                        "user": {"login": "satanic"},
                        "pull_request": {"merged_at": "2026-10-12T05:00:00Z"},
                    }
                },
            }
        ]
        gh = _IssueGitHub(self._issue("No"), [], timeline)
        facts = relay.issue_facts(gh, 3067, BOT, SKIP)
        assert facts["merged_prs_referencing"] == [
            {"number": 3070, "title": "fix(sources): prevent idempotency lockout", "merged_at": "2026-10-12T05:00:00Z"}
        ]
        assert facts["open_prs_referencing"] == []
        assert [pr["number"] for pr in facts["similar_merged_prs"]] == [2837]
        assert any(q.startswith("is:pr is:merged merged:>=") for q in gh.queries)


class _CompareGitHub:
    """Answers ``/compare`` calls from a parent map and the set of commits on the base branch."""

    def __init__(self, parents: dict, on_base: set, status: str = "ahead") -> None:
        self.parents, self.on_base, self.status = parents, on_base, status

    def get(self, path: str, **params) -> dict:
        left, right = path.removeprefix("/compare/").split("...")
        if left == "main":
            return {"status": "behind" if right in self.on_base else "diverged"}
        commits = [{"sha": sha, "parents": [{"sha": p} for p in ps]} for sha, ps in self.parents.items()]
        return {"status": self.status, "commits": commits}


class TestBaseMergesOnly:
    # PR chain: reviewed -> m1 (merges main1) -> m2 (merges main2); main1/main2 came in from main.
    PARENTS = {"main1": ["main0"], "main2": ["main1"], "m1": ["reviewed", "main1"], "m2": ["m1", "main2"]}

    def test_only_merges_of_the_base_branch(self):
        gh = _CompareGitHub(self.PARENTS, {"main1", "main2"})
        assert relay.base_merges_only(gh, "reviewed", "m2", "main")

    def test_a_commit_of_the_pr_own(self):
        parents = {**self.PARENTS, "fix": ["m2"]}
        assert not relay.base_merges_only(_CompareGitHub(parents, {"main1", "main2"}), "reviewed", "fix", "main")

    def test_a_merge_of_another_branch(self):
        assert not relay.base_merges_only(_CompareGitHub(self.PARENTS, {"main1"}), "reviewed", "m2", "main")

    def test_rewritten_history(self):
        gh = _CompareGitHub(self.PARENTS, {"main1", "main2"}, status="diverged")
        assert not relay.base_merges_only(gh, "reviewed", "m2", "main")

    def test_compare_refused(self):
        class Refusing:
            def get(self, path: str, **params) -> dict:
                raise relay.urllib.error.HTTPError("u", 404, "not found", {}, None)

        assert not relay.base_merges_only(Refusing(), "reviewed", "m2", "main")

    def test_review_is_skipped_after_base_merges(self):
        facts = {
            "draft": False,
            "author": {"association": "NONE", "login": "dev"},
            "ci": {"state": "awaiting_approval"},
            "coderabbit": {"status": "success"},
            "head_sha": "m2",
            "base": "main",
            "last_bot_review": {"sha": "reviewed", "ci": "awaiting_approval", "verdict": "ready"},
            "base_merges_only_since_review": True,
        }
        assert "only main merged in" in relay.review_is_due(facts, SKIP, BOT)


class TestPrMentionJob:
    def test_mention_job_carries_the_comment(self, monkeypatch):
        def pr_facts(gh, number, bot):
            return {"number": number, "author": {"login": "dev", "association": "NONE"}}

        def author_facts(gh, login, association):
            return {"login": login, "association": association}

        monkeypatch.setattr(relay, "pr_facts", pr_facts)
        monkeypatch.setattr(relay, "author_facts", author_facts)

        class Comments:
            def get(self, path: str, **params) -> dict:
                assert path == "/issues/comments/99"
                return _comment("@arc53-machine Done", login="dev") | {"created_at": "2026-10-06T20:21:37Z"}

        decision = {"kind": "pr_mention", "number": 3009, "comment_id": 99}
        [(kind, facts, key, trigger)] = relay.jobs_for(Comments(), decision, {}, BOT, SKIP)
        assert (kind, facts["number"], key) == ("pr_mention", 3009, "pr-3009-pr_mention-99")
        assert trigger["comment"]["body"] == "@arc53-machine Done"
        assert trigger["commenter"]["is_maintainer"] is False
