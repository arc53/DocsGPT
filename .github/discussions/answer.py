#!/usr/bin/env python3
"""Answer questions in GitHub Discussions with the DocsGPT discussions agent.

Collects a discussion and its comments, decides whether it should be answered
(a new question, or the author replying to the bot's answer), and asks the agent
through /v1/chat/completions. The agent searches the product docs, reads the
repository and reports to Telegram on the server; it answers with a JSON
decision. In live mode this script posts the answer, after checking its links
and mentions, with the workflow's GITHUB_TOKEN. Run by
.github/workflows/discussions.yml. Standard library only.

    python .github/discussions/answer.py                 # from a GitHub Actions event
    python .github/discussions/answer.py --number 1666 --dry-run
    python .github/discussions/answer.py --backlog --limit 5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

API = "https://api.github.com"
DEFAULT_REPO = "arc53/DocsGPT"
DEFAULT_URL = "https://gptcloud.arc53.com"
KEY_ENV = "DOCSGPT_DISCUSSIONS_AGENT_KEY"
DEFAULT_CATEGORIES = "q-a,general"
DEFAULT_BOT = "github-actions"
DEFAULT_MAINTAINERS = "dartpain,pabik,ManishMadan2882,siiddhantt,tenokami,arc53-machine"
MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
MODES = ("shadow", "live")
MARKER = "docsgpt-discussions"
FOOTER = "<sub>Automated answer from the DocsGPT docs. A maintainer will follow up if it doesn't solve this.</sub>"
# Bot replies to the author's follow-ups in one thread; after that a maintainer takes over.
MAX_FOLLOW_UPS = 2
AGENT_TIMEOUT = 600
BODY_LIMIT = 6000
COMMENT_LIMIT = 2000
ANSWER_LIMIT = 6000
# The cloud's firewall answers 403 to urllib's default User-Agent.
USER_AGENT = "docsgpt-discussions (+https://github.com/arc53/DocsGPT)"

DECISIONS = ("answer", "escalate", "skip")
URL_RE = re.compile(r"https?://[^\s)\]>\"'`<]+")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,}).*?^ {0,3}\1", re.DOTALL | re.MULTILINE)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
MENTION_RE = re.compile(r"(?<![\w/@.`])@([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))\b")
JSON_FENCE_RE = re.compile(r"\A\s*```(?:json)?\s*(.*?)\s*```\s*\Z", re.DOTALL)
# Hosts an answer may link to; github.com only under /arc53/.
ALLOWED_HOSTS = ("docsgpt.cloud", "docs.ac", "localhost", "127.0.0.1", "0.0.0.0")
GITHUB_HOSTS = ("github.com", "raw.githubusercontent.com")

DISCUSSION_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    discussion(number: $number) {
      id number title body url createdAt locked closed isAnswered authorAssociation
      author { login __typename }
      category { slug name }
      comments(first: 50) {
        nodes {
          id body createdAt authorAssociation author { login __typename }
          replies(first: 50) { nodes { id body createdAt authorAssociation author { login __typename } } }
        }
      }
    }
  }
}
"""

