"""Tests for the Discussions answer script (.github/discussions/answer.py)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / ".github" / "discussions" / "answer.py"
_spec = importlib.util.spec_from_file_location("discussions_answer", SCRIPT_PATH)
answer = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = answer
_spec.loader.exec_module(answer)

MAINTAINERS = answer.Maintainers(logins=frozenset({"dartpain"}), associations=frozenset({"OWNER", "MEMBER"}))
BOT = "github-actions"


def user(login, typename="User"):
    return {"login": login, "__typename": typename}


def comment(node_id, login, body="text", association="NONE", typename="User", replies=()):
    return {
        "id": node_id,
        "body": body,
        "createdAt": "2026-10-01T10:00:00Z",
        "authorAssociation": association,
        "author": user(login, typename),
        "replies": {"nodes": list(replies)},
    }


def raw_discussion(comments=(), **overrides):
    raw = {
        "id": "D_1",
        "number": 12,
        "title": "How do I use Ollama?",
        "body": "I run Ollama locally. What do I set?",
        "url": "https://github.com/arc53/DocsGPT/discussions/12",
        "createdAt": "2026-10-01T09:00:00Z",
        "locked": False,
        "closed": False,
        "isAnswered": False,
        "authorAssociation": "NONE",
        "author": user("asker"),
        "category": {"slug": "q-a", "name": "Q&A"},
        "comments": {"nodes": list(comments)},
    }
    raw.update(overrides)
    return raw


def bot_answer(node_id="C_bot", replies=()):
    return comment(node_id, BOT, f"Set `LLM_PROVIDER`.\n\n<!-- {answer.MARKER} -->", typename="Bot", replies=replies)


def facts(raw):
    return answer.discussion_facts(raw, MAINTAINERS, BOT)


# --- Routing ------------------------------------------------------------------


def discussion_event(**overrides):
    event = {
        "action": "created",
        "discussion": {
            "number": 12,
            "category": {"slug": "q-a"},
            "user": {"login": "asker", "type": "User"},
            "author_association": "NONE",
        },
    }
    event["discussion"].update(overrides)
    return event


def test_route_new_question():
    job = answer.route("discussion", discussion_event(), MAINTAINERS, ("q-a", "general"))
    assert job == answer.Job(kind="discussion_created", number=12)


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": {"slug": "ideas"}},
        {"user": {"login": "dependabot[bot]", "type": "Bot"}},
        {"user": {"login": "dartpain", "type": "User"}},
        {"author_association": "MEMBER"},
    ],
)
def test_route_skips_other_categories_bots_and_maintainers(overrides):
    assert answer.route("discussion", discussion_event(**overrides), MAINTAINERS, ("q-a", "general")) is None


def test_route_follow_up_reply():
    event = discussion_event()
    event["comment"] = {"node_id": "C_reply", "parent_id": 99, "user": {"login": "asker", "type": "User"}}
    job = answer.route("discussion_comment", event, MAINTAINERS, ("q-a", "general"))
    assert job == answer.Job(kind="follow_up", number=12, comment_id="C_reply")


@pytest.mark.parametrize(
    "comment_overrides",
    [
        {"parent_id": None},  # a new top-level comment, not a reply to the bot
        {"user": {"login": "someone-else", "type": "User"}},
        {"user": {"login": "github-actions[bot]", "type": "Bot"}},
    ],
)
def test_route_skips_comments_that_are_not_the_author_replying(comment_overrides):
    event = discussion_event()
    event["comment"] = {"node_id": "C_reply", "parent_id": 99, "user": {"login": "asker", "type": "User"}}
    event["comment"].update(comment_overrides)
    assert answer.route("discussion_comment", event, MAINTAINERS, ("q-a", "general")) is None


def test_route_ignores_edits():
    assert answer.route("discussion", {**discussion_event(), "action": "edited"}, MAINTAINERS, ("q-a",)) is None


# --- Facts and eligibility ----------------------------------------------------


def test_facts_mark_bot_answers_and_maintainers():
    f = facts(raw_discussion([bot_answer(), comment("C_m", "dartpain", "Try this")]))
    assert [c["by_bot"] for c in f["comments"]] == [True, False]
    assert [c["author"]["is_maintainer"] for c in f["comments"]] == [False, True]
    assert f["author"]["login"] == "asker"


def test_marker_from_a_person_is_not_a_bot_answer():
    f = facts(raw_discussion([comment("C_x", "asker", f"<!-- {answer.MARKER} -->")]))
    assert f["comments"][0]["by_bot"] is False


def test_new_discussion_is_eligible():
    ok, reason, reply_to = answer.eligibility(facts(raw_discussion()), answer.Job("discussion_created", 12))
    assert (ok, reply_to) == (True, None)


@pytest.mark.parametrize(
    "raw",
    [
        raw_discussion(isAnswered=True),
        raw_discussion(locked=True),
        raw_discussion(closed=True),
        raw_discussion([bot_answer()]),
        raw_discussion([comment("C_m", "dartpain")]),
    ],
)
def test_new_discussion_skips(raw):
    ok, reason, _ = answer.eligibility(facts(raw), answer.Job("discussion_created", 12))
    assert not ok and reason


def test_follow_up_replies_in_the_bot_thread():
    reply = comment("C_reply", "asker", "That didn't work")
    f = facts(raw_discussion([bot_answer(replies=[reply])]))
    ok, _, reply_to = answer.eligibility(f, answer.Job("follow_up", 12, "C_reply"))
    assert (ok, reply_to) == (True, "C_bot")


def test_follow_up_outside_the_bot_thread_is_skipped():
    reply = comment("C_reply", "asker", "thanks")
    f = facts(raw_discussion([comment("C_other", "helper", replies=[reply])]))
    ok, _, _ = answer.eligibility(f, answer.Job("follow_up", 12, "C_reply"))
    assert not ok


def test_follow_up_stops_after_the_reply_limit():
    replies = []
    for i in range(answer.MAX_FOLLOW_UPS):
        replies.append(comment(f"C_q{i}", "asker", "still broken"))
        replies.append(comment(f"C_a{i}", BOT, f"Try again\n<!-- {answer.MARKER} -->", typename="Bot"))
    replies.append(comment("C_reply", "asker", "still broken"))
    f = facts(raw_discussion([bot_answer(replies=replies)]))
    ok, reason, _ = answer.eligibility(f, answer.Job("follow_up", 12, "C_reply"))
    assert not ok and "limit" in reason


def test_follow_up_skipped_once_a_maintainer_joined():
    replies = [comment("C_m", "dartpain", "Let me check"), comment("C_reply", "asker", "ok")]
    f = facts(raw_discussion([bot_answer(replies=replies)]))
    ok, _, _ = answer.eligibility(f, answer.Job("follow_up", 12, "C_reply"))
    assert not ok


# --- The agent's reply --------------------------------------------------------


def test_parse_reply_accepts_a_fenced_object():
    content = '```json\n{"decision": "answer", "confidence": 0.9, "answer": "Set X.", "reason": "docs"}\n```'
    assert answer.parse_reply(content)["decision"] == "answer"


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps({"decision": "maybe", "confidence": 1, "answer": "", "reason": ""}),
        json.dumps({"decision": "answer", "confidence": 0.9, "answer": "  ", "reason": ""}),
    ],
)
def test_parse_reply_rejects_bad_answers(content):
    with pytest.raises(answer.AnswerError):
        answer.parse_reply(content)


def test_check_answer_allows_project_links_and_code():
    text = (
        "Set `LLM_PROVIDER=openai` and `OPENAI_BASE_URL=http://localhost:11434/v1`, see "
        "[the docs](https://docs.docsgpt.cloud/Models/local-inference) and "
        "https://github.com/arc53/DocsGPT/blob/main/.env-template. Thanks @asker.\n\n"
        "```python\n@app.route('/x')\ndef x(): ...\n```"
    )
    assert answer.check_answer(text, "asker") == []


@pytest.mark.parametrize(
    "text, problem",
    [
        ("See https://example.com/buy-now", "link"),
        ("See [here](https://github.com/someone/other)", "link"),
        ("Ping @dartpain about it", "mention"),
        ("x" * (answer.ANSWER_LIMIT + 1), "long"),
        (f"<!-- {answer.MARKER} -->", "marker"),
    ],
)
def test_check_answer_holds_back_unsafe_text(text, problem):
    problems = answer.check_answer(text, "asker")
    assert any(problem in p for p in problems)


def test_render_comment_adds_footer_and_marker():
    body = answer.render_comment("Set X.")
    assert body.startswith("Set X.")
    assert body.rstrip().endswith(f"<!-- {answer.MARKER} -->")
    assert "Automated answer" in body


def test_build_message_carries_mode_and_thread():
    reply = comment("C_reply", "asker", "That didn't work")
    f = facts(raw_discussion([bot_answer(replies=[reply])]))
    message = json.loads(answer.build_message(f, answer.Job("follow_up", 12, "C_reply"), "shadow"))
    assert message["kind"] == "follow_up" and message["mode"] == "shadow"
    assert message["trigger"]["comment"]["body"] == "That didn't work"
    assert message["discussion"]["comments"][0]["by_bot"] is True


# --- Handling a discussion end to end -----------------------------------------


class FakeGitHub:
    def __init__(self, discussions):
        self.discussions = discussions
        self.posted = []

    def discussion(self, number):
        return self.discussions[number]

    def backlog(self, categories, max_age_days):
        return sorted(self.discussions)

    def add_comment(self, discussion_id, body, reply_to):
        self.posted.append((discussion_id, body, reply_to))
        return "https://github.com/arc53/DocsGPT/discussions/12#discussioncomment-1"


def agent_says(monkeypatch, reply):
    calls = []

    def fake(url, key, message, idempotency_key):
        calls.append(json.loads(message))
        return json.dumps(reply)

    monkeypatch.setattr(answer, "ask_agent", fake)
    return calls


ANSWER = {"decision": "answer", "confidence": 0.9, "answer": "Set `LLM_PROVIDER`.", "reason": "docs"}


def args(**overrides):
    defaults = {"dry_run": False, "url": "https://example.test", "backlog": False, "limit": 10}
    return answer.argparse.Namespace(**{**defaults, **overrides})


def test_handle_live_posts_the_answer(monkeypatch):
    gh = FakeGitHub({12: raw_discussion()})
    agent_says(monkeypatch, ANSWER)
    outcome = answer.handle(answer.Job("discussion_created", 12), gh, args(), "live", MAINTAINERS, BOT)
    assert outcome == "posted"
    assert gh.posted[0][0] == "D_1" and gh.posted[0][1].startswith("Set `LLM_PROVIDER`.")


def test_handle_shadow_posts_nothing(monkeypatch):
    gh = FakeGitHub({12: raw_discussion()})
    calls = agent_says(monkeypatch, ANSWER)
    outcome = answer.handle(answer.Job("discussion_created", 12), gh, args(), "shadow", MAINTAINERS, BOT)
    assert outcome == "done" and gh.posted == [] and calls[0]["mode"] == "shadow"


def test_handle_holds_back_an_unsafe_answer(monkeypatch):
    gh = FakeGitHub({12: raw_discussion()})
    agent_says(monkeypatch, {**ANSWER, "answer": "Buy at https://example.com"})
    outcome = answer.handle(answer.Job("discussion_created", 12), gh, args(), "live", MAINTAINERS, BOT)
    assert outcome == "failed" and gh.posted == []


def test_handle_skips_without_asking_the_agent(monkeypatch):
    gh = FakeGitHub({12: raw_discussion(isAnswered=True)})
    calls = agent_says(monkeypatch, ANSWER)
    outcome = answer.handle(answer.Job("manual", 12), gh, args(), "live", MAINTAINERS, BOT)
    assert outcome == "skipped" and calls == []


def test_backlog_limit_counts_only_agent_runs(monkeypatch):
    gh = FakeGitHub({1: raw_discussion(isAnswered=True), 2: raw_discussion(), 3: raw_discussion()})
    calls = agent_says(monkeypatch, ANSWER)
    monkeypatch.setattr(answer, "GitHub", lambda token, repo: gh)
    monkeypatch.setenv("DISCUSSIONS_MODE", "shadow")
    assert answer.main(["--backlog", "--limit", "1"]) == 0
    assert len(calls) == 1