BACKLOG_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    discussions(first: 50, states: OPEN, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes { number createdAt isAnswered category { slug } }
    }
  }
}
"""

ADD_COMMENT = """
mutation($discussion: ID!, $body: String!, $replyTo: ID) {
  addDiscussionComment(input: {discussionId: $discussion, body: $body, replyToId: $replyTo}) {
    comment { url }
  }
}
"""


class AnswerError(Exception):
    """The agent could not be reached or its answer was unusable."""


@dataclass(frozen=True)
class Maintainers:
    logins: frozenset[str]
    associations: frozenset[str] = MAINTAINER_ASSOCIATIONS

    def includes(self, login: Optional[str], association: Optional[str]) -> bool:
        """True for a listed login or an association GitHub reports for members."""
        return (login or "").lower() in self.logins or (association or "") in self.associations

    @classmethod
    def from_env(cls) -> "Maintainers":
        raw = os.environ.get("DISCUSSIONS_MAINTAINERS") or DEFAULT_MAINTAINERS
        return cls(logins=frozenset(x.strip().lower() for x in raw.split(",") if x.strip()))


@dataclass(frozen=True)
class Job:
    kind: str  # discussion_created, follow_up or manual
    number: int
    comment_id: Optional[str] = None


def truncate(text: Optional[str], limit: int) -> str:
    """Trim text to ``limit`` characters, marking the cut."""
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


# --- Routing ------------------------------------------------------------------


def route(
    event_name: str, event: dict[str, Any], maintainers: Maintainers, categories: tuple[str, ...]
) -> Optional[Job]:
    """The job an Actions event asks for, or None to skip it."""
    discussion = event.get("discussion") or {}
    author = discussion.get("user") or {}
    if event.get("action") != "created" or (discussion.get("category") or {}).get("slug") not in categories:
        return None
    if author.get("type") == "Bot" or maintainers.includes(author.get("login"), discussion.get("author_association")):
        return None
    if event_name == "discussion":
        return Job("discussion_created", int(discussion["number"]))
    if event_name == "discussion_comment":
        comment = event.get("comment") or {}
        commenter = comment.get("user") or {}
        # Only the author replying inside a thread; eligibility() checks the thread is the bot's.
        if comment.get("parent_id") is None or commenter.get("type") == "Bot":
            return None
        if (commenter.get("login") or "").lower() != (author.get("login") or "").lower():
            return None
        return Job("follow_up", int(discussion["number"]), comment.get("node_id"))
    return None


# --- Facts --------------------------------------------------------------------


def _person(node: dict[str, Any], maintainers: Maintainers) -> dict[str, Any]:
    author = node.get("author") or {}
    login = author.get("login") or "ghost"
    return {
        "login": login,
        "is_maintainer": maintainers.includes(login, node.get("authorAssociation")),
        "is_bot": author.get("__typename") == "Bot",
    }


def _comment(node: dict[str, Any], maintainers: Maintainers, bot: str) -> dict[str, Any]:
    author = _person(node, maintainers)
    body = node.get("body") or ""
    return {
        "id": node.get("id"),
        "author": author,
        "created_at": node.get("createdAt"),
        "by_bot": author["login"].lower() == bot.lower() and MARKER in body,
        "body": truncate(body.replace(f"<!-- {MARKER} -->", ""), COMMENT_LIMIT),
    }


def discussion_facts(raw: dict[str, Any], maintainers: Maintainers, bot: str) -> dict[str, Any]:
    """The parts of a discussion the agent and the eligibility rules need."""
    comments = []
    for node in (raw.get("comments") or {}).get("nodes") or []:
        item = _comment(node, maintainers, bot)
        item["replies"] = [_comment(r, maintainers, bot) for r in (node.get("replies") or {}).get("nodes") or []]
        comments.append(item)
    return {
        "id": raw["id"],
        "number": raw["number"],
        "title": raw.get("title") or "",
        "body": truncate(raw.get("body"), BODY_LIMIT),
        "url": raw.get("url"),
        "category": (raw.get("category") or {}).get("slug"),
        "created_at": raw.get("createdAt"),
        "locked": bool(raw.get("locked")),
        "closed": bool(raw.get("closed")),
        "answered": bool(raw.get("isAnswered")),
        "author": _person(raw, maintainers),
        "comments": comments,
    }


def eligibility(facts: dict[str, Any], job: Job) -> tuple[bool, str, Optional[str]]:
    """Whether to answer: ``(ok, reason when not, comment id to reply under)``."""
    if facts["answered"] or facts["locked"] or facts["closed"]:
        return False, "already answered, locked or closed", None
    if facts["author"]["is_maintainer"] or facts["author"]["is_bot"]:
        return False, "opened by a maintainer or a bot", None
    everyone = [c for top in facts["comments"] for c in [top, *top["replies"]]]
    if any(c["author"]["is_maintainer"] for c in everyone):
        return False, "a maintainer has joined the discussion", None
    if job.kind != "follow_up":
        if any(c["by_bot"] for c in facts["comments"]):
            return False, "already has the bot's answer", None
        return True, "", None
    for top in facts["comments"]:
        ids = [r["id"] for r in top["replies"]]
        if job.comment_id not in ids:
            continue
        if not top["by_bot"]:
            return False, "the reply is not in the bot's thread", None
        if top["replies"][ids.index(job.comment_id)]["author"]["login"].lower() != facts["author"]["login"].lower():
            return False, "the reply is not from the discussion's author", None
        if sum(r["by_bot"] for r in top["replies"]) >= MAX_FOLLOW_UPS:
            return False, "reached the follow-up limit", None
        return True, "", top["id"]
    return False, "the reply was not found", None


def build_message(facts: dict[str, Any], job: Job, mode: str) -> str:
    """The JSON input for one agent run."""
    message: dict[str, Any] = {"kind": job.kind, "mode": mode, "discussion": facts}
    if job.comment_id:
        trigger = next(
            (r for top in facts["comments"] for r in top["replies"] if r["id"] == job.comment_id),
            None,
        )
        message["trigger"] = {"comment": trigger}
    return json.dumps(message, ensure_ascii=False)


# --- The agent's reply --------------------------------------------------------


def parse_reply(content: str) -> dict[str, Any]:
    """The agent's decision, validated."""
    match = JSON_FENCE_RE.match(content or "")
    try:
        data = json.loads(match.group(1) if match else content)
    except (TypeError, ValueError) as exc:
        raise AnswerError("The agent's answer is not JSON.") from exc
    if not isinstance(data, dict) or data.get("decision") not in DECISIONS:
        raise AnswerError("The agent's answer has no valid decision.")
    data["answer"] = (data.get("answer") or "").strip()
    if data["decision"] == "answer" and not data["answer"]:
        raise AnswerError("The agent decided to answer but wrote nothing.")
    return data


def _link_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url.rstrip(".,;:!?"))
    host = (parsed.hostname or "").lower()
    if host in GITHUB_HOSTS:
        return parsed.path.lower().startswith("/arc53/")
    return any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_HOSTS)


def check_answer(text: str, author: str) -> list[str]:
    """Reasons not to post an answer publicly; empty when it is fine."""
    problems = []
    if len(text) > ANSWER_LIMIT:
        problems.append(f"too long ({len(text)} characters)")
    if MARKER in text:
        problems.append("contains the bot's marker")
    bad_links = sorted({u for u in URL_RE.findall(text) if not _link_allowed(u)})
    if bad_links:
        hosts = sorted({urllib.parse.urlparse(u).hostname or u for u in bad_links})
        problems.append("link outside the allowed sites: " + ", ".join(hosts))
    prose = INLINE_CODE_RE.sub("", FENCE_RE.sub("", text))
    mentions = sorted({m for m in MENTION_RE.findall(prose) if m.lower() != author.lower()})
    if mentions:
        problems.append("mentions someone other than the author: " + ", ".join(mentions))
    return problems


def render_comment(text: str) -> str:
    """The comment body: the answer, the footer and the marker."""
    return f"{text.strip()}\n\n{FOOTER}\n<!-- {MARKER} -->\n"


# --- GitHub and the agent -----------------------------------------------------


class GitHub:
    """Minimal GitHub GraphQL client."""

    def __init__(self, token: Optional[str], repo: str) -> None:
        self.token = token
        self.owner, self.name = repo.split("/", 1)

    def graphql(self, query: str, **variables: Any) -> dict[str, Any]:
        """Run a GraphQL query and return its data."""
        headers = {"Content-Type": "application/json", "User-Agent": "docsgpt-discussions"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = json.dumps({"query": query, "variables": variables}).encode()
        request = urllib.request.Request(f"{API}/graphql", data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
        if data.get("errors"):
            raise RuntimeError(f"GitHub GraphQL error: {data['errors'][0].get('message')}")
        return data["data"]

    def discussion(self, number: int) -> dict[str, Any]:
        """One discussion with its comments and replies."""
        found = self.graphql(DISCUSSION_QUERY, owner=self.owner, name=self.name, number=number)
        return found["repository"]["discussion"]

    def backlog(self, categories: tuple[str, ...], max_age_days: int) -> list[int]:
        """Open, unanswered discussions in the categories, newest first."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        nodes = self.graphql(BACKLOG_QUERY, owner=self.owner, name=self.name)["repository"]["discussions"]["nodes"]
        return [
            n["number"]
            for n in nodes
            if (n.get("category") or {}).get("slug") in categories
            and not n.get("isAnswered")
            and datetime.fromisoformat(n["createdAt"].replace("Z", "+00:00")) >= cutoff
        ]

    def add_comment(self, discussion_id: str, body: str, reply_to: Optional[str]) -> str:
        """Post a comment, or a reply under ``reply_to``; return its URL."""
        data = self.graphql(ADD_COMMENT, discussion=discussion_id, body=body, replyTo=reply_to)
        return data["addDiscussionComment"]["comment"]["url"]


def ask_agent(url: str, key: Optional[str], message: str, idempotency_key: str) -> str:
    """Send one message to the agent and return its answer."""
    if not key:
        raise AnswerError(f"{KEY_ENV} is not set.")
    body = json.dumps({"model": "docsgpt", "messages": [{"role": "user", "content": message}], "stream": False})
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=body.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            # A rerun gets the earlier answer back instead of running the agent (and Telegram) again.
            "Idempotency-Key": idempotency_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=AGENT_TIMEOUT) as response:
            data = json.load(response)
        return data["choices"][0]["message"]["content"] or ""
    except urllib.error.HTTPError as exc:
        raise AnswerError(f"The agent answered HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AnswerError(f"The agent could not be reached ({exc}).") from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AnswerError("The agent's response has no message content.") from exc


# --- Main ---------------------------------------------------------------------


def jobs_from_args(
    args: argparse.Namespace, gh: GitHub, maintainers: Maintainers, categories: tuple[str, ...]
) -> list[Job]:
    """The jobs this run handles: one number, the backlog, or the Actions event."""
    if args.number:
        return [Job("manual", args.number)]
    if args.backlog:
        return [Job("manual", n) for n in gh.backlog(categories, args.max_age_days)]
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        raise SystemExit("Pass --number or --backlog, or run from a GitHub Actions event.")
    with open(path, encoding="utf-8") as fh:
        event = json.load(fh)
    job = route(os.environ.get("GITHUB_EVENT_NAME", ""), event, maintainers, categories)
    return [job] if job else []


def handle(job: Job, gh: GitHub, args: argparse.Namespace, mode: str, maintainers: Maintainers, bot: str) -> str:
    """Answer one discussion: ``skipped``, ``done`` (no post), ``posted`` or ``failed``."""
    facts = discussion_facts(gh.discussion(job.number), maintainers, bot)
    ok, reason, reply_to = eligibility(facts, job)
    if not ok:
        print(f"#{job.number}: skipped, {reason}.")
        return "skipped"
    message = build_message(facts, job, mode)
    if args.dry_run:
        print(message)
        return "done"
    key = f"discussion-{job.number}-{job.comment_id or 'new'}"
    try:
        reply = parse_reply(ask_agent(args.url, os.environ.get(KEY_ENV), message, key))
    except AnswerError as exc:
        print(f"::error::#{job.number}: {exc}")
        return "failed"
    # The answer itself stays out of this public log until it is posted.
    print(f"#{job.number}: the agent decided to {reply['decision']}.")
    if reply["decision"] != "answer" or mode != "live":
        return "done"
    problems = check_answer(reply["answer"], facts["author"]["login"])
    if problems:
        print(f"::error::#{job.number}: answer held back: {'; '.join(problems)}.")
        return "failed"
    print(f"#{job.number}: posted {gh.add_comment(facts['id'], render_comment(reply['answer']), reply_to)}")
    return "posted"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--number", type=int, help="answer this discussion")
    parser.add_argument("--backlog", action="store_true", help="answer the open, unanswered discussions")
    parser.add_argument("--max-age-days", type=int, default=365, help="with --backlog, skip older discussions")
    parser.add_argument("--limit", type=int, default=10, help="with --backlog, answer at most this many")
    parser.add_argument("--dry-run", action="store_true", help="print the agent's input, send nothing")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO)
    parser.add_argument("--url", default=os.environ.get("DOCSGPT_URL") or DEFAULT_URL)
    args = parser.parse_args(argv)

    mode = os.environ.get("DISCUSSIONS_MODE") or "shadow"
    if mode not in MODES:
        raise SystemExit(f"DISCUSSIONS_MODE must be one of {', '.join(MODES)}, not {mode!r}.")
    categories = tuple(c.strip() for c in (os.environ.get("DISCUSSIONS_CATEGORIES") or DEFAULT_CATEGORIES).split(","))
    maintainers = Maintainers.from_env()
    bot = os.environ.get("DISCUSSIONS_BOT_LOGIN") or DEFAULT_BOT
    gh = GitHub(os.environ.get("GITHUB_TOKEN"), args.repo)

    jobs = jobs_from_args(args, gh, maintainers, categories)
    if not jobs:
        print("Nothing to answer.")
    runs, failed = 0, False
    for job in jobs:
        if args.backlog and runs >= args.limit:
            break
        outcome = handle(job, gh, args, mode, maintainers, bot)
        failed |= outcome == "failed"
        runs += outcome != "skipped"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
